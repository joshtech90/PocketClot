#!/usr/bin/env python3
"""Nach Serverinstallation: Konto binden, abholen/chats/liefern. Kein LaunchAgent."""
import json
from pathlib import Path
import re
import sys
sys.dont_write_bytecode = True
import time


def konto_bindung(daten, bisher):
    frei = daten.get('freigegeben')
    if not isinstance(frei, list) or len(frei) != 1 or not isinstance(frei[0], str) or not re.fullmatch(r'usr_[A-Za-z0-9_-]{1,80}', frei[0]):
        raise ValueError('Genau ein freigegebenes Konto erwartet')
    if bisher not in (None, frei[0]):
        raise ValueError('Vorhandene Konto-ID darf nicht wechseln')
    if not isinstance(daten.get('exporte'), list) or len(daten['exporte']) > 1 or any(e.get('konto') != frei[0] for e in daten['exporte']):
        raise ValueError('Fremder Export abgelehnt')
    return frei[0]


def main():
    home = Path.home()
    cfg = home / '.config/clivia'
    if (cfg / 'NOTAUS').exists():
        raise ValueError('Notaus aktiv')
    # Vorbereitungsmodul enthaelt nur Hilfsfunktionen, keine Seiteneffekte beim Import.
    import importlib.util
    spec = importlib.util.spec_from_file_location('mac_vorbereitung', cfg / 'pocketclot-vorbereiten.py')
    vor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vor)
    m = vor.modul()
    datei = cfg / 'pocketclot.json'
    m.keine_links(datei)
    konfig = json.loads(datei.read_text())
    # SSH-Verbindung ist durch eigenen Key, from=, forced command und gepinnten Hostkey gebunden.
    p = m.Pfade(home / 'Projects/Clivia', home, konfig.get('user_id') or 'usr_einrichtung_ausstehend')
    with m.sperre(p) as frei:
        if not frei:
            raise ValueError('Anderer Lauf aktiv')
        roh = m.ssh(p, 'abholen')
        if len(roh) > m.MAX_TRANSPORT:
            raise ValueError('Antwort zu gross')
        antwort = json.loads(roh)
        konfig['user_id'] = konto_bindung(antwort, konfig.get('user_id'))
        konfig.pop('einrichtung', None)
        m.atomar(datei, (json.dumps(konfig) + '\n').encode())
        p = m.Pfade(p.repo, home, konfig['user_id'])
        # Exportlauf startet 90s nach Dienststart. Warten ist unter derselben
        # Laufsperre wie alle drei Originalimplementierungen; kein stiller CLI-Skip.
        for versuch in range(13):
            if antwort.get('exporte'):
                break
            if versuch == 12:
                raise ValueError('Export noch nicht bereit; Erstlauf spaeter erneut starten')
            time.sleep(10)
            antwort = json.loads(m.ssh(p, 'abholen'))
            konto_bindung(antwort, konfig['user_id'])
        p.pruefe_notaus()
        print(f'Abgeholt: {m.abholen(p)} Chats')
        p.pruefe_notaus()
        print(f'Ausgewertet: {m.chats(p)} geaenderte Chats')
        p.pruefe_notaus()
        m.liefern(p)
        print('Paket geliefert.')
    print('Erstlauf erfolgreich. Automatik bleibt ausgeschaltet.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('Erstlauf fehlgeschlagen: ' + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
