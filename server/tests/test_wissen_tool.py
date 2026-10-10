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


def _konfig(monkeypatch, user_ids="usr_joscha"):
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
    assert wissen_tool.freigeschaltet("usr_joscha")
    assert not wissen_tool.freigeschaltet("usr_kati")
    assert not wissen_tool.freigeschaltet(None)
    monkeypatch.setattr(settings, "wissen_token", "")
    assert not wissen_tool.freigeschaltet("usr_joscha")


def test_fremdes_konto_bekommt_nichts_und_es_gibt_keinen_aufruf(monkeypatch):
    _konfig(monkeypatch)
    aufrufe = []
    _fake_client(monkeypatch, lambda req: aufrufe.append(req) or httpx.Response(200, json={"treffer": []}))
    res = asyncio.run(wissen_tool.run("usr_kati", {"anfrage": "Mama"}))
    assert not res["ok"] and not aufrufe


def test_treffer_werden_mit_token_geholt_und_formatiert(monkeypatch):
    _konfig(monkeypatch)
    gesehen = {}

    def handler(req):
        gesehen["auth"] = req.headers.get("Authorization")
        gesehen["q"] = req.url.params.get("q")
        return httpx.Response(200, json={"treffer": [
            {"person": "Aaron", "abschnitt": "Kernkarte", "text": "Bruder"}]})
    _fake_client(monkeypatch, handler)
    res = asyncio.run(wissen_tool.run("usr_joscha", {"anfrage": "Wer ist Aaron?"}))
    assert res["ok"] and "### Aaron: Kernkarte" in res["text"] and "Bruder" in res["text"]
    assert gesehen["auth"] == "Bearer " + "t" * 40 and gesehen["q"] == "Wer ist Aaron?"


def test_dienst_weg_ist_kein_absturz(monkeypatch):
    _konfig(monkeypatch)

    def handler(req):
        raise httpx.ConnectError("weg")
    _fake_client(monkeypatch, handler)
    res = asyncio.run(wissen_tool.run("usr_joscha", {"anfrage": "x"}))
    assert not res["ok"] and "nicht erreichbar" in res["text"]
