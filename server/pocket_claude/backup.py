"""Backup-Export und -Import.

Ein Backup ist ein ZIP-Archiv mit folgender Struktur:

    manifest.json          — Metadata (Version, Datum, Statistiken)
    pocket_claude.db       — SQLite-Snapshot (mit FTS-Index)
    uploads/<id>.<ext>...  — alle Attachment-Files

Beim Export wird die SQLite-DB per `VACUUM INTO` sauber kopiert (= eigene
Datei, keine Locks, kompaktiert). Beim Import wird der bestehende Stand erst
in `data/backup-before-import-{ts}.zip` gesichert, dann je nach Modus
"replace" oder "merge" verarbeitet.

Optional AES-256-verschlüsselt: wenn beim Export ein Passwort übergeben wird,
landet das ganze ZIP verschlüsselt auf der Platte (pyzipper, WZ_AES 256bit).
Beim Import wird dasselbe Passwort wieder gebraucht — Manifest-Peek schlägt
ohne PW mit RuntimeError fehl, die App reagiert darauf mit einem PW-Prompt.

Schema-Version: erhöhen, wenn das DB-Schema sich ändert und alte Backups nicht
mehr direkt importierbar sind.
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import logging
import os
import shutil
import sqlite3
import time
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

import aiosqlite

# pyzipper ist optional: ohne die Lib startet der Server normal, nur
# Verschlüsselung ist dann nicht verfügbar. So bleibt der Server lauffähig,
# auch wenn `pip install -r requirements.txt` noch nicht aufgerufen wurde.
try:
    import pyzipper
    HAS_PYZIPPER = True
except ImportError:
    pyzipper = None  # type: ignore
    HAS_PYZIPPER = False

from pocket_claude import __version__
from pocket_claude.config import settings

log = logging.getLogger(__name__)

BACKUP_SCHEMA_VERSION = 1
MANIFEST_FILENAME = "manifest.json"
DB_FILENAME = "pocket_claude.db"
UPLOADS_DIR = "uploads"

# Zip-Bomb-/Zip-Slip-Schutz beim Import. Werte bewusst grosszügig, aber endlich.
_MAX_ENTRIES = 100_000            # max. Anzahl Einträge im Archiv
_MAX_TOTAL_UNCOMPRESSED = 20 * 1024 * 1024 * 1024   # 20 GiB gesamt entpackt
_MAX_SINGLE_UNCOMPRESSED = 5 * 1024 * 1024 * 1024   # 5 GiB pro Einzeldatei
_MAX_COMPRESSION_RATIO = 200      # entpackt/gepackt pro Datei (Bomb-Heuristik)
_COPY_CHUNK = 1024 * 1024


class BackupUnsafeEntryError(ValueError):
    """Ein ZIP-Eintrag ist unsicher (Zip-Slip, absoluter Pfad, Backslash,
    Symlink) oder verletzt die Grössen-/Ratio-Limits (Zip-Bomb)."""


def _is_symlink_entry(info: zipfile.ZipInfo) -> bool:
    """True, wenn der ZIP-Eintrag als Symlink markiert ist (Unix-Mode im
    external_attr). Symlinks im Backup könnten sonst beim späteren Schreiben
    aus dem Zielverzeichnis herausführen."""
    mode = (info.external_attr >> 16) & 0o170000
    return mode == 0o120000  # S_IFLNK


def _safe_relpath(name: str) -> str:
    """Validiert einen `uploads/<...>`-ZIP-Eintragsnamen und gibt den relativen
    Pfad UNTERHALB von uploads zurück. Wirft BackupUnsafeEntryError bei
    absoluten Pfaden, `..`, Backslashes oder leeren Komponenten.

    Nur ein String-Test auf ".." reicht NICHT — hier wird der Pfad in POSIX-
    Komponenten zerlegt und jede einzeln geprüft; die Containment-Prüfung via
    resolve() passiert zusätzlich beim tatsächlichen Schreiben.
    """
    if "\\" in name:
        raise BackupUnsafeEntryError(f"Backslash im Eintrag: {name!r}")
    prefix = f"{UPLOADS_DIR}/"
    if not name.startswith(prefix):
        raise BackupUnsafeEntryError(f"Eintrag ausserhalb {UPLOADS_DIR}/: {name!r}")
    rel = name[len(prefix):]
    if not rel or rel.endswith("/"):
        raise BackupUnsafeEntryError(f"Kein Datei-Eintrag: {name!r}")
    # Absolut? (POSIX oder Windows-Laufwerk)
    if rel.startswith("/") or (len(rel) >= 2 and rel[1] == ":"):
        raise BackupUnsafeEntryError(f"Absoluter Pfad: {name!r}")
    parts = rel.split("/")
    for p in parts:
        if p in ("", ".", ".."):
            raise BackupUnsafeEntryError(f"Unsichere Pfadkomponente in {name!r}")
    return rel


def _extract_uploads_safely(zf, uploads_dir: Path, *, skip_existing: bool) -> int:  # noqa: ANN001
    """Extrahiert alle `uploads/<...>`-Einträge sicher in `uploads_dir`.

    Sicherheitsmassnahmen (BR-008):
    - jeder Eintrag muss ein POSIX-relativer Pfad ohne `..`/absolute Teile sein,
    - Symlink-Einträge werden abgelehnt,
    - das aufgelöste Ziel muss via resolve() INNERHALB von uploads_dir liegen,
    - Zip-Bomb-Guard: Entry-Count, Einzel-/Gesamtgrösse und Kompressionsratio.

    Extrahiert wird zunächst in ein isoliertes Temp-Verzeichnis INNERHALB von
    uploads_dir; nur validierte Dateien werden anschliessend atomar an ihren
    Zielplatz verschoben. Returnt die Anzahl übernommener Dateien.
    """
    uploads_root = uploads_dir.resolve()
    uploads_root.mkdir(parents=True, exist_ok=True)
    staging = Path(uploads_root) / f".import-staging-{uuid.uuid4().hex[:12]}"
    staging.mkdir(parents=True, exist_ok=False)

    total_uncompressed = 0
    entry_count = 0
    moved = 0
    try:
        for info in zf.infolist():
            name = info.filename
            if not name.startswith(f"{UPLOADS_DIR}/") or name.endswith("/"):
                continue
            entry_count += 1
            if entry_count > _MAX_ENTRIES:
                raise BackupUnsafeEntryError(
                    f"Zu viele Einträge (> {_MAX_ENTRIES}) — Zip-Bomb-Verdacht."
                )
            if _is_symlink_entry(info):
                raise BackupUnsafeEntryError(f"Symlink-Eintrag abgelehnt: {name!r}")

            rel = _safe_relpath(name)

            declared = int(getattr(info, "file_size", 0) or 0)
            if declared > _MAX_SINGLE_UNCOMPRESSED:
                raise BackupUnsafeEntryError(
                    f"Einzeldatei zu gross ({declared} B): {name!r}"
                )
            comp = int(getattr(info, "compress_size", 0) or 0)
            if comp > 0 and declared / comp > _MAX_COMPRESSION_RATIO:
                raise BackupUnsafeEntryError(
                    f"Kompressionsratio verdächtig ({declared}/{comp}): {name!r}"
                )

            # Ziel im Staging berechnen und Containment erzwingen.
            staged_target = (staging / rel).resolve()
            if os.path.commonpath([str(staging.resolve()), str(staged_target)]) != str(staging.resolve()):
                raise BackupUnsafeEntryError(f"Pfad-Escape (staging): {name!r}")

            staged_target.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            with zf.open(info) as src, open(staged_target, "wb") as dst:
                while True:
                    chunk = src.read(_COPY_CHUNK)
                    if not chunk:
                        break
                    written += len(chunk)
                    total_uncompressed += len(chunk)
                    if written > _MAX_SINGLE_UNCOMPRESSED:
                        raise BackupUnsafeEntryError(
                            f"Einzeldatei überschreitet Limit beim Lesen: {name!r}"
                        )
                    if total_uncompressed > _MAX_TOTAL_UNCOMPRESSED:
                        raise BackupUnsafeEntryError(
                            "Gesamtgrösse überschreitet Limit — Zip-Bomb-Verdacht."
                        )
                    dst.write(chunk)

        # Alle Einträge validiert + geschrieben → jetzt atomar ins Ziel übernehmen.
        for staged in sorted(staging.rglob("*")):
            if not staged.is_file():
                continue
            rel = staged.relative_to(staging)
            final_target = (uploads_root / rel).resolve()
            # Doppelte Containment-Prüfung gegen das echte Zielverzeichnis.
            if os.path.commonpath([str(uploads_root), str(final_target)]) != str(uploads_root):
                raise BackupUnsafeEntryError(f"Pfad-Escape (final): {rel}")
            if skip_existing and final_target.exists():
                continue
            final_target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged, final_target)
            moved += 1
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    return moved


def _copy_limited(src, dst, name: str) -> None:  # noqa: ANN001
    """Kopiert einen ZIP-Eintrag mit derselben Obergrenze wie Uploads. Die DB
    lief vorher ungebremst durch: eine stark gepackte Riesen-DB fuellte die Platte."""
    written = 0
    while True:
        chunk = src.read(_COPY_CHUNK)
        if not chunk:
            return
        written += len(chunk)
        if written > _MAX_SINGLE_UNCOMPRESSED:
            raise BackupUnsafeEntryError(f"Eintrag überschreitet Limit beim Lesen: {name!r}")
        dst.write(chunk)


# --------------------------------------------------------------------- ZIP-HELPER

def _open_zip_for_write(fp, password: Optional[str]):
    """Öffnet ein ZIP zum Schreiben — verschlüsselt (AES-256), wenn ein
    Passwort gegeben ist, sonst standard ZIP_DEFLATED.

    Rückgabewert: ein Context-Manager, der wie zipfile.ZipFile benutzt wird.
    """
    if password:
        if not HAS_PYZIPPER:
            raise RuntimeError(
                "Verschlüsselung nicht verfügbar — pyzipper fehlt im venv. "
                "Bitte einmal 'Update Dependencies.command' (im Server-Ordner) "
                "doppelklicken, dann Server neu starten."
            )
        zf = pyzipper.AESZipFile(fp, "w", compression=pyzipper.ZIP_DEFLATED,
                                 encryption=pyzipper.WZ_AES)
        zf.setpassword(password.encode("utf-8"))
        # nbits=256 ist Default bei pyzipper, aber explizit setzen schadet nicht
        try:
            zf.setencryption(pyzipper.WZ_AES, nbits=256)
        except Exception:  # noqa: BLE001
            pass
        return zf
    return zipfile.ZipFile(fp, "w", compression=zipfile.ZIP_DEFLATED)


def _open_zip_for_read(fp, password: Optional[str]):
    """Öffnet ein ZIP zum Lesen. Falls verschlüsselt: PW setzen. Wenn PW
    fehlt oder falsch ist, wird das beim ersten read() bemerkt — Caller
    soll RuntimeError abfangen."""
    # pyzipper kann auch unverschlüsselte ZIPs lesen → einheitlicher Pfad.
    # Ohne pyzipper fallback auf stdlib zipfile (nur für unverschlüsselte ZIPs).
    if HAS_PYZIPPER:
        zf = pyzipper.AESZipFile(fp, "r")
        if password:
            zf.setpassword(password.encode("utf-8"))
        return zf
    if password:
        raise RuntimeError(
            "Verschlüsseltes Backup, aber pyzipper fehlt im venv. "
            "Bitte einmal 'Update Dependencies.command' doppelklicken."
        )
    return zipfile.ZipFile(fp, "r")


class BackupPasswordError(ValueError):
    """ZIP ist verschlüsselt aber Passwort fehlt oder ist falsch."""


def _detect_encrypted(fp_bytes: bytes) -> bool:
    """Quick-Check ob ein ZIP-Archiv verschlüsselt ist (Encryption-Bit in den
    ZIP-Headers gesetzt). Funktioniert für ZipCrypto und AES-Variante."""
    try:
        with zipfile.ZipFile(io.BytesIO(fp_bytes), "r") as zf:
            return any(info.flag_bits & 0x1 for info in zf.infolist())
    except zipfile.BadZipFile:
        return False


@dataclass
class BackupManifest:
    schema_version: int
    created_at: str
    server_version: str
    conversation_count: int
    message_count: int
    attachment_count: int
    # Bei Per-User-Backups: User-Info zur Identifikation beim Import.
    # None bei globalem Admin-Backup.
    user_id: Optional[str] = None
    user_name: Optional[str] = None

    def to_dict(self) -> dict:
        d = {
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "server_version": self.server_version,
            "conversation_count": self.conversation_count,
            "message_count": self.message_count,
            "attachment_count": self.attachment_count,
        }
        if self.user_id:
            d["user_id"] = self.user_id
            d["user_name"] = self.user_name or ""
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "BackupManifest":
        return cls(
            schema_version=int(data.get("schema_version", 0)),
            created_at=str(data.get("created_at", "")),
            server_version=str(data.get("server_version", "")),
            conversation_count=int(data.get("conversation_count", 0)),
            user_id=data.get("user_id"),
            user_name=data.get("user_name"),
            message_count=int(data.get("message_count", 0)),
            attachment_count=int(data.get("attachment_count", 0)),
        )


# --------------------------------------------------------------------- EXPORT

async def _gather_stats(user_id: Optional[str] = None) -> tuple[int, int, int]:
    """Zählt Konversationen, Messages, Attachments — für die Manifest-Info.
    Mit `user_id`: nur die Daten dieses Users."""
    async with aiosqlite.connect(settings.db_path) as conn:
        if user_id is None:
            async def count(table: str) -> int:
                cur = await conn.execute(f"SELECT COUNT(*) FROM {table}")
                row = await cur.fetchone()
                return int(row[0]) if row else 0
            return await count("conversations"), await count("messages"), await count("attachments")
        # Per-User
        cur = await conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE user_id = ?", (user_id,),
        )
        conv = (await cur.fetchone())[0]
        cur = await conn.execute(
            "SELECT COUNT(*) FROM messages WHERE conversation_id IN "
            "(SELECT id FROM conversations WHERE user_id = ?)", (user_id,),
        )
        msg = (await cur.fetchone())[0]
        cur = await conn.execute(
            "SELECT COUNT(*) FROM attachments WHERE user_id = ?", (user_id,),
        )
        att = (await cur.fetchone())[0]
        return int(conv), int(msg), int(att)


def _wipe_sessions(cur: sqlite3.Cursor) -> None:
    """Entfernt ALLE Zeilen aus der sessions-Tabelle einer DB-Kopie.
    sessions.token ist das Bearer-Credential — es darf weder in der Backup-DB
    noch (unverschlüsselt) in den ZIP-Bytes landen. Nach einem Restore muss
    sich jeder User neu einloggen."""
    if cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'"
    ).fetchone():
        cur.execute("DELETE FROM sessions")


def _strip_sessions(db_path: Path) -> None:
    """Löscht die sessions-Tabelle einer frisch kopierten DB (Admin-Pfad, wo
    _filter_db_to_user nicht läuft). Wird NIE auf der Live-DB aufgerufen."""
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        _wipe_sessions(cur)
        conn.commit()
    finally:
        conn.close()


def _filter_db_to_user(db_path: Path, user_id: str) -> None:
    """Reduziert eine DB-Kopie auf die Daten eines einzelnen Users.
    Wird auf einer FRISCHEN VACUUM-Kopie aufgerufen, NICHT auf der Live-DB!"""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        cur = conn.cursor()
        # Andere User raus
        cur.execute("DELETE FROM users WHERE id != ?", (user_id,))
        # Conversations + Messages: messages haben FK ON DELETE CASCADE
        cur.execute("DELETE FROM conversations WHERE user_id != ? OR user_id IS NULL", (user_id,))
        # Attachments
        cur.execute("DELETE FROM attachments WHERE user_id != ? OR user_id IS NULL", (user_id,))
        # KV-Settings nur des Users behalten
        cur.execute("DELETE FROM kv_settings WHERE scope != ?", (user_id,))
        # Sessions KOMPLETT raus — sessions.token IST das Bearer-Credential und
        # darf NIE in ein Backup gelangen (Account-Takeover; Verschlüsselung ist
        # optional). Auch die eigenen Sessions werden entfernt, nicht nur
        # entwertet: ein leerer Platzhalter-Token bricht ausserdem die
        # UNIQUE/PK-Constraint, sobald ein User zwei aktive Sessions hat.
        # Nach einem Restore ist ein erneuter Login erforderlich.
        _wipe_sessions(cur)
        # token_usage (wird von usage.ensure_schema lazy angelegt) anderer User raus.
        if cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='token_usage'"
        ).fetchone():
            cur.execute("DELETE FROM token_usage WHERE user_id != ?", (user_id,))
        conn.commit()
        # FTS reindex — die Trigger sind beim DELETE schon gefeuert, aber zur
        # Sicherheit einmal neu aufbauen
        cur.execute("DELETE FROM messages_fts")
        cur.execute("""
            INSERT INTO messages_fts (content, title, conversation_id, message_id, role, created_at)
            SELECT m.content,
                   (SELECT title FROM conversations c WHERE c.id = m.conversation_id),
                   m.conversation_id, m.id, m.role, m.created_at
            FROM messages m
        """)
        conn.commit()
        cur.execute("VACUUM")
    finally:
        conn.close()


def _vacuum_to(target: Path) -> None:
    """VACUUM INTO erzeugt eine saubere DB-Kopie ohne Locks. Funktioniert auch
    während die Haupt-DB von der App genutzt wird."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    src = sqlite3.connect(str(settings.db_path))
    try:
        # VACUUM INTO ist ab SQLite 3.27 verfügbar (2019), in modernen Python
        # builds enthalten. Schreibt eine komplette kompaktierte Kopie.
        src.execute("VACUUM INTO ?", (str(target),))
    finally:
        src.close()


