"""Werkzeuge `web_search` und `web_fetch` fuer die Zusatz-Modelle.

Claude bringt Websuche und Seitenabruf ueber die Agent-SDK selbst mit (siehe
`claude_engine.py`). Die Gateway-Modelle nicht, und die beiden Anbieter loesen
das unterschiedlich:

  - **GPT ueber CodexLB** hat eine eingebaute Suche. Die wird nicht hier
    beantwortet, sondern als `{"type": "web_search"}` in die Werkzeugliste des
    Requests gelegt; das Gateway erledigt den Rest. Siehe `openai_engine.py`.
  - **Gemini ueber CLIProxyAPI** kann Google-Grounding, aber nur ueber den
    nativen Gemini-Pfad `/v1beta/...:generateContent`. Ueber den
    OpenAI-Pfad, den PocketClot sonst benutzt, scheitert es mit
    `malformed_function_call`. Deshalb beantwortet `search()` unten den
    Werkzeugaufruf mit einem eigenen, kurzen Aufruf gegen diesen Pfad.

Der Seitenabruf ist fuer beide gleich und laeuft hier.

Kosten entstehen in keinem der beiden Faelle: beides laeuft ueber Konten, die
ohnehin bezahlt sind.
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import socket
import tempfile
import zlib
from typing import Any

import httpx

from pocket_claude import gateways, pdf_text, reddit_api

log = logging.getLogger(__name__)

SEARCH_TOOL_NAME = "web_search"
FETCH_TOOL_NAME = "web_fetch"

SEARCH_TIMEOUT = 60.0
FETCH_TIMEOUT = 20.0

# Absolute Obergrenze fuer einen Seitenabruf. Der httpx-Timeout ist ein
# Inaktivitaets-Timeout: ein Server, der alle paar Sekunden ein Byte schickt,
# koennte den Abruf sonst beliebig lange offenhalten, und die Zeitpruefung des
# Turns greift erst wieder zwischen den Werkzeugrunden.
FETCH_TOTAL_SECONDS = 45.0

# Wieviel Text eine abgerufene Seite maximal ins Gespraech einbringt. Mehr
# bringt selten Erkenntnis und frisst das Kontextfenster.
FETCH_MAX_CHARS = 12_000
FETCH_MAX_BYTES = 3_000_000
MAX_REDIRECTS = 4

# PDFs duerfen groesser sein als Seiten: Abgeschnitten waeren sie unlesbar. Zum
# Kontextfenster kommt immer nur ein Ausschnitt, der Rest ist per `pages` abrufbar.
PDF_MAX_BYTES = 50_000_000
PDF_MAX_CHARS = 40_000
# Manche Server kennzeichnen PDFs nur als allgemeine Binaerdatei.
_UNSPECIFIC_TYPES = {"", "application/octet-stream", "binary/octet-stream",
                     "application/download", "application/force-download"}

SEARCH_TOOL_DESCRIPTION = (
    "Sucht im Internet und liefert eine zusammengefasste Antwort mit Quellen. "
    "Nutze das Werkzeug immer, wenn die Frage aktuelles Wissen braucht: "
    "Nachrichten, Preise, Wetter, Termine, Versionen, alles was sich aendert, "
    "und alles worueber Du dir nicht sicher bist."
)

SEARCH_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": (
                "Die Suchanfrage in natuerlicher Sprache. Formuliere sie so, "
                "wie Du sie einer Suchmaschine geben wuerdest."
            ),
        },
    },
    "required": ["query"],
}

FETCH_TOOL_DESCRIPTION = (
    "Ruft eine konkrete Webseite ab und liefert ihren Text zurueck. Nutze das "
    "Werkzeug, wenn eine bestimmte Adresse gelesen werden soll, etwa eine "
    "Quelle aus einer vorherigen Suche. PDF-Dokumente werden als Text gelesen, "
    "lange PDFs seitenweise: das Ergebnis nennt die Seitenzahl, weitere Seiten "
    "holst Du mit `pages`. Reddit-Adressen werden ueber die "
    "Reddit-API gelesen, inklusive Beitraegen und Kommentaren. Fuer Reddit-Suchen "
    "nutze https://www.reddit.com/search?q=SUCHBEGRIFF oder "
    "https://www.reddit.com/r/SUBREDDIT/search?q=SUCHBEGRIFF&restrict_sr=on."
)

FETCH_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "description": "Die vollstaendige Adresse, beginnend mit http:// oder https://.",
        },
        "pages": {
            "type": "string",
            "description": "Nur bei PDFs: gewuenschte Seiten, zum Beispiel 12 oder 12-30.",
        },
    },
    "required": ["url"],
}


# ---------- Suche ueber den nativen Gemini-Pfad ----------

def _sources_from_grounding(meta: dict) -> list[dict]:
    """Zieht Titel und Link der benutzten Quellen aus den Grounding-Metadaten."""
    out: list[dict] = []
    seen: set[str] = set()
    for chunk in (meta.get("groundingChunks") or []):
        web = chunk.get("web") if isinstance(chunk, dict) else None
        if not isinstance(web, dict):
            continue
        uri = str(web.get("uri") or "").strip()
        title = str(web.get("title") or "").strip()
        if not uri or uri in seen:
            continue
        seen.add(uri)
        out.append({"title": title or uri, "url": uri})
    return out


def _text_from_candidate(cand: dict) -> str:
    parts = (cand.get("content") or {}).get("parts") or []
    texts = [p.get("text", "") for p in parts if isinstance(p, dict) and p.get("text")]
    return "".join(texts).strip()


async def search(gw: gateways.GatewayConfig, model_id: str, query: str) -> dict:
    """Beantwortet eine Suchanfrage ueber Google-Grounding.

    Rueckgabe: {"ok": bool, "text": str, "sources": [{"title", "url"}]}.
    Wirft nie: eine durchgereichte Ausnahme wuerde den ganzen Chat-Turn
    abbrechen, statt dem Modell nur zu sagen, dass die Suche gerade nicht ging.
    """
    try:
        return await _search_inner(gw, model_id, query)
    except Exception as exc:  # noqa: BLE001 - siehe Docstring
        log.warning("PC_WEB: Suche %r fehlgeschlagen: %s: %s",
                    (query or "")[:60], type(exc).__name__, exc)
        return {"ok": False, "sources": [], "text": (
            "Die Suche ist fehlgeschlagen. Beantworte die Frage aus Deinem "
            "eigenen Wissen und sag dazu, dass die Suche gerade nicht ging."
        )}


async def _search_inner(gw: gateways.GatewayConfig, model_id: str, query: str) -> dict:
    query = (query or "").strip()
    if not query:
        return {"ok": False, "text": "Es wurde keine Suchanfrage angegeben.",
                "sources": []}

    url = f"{gateways.native_base_url(gw)}/models/{model_id}:generateContent"
    headers = {"Content-Type": "application/json"}
    if gw.api_key:
        headers["Authorization"] = f"Bearer {gw.api_key}"
    body = {
        "contents": [{"role": "user", "parts": [{"text": query}]}],
        "tools": [{"google_search": {}}],
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(SEARCH_TIMEOUT, connect=10.0)) as cli:
            r = await cli.post(url, headers=headers, json=body)
    except httpx.TimeoutException:
        return {"ok": False, "sources": [],
                "text": "Die Suche hat zu lange gedauert. Sag das dem Nutzer."}
    except httpx.RequestError as exc:
        log.warning("PC_WEB: Suche nicht erreichbar: %s", exc)
        return {"ok": False, "sources": [],
                "text": "Die Suche ist gerade nicht erreichbar. Sag das dem Nutzer."}

    if r.status_code >= 400:
        log.warning("PC_WEB: Suche HTTP %d: %s", r.status_code, r.text[:300])
        return {"ok": False, "sources": [], "text": (
            f"Die Suche hat mit HTTP {r.status_code} geantwortet. Beantworte die "
            f"Frage aus Deinem eigenen Wissen und sag dazu, dass die Suche gerade "
            f"nicht ging."
        )}

    try:
        data = r.json()
    except ValueError:
        return {"ok": False, "sources": [],
                "text": "Die Suche hat eine unlesbare Antwort geliefert."}

    if not isinstance(data, dict):
        return {"ok": False, "sources": [],
                "text": "Die Suche hat eine unerwartete Antwortform geliefert."}
    cands = data.get("candidates") or []
    if not isinstance(cands, list) or not cands or not isinstance(cands[0], dict):
        return {"ok": False, "sources": [],
                "text": "Die Suche hat nichts zurueckgeliefert."}

    cand = cands[0]
    text = _text_from_candidate(cand)
    meta = cand.get("groundingMetadata") or {}
    sources = _sources_from_grounding(meta)
    queries = meta.get("webSearchQueries") or []

    if not text:
        return {"ok": False, "sources": sources,
                "text": "Die Suche hat keinen verwertbaren Text geliefert."}

    log.info("PC_WEB: Suche %r -> %d Zeichen, %d Quellen, Anfragen=%s",
             query[:60], len(text), len(sources), queries)

    if sources:
        liste = "\n".join(f"- {s['title']}: {s['url']}" for s in sources)
        text = f"{text}\n\nQuellen:\n{liste}"
    return {"ok": True, "text": text, "sources": sources}


# ---------- Seitenabruf ----------

# Netze, die `ipaddress` nicht als privat fuehrt, die hier aber trotzdem
# gesperrt gehoeren. Der wichtigste Fall ist 100.64.0.0/10: dort liegt das
# ganze Tailnet. Ohne diesen Eintrag koennte ein Modell den Server dazu
# bringen, Paradies-Dienste abzurufen und deren Antworten in den Chat zu
# stellen, denn formal sind das oeffentliche Adressen.
_EXTRA_BLOCKED_NETS = [
    ipaddress.ip_network("100.64.0.0/10"),    # CGNAT, dort haengt Tailscale
    ipaddress.ip_network("192.0.0.0/24"),     # IETF-Protokollzuweisungen
    ipaddress.ip_network("198.18.0.0/15"),    # Benchmark-Netze
    ipaddress.ip_network("64:ff9b::/96"),     # NAT64
]


class _BlockedUrl(ValueError):
    """Adresse zeigt nicht ins offene Netz."""


def _check_ip(raw: str) -> None:
    """Prueft eine einzelne IP-Adresse gegen alle Sperren."""
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError:
        raise _BlockedUrl(f"Unlesbare Adresse: {raw}")
    if (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
        raise _BlockedUrl(
            "Diese Adresse zeigt ins private Netz und wird nicht abgerufen."
        )
    if any(ip in net for net in _EXTRA_BLOCKED_NETS if ip.version == net.version):
        raise _BlockedUrl(
            "Diese Adresse zeigt ins private Netz und wird nicht abgerufen."
        )
    # Eine IPv6-Adresse, die eine IPv4-Adresse einpackt, muss zusaetzlich als
    # diese IPv4-Adresse geprueft werden. Sonst waere ::ffff:127.0.0.1 ein
    # Schlupfloch.
    mapped = getattr(ip, "ipv4_mapped", None) or getattr(ip, "sixtofour", None)
    if mapped is not None:
        if (mapped.is_private or mapped.is_loopback or mapped.is_link_local
                or mapped.is_reserved or mapped.is_multicast
                or any(mapped in n for n in _EXTRA_BLOCKED_NETS if n.version == 4)):
            raise _BlockedUrl(
                "Diese Adresse zeigt ins private Netz und wird nicht abgerufen."
            )


def _check_host(host: str) -> None:
    """Laesst nur oeffentlich erreichbare Adressen durch.

    Ohne diese Pruefung koennte ein Modell den Server dazu bringen, seine
    eigenen internen Dienste abzurufen und deren Antwort in den Chat zu
    stellen: die eigene API auf 127.0.0.1, das Modell-Gateway samt Schluessel,
    alles im Tailnet, oder den Metadaten-Dienst einer Cloud-Instanz.

    Das allein reicht aber NICHT. Zwischen dieser Aufloesung und dem
    Verbindungsaufbau loest httpx den Namen ein zweites Mal auf. Wer den
    DNS-Eintrag kontrolliert, kann beim ersten Mal eine harmlose und beim
    zweiten Mal eine interne Adresse liefern. Deshalb wird nach dem
    Verbindungsaufbau zusaetzlich die echte Gegenstelle geprueft, siehe
    `_check_peer()`.
    """
    if not host:
        raise _BlockedUrl("Die Adresse hat keinen Rechnernamen.")
    low = host.lower().strip("[]")
    if low in ("localhost",) or low.endswith(".localhost") or low.endswith(".internal"):
        raise _BlockedUrl("Adressen im eigenen Netz werden nicht abgerufen.")

    try:
        infos = socket.getaddrinfo(low, None)
    except socket.gaierror as exc:
        raise _BlockedUrl(f"Der Rechnername '{host}' ist nicht aufloesbar.") from exc

    for info in infos:
        _check_ip(info[4][0])


def _check_peer(response: httpx.Response) -> None:
    """Prueft, mit WEM die Verbindung tatsaechlich zustande kam.

    Das schliesst die Luecke zwischen Namensaufloesung und Verbindungsaufbau:
    egal was der DNS-Eintrag beim zweiten Nachschlagen geliefert hat, eine
    Antwort von einer gesperrten Adresse wird verworfen, bevor auch nur ein
    Byte davon im Chat landet.
    """
    stream = response.extensions.get("network_stream")
    if stream is None:
        return
    addr = stream.get_extra_info("server_addr")
    if not addr:
        return
    _check_ip(str(addr[0]))


_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<(script|style|noscript|svg)\b.*?</\1>", re.S | re.I)
_WS_RE = re.compile(r"[ \t]{2,}")
_NL_RE = re.compile(r"\n{3,}")


def _html_to_text(html: str) -> str:
    """Macht aus HTML lesbaren Fliesstext. Bewusst ohne Extra-Bibliothek."""
    import html as _html

    text = _SCRIPT_RE.sub(" ", html)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</(p|div|li|h[1-6]|tr|section|article)>", "\n", text, flags=re.I)
    text = _TAG_RE.sub(" ", text)
    text = _html.unescape(text)
    text = _WS_RE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return _NL_RE.sub("\n\n", text).strip()


async def fetch(url: str, pages: object = None, nur_pdf: bool = False) -> dict:
    """Ruft eine Seite oder ein PDF ab und gibt den Text zurueck.

    `pages` waehlt bei PDFs die Seiten. `nur_pdf` lehnt normale Seiten ab, das
    braucht der Claude-Pfad: Dort bleiben sie beim eingebauten WebFetch.

    Rueckgabe wie `search()`, und wie dort wird NIE geworfen: ein Werkzeug, das
    eine Ausnahme durchreicht, wuerde den ganzen Chat-Turn abbrechen statt nur
    eine Meldung zu erzeugen, die das Modell dem Nutzer erklaeren kann.
    """
    try:
        return await asyncio.wait_for(_fetch_inner(url, pages, nur_pdf),
                                      timeout=FETCH_TOTAL_SECONDS)
    except asyncio.TimeoutError:
        return {"ok": False, "sources": [],
                "text": "Die Seite hat zu lange gebraucht und wurde abgebrochen."}
    except _BlockedUrl as exc:
        log.info("PC_WEB: Abruf abgelehnt fuer %r: %s", url[:120], exc)
        return {"ok": False, "sources": [], "text": str(exc)}
    except pdf_text.PdfFehler as exc:
        log.info("PC_PDF: %r nicht gelesen: %s", url[:120], exc)
        return {"ok": False, "sources": [], "text": str(exc)}
    except Exception as exc:  # noqa: BLE001 - siehe Docstring
        log.warning("PC_WEB: Abruf %r fehlgeschlagen: %s: %s",
                    url[:120], type(exc).__name__, exc)
        return {"ok": False, "sources": [],
                "text": "Die Seite konnte nicht geladen werden."}


def _pdf_ergebnis(current: str, seiten: list[str], pages: object) -> dict:
    """Formuliert das Werkzeug-Ergebnis fuer ein gelesenes PDF."""
    if not pdf_text.hat_text(seiten):
        return {"ok": False, "sources": [], "text": (
            f"Dieses PDF hat {len(seiten)} Seiten, aber keinen lesbaren Text, es ist "
            f"vermutlich ein Scan. Sag das dem Nutzer: Als Anhang im Chat kann Claude "
            f"es als Bild lesen."
        )}
    text, first, last = pdf_text.ausschnitt(
        seiten, pdf_text.seitenangabe(pages), PDF_MAX_CHARS)
    total = len(seiten)
    weiter = ""
    if last < total:
        weiter = (f"\n\n[Das PDF geht weiter. Naechste Seiten mit "
                  f"pages=\"{last + 1}-{min(last + 20, total)}\" abrufen.]")
    log.info("PC_PDF: %r -> Seite %d-%d von %d", current[:120], first, last, total)
    return {
        "ok": True,
        "text": f"PDF von {current}, {total} Seiten, hier Seite {first} bis {last}:"
                f"\n\n{text}{weiter}",
        "sources": [{"title": str(httpx.URL(current).host or current), "url": current}],
    }


async def _body_chunks(r: httpx.Response):
    """Liefert den Inhalt stueckweise und packt je Schritt hoechstens 64 KB aus.

    `r.aiter_bytes()` entpackt erst alles, was gerade angekommen ist. Wenige Bytes
    koennen so zu Gigabytes werden, bevor eine Groessenpruefung drankommt, und zwar
    im Serverprozess. Mehrfach gepackte Antworten werden gar nicht erst gelesen.
    """
    encoding = (r.headers.get("content-encoding") or "").strip().lower()
    if encoding in ("", "identity"):
        async for chunk in r.aiter_raw():
            yield chunk
        return
    if encoding not in ("gzip", "x-gzip"):
        raise ValueError(f"Nicht unterstuetzte Kompression: {encoding[:40]}")
    entpacker = zlib.decompressobj(wbits=31)
    async for chunk in r.aiter_raw():
        data = chunk
        while True:
            out = entpacker.decompress(data, 65536)
            if out:
                yield out
            data = entpacker.unconsumed_tail
            if not data and len(out) < 65536:
                break


async def _read_pdf(r: httpx.Response, pruefen: bool) -> bytes | None:
    """Laedt ein PDF. Mit `pruefen` wird abgebrochen, wenn es am Anfang keins ist."""
    chunks: list[bytes] = []
    total = 0
    async for chunk in _body_chunks(r):
        total += len(chunk)
        if total > PDF_MAX_BYTES:
            raise pdf_text.PdfFehler("Dieses PDF ist zu gross, um es hier zu lesen.")
        chunks.append(chunk)
        if pruefen and total >= 1024:
            if b"%PDF-" not in b"".join(chunks)[:1024]:
                return None
            pruefen = False
    raw = b"".join(chunks)
    if pruefen and b"%PDF-" not in raw[:1024]:
        return None
    return raw


async def _pdf_lesen(raw: bytes) -> list[str]:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as datei:
        def schreiben() -> None:
            datei.write(raw)
            datei.flush()
        await asyncio.to_thread(schreiben)
        return await pdf_text.seiten(datei.name)


async def _fetch_inner(url: str, pages: object = None, nur_pdf: bool = False) -> dict:
    """Der eigentliche Abruf. Redirects werden von Hand verfolgt, damit jede
    Zwischenstation dieselbe Pruefung durchlaeuft: sonst genuegte ein
    oeffentlicher Kurzlink, der auf eine interne Adresse zeigt."""
    url = (url or "").strip()
    if not url:
        return {"ok": False, "text": "Es wurde keine Adresse angegeben.", "sources": []}
    pdf_text.seitenangabe(pages)  # Falsche Angabe: melden, bevor geladen wird

    # Beim Blaettern nicht jedes Mal neu laden. Hierhin kommt nur, was schon
    # die Sperren fuer interne Adressen passiert hat.
    gelesen = pdf_text.aus_cache(url)
    if gelesen is not None:
        return _pdf_ergebnis(gelesen[0], gelesen[1], pages)

    current = url
    pdf_raw: bytes | None = None
    kein_pdf = ("Unter dieser Adresse liegt kein PDF. "
                "Fuer normale Seiten WebFetch verwenden.")
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(FETCH_TIMEOUT, connect=8.0),
        follow_redirects=False,
        headers={"User-Agent": "PocketClot/1.0 (+Chat-Assistent)",
                 "Accept-Encoding": "gzip"},
    ) as cli:
        for _ in range(MAX_REDIRECTS + 1):
            parsed = httpx.URL(current)
            if parsed.scheme not in ("http", "https"):
                raise _BlockedUrl("Nur http- und https-Adressen werden abgerufen.")
            # Also dispatch after public redirects (e.g. Reddit share links).
            # The Reddit adapter validates routes and sends credentials only to
            # fixed API hosts, never to the supplied URL.
            if reddit_api.configured() and reddit_api.is_reddit_url(current):
                return await reddit_api.fetch(current)
            await asyncio.to_thread(_check_host, parsed.host or "")

            async with cli.stream("GET", current) as r:
                _check_peer(r)

                if r.status_code in (301, 302, 303, 307, 308):
                    loc = r.headers.get("location")
                    if not loc:
                        return {"ok": False, "sources": [],
                                "text": "Die Seite leitet weiter, sagt aber nicht wohin."}
                    current = str(httpx.URL(current).join(loc))
                    continue

                if r.status_code >= 400:
                    return {"ok": False, "sources": [],
                            "text": f"Die Seite hat mit HTTP {r.status_code} geantwortet."}

                ctype = (r.headers.get("content-type") or "").lower()
                mime = ctype.split(";")[0].strip()
                unspezifisch = mime in _UNSPECIFIC_TYPES
                if "pdf" in mime or unspezifisch:
                    pdf_raw = await _read_pdf(r, pruefen=unspezifisch)
                    if pdf_raw is not None:
                        break
                if nur_pdf:
                    return {"ok": False, "sources": [], "text": kein_pdf}
                if not (ctype.startswith("text/") or "json" in ctype or "xml" in ctype):
                    return {"ok": False, "sources": [], "text": (
                        f"Unter dieser Adresse liegt kein Text, sondern "
                        f"{ctype or 'ein unbekanntes Format'}."
                    )}

                # Stueckweise lesen und hart abschneiden. `r.content` wuerde die
                # ganze Antwort erst in den Speicher holen und AUSPACKEN; eine
                # als gzip getarnte Bombe koennte damit den Server umwerfen,
                # bevor die Groessenpruefung ueberhaupt drankommt. Siehe `_body_chunks`.
                chunks: list[bytes] = []
                total = 0
                truncated = False
                async for chunk in _body_chunks(r):
                    total += len(chunk)
                    if total > FETCH_MAX_BYTES:
                        chunks.append(chunk[: max(0, FETCH_MAX_BYTES - (total - len(chunk)))])
                        truncated = True
                        break
                    chunks.append(chunk)
                raw = b"".join(chunks)
                encoding = r.encoding or "utf-8"
                break
        else:
            return {"ok": False, "sources": [],
                    "text": "Die Adresse leitet zu oft weiter."}

    if pdf_raw is not None:
        seiten = await _pdf_lesen(pdf_raw)
        pdf_text.merken(url, (current, seiten))
        return _pdf_ergebnis(current, seiten, pages)

    body = raw.decode(encoding, errors="replace")
    text = _html_to_text(body) if "html" in ctype else body.strip()
    if len(text) > FETCH_MAX_CHARS:
        text = text[:FETCH_MAX_CHARS]
        truncated = True
    if truncated:
        text += "\n\n[... gekuerzt ...]"

    if not text.strip():
        return {"ok": False, "sources": [], "text": "Die Seite ist leer."}

    log.info("PC_WEB: Abruf %r -> %d Zeichen%s", current[:120], len(text),
             " (gekuerzt)" if truncated else "")
    title = str(httpx.URL(current).host or current)
    return {
        "ok": True,
        "text": f"Inhalt von {current}:\n\n{text}",
        "sources": [{"title": title, "url": current}],
    }
