"""Werkzeug `erinnern`: nur fuer freigeschaltete Konten, Fehler kippen nie den Chat."""
from __future__ import annotations

import asyncio
import os
import tempfile

os.environ.setdefault("SERVER_TOKEN", "x" * 40)
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="pc-test-data-"))

import httpx  # noqa: E402

from pocket_claude import wissen_tool  # noqa: E402
from pocket_claude.config import settings  # noqa: E402


def _konfig(monkeypatch, user_ids="usr_freigegeben"):
    monkeypatch.setattr(settings, "wissen_url", "http://dienst:8473")
    monkeypatch.setattr(settings, "wissen_token", "t" * 40)
    monkeypatch.setattr(settings, "wissen_user_ids", user_ids)


def _fake_client(monkeypatch, handler):
    echt = httpx.AsyncClient

    def neu(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return echt(*args, **kwargs)
    monkeypatch.setattr(httpx, "AsyncClient", neu)


def test_nur_eingetragene_konten(monkeypatch):
    _konfig(monkeypatch)
    assert wissen_tool.freigeschaltet("usr_freigegeben")
    assert not wissen_tool.freigeschaltet("usr_andere")
    assert not wissen_tool.freigeschaltet(None)
    monkeypatch.setattr(settings, "wissen_token", "")
    assert not wissen_tool.freigeschaltet("usr_freigegeben")


def test_fremdes_konto_bekommt_nichts_und_es_gibt_keinen_aufruf(monkeypatch):
    _konfig(monkeypatch)
    aufrufe = []
    _fake_client(monkeypatch, lambda req: aufrufe.append(req) or httpx.Response(200, json={"treffer": []}))
    res = asyncio.run(wissen_tool.run("usr_andere", {"anfrage": "Mama"}))
    assert not res["ok"] and not aufrufe


def test_treffer_werden_mit_token_geholt_und_formatiert(monkeypatch):
    _konfig(monkeypatch)
    gesehen = {}

    def handler(req):
        gesehen["auth"] = req.headers.get("Authorization")
        gesehen["q"] = __import__("json").loads(req.content)["q"]
        return httpx.Response(200, json={"treffer": [
            {"person": "Anna", "abschnitt": "Kernkarte", "text": "Bruder"}]})
    _fake_client(monkeypatch, handler)
    res = asyncio.run(wissen_tool.run("usr_freigegeben", {"anfrage": "Wer ist Anna?"}))
    assert res["ok"] and "### Anna: Kernkarte" in res["text"] and "Bruder" in res["text"]
    assert gesehen["auth"] == "Bearer " + "t" * 40 and gesehen["q"] == "Wer ist Anna?"


def test_dienst_weg_ist_kein_absturz(monkeypatch):
    _konfig(monkeypatch)

    def handler(req):
        raise httpx.ConnectError("weg")
    _fake_client(monkeypatch, handler)
    res = asyncio.run(wissen_tool.run("usr_freigegeben", {"anfrage": "x"}))
    assert not res["ok"] and "nicht erreichbar" in res["text"]


def test_frage_steht_nie_in_der_url(monkeypatch):
    _konfig(monkeypatch)
    urls = []
    _fake_client(monkeypatch, lambda req: urls.append(str(req.url)) or httpx.Response(200, json={"treffer": []}))
    asyncio.run(wissen_tool.run("usr_freigegeben", {"anfrage": "geheime Frage"}))
    assert urls and "geheime" not in urls[0]


def test_werkzeuggrenze_sperrt_bash_ohne_freigabe():
    from pocket_claude import claude_engine
    g = claude_engine.werkzeuggrenze(["WebSearch", "mcp__pocket__erinnern"])
    assert g["tools"] == ["WebSearch"]
    assert "Bash" in g["disallowed_tools"] and "Write" in g["disallowed_tools"]
    assert "WebSearch" not in g["disallowed_tools"]
    g = claude_engine.werkzeuggrenze([])
    assert g["tools"] == [] and "Read" in g["disallowed_tools"]


def test_hook_sperrt_webabruf_erst_nach_erinnern():
    from pocket_claude import claude_engine
    zustand = {}
    hooks = claude_engine._nach_erinnern_sperren(zustand)
    pruefen = hooks["PreToolUse"][0].hooks[0]
    assert asyncio.run(pruefen({}, "x", None)) == {}
    zustand["erinnert"] = True
    out = asyncio.run(pruefen({}, "x", None))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
