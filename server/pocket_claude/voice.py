"""Voice-Input — Groq Whisper Large v3 Turbo Wrapper.

Eingehend: rohes Audio-File (m4a/aac/webm-opus/wav/...) + UI-Sprache.
Ausgehend: transkribierter Text.

Pro Sprache ein eigener Bias-Prompt. Die Standard-Prompts sind 1:1 aus
`AI-Voice-Keyboard` übernommen (arrays.xml,
`dictate_style_prompt_punctuation_capitalization_prompts`) — kurz und
generisch, biasen Whisper auf saubere Zeichensetzung + Großschreibung
ohne semantisch in die Transkription einzugreifen.

Sprachauflösung pro User (KV-Tabelle, scope=user_id):
  voice_lang_mode      "auto"     → folgt der UI-Sprache aus dem Request
                       "override" → nutzt voice_lang_override
  voice_lang_override  ISO-Code der gewählten Sprache (z.B. "sv", "ko")
  voice_prompt_cache   JSON-Map {lang_code: bias_prompt_text} —
                       Cache für Übersetzungen, die Claude on-demand für
                       Sprachen liefert, die nicht in BUNDLED_PROMPTS sind.
                       Wenn der User den Standard-Prompt einer bundled
                       Sprache überschreibt, landet das hier ebenfalls.
"""
from __future__ import annotations

import json
import logging
from typing import Final

import httpx

log = logging.getLogger(__name__)

GROQ_TRANSCRIBE_URL: Final = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_DEFAULT_MODEL: Final = "whisper-large-v3-turbo"

# UI-Locale → Whisper-Sprachcode (Whisper akzeptiert nur zweistellige Codes
# bzw. einige Sonderfälle; "pt-BR" und "zh-CN" reduzieren wir hier).
def _to_whisper_code(locale: str | None) -> str:
    if not locale:
        return "en"
    s = locale.strip().lower().replace("_", "-")
    # Direkte Bundled-Codes
    if s in BUNDLED_PROMPTS:
        return s
    base = s.split("-", 1)[0]
    if base in BUNDLED_PROMPTS:
        return base
    return base or "en"


