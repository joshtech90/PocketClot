"""Backup-Import im Modus "replace": ein abgelehntes Backup darf den
bestehenden Stand nicht anfassen. Frueher waren die Uploads da schon geloescht
und die Datenbank ersetzt, bevor die Upload-Eintraege geprueft wurden."""
from __future__ import annotations

import asyncio
import io
import os
import tempfile
import zipfile

_TMP_DATA_DIR = tempfile.mkdtemp(prefix="pc-test-data-")
os.environ.setdefault("SERVER_TOKEN", "x" * 40)
os.environ.setdefault("DATA_DIR", _TMP_DATA_DIR)

import pytest  # noqa: E402

from pocket_claude import backup, db  # noqa: E402
from pocket_claude.config import settings  # noqa: E402


def test_rejected_replace_keeps_live_data():
    asyncio.run(db.init_db())
    cid = asyncio.run(db.create_conversation("Bleibt"))
    upload = settings.uploads_dir / "bleibt.txt"
    upload.write_bytes(b"vorher")
    db_before = settings.db_path.read_bytes()

    good = asyncio.run(backup.create_backup_zip())
    buf = io.BytesIO(good)
    with zipfile.ZipFile(buf, "a") as zf:
        zf.writestr("uploads/../ausbruch.txt", b"boese")

    with pytest.raises(backup.BackupUnsafeEntryError):
        backup.import_backup(buf.getvalue(), "replace")

    assert upload.read_bytes() == b"vorher"
    assert settings.db_path.read_bytes() == db_before
    assert asyncio.run(db.get_conversation(cid)) is not None
    leftovers = [p.name for p in settings.data_dir.iterdir()
                 if p.name.startswith((".uploads-import-", ".uploads-old-"))
                 or p.suffix == ".import-tmp"]
    assert leftovers == []
