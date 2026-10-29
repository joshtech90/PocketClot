"""Signierte Telegram-Dateihuellen, ohne Netzwerk oder echte Kontodaten."""
from __future__ import annotations
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

PART = 18 * 1024**2  # Unter Bot-API-getFile-Limit inklusive Huelle.
LIMITS = {'wissen': 50 * 1024**2, 'export': 100 * 1024**2, 'status': 4096}
MAGIC = {'wissen': b'PCW1', 'export': b'PCX1', 'status': b'PCS1'}
HEADER = 4096
DOMAIN = b'pocketclot-telegram-v1\0'


def digest(b):
    return hashlib.sha256(b).hexdigest()


def encoded(b):
    return base64.b64encode(b).decode('ascii')


def decoded(s):
    return base64.b64decode(s, validate=True)


def canonical(d):
    return json.dumps(d, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')


def no_links(p):
    p = Path(p)
    if any(q.is_symlink() for q in (p, *p.parents)):
        raise ValueError('Verknuepfung im Transportpfad')


def atomic(p, raw):
    p = Path(p)
    no_links(p)
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=p.parent, prefix='.telegram-')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, p)
    finally:
        Path(name).unlink(missing_ok=True)


def read_json(p, default=None):
    no_links(p)
    return json.loads(Path(p).read_bytes()) if Path(p).exists() else default


def config(p):
    p = Path(p)
    no_links(p)
    s = p.stat()
    if s.st_uid != os.getuid() or s.st_mode & 0o077 or not p.is_file():
        raise ValueError('Transportkonfiguration braucht eigenen Besitzer und 0600')
    d = read_json(p)
    if (type(d.get('chat_id')) is not int or d['chat_id'] >= 0
            or type(d.get('user_sender_id')) is not int or d['user_sender_id'] <= 0
            or type(d.get('bot_sender_id')) is not int or d['bot_sender_id'] <= 0
            or d['bot_sender_id'] == d['user_sender_id']
            or not re.fullmatch(r'usr_[A-Za-z0-9_-]{1,80}', d.get('account', ''))):
        raise ValueError('Transport-Empfaengerbindung fehlt')
    Ed25519PrivateKey.from_private_bytes(decoded(d['sign_private']))
    Ed25519PublicKey.from_public_bytes(decoded(d['peer_public']))
    return d


