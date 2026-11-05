"""PDFs lesen: per Link fuer alle Modelle und als Anhang fuer Gemini und GPT."""
import asyncio
import os
import shutil
import tempfile

import httpx
import pytest

os.environ.setdefault("SERVER_TOKEN", "x" * 40)
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="pc-pdf-test-"))

from pocket_claude import attachments, claude_engine, openai_engine, pdf_text, web_tool

pytestmark = pytest.mark.skipif(not shutil.which("pdftotext"),
                                reason="pdftotext (poppler-utils) fehlt")

URL = "https://example.org/dissertation.pdf?sequence=1"


def pdf_bytes(*seiten: str) -> bytes:
    """Kleinstes gueltiges PDF. Eine leere Seite hat keine Textebene wie ein Scan."""
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(len(seiten)))
    objs = ["<< /Type /Catalog /Pages 2 0 R >>",
            f"<< /Type /Pages /Kids [{kids}] /Count {len(seiten)} >>"]
    font = 3 + 2 * len(seiten)
    for i, text in enumerate(seiten):
        strom = f"BT /F1 12 Tf 50 700 Td ({text}) Tj ET" if text else ""
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                    f"/Contents {4 + 2 * i} 0 R /Resources << /Font << /F1 {font} 0 R >> >> >>")
        objs.append(f"<< /Length {len(strom)} >>\nstream\n{strom}\nendstream")
    objs.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = b"%PDF-1.4\n"
    offsets = []
    for number, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{obj}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += (f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    return out


@pytest.fixture
def netz(monkeypatch):
    """Antwortet ohne echtes Netz und zaehlt die Abrufe."""
    pdf_text._cache.clear()
    monkeypatch.setattr(web_tool, "_check_host", lambda host: None)
    real_client = httpx.AsyncClient
    abrufe = []

    def install(body: bytes, ctype: str = "application/pdf;charset=ISO-8859-1"):
        def handler(req):
            abrufe.append(str(req.url))
            return httpx.Response(200, content=body, headers={"content-type": ctype})
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_client(
            **kw, transport=httpx.MockTransport(handler)))
        return abrufe
    return install


def test_link_liest_pdf_und_blaettert_ohne_neuen_download(netz):
    abrufe = netz(pdf_bytes("Erkrankungsalter Median", "Gehhilfe Definition"))
    erste = asyncio.run(web_tool.fetch(URL))
    assert erste["ok"] and "Erkrankungsalter Median" in erste["text"]
    assert "2 Seiten" in erste["text"]
    assert erste["sources"][0]["url"] == URL

    zweite = asyncio.run(web_tool.fetch(URL, pages="2"))
    assert "Gehhilfe Definition" in zweite["text"]
    assert "Erkrankungsalter" not in zweite["text"]
    assert len(abrufe) == 1


def test_langes_pdf_kommt_in_stuecken_und_nennt_die_naechsten_seiten(netz, monkeypatch):
    monkeypatch.setattr(web_tool, "PDF_MAX_CHARS", 50)
    netz(pdf_bytes(*[f"Inhalt der Seite Nummer {i}" for i in range(1, 7)]))
    erste = asyncio.run(web_tool.fetch(URL))
    assert "Nummer 1" in erste["text"] and "Nummer 6" not in erste["text"]
    assert 'pages="2-' in erste["text"] or 'pages="3-' in erste["text"]
    letzte = asyncio.run(web_tool.fetch(URL, pages="6"))
    assert "Nummer 6" in letzte["text"] and "geht weiter" not in letzte["text"]


@pytest.mark.parametrize("pages,erwartet", [("99", "6 Seiten"), ("abc", "ungueltig"), ("4-2", "6 Seiten")])
def test_falsche_seitenangabe_wird_erklaert(netz, pages, erwartet):
    netz(pdf_bytes(*["Text der Seite"] * 6))
    asyncio.run(web_tool.fetch(URL))
    result = asyncio.run(web_tool.fetch(URL, pages=pages))
    assert not result["ok"] and erwartet in result["text"]


def test_pdf_ohne_passende_kennzeichnung_wird_erkannt(netz):
    netz(pdf_bytes("Volltext der Arbeit"), ctype="application/octet-stream")
    assert "Volltext der Arbeit" in asyncio.run(web_tool.fetch(URL))["text"]


def test_andere_binaerdatei_bleibt_abgelehnt(netz):
    netz(b"\x00\x01" * 2000, ctype="application/octet-stream")
    result = asyncio.run(web_tool.fetch("https://example.org/archiv.zip"))
    assert not result["ok"] and "kein Text" in result["text"]


@pytest.mark.parametrize("body,erwartet", [
    (pdf_bytes("", ""), "Scan"),
    (b"%PDF-1.4\nkaputt", "nicht lesen"),
])
def test_unlesbares_pdf_gibt_klare_meldung(netz, body, erwartet):
    netz(body)
    result = asyncio.run(web_tool.fetch(URL))
    assert not result["ok"] and erwartet in result["text"]