async def create_backup_zip(
    password: Optional[str] = None,
    user_id: Optional[str] = None,
    user_name: Optional[str] = None,
) -> bytes:
    """Erzeugt das Backup als In-Memory-ZIP.

    - `user_id=None` (Admin-Pfad): global, alle User-Daten.
    - `user_id` gegeben: nur die Daten dieses Users (per-User-Export).
    - `password`: AES-256-Verschlüsselung des ZIP."""
    conv_count, msg_count, att_count = await _gather_stats(user_id=user_id)
    manifest = BackupManifest(
        schema_version=BACKUP_SCHEMA_VERSION,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        server_version=__version__,
        conversation_count=conv_count,
        message_count=msg_count,
        attachment_count=att_count,
        user_id=user_id,
        user_name=user_name,
    )

    # Welche Attachment-Pfade gehören mit ins ZIP?
    allowed_paths: Optional[set[str]] = None
    if user_id is not None:
        async with aiosqlite.connect(settings.db_path) as conn:
            cur = await conn.execute(
                "SELECT path FROM attachments WHERE user_id = ?", (user_id,),
            )
            allowed_paths = {row[0] for row in await cur.fetchall()}

    # Kopieren, Filtern, Packen und Aufraeumen in EINEM Thread: synchron im
    # Event-Loop stand sonst der ganze Server, solange ein grosses Backup
    # entsteht. Und nur so raeumt der Thread seine Kopie selbst weg, auch wenn
    # der Aufrufer unterdessen abbricht.
    buf = await asyncio.to_thread(
        _build_zip_sync, manifest, password, user_id, allowed_paths)

    scope = f"user={user_name or user_id}" if user_id else "global"
    encrypted_note = " [AES-256]" if password else ""
    log.info(
        "Backup erzeugt%s [%s]: %d Konv. / %d Msg. / %d Attach. (%d KB)",
        encrypted_note, scope, conv_count, msg_count, att_count, len(buf.getvalue()) // 1024,
    )
    return buf.getvalue()