@contextmanager
def lock(p):
    p = Path(p)
    no_links(p)
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(p, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def sequence(state):
    n = max(time.time_ns(), read_json(state, {'sequence': 0})['sequence'] + 1)
    atomic(state, canonical({'sequence': n}))  # Vor Versand reservieren, auch bei Abbruch.
    return n


def documents(raw, kind, account, private, seq, *, part_size=PART, timestamp=None):
    if kind not in LIMITS or not raw.startswith(MAGIC[kind]) or not 4 <= len(raw) <= LIMITS[kind]:
        raise ValueError('Transportinhalt ungueltig')
    if not 1 <= part_size <= PART:
        raise ValueError('Teilgroesse ungueltig')
    count = math.ceil(len(raw) / part_size)
    common = dict(v=1, kind=kind, account=account, seq=seq,
                  time=int(time.time()) if timestamp is None else timestamp,
                  total=len(raw), hash=digest(raw), count=count, part_size=part_size)
    for i in range(count):
        payload = raw[i * part_size:(i + 1) * part_size]
        h = dict(common, index=i, length=len(payload), part_hash=digest(payload))
        sig = Ed25519PrivateKey.from_private_bytes(decoded(private)).sign(DOMAIN + canonical(h))
        wire = canonical({'header': h, 'signature': encoded(sig)}) + b'\n' + payload
        yield f'{seq}-{i + 1:04d}.pct', wire


class Receiver:
    def __init__(self, cfg, root, kind, peer, apply):
        self.cfg, self.root, self.kind, self.peer, self.apply = cfg, Path(root), kind, peer, apply

    def accept(self, chat, sender, raw):
        if chat != self.cfg['chat_id'] or sender != self.cfg[self.peer]:
            raise ValueError('Transport-Absender oder Gruppe unzulaessig')
        if len(raw) > PART + HEADER or b'\n' not in raw[:HEADER]:
            raise ValueError('Transportdatei zu gross oder Huelle fehlt')
        head, payload = raw.split(b'\n', 1)
        envelope = json.loads(head)
        if not isinstance(envelope, dict) or not isinstance(envelope.get('header'), dict):
            raise ValueError('Ungueltige Huelle')
        h = envelope['header']
        Ed25519PublicKey.from_public_bytes(decoded(self.cfg['peer_public'])).verify(
            decoded(envelope['signature']), DOMAIN + canonical(h))
        if set(h) != {'v', 'kind', 'account', 'seq', 'time', 'total', 'hash', 'count', 'part_size', 'index', 'length', 'part_hash'}:
            raise ValueError('Unbekannte Huelle')
        if h['v'] != 1 or h['kind'] != self.kind or h['account'] != self.cfg['account']:
            raise ValueError('Fremdes Konto oder Richtung')
        if any(type(h[k]) is not int for k in ('seq', 'time', 'total', 'count', 'part_size', 'index', 'length')):
            raise ValueError('Ungueltige Zaehler')
        if (not 0 < h['seq'] < 2**63 or not 4 <= h['total'] <= LIMITS[self.kind]
                or not 1 <= h['part_size'] <= PART or not 1 <= h['count'] <= 128
                or h['count'] != math.ceil(h['total'] / h['part_size'])
                or not 0 <= h['index'] < h['count']
                or h['length'] != min(h['part_size'], h['total'] - h['index'] * h['part_size'])
                or not 0 <= h['time'] <= time.time() + 300
                or (self.kind != 'export' and h['time'] < time.time() - 86400)
                or not re.fullmatch('[0-9a-f]{64}', h['hash'])
                or len(payload) != h['length'] or digest(payload) != h['part_hash']):
            raise ValueError('Transporthash, Laenge oder Zeit ungueltig')
        state = self.root / 'received.json'
        done = read_json(state, {'seq': 0})
        if h['seq'] <= done['seq']:
            return False
        folder = self.root / 'parts' / str(h['seq'])
        meta = {k: v for k, v in h.items() if k not in ('index', 'length', 'part_hash')}
        old = read_json(folder / 'meta.json')
        if old is not None and old != meta:
            raise ValueError('Widerspruechliche Teilserie')
        if old is None:
            parent = folder.parent
            no_links(parent)
            pending = list(parent.iterdir()) if parent.exists() else []
            # Nur bereits angewendete, reproduzierbare Transportteile bereinigen.
            for q in pending:
                previous = read_json(q / 'meta.json', {}) if q.name.isdigit() else {}
                if q.name.isdigit() and (int(q.name) <= done['seq'] or previous.get('time', 0) < time.time() - 86400):
                    import shutil
                    no_links(q)
                    shutil.rmtree(q)
            if parent.exists() and len(list(parent.iterdir())) >= 8:
                raise ValueError('Zu viele unvollstaendige Transfers')
            atomic(folder / 'meta.json', canonical(meta))
        atomic(folder / str(h['index']), payload)
        paths = [folder / str(i) for i in range(h['count'])]
        if not all(p.exists() for p in paths):
            return False
        for p in paths:
            no_links(p)
        data = b''.join(p.read_bytes() for p in paths)
        if len(data) != h['total'] or digest(data) != h['hash'] or not data.startswith(MAGIC[self.kind]):
            raise ValueError('Gesamtdatei ungueltig')
        self.apply(data, meta)  # Erst Anwendung, dann Replaymarke; Callback idempotent.
        atomic(state, canonical(dict(seq=h['seq'], hash=h['hash'], time=h['time'])))
        return True
