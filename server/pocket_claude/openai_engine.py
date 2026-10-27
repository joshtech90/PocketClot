"""Streaming-Engine fuer die Zusatz-Modelle (Gemini, GPT) ueber OpenAI-Gateways.

Claude laeuft weiterhin ueber `claude_engine.py` und die Claude-Agent-SDK. Fuer
die Zusatz-Modelle gibt es keine SDK und keinen Server-State: die Gateways
(CLIProxyAPI fuer die Google-Konten, CodexLB fuer die ChatGPT-Konten) sind
zustandslos und sprechen `POST /v1/chat/completions` mit Streaming.

Konsequenzen daraus:
  - Der Verlauf wird bei JEDEM Turn aus unserer DB neu aufgebaut. Es gibt kein
    `--resume` wie bei Claude.
  - Das Kontextfenster muessen wir selbst im Auge behalten (siehe `_build_messages`).
  - Werkzeuge laufen ueber das native Function-Calling der Gateways:
    `generate_image` (siehe `image_tool.py`) sowie `web_search` und `web_fetch`
    (siehe `web_tool.py`). GPT-Modelle bei CodexLB bekommen statt unseres
    Such-Werkzeugs die eingebaute Suche des Gateways.

Die Funktion `stream_reply()` spiegelt bewusst Signatur und Event-Format von
`claude_engine.stream_reply()`, damit `server.py` nur eine Weiche braucht.

Bewusst nur `httpx`, kein openai-SDK: die Gateways sprechen ein schmales
Protokoll, und eine zusaetzliche Dependency waere hier reiner Ballast.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
from pathlib import Path
from typing import AsyncIterator

import httpx

from pocket_claude import attachments as att_mod
from pocket_claude import db, gateways, usage, web_tool
from pocket_claude.config import settings

log = logging.getLogger(__name__)

# Wie oft darf das Modell hintereinander Werkzeuge aufrufen. Seit es neben der
# Bilderzeugung auch Suche und Seitenabruf gibt, sind drei Runden zu knapp:
# "suchen, Treffer nachlesen, antworten" braucht allein schon zwei. Nach oben
# begrenzt ohnehin `MAX_TURN_SECONDS`.
MAX_TOOL_ROUNDS = 6

# Ein Bild im Prompt kostet je nach Modell 500 bis 2000 Tokens. Wir rechnen
# pauschal, weil wir die echte Kachelung der Gateways nicht kennen.
IMAGE_TOKEN_ESTIMATE = 1500

# Wieviel vom Kontextfenster darf der Verlauf belegen. Der Rest ist Reserve
# fuer die Antwort und fuer Werkzeug-Ergebnisse.
HISTORY_BUDGET_RATIO = 0.55

# Die letzten N Nachrichten werden nie weggekuerzt, sonst verliert das Modell
# den unmittelbaren Gespraechsfaden.
PROTECTED_TAIL = 4

# Harte Obergrenze fuer erzeugte Bilder pro Turn. `MAX_TOOL_ROUNDS` begrenzt nur
# die Runden; ein Modell koennte in EINER Runde beliebig viele Tool-Calls
# schicken und damit das Gemini-Kontingent und den Plattenplatz leerraeumen.
MAX_IMAGES_PER_TURN = 4

# Absolute Obergrenze fuer einen kompletten Turn. Der httpx-Read-Timeout ist ein
# Inaktivitaets-Timeout: ein Gateway, das alle paar Sekunden ein Byte schickt,
# koennte sonst ewig laufen und Verbindung plus Task blockieren.
MAX_TURN_SECONDS = 900.0


# ---------- Verlauf ----------

def _estimate_tokens(content) -> int:
    """Grobe Token-Schaetzung. Zeichen durch 4, Bilder pauschal."""
    if isinstance(content, str):
        return len(content) // 4 + 4
    if isinstance(content, list):
        total = 4
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text":
                total += len(part.get("text") or "") // 4
            elif part.get("type") == "image_url":
                total += IMAGE_TOKEN_ESTIMATE
        return total
    return 4


async def _read_bytes(path_str: str) -> bytes | None:
    """Liest eine Anhang-Datei im Thread-Pool. None wenn sie weg oder kaputt ist."""
    def _read() -> bytes | None:
        p = Path(path_str)
        return p.read_bytes() if p.is_file() else None
    try:
        return await asyncio.to_thread(_read)
    except OSError as exc:
        log.warning("PC_GW: Anhang %s nicht lesbar: %s", path_str, exc)
        return None


async def _message_content(
    msg: dict,
    attach_ids: list[str],
    attachments_by_id: dict[str, dict],
    supports_vision: bool,
):
    """Baut den Content einer Nachricht: Text inline, Bilder als data-URI.

    Rueckgabe ist entweder ein String (nur Text) oder die OpenAI-Multipart-Liste
    (Text plus Bilder).
    """
    text_ids: list[str] = []
    image_atts: list[dict] = []
    notes: list[str] = []

    for aid in attach_ids:
        att = attachments_by_id.get(aid)
        if not att:
            continue
        filename = att.get("filename") or "Datei"
        mime = (att.get("mime_type") or "application/octet-stream").lower()
        # Audio geht als Transkript-Text rein, wie bei Claude.
        if att_mod.looks_like_text(filename, mime) or att_mod.is_audio(filename, mime):
            text_ids.append(aid)
        elif mime.startswith("image/"):
            image_atts.append(att)
        else:
            notes.append(
                f"[Datei '{filename}' kann dieses Modell nicht oeffnen. "
                f"Nur Claude kann Anhaenge dieser Art lesen.]"
            )

    # Text-Anhaenge gehen durch dieselbe Inline-Logik wie beim Claude-Pfad.
    text = att_mod.build_prompt_text(
        {"content": msg.get("content") or "", "attachment_ids": text_ids},
        attachments_by_id,
    )

    image_parts: list[dict] = []
    for att in image_atts:
        filename = att.get("filename") or "Bild"
        if not supports_vision:
            notes.append(f"[Bild '{filename}' kann dieses Modell nicht lesen.]")
            continue
        raw = await _read_bytes(att.get("path") or "")
        if raw is None:
            notes.append(f"[Bild '{filename}' ist auf dem Server nicht mehr vorhanden.]")
            continue
        mime = (att.get("mime_type") or "image/png").lower()
        b64 = base64.b64encode(raw).decode("ascii")
        image_parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{b64}"},
        })

    if notes:
        text = (text + "\n\n" + "\n".join(notes)).strip() if text.strip() else "\n".join(notes)

    if image_parts:
        parts: list[dict] = []
        if text.strip():
            parts.append({"type": "text", "text": text})
        parts.extend(image_parts)
        return parts
    return text


def _rough_text_tokens(row: dict, attachments_by_id: dict[str, dict],
                       attach_ids: list[str]) -> int:
    """Billige Vorab-Schaetzung fuer die Budget-Entscheidung.

    Wichtig: hier wird NICHTS von der Platte gelesen. Erst wenn feststeht,
    welche Nachrichten ueberhaupt im Kontext landen, werden deren Bilder
    geladen und base64-kodiert. Sonst wuerde ein langer Chat mit vielen Bildern
    erst hunderte Megabyte in den Speicher ziehen und sie dann wegwerfen.
    """
    total = len(row.get("content") or "") // 4 + 4
    for aid in attach_ids:
        att = attachments_by_id.get(aid)
        if not att:
            continue
        mime = (att.get("mime_type") or "").lower()
        if att_mod.is_audio(att.get("filename") or "", mime):
            total += len(att_mod.transcript_for_prompt(att)) // 4 + 20
        elif att_mod.looks_like_text(att.get("filename") or "", mime):
            total += min(att.get("size_bytes") or 0, att_mod.MAX_TEXT_ATTACHMENT_BYTES) // 4
        elif mime.startswith("image/"):
            total += IMAGE_TOKEN_ESTIMATE
    return total


async def _build_messages(
    cid: str,
    user_message_id: int,
    system_prompt: str,
    model: gateways.ChatModel,
    extra_attachment_ids: list[str] | None,
) -> list[dict]:
    """Baut den kompletten Nachrichten-Verlauf fuer das Gateway."""
    rows = await db.list_messages(cid)
    # Alles nach der aktuellen User-Nachricht abschneiden (dort gibt es nichts,
    # aber bei einem Retry koennte eine alte Assistant-Antwort dranhaengen).
    cut = len(rows)
    for i, row in enumerate(rows):
        if row["id"] == user_message_id:
            cut = i + 1
            break
    rows = rows[:cut]

    extra_ids = list(extra_attachment_ids or [])
    all_ids: list[str] = []
    for row in rows:
        for aid in (row.get("attachment_ids") or []):
            if aid not in all_ids:
                all_ids.append(aid)
    for aid in extra_ids:
        if aid not in all_ids:
            all_ids.append(aid)

    attachments = await db.get_attachments(all_ids) if all_ids else []
    attachments_by_id = {a["id"]: a for a in attachments}

    # Pro Zeile die effektive Anhang-Liste bestimmen (Gem-Wissensdateien haengen
    # nur an der aktuellen Nachricht).
    per_row_ids: list[list[str]] = []
    for row in rows:
        own = list(row.get("attachment_ids") or [])
        if row["id"] == user_message_id and extra_ids:
            own += [x for x in extra_ids if x not in own]
        per_row_ids.append(own)

    # Budget-Entscheidung ZUERST, rein auf Schaetzungen. Danach werden nur die
    # ueberlebenden Nachrichten wirklich aufgebaut.
    ctx = model.context_length or settings.max_context_tokens
    budget = int(min(ctx, settings.max_context_tokens) * HISTORY_BUDGET_RATIO)
    sys_tokens = len(system_prompt) // 4 + 4 if system_prompt else 0

    est = [_rough_text_tokens(r, attachments_by_id, ids)
           for r, ids in zip(rows, per_row_ids)]
    first = 0
    while (len(rows) - first) > PROTECTED_TAIL and sys_tokens + sum(est[first:]) > budget:
        first += 1
    truncated = first > 0

    # Reicht selbst der geschuetzte Rest nicht, sind meist Bilder schuld. Dann
    # fliegen die Bilder der aelteren geschuetzten Nachrichten raus, statt das
    # Gateway in einen Kontext-Fehler laufen zu lassen.
    drop_images_before = -1
    if sys_tokens + sum(est[first:]) > budget:
        drop_images_before = len(rows) - 1
        log.info("PC_GW: Budget zu eng, Bilder aelterer Nachrichten werden weggelassen")

    history: list[dict] = []
    for idx in range(first, len(rows)):
        row = rows[idx]
        role = row.get("role") or "user"
        if role == "assistant":
            # Auch Assistant-Nachrichten koennen Anhaenge haben: die im Chat
            # erzeugten Bilder. Die gehoeren mit rein, sonst kann das Modell ein
            # eigenes Bild im naechsten Turn weder sehen noch korrigieren.
            content = await _message_content(
                row, per_row_ids[idx], attachments_by_id,
                model.supports_vision and idx > drop_images_before,
            )
            history.append({"role": "assistant", "content": content})
            continue

        content = await _message_content(
            row, per_row_ids[idx], attachments_by_id,
            model.supports_vision and idx > drop_images_before,
        )
        if role == "system":
            # Eine System-Zeile mitten im Verlauf wuerde die Reihenfolge
            # zerstoeren, also als markierte User-Nachricht einreihen.
            if isinstance(content, str):
                content = f"[System] {content}"
            else:
                content = [{"type": "text", "text": "[System]"}] + list(content)
        history.append({"role": "user", "content": content})

    out: list[dict] = []
    sp = (system_prompt or "").strip()
    if truncated:
        note = ("[Aeltere Teile des Verlaufs wurden aus Platzgruenden weggelassen. "
                "Frag nach, wenn Dir Zusammenhang fehlt.]")
        sp = f"{sp}\n\n{note}" if sp else note
        log.info("PC_GW: Verlauf gekuerzt auf %d Nachrichten (Budget %d Tokens)",
                 len(history), budget)
    if sp:
        out.append({"role": "system", "content": sp})
    out.extend(history)
    return out


# ---------- Fehlermeldungen ----------

def _http_error_message(status: int, body: str, gw: gateways.GatewayConfig,
                        model_id: str) -> str:
    detail = body.strip()
    try:
        parsed = json.loads(body)
        err = parsed.get("error") if isinstance(parsed, dict) else None
        if isinstance(err, dict) and err.get("message"):
            detail = str(err["message"])
        elif isinstance(err, str):
            detail = err
        elif isinstance(parsed, dict) and parsed.get("message"):
            detail = str(parsed["message"])
    except (ValueError, TypeError):
        pass

    if status in (401, 403):
        return (f"Das Gateway '{gw.label}' hat den Zugriff abgelehnt. "
                f"API-Key in der .env pruefen.")
    if status == 404:
        return (f"Das Modell '{model_id}' kennt das Gateway nicht mehr. "
                f"Bitte in den Einstellungen ein anderes waehlen.")
    if status == 429:
        return ("Das Konto-Kontingent ist gerade erschoepft. Spaeter erneut "
                "versuchen oder ein anderes Modell waehlen.")
    return f"Gateway-Fehler (HTTP {status}): {detail[:400]}"


# ---------- Stream-Parsing ----------

def _reasoning_text(delta: dict) -> str:
    """Holt den Reasoning-Text aus einem Delta. Die Gateways sind sich uneins:
    mal `reasoning_content` als String, mal `reasoning` als String oder Objekt."""
    val = delta.get("reasoning_content")
    if isinstance(val, str) and val:
        return val
    val = delta.get("reasoning")
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        for key in ("text", "content", "summary"):
            inner = val.get(key)
            if isinstance(inner, str) and inner:
                return inner
            if isinstance(inner, list):
                return "".join(
                    p.get("text", "") for p in inner if isinstance(p, dict)
                )
    return ""


async def _sse_events(resp):
    """Zerlegt einen SSE-Stream in Datenzeilen.

    Yieldet jede `data:`-Zeile einzeln und danach `None` als Ereignis-Ende
    (Leerzeile). Der Aufrufer setzt die Zeilen selbst zusammen. Kommentare
    (`:` am Anfang) und andere Felder werden ignoriert.
    """
    async for line in resp.aiter_lines():
        if line == "":
            yield None
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            # Genau EIN optionales Leerzeichen nach dem Doppelpunkt gehoert
            # laut Spec zum Trenner, alles weitere sind Nutzdaten.
            value = line[5:]
            yield value[1:] if value.startswith(" ") else value
    # Manche Server schliessen ohne abschliessende Leerzeile.
    yield None


def _merge_tool_call_delta(acc: dict[int, dict], deltas: list) -> None:
    """Fuegt fragmentierte tool_call-Deltas zusammen. Die Argumente kommen in
    beliebig kleinen Haeppchen und muessen ueber den Index zugeordnet werden."""
    for tc in deltas:
        if not isinstance(tc, dict):
            continue
        # Manche Gateways schicken "index": null; als Schluessel neben Zahlen
        # liesse sich das spaeter nicht sortieren.
        idx = tc.get("index")
        if not isinstance(idx, int):
            idx = 0
        slot = acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
        if tc.get("id"):
            slot["id"] = tc["id"]
        fn = tc.get("function") or {}
        if fn.get("name"):
            slot["name"] = fn["name"]
        if fn.get("arguments"):
            # Manche Gateways schicken Fragmente als Nicht-String.
            slot["arguments"] += str(fn["arguments"])


# ---------- Hauptfunktion ----------

async def stream_reply(
    cid: str,
    user_message_id: int,
    *,
    model_key: str,
    effort: str = "",
    system_prompt: str | None = None,
    user_id: str | None = None,
    extra_attachment_ids: list[str] | None = None,
    allow_image_tool: bool = True,
    image_defaults: dict | None = None,
    skills: dict | None = None,
    wissen_schluessel: str | None = None,
    image_wish: bool = False,
) -> AsyncIterator[dict]:
    """Streamt eine Antwort eines Zusatz-Modells.

    Yieldet dieselben Events wie `claude_engine.stream_reply`, plus `image` und
    `sources`. Wirft nie eine Exception nach aussen: jeder Fehler wird ein
    `error`-Event.
    """
    log.info("PC_GW: stream_reply START cid=%s msg=%s model=%s effort=%s",
             cid, user_message_id, model_key, effort)
    # Beides ausserhalb des try, damit ein Fehler NACH einer Bilderzeugung die
    # Bilder nicht verwaisen laesst: sie sind dem Nutzer schon angezeigt worden
    # und liegen als Attachment auf der Platte.
    full_text_parts: list[str] = []
    image_attachments: list[dict] = []
    web_sources: list[dict] = []
    try:
        # Ungefiltert: die Kuratierung bestimmt nur, was im Picker steht.
        # Ein Chat mit einem aelteren Modell muss weiterlaufen duerfen.
        models = await gateways.list_models(curated=False)
        # Ohne Wunsch vom Client gilt die Server-Vorgabe aus der .env.
        wanted_effort = (effort or "").strip() or settings.extra_model_default_effort
        try:
            model, model_id, reasoning_effort = gateways.resolve(
                model_key, wanted_effort, models)
        except KeyError:
            yield {"type": "error", "message": (
                f"Das Modell '{model_key}' wird gerade nicht angeboten. "
                f"Bitte in den Einstellungen ein anderes waehlen."
            )}
            return

        gw = gateways.gateway_by_id(model.gateway_id)
        if gw is None:
            yield {"type": "error", "message": (
                f"Das Gateway '{model.gateway_id}' ist auf dem Server nicht "
                f"konfiguriert."
            )}
            return

        messages = await _build_messages(
            cid, user_message_id, (system_prompt or "").strip(), model, extra_attachment_ids,
        )

        # Werkzeuge zusammenstellen. Die Schalter sind dieselben wie bei
        # Claude; was ein Modell nicht kann, faellt hier still weg.
        sk = skills or {}
        tools: list[dict] = []
        image_tool = None
        if allow_image_tool and user_id is not None:
            try:
                from pocket_claude import image_tool as _image_tool
                image_tool = _image_tool
                tools.append({
                    "type": "function",
                    "function": {
                        "name": image_tool.TOOL_NAME,
                        "description": image_tool.TOOL_DESCRIPTION,
                        "parameters": image_tool.PARAMETERS,
                    },
                })
            except ImportError as exc:
                log.warning("PC_GW: Bild-Werkzeug nicht verfuegbar: %s", exc)

        # "Bild erstellen" aus dem Plus-Menue: Hinweis an die aktuelle Nachricht,
        # nur fuer diesen Turn. Der Verlauf kommt bei jedem Turn frisch aus der
        # Datenbank, dort steht er nicht.
        if image_wish and image_tool is not None and messages and messages[-1]["role"] == "user":
            letzte = messages[-1]["content"]
            if isinstance(letzte, str):
                messages[-1]["content"] = f"{letzte}\n\n{image_tool.WISH_HINT}"
            else:
                messages[-1]["content"] = [*letzte, {"type": "text", "text": image_tool.WISH_HINT}]

        # Privates Gedaechtnis, nur fuer freigeschaltete Konten
        from pocket_claude import wissen_tool
        mit_wissen = wissen_tool.freigeschaltet(user_id, wissen_schluessel)
        erinnert = False
        if mit_wissen:
            tools.append({
                "type": "function",
                "function": {
                    "name": wissen_tool.TOOL_NAME,
                    "description": wissen_tool.TOOL_DESCRIPTION,
                    "parameters": wissen_tool.PARAMETERS,
                },
            })

        # Suche: GPT bei CodexLB bringt seine eigene mit, die ist besser
        # eingebunden als alles, was wir vorne dranbauen koennten. Gemini
        # bekommt unser Werkzeug, das intern den nativen Google-Pfad benutzt.
        want_search = sk.get("web_search", True)
        native_search = bool(want_search and model.native_web_search)
        own_search = bool(want_search and not model.native_web_search
                          and model.family == "gemini")
        if native_search:
            tools.append({"type": "web_search"})
        if own_search:
            tools.append({
                "type": "function",
                "function": {
                    "name": web_tool.SEARCH_TOOL_NAME,
                    "description": web_tool.SEARCH_TOOL_DESCRIPTION,
                    "parameters": web_tool.SEARCH_PARAMETERS,
                },
            })
        want_fetch = bool(sk.get("web_fetch", True))
        if want_fetch:
            tools.append({
                "type": "function",
                "function": {
                    "name": web_tool.FETCH_TOOL_NAME,
                    "description": web_tool.FETCH_TOOL_DESCRIPTION,
                    "parameters": web_tool.FETCH_PARAMETERS,
                },
            })
        log.info("PC_GW: Werkzeuge cid=%s bild=%s suche=%s(nativ=%s) abruf=%s",
                 cid, image_tool is not None, bool(want_search),
                 native_search, want_fetch)

        headers = {"Content-Type": "application/json"}
        if gw.api_key:
            headers["Authorization"] = f"Bearer {gw.api_key}"
        url = f"{gw.base_url}/chat/completions"
        timeout = httpx.Timeout(gw.timeout, connect=15.0, read=gw.timeout)

        tokens_in = tokens_out = tokens_cached = 0
        aborted_tools = False
        image_budget_hit = False
        # Die eingebaute Websuche der Gateways ist kein Standard. Erkennt ein
        # Gateway sie nicht, wird sie einmalig fuer diesen Turn abgeschaltet,
        # statt jeden Anlauf an HTTP 400 scheitern zu lassen.
        search_disabled = False
        deadline = asyncio.get_running_loop().time() + MAX_TURN_SECONDS

        async with httpx.AsyncClient(timeout=timeout) as client:
            # Bewusst eine while-Schleife statt `for ... in range(...)`: ein
            # Anlauf, den das Modell wegen einer nicht unterstuetzten Denktiefe
            # abgelehnt hat, soll keine Werkzeug-Runde verbrauchen.
            round_idx = 0
            effort_retries = 0
            while round_idx <= MAX_TOOL_ROUNDS:
                if asyncio.get_running_loop().time() > deadline:
                    log.warning("PC_GW: Turn-Zeitlimit erreicht cid=%s", cid)
                    aborted_tools = True
                    break
                payload: dict = {
                    "model": model_id,
                    "messages": messages,
                    "stream": True,
                    "stream_options": {"include_usage": True},
                }
                if reasoning_effort:
                    payload["reasoning_effort"] = reasoning_effort
                if tools:
                    payload["tools"] = tools
                    payload["tool_choice"] = "auto"

                round_text_parts: list[str] = []
                tool_acc: dict[int, dict] = {}
                thinking_open = False
                round_in = round_out = round_cached = 0

                async with client.stream("POST", url, headers=headers, json=payload) as resp:
                    if resp.status_code >= 400:
                        body = (await resp.aread()).decode("utf-8", errors="replace")
                        # Nicht jede Denktiefe kann jedes Modell. Gemini 3.7
                        # Flash lehnt "minimal" rundheraus ab. Statt dem Nutzer
                        # einen Fehler zu zeigen, merken wir uns die Stufe und
                        # versuchen es eine Stufe hoeher nochmal.
                        if (resp.status_code == 400 and native_search
                                and not search_disabled
                                and _tool_type_rejected(body)):
                            log.info("PC_GW: %s kennt die eingebaute Websuche "
                                     "nicht, weiter ohne", model.key)
                            search_disabled = True
                            tools = [t for t in tools if t.get("type") != "web_search"]
                            continue
                        if (resp.status_code == 400 and reasoning_effort
                                and effort_retries < 2
                                and _effort_rejected(body)):
                            gateways.mark_effort_unsupported(
                                model.key, reasoning_effort)
                            higher = _effort_one_step_up(model, reasoning_effort)
                            log.info("PC_GW: %s lehnt Denktiefe %r ab, "
                                     "versuche %r", model.key,
                                     reasoning_effort, higher)
                            reasoning_effort = higher
                            # Bei Namensvarianten steckt die Stufe auch in der
                            # Modell-ID; die muss mitwandern, sonst geht die
                            # abgelehnte Variante einfach nochmal raus.
                            if model.effort_mode == "model_variant" and higher:
                                model_id = model.variant_ids.get(higher, model.fallback_id)
                            effort_retries += 1
                            continue
                        msg = _http_error_message(resp.status_code, body, gw, model_id)
                        log.warning("PC_GW: %s", msg)
                        yield {"type": "error", "message": msg}
                        return

                    # SSE erlaubt mehrere `data:`-Zeilen pro Ereignis; sie
                    # gehoeren mit Zeilenumbruch zusammengesetzt. Ein Ereignis
                    # endet an der Leerzeile. Zeilenweises Parsen wuerde bei
                    # solchen Gateways Text und Tool-Calls verlieren.
                    data_lines: list[str] = []
                    stream_done = False

                    async for line in _sse_events(resp):
                        if line is None:
                            raw = "\n".join(data_lines)
                            data_lines = []
                            if not raw:
                                continue
                            if raw.strip() == "[DONE]":
                                stream_done = True
                                break
                            try:
                                chunk = json.loads(raw)
                            except ValueError:
                                log.debug("PC_GW: unlesbares Stream-Ereignis uebersprungen: %r",
                                          raw[:120])
                                continue
                        else:
                            data_lines.append(line)
                            continue

                        u = chunk.get("usage")
                        if isinstance(u, dict):
                            # Pro Runde EINMAL zaehlen, aber ueber die Runden
                            # aufaddieren: ein Tool-Loop macht mehrere echte
                            # Gateway-Requests, die alle Geld kosten.
                            round_in = u.get("prompt_tokens") or 0
                            round_out = u.get("completion_tokens") or 0
                            details = u.get("prompt_tokens_details") or {}
                            round_cached = (
                                details.get("cached_tokens") or 0
                                if isinstance(details, dict) else 0
                            )

                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        choice = choices[0]
                        delta = choice.get("delta") or {}

                        think = _reasoning_text(delta)
                        if think:
                            thinking_open = True
                            yield {"type": "thinking_delta", "text": think}

                        text = delta.get("content")
                        if isinstance(text, list):
                            # Manche Gateways schicken Content als Part-Liste.
                            text = "".join(
                                p.get("text", "") for p in text if isinstance(p, dict)
                            )
                        if text:
                            if thinking_open:
                                thinking_open = False
                                yield {"type": "block_stop"}
                            if (not round_text_parts and full_text_parts
                                    and not full_text_parts[-1].endswith("\n")):
                                # Text nach einem Werkzeug als neuer Absatz,
                                # sonst klebt er an den Satz davor.
                                full_text_parts.append("\n\n")
                                yield {"type": "delta", "text": "\n\n"}
                            round_text_parts.append(text)
                            full_text_parts.append(text)
                            yield {"type": "delta", "text": text}

                        tc = delta.get("tool_calls")
                        if isinstance(tc, list) and tc:
                            _merge_tool_call_delta(tool_acc, tc)

                _ = stream_done
                if thinking_open:
                    yield {"type": "block_stop"}

                tokens_in += round_in
                tokens_out += round_out
                tokens_cached += round_cached

                if not tool_acc:
                    break

                # Text vor den Werkzeugen ("Ich schaue kurz nach.") ist ein
                # fertiger Block: die App liest ihn vor, waehrend das Werkzeug
                # laeuft, statt bis zum naechsten Satz zu warten (wie bei Claude).
                if round_text_parts:
                    yield {"type": "block_stop"}

                if round_idx >= MAX_TOOL_ROUNDS:
                    aborted_tools = True
                    break

                # Der Assistant-Turn MIT den tool_calls muss zurueck in den
                # Verlauf, sonst lehnt das Gateway die tool-Antworten ab.
                calls = []
                for idx in sorted(tool_acc):
                    slot = tool_acc[idx]
                    calls.append({
                        "id": slot["id"] or f"call_{round_idx}_{idx}",
                        "type": "function",
                        "function": {
                            "name": slot["name"],
                            "arguments": slot["arguments"] or "{}",
                        },
                    })
                messages.append({
                    "role": "assistant",
                    "content": "".join(round_text_parts) or None,
                    "tool_calls": calls,
                })

                for call in calls:
                    name = call["function"]["name"]
                    try:
                        args = json.loads(call["function"]["arguments"] or "{}")
                    except ValueError:
                        args = {}
                    if not isinstance(args, dict):
                        args = {}

                    # Ein Werkzeug darf den Turn nie kippen. Die Werkzeuge
                    # fangen ihre eigenen Fehler zwar ab, aber ein unerwarteter
                    # Fall wuerde sonst bis zum aeusseren Fehlerfaenger laufen
                    # und die halbe Antwort mitreissen. Das Modell bekommt
                    # stattdessen eine Meldung und kann sie erklaeren.
                    try:
                        if erinnert and name in (web_tool.SEARCH_TOOL_NAME, web_tool.FETCH_TOOL_NAME,
                                                 getattr(image_tool, "TOOL_NAME", "")):
                            # Sperre zuerst pruefen, vor jedem externen Werkzeug
                            tool_text = ("Nach einer Abfrage des privaten Gedaechtnisses sind "
                                         "Webabrufe und Bilder in dieser Antwort gesperrt.")
                        elif image_tool is not None and name == image_tool.TOOL_NAME:
                            if len(image_attachments) >= MAX_IMAGES_PER_TURN:
                                image_budget_hit = True
                                tool_text = (
                                    f"Es wurden in dieser Antwort bereits "
                                    f"{MAX_IMAGES_PER_TURN} Bilder erzeugt, das ist "
                                    f"die Obergrenze. Sag dem Nutzer, dass er fuer "
                                    f"weitere Bilder nochmal fragen soll."
                                )
                            else:
                                remaining = MAX_IMAGES_PER_TURN - len(image_attachments)
                                capped = dict(args)
                                try:
                                    wanted = int(capped.get("count") or 1)
                                except (TypeError, ValueError):
                                    wanted = 1
                                capped["count"] = max(1, min(wanted, remaining))
                                result = await image_tool.run(
                                    user_id, capped, image_defaults or {},
                                )
                                atts = [a for a in (result.get("attachments") or [])
                                        if isinstance(a, dict) and a.get("id")]
                                if result.get("ok") and atts:
                                    image_attachments.extend(atts)
                                    yield {"type": "image", "attachments": atts}
                                tool_text = result.get("text") or (
                                    "Bild erzeugt." if result.get("ok")
                                    else "Bilderzeugung fehlgeschlagen."
                                )
                        elif mit_wissen and name == wissen_tool.TOOL_NAME:
                            res = await wissen_tool.run(user_id, args, wissen_schluessel)
                            tool_text = res["text"]
                            # Nach privater Recherche keine Webwerkzeuge mehr in diesem Turn
                            erinnert = True
                            gesperrt = {web_tool.SEARCH_TOOL_NAME, web_tool.FETCH_TOOL_NAME}
                            if image_tool is not None:
                                gesperrt.add(image_tool.TOOL_NAME)
                            tools[:] = [t for t in tools if t.get("type") != "web_search" and
                                        (t.get("function") or {}).get("name") not in gesperrt]
                        elif own_search and name == web_tool.SEARCH_TOOL_NAME:
                            res = await web_tool.search(
                                gw, model_id, str(args.get("query") or ""))
                            tool_text = res["text"]
                            _collect_sources(res, web_sources)
                        elif want_fetch and name == web_tool.FETCH_TOOL_NAME:
                            res = await web_tool.fetch(str(args.get("url") or ""))
                            tool_text = res["text"]
                            _collect_sources(res, web_sources)
                        else:
                            tool_text = f"Das Werkzeug '{name}' gibt es hier nicht."
                            log.warning("PC_GW: unbekanntes Werkzeug angefragt: %s", name)
                    except Exception as exc:  # noqa: BLE001 - siehe Kommentar
                        log.warning("PC_GW: Werkzeug %s fehlgeschlagen: %s: %s",
                                    name, type(exc).__name__, exc)
                        tool_text = (f"Das Werkzeug '{name}' ist fehlgeschlagen. "
                                     f"Sag dem Nutzer, dass es gerade nicht ging.")

                    messages.append({
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": tool_text,
                    })

                round_idx += 1

        if aborted_tools:
            note = "\n\n_Weitere Werkzeugaufrufe wurden abgebrochen (Limit erreicht)._"
            full_text_parts.append(note)
            yield {"type": "delta", "text": note}

        if image_budget_hit:
            note = (f"\n\n_Es wurden {MAX_IMAGES_PER_TURN} Bilder erzeugt, "
                    f"das ist die Obergrenze pro Antwort._")
            full_text_parts.append(note)
            yield {"type": "delta", "text": note}

        # Quellen als Fussnoten unter die Antwort. Bewusst als Text und nicht
        # als eigenes Feld: so ueberleben sie Neuladen, Backup und Wiederher-
        # stellung, und die App braucht dafuer nichts Neues zu koennen.
        # Was das Modell schon selbst verlinkt hat, wird nicht wiederholt.
        footnotes = _source_footnotes(web_sources, "".join(full_text_parts))
        if footnotes:
            full_text_parts.append(footnotes)
            yield {"type": "delta", "text": footnotes}

        full_text = "".join(full_text_parts).strip()
        if not full_text and not image_attachments:
            yield {"type": "error", "message": (
                f"{model.label} hat eine leere Antwort geliefert. "
                f"Schick die Nachricht nochmal oder waehle ein anderes Modell."
            )}
            return

        # `cached_tokens` sind laut OpenAI-Schema bereits Teil von
        # `prompt_tokens`, also NICHT nochmal dazuzaehlen.
        context_total = tokens_in + tokens_out
        if context_total <= 0:
            context_total = max(1, len(full_text) // 4)

        msg_id = await db.add_message(
            cid,
            role="assistant",
            content=full_text,
            tokens=context_total,
            attachment_ids=[a["id"] for a in image_attachments] or None,
        )
        await db.set_total_tokens(cid, context_total)

        if user_id is not None:
            try:
                await usage.record(
                    user_id=user_id,
                    provider=f"gateway:{model.family}",
                    input_tokens=tokens_in,
                    output_tokens=tokens_out,
                    cache_create=0,
                    cache_read=tokens_cached,
                )
            except Exception as exc:  # noqa: BLE001 - Statistik darf nie den Chat kippen
                log.warning("PC_GW: usage.record fehlgeschlagen: %s", exc)

        log.info("PC_GW: stream_reply DONE cid=%s msg=%s in=%d out=%d imgs=%d",
                 cid, msg_id, tokens_in, tokens_out, len(image_attachments))
        yield {
            "type": "done",
            "assistant_message_id": msg_id,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "tokens_cached_read": tokens_cached,
            "tokens_cached_write": 0,
        }

    except httpx.ConnectError as exc:
        log.warning("PC_GW: Verbindung fehlgeschlagen: %s", exc)
        await _rescue_partial(cid, full_text_parts, image_attachments)
        yield {"type": "error", "message": (
            "Das Gateway ist nicht erreichbar. Laeuft der Dienst auf dem Server?"
        )}
    except httpx.TimeoutException:
        log.warning("PC_GW: Timeout cid=%s model=%s", cid, model_key)
        await _rescue_partial(cid, full_text_parts, image_attachments)
        yield {"type": "error", "message": (
            "Das Modell hat nicht rechtzeitig geantwortet. Versuch es nochmal "
            "oder waehle eine niedrigere Denktiefe."
        )}
    except Exception as exc:  # noqa: BLE001 - nach aussen darf nie etwas durchschlagen
        log.exception("PC_GW: unerwarteter Fehler cid=%s", cid)
        await _rescue_partial(cid, full_text_parts, image_attachments)
        yield {"type": "error", "message": f"{type(exc).__name__}: {exc}"}


def _effort_rejected(body: str) -> bool:
    """Erkennt, ob ein HTTP 400 an der gewaehlten Denktiefe lag.

    Gemini antwortet zum Beispiel mit "Thinking level MINIMAL is not supported
    for this model". Die Formulierungen unterscheiden sich je Anbieter, deshalb
    wird auf mehrere Stichworte geprueft.
    """
    low = (body or "").lower()
    if "thinking level" in low or "reasoning_effort" in low:
        return True
    return "reasoning" in low and ("not supported" in low or "invalid" in low)


def _tool_type_rejected(body: str) -> bool:
    """Erkennt, ob ein HTTP 400 an einem nicht unterstuetzten Werkzeug-Typ lag.

    Die eingebaute Websuche wird als `{"type": "web_search"}` angefragt, und das
    steht in keinem Standard. Ein Gateway, das sie nicht kennt, lehnt entweder
    den Werkzeug-Typ ab oder die ganze Anfrage als ungueltig.
    """
    low = (body or "").lower()
    if "web_search" in low:
        return True
    return ("tool" in low or "invalid request" in low) and (
        "not supported" in low or "unsupported" in low
        or "unknown" in low or "invalid" in low)


def _effort_one_step_up(model: gateways.ChatModel, current: str) -> str | None:
    """Naechsthoehere Stufe, die dieses Modell noch anbietet.

    Gibt None zurueck, wenn es keine gibt: dann laeuft der naechste Anlauf ganz
    ohne Angabe, also mit der Vorgabe des Gateways.
    """
    bad = gateways.unsupported_efforts(model.key)
    rest = [e for e in model.efforts if e not in bad]
    if not rest:
        return None
    try:
        idx = gateways.EFFORT_ORDER.index(current)
    except ValueError:
        return None
    for eff in gateways.EFFORT_ORDER[idx + 1:]:
        if eff in rest:
            return eff
    return None


def _collect_sources(result: dict, bucket: list[dict]) -> None:
    """Sammelt neue Quellen eines Werkzeug-Ergebnisses ohne Dubletten."""
    if not result.get("ok"):
        return
    known = {s["url"] for s in bucket}
    for src in result.get("sources") or []:
        url = src.get("url")
        if url and url not in known:
            known.add(url)
            bucket.append(src)


def _source_footnotes(sources: list[dict], answer: str) -> str:
    """Baut den Quellen-Block. Leerer String, wenn es nichts zu ergaenzen gibt."""
    fresh = [s for s in sources if s.get("url") and s["url"] not in answer]
    if not fresh:
        return ""
    lines = "\n".join(f"{i}. [{s['title']}]({s['url']})"
                       for i, s in enumerate(fresh, 1))
    return f"\n\n**Quellen**\n{lines}"


async def _rescue_partial(cid: str, text_parts: list[str],
                          images: list[dict]) -> None:
    """Rettet bereits erzeugte Bilder, wenn der Turn danach abbricht.

    Ohne das waeren die Bilder zwar auf der Platte und im Chat sichtbar
    gewesen, wuerden aber beim naechsten Laden verschwinden, weil sie an keiner
    Nachricht haengen.
    """
    if not images:
        return
    text = "".join(text_parts).strip()
    if not text:
        text = "_Die Antwort wurde abgebrochen, die erzeugten Bilder bleiben hier._"
    try:
        await db.add_message(
            cid, role="assistant", content=text, tokens=0,
            attachment_ids=[a["id"] for a in images],
        )
        log.info("PC_GW: %d Bilder nach Abbruch gerettet cid=%s", len(images), cid)
    except Exception as exc:  # noqa: BLE001 - Rettung darf selbst nichts kippen
        log.warning("PC_GW: Bilder-Rettung fehlgeschlagen: %s", exc)