def _build_zip_sync(
    manifest: "BackupManifest",
    password: Optional[str],
    user_id: Optional[str],
    allowed_paths: Optional[set[str]],
) -> io.BytesIO:
    # DB sauber kopieren (kein Lock-Konflikt mit dem laufenden Server).
    # Eindeutiger Name (zwei Exporte in derselben Sekunde) und Aufraeumen in
    # jedem Fall: scheiterte der Export unterwegs, blieb sonst eine Kopie der
    # Chat-Datenbank im Datenordner liegen.
    tmp_db = settings.data_dir / f".backup-snapshot-{int(time.time())}-{uuid.uuid4().hex[:8]}.db"
    try:
        _vacuum_to(tmp_db)
        # Bei per-User-Export: die Kopie auf die User-Daten reduzieren (entfernt
        # dabei auch die sessions-Tabelle). Beim globalen Admin-Export läuft der
        # Filter nicht — sessions dort separat komplett entfernen, sonst würden ALLE
        # aktiven Bearer-Tokens im Klartext im Backup landen.
        if user_id is not None:
            _filter_db_to_user(tmp_db, user_id)
        else:
            _strip_sessions(tmp_db)

        buf = io.BytesIO()
        with _open_zip_for_write(buf, password) as zf:
            zf.writestr(MANIFEST_FILENAME, json.dumps(manifest.to_dict(), indent=2))
            zf.write(tmp_db, arcname=DB_FILENAME)
            uploads_dir = settings.data_dir / "uploads"
            if uploads_dir.exists():
                for f in uploads_dir.rglob("*"):
                    if not f.is_file():
                        continue
                    # Bei per-User: nur die Files mit registriertem path
                    if allowed_paths is not None and str(f) not in allowed_paths:
                        continue
                    arcname = f"{UPLOADS_DIR}/{f.relative_to(uploads_dir)}"
                    zf.write(f, arcname=arcname)
        return buf
    finally:
        tmp_db.unlink(missing_ok=True)


