"""Kontotrennung, unveraenderter Leben-Abholer und echte lokale Installation."""
import ast
import base64
import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

REPO = Path(__file__).resolve().parents[2]
DEPLOY = REPO / 'deploy/clivia-wissen'


def laden(name):
    spec = importlib.util.spec_from_file_location('clivia_' + name, DEPLOY / (name + '.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def ssh_pub():
    return Ed25519PrivateKey.generate().public_key().public_bytes(
        serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode()


@pytest.fixture
def baum(tmp_path):
    root = tmp_path / 'web'
    root.mkdir()
    (root / '.clivia-test-root').write_text('Nur lokale Tests\n')
    def p(name):
        z = root / name.lstrip('/')
        z.parent.mkdir(parents=True, exist_ok=True)
        return z
    db = p('/opt/pocket-claude/data/pocket_claude.db')
    with sqlite3.connect(db) as c:
        c.execute('CREATE TABLE users (id TEXT, name TEXT)')
        c.execute("INSERT INTO users VALUES ('usr_clivia', 'ClIvIa')")
    konten = {'export_empfaenger': 'global-unveraendert', 'unbekannte_option': [1, 2], 'konten': {
        'usr_joscha': {'paket': 'wissen.paket', 'extra': 'behalten'},
        'usr_kati': {'paket': 'kati.paket', 'export': True},
        'usr_andere': {'paket': 'andere.paket', 'export': True}}}
    p('/opt/pocket-claude/wissen/konten.json').write_text(json.dumps(konten))
    for name in ('wissen_export.py', 'wissen_tool.py'):
        shutil.copy2(REPO / 'server/pocket_claude' / name, p('/opt/pocket-claude/pocket_claude/' + name))
    auth = p('/home/lilith/.ssh/authorized_keys')
    auth.write_text('# Bestehende Schluessel\n' + ssh_pub() + ' shell-behalten\n' +
        'from="100.64.0.2",command="/opt/pocket-claude/wissen/abholen.sh",restrict ' + ssh_pub() + ' aihub-wissen-abholen\n' +
        'from="100.64.0.2",command="/opt/pocket-claude/wissen/empfangen.sh",restrict ' + ssh_pub() + ' aihub-wissen-paket\n')
    auth.chmod(0o600)
    ctl = p('/bin/systemctl')
    ctl.write_text('''#!/usr/bin/env python3
from pathlib import Path
import json,sys
r = Path(__file__).resolve().parents[1]
a = sys.argv[1]
with (r / 'dienst.log').open('a') as f:
    f.write(a + '\\n')
if a == 'restart' and (r / 'fail-restart').exists():
    (r / 'fail-restart').unlink()
    sys.exit(1)
if a == 'restart':
    kaputt = (r / 'fail-health').exists()
    (r / 'fail-health').unlink(missing_ok=True)
    (r / 'dienst-health.json').write_text(json.dumps({'status': 'ok', 'db_ok': not kaputt}))
''')
    ctl.chmod(0o755)
    paket = tmp_path / 'uploadordner'
    shutil.copytree(DEPLOY, paket, ignore=shutil.ignore_patterns('upload', '__pycache__'))
    (paket / 'upload').mkdir()
    for n in ('liefern', 'abholen'):
        (paket / 'upload' / (n + '.pub')).write_text(ssh_pub() + '\n')
    key = X25519PrivateKey.generate()
    (paket / 'upload/export.pub').write_text(base64.urlsafe_b64encode(key.public_key().public_bytes_raw()).decode().rstrip('='))
    (paket / 'upload/from-ip.txt').write_text('100.64.0.3\n')
    shutil.copytree(REPO / 'server/pocket_claude', paket / 'server-module',
                    ignore=lambda _, names: [n for n in names if n not in ('wissen_export.py', 'wissen_tool.py')])
    vor = {str(z.relative_to(root)): (z.read_bytes(), z.stat().st_mode & 0o7777) for z in root.rglob('*') if z.is_file()}
    return SimpleNamespace(root=root, p=p, paket=paket, vor=vor, db=db, konten=konten, auth=auth)


def ausfuehren(b, script='einrichten.sh', *args):
    return subprocess.run(['bash', str(b.paket / script), *map(str, args)],
                          env={**os.environ, 'CLIVIA_TEST_ROOT': str(b.root), 'PYTHONDONTWRITEBYTECODE': '1'},
                          capture_output=True, text=True, timeout=30)


def alter_stand(b):
    for rel, (roh, modus) in b.vor.items():
        assert (b.root / rel).read_bytes() == roh, rel
        assert (b.root / rel).stat().st_mode & 0o7777 == modus, rel
    assert not b.p('/opt/pocket-claude/wissen/konto-abholen.py').exists()
    assert not b.p('/opt/pocket-claude/wissen/clivia-empfangen.py').exists()


def test_installation_idempotent_und_exakte_ruecknahme(baum):
    b = baum
    r = ausfuehren(b)
    assert r.returncode == 0, r.stderr
    backup = next(b.p('/var/backups/pocketclot-clivia').glob('*/manifest.json')).parent
    neu = json.loads(b.p('/opt/pocket-claude/wissen/konten.json').read_text())
    assert {k: v for k, v in neu.items() if k != 'konten'} == {k: v for k, v in b.konten.items() if k != 'konten'}
    assert {k: v for k, v in neu['konten'].items() if k != 'usr_clivia'} == b.konten['konten']
    assert neu['konten']['usr_clivia']['export'] is True
    zeilen = b.auth.read_text().splitlines()
    assert zeilen[:2] == b.vor['home/lilith/.ssh/authorized_keys'][0].decode().splitlines()[:2]
    aihub = next(z for z in zeilen if z.endswith('aihub-wissen-abholen'))
    assert 'konto-abholen.py usr_joscha usr_kati"' in aihub
    assert 'from="100.64.0.2"' in aihub and ',restrict ' in aihub
    assert '/wissen/abholen.sh' not in b.auth.read_text()
    assert any('konto-abholen.py usr_clivia"' in z and 'from="100.64.0.3"' in z for z in zeilen)
    for name in ('wissen_export.py', 'wissen_tool.py'):
        assert b.p('/opt/pocket-claude/pocket_claude/' + name).read_bytes() == (REPO / 'server/pocket_claude' / name).read_bytes()
    installiert = b.auth.read_bytes()
    r = ausfuehren(b)
    assert r.returncode == 0, r.stderr
    assert b.auth.read_bytes() == installiert
    assert hashlib.sha256(b.db.read_bytes()).digest() == hashlib.sha256(b.vor['opt/pocket-claude/data/pocket_claude.db'][0]).digest()
    r = ausfuehren(b, 'zuruecknehmen.sh', backup)
    assert r.returncode == 0, r.stderr
    alter_stand(b)
    assert ausfuehren(b, 'zuruecknehmen.sh', backup).returncode == 0


@pytest.mark.parametrize('fehler', ['fail-restart', 'fail-health'])
def test_dienstfehler_stellt_alle_dateien_wieder_her(baum, fehler):
    b = baum
    (b.root / fehler).touch()
    r = ausfuehren(b)
    assert r.returncode != 0
    alter_stand(b)
    manifest = next(b.p('/var/backups/pocketclot-clivia').glob('*/manifest.json'))
    assert json.loads(manifest.read_text())['status'] == 'zurueckgenommen'
    assert (b.root / 'dienst.log').read_text().splitlines()[-2:] == ['is-active', 'is-active']


@pytest.mark.parametrize('fall', ['kein-konto', 'zwei-konten', 'doppelter-key', 'doppelter-key-tab', 'doppelter-key-spaces', 'clivia-key-tab', 'symlink', 'fremdes-modul', 'falscher-empfaenger'])
def test_ungueltige_voraussetzungen_aendern_nichts(baum, fall):
    b = baum
    if fall in ('kein-konto', 'zwei-konten'):
        with sqlite3.connect(b.db) as c:
            if fall == 'kein-konto':
                c.execute('DELETE FROM users')
            else:
                c.execute("INSERT INTO users VALUES ('usr_doppelt', 'clivia')")
    elif fall.startswith('doppelter-key') or fall == 'clivia-key-tab':
        z = b.auth.read_text().splitlines()[2].split('restrict ')[1]
        if fall == 'clivia-key-tab':
            z = (b.paket / 'upload/abholen.pub').read_text().strip()
        if fall.endswith('tab'):
            z = z.replace('ssh-ed25519 ', 'ssh-ed25519\t')
        elif fall.endswith('spaces'):
            z = z.replace('ssh-ed25519 ', 'ssh-ed25519  ')
        b.auth.write_text(b.auth.read_text() + z + '\n')
    elif fall == 'symlink':
        (b.paket / 'upload/export.pub').unlink()
        (b.paket / 'upload/export.pub').symlink_to(b.auth)
    elif fall == 'fremdes-modul':
        b.p('/opt/pocket-claude/pocket_claude/wissen_tool.py').write_text('# fremde Aenderung\n')
    else:
        (b.paket / 'upload/export.pub').write_text(base64.urlsafe_b64encode(bytes(32)).decode())
    vorher = {str(p): p.read_bytes() for p in b.root.rglob('*') if p.is_file()}
    r = ausfuehren(b)
    assert r.returncode != 0
    for p, roh in vorher.items():
        assert Path(p).read_bytes() == roh
    assert not (b.root / 'dienst.log').exists()


def test_ruecknahme_ueberschreibt_keine_spaeteren_aenderungen(baum):
    b = baum
    assert ausfuehren(b).returncode == 0
    backup = next(b.p('/var/backups/pocketclot-clivia').glob('*/manifest.json')).parent
    b.auth.write_text(b.auth.read_text() + '# spaeter hinzugefuegt\n')
    vorher = b.auth.read_bytes()
    assert ausfuehren(b, 'zuruecknehmen.sh', backup).returncode != 0
    assert b.auth.read_bytes() == vorher


def test_transport_nimmt_nur_clivias_paket_an(tmp_path):
    empfang = laden('empfangen')
    paket = b'PCW1' + b'x' * 40
    def huelle(name):
        return f'PCW1-HUELLE {len(paket)} {hashlib.sha256(paket).hexdigest()} {name}\n'.encode() + paket
    for name in ('kati', 'wissen'):
        with pytest.raises(ValueError):
            empfang.empfangen(tmp_path, io.BytesIO(huelle(name)), io.StringIO())
    ausgabe = io.StringIO()
    empfang.empfangen(tmp_path, io.BytesIO(huelle('clivia')), ausgabe)
    assert (tmp_path / 'clivia.paket').read_bytes() == paket
    assert not (tmp_path / 'kati.paket').exists()


def test_mac_bootstrap_lehnt_fremde_oder_mehrere_konten_ab():
    m = laden('mac-erstlauf')
    assert m.konto_bindung({'freigegeben': ['usr_clivia'], 'exporte': []}, None) == 'usr_clivia'
    for daten, bisher in [({'freigegeben': ['usr_kati', 'usr_clivia'], 'exporte': []}, None),
                          ({'freigegeben': ['usr_kati'], 'exporte': []}, 'usr_clivia'),
                          ({'freigegeben': ['usr_clivia'], 'exporte': [{'konto': 'usr_kati'}]}, None)]:
        with pytest.raises(ValueError):
            m.konto_bindung(daten, bisher)


def test_unveraendertes_wissen_kati_verarbeitet_neues_format_und_widerruf(monkeypatch, tmp_path):
    monkeypatch.setenv('SERVER_TOKEN', 'x' * 40)
    from pocket_claude import wissen_export
    abholer = laden('abholen')
    leben = Path(os.environ.get('LEBEN_REPO', Path.home() / 'Projects/Leben'))
    quelle = leben / 'tools/wissen_kati.py'
    if not quelle.is_file():
        pytest.skip('Optionaler Originalquelltext: LEBEN_REPO setzen')
    # Exakte, unveraenderte Originalfunktionen; keine projektfremden Import-Seiteneffekte.
    a = ast.parse(quelle.read_text())
    namen = {'_export_privat', 'entsiegeln', 'chat_pfad', 'abholen', 'widerrufen', '_cache', '_cache_setzen'}
    funcs = [n for n in a.body if isinstance(n, ast.FunctionDef) and n.name in namen]
    assert len(funcs) == len(namen)
    chats, roh, geteilt = (tmp_path / p for p in ('chats', 'roh', 'geteilt'))
    for p in (chats, roh, geteilt):
        p.mkdir()
    key = X25519PrivateKey.generate()
    keyfile = tmp_path / 'synthetischer-test.key'
    keyfile.write_text(base64.urlsafe_b64encode(key.private_bytes_raw()).decode().rstrip('='))
    def atomar(p, text):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    ns = dict(base64=base64, gzip=gzip, json=json, os=os, re=__import__('re'), Path=Path,
              subprocess=SimpleNamespace(run=None, DEVNULL=subprocess.DEVNULL, TimeoutExpired=subprocess.TimeoutExpired),
              EXPORT_PRIVAT=keyfile, EXPORT_MAGIE=b'PCX1', EXPORT_INFO=b'pocketclot-export-v1',
              CHATS=chats, KATI_ROH=roh, GETEILT=geteilt, ABHOL_SCHLUESSEL=tmp_path / 'ssh-test', ABHOL_HOST='synthetisch',
              MAX_TRANSPORT=150 * 1024**2, MAX_KLAR=200 * 1024**2, MAX_CHATS=5000,
              _CID=__import__('re').compile(r'conv_[A-Za-z0-9_-]{4,64}'), auswahl=lambda: {'konto': 'usr_kati'},
              wa=SimpleNamespace(atomar=atomar, privat=lambda p: p.mkdir(exist_ok=True), log=lambda _: None))
    exec(compile(ast.Module(body=funcs, type_ignores=[]), str(quelle), 'exec'), ns)
    web = tmp_path / 'exportserver'
    (web / 'aus').mkdir(parents=True)
    konten = {'konten': {u: {'export': True} for u in ('usr_joscha', 'usr_kati', 'usr_clivia')}}
    (web / 'konten.json').write_text(json.dumps(konten))
    for uid in konten['konten']:
        payload = {'user_id': uid, 'erstellt': '2026-10-29', 'konversationen': [{'id': 'conv_test1234', 'titel': 'synthetisch'}]}
        (web / 'aus' / f'{uid}.export').write_bytes(wissen_export.versiegeln(gzip.compress(json.dumps(payload).encode()), key.public_key().public_bytes_raw()))
    def antwort(*_, **__):
        d = abholer.abholen(web, ['usr_joscha', 'usr_kati'])
        assert 'usr_clivia' not in d['freigegeben']
        assert {e['konto'] for e in d['exporte']} <= {'usr_joscha', 'usr_kati'}
        return SimpleNamespace(returncode=0, stdout=json.dumps(d).encode())
    ns['subprocess'].run = antwort
    assert ns['abholen']() == 1
    assert json.loads((chats / 'stand.json').read_text())['ids'] == ['conv_test1234']
    nur_clivia = abholer.abholen(web, ['usr_clivia'])
    assert nur_clivia['freigegeben'] == ['usr_clivia']
    assert [e['konto'] for e in nur_clivia['exporte']] == ['usr_clivia']
    (web / 'aus/usr_kati.export').unlink()
    vorher = (chats / 'stand.json').read_bytes()
    with pytest.raises(SystemExit, match='Export fehlt'):
        ns['abholen']()
    assert (chats / 'stand.json').read_bytes() == vorher
    konten['konten']['usr_kati']['export'] = False
    (web / 'konten.json').write_text(json.dumps(konten))
    (roh / 'cache.json').write_text(json.dumps({'chat:alt': 'weg', 'fassung:bleibt': 'da'}))
    (roh / 'fakten').mkdir()
    (roh / 'fakten/notiz.json').write_text('{}')
    (geteilt / 'von-kati.md').write_text('synthetische Weitergabe')
    assert ns['abholen']() == 0
    assert not list(chats.glob('*.json'))
    assert not list((roh / 'fakten').glob('*.json'))
    assert not (geteilt / 'von-kati.md').exists()
    assert json.loads((roh / 'cache.json').read_text()) == {'fassung:bleibt': 'da'}


def test_mac_vorbereitung_baut_paket_und_behaelt_alle_schluessel(monkeypatch, tmp_path):
    clivia = Path(os.environ.get('CLIVIA_REPO', Path.home() / '.local/share/clivia-arbeit/Clivia'))
    original = clivia / 'tools/pocketclot_wissen.py'
    if not original.exists():
        pytest.skip('Optionaler Originalquelltext: CLIVIA_REPO setzen')
    home = tmp_path / 'mac'
    repo = home / 'Projects/Clivia'
    (repo / 'tools').mkdir(parents=True)
    shutil.copy2(original, repo / 'tools/pocketclot_wissen.py')
    (repo / 'wissen').mkdir()
    (repo / 'wissen/profil.md').write_text('# Profil\n\nSynthetische Testperson mag Wandern.\n')
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))
    vor = laden('mac-vorbereiten')
    monkeypatch.setattr(sys, 'argv', ['mac-vorbereiten.py', '100.64.0.4', ssh_pub()])
    vor.main()
    cfg = home / '.config/clivia'
    assert json.loads((cfg / 'pocketclot.json').read_text())['user_id'] is None
    keys = [home / '.ssh/pocketclot_liefern', home / '.ssh/pocketclot_abholen',
            cfg / 'geheim/pocketclot-export.key', cfg / 'geheim/pocketclot-wissen.key']
    vorher = {str(p): hashlib.sha256(p.read_bytes()).digest() for p in keys}
    vor.main()
    for p in keys:
        assert hashlib.sha256(p.read_bytes()).digest() == vorher[str(p)]
        assert p.stat().st_mode & 0o777 == 0o600
    assert (home / '.local/state/clivia/pocketclot/clivia.paket').read_bytes().startswith(b'PCW1')
    # Fehlender privater Exportkey bei bestehendem Abholstand darf niemals rotiert werden.
    (home / '.local/state/clivia/pocketclot/freigabe.json').write_text('{}')
    (cfg / 'geheim/pocketclot-export.key').unlink()
    with pytest.raises(FileNotFoundError):
        vor.main()
    assert not (cfg / 'geheim/pocketclot-export.key').exists()


@pytest.mark.parametrize('belegt', [False, True])
def test_erstlauf_haelt_sperre_bis_lieferung_und_meldet_belegung_nicht_als_erfolg(monkeypatch, tmp_path, belegt, capsys):
    from contextlib import contextmanager
    m = laden('mac-erstlauf')
    cfg = tmp_path / '.config/clivia'
    cfg.mkdir(parents=True)
    (cfg / 'pocketclot.json').write_text('{"user_id": null}')
    (cfg / 'pocketclot-vorbereiten.py').write_text(
        "def modul():\n    import sys\n    return sys.modules['clivia_erstlauf_test']\n")
    gehalten, schritte = [], []
    @contextmanager
    def sperre(p):
        gehalten.append(True)
        try:
            yield not belegt
        finally:
            gehalten.pop()
    def schritt(name, wert=None):
        def aufruf(p):
            assert gehalten == [True]
            schritte.append(name)
            return wert
        return aufruf
    original = SimpleNamespace(
        Pfade=lambda repo, home, uid: SimpleNamespace(repo=repo, home=home, user_id=uid, pruefe_notaus=lambda: None),
        keine_links=lambda _: None, sperre=sperre, MAX_TRANSPORT=1024,
        ssh=lambda *_: b'{"freigegeben":["usr_clivia"],"exporte":[{"konto":"usr_clivia"}]}',
        atomar=lambda p, roh: p.write_bytes(roh), abholen=schritt('abholen', 3),
        chats=schritt('chats', 2), liefern=schritt('liefern'))
    monkeypatch.setitem(sys.modules, 'clivia_erstlauf_test', original)
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: tmp_path))
    if belegt:
        with pytest.raises(ValueError, match='Anderer Lauf aktiv'):
            m.main()
        assert not schritte
        assert 'Erstlauf erfolgreich' not in capsys.readouterr().out
    else:
        m.main()
        assert schritte == ['abholen', 'chats', 'liefern']
        assert 'Erstlauf erfolgreich' in capsys.readouterr().out
        assert json.loads((cfg / 'pocketclot.json').read_text())['user_id'] == 'usr_clivia'
    assert not gehalten
