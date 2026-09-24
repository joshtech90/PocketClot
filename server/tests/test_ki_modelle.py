"""Modell-Register: Picker, Anheben alter IDs, Pool-Anzeigenamen."""
import json
from pathlib import Path

import pytest

from pocket_claude import ki_modelle

REGISTER = Path(__file__).resolve().parents[1] / "pocket_claude" / "ki_modelle.json"
QUELLE = Path(__file__).resolve().parents[3] / "AI Worker" / "config" / "ki-modelle.json"


def test_picker_nennt_familien_mit_aktuellem_namen():
    daten = json.loads(REGISTER.read_text())["familien"]
    picker = dict(ki_modelle.picker())
    assert list(picker)[0] == "opus"
    assert picker["opus"] == daten["opus"]["name"]
    assert all("-" not in key for key in picker)  # keine Versionsnummern als Schluessel


@pytest.mark.parametrize("gespeichert,erwartet", [
    ("claude-opus-5", "opus"),                # alte Generation wird angehoben
    ("claude-opus-5[1m]", "opus[1m]"),        # 1M-Kontext bleibt erhalten
    ("claude-opus-4-8", "opus"),
    ("claude-sonnet-4-6", "sonnet"),
    ("claude-haiku-4-5-20251001", "haiku"),
    ("opus", "opus"),
    ("us.anthropic.claude-opus-5", "us.anthropic.claude-opus-5"),  # Bedrock bleibt roh
    ("gpt-5.6-sol", "gpt-5.6-sol"),
    (None, None),
])
def test_fuer_cli(gespeichert, erwartet):
    assert ki_modelle.fuer_cli(gespeichert) == erwartet


def test_bestandschats_bleiben_erlaubt():
    ids = ki_modelle.bekannte_ids()
    assert {"claude-opus-5", "claude-opus-4-8", "opus", "fable"} <= ids


def test_pool_kurzname_bekommt_generation_im_namen():
    name = json.loads(REGISTER.read_text())["familien"]["gemini-flash"]["name"]
    assert ki_modelle.pool_anzeigename("gemini-flash") == name
    assert ki_modelle.pool_anzeigename("gemini-3.8-flash") == ""


@pytest.mark.skipif(not QUELLE.exists(), reason="AI Worker nicht ausgecheckt")
def test_kopie_entspricht_dem_register_im_ai_worker():
    assert REGISTER.read_text() == QUELLE.read_text(), (
        "Veraltete Kopie: `ki-modelle anwenden` laufen lassen und ausrollen")