def suggested_filename() -> str:
    """Filename für den Download — Datum drin, damit User mehrere unterscheiden."""
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"pocket-claude-backup-{ts}.zip"


# --------------------------------------------------------------------- IMPORT

ImportMode = Literal["replace", "merge"]


@dataclass
class ImportResult:
    mode: ImportMode
    manifest: BackupManifest
    pre_import_backup_path: str
    conversations_added: int
    conversations_updated: int
    conversations_skipped: int
    messages_imported: int
    attachments_imported: int


def _read_manifest(zf) -> BackupManifest:  # noqa: ANN001 — pyzipper/zipfile beide
    if MANIFEST_FILENAME not in zf.namelist():
        raise ValueError(
            f"Backup-ZIP enthält keine {MANIFEST_FILENAME} — wahrscheinlich "
            f"kein Pocket-Claude-Backup."
        )
    try:
        raw = zf.read(MANIFEST_FILENAME)
    except RuntimeError as e:
        # pyzipper wirft RuntimeError("File is encrypted, password required")
        # bzw. RuntimeError("Bad password for file") — übersetzen
        msg = str(e).lower()
        if "encrypt" in msg or "password" in msg:
            raise BackupPasswordError(str(e)) from e
        raise
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError(f"manifest.json ungültig: {e}") from e
    m = BackupManifest.from_dict(data)
    if m.schema_version > BACKUP_SCHEMA_VERSION:
        raise ValueError(
            f"Backup-Schema-Version {m.schema_version} ist neuer als unsere "
            f"({BACKUP_SCHEMA_VERSION}). Server-Update nötig."
        )
    if m.schema_version < 1:
        raise ValueError(f"Unbekannte Schema-Version {m.schema_version}.")
    return m


