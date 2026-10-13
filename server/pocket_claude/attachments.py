"""Anhang-Aufbereitung fuer den Prompt.

Frueher lag das direkt in `claude_engine.py`. Seit es neben Claude auch die
Zusatz-Modelle (Gemini/GPT ueber `openai_engine.py`) gibt, brauchen beide
Engines dieselbe Heuristik: welcher Anhang gehoert als Text inline in den
Prompt, und welcher ist binaer und wird nur referenziert.

Das Verhalten ist unveraendert gegenueber der frueheren Fassung in
`claude_engine.py`. Die oeffentlichen Namen heissen ohne Unterstrich
(`looks_like_text`, `build_prompt_text`, `has_binary_attachments`); die alten
Namen bleiben in `claude_engine` als Alias bestehen.
"""
from __future__ import annotations

import base64
import logging
from pathlib import Path

log = logging.getLogger(__name__)


MAX_TEXT_ATTACHMENT_BYTES = 200_000

# Bilder bekommt Claude direkt in die Nachricht, nicht als Pfad fuer das
# Read-Werkzeug. Ueber das Werkzeug hing es am Modell, ob es den Anhang
# ueberhaupt oeffnet: in einem langen Chat, in dem es vorher kein Read hatte,
# antwortete Claude trotz Bild, sein Werkzeug zum Lesen von Dateien sei
# deaktiviert. Die API nimmt hoechstens 5 MB base64 je Bild, das sind 3,75 MB
# Rohdaten; groessere Bilder gehen weiter ueber Read, das selbst verkleinert.
MAX_INLINE_IMAGE_BYTES = 3_750_000

_TEXT_MIME_PREFIXES = ("text/",)
_TEXT_MIME_TYPES = {
    # Universale Daten-/Konfig-Formate
    "application/json", "application/ld+json",
    "application/xml", "application/atom+xml", "application/rss+xml",
    "application/yaml", "application/x-yaml",
    "application/toml",
    "application/x-www-form-urlencoded",
    # Skript-/Source-Sprachen, die manchmal als application/* kommen
    "application/javascript", "application/ecmascript",
    "application/typescript",
    "application/x-shellscript", "application/x-sh",
    "application/x-python", "application/x-python-code",
    "application/x-ruby", "application/x-perl",
    "application/x-php",
    "application/sql",
    # Klassische plain-text Container ohne text/-Prefix
    "application/csv",
    "application/x-tex", "application/x-latex",
    "application/x-makefile",
}
_TEXT_EXTENSIONS = {
    # Klassiker
    ".md", ".markdown", ".txt", ".log", ".rst", ".adoc",
    # Daten
    ".json", ".jsonl", ".ndjson", ".yaml", ".yml", ".xml",
    ".csv", ".tsv", ".tab", ".toml", ".ini", ".cfg", ".conf", ".env",
    ".properties", ".plist", ".lock",
    # Web
    ".html", ".htm", ".css", ".scss", ".sass", ".less",
    ".vue", ".svelte", ".astro",
    # JS-Welt
    ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx",
    # Python-Welt
    ".py", ".pyx", ".pyi", ".ipynb",
    # JVM-Welt
    ".kt", ".kts", ".java", ".scala", ".groovy", ".clj", ".cljc", ".cljs",
    ".gradle",
    # Native + System
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".hxx",
    ".rs", ".go", ".swift", ".m", ".mm",
    ".zig", ".nim", ".v", ".d",
    # Skript-Sprachen
    ".rb", ".pl", ".pm", ".php", ".lua", ".r", ".jl",
    ".sh", ".zsh", ".bash", ".fish", ".ps1", ".bat", ".cmd",
    # Funktional / ML
    ".ex", ".exs", ".erl", ".hrl", ".hs", ".ml", ".mli", ".elm", ".fs", ".fsi",
    # Dart / Flutter / sonstige
    ".dart",
    # DB / Query
    ".sql", ".graphql", ".gql", ".proto",
    # DevOps
    ".tf", ".tfvars", ".hcl", ".nomad", ".nix",
    # Sonstiges Text-Heavy
    ".tex", ".bib", ".diff", ".patch", ".srt", ".vtt",
}

# Files OHNE Punkt-Extension, die per Konvention reiner Text sind.
_TEXT_FILENAMES = {
    "dockerfile", "containerfile",
    "makefile", "gnumakefile",
    "rakefile", "gemfile", "procfile", "vagrantfile",
    "license", "licence", "copying", "readme", "changelog", "authors",
    "todo", "notes",
    ".gitignore", ".gitattributes", ".dockerignore", ".editorconfig",
    ".prettierrc", ".eslintrc", ".babelrc",
}