# Vollständige AI-Voice-Keyboard-Liste (arrays.xml). 57 Sprachen — deckt
# Whispers Sprachpaar im praktischen Alltag mehr als ab. Reihenfolge
# wie im Original-Repo.
BUNDLED_PROMPTS: Final[dict[str, str]] = {
    "en": "This sentence has capitalization and punctuation.",
    "af": "Hierdie sin het hoofletters en leestekens.",
    "ar": "تحتوي هذه الجملة على أحرف كبيرة وعلامات ترقيم.",
    "hy": "Այս նախադասությունն ունի մեծատառեր և կետադրություն։",
    "az": "Bu cümlədə böyük hərflər və durğu işarələri var.",
    "be": "Гэты сказ мае вялікія літары і знакі прыпынку.",
    "bs": "Ova rečenica ima velika slova i interpunkciju.",
    "bg": "Това изречение има главни букви и пунктуация.",
    "ca": "Aquesta frase té majúscules i puntuació.",
    "zh": "这句话有大写和标点符号。",
    "hr": "Ova rečenica ima velika slova i interpunkciju.",
    "cs": "Tato věta má velká písmena a interpunkci.",
    "da": "Denne sætning har store bogstaver og tegnsætning.",
    "nl": "Deze zin heeft hoofdletters en interpunctie.",
    "et": "Selles lauses on suurtähed ja kirjavahemärgid.",
    "fi": "Tässä lauseessa on isot kirjaimet ja välimerkit.",
    "fr": "Cette phrase comporte des majuscules et de la ponctuation.",
    "gl": "Esta frase ten maiúsculas e puntuación.",
    "de": "Dieser Satz enthält Großschreibung und Satzzeichen.",
    "el": "Αυτή η πρόταση έχει κεφαλαία και σημεία στίξης.",
    "he": "במשפט הזה יש אותיות גדולות וסימני פיסוק.",
    "hi": "इस वाक्य में बड़े अक्षर और विराम चिह्न हैं।",
    "hu": "Ez a mondat nagybetűket és írásjeleket tartalmaz.",
    "is": "Þessi setning hefur hástafi og greinarmerki.",
    "id": "Kalimat ini memiliki huruf kapital dan tanda baca.",
    "it": "Questa frase ha maiuscole e punteggiatura.",
    "ja": "この文には大文字と句読点があります。",
    "kn": "ಈ ವಾಕ್ಯದಲ್ಲಿ ದೊಡ್ಡ ಅಕ್ಷರಗಳು ಮತ್ತು ವಿರಾಮಚಿಹ್ನೆಗಳಿವೆ.",
    "kk": "Бұл сөйлемде бас әріптер мен тыныс белгілері бар.",
    "ko": "이 문장에는 대문자와 문장 부호가 있습니다.",
    "lv": "Šajā teikumā ir lielie burti un pieturzīmes.",
    "lt": "Šiame sakinyje yra didžiosios raidės ir skyrybos ženklai.",
    "mk": "Оваа реченица има големи букви и интерпункција.",
    "ms": "Ayat ini mempunyai huruf besar dan tanda baca.",
    "mr": "या वाक्यात मोठी अक्षरे आणि विरामचिन्हे आहेत.",
    "mi": "He pūmatua me ngā tohutohu tuhituhi kei tēnei rerenga kōrero.",
    "ne": "यस वाक्यमा ठूला अक्षर र विरामचिह्न छन्।",
    "no": "Denne setningen har store bokstaver og tegnsetting.",
    "fa": "این جمله دارای حروف بزرگ و علائم نگارشی است.",
    "pl": "To zdanie ma wielkie litery i interpunkcję.",
    "pt": "Esta frase tem maiúsculas e pontuação.",
    "ro": "Această propoziție are majuscule și semne de punctuație.",
    "ru": "Это предложение содержит заглавные буквы и знаки препинания.",
    "sr": "Ova rečenica ima velika slova i interpunkciju.",
    "sk": "Táto veta má veľké písmená a interpunkciu.",
    "sl": "Ta stavek ima velike začetnice in ločila.",
    "es": "Esta oración tiene mayúsculas y puntuación.",
    "sw": "Sentensi hii ina herufi kubwa na alama za uandishi.",
    "sv": "Den här meningen har versaler och skiljetecken.",
    "tl": "Ang pangungusap na ito ay may malalaking titik at bantas.",
    "ta": "இந்த வாக்கியத்தில் பெரிய எழுத்துகளும் நிறுத்தக்குறிகளும் உள்ளன.",
    "th": "ประโยคนี้มีตัวพิมพ์ใหญ่และเครื่องหมายวรรคตอน",
    "tr": "Bu cümlede büyük harfler ve noktalama işaretleri var.",
    "uk": "У цьому реченні є великі літери та розділові знаки.",
    "ur": "اس جملے میں بڑے حروف اور رموزِ اوقاف ہیں۔",
    "vi": "Câu này có chữ viết hoa và dấu câu.",
    "cy": "Mae gan y frawddeg hon briflythrennau ac atalnodi.",
}