def peek_manifest(zip_bytes: bytes, password: Optional[str] = None) -> BackupManifest:
    """Liest nur die Manifest-Info — für den Confirm-Dialog vor dem Import.
    Wirft BackupPasswordError wenn das ZIP verschlüsselt ist und kein/falsches
    Passwort übergeben wurde."""
    if _detect_encrypted(zip_bytes) and not password:
        raise BackupPasswordError("Backup ist verschlüsselt — Passwort nötig.")
    with _open_zip_for_read(io.BytesIO(zip_bytes), password) as zf:
        return _read_manifest(zf)


def _save_pre_import_backup() -> Path:
    """Speichert den aktuellen Zustand als ZIP, BEVOR wir importieren —
    Notfall-Rückweg. Returnt den Pfad."""
    # uuid-Suffix zusätzlich zum Sekunden-Timestamp: zwei Imports in derselben
    # Sekunde dürfen sich weder die Safety-ZIP noch das Snapshot-.db gegenseitig
    # überschreiben.
    ts = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    target = settings.data_dir / f"backup-before-import-{ts}.zip"
    # Synchron, weil wir gerade dabei sind den Import zu starten und kein
    # async-context da ist
    snapshot_db = settings.data_dir / f".pre-import-snapshot-{ts}.db"
    _vacuum_to(snapshot_db)
    # Auch das Sicherheits-ZIP darf keine Live-Bearer-Tokens tragen.
    _strip_sessions(snapshot_db)
    try:
        # "x" = exklusives Erstellen, kein stilles Truncate einer bereits
        # existierenden Safety-ZIP.
        with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(snapshot_db, arcname=DB_FILENAME)
            uploads_dir = settings.data_dir / "uploads"
            if uploads_dir.exists():
                for f in uploads_dir.rglob("*"):
                    if f.is_file():
                        zf.write(f, arcname=f"{UPLOADS_DIR}/{f.relative_to(uploads_dir)}")
    finally:
        try:
            snapshot_db.unlink()
        except OSError:
            pass
    log.info("Pre-Import-Backup gespeichert: %s", target)
    return target


