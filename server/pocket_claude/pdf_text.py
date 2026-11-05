"""Text aus PDFs lesen, fuer Links (`web_tool`) und Anhaenge der Zusatz-Modelle.

Die Arbeit macht `pdftotext` aus poppler-utils. Das Paket braucht der Server
ohnehin: Claudes Read-Werkzeug zeigt PDF-Anhaenge nur mit dessen `pdftoppm` an.

Die Datei kann aus dem offenen Netz stammen, deshalb laeuft das Auslesen in einem
eigenen Prozess mit Zeit-, Speicher- und Ausgabegrenze. Eine praeparierte Datei
trifft so hoechstens diesen einen Abruf und nie den Server.
"""
from __future__ import annotations

import asyncio
import logging
import re
import resource
import time
from collections import OrderedDict

log = logging.getLogger(__name__)

PDFTOTEXT = "pdftotext"
EXTRACT_SECONDS = 30.0
MAX_MEMORY_BYTES = 1_500_000_000
MAX_CPU_SECONDS = 60
MAX_OUTPUT_BYTES = 8_000_000

CACHE_SECONDS = 15 * 60
CACHE_ENTRIES = 4

_PAGES_RE = re.compile(r"^\s*(\d+)\s*(?:-\s*(\d+)\s*)?$")
_BLANK_LINES_RE = re.compile(r"\n{3,}")

_cache: OrderedDict[str, tuple[float, object]] = OrderedDict()


class PdfFehler(Exception):
    """Lesbare Meldung, die das Modell dem Nutzer weitergeben kann."""


def aus_cache(key: str):
    """Schon gelesenes Dokument. Spart beim Blaettern den erneuten Download."""
    entry = _cache.get(key)
    if entry is None:
        return None
    if time.monotonic() - entry[0] > CACHE_SECONDS:
        _cache.pop(key, None)
        return None
    _cache.move_to_end(key)
    return entry[1]


def merken(key: str, value: object) -> None:
    _cache[key] = (time.monotonic(), value)
    _cache.move_to_end(key)
    while len(_cache) > CACHE_ENTRIES:
        _cache.popitem(last=False)


def _grenzen() -> None:
    """Laeuft im Kindprozess vor dem Start von pdftotext."""
    for limit, value in ((resource.RLIMIT_AS, MAX_MEMORY_BYTES),
                         (resource.RLIMIT_CPU, MAX_CPU_SECONDS)):
        try:
            resource.setrlimit(limit, (value, value))
        except (ValueError, OSError):
            pass  # macOS kennt nicht jede Grenze; relevant ist der Linux-Server


async def seiten(path: str) -> list[str]:
    """Liest den Text je Seite. Wirft bei jedem Problem `PdfFehler`."""
    try:
        proc = await asyncio.create_subprocess_exec(
            PDFTOTEXT, "-enc", "UTF-8", "-eol", "unix", str(path), "-",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            preexec_fn=_grenzen,
        )
    except FileNotFoundError as exc:
        log.warning("PC_PDF: pdftotext fehlt, poppler-utils installieren")
        raise PdfFehler("PDFs kann der Server gerade nicht lesen, "
                        "ihm fehlt das Programm dafuer.") from exc

    chunks: list[bytes] = []
    total = 0
    try:
        async with asyncio.timeout(EXTRACT_SECONDS):
            while chunk := await proc.stdout.read(65536):
                total += len(chunk)
                if total > MAX_OUTPUT_BYTES:
                    raise PdfFehler("Dieses PDF enthaelt zu viel Text, um es zu lesen.")
                chunks.append(chunk)
            code = await proc.wait()
    except TimeoutError as exc:
        raise PdfFehler("Das Auslesen dieses PDFs hat zu lange gedauert.") from exc
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()

    if code != 0:
        log.info("PC_PDF: pdftotext endete mit Code %s", code)
        raise PdfFehler("Dieses PDF laesst sich nicht lesen. Es ist beschaedigt "
                        "oder mit einem Passwort geschuetzt.")

    text = b"".join(chunks).decode("utf-8", errors="replace")
    # pdftotext beendet jede Seite mit einem Seitenvorschub, auch die letzte.
    pages = text.split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    return [_BLANK_LINES_RE.sub("\n\n", p).strip() for p in pages]


def hat_text(pages: list[str]) -> bool:
    """Ohne ein einziges Zeichen fehlt die Textebene, das ist meist ein Scan."""
    return any(pages)


def seitenangabe(spec: object) -> tuple[int, int | None] | None:
    """Liest "12" oder "12-30". Nichts angegeben heisst `None`, also von vorn."""
    if spec is None or str(spec).strip() == "":
        return None
    match = _PAGES_RE.match(str(spec))
    if not match:
        raise PdfFehler(f"Die Seitenangabe '{spec}' ist ungueltig. "
                        f"Erlaubt sind zum Beispiel 12 oder 12-30.")
    start = int(match.group(1))
    if match.group(2) is None:
        return start, start
    return start, int(match.group(2))


def ausschnitt(pages: list[str], bereich: tuple[int, int | None] | None,
               max_chars: int) -> tuple[str, int, int]:
    """Baut den Text der gewuenschten Seiten, bis `max_chars` erreicht ist.

    Rueckgabe: Text, erste und letzte gelieferte Seite. Mindestens eine Seite
    kommt immer zurueck, notfalls gekuerzt.
    """
    total = len(pages)
    start, end = bereich or (1, total)
    end = total if end is None else end
    if start < 1 or start > total or end < start:
        raise PdfFehler(f"Diese Seiten gibt es nicht, das PDF hat {total} Seiten.")
    end = min(end, total)

    blocks: list[str] = []
    used = 0
    last = start
    for number in range(start, end + 1):
        body = pages[number - 1] or "(kein Text auf dieser Seite, vielleicht ein Bild)"
        block = f"[Seite {number}]\n{body}"
        if blocks and used + len(block) > max_chars:
            break
        if len(block) > max_chars:
            block = f"{block[:max_chars]}\n[... Seite {number} gekuerzt ...]"
        blocks.append(block)
        used += len(block)
        last = number
    return "\n\n".join(blocks), start, last