def test_zu_grosses_pdf_wird_abgebrochen(netz, monkeypatch):
    monkeypatch.setattr(web_tool, "PDF_MAX_BYTES", 100)
    netz(pdf_bytes("Text"))
    result = asyncio.run(web_tool.fetch(URL))
    assert not result["ok"] and "zu gross" in result["text"]


def test_fehlendes_programm_bricht_nicht_den_turn(netz, monkeypatch):
    monkeypatch.setattr(pdf_text, "PDFTOTEXT", "/gibt/es/nicht/pdftotext")
    netz(pdf_bytes("Text"))
    result = asyncio.run(web_tool.fetch(URL))
    assert not result["ok"] and "fehlt" in result["text"]


def test_interne_adresse_bleibt_gesperrt_auch_als_pdf():
    result = asyncio.run(web_tool.fetch("http://127.0.0.1:8787/geheim.pdf"))
    assert not result["ok"] and "privat" in result["text"]


def test_claude_liest_pdf_ueber_eigenes_werkzeug_mit_gedaechtnis_sperre(netz):
    netz(pdf_bytes("Erkrankungsalter Median"))
    zustand = {}
    server, namen = claude_engine._build_image_mcp_server(
        "usr_test", None, [], asyncio.Queue(), mit_bild=False, mit_web=True,
        wissen_zustand=zustand)
    assert "mcp__pocket__web_fetch" in namen
    from mcp.shared.memory import create_connected_server_and_client_session

    async def run():
        async with create_connected_server_and_client_session(server["instance"]) as client:
            result = await client.call_tool("web_fetch", {"url": URL})
            assert not result.isError and "Erkrankungsalter" in str(result)
            zustand["erinnert"] = True
            result = await client.call_tool("web_fetch", {"url": URL})
            assert result.isError and "Erkrankungsalter" not in str(result)
    asyncio.run(run())


def test_claude_normale_seiten_bleiben_beim_eingebauten_abruf(netz):
    netz(b"<html>Seite</html>", ctype="text/html")
    result = asyncio.run(web_tool.fetch("https://example.org/", nur_pdf=True))
    assert not result["ok"] and "WebFetch" in result["text"]


@pytest.mark.parametrize("url,gesperrt", [
    ("https://example.org/arbeit.PDF?sequence=1", True),
    ("https://example.org/", False),
    ("https://example.org/pdf-erklaert.html", False),
])
def test_eingebauter_abruf_gibt_pdf_links_weiter(url, gesperrt):
    hook = claude_engine._pdf_nativ_sperren()["PreToolUse"][0].hooks[0]
    antwort = asyncio.run(hook({"tool_input": {"url": url}}, "x", None))
    assert bool(antwort) is gesperrt
    if gesperrt:
        assert "mcp__pocket__web_fetch" in antwort["hookSpecificOutput"]["permissionDecisionReason"]


def _anhang(tmp_path, body: bytes, name: str = "befund.pdf") -> dict:
    pfad = tmp_path / name
    pfad.write_bytes(body)
    return {"filename": name, "mime_type": "application/pdf", "path": str(pfad),
            "size_bytes": len(body)}


def _inhalt(att: dict) -> str:
    return asyncio.run(openai_engine._message_content(
        {"content": "Was steht drin?"}, ["a1"], {"a1": att}, supports_vision=True))


def test_gemini_und_gpt_bekommen_pdf_anhang_als_text(tmp_path):
    pdf_text._cache.clear()
    inhalt = _inhalt(_anhang(tmp_path, pdf_bytes("Blutwerte unauffaellig")))
    assert "Was steht drin?" in inhalt and "Blutwerte unauffaellig" in inhalt


@pytest.mark.parametrize("body,erwartet", [
    (pdf_bytes("", ""), "Scan"),
    (b"%PDF-1.4\nkaputt", "nicht lesen"),
])
def test_unlesbarer_pdf_anhang_kippt_den_turn_nicht(tmp_path, body, erwartet):
    pdf_text._cache.clear()
    inhalt = _inhalt(_anhang(tmp_path, body))
    assert "Was steht drin?" in inhalt and erwartet in inhalt


def test_geloeschter_pdf_anhang_wird_gemeldet(tmp_path):
    att = _anhang(tmp_path, pdf_bytes("Text"))
    os.unlink(att["path"])
    assert "nicht mehr vorhanden" in _inhalt(att)


def test_budget_rechnet_pdf_ein_ohne_die_platte_zu_lesen():
    att = {"filename": "a.pdf", "mime_type": "application/pdf", "path": "/gibt/es/nicht",
           "size_bytes": 10_000_000}
    tokens = openai_engine._rough_text_tokens({"content": ""}, {"a1": att}, ["a1"])
    assert tokens >= attachments.MAX_TEXT_ATTACHMENT_BYTES // 4
