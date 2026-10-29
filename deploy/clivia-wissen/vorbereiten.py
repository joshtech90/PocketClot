#!/usr/bin/env python3
"""Uploadordner aus den kanonischen Repo-Dateien bauen, ohne Patch-Kopien."""
import hashlib
from pathlib import Path
import shutil

basis = Path(__file__).resolve().parents[2]
quelle = basis / 'deploy/clivia-wissen'
ziel = basis / '.ai/tmp/clivia-wissen-upload'
ziel.mkdir(parents=True, exist_ok=True)
for name in ('einrichten.sh', 'zuruecknehmen.sh', 'installation.py', 'abholen.py', 'empfangen.py', 'README.md'):
    shutil.copy2(quelle / name, ziel / name)
(ziel / 'upload').mkdir(exist_ok=True)
for name in ('liefern.pub', 'abholen.pub', 'export.pub', 'from-ip.txt'):
    shutil.copy2(quelle / 'upload' / name, ziel / 'upload' / name)
(ziel / 'server-module').mkdir(exist_ok=True)
for name in ('wissen_export.py', 'wissen_tool.py'):
    p = basis / 'server/pocket_claude' / name
    shutil.copy2(p, ziel / 'server-module' / name)
    assert hashlib.sha256(p.read_bytes()).digest() == hashlib.sha256((ziel / 'server-module' / name).read_bytes()).digest()
print(ziel)
