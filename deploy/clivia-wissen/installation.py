#!/usr/bin/env python3
"""Validierte, gesicherte Installation. Keine Zugangsdaten und kein DB-Schreiben."""
from __future__ import annotations

import base64
import datetime
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import shlex
import signal
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request

BASIS = Path('/opt/pocket-claude')
WISSEN = BASIS / 'wissen'
AUTH = Path('/home/lilith/.ssh/authorized_keys')
BACKUPS = Path('/var/backups/pocketclot-clivia')
UID = re.compile(r'usr_[A-Za-z0-9_-]{1,80}')
ALTE_HASHES = {
    'wissen_export.py': '8e6fbede4a71b5bcb664b2a59286385bf3de68e3aeccaf8c60d462fa31a26756',
    'wissen_tool.py': '422fbc3ae24ff7376406f5b2b9e762443ebd133281628b7210d2aabbff8da114',
}


def pruefe(bedingung, text):
    if not bedingung:
        raise ValueError(text)


def sha(roh):
    return hashlib.sha256(roh).hexdigest()


def ohne_links(p):
    for teil in (p, *p.parents):
        pruefe(not teil.is_symlink(), 'Symlink im Installationspfad')
    return p


class Umgebung:
    def __init__(self):
        test = os.environ.get('CLIVIA_TEST_ROOT')
        self.test = bool(test)
        self.root = Path(test) if test else Path('/')
        pruefe(self.root.is_absolute(), 'Testwurzel muss absolut sein')
        ohne_links(self.root)
        if test:
            pruefe(self.root != Path('/') and
                   (self.root / '.clivia-test-root').read_text().strip() == 'Nur lokale Tests',
                   'Testwurzel nicht freigegeben')
        else:
            pruefe(os.geteuid() == 0, 'Mit sudo bash einrichten.sh ausfuehren')
        self.systemctl = str(self.p('/bin/systemctl')) if test else '/usr/bin/systemctl'

    def p(self, absolut):
        p = Path(absolut)
        pruefe(p.is_absolute() and '..' not in p.parts, 'Ungueltiger Zielpfad')
        return ohne_links(self.root / p.relative_to('/'))

    def dienst(self, aktion):
        subprocess.run([self.systemctl, aktion, 'pocket-claude'], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90)

    def bereit(self):
        # Type=simple meldet active schon vor abgeschlossener ASGI-Initialisierung.
        # Testmodus liest nur die nachgebaute Healthdatei, niemals einen Live-Port.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(30):
            try:
                self.dienst('is-active')
                if self.test:
                    antwort = self.p('/dienst-health.json').read_bytes()
                else:
                    with opener.open('http://127.0.0.1:8787/health', timeout=1) as r:
                        antwort = r.read(4097)
                pruefe(len(antwort) <= 4096, 'Dienstantwort zu gross')
                d = json.loads(antwort)
                if d.get('status') == 'ok' and d.get('db_ok') is True:
                    self.dienst('is-active')
                    return
            except (OSError, ValueError, AttributeError, subprocess.SubprocessError):
                pass
            if not self.test:
                time.sleep(1)
        raise ValueError('Dienst nicht betriebsbereit; Ruecknahme erforderlich')


