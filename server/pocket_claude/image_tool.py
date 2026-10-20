"""Tool-Definition und Ausfuehrung fuer die Bildgenerierung (generate_image).

Wird sowohl im Claude-Pfad (via In-Process MCP) als auch im Gateway-Pfad
(OpenAI-kompatible Tool Calls) verwendet.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
from typing import Any

from pocket_claude import db, image_engine
from pocket_claude.config import settings

log = logging.getLogger(__name__)

TOOL_NAME = "generate_image"

TOOL_DESCRIPTION = (
    "Erzeugt ein Bild aus einer Bildbeschreibung und zeigt es direkt im Chat. "
    "Nutze das Werkzeug, wenn der Nutzer ein Bild, eine Illustration, ein Logo, "
    "ein Icon oder eine Grafik moechte. Die Beschreibung sollte ausfuehrlich "
    "und auf Englisch sein, das liefert bessere Ergebnisse."
)

# Die Aufloesung steht bewusst NICHT im Schema: sie ist eine Nutzer-Einstellung
# (Einstellungen, Abschnitt Bilder), keine Entscheidung des Modells. Sonst
# wuerde jedes Modell nach Lust und Laune eine andere Groesse waehlen und die
# eingestellte Vorgabe waere wertlos. Seitenverhaeltnis und Anzahl darf das
# Modell dagegen selbst waehlen, das haengt am Bildinhalt.
PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "prompt": {
            "type": "string",
            "description": (
                "Ausfuehrliche Bildbeschreibung, am besten auf Englisch: Motiv, "
                "Stil, Licht, Perspektive, Hintergrund."
            ),
        },
        "aspect_ratio": {
            "type": "string",
            "enum": ["1:1", "16:9", "9:16", "4:3", "3:4"],
            "description": "Seitenverhaeltnis. Ohne Angabe gilt die Nutzer-Vorgabe.",
        },
        "count": {
            "type": "integer",
            "minimum": 1,
            "maximum": 4,
            "description": "Anzahl Varianten. Ohne Angabe eine.",
        },
        "edit_attached_images": {
            "type": "boolean",
            "description": (
                "Auf true setzen, wenn ein vorhandenes Bild GEAENDERT werden "
                "soll, statt ein neues zu zeichnen: die Bilder, die der Nutzer "
                "gerade mitschickt, oder ohne Anhang das zuletzt im Chat "
                "gezeigte Bild (auch ein eben erzeugtes, etwa bei 'mach den "
                "Himmel dunkler'). Die Beschreibung sagt dann nur, was sich "
                "aendern soll. Ohne Bild im Gespraech wirkungslos."
            ),
        },
    },
    "required": ["prompt"],
}

# Anweisung fuer eine Nachricht, bei der der Nutzer im Plus-Menue "Bild
# erstellen" gewaehlt hat. Sie haengt nur am laufenden Turn und landet nicht
# in der Datenbank.
WISH_HINT = (
    "[Hinweis der App: Der Nutzer hat fuer diese Nachricht \"Bild erstellen\" "
    "gewaehlt. Rufe das Werkzeug generate_image auf, auch wenn die Nachricht "
    "kurz oder mehrdeutig ist, und nutze den bisherigen Verlauf fuer eine "
    "ausfuehrliche Bildbeschreibung. Bezieht sich die Nachricht auf ein "
    "vorhandenes Bild, setze edit_attached_images. Frage nicht zurueck.]"
)


async def store_images(images: list[image_engine.GeneratedImage], user_id: str) -> list[dict]:
    """Speichert generierte Bilder auf der Festplatte und registriert sie in der DB.

    Uebernommen aus der Endpoint-Logik von server.py:
    - Zufalls-Dateiname mit secrets.token_urlsafe(10)
    - Dateiendung aus mime_type
    - Speicherung im konfigurierten uploads_dir (via asyncio.to_thread)
    - Attachment-Eintrag in der Datenbank

    Rueckgabe je Bild: dict mit id, filename, mime_type, size_bytes, text.
    """
    out_atts: list[dict] = []
    for img in images:
        ext = "png" if "png" in img.mime_type else (img.mime_type.split("/")[-1] or "bin")
        disk_name = f"img_{secrets.token_urlsafe(10)}.{ext}"
        target = settings.uploads_dir / disk_name
        await asyncio.to_thread(target.write_bytes, img.data)
        # Der Anbieter gehoert in den Dateinamen: im Modus "beide" haengen zwei
        # Bilder nebeneinander, und ohne Namen sieht man nicht, welches von wem
        # ist. Ohne Angabe bleibt es beim neutralen "bild".
        quelle = img.provider or "bild"
        filename = f"{quelle}-{img.index + 1}.{ext}"
        aid = await db.add_attachment(
            filename=filename,
            mime_type=img.mime_type,
            size_bytes=len(img.data),
            path=target,
            user_id=user_id,
        )
        out_atts.append({
            "id": aid,
            "filename": filename,
            "mime_type": img.mime_type,
            "size_bytes": len(img.data),
            "text": img.text,
        })
    return out_atts


async def _load_references(
    attachment_ids: list[str], user_id: str,
) -> list[image_engine.ReferenceImage]:
    """Laedt die Bilder einer Nachricht als Vorlagen.

    Alles, was sich nicht laden laesst oder kein brauchbares Bild ist, wird
    still uebersprungen: ein kaputter Anhang darf die Bilderzeugung nicht
    kippen, und schon gar nicht den ganzen Chat-Turn. Deshalb faengt diese
    Funktion JEDEN Fehler ab, auch unerwartete wie eine Datenbankzeile ohne
    Pfad.

    Die Anzahl wird erst am Ende begrenzt, nicht vorher: sonst wuerden vier
    Textdokumente am Anfang der Nachricht die Bilder dahinter verdraengen.
    """
    from pathlib import Path

    raw: list[tuple[str, bytes]] = []
    for aid in attachment_ids:
        if len(raw) >= image_engine.MAX_REFERENCE_IMAGES:
            break
        try:
            att = await db.get_attachment(aid, user_id=user_id)
            if not att:
                continue
            mime = str(att.get("mime_type") or "").lower()
            if not mime.startswith("image/"):
                continue
            path = att.get("path")
            if not path:
                continue
            data = await asyncio.to_thread(Path(str(path)).read_bytes)
        except Exception as exc:  # noqa: BLE001 - siehe Docstring
            log.warning("PC_IMG: Vorlage %s uebersprungen: %s: %s",
                        aid, type(exc).__name__, exc)
            continue
        raw.append((mime, data))

    return image_engine.usable_references(raw)


async def previous_image_ids(cid: str, before_message_id: int | None = None) -> list[str]:
    """Die Bild-Anhaenge der juengsten Nachricht im Chat, die Bilder traegt.

    Egal ob erzeugt (Antwort) oder hochgeladen (Frage): gemeint ist das Bild,
    das der Nutzer zuletzt gesehen hat. Fehler liefern eine leere Liste, die
    Vorlage ist nur ein Komfort und darf den Turn nie kippen.
    """
    try:
        msgs = await db.list_messages(cid)
        for m in reversed(msgs):
            if before_message_id is not None and m["id"] >= before_message_id:
                continue
            ids = m.get("attachment_ids") or []
            if not ids:
                continue
            atts = await db.get_attachments(ids)
            bilder = [a["id"] for a in atts
                      if str(a.get("mime_type") or "").lower().startswith("image/")]
            if bilder:
                return bilder
    except Exception as exc:  # noqa: BLE001 - siehe Docstring
        log.warning("PC_IMG: letztes Bild nicht ermittelbar: %s: %s", type(exc).__name__, exc)
    return []


async def run(user_id: str, args: dict, defaults: dict | None = None) -> dict:
    """Fuehrt die Bildgenerierung fuer das Tool aus und speichert die Ergebnisse.

    Prioritaet: args vor defaults vor Modul-Defaults.
    Rueckgabe: {"ok": bool, "attachments": [...], "text": str}
    """
    defaults = defaults or {}

    prompt = (args.get("prompt") or "").strip()
    if not prompt:
        return {
            "ok": False,
            "attachments": [],
            "text": "Kein Prompt fuer die Bildgenerierung angegeben.",
        }

    aspect_ratio = (
        args.get("aspect_ratio")
        or defaults.get("aspect_ratio")
        or defaults.get("image_default_aspect")
        or "1:1"
    )
    # Aufloesung kommt IMMER aus den Nutzer-Einstellungen, nie vom Modell.
    size = (
        defaults.get("size")
        or defaults.get("image_default_size")
        or image_engine.DEFAULT_IMAGE_SIZE
    )
    model = (
        args.get("model")
        or defaults.get("model")
        or defaults.get("image_default_model")
        or None
    )

    try:
        raw_count = args.get("count") if args.get("count") is not None else defaults.get("count")
        count_val = int(raw_count) if raw_count is not None else 1
    except (TypeError, ValueError):
        count_val = 1

    # Anbieter: Nutzer-Vorgabe, sonst richtet sich das Bild nach dem Modell,
    # das gerade antwortet. Ein GPT-Chat zeichnet dann mit gpt-image-2, ein
    # Gemini-Chat mit dem Gemini-Bildmodell.
    provider = image_engine.canonical_provider(
        defaults.get("provider") or defaults.get("image_provider")
    )
    family_hint = defaults.get("family_hint") or ""

    # Bearbeiten statt neu zeichnen: das Modell entscheidet anhand der Frage,
    # ob die mitgeschickten Bilder Vorlage sein sollen. `_load_references`
    # faengt selbst alles ab und liefert im Zweifel eine leere Liste; dann wird
    # eben neu gezeichnet statt bearbeitet.
    # Ohne eigenen Bild-Anhang ist das zuletzt im Chat gezeigte Bild gemeint:
    # "mach den Himmel abendlich" soll das eben erzeugte Bild aendern, nicht
    # ein neues Motiv zeichnen.
    references: list[image_engine.ReferenceImage] = []
    if args.get("edit_attached_images"):
        references = await _load_references(
            defaults.get("attachment_ids") or [], user_id,
        )
        if not references and defaults.get("previous_image_ids"):
            references = await _load_references(defaults["previous_image_ids"], user_id)
            if references:
                log.info("PC_IMG: Vorlage ist das letzte Bild im Chat (%d)", len(references))
        if not references:
            log.info("PC_IMG: Bearbeiten gewuenscht, aber kein brauchbares Bild dabei")

    # Kein Schluessel mehr noetig: die Bilder entstehen ueber die Gateways und
    # damit ueber Konten, die ohnehin bezahlt sind.
    try:
        images = await image_engine.generate(
            prompt=prompt,
            provider=provider,
            family_hint=family_hint,
            model=model,
            aspect_ratio=aspect_ratio,
            image_size=size,
            count=count_val,
            references=references or None,
        )
    except image_engine.ImageGenError as e:
        return {
            "ok": False,
            "attachments": [],
            "text": f"Fehler bei der Bildgenerierung: {e}",
        }
    except Exception as e:
        log.exception("Unerwarteter Fehler bei generate_image")
        return {
            "ok": False,
            "attachments": [],
            "text": f"Unerwarteter Fehler bei der Bildgenerierung: {e}",
        }

    # Speichern kann auch schiefgehen (Platte voll, Verzeichnis nicht
    # beschreibbar, DB-Fehler). Das darf NICHT als Exception aus dem Werkzeug
    # herausfallen, sonst kippt der ganze Chat-Turn.
    try:
        attachments = await store_images(images, user_id=user_id)
    except Exception as e:  # noqa: BLE001
        log.exception("Bilder konnten nicht gespeichert werden")
        return {
            "ok": False,
            "attachments": [],
            "text": f"Die Bilder konnten nicht gespeichert werden: {e}",
        }

    # Kurz halten: der Nutzer sieht das Bild, eine Beschreibung davon oder ein
    # Absatz mit Varianten-Angeboten ist nur Lesestoff ohne Nutzen.
    count_done = len(attachments)
    if count_done == 1:
        summary = (
            "1 Bild wurde erfolgreich generiert und dem Nutzer bereits im Chat angezeigt. "
            "Erfinde keinen Markdown-Bild-Link oder Dateipfad im Text. Schreib dazu "
            "hoechstens einen kurzen Satz, beschreibe das Bild nicht."
        )
    else:
        summary = (
            f"{count_done} Bilder wurden erfolgreich generiert und dem Nutzer bereits im Chat angezeigt. "
            "Erfinde keine Markdown-Bild-Links oder Dateipfade im Text. Schreib dazu "
            "hoechstens einen kurzen Satz, beschreibe die Bilder nicht."
        )

    return {
        "ok": True,
        "attachments": attachments,
        "text": summary,
    }
