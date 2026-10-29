#!/usr/bin/env python3
"""Zwangsbefehl: nur clivia.paket; SSH_ORIGINAL_COMMAND wird nie ausgewertet."""
import fcntl
import hashlib
import os
from pathlib import Path
import re
import sys
import tempfile

ORDNER = Path('/opt/pocket-claude/wissen')
MAX = 50 * 1024**2


def empfangen(ordner, eingabe, ausgabe):
    with (ordner / '.clivia-empfang.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        kopf = eingabe.readline(256)
        m = re.fullmatch(rb'PCW1-HUELLE ([0-9]{1,8}) ([0-9a-f]{64}) clivia\n', kopf)
        if not m or not 32 <= int(m[1]) <= MAX:
            raise ValueError('Ungueltige Huelle')
        laenge = int(m[1])
        fd, name = tempfile.mkstemp(prefix='.clivia-', dir=ordner)
        try:
            h, anzahl, magie = hashlib.sha256(), 0, b''
            with os.fdopen(fd, 'wb') as f:
                while anzahl <= laenge:
                    block = eingabe.read(min(65536, laenge + 1 - anzahl))
                    if not block:
                        break
                    if anzahl == 0:
                        magie = block[:4]
                    anzahl += len(block)
                    h.update(block)
                    f.write(block)
                f.flush()
                os.fsync(f.fileno())
                os.fchmod(f.fileno(), 0o644)
            if anzahl != laenge or h.hexdigest().encode() != m[2] or magie != b'PCW1':
                raise ValueError('Paket unvollstaendig oder beschaedigt')
            ziel = ordner / 'clivia.paket'
            if ziel.is_symlink():
                raise ValueError('Verknuepfung unzulaessig')
            os.replace(name, ziel)
            ausgabe.write(f'ok {laenge}\n')
        finally:
            Path(name).unlink(missing_ok=True)


if __name__ == '__main__':
    try:
        empfangen(ORDNER, sys.stdin.buffer, sys.stdout)
    except Exception:
        sys.exit('Empfang abgelehnt')