def atomar(p, roh, modus, uid=None, gid=None):
    ohne_links(p)
    fd, name = tempfile.mkstemp(prefix='.clivia-install-', dir=p.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(roh)
            f.flush()
            os.fsync(f.fileno())
            if uid is not None and os.geteuid() == 0:
                os.fchown(f.fileno(), uid, gid)
            os.fchmod(f.fileno(), modus)
        os.replace(name, p)
    finally:
        Path(name).unlink(missing_ok=True)


def public_ssh(p):
    text = p.read_text().strip().split()
    pruefe(len(text) in (2, 3) and text[0] == 'ssh-ed25519', 'Nur oeffentliche Ed25519-Schluessel erlaubt')
    try:
        roh = base64.b64decode(text[1], validate=True)
    except ValueError:
        raise ValueError('Ungueltiger oeffentlicher SSH-Schluessel') from None
    typ = b'ssh-ed25519'
    pruefe(roh == struct.pack('>I', len(typ)) + typ + struct.pack('>I', 32) + roh[-32:]
           and len(roh) == 51, 'Ungueltiger Ed25519-Schluessel')
    return 'ssh-ed25519 ' + text[1]


def schluessel_in_zeile(zeile):
    if not zeile.strip() or zeile.lstrip().startswith('#'):
        return None
    # OpenSSH akzeptiert Tabs/mehrere Leerzeichen. Optionen koennen selbst
    # zitierte Leerzeichen enthalten; Kommentare nach dem Key werden nicht geparst.
    lexer = shlex.shlex(zeile, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ''
    try:
        typ = next(lexer, '')
        if typ != 'ssh-ed25519':
            typ = next(lexer, '')
        if typ != 'ssh-ed25519':
            return None
        blob = next(lexer, '')
    except ValueError:
        raise ValueError('SSH-Zeile vor dem Schluessel ungueltig') from None
    pruefe(re.fullmatch(r'[A-Za-z0-9+/=]+', blob), 'SSH-Public-Key ungueltig')
    return 'ssh-ed25519 ' + blob


def autorisierung(alt, uid, aihub_ids, liefern, abholen, ip):
    pruefe(liefern != abholen, 'Getrennte SSH-Schluessel erforderlich')
    zeilen = alt.splitlines()
    # Der alte kontouebergreifende Befehl darf fuer KEINEN Schluessel erreichbar bleiben.
    alt_befehl = str(WISSEN / 'abholen.sh')
    neu_befehl = str(WISSEN / 'konto-abholen.py')
    kandidaten = [i for i, z in enumerate(zeilen) if not z.lstrip().startswith('#') and
                  (alt_befehl in z or (neu_befehl in z and 'aihub-wissen-abholen' in z))]
    pruefe(len(kandidaten) == 1, 'Genau eine bisherige aihub-Abholzeile erwartet')
    i = kandidaten[0]
    z = zeilen[i]
    pruefe('restrict' in z and re.search(r'from="[^"]+"', z), 'aihub-from/restrict fehlt')
    aihub_key = schluessel_in_zeile(z)
    pruefe(aihub_key is not None and aihub_key not in (liefern, abholen), 'SSH-Schluessel kollidieren')
    pruefe(sum(schluessel_in_zeile(x) == aihub_key for x in zeilen) == 1,
           'aihub-Abholschluessel mehrfach vorhanden')
    kommando = neu_befehl + ' ' + ' '.join(aihub_ids)
    pruefe(len(re.findall(r'command="[^"]*"', z)) == 1, 'aihub-Zwangsbefehl unklar')
    z = re.sub(r'command="[^"]*"', lambda m: 'command="' + kommando + '"', z)
    if 'aihub-wissen-abholen' not in z:
        z += ' aihub-wissen-abholen'
    zeilen[i] = z
    neue = []
    for key, befehl, kommentar in (
        (liefern, str(WISSEN / 'clivia-empfangen.py'), 'clivia-wissen-liefern'),
        (abholen, neu_befehl + ' ' + uid, 'clivia-wissen-abholen'),
    ):
        erwartet = f'from="{ip}",command="{befehl}",restrict {key} {kommentar}'
        for s in zeilen:
            if schluessel_in_zeile(s) == key or kommentar in s:
                pruefe(s == erwartet, 'Clivia-Schluessel schon anders freigegeben')
        if erwartet not in zeilen:
            neue.append(erwartet)
    return ('\n'.join(zeilen + neue) + '\n').encode()


def plan(u, paket):
    upload = ohne_links(paket / 'upload')
    liefern = public_ssh(ohne_links(upload / 'liefern.pub'))
    abholen = public_ssh(ohne_links(upload / 'abholen.pub'))
    pub = ohne_links(upload / 'export.pub').read_text().strip()
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
    try:
        k = base64.b64decode(pub + '=' * (-len(pub) % 4), altchars=b'-_', validate=True)
        pruefe(len(k) == 32, 'X25519-Empfaenger ungueltig')
        X25519PrivateKey.generate().exchange(X25519PublicKey.from_public_bytes(k))
    except ValueError:
        raise ValueError('X25519-Empfaenger ungueltig') from None
    ip = ohne_links(upload / 'from-ip.txt').read_text().strip()
    try:
        gueltige_ip = ipaddress.ip_address(ip) in ipaddress.ip_network('100.64.0.0/10')
    except ValueError:
        gueltige_ip = False
    pruefe(gueltige_ip, 'Tailscale-IPv4 erforderlich')
    # Ausschliesslich readonly; bewusst nur ID/Name, keine Passwort-/Token-Spalten.
    datenbank = u.p(BASIS / 'data/pocket_claude.db')
    sqlite = '/usr/bin/sqlite3'
    antwort = subprocess.check_output([sqlite, '-readonly', '-json', str(datenbank),
        "SELECT id, name FROM users WHERE lower(name) = 'clivia';"], stderr=subprocess.DEVNULL, timeout=20)
    treffer = json.loads(antwort or b'[]')
    pruefe(len(treffer) == 1 and UID.fullmatch(treffer[0]['id']), 'Konto clivia nicht eindeutig')
    uid = treffer[0]['id']
    konten_p = u.p(WISSEN / 'konten.json')
    bestand = json.loads(konten_p.read_text())
    konten = bestand['konten']
    pruefe(isinstance(konten, dict), 'Kontenliste ungueltig')
    # Die vorherige Pipeline umfasst genau diese Paketbindungen. Keine stille Freigabe weiterer Konten.
    aihub_ids = []
    for name in ('wissen.paket', 'kati.paket'):
        ids = [i for i, e in konten.items() if isinstance(e, dict) and e.get('paket') == name]
        pruefe(len(ids) == 1 and UID.fullmatch(ids[0]) and ids[0] != uid,
               'Joscha/Kati nicht eindeutig zugeordnet')
        aihub_ids.append(ids[0])
    eintrag = {'paket': 'clivia.paket', 'export': True, 'export_empfaenger': pub}
    if uid in konten:
        pruefe(konten[uid] == eintrag, 'Clivia-Eintrag vorhanden und abweichend')
    pruefe(not any(i != uid and e.get('paket') == 'clivia.paket' for i, e in konten.items()),
           'Clivia-Paket schon einem anderen Konto zugeordnet')
    konten[uid] = eintrag
    a = autorisierung(u.p(AUTH).read_text(), uid, aihub_ids, liefern, abholen, ip)
    dateien = [(AUTH, a, 0o600),
               (WISSEN / 'konten.json', (json.dumps(bestand, indent=2) + '\n').encode(), 0o644)]
    for name, alt_hash in ALTE_HASHES.items():
        quelle = ohne_links(paket / 'server-module' / name)
        roh = quelle.read_bytes()
        compile(roh, name, 'exec')
        ziel = BASIS / 'pocket_claude' / name
        pruefe(sha(u.p(ziel).read_bytes()) in (alt_hash, sha(roh)),
               'Server-Modul wurde zwischenzeitlich geaendert; neu pruefen')
        dateien.append((ziel, roh, 0o644))
    for name, zielname in (('abholen.py', 'konto-abholen.py'), ('empfangen.py', 'clivia-empfangen.py')):
        roh = ohne_links(paket / name).read_bytes()
        compile(roh, name, 'exec')
        ziel = WISSEN / zielname
        if u.p(ziel).exists():
            pruefe(u.p(ziel).read_bytes() == roh, 'Vorhandenes Transportskript weicht ab')
        dateien.append((ziel, roh, 0o755))
    return uid, dateien


def sichern(u, dateien):
    basis = u.p(BACKUPS)
    basis.mkdir(parents=True, exist_ok=True, mode=0o700)
    basis.chmod(0o700)
    backup = Path(tempfile.mkdtemp(prefix=datetime.datetime.now().strftime('%Y%m%d-%H%M%S-'), dir=basis))
    m = {'wurzel': str(u.root), 'dateien': [], 'status': 'vorbereitet'}
    for i, (rel, roh, modus) in enumerate(dateien):
        p = u.p(rel)
        e = {'pfad': str(rel), 'backup': str(i), 'installiert_sha256': sha(roh), 'vorhanden': p.exists()}
        if p.exists():
            pruefe(p.is_file(), 'Zieldatei ist keine regulaere Datei')
            s = p.stat()
            shutil.copy2(p, backup / str(i))
            e.update(uid=s.st_uid, gid=s.st_gid, modus=s.st_mode & 0o7777, vorher_sha256=sha(p.read_bytes()))
        m['dateien'].append(e)
    manifest(backup, m)
    return backup, m


def manifest(backup, m):
    atomar(backup / 'manifest.json', (json.dumps(m, indent=2) + '\n').encode(), 0o600)


def ruecknahme(u, backup):
    ohne_links(backup)
    pruefe(backup.parent == u.p(BACKUPS), 'Backup ausserhalb der vorgesehenen Ablage')
    m = json.loads((backup / 'manifest.json').read_text())
    pruefe(m['wurzel'] == str(u.root), 'Backup gehoert zu anderer Installation')
    if m['status'] == 'zurueckgenommen':
        u.dienst('is-active')
        return
    erlaubt = {str(AUTH), str(WISSEN / 'konten.json'),
               *(str(BASIS / 'pocket_claude' / n) for n in ALTE_HASHES),
               str(WISSEN / 'konto-abholen.py'), str(WISSEN / 'clivia-empfangen.py')}
    pruefe({e['pfad'] for e in m['dateien']} == erlaubt and len(m['dateien']) == len(erlaubt),
           'Backupmanifest ungueltig')
    for i, e in enumerate(m['dateien']):
        pruefe(e['backup'] == str(i), 'Backuppfad ungueltig')
        p = u.p(e['pfad'])
        if p.exists():
            pruefe(sha(p.read_bytes()) in (e['installiert_sha256'], e.get('vorher_sha256')),
                   'Datei seit Installation geaendert; Ruecknahme wuerde fremde Arbeit ueberschreiben')
        if e['vorhanden']:
            pruefe(sha(ohne_links(backup / str(i)).read_bytes()) == e['vorher_sha256'], 'Backup beschaedigt')
    # Erst Freigabe entziehen, dann den alten breiten Abholbefehl wieder erreichbar machen.
    u.dienst('stop')
    for e in sorted(m['dateien'], key=lambda e: (e['pfad'] != str(WISSEN / 'konten.json'), e['pfad'] == str(AUTH))):
        p = u.p(e['pfad'])
        if e['vorhanden']:
            atomar(p, (backup / e['backup']).read_bytes(), e['modus'], e['uid'], e['gid'])
        else:
            p.unlink(missing_ok=True)
    u.dienst('restart')
    u.bereit()
    m['status'] = 'zurueckgenommen'
    manifest(backup, m)


def einrichten(u, paket):
    uid, dateien = plan(u, paket)
    u.dienst('is-active')
    backup, m = sichern(u, dateien)
    print('Sicherung: ' + str(backup), flush=True)
    try:
        u.dienst('stop')
        for e, (rel, roh, modus) in zip(m['dateien'], dateien):
            # Bestehende Eigentuemer bewahren; neue Skripte root gehoeren lassen.
            atomar(u.p(rel), roh, modus, e.get('uid', 0), e.get('gid', 0))
        u.dienst('restart')
        u.bereit()
        m['status'] = 'installiert'
        manifest(backup, m)
    except BaseException:
        print('Einrichtung fehlgeschlagen, stelle Sicherung wieder her.', file=sys.stderr)
        # Ein zweites TERM-Signal darf die laufende Ruecknahme nicht unterbrechen.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        try:
            ruecknahme(u, backup)
        except BaseException:
            print('Ruecknahme fehlgeschlagen. Dienst und Sicherung manuell pruefen: ' + str(backup), file=sys.stderr)
        raise
    print('Installiert; Dienst aktiv; Clivias Konto-ID: ' + uid)
    print('Keine Automatik aktiviert. Erstlauf auf Clivias Mac ausfuehren.')


def main():
    u = Umgebung()
    backup_basis = u.p(BACKUPS)
    backup_basis.mkdir(parents=True, exist_ok=True, mode=0o700)
    with ohne_links(backup_basis / '.installation.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        def abbruch(*_):
            raise InterruptedError('Abbruchsignal')
        signal.signal(signal.SIGTERM, abbruch)
        aktion, ort = sys.argv[1:]
        if aktion == 'einrichten':
            einrichten(u, ohne_links(Path(ort).absolute()))
        elif aktion == 'zuruecknehmen':
            ruecknahme(u, Path(ort).absolute())
        else:
            raise ValueError('Unbekannte Aktion')


if __name__ == '__main__':
    try:
        main()
    except (Exception, KeyboardInterrupt) as exc:
        # Keine Pfad-/SQL-/Konfiginhalte aus beliebigen Exceptions protokollieren.
        print('Abgebrochen: ' + type(exc).__name__ + (': ' + str(exc) if isinstance(exc, ValueError) else ''), file=sys.stderr)
        sys.exit(1)
