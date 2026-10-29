#!/usr/bin/env python3
"""Zwangsbefehl mit FESTEN Kontoargumenten aus authorized_keys, nie vom Client.

Fuer Clivia genau eine ID, fuer aihub ausschliesslich die bisherigen zwei IDs.
Kein Clientargument und kein SSH_ORIGINAL_COMMAND wird ausgewertet.
"""
import base64
import json
from pathlib import Path
import re
import sys

ORDNER = Path('/opt/pocket-claude/wissen')
MAX = 100 * 1024**2
# Base64 plus JSON muss unter wissen_kati.MAX_TRANSPORT (150 MiB) bleiben.
GESAMT = 110 * 1024**2


def abholen(ordner, erlaubt):
    if not erlaubt or any(not re.fullmatch(r'usr_[A-Za-z0-9_-]{1,80}', u) for u in erlaubt):
        raise ValueError('Feste Kontobindung fehlt')
    # Fehlend/kaputt ist ein Fehler, kein stiller Widerruf.
    konten = json.loads((ordner / 'konten.json').read_text())['konten']
    if not isinstance(konten, dict):
        raise ValueError('Kontenliste ungueltig')
    frei, aus, summe = [], [], 0
    for uid in sorted(set(erlaubt)):
        e = konten.get(uid, {})
        if not isinstance(e, dict):
            raise ValueError('Kontoeintrag ungueltig')
        if e.get('export') is not True:
            continue
        frei.append(uid)
        p = ordner / 'aus' / f'{uid}.export'
        if p.is_symlink():
            raise ValueError('Verknuepfung unzulaessig')
        if not p.exists():
            continue
        if p.stat().st_size > MAX:
            raise ValueError('Export zu gross')
        roh = p.read_bytes()
        summe += len(roh)
        if len(roh) > MAX or summe > GESAMT or not roh.startswith(b'PCX1'):
            raise ValueError('Export ungueltig')
        aus.append({'konto': uid, 'daten': base64.b64encode(roh).decode()})
    return {'freigegeben': frei, 'exporte': aus}


if __name__ == '__main__':
    try:
        json.dump(abholen(ORDNER, sys.argv[1:]), sys.stdout)
    except Exception:
        sys.exit('Abholen abgelehnt')
