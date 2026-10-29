#!/usr/bin/env python3
"""Auf Clivias Mac: nur erlaubte Konfig-/Schluessel-/Zustandspfade beschreiben.

Parameter sind ausschliesslich oeffentlich: Web-IP und verifizierter Hostkey.
Der noch unbekannte Konto-Identifier wird beim Erstlauf authentifiziert bezogen.
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
sys.dont_write_bytecode = True


def modul():
    p = Path.home() / 'Projects/Clivia/tools/pocketclot_wissen.py'
    spec = importlib.util.spec_from_file_location('clivia_pocketclot_wissen', p)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


def fest(m, p, roh):
    m.keine_links(p)
    if p.exists():
        if p.read_bytes() != roh:
            raise ValueError('Bestehende Konfiguration weicht ab; nicht ersetzt')
    else:
        m.atomar(p, roh)
    p.chmod(0o600)


def main():
    os.umask(0o077)
    m = modul()
    home = Path.home()
    cfg = home / '.config/clivia'
    for p in (cfg, cfg / 'geheim', home / '.ssh', home / '.local/state/clivia/pocketclot'):
        m.privat_ordner(p)
    if (cfg / 'NOTAUS').exists():
        raise ValueError('Notaus aktiv')
    web_ip, hostkey = sys.argv[1:]
    import ipaddress
    if ipaddress.ip_address(web_ip) not in ipaddress.ip_network('100.64.0.0/10'):
        raise ValueError('Web muss Tailscale-IPv4 sein')
    typ, wert, *_ = hostkey.split()
    if typ != 'ssh-ed25519':
        raise ValueError('Ed25519-Hostkey erwartet')
    fest(m, cfg / 'pocketclot-known_hosts', f'{web_ip} {typ} {wert}\n'.encode())
    fest(m, cfg / 'pocketclot-ssh.conf', (
        f'Host web\n    HostName {web_ip}\n    User lilith\n    Port 22\n'
        '    UserKnownHostsFile ~/.config/clivia/pocketclot-known_hosts\n'
        '    StrictHostKeyChecking yes\n    IdentitiesOnly yes\n    BatchMode yes\n').encode())
    datei = cfg / 'pocketclot.json'
    m.keine_links(datei)
    if not datei.exists():
        m.atomar(datei, b'{"user_id": null, "einrichtung": "Konto-ID beim authentifizierten Erstlauf beziehen"}\n')
    datei.chmod(0o600)
    daten = json.loads(datei.read_text())
    uid = daten.get('user_id')
    if uid is not None and not m.UID.fullmatch(uid):
        raise ValueError('Vorhandene Konto-ID ungueltig')
    for art in ('liefern', 'abholen'):
        key = home / '.ssh' / f'pocketclot_{art}'
        m.keine_links(key)
        m.keine_links(key.with_suffix('.pub'))
        if not key.exists():
            if key.with_suffix('.pub').exists():
                raise ValueError('Private SSH-Datei fehlt, keine automatische Rotation')
            subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(key),
                            '-C', f'pocketclot-clivia-{art}'], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        key.chmod(0o600)
        pub = b' '.join(subprocess.check_output(['ssh-keygen', '-y', '-P', '', '-f', str(key)], stderr=subprocess.DEVNULL).split()[:2])
        if key.with_suffix('.pub').exists():
            if b' '.join(key.with_suffix('.pub').read_bytes().split()[:2]) != pub:
                raise ValueError('SSH-Schluesselpaar passt nicht')
        else:
            m.atomar(key.with_suffix('.pub'), pub + b'\n')
    # Nur fuer die vorbereitende Paketfunktion: sie bindet keine Chats an diese ID.
    # Die native CLI bleibt durch user_id=null bis zum Erstlauf sicher gesperrt.
    p = m.Pfade(home / 'Projects/Clivia', home, uid or 'usr_einrichtung_ausstehend')
    with m.sperre(p) as frei:
        if not frei:
            raise ValueError('Anderer Lauf aktiv')
        oeffentlich = m.export_oeffentlich(p.export_key, erzeugen=not (p.zustand / 'freigabe.json').exists())
        m.atomar(cfg / 'pocketclot-export.pub', (oeffentlich + '\n').encode())
        roh = m.paket(p)
    print(f'Vorbereitet: zwei SSH-Schluessel, Exportempfaenger, AES-Schluessel, Paket {len(roh)} Byte.')
    print('Konto-ID ' + ('vorhanden.' if uid else 'wird nach Serverinstallation authentifiziert uebernommen.'))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('Mac-Vorbereitung fehlgeschlagen: ' + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
