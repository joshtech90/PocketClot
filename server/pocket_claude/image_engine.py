"""Bilderzeugung ueber das Modell-Gateway.

Bis August 2026 lief das ueber `generativelanguage.googleapis.com` mit einem
AI-Studio-Schluessel, und jedes Bild kostete Geld. Seit dem 29.08.2026 laeuft es
ueber dasselbe Gateway, an dem auch die Gemini-Chatmodelle haengen, und damit
ueber die vorhandenen Google-Konten: kostenlos, ohne Schluessel in der App.

Moeglich ist das, weil CLIProxyAPI neben dem OpenAI-Pfad auch den echten
Gemini-Pfad `/v1beta/...:generateContent` bedient. Der nimmt exakt denselben
Request entgegen wie die kostenpflichtige Schnittstelle, deshalb bleibt hier
fast alles wie es war. Unterstuetzt weiterhin:

- Text-to-Image  (nur `prompt`)
- Image-to-Image (Editing: `prompt` + 1..n Referenz-Bilder als Inline-Data)
- Aspect-Ratio   (1:1, 16:9, 9:16, 4:3, 3:4 via `imageConfig.aspectRatio`)
- Aufloesung     (1K, 2K, 4K via `imageConfig.imageSize`)
- Mehrere Bilder (jetzt als mehrere Aufrufe, siehe unten)

Ein Unterschied bleibt: `candidateCount > 1` lehnt das Gateway ab
("Only one candidate can be specified in the current model"). Mehrere Varianten
entstehen deshalb durch mehrere Aufrufe nacheinander.

Die Modellwahl ist entfallen: welches Bildmodell es gibt, sagt das Gateway
(`gateways.image_target()`). Fehler werden als `ImageGenError` mit
aussagekraeftiger Message geworfen.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
from dataclasses import dataclass

import httpx

from pocket_claude import gateways

log = logging.getLogger(__name__)

# Die Modellwahl liegt beim Gateway, nicht mehr bei uns: es bietet genau die
# Bildmodelle an, fuer die ein Konto eingeloggt ist. Die Liste hier bliebe sonst
# dauerhaft hinter dem zurueck, was wirklich verfuegbar ist.
AVAILABLE_MODELS: list[dict] = []

# ---------------------------------------------------------------------------
# Zwei Anbieter, zwei Bildsprachen
# ---------------------------------------------------------------------------
# Gemini nimmt Seitenverhaeltnis und Aufloesung als eigene Felder entgegen und
# haelt sich exakt daran. GPT (gpt-image-2 ueber CodexLB) will stattdessen eine
# konkrete Pixelgroesse und behandelt sie als Wunsch: das Seitenverhaeltnis
# kommt ungefaehr an, die genaue Kantenlaenge nicht. Am 29.08.2026 gemessen,
# zum Beispiel 3840x2160 angefordert und 1536x1024 zurueckbekommen.
# "Beide" ersetzt das frühere "Automatisch". Automatisch war eine Entscheidung
# hinter dem Rücken des Nutzers: er sah am Ergebnis nicht, wer gezeichnet hat.
# Beide gleichzeitig zu fragen kostet nichts extra (beide Konten sind ohnehin
# bezahlt) und macht den Unterschied auf einen Blick sichtbar.
PROVIDER_BOTH = "both"
PROVIDER_GEMINI = "gemini"
PROVIDER_GPT = "gpt"
# Alter Wert, damit gespeicherte Einstellungen weiter gelesen werden koennen.
PROVIDER_AUTO = "auto"

IMAGE_PROVIDERS: list[dict] = [
    {"id": PROVIDER_BOTH, "label": "Beide"},
    {"id": PROVIDER_GEMINI, "label": "Gemini"},
    {"id": PROVIDER_GPT, "label": "GPT"},
]

def canonical_provider(value: str | None) -> str:
    """Hebt einen gespeicherten Anbieterwert auf den heutigen Stand.

    Der fruehere Wert "auto" liegt bei Bestandsnutzern noch im KV-Store. Er
    wird zu "beide": die App zeigt fuer so einen Nutzer den Knopf "Beide" an,
    und es waere irrefuehrend, wenn im Chat trotzdem nur ein Anbieter
    zeichnete. Leer heisst ebenfalls "beide", das ist die Vorgabe.
    """
    wanted = (value or "").strip().lower()
    if wanted in ("", PROVIDER_AUTO):
        return PROVIDER_BOTH
    return wanted


# Das Bildmodell von CodexLB steht in keiner Modell-Liste, es gibt dort nur den
# Endpunkt /v1/images/generations. Deshalb fest verdrahtet, in `gateways`,
# weil die Erkennung des GPT-Bildwegs genau dieses Modell verlangt.
GPT_IMAGE_MODEL = gateways.GPT_IMAGE_MODEL

# Groessen von gpt-image-2. NICHT gerechnet, sondern die nativen Werte aus der
# Modell-Dokumentation: das Modell kennt feste Stufen, und eine selbst
# ausgerechnete Groesse dazwischen laesst es auf seine eigene zurueckfallen.
# Genau daran lag es, dass angeforderte Aufloesungen frueher nicht ankamen.
#
# Regeln, die dabei gelten: beide Kanten durch 16 teilbar, Seitenverhaeltnis
# zwischen 1:3 und 3:1, laengste Kante hoechstens 3840. Alles ueber 2560x1440
# gilt beim Anbieter als experimentell, deshalb ist 4K hier moeglich, aber
# nicht die Vorgabe.
GPT_SIZES: dict[str, dict[str, str]] = {
    "1:1":  {"1K": "1280x1280", "2K": "2048x2048", "4K": "2880x2880"},
    "16:9": {"1K": "1280x720",  "2K": "2048x1152", "4K": "3840x2160"},
    "9:16": {"1K": "720x1280",  "2K": "1152x2048", "4K": "2160x3840"},
    "4:3":  {"1K": "1280x960",  "2K": "2048x1536", "4K": "3312x2480"},
    "3:4":  {"1K": "960x1280",  "2K": "1536x2048", "4K": "2480x3312"},
}

# Detailtiefe bei gpt-image-2. Der Unterschied ist nicht die Groesse, sondern
# wie lange das Modell rechnet: `low` 3 bis 8 Sekunden, `medium` 20 bis 40,
# `high` 150 bis 280. `high` war hier fest verdrahtet und damit die Ursache
# fuer Zeitueberschreitungen. `medium` ist die vernuenftige Vorgabe.
GPT_QUALITY_BY_SIZE = {"1K": "medium", "2K": "medium", "4K": "high"}

# Zeitgrenze fuer einen Bildaufruf. Bewusst grosszuegig: gpt-image-2 rechnet in
# hoher Detailtiefe bis zu viereinhalb Minuten. Das ist die VORGABE, kein
# Mindestwert; ein Aufrufer mit knapperem Budget darf weniger uebergeben.
DEFAULT_TIMEOUT_SECONDS = 330.0

# Wie lange im Modus "beide" auf den zweiten Anbieter gewartet wird, nachdem der
# erste fertig ist. Danach zaehlt das vorhandene Bild mehr als Vollstaendigkeit.
BOTH_GRACE_SECONDS = 45.0


def gpt_size(aspect_ratio: str | None, image_size: str | None) -> str:
    """Die native Pixelgroesse von gpt-image-2 fuer Verhaeltnis und Stufe.

    Unbekannte Eingaben fallen auf Quadrat in 2K zurueck, statt eine Ausnahme
    zu werfen: eine ungueltige Groesse soll die Bilderzeugung nicht verhindern.
    """
    aspect = (aspect_ratio or "1:1").strip()
    size = (image_size or "2K").strip().upper()
    row = GPT_SIZES.get(aspect) or GPT_SIZES["1:1"]
    return row.get(size) or row["2K"]


def gpt_quality(image_size: str | None) -> str:
    """Detailtiefe passend zur Aufloesungsstufe."""
    return GPT_QUALITY_BY_SIZE.get((image_size or "2K").strip().upper(), "medium")


ASPECT_RATIOS: list[dict] = [
    {"id": "1:1",  "label": "Quadrat (1:1)"},
    {"id": "16:9", "label": "Querformat (16:9)"},
    {"id": "9:16", "label": "Hochformat (9:16)"},
    {"id": "4:3",  "label": "Foto Quer (4:3)"},
    {"id": "3:4",  "label": "Foto Hoch (3:4)"},
]

IMAGE_SIZES: list[dict] = [
    {"id": "1K", "label": "Standard (1K)"},
    {"id": "2K", "label": "Hoch (2K)"},
    {"id": "4K", "label": "Sehr hoch (4K)"},
]

DEFAULT_IMAGE_SIZE = "2K"

# Obergrenze fuer Bilder pro Werkzeugaufruf. Weil das Gateway nur ein Bild pro
# Anfrage liefert, sind das ebenso viele Aufrufe nacheinander.
MAX_CANDIDATES = 4

# Wieviele Bild-Anfragen duerfen SERVERWEIT gleichzeitig laufen. Bewusst auf
# Modulebene und nicht je Aufruf: sonst waere die Grenze pro Chat-Turn gemeint,
# und zwei gleichzeitige Turns wuerden sie stillschweigend verdoppeln. Genau
# daran haengt aber das Kontingent des Google-Kontos.
# Wieviele Vorlagenbilder hoechstens mitgehen. Der Bearbeiten-Endpunkt laesst
# mehr zu, aber jedes Bild kostet Kontext und Wartezeit, und mehr als eine
# Handvoll ist beim Bearbeiten selten sinnvoll.
MAX_REFERENCE_IMAGES = 4

# Grenzen fuer Vorlagenbilder. Die App verkleinert vor dem Hochladen, ein
# eigener API-Client tut das aber nicht, und jede Vorlage liegt beim Aufruf
# komplett im Speicher und geht bei mehreren Varianten mehrfach zum Gateway.
MAX_REFERENCE_BYTES = 8_000_000
MAX_REFERENCE_TOTAL_BYTES = 20_000_000

# Bildformate, die beide Anbieter verstehen, erkannt an den ersten Bytes statt
# am gemeldeten Mimetyp. Ein Anhang kann als image/png deklariert und trotzdem
# ein abgeschnittenes HEIC sein; das wuerde den ganzen Bearbeiten-Aufruf
# abweisen, statt nur diese eine Vorlage zu ueberspringen.
def sniff_image(data: bytes) -> tuple[str, str] | None:
    """Erkennt Bildformat und Endung. None heisst: nicht verwendbar."""
    if not data or len(data) < 12:
        return None
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png", "png"
    if data[:2] == b"\xff\xd8":
        return "image/jpeg", "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    return None

_CONCURRENCY = 2
_gate: asyncio.Semaphore | None = None


def _concurrency_gate() -> asyncio.Semaphore:
    """Der gemeinsame Semaphore, beim ersten Bedarf angelegt.

    Nicht auf Modulebene erzeugt: ein Semaphore bindet sich an den Event-Loop,
    der beim Import laeuft, und das muss nicht derselbe sein wie der spaetere
    Betriebs-Loop.
    """
    global _gate
    if _gate is None:
        _gate = asyncio.Semaphore(_CONCURRENCY)
    return _gate


class ImageGenError(RuntimeError):
    """Generations-Fehler. Frontend zeigt `str(e)` direkt an."""


@dataclass
class GeneratedImage:
    index: int           # 0..n innerhalb dieses Calls
    mime_type: str       # i.d.R. "image/png"
    data: bytes          # rohe Bild-Bytes
    text: str | None = None  # falls das Modell Text zusaetzlich produziert hat
    # Wer es gezeichnet hat. Wichtig im Modus "beide", sonst sieht der Nutzer
    # zwei Bilder und weiss nicht, welches von wem ist.
    provider: str = ""


@dataclass
class ReferenceImage:
    """Input-Bild fuer Editing/Variations."""
    mime_type: str
    data: bytes


async def generate(
    *,
    prompt: str,
    provider: str = PROVIDER_BOTH,
    family_hint: str = "",
    model: str | None = None,
    aspect_ratio: str | None = None,
    image_size: str | None = None,
    count: int = 1,
    references: list[ReferenceImage] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[GeneratedImage]:
    """Erzeugt `count` Bilder aus `prompt`, optional mit `references` als Vorlage.

    Beide Wege laufen ueber Konten, die ohnehin bezahlt sind, und kosten nichts
    pro Bild. `provider` waehlt zwischen Gemini, GPT und beiden zugleich. Ein
    gespeichertes "auto" von frueher wird zu "beide"; nur wenn danach genau ein
    Anbieter uebrig bleibt, entscheidet `family_hint`, also die Familie des
    Modells, das gerade antwortet.

    Wirft `ImageGenError`, wenn gar nichts zustande kommt; kommen einzelne der
    gewuenschten Varianten nicht durch, werden die uebrigen trotzdem geliefert.
    """
    if not prompt or not prompt.strip():
        raise ImageGenError("Prompt darf nicht leer sein.")

    provider = canonical_provider(provider)
    order, gpt_gw = await _provider_order(provider, family_hint, bool(references))
    if not order:
        raise ImageGenError(
            "Bilderzeugung ist auf diesem Server nicht eingerichtet: kein "
            "Gateway meldet ein Bildmodell. Laeuft das Gateway?"
        )

    # "Beide" heisst wirklich beide: je ein Bild von jedem Anbieter, nebeneinander
    # im Ergebnis. Faellt einer aus, kommt trotzdem das des anderen an; nur wenn
    # beide scheitern, gibt es einen Fehler.
    if provider == PROVIDER_BOTH and len(order) > 1:
        # Die gewuenschte Anzahl gilt fuer das ERGEBNIS, nicht je Anbieter.
        # Sonst wuerden aus "vier Varianten" acht Bilder und die doppelte
        # Wartezeit, ohne dass irgendwo danach gefragt wurde.
        per_provider = max(1, min(int(count), MAX_CANDIDATES) // len(order))
        tasks = {
            asyncio.create_task(
                _run_provider(kind, gw=gpt_gw, prompt=prompt, model=model,
                              aspect_ratio=aspect_ratio, image_size=image_size,
                              count=per_provider, references=references,
                              timeout=timeout)
            ): kind
            for kind in order
        }
        # NICHT auf beide warten, sondern nach dem ersten BILD nur noch eine
        # kurze Gnadenfrist. Sonst haengt ein fertiges Bild hinter einem
        # Anbieter fest, der in sein Zeitlimit laeuft, und der Nutzer wartet
        # minutenlang auf etwas, das laengst da ist. Ein schneller Fehlschlag
        # (etwa Kontingent erschoepft) startet die Frist nicht: sonst wuerde
        # der andere Anbieter abgebrochen, obwohl nur er noch ein Bild liefern
        # kann.
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        done: set = set()
        pending: set = set(tasks)
        try:
            while pending:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    break
                finished, pending = await asyncio.wait(
                    pending, timeout=remaining, return_when=asyncio.FIRST_COMPLETED)
                done |= finished
                if any(t.exception() is None for t in finished):
                    break
            if pending and any(t.exception() is None for t in done):
                # Auch die Gnadenfrist endet spaetestens am Gesamtzeitlimit.
                grace = max(0.0, min(BOTH_GRACE_SECONDS, deadline - loop.time()))
                more, pending = await asyncio.wait(pending, timeout=grace)
                done |= more
        finally:
            # Auch wenn der Aufrufer abbricht (Turn-Zeitlimit, Nutzer stoppt):
            # kein Anbieter darf danach weiterlaufen und Gateway-Plaetze belegen.
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        for task in pending:
            log.warning("image-gen: %s war zu langsam und wurde abgebrochen",
                        tasks[task])

        images: list[GeneratedImage] = []
        first_error: BaseException | None = None
        for task in done:
            kind = tasks[task]
            exc = task.exception()
            if exc is not None:
                if first_error is None:
                    first_error = exc
                log.warning("image-gen: %s ist ausgefallen: %s: %s",
                            kind, type(exc).__name__, exc)
                continue
            for img in task.result():
                images.append(GeneratedImage(
                    index=len(images), mime_type=img.mime_type, data=img.data,
                    text=img.text, provider=kind,
                ))
        if not images:
            if isinstance(first_error, ImageGenError):
                raise first_error
            if first_error is not None:
                # Den echten Grund nennen statt ihn nur ins Log zu schreiben.
                raise ImageGenError(
                    f"Kein Anbieter hat ein Bild geliefert "
                    f"({type(first_error).__name__}: {first_error})."
                )
            raise ImageGenError("Kein Anbieter hat rechtzeitig ein Bild geliefert.")
        if len(images) < len(order) * per_provider:
            log.info("image-gen: nur %d von %d Bildern, ein Anbieter fiel aus",
                     len(images), len(order) * per_provider)
        return images

    last_error: ImageGenError | None = None
    for pos, kind in enumerate(order):
        try:
            return await _run_provider(
                kind, gw=gpt_gw, prompt=prompt, model=model,
                aspect_ratio=aspect_ratio, image_size=image_size,
                count=count, references=references, timeout=timeout,
            )
        except ImageGenError as exc:
            last_error = exc
            if pos + 1 < len(order):
                log.warning("image-gen: %s ist ausgefallen (%s), versuche %s",
                            kind, exc, order[pos + 1])
    raise last_error or ImageGenError("Es kam kein Bild zurueck.")


async def _run_provider(
    kind: str, *, gw, prompt: str, model: str | None, aspect_ratio: str | None,
    image_size: str | None, count: int, references, timeout: float,
) -> list[GeneratedImage]:
    """Ruft genau einen Anbieter auf und markiert die Bilder mit seinem Namen."""
    if kind == PROVIDER_GPT:
        out = await _generate_gpt(
            gw=gw, prompt=prompt, aspect_ratio=aspect_ratio,
            image_size=image_size, count=count, timeout=timeout,
            references=references,
        )
    else:
        out = await _generate_gemini(
            prompt=prompt, model=model, aspect_ratio=aspect_ratio,
            image_size=image_size, count=count, references=references,
            timeout=timeout,
        )
    for img in out:
        img.provider = kind
    return out


async def _provider_order(
    provider: str, family_hint: str, has_references: bool,
) -> tuple[list[str], "gateways.GatewayConfig | None"]:
    """Welche Anbieter in welcher Reihenfolge versucht werden.

    Zurueck kommt nur, was auch wirklich eingerichtet ist, dazu das
    GPT-Gateway, damit es nicht ein zweites Mal gesucht werden muss: zwischen
    zwei Abfragen koennte der Cache ablaufen und die zweite None liefern.

    Bei "beide" stehen beide in der Liste, und faellt einer aus, bleibt der
    andere. Bei einer ausdruecklichen Wahl wird nicht gewechselt: wer GPT
    anklickt und stillschweigend ein Gemini-Bild bekaeme, wuerde den
    Unterschied nie bemerken. Nur wenn der gewaehlte Anbieter ueberhaupt nicht
    eingerichtet ist, springt der andere ein, denn gar kein Bild ist die
    schlechtere Antwort.
    """
    gpt_gw = await gateways.gpt_image_gateway()
    gemini_ok = await gateways.image_target() is not None
    gpt_ok = gpt_gw is not None

    available = [k for k, ok in
                 ((PROVIDER_GEMINI, gemini_ok), (PROVIDER_GPT, gpt_ok)) if ok]
    if not available:
        return [], gpt_gw

    wanted = canonical_provider(provider)
    if wanted == PROVIDER_BOTH:
        # Die Reihenfolge zaehlt nur, wenn hier gar nicht beide gleichzeitig
        # zeichnen koennen, weil nur ein Gateway laeuft. Dann faengt der
        # Anbieter des antwortenden Modells an.
        first = PROVIDER_GPT if (family_hint or "").lower() == "gpt" else PROVIDER_GEMINI
        if first not in available:
            first = available[0]
        return [first] + [k for k in available if k != first], gpt_gw

    if wanted in available:
        return [wanted], gpt_gw
    log.info("image-gen: %s gewuenscht, aber nicht eingerichtet, nehme %s",
             wanted, available[0])
    return [available[0]], gpt_gw


async def _generate_gemini(
    *,
    prompt: str,
    model: str | None,
    aspect_ratio: str | None,
    image_size: str | None,
    count: int,
    references: list[ReferenceImage] | None,
    timeout: float,
) -> list[GeneratedImage]:
    """Bilder ueber den nativen Gemini-Pfad des Gateways."""
    target = await gateways.image_target(preferred=(model or "").strip())
    if target is None:
        raise ImageGenError(
            "Bilderzeugung ist auf diesem Server nicht eingerichtet: kein "
            "Gateway meldet ein Bildmodell. Laeuft das Gateway?"
        )
    gw, model_id = target
    count = max(1, min(int(count), MAX_CANDIDATES))

    parts: list[dict] = [{"text": prompt.strip()}]
    for ref in references or []:
        parts.append({
            "inlineData": {
                "mimeType": ref.mime_type,
                "data": base64.b64encode(ref.data).decode("ascii"),
            }
        })

    body: dict = {
        "contents": [{"role": "user", "parts": parts}],
        # `candidateCount` bleibt bewusst bei 1: das Gateway lehnt alles andere
        # ab. Mehrere Varianten entstehen unten durch mehrere Aufrufe.
        "generationConfig": {"responseModalities": ["IMAGE"], "candidateCount": 1},
    }
    image_config: dict[str, str] = {}
    if aspect_ratio and aspect_ratio.strip():
        image_config["aspectRatio"] = aspect_ratio.strip()
    if image_size and image_size.strip():
        image_config["imageSize"] = image_size.strip()
    if image_config:
        body["generationConfig"]["imageConfig"] = image_config

    url = f"{gateways.native_base_url(gw)}/models/{model_id}:generateContent"
    headers = {"Content-Type": "application/json"}
    if gw.api_key:
        headers["Authorization"] = f"Bearer {gw.api_key}"

    log.info("image-gen: gateway=%s model=%s aspect=%s size=%s count=%d refs=%d prompt=%r",
             gw.id, model_id, aspect_ratio, image_size, count,
             len(references or []), prompt[:80])

    # Zwei Anfragen gleichzeitig, serverweit. Alle auf einmal provoziert bei
    # Google gern ein Kontingent-Limit, eine nach der anderen dauert unnoetig
    # lange.
    gate = _concurrency_gate()

    async def _one(idx: int) -> tuple[int, list[GeneratedImage] | Exception]:
        async with gate:
            try:
                return idx, await _generate_one(
                    url, headers, body, timeout, aspect_ratio, image_size,
                )
            except ImageGenError as exc:
                return idx, exc

    results = await asyncio.gather(*(_one(i) for i in range(count)))

    images: list[GeneratedImage] = []
    first_error: ImageGenError | None = None
    for idx, res in sorted(results, key=lambda r: r[0]):
        if isinstance(res, Exception):
            if first_error is None and isinstance(res, ImageGenError):
                first_error = res
            continue
        for img in res:
            images.append(GeneratedImage(index=len(images), mime_type=img.mime_type,
                                         data=img.data, text=img.text))

    if not images:
        raise first_error or ImageGenError("Es kam kein Bild zurueck.")
    if first_error is not None:
        log.info("image-gen: %d von %d Varianten erzeugt, Rest fehlgeschlagen: %s",
                 len(images), count, first_error)
    return images


async def _generate_gpt(
    *,
    gw: "gateways.GatewayConfig | None",
    prompt: str,
    aspect_ratio: str | None,
    image_size: str | None,
    count: int,
    timeout: float,
    references: list[ReferenceImage] | None = None,
) -> list[GeneratedImage]:
    """Bilder ueber den OpenAI-Bildpfad von CodexLB (gpt-image-2).

    Mit Vorlagen geht es an `/v1/images/edits`, das multipart spricht und die
    Bilder als Datei-Teile erwartet; ohne Vorlagen an `/v1/images/generations`
    mit JSON. Der Rest ist identisch.

    Zur Groesse: das Gateway nimmt die berechnete Pixelgroesse an und reicht sie
    weiter, das Modell dahinter behandelt sie aber als Wunsch. Das
    Seitenverhaeltnis kommt ungefaehr an, die genaue Kantenlaenge nicht.
    Nachtraeglich hochzurechnen waere unehrlich, deshalb bleibt es beim
    gelieferten Bild.
    """
    if gw is None:
        raise ImageGenError(
            "Fuer GPT-Bilder ist auf diesem Server kein Gateway eingerichtet."
        )
    count = max(1, min(int(count), MAX_CANDIDATES))
    size = gpt_size(aspect_ratio, image_size)

    refs = list(references or [])[:MAX_REFERENCE_IMAGES]
    editing = bool(refs)
    endpoint = "images/edits" if editing else "images/generations"
    url = f"{gw.base_url.rstrip('/')}/{endpoint}"
    headers = {}
    if gw.api_key:
        headers["Authorization"] = f"Bearer {gw.api_key}"
    fields = {
        "model": GPT_IMAGE_MODEL,
        "prompt": prompt.strip(),
        "size": size,
        # NICHT fest auf "high": das laesst das Modell 150 bis 280 Sekunden
        # rechnen und lief zuverlaessig in eine Zeitueberschreitung.
        "quality": gpt_quality(image_size),
        # Das Gateway lehnt n groesser eins ab, mehrere Varianten entstehen
        # deshalb wie bei Gemini durch mehrere Aufrufe.
        "n": 1,
    }

    log.info("image-gen: gateway=%s modell=%s groesse=%s (aus %s/%s) anzahl=%d "
             "vorlagen=%d", gw.id, GPT_IMAGE_MODEL, size, aspect_ratio,
             image_size, count, len(refs))

    gate = _concurrency_gate()

    async def _one(idx: int):
        async with gate:
            try:
                return idx, await _gpt_one(url, headers, fields, refs, timeout)
            except ImageGenError as exc:
                return idx, exc

    results = await asyncio.gather(*(_one(i) for i in range(count)))

    images: list[GeneratedImage] = []
    first_error: ImageGenError | None = None
    for _idx, res in sorted(results, key=lambda r: r[0]):
        if isinstance(res, Exception):
            if first_error is None and isinstance(res, ImageGenError):
                first_error = res
            continue
        images.append(GeneratedImage(index=len(images), mime_type=res[0], data=res[1]))

    if not images:
        raise first_error or ImageGenError("Es kam kein Bild zurueck.")
    if first_error is not None:
        log.info("image-gen: %d von %d Varianten erzeugt, Rest fehlgeschlagen: %s",
                 len(images), count, first_error)
    return images


async def _gpt_one(url: str, headers: dict, fields: dict,
                   references: list[ReferenceImage],
                   timeout: float) -> tuple[str, bytes]:
    """Ein einzelner Bild-Aufruf gegen den OpenAI-Bildpfad.

    Ohne Vorlagen als JSON, mit Vorlagen als multipart. Die Textfelder sind in
    beiden Faellen dieselben, nur die Verpackung unterscheidet sich.
    """
    try:
        async with httpx.AsyncClient(timeout=timeout) as cli:
            if references:
                files = [
                    ("image", (f"vorlage{i}.{_ext_for(ref.mime_type)}",
                               ref.data, ref.mime_type))
                    for i, ref in enumerate(references)
                ]
                r = await cli.post(
                    url, headers=headers,
                    data={k: str(v) for k, v in fields.items()},
                    files=files,
                )
            else:
                r = await cli.post(
                    url, headers={**headers, "Content-Type": "application/json"},
                    json=fields,
                )
    except httpx.TimeoutException as e:
        raise ImageGenError(
            f"Timeout nach {timeout:.0f}s: Bild zu komplex oder Gateway ueberlastet."
        ) from e
    except httpx.RequestError as e:
        raise ImageGenError(f"Netzwerk-Fehler: {e}") from e

    if r.status_code >= 400:
        msg = r.text[:400]
        try:
            err = (r.json().get("error") or {})
            msg = err.get("message") or msg
        except Exception:
            pass
        log.warning("image-gen GPT HTTP %d: %s", r.status_code, msg)
        block = explain_block(msg) if r.status_code in _BLOCK_STATUS else None
        if block:
            raise ImageGenError(block)
        if r.status_code == 429:
            raise ImageGenError(
                "Das Bild-Kontingent des Kontos ist gerade erschoepft. "
                "Spaeter nochmal versuchen."
            )
        if r.status_code in (401, 403):
            raise ImageGenError(
                "Das Gateway erlaubt diesem Zugang keine Bilder. Ist das "
                "Bildmodell fuer den Schluessel freigegeben?"
            )
        raise ImageGenError(f"Gateway-Fehler (HTTP {r.status_code}): {msg}")

    try:
        data = r.json()
    except Exception as e:
        raise ImageGenError(f"Antwort konnte nicht geparst werden: {e}") from e

    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        raise ImageGenError("Die Antwort enthielt kein Bild.")
    first = items[0] if isinstance(items[0], dict) else {}
    raw_b64 = first.get("b64_json")
    if not raw_b64:
        block = explain_block(str(first.get("revised_prompt") or ""),
                              str(data.get("error") or ""))
        raise ImageGenError(block or "Die Antwort enthielt kein Bild.")
    try:
        raw = base64.b64decode(raw_b64)
    except Exception as e:
        raise ImageGenError(f"Das Bild war nicht lesbar: {e}") from e

    fmt = (fields.get("output_format") or "png").lower()
    return f"image/{'jpeg' if fmt == 'jpeg' else fmt}", raw


# Gruende, aus denen ein Anbieter ein Bild verweigert, in verstaendlichem
# Deutsch. Ohne diese Uebersetzung sieht der Nutzer nur "HTTP 502" oder
# "finishReason: IMAGE_SAFETY" und haelt es fuer eine Stoerung, obwohl es eine
# bewusste Ablehnung war.
# Die Muster sind bewusst eng gefasst. Ein frueherer Entwurf suchte nach
# Bruchstuecken wie "face", "minor", "blocked" oder "not allowed", und die
# stecken auch in "interface", einer Versionsnummer, einer Firewall-Meldung
# oder in "405 Method Not Allowed". Eine Netzwerkstoerung als Inhalts-Ablehnung
# auszugeben waere schlimmer als gar keine Erklaerung.
_BLOCK_HINTS: list[tuple[tuple[str, ...], str]] = [
    (("image_safety", "imagesafety", "safety_filter", "safety filter",
      "safety system", "safety_system", "sicherheitsgr"),
     "Der Anbieter hat das Bild aus Sicherheitsgruenden abgelehnt."),
    (("prohibited_content", "moderation_blocked", "content_policy",
      "content policy", "content_filter", "content filter", "responsible_ai",
      "blocklist", "usage policies", "usage policy", "rejected by our",
      "safety_violation", "policy violation"),
     "Der Anbieter hat den Bildwunsch als unzulaessig abgelehnt."),
    (("person_generation", "celebrity", "public_figure", "real person",
      "recognizable person"),
     "Der Anbieter erzeugt oder veraendert keine Bilder von erkennbaren Personen."),
    (("recitation",),
     "Der Anbieter hat abgelehnt, weil das Ergebnis zu nah an geschuetztem "
     "Material waere."),
    (("copyright", "trademark", "intellectual_property"),
     "Der Anbieter hat wegen geschuetzter Inhalte abgelehnt."),
    (("csam", "child_safety", "child safety", "minor_safety"),
     "Der Anbieter hat den Bildwunsch abgelehnt: er beruehrt den Schutz "
     "Minderjaehriger."),
]


# HTTP-Status, bei denen eine Ablehnung ueberhaupt plausibel ist. Alles andere
# (429 Kontingent, 5xx Stoerung) ist technisch, egal was im Text steht.
_BLOCK_STATUS = frozenset({400, 403, 422})


def explain_block(*fragments: str | None) -> str | None:
    """Sucht in Fehlertexten und Abbruchgruenden nach einer Ablehnung.

    Gibt eine erklaerende Meldung zurueck, oder None wenn es nach einer
    technischen Stoerung aussieht statt nach einer bewussten Ablehnung.
    """
    haystack = " ".join(f for f in fragments if f).lower()
    if not haystack:
        return None
    for needles, message in _BLOCK_HINTS:
        if any(n in haystack for n in needles):
            return message
    return None


def _ext_for(mime: str) -> str:
    """Dateiendung fuer einen Bild-Mimetyp. Der Endpunkt prueft sie mit."""
    low = (mime or "").lower()
    if "jpeg" in low or "jpg" in low:
        return "jpg"
    if "webp" in low:
        return "webp"
    return "png"


def usable_references(
    raw: list[tuple[str, bytes]],
) -> list[ReferenceImage]:
    """Macht aus (mimetyp, bytes)-Paaren brauchbare Vorlagen.

    Aussortiert wird alles, was zu gross ist oder kein Format hat, das beide
    Anbieter lesen koennen. Der Mimetyp wird dabei auf das gesetzt, was wirklich
    in den Bytes steht, nicht auf das, was die Datenbank behauptet.
    """
    out: list[ReferenceImage] = []
    total = 0
    seen: set[bytes] = set()
    for mime, data in raw:
        if len(out) >= MAX_REFERENCE_IMAGES:
            break
        if not data or len(data) > MAX_REFERENCE_BYTES:
            log.info("image-gen: Vorlage uebersprungen, %d Bytes", len(data or b""))
            continue
        sniffed = sniff_image(data)
        if sniffed is None:
            log.info("image-gen: Vorlage uebersprungen, Format nicht lesbar "
                     "(gemeldet als %r)", mime)
            continue
        # Dieselbe Datei zweimal mitzuschicken bringt nichts und kostet doppelt.
        digest = hashlib.sha256(data).digest()
        if digest in seen:
            continue
        if total + len(data) > MAX_REFERENCE_TOTAL_BYTES:
            log.info("image-gen: weitere Vorlagen uebersprungen, Gesamtgrenze erreicht")
            break
        seen.add(digest)
        total += len(data)
        out.append(ReferenceImage(mime_type=sniffed[0], data=data))
    return out


async def _generate_one(
    url: str,
    headers: dict,
    body: dict,
    timeout: float,
    aspect_ratio: str | None,
    image_size: str | None,
) -> list[GeneratedImage]:
    """Ein einzelner Bild-Aufruf inklusive Wiederholung ohne `imageSize`."""

    async def _send(req_body: dict) -> httpx.Response:
        try:
            async with httpx.AsyncClient(timeout=timeout) as cli:
                return await cli.post(url, headers=headers, json=req_body)
        except httpx.TimeoutException as e:
            raise ImageGenError(
                f"Timeout nach {timeout:.0f}s: Bild zu komplex oder Gateway ueberlastet."
            ) from e
        except httpx.RequestError as e:
            raise ImageGenError(f"Netzwerk-Fehler: {e}") from e

    r = await _send(body)

    # Nicht jedes Bildmodell kennt `imageSize`. Dann einmal ohne wiederholen,
    # damit ein Bild in Standardgroesse besser ist als gar keins.
    if r.status_code == 400 and image_size:
        low = r.text.lower()
        if "imagesize" in low or "image_config" in low or "imageconfig" in low:
            log.info("image-gen: Modell kennt imageSize nicht, wiederhole ohne")
            retry = {
                "contents": body["contents"],
                "generationConfig": {
                    "responseModalities": body["generationConfig"]["responseModalities"],
                    "candidateCount": 1,
                },
            }
            if aspect_ratio and aspect_ratio.strip():
                retry["generationConfig"]["imageConfig"] = {
                    "aspectRatio": aspect_ratio.strip()}
            r = await _send(retry)

    if r.status_code >= 400:
        msg = r.text[:400]
        try:
            err = (r.json().get("error") or {})
            msg = err.get("message") or msg
            status = err.get("status") or ""
            if status:
                msg = f"[{status}] {msg}"
        except Exception:
            pass
        log.warning("image-gen HTTP %d: %s", r.status_code, msg)
        # Nur bei Status, die eine Ablehnung sein KOENNEN. Ein 502 oder 429 ist
        # eine Stoerung, auch wenn im Text zufaellig ein Reizwort steht.
        block = explain_block(msg) if r.status_code in _BLOCK_STATUS else None
        if block:
            raise ImageGenError(block)
        if r.status_code == 429:
            raise ImageGenError(
                "Das Bild-Kontingent des Kontos ist gerade erschoepft. "
                "Spaeter nochmal versuchen."
            )
        raise ImageGenError(f"Gateway-Fehler (HTTP {r.status_code}): {msg}")

    try:
        data = r.json()
    except Exception as e:
        raise ImageGenError(f"Antwort konnte nicht geparst werden: {e}") from e

    images = _extract_images(data)
    if not images:
        reasons = [str(c.get("finishReason")) for c in data.get("candidates", [])
                   if c.get("finishReason")]
        feedback = data.get("promptFeedback") or {}
        block = explain_block(
            *reasons,
            str(feedback.get("blockReason") or ""),
            _collect_text((data.get("candidates") or [{}])[0].get("content") or {}),
        )
        if block:
            raise ImageGenError(block)
        # Kommt kein Bild und nennt der Anbieter auch keinen Grund, ist die
        # haeufigste Ursache trotzdem eine Ablehnung: Gemini schweigt bei
        # manchen Faellen einfach. Das gehoert gesagt, sonst sucht der Nutzer
        # den Fehler bei sich oder beim Server.
        # Ohne genannten Grund NICHT behaupten, es sei eine Ablehnung gewesen:
        # dieselbe Lage entsteht auch, wenn das Modell nur Text liefert oder
        # sich das Antwortformat geaendert hat.
        raise ImageGenError(
            "Der Anbieter hat kein Bild geliefert"
            + (f" (Grund: {', '.join(reasons)})" if reasons else
               " und keinen Grund genannt")
            + ". Das kann eine Inhalts-Ablehnung sein, etwa bei erkennbaren "
              "Personen, oder eine Stoerung beim Anbieter."
        )
    return images


def _extract_images(payload: dict) -> list[GeneratedImage]:
    out: list[GeneratedImage] = []
    for ci, cand in enumerate(payload.get("candidates", [])):
        content = cand.get("content") or {}
        for pi, part in enumerate(content.get("parts", [])):
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                mime = inline.get("mimeType") or inline.get("mime_type") or "image/png"
                try:
                    raw = base64.b64decode(inline["data"])
                except Exception:
                    continue
                out.append(GeneratedImage(index=ci, mime_type=mime, data=raw,
                                          text=_collect_text(content)))
                break  # ein Bild pro Candidate
    return out


def _collect_text(content: dict) -> str | None:
    texts = [p.get("text") for p in content.get("parts", []) if p.get("text")]
    if not texts:
        return None
    joined = " ".join(t.strip() for t in texts if t.strip())
    return joined or None


def get_config() -> dict:
    """Config-Info fuers Frontend.

    `models` ist seit dem Umstieg aufs Gateway leer und `default_model` ein
    leerer String: welches Bildmodell laeuft, entscheidet das Gateway. Beide
    Felder bleiben im Schema, damit aeltere App-Staende nicht stolpern.
    """
    return {
        "models": AVAILABLE_MODELS,
        "providers": IMAGE_PROVIDERS,
        "aspect_ratios": ASPECT_RATIOS,
        "image_sizes": IMAGE_SIZES,
        "max_candidates": MAX_CANDIDATES,
        "default_model": "",
        "default_provider": PROVIDER_BOTH,
        "default_aspect": "1:1",
        "default_image_size": DEFAULT_IMAGE_SIZE,
    }