def _replace_db_and_uploads(zf) -> tuple[int, int, int]:  # noqa: ANN001
    """Komplett-Replace: aktuelle DB + uploads verwerfen, aus ZIP extrahieren.
    Returnt (conversations_added, messages_imported, attachments_imported)."""
    target_db = settings.data_dir / DB_FILENAME
    uploads_dir = settings.data_dir / "uploads"

    # Erst ALLES neben dem Live-Stand vorbereiten und pruefen, dann tauschen.
    # Vorher wurden die Uploads zuerst geloescht und die DB ersetzt; ein
    # kaputtes oder abgelehntes Backup hinterliess dann einen halben Stand.
    if DB_FILENAME not in zf.namelist():
        raise ValueError(f"Backup enthält keine {DB_FILENAME}.")
    tag = uuid.uuid4().hex[:12]
    tmp_db = target_db.with_suffix(".import-tmp")
    new_uploads = settings.data_dir / f".uploads-import-{tag}"
    old_uploads = settings.data_dir / f".uploads-old-{tag}"
    try:
        with zf.open(DB_FILENAME) as src, open(tmp_db, "wb") as dst:
            _copy_limited(src, dst, DB_FILENAME)
        # Die neue DB muss lesbar sein und die Kerntabellen haben, BEVOR etwas
        # getauscht wird; sonst ersetzte eine kaputte Datei die echte.
        conv, msg = _check_import_db(tmp_db)
        # Uploads sicher extrahieren (Zip-Slip-/Zip-Bomb-Schutz, BR-008).
        att_count = _extract_uploads_safely(zf, new_uploads, skip_existing=False)
    except BaseException:
        tmp_db.unlink(missing_ok=True)
        shutil.rmtree(new_uploads, ignore_errors=True)
        raise

    # Tauschen: erst die Uploads (zuruecknehmbar), zuletzt die DB. os.replace
    # der DB ist atomar; offene aiosqlite-Handles bleiben auf dem alten Inode,
    # statt dass unter ihnen Bytes zerstoert werden. Scheitert ein Schritt,
    # kommt der alte Upload-Ordner zurueck und die DB bleibt unberuehrt.
    had_uploads = uploads_dir.exists()
    try:
        if had_uploads:
            os.replace(uploads_dir, old_uploads)
        try:
            os.replace(new_uploads, uploads_dir)
            os.replace(tmp_db, target_db)
        except BaseException:
            if uploads_dir.exists() and not new_uploads.exists():
                os.replace(uploads_dir, new_uploads)
            if had_uploads:
                os.replace(old_uploads, uploads_dir)
            raise
    except BaseException:
        tmp_db.unlink(missing_ok=True)
        shutil.rmtree(new_uploads, ignore_errors=True)
        raise
    shutil.rmtree(old_uploads, ignore_errors=True)

    return conv, msg, att_count