# Display-Namen für die UI (in Englisch — UI lokalisiert die Locale-Labels
# selber falls gewünscht). Coverage = was als „bundled" angezeigt wird.
LANG_DISPLAY_NAMES: Final[dict[str, str]] = {
    "en": "English", "de": "German", "es": "Spanish", "fr": "French",
    "pt": "Portuguese", "it": "Italian", "nl": "Dutch", "pl": "Polish",
    "ru": "Russian", "uk": "Ukrainian", "tr": "Turkish", "ar": "Arabic",
    "fa": "Persian", "he": "Hebrew", "hi": "Hindi", "id": "Indonesian",
    "ms": "Malay", "ja": "Japanese", "ko": "Korean", "zh": "Chinese (Mandarin)",
    "vi": "Vietnamese", "th": "Thai", "cs": "Czech", "sk": "Slovak",
    "sl": "Slovenian", "hr": "Croatian", "sr": "Serbian", "bs": "Bosnian",
    "bg": "Bulgarian", "el": "Greek", "ro": "Romanian", "hu": "Hungarian",
    "fi": "Finnish", "sv": "Swedish", "no": "Norwegian", "da": "Danish",
    "is": "Icelandic", "et": "Estonian", "lv": "Latvian", "lt": "Lithuanian",
    "be": "Belarusian", "mk": "Macedonian", "sw": "Swahili", "ca": "Catalan",
    "gl": "Galician", "az": "Azerbaijani", "kk": "Kazakh", "kn": "Kannada",
    "mr": "Marathi", "ta": "Tamil", "ne": "Nepali", "ur": "Urdu",
    "tl": "Tagalog", "cy": "Welsh", "mi": "Maori", "hy": "Armenian",
    "af": "Afrikaans",
}


# ──────────────────────────────────────────────────────────────────────
# Resolve-Logik: aus User-KV + UI-Locale die effektive Sprache + den
# effektiven Bias-Prompt berechnen.
# ──────────────────────────────────────────────────────────────────────

KV_LANG_MODE = "voice_lang_mode"            # "auto" (default) | "override"
KV_LANG_OVERRIDE = "voice_lang_override"    # ISO-Code
KV_PROMPT_CACHE = "voice_prompt_cache"      # JSON {lang: prompt}
KV_GROQ_API_KEY = "voice_groq_api_key"


def resolve_effective_lang(
    *,
    kv: dict[str, str],
    request_locale: str | None,
) -> str:
    """Liefert den effektiven 2-Buchstaben-Whisper-Sprachcode."""
    mode = (kv.get(KV_LANG_MODE) or "auto").strip().lower()
    if mode == "override":
        override = (kv.get(KV_LANG_OVERRIDE) or "").strip()
        if override:
            return _to_whisper_code(override)
    return _to_whisper_code(request_locale)