def looks_like_text(filename: str, mime: str) -> bool:
    """Heuristik: gehört der Anhang inline in den Prompt-Text, oder soll er
    nur per Read-Tool referenziert werden?

    Reihenfolge:
      1. MIME-Prefix text/* → ja
      2. MIME aus expliziter Allowlist → ja
      3. Filename-Extension in der Allowlist → ja
      4. Filename selbst (ohne Punkt) in der Konventions-Liste → ja
      5. sonst nein (= Binär, per Read-Tool)
    """
    if any(mime.startswith(p) for p in _TEXT_MIME_PREFIXES):
        return True
    if mime in _TEXT_MIME_TYPES:
        return True
    lower = filename.lower()
    if any(lower.endswith(ext) for ext in _TEXT_EXTENSIONS):
        return True
    # Punkt-loser Filename (z.B. „Dockerfile", „Makefile") → letztes Path-Segment
    base = lower.rsplit("/", 1)[-1]
    if base in _TEXT_FILENAMES:
        return True
    return False


def _bildformat(head: bytes) -> str | None:
    """Mimetyp an den ersten Bytes, nur Formate, die Claude direkt liest."""
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if head[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def inline_images(
    attach_ids: list[str], attachments_by_id: dict[str, dict]
) -> tuple[list[dict], set[str]]:
    """Bild-Anhaenge als Inhaltsbloecke fuer die Nachricht an Claude.

    Liefert die Bloecke und die IDs, die damit erledigt sind. Alles andere
    (PDF, HEIC, zu gross, Datei fehlt) bleibt beim Read-Werkzeug.
    """
    blocks: list[dict] = []
    ids: set[str] = set()
    for aid in attach_ids:
        a = attachments_by_id.get(aid)
        if not a or aid in ids or looks_like_text(a["filename"], a["mime_type"] or ""):
            continue
        path = Path(a["path"])
        try:
            if not path.is_file() or path.stat().st_size > MAX_INLINE_IMAGE_BYTES:
                continue
            raw = path.read_bytes()
        except OSError as exc:
            log.warning("Bild %s nicht lesbar: %s", a["filename"], exc)
            continue
        mime = _bildformat(raw[:12])
        if not mime:
            continue
        blocks.append({"type": "image", "source": {
            "type": "base64", "media_type": mime,
            "data": base64.b64encode(raw).decode("ascii")}})
        ids.add(aid)
    return blocks, ids


def build_prompt_text(user_msg: dict, attachments_by_id: dict[str, dict],
                      inline_ids: set[str] = frozenset()) -> str:
    content = user_msg["content"] or ""
    attach_ids = user_msg.get("attachment_ids") or []
    if not attach_ids:
        return content
    parts: list[str] = []
    if content.strip():
        parts.append(content.strip())
    for aid in attach_ids:
        a = attachments_by_id.get(aid)
        if not a:
            parts.append(f"\n\n[Anhang {aid} unauffindbar.]")
            continue
        filename = a["filename"]
        mime = a["mime_type"] or "application/octet-stream"
        path = Path(a["path"])
        if not path.exists():
            parts.append(f"\n\n[Anhang '{filename}' fehlt auf dem Server.]")
            continue
        if aid in inline_ids:
            parts.append(f"\n\n[Bild '{filename}' ist dieser Nachricht direkt beigefuegt.]")
            continue
        if looks_like_text(filename, mime):
            try:
                raw = path.read_bytes()
                truncated = False
                if len(raw) > MAX_TEXT_ATTACHMENT_BYTES:
                    raw = raw[:MAX_TEXT_ATTACHMENT_BYTES]
                    truncated = True
                text = raw.decode("utf-8", errors="replace")
                fence = "```"
                if fence in text:
                    fence = "````"
                trunc_note = "\n\n…[gekürzt]" if truncated else ""
                parts.append(
                    f"\n\n--- Anhang: **{filename}** "
                    f"({mime}, {a['size_bytes']} Bytes) ---\n"
                    f"{fence}\n{text}{trunc_note}\n{fence}\n--- Ende Anhang ---"
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("Anhang %s nicht als Text lesbar: %s", filename, exc)
                parts.append(f"\n\n[Anhang '{filename}' konnte nicht gelesen werden: {exc}]")
        else:
            abs_path = path.resolve()
            parts.append(
                f"\n\n--- Anhang: **{filename}** ({mime}, {a['size_bytes']} Bytes) ---\n"
                f"Bitte lies die Datei mit dem `Read`-Tool — absoluter Pfad:\n"
                f"`{abs_path}`\n"
                f"--- Ende Anhang ---"
            )
    return "".join(parts)


def has_binary_attachments(
    attach_ids: list[str], attachments_by_id: dict[str, dict],
    inline_ids: set[str] = frozenset(),
) -> bool:
    for aid in attach_ids:
        a = attachments_by_id.get(aid)
        if not a or aid in inline_ids:
            continue
        if not looks_like_text(a["filename"], a["mime_type"]):
            return True
    return False