def _check_import_db(path: Path) -> tuple[int, int]:
    """Prueft eine Backup-DB vor dem Einspielen und liefert (Chats, Nachrichten)."""
    try:
        with contextlib.closing(sqlite3.connect(str(path))) as conn:
            ok = conn.execute("PRAGMA quick_check").fetchone()
            if not ok or ok[0] != "ok":
                raise ValueError("Backup-Datenbank ist beschädigt.")
            conv = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
            msg = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            conn.execute("SELECT COUNT(*) FROM attachments").fetchone()
    except sqlite3.DatabaseError as exc:
        raise ValueError(f"Backup-Datenbank ist nicht lesbar: {exc}") from exc
    return int(conv), int(msg)


def _merge_db_and_uploads(zf) -> tuple[int, int, int, int]:  # noqa: ANN001
    """Merge: aus dem Backup nur Konversationen + Messages hinzufügen, die in
    der aktuellen DB noch nicht existieren (gleiche cid). Bestehende werden
    NICHT überschrieben. Attachments werden mitgeschickt, sofern referenziert
    und noch nicht da.
    Returnt (added, skipped, messages_imported, attachments_imported)."""
    target_db = settings.data_dir / DB_FILENAME
    uploads_dir = settings.data_dir / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    # Backup-DB temporär entpacken
    tmp_dir = settings.data_dir / ".merge-tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    backup_db_path = tmp_dir / "backup.db"
    try:
        with zf.open(DB_FILENAME) as src, open(backup_db_path, "wb") as dst:
            _copy_limited(src, dst, DB_FILENAME)

        added = 0
        skipped = 0
        msgs_imported = 0
        atts_imported = 0

        with sqlite3.connect(str(target_db)) as live_conn:
            live_conn.execute("PRAGMA foreign_keys = ON")
            with sqlite3.connect(str(backup_db_path)) as backup_conn:
                backup_conn.row_factory = sqlite3.Row

                # Konversationen aus Backup durchgehen
                cur = backup_conn.execute("SELECT * FROM conversations")
                for row in cur:
                    cid = row["id"]
                    existing = live_conn.execute(
                        "SELECT 1 FROM conversations WHERE id = ?", (cid,)
                    ).fetchone()
                    if existing:
                        skipped += 1
                        continue

                    # Conversation einfügen — user_id + skills_override müssen
                    # mit, sonst werden importierte Chats keinem User
                    # zugeordnet (→ unsichtbar im list_conversations-Filter)
                    # und alle Per-Chat-Skills-Overrides gehen verloren.
                    # `row.keys()` checken statt hardcoden, weil alte Backups
                    # die skills_override-Spalte evtl. noch nicht haben.
                    row_keys = set(row.keys())
                    user_id_val = row["user_id"] if "user_id" in row_keys else None
                    skills_val = (
                        row["skills_override"]
                        if "skills_override" in row_keys else None
                    )
                    # locked evtl. nicht in alten Backups → Guard wie bei skills.
                    locked_val = row["locked"] if "locked" in row_keys else 0
                    live_conn.execute(
                        """INSERT INTO conversations
                           (id, title, created_at, last_message_at,
                            total_tokens, claude_session_id, pinned,
                            user_id, skills_override, locked)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (row["id"], row["title"], row["created_at"],
                         row["last_message_at"], row["total_tokens"],
                         row["claude_session_id"], row["pinned"],
                         user_id_val, skills_val, locked_val),
                    )
                    added += 1

                    # Zugehörige Messages
                    msg_cur = backup_conn.execute(
                        "SELECT * FROM messages WHERE conversation_id = ?",
                        (cid,),
                    )
                    for m in msg_cur:
                        live_conn.execute(
                            """INSERT INTO messages
                               (conversation_id, role, content, created_at,
                                tokens, attachment_ids)
                               VALUES (?, ?, ?, ?, ?, ?)""",
                            (m["conversation_id"], m["role"], m["content"],
                             m["created_at"], m["tokens"], m["attachment_ids"]),
                        )
                        msgs_imported += 1

                # Attachments-Tabelle: alle, die in den importierten Messages
                # referenziert sind (lassen sich nicht trivial auflösen ohne
                # JSON-Parsing — pragmatisch: alle aus Backup übernehmen,
                # bei id-Konflikt skip)
                att_cur = backup_conn.execute("SELECT * FROM attachments")
                for a in att_cur:
                    aid = a["id"]
                    existing = live_conn.execute(
                        "SELECT 1 FROM attachments WHERE id = ?", (aid,)
                    ).fetchone()
                    if existing:
                        continue
                    a_keys = set(a.keys())
                    att_user_id = a["user_id"] if "user_id" in a_keys else None
                    att_transcript = a["transcript"] if "transcript" in a_keys else None
                    live_conn.execute(
                        """INSERT INTO attachments
                           (id, filename, mime_type, size_bytes, path,
                            uploaded_at, user_id, transcript)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (a["id"], a["filename"], a["mime_type"],
                         a["size_bytes"], a["path"], a["uploaded_at"],
                         att_user_id, att_transcript),
                    )
                    atts_imported += 1

            live_conn.commit()

        # Uploads sicher dazukopieren, ohne bestehende zu überschreiben
        # (Zip-Slip-/Zip-Bomb-Schutz, BR-008).
        _extract_uploads_safely(zf, uploads_dir, skip_existing=True)

        return added, skipped, msgs_imported, atts_imported
    finally:
        try:
            backup_db_path.unlink(missing_ok=True)
            tmp_dir.rmdir()
        except OSError:
            pass