def get_prompt_cache(kv: dict[str, str]) -> dict[str, str]:
    raw = (kv.get(KV_PROMPT_CACHE) or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return {str(k): str(v) for k, v in data.items() if isinstance(v, str) and v}
    except Exception:
        return {}


def resolve_prompt(*, kv: dict[str, str], lang: str) -> tuple[str, str]:
    """Liefert (bias_prompt, source) — source ∈ {"cache", "bundled", "fallback"}.

    Der Cache hat Vorrang, sodass ein bewusst übersetzter / vom User
    feinjustierter Prompt nicht von der gebundleten Default überschrieben wird.
    """
    cache = get_prompt_cache(kv)
    if lang in cache and cache[lang].strip():
        return cache[lang], "cache"
    if lang in BUNDLED_PROMPTS:
        return BUNDLED_PROMPTS[lang], "bundled"
    return BUNDLED_PROMPTS["en"], "fallback"


# ──────────────────────────────────────────────────────────────────────
# Groq-Transcribe
# ──────────────────────────────────────────────────────────────────────

class VoiceTranscribeError(Exception):
    """Wrapper für Fehler beim Transkribieren — die Message landet direkt im UI."""


async def transcribe(
    *,
    audio_bytes: bytes,
    filename: str,
    content_type: str,
    api_key: str,
    whisper_lang: str,
    bias_prompt: str,
    model: str = GROQ_DEFAULT_MODEL,
    timeout_sec: float = 60.0,
) -> str:
    """Schickt das Audio an Groq, liefert den Transkript-Text zurück.

    Anders als vorher: Sprache + Bias-Prompt sind explizit übergeben —
    der Caller hat die Resolution (auto vs. override, bundled vs.
    übersetzt) bereits gemacht. Hält die Funktion testbar.
    """
    if not api_key:
        raise VoiceTranscribeError(
            "Kein Groq-API-Key gesetzt. In den Einstellungen unter "
            "'Spracheingabe' eintragen.")
    if not audio_bytes:
        raise VoiceTranscribeError("Audio-Daten leer.")

    files = {
        "file": (filename, audio_bytes, content_type or "application/octet-stream"),
    }
    data = {
        "model": model,
        "response_format": "json",
        "temperature": "0",
    }
    # Leer heisst: Whisper erkennt die Sprache selbst. Geteilte Sprachnachrichten
    # koennen in jeder Sprache sein, ein fester Hinweis wuerde sie verbiegen.
    if whisper_lang:
        data["language"] = whisper_lang
    if bias_prompt:
        data["prompt"] = bias_prompt
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        async with httpx.AsyncClient(timeout=timeout_sec) as cli:
            r = await cli.post(
                GROQ_TRANSCRIBE_URL,
                headers=headers,
                files=files,
                data=data,
            )
    except httpx.TimeoutException as e:
        log.warning("Groq transcribe timeout: %s", e)
        raise VoiceTranscribeError(
            "Groq antwortet zu langsam (>60 s). Bitte nochmal versuchen."
        ) from e
    except httpx.RequestError as e:
        log.warning("Groq transcribe network error: %s", e)
        raise VoiceTranscribeError(f"Netzwerkfehler zu Groq: {e}") from e

    if r.status_code == 401:
        raise VoiceTranscribeError(
            "Groq-API-Key ungültig oder abgelaufen. In den Einstellungen "
            "neuen Key eintragen.")
    if r.status_code == 429:
        raise VoiceTranscribeError(
            "Groq-Rate-Limit erreicht (zu viele Anfragen). Kurz warten und "
            "erneut versuchen.")
    if r.status_code >= 500:
        raise VoiceTranscribeError(
            f"Groq-Serverfehler ({r.status_code}). Bitte später nochmal.")
    if r.status_code >= 400:
        msg = f"HTTP {r.status_code}"
        try:
            j = r.json()
            err = (j.get("error") or {}).get("message") or ""
            if err:
                msg = err
        except Exception:  # noqa: BLE001
            msg = (r.text or msg)[:200]
        raise VoiceTranscribeError(f"Groq lehnt die Anfrage ab: {msg}")

    try:
        body = r.json()
    except Exception as e:  # noqa: BLE001
        raise VoiceTranscribeError(
            f"Groq-Antwort ist kein JSON: {r.text[:200]}") from e

    text = (body.get("text") or "").strip()
    if not text:
        raise VoiceTranscribeError(
            "Transkript ist leer — vermutlich keine Sprache erkannt. "
            "Bitte näher ans Mikro oder lauter sprechen.")
    return text


# ──────────────────────────────────────────────────────────────────────
# Prompt-Übersetzung via Anthropic (Claude)
# ──────────────────────────────────────────────────────────────────────

# Translation-System-Prompt — bewusst HART formuliert, damit Claude
# garantiert keine Meta-Kommentare ausgibt. Englisch, weil so die
# Instruction-Following-Performance über alle Modelle am stabilsten ist.
TRANSLATE_SYSTEM_PROMPT: Final = """You translate ONE short bias sentence used to prime an automatic speech recognition system (Whisper). The user gives you the source text and a target language. You output ONLY the translation.

ABSOLUTE RULES:
1. Output ONLY the translated sentence. Nothing else. No introduction. No quotes around it. No explanation.
2. NEVER write "Here is", "Translation:", "Sure", "Note:" or any other preamble or commentary — even one word of meta-text breaks the downstream system.
3. The translation must read like a native sentence in the target language and mention capitalization, punctuation, or whatever the source talks about, in the local idiom.
4. Preserve the sentence's purpose: it's a bias prompt for a speech recognizer. Keep it short (one sentence, ≤120 chars).
5. If you cannot translate, still output ONLY a best-effort translation. Do not refuse, do not explain.

Output: raw translated sentence, single line."""


def _build_translate_user_msg(*, target_lang: str, source_text: str) -> str:
    """User-Prompt, der zur SYSTEM-Anweisung passt."""
    target_name = LANG_DISPLAY_NAMES.get(target_lang.lower(), target_lang)
    return (
        f"Target language: {target_name} (ISO code: {target_lang})\n"
        f"Source sentence (English):\n{source_text}"
    )


_META_PREFIXES: Final = (
    "here is the translation:", "the translation is:", "translation:",
    "translated:", "translated to", "translates to:",
    "sure, here you go:", "sure, here:", "sure, here", "sure:",
    "here you go:", "here:", "okay,", "ok,",
)


def _strip_quotes(s: str) -> str:
    if len(s) < 2:
        return s
    pairs = [('"', '"'), ("'", "'"), ("«", "»"), ("„", "“"),
             ("“", "”"), ("‚", "‘")]
    for open_c, close_c in pairs:
        if s.startswith(open_c) and s.endswith(close_c):
            return s[1:-1].strip()
    # Anführungszeichen am Anfang, Zeichensetzung am Ende ausserhalb
    # ("Hello world".) — auch das einfangen.
    for open_c, close_c in pairs:
        if s.startswith(open_c) and close_c in s[1:]:
            # Inhalt bis zum schließenden Quote
            end = s.find(close_c, 1)
            inner = s[1:end].strip()
            if inner:
                return inner
    return s


def _sanitize_translation(raw: str) -> str:
    """Defensive Reinigung: Meta-Präfixe + Anführungszeichen + Code-Fences
    rauswerfen, die erste echte Zeile nehmen. Trotz harter System-Anweisung
    kann Claude Mal ein „Here is:" davorpacken — fängt das hier ab."""
    if not raw:
        return ""
    s = raw.strip()
    # Code-Fences entfernen
    if s.startswith("```"):
        inner = [ln for ln in s.splitlines() if not ln.startswith("```")]
        s = "\n".join(inner).strip()
    # Meta-Präfixe in einer Schleife abziehen — Claude kettet manchmal mehrere
    # ("Sure, here you go: Translation: …")
    for _ in range(3):
        lowered = s.lower()
        matched = False
        for prefix in _META_PREFIXES:
            if lowered.startswith(prefix):
                s = s[len(prefix):].strip()
                matched = True
                break
        if not matched:
            break
    s = _strip_quotes(s)
    # Nur die erste nicht-leere Zeile (Schutz vor angefügten Erklärungen)
    for line in s.splitlines():
        line = line.strip()
        if line:
            return line
    return s


async def translate_bias_prompt(
    *,
    target_lang: str,
    source_text: str | None = None,
    user_id: str | None = None,
    timeout_sec: float = 30.0,
) -> str:
    """Übersetzt den englischen Default-Bias-Prompt in `target_lang`.

    Geht über `claude_engine.oneshot_text()` mit dem User-Auth-Kontext
    (Pro/Max | API-Key | Bedrock — egal welcher). Liefert reinen Text
    zurück, garantiert ohne Meta-Kommentare (siehe TRANSLATE_SYSTEM_PROMPT
    + _sanitize_translation).
    """
    src = (source_text or BUNDLED_PROMPTS["en"]).strip()
    lang_code = _to_whisper_code(target_lang)
    # Late-Import, damit voice.py kein hartes claude_engine-Dep hat
    # (vermeidet Import-Zyklen falls voice irgendwann von claude_engine
    # genutzt wird).
    from pocket_claude import claude_engine
    raw = await claude_engine.oneshot_text(
        system_prompt=TRANSLATE_SYSTEM_PROMPT,
        user_message=_build_translate_user_msg(
            target_lang=lang_code, source_text=src,
        ),
        user_id=user_id,
        timeout_sec=timeout_sec,
    )
    clean = _sanitize_translation(raw)
    if not clean:
        raise RuntimeError("Claude lieferte einen leeren Übersetzungs-Output.")
    if len(clean) > 240:
        clean = clean[:240].rstrip()
    return clean