def import_backup(
    zip_bytes: bytes,
    mode: ImportMode,
    password: Optional[str] = None,
) -> ImportResult:
    """Importiert ein Backup-ZIP. Macht IMMER zuerst ein Pre-Import-Backup,
    falls was schiefgeht. Modus 'replace' überschreibt alles, 'merge' fügt
    nur Neues hinzu. Wenn ZIP verschlüsselt: Password mitgeben."""
    if mode not in ("replace", "merge"):
        raise ValueError(f"Unbekannter Modus: {mode}")
    if _detect_encrypted(zip_bytes) and not password:
        raise BackupPasswordError("Backup ist verschlüsselt — Passwort nötig.")

    with _open_zip_for_read(io.BytesIO(zip_bytes), password) as zf:
        manifest = _read_manifest(zf)  # validiert auch das PW über Manifest-Read

        # Auto-Backup vor Replace/Merge
        pre = _save_pre_import_backup()

        if mode == "replace":
            conv, msgs, atts = _replace_db_and_uploads(zf)
            result = ImportResult(
                mode="replace",
                manifest=manifest,
                pre_import_backup_path=str(pre),
                conversations_added=conv,
                conversations_updated=0,
                conversations_skipped=0,
                messages_imported=msgs,
                attachments_imported=atts,
            )
        else:
            added, skipped, msgs, atts = _merge_db_and_uploads(zf)
            result = ImportResult(
                mode="merge",
                manifest=manifest,
                pre_import_backup_path=str(pre),
                conversations_added=added,
                conversations_updated=0,
                conversations_skipped=skipped,
                messages_imported=msgs,
                attachments_imported=atts,
            )

    log.info("Backup-Import (%s) fertig: %s", mode, result)
    return result
