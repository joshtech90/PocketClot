"""SQLite layer: schema, connection, CRUD."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

import aiosqlite

from pocket_claude.config import settings

SCHEMA = """
-- Multi-User: jeder User loggt sich mit username + password ein. Nach
-- erfolgreichem Login wird ein Session-Token erzeugt (Tabelle `sessions`),
-- das die App/Web-UI dann als Bearer-Token mitschickt.
--
-- Legacy: alte User aus der Token-Only-Zeit haben kein password_hash. Ihr
-- ursprüngliches `token` bleibt einmalig gültig als „Passwort" für den
-- ersten Login — danach setzen sie ein echtes Passwort (must_change_password=1).
CREATE TABLE IF NOT EXISTS users (
    id                    TEXT PRIMARY KEY,
    name                  TEXT NOT NULL,
    token                 TEXT NOT NULL UNIQUE,
    password_hash         TEXT,
    must_change_password  INTEGER NOT NULL DEFAULT 0,
    is_admin              INTEGER NOT NULL DEFAULT 0,
    created_at            TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_name_unique ON users(name COLLATE NOCASE);

-- Session-Tokens: ein Token pro Login. Werden vom Client (App/Web-UI) als
-- Bearer mitgeschickt. Beim Logout / Passwort-Reset werden alle Sessions
-- eines Users gelöscht.
CREATE TABLE IF NOT EXISTS sessions (
    token         TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    last_seen_at  TEXT NOT NULL,
    user_agent    TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS conversations (
    id                  TEXT PRIMARY KEY,
    title               TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    last_message_at     TEXT,
    total_tokens        INTEGER NOT NULL DEFAULT 0,
    claude_session_id   TEXT,
    pinned              INTEGER NOT NULL DEFAULT 0,
    -- Pro-Chat-Sperre (UI-Riegel): 1 = Chat ist gesperrt, App/Web-UI verlangen
    -- vor Anzeige den globalen PIN (bzw. Fingerabdruck in der App). Der PIN-Hash
    -- selbst liegt user-global im kv_settings (Key `chat_lock_pin_hash`).
    locked              INTEGER NOT NULL DEFAULT 0,
    user_id             TEXT
);
-- Indexe auf migrationsabhängige Spalten (user_id) werden in _ensure_indexes()
-- erstellt — nachdem _ensure_columns() die Spalten ggf. nachgezogen hat.

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('user','assistant','system')),
    content         TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    tokens          INTEGER NOT NULL DEFAULT 0,
    attachment_ids  TEXT NOT NULL DEFAULT '[]',
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, id);

CREATE TABLE IF NOT EXISTS attachments (
    id          TEXT PRIMARY KEY,
    filename    TEXT NOT NULL,
    mime_type   TEXT NOT NULL,
    size_bytes  INTEGER NOT NULL,
    path        TEXT NOT NULL,
    uploaded_at TEXT NOT NULL,
    user_id     TEXT
);
-- idx_att_user wird in _ensure_indexes() angelegt (s.o.)

-- Volltextsuche über Message-Content + Conversation-Titel.
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content,
    title,
    conversation_id UNINDEXED,
    message_id UNINDEXED,
    role UNINDEXED,
    created_at UNINDEXED,
    tokenize='unicode61 remove_diacritics 2'
);

-- Trigger: jede neue/geänderte Message landet im FTS-Index.
CREATE TRIGGER IF NOT EXISTS messages_fts_insert
AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts (content, title, conversation_id, message_id, role, created_at)
    SELECT NEW.content,
           (SELECT title FROM conversations WHERE id = NEW.conversation_id),
           NEW.conversation_id, NEW.id, NEW.role, NEW.created_at;
END;

CREATE TRIGGER IF NOT EXISTS messages_fts_delete
AFTER DELETE ON messages BEGIN
    DELETE FROM messages_fts WHERE message_id = OLD.id;
END;

-- Titel-Updates auch im Index nachpflegen
CREATE TRIGGER IF NOT EXISTS conversations_title_update
AFTER UPDATE OF title ON conversations BEGIN
    UPDATE messages_fts SET title = NEW.title WHERE conversation_id = NEW.id;
END;

-- Konversation-Delete räumt Trigger-Lücke (FK-Cascade greift bei FTS5 nicht)
CREATE TRIGGER IF NOT EXISTS conversations_delete_fts
AFTER DELETE ON conversations BEGIN
    DELETE FROM messages_fts WHERE conversation_id = OLD.id;
END;

-- Generischer Key-Value-Store für UI-Settings (Theme, Effort, TTS-Pref,
-- System-Prompt-Mode etc.). Aktuell single-user; bei Multi-User-Erweiterung
-- später eine `user_id`-Spalte. `scope` ist Reserve für „global vs. per-user".
CREATE TABLE IF NOT EXISTS kv_settings (
    scope       TEXT NOT NULL DEFAULT 'default',
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (scope, key)
);

-- Gems = Custom Agents (wie ChatGPT-GPTs / Gemini-Gems). user_id=NULL +
-- is_builtin=1 → vom Server ausgeliefert (z.B. „Meme-Finder"), read-only und
-- für alle User sichtbar. Sonst gehört das Gem genau einem User.
CREATE TABLE IF NOT EXISTS gems (
    id                    TEXT PRIMARY KEY,
    user_id               TEXT,
    name                  TEXT NOT NULL,
    emoji                 TEXT,
    description           TEXT,
    instructions          TEXT NOT NULL,
    conversation_starters TEXT,                  -- JSON-Array[String]
    model                 TEXT,                  -- NULL = globaler Default
    effort                TEXT,                  -- NULL = Chat-Default
    skills                TEXT,                  -- NULL = User-Default; sonst JSON SkillsDto
    is_builtin            INTEGER NOT NULL DEFAULT 0,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gems_user ON gems(user_id);

-- Wissens-/Referenzdateien eines Gems. Verknüpft eine vorhandene attachments-
-- Zeile mit dem Gem (Upload läuft über dieselbe Pipeline wie Chat-Anhänge).
CREATE TABLE IF NOT EXISTS gem_files (
    gem_id        TEXT NOT NULL,
    attachment_id TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    PRIMARY KEY (gem_id, attachment_id)
);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(9)}"


async def _ensure_columns(db: aiosqlite.Connection) -> None:
    """Migrations: füge fehlende Spalten zu bestehenden Tabellen hinzu."""
    cur = await db.execute("PRAGMA table_info(conversations)")
    conv_cols = {row[1] for row in await cur.fetchall()}
    if "claude_session_id" not in conv_cols:
        await db.execute("ALTER TABLE conversations ADD COLUMN claude_session_id TEXT")
    if "pinned" not in conv_cols:
        await db.execute("ALTER TABLE conversations ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")
    # Pro-Chat-Sperre (UI-Riegel) — s. SCHEMA-Kommentar oben.
    if "locked" not in conv_cols:
        await db.execute("ALTER TABLE conversations ADD COLUMN locked INTEGER NOT NULL DEFAULT 0")
    if "user_id" not in conv_cols:
        await db.execute("ALTER TABLE conversations ADD COLUMN user_id TEXT")
    # Skills-Override pro Konversation: JSON-encoded SkillsDto oder NULL
    # (NULL = User-Default greift).
    if "skills_override" not in conv_cols:
        await db.execute("ALTER TABLE conversations ADD COLUMN skills_override TEXT")
    # Gem-Bindung: wenn gesetzt, ist der Chat „mit einem Gem" gestartet.
    if "gem_id" not in conv_cols:
        await db.execute("ALTER TABLE conversations ADD COLUMN gem_id TEXT")
    # Zusatz-Modelle: welches Modell wurde in diesem Chat zuletzt benutzt.
    # NULL bzw. leer = Claude (Standard).
    if "chat_model" not in conv_cols:
        await db.execute("ALTER TABLE conversations ADD COLUMN chat_model TEXT")
    # Denktiefe, die nur fuer diesen Chat gilt. Ein Gem bringt sie beim Start
    # mit, im Chat umgestellt wird sie hier gemerkt. NULL = die gemerkte
    # Denktiefe der Modell-Familie aus den Einstellungen.
    if "chat_effort" not in conv_cols:
        await db.execute("ALTER TABLE conversations ADD COLUMN chat_effort TEXT")
        # Einmalig: bestehende Gem-Chats bekommen Modell und Denktiefe ihres
        # Gems fest eingetragen, so wie neue Gem-Chats beim Anlegen. Bisher
        # rechneten Server und Clients beides bei jedem Turn aus dem Gem nach;
        # damit liess sich "im Chat auf Claude bzw. Familien-Vorgabe zurueck"
        # nicht von "nie umgestellt" unterscheiden.
        await db.execute(
            "UPDATE conversations SET "
            "chat_model = COALESCE(chat_model, (SELECT NULLIF(g.model, '') FROM gems g WHERE g.id = conversations.gem_id)), "
            "chat_effort = (SELECT NULLIF(g.effort, '') FROM gems g WHERE g.id = conversations.gem_id) "
            "WHERE gem_id IS NOT NULL"
        )
    cur = await db.execute("PRAGMA table_info(attachments)")
    att_cols = {row[1] for row in await cur.fetchall()}
    if "user_id" not in att_cols:
        await db.execute("ALTER TABLE attachments ADD COLUMN user_id TEXT")
    if "transcript" not in att_cols:
        # Transkript von Audio-Anhaengen (Groq Whisper), siehe attachments.py
        await db.execute("ALTER TABLE attachments ADD COLUMN transcript TEXT")
    # Users-Tabelle: password_hash + must_change_password
    cur = await db.execute("PRAGMA table_info(users)")
    user_cols = {row[1] for row in await cur.fetchall()}
    if "password_hash" not in user_cols:
        await db.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
    if "must_change_password" not in user_cols:
        await db.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0")
    await db.commit()


async def _ensure_indexes(db: aiosqlite.Connection) -> None:
    """Indexe auf Spalten, die per Migration angefügt wurden — separat, damit
    eine alte DB (ohne user_id) nicht beim CREATE INDEX scheitert. Wird NACH
    _ensure_columns aufgerufen, wenn alle Spalten garantiert existieren."""
    await db.execute("CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(user_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_att_user ON attachments(user_id)")
    await db.commit()


# ---------- Password-Hashing (stdlib scrypt) ----------

# scrypt-Parameter — Standard für interaktive Logins (siehe RFC 7914 §2):
#   N=2**15 (~32 MB), r=8, p=1 → ~50 ms auf modernem Server, sicher.
# maxmem muss explizit gesetzt werden, weil Pythons OpenSSL-Wrapper sonst
# einen 32 MB Default zieht und bei diesen Parametern schon abbricht.
_SCRYPT_N = 2 ** 15
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32
_SCRYPT_MAXMEM = 128 * 1024 * 1024  # 128 MB, mehr als genug für N=2**15·r=8


def hash_password(password: str) -> str:
    """Hasht ein Passwort mit scrypt. Format: `scrypt$N$r$p$salt_b64$hash_b64`."""
    if not password:
        raise ValueError("Passwort darf nicht leer sein.")
    salt = os.urandom(16)
    dk = hashlib.scrypt(
        password.encode("utf-8"), salt=salt,
        n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCRYPT_DKLEN,
        maxmem=_SCRYPT_MAXMEM,
    )
    return (
        f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}"
        f"${base64.b64encode(salt).decode('ascii')}"
        f"${base64.b64encode(dk).decode('ascii')}"
    )


def verify_password(password: str, stored: str | None) -> bool:
    """Prüft Passwort gegen einen scrypt-Hash. False auch bei NULL/leerem Hash."""
    if not password or not stored:
        return False
    try:
        scheme, n_s, r_s, p_s, salt_b64, hash_b64 = stored.split("$", 5)
        if scheme != "scrypt":
            return False
        n, r, p = int(n_s), int(r_s), int(p_s)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        dk = hashlib.scrypt(
            password.encode("utf-8"), salt=salt,
            n=n, r=r, p=p, dklen=len(expected),
            maxmem=_SCRYPT_MAXMEM,
        )
        return hmac.compare_digest(dk, expected)
    except (ValueError, KeyError):
        return False


def _new_session_token() -> str:
    """Generiert ein neues, kryptographisch starkes Session-Token."""
    return secrets.token_urlsafe(32)


def generate_temp_password(words: int = 4) -> str:
    """Lesbares temporäres Passwort: 4 zufällige Tokens, mit `-` verbunden.
    Beispiel: `kite-bronze-quiet-7f3a`. Lang genug für sicher, leicht
    abtippbar fürs Admin-Reset-Szenario."""
    parts = [secrets.token_hex(2) for _ in range(words)]
    return "-".join(parts)


# Backwards-compat (intern in der Server-Code-Basis genutzt)
_generate_temp_password = generate_temp_password


async def _bootstrap_admin_user(db: aiosqlite.Connection) -> tuple[str, str] | None:
    """Beim allerersten Start: legt einen Admin-User an.

    Initial-Passwort:
    1. Wenn env-Variable `POCKET_CLAUDE_ADMIN_PASSWORD` gesetzt → das nehmen.
    2. Sonst: temp-Passwort generieren und in `data/INITIAL_PASSWORD.txt` schreiben.

    In beiden Fällen ist must_change_password=1, d.h. erster Login zwingt zum
    Passwort-Setzen.

    Bestehende Daten (ohne user_id) werden dem neuen Admin zugeordnet (für die
    Migration aus der Single-User-Zeit).

    Returnt (admin_id, initial_password) wenn was Neues angelegt wurde, sonst None.
    """
    cur = await db.execute("SELECT COUNT(*) FROM users")
    row = await cur.fetchone()
    if row and row[0] > 0:
        return None  # Schon User da, keine Bootstrap

    admin_id = _new_id("usr")
    init_pw = os.environ.get("POCKET_CLAUDE_ADMIN_PASSWORD", "").strip() \
        or _generate_temp_password()

    # `token`-Spalte ist NOT NULL UNIQUE — wir füllen sie mit einem zufälligen
    # Wert (wird nicht für Auth genutzt, ist seit Session-Login Legacy).
    legacy_token = secrets.token_urlsafe(24)
    await db.execute(
        "INSERT INTO users (id, name, token, password_hash, must_change_password, "
        "is_admin, created_at) VALUES (?, ?, ?, ?, 1, 1, ?)",
        (admin_id, "Admin", legacy_token, hash_password(init_pw), _now_iso()),
    )
    # Bestehende Daten dem Admin zuweisen (Migration aus Single-User-Zeit)
    await db.execute("UPDATE conversations SET user_id = ? WHERE user_id IS NULL", (admin_id,))
    await db.execute("UPDATE attachments SET user_id = ? WHERE user_id IS NULL", (admin_id,))
    await db.execute("UPDATE kv_settings SET scope = ? WHERE scope = 'default'", (admin_id,))
    await db.commit()

    # Persist the initial password so the operator doesn't have to fish it
    # out of the server log on first launch.
    if not os.environ.get("POCKET_CLAUDE_ADMIN_PASSWORD"):
        try:
            init_file = settings.data_dir / "INITIAL_PASSWORD.txt"
            init_file.write_text(
                f"PocketClot — Initial admin password\n"
                f"=======================================\n\n"
                f"Username: Admin\n"
                f"Password: {init_pw}\n\n"
                f"You will be asked to change the password on first login.\n"
                f"Delete this file once you have changed it.\n",
                encoding="utf-8",
            )
        except OSError:
            pass

    return (admin_id, init_pw)


async def init_db() -> None:
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(settings.db_path) as db:
        await db.executescript(SCHEMA)
        await _ensure_columns(db)
        await _ensure_indexes(db)
        bootstrap = await _bootstrap_admin_user(db)
        if bootstrap:
            admin_id, init_pw = bootstrap
            import logging
            log = logging.getLogger(__name__)
            log.info("=" * 60)
            log.info("Admin-User angelegt (id=%s)", admin_id)
            log.info("  Username: Admin")
            log.info("  Initial-Passwort: %s", init_pw)
            log.info("  (steht auch in %s)", settings.data_dir / "INITIAL_PASSWORD.txt")
            log.info("  Beim ersten Login musst Du es ändern.")
            log.info("=" * 60)
        await _seed_builtin_gems(db)
        await db.commit()
    # Falls die DB schon Messages hatte als FTS-Tabelle frisch angelegt wurde,
    # einmalig reindexieren — sonst sind alte Chats nicht durchsuchbar.
    async with aiosqlite.connect(settings.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute("SELECT COUNT(*) AS c FROM messages_fts")
        fts_count = (await cur.fetchone())["c"]
        cur = await conn.execute("SELECT COUNT(*) AS c FROM messages")
        msg_count = (await cur.fetchone())["c"]
    if msg_count > 0 and fts_count == 0:
        n = await reindex_fts()
        import logging
        logging.getLogger(__name__).info("FTS-Index neu aufgebaut: %d Messages", n)


@asynccontextmanager
async def get_db() -> AsyncIterator[aiosqlite.Connection]:
    db = await aiosqlite.connect(settings.db_path)
    db.row_factory = aiosqlite.Row
    try:
        await db.execute("PRAGMA foreign_keys = ON;")
        # Without a busy_timeout SQLite's default is 0: any contended write
        # (concurrent SSE streams + background TTS pre-gen + per-chunk KV
        # counter writes all hit the same file) fails *immediately* with
        # "database is locked" instead of waiting. 5s lets the writer block
        # until the holder commits — turns spurious crashes into a short wait.
        await db.execute("PRAGMA busy_timeout = 5000;")
        yield db
    finally:
        await db.close()


# ---------- Conversations ----------

async def create_conversation(
    title: str | None = None, user_id: str | None = None, gem_id: str | None = None,
    chat_model: str | None = None, chat_effort: str | None = None,
) -> str:
    cid = _new_id("conv")
    async with get_db() as db:
        await db.execute(
            "INSERT INTO conversations(id, title, created_at, user_id, gem_id, "
            "chat_model, chat_effort) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (cid, title or "Neuer Chat", _now_iso(), user_id, gem_id,
             (chat_model or "").strip() or None, (chat_effort or "").strip() or None),
        )
        await db.commit()
    return cid


async def list_conversations(user_id: str | None = None) -> list[dict]:
    """Listet Konversationen, die mindestens eine Nachricht haben.
    `user_id=None` → ALLE (nur intern für Admin-Backup), sonst Filter."""
    where = "WHERE EXISTS (SELECT 1 FROM messages m WHERE m.conversation_id = c.id)"
    params: tuple = ()
    if user_id is not None:
        where += " AND c.user_id = ?"
        params = (user_id,)
    async with get_db() as db:
        cur = await db.execute(
            f"""
            SELECT
                c.id, c.title, c.created_at, c.last_message_at, c.total_tokens,
                c.claude_session_id, c.pinned, c.locked, c.user_id, c.gem_id, c.chat_model,
                c.chat_effort,
                (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS msg_count
            FROM conversations c
            {where}
            ORDER BY c.pinned DESC, COALESCE(c.last_message_at, c.created_at) DESC
            """,
            params,
        )
        rows = await cur.fetchall()
    return [dict(row) for row in rows]


async def set_pinned(cid: str, pinned: bool, user_id: str | None = None) -> None:
    """Wenn user_id gegeben, wird nur geupdated wenn der Chat dem User gehört."""
    sql = "UPDATE conversations SET pinned = ? WHERE id = ?"
    params: tuple = (1 if pinned else 0, cid)
    if user_id is not None:
        sql += " AND user_id = ?"
        params = params + (user_id,)
    async with get_db() as db:
        await db.execute(sql, params)
        await db.commit()


async def set_locked(cid: str, locked: bool, user_id: str | None = None) -> None:
    """Setzt/löscht die Pro-Chat-Sperre. Wenn user_id gegeben, nur wenn Owner."""
    sql = "UPDATE conversations SET locked = ? WHERE id = ?"
    params: tuple = (1 if locked else 0, cid)
    if user_id is not None:
        sql += " AND user_id = ?"
        params = params + (user_id,)
    async with get_db() as db:
        await db.execute(sql, params)
        await db.commit()


async def set_chat_model(cid: str, model_key: str | None,
                         user_id: str | None = None) -> None:
    """Merkt sich das zuletzt in diesem Chat benutzte Modell.

    Leerer String wird als NULL gespeichert, damit "Claude" genau einen
    Zustand hat und nicht zwei.
    """
    value = (model_key or "").strip() or None
    sql = "UPDATE conversations SET chat_model = ? WHERE id = ?"
    params: tuple = (value, cid)
    if user_id is not None:
        sql += " AND user_id = ?"
        params = params + (user_id,)
    async with get_db() as db:
        await db.execute(sql, params)
        await db.commit()


async def set_chat_effort(cid: str, effort: str | None,
                          user_id: str | None = None) -> None:
    """Setzt die Denktiefe dieses Chats. Leer = wieder die der Modell-Familie."""
    value = (effort or "").strip().lower() or None
    sql = "UPDATE conversations SET chat_effort = ? WHERE id = ?"
    params: tuple = (value, cid)
    if user_id is not None:
        sql += " AND user_id = ?"
        params = params + (user_id,)
    async with get_db() as db:
        await db.execute(sql, params)
        await db.commit()


async def get_conversation(cid: str, user_id: str | None = None) -> dict | None:
    """Liefert die Conversation. Wenn user_id gegeben: nur wenn Owner;
    sonst None (für den Aufrufer wie „nicht gefunden")."""
    sql = "SELECT * FROM conversations WHERE id = ?"
    params: tuple = (cid,)
    if user_id is not None:
        sql += " AND user_id = ?"
        params = (cid, user_id)
    async with get_db() as db:
        cur = await db.execute(sql, params)
        row = await cur.fetchone()
    return dict(row) if row else None


async def update_conversation_title(cid: str, title: str, user_id: str | None = None) -> None:
    sql = "UPDATE conversations SET title = ? WHERE id = ?"
    params: tuple = (title, cid)
    if user_id is not None:
        sql += " AND user_id = ?"
        params = params + (user_id,)
    async with get_db() as db:
        await db.execute(sql, params)
        await db.commit()


async def set_title_if_default(
    cid: str, title: str, expected: str, user_id: str | None = None,
) -> int:
    """Atomarer Compare-and-Set des Titels: setzt `title` nur, wenn der aktuelle
    Titel noch exakt `expected` ist (z.B. der Default „Neuer Chat"). Das
    WHERE-Prädikat schützt gegen die TOCTOU-Race mit einem parallelen manuellen
    Rename (BR-027) — ein Vorher-Lesen wäre weiterhin racy.

    Returnt die Anzahl geänderter Zeilen (0 = nichts überschrieben)."""
    sql = "UPDATE conversations SET title = ? WHERE id = ? AND title = ?"
    params: tuple = (title, cid, expected)
    if user_id is not None:
        sql += " AND user_id = ?"
        params = params + (user_id,)
    async with get_db() as db:
        cur = await db.execute(sql, params)
        await db.commit()
        return cur.rowcount


async def delete_conversation(cid: str, user_id: str | None = None) -> bool:
    sql = "DELETE FROM conversations WHERE id = ?"
    params: tuple = (cid,)
    if user_id is not None:
        sql += " AND user_id = ?"
        params = params + (user_id,)
    async with get_db() as db:
        cur = await db.execute(sql, params)
        await db.commit()
        affected = cur.rowcount
    return affected > 0


async def set_claude_session_id(cid: str, session_id: str | None) -> None:
    async with get_db() as db:
        await db.execute(
            "UPDATE conversations SET claude_session_id = ? WHERE id = ?",
            (session_id, cid),
        )
        await db.commit()


async def clear_user_session_ids(user_id: str) -> int:
    """Drop the cached CLI session ID for every conversation owned by the
    user. Used when the user switches Claude auth modes (the cached session
    belongs to the previous provider and can't be resumed). Returns the
    number of rows affected."""
    async with get_db() as db:
        cur = await db.execute(
            "UPDATE conversations SET claude_session_id = NULL "
            "WHERE user_id = ? AND claude_session_id IS NOT NULL",
            (user_id,),
        )
        await db.commit()
        return cur.rowcount or 0


async def clear_user_locks(user_id: str) -> int:
    """Entfernt das locked-Flag von allen Chats des Users (beim PIN-Entfernen).
    Returnt die Anzahl betroffener Zeilen."""
    async with get_db() as db:
        cur = await db.execute(
            "UPDATE conversations SET locked = 0 WHERE user_id = ? AND locked = 1",
            (user_id,),
        )
        await db.commit()
        return cur.rowcount or 0


async def set_conversation_skills_override(
    cid: str, override_json: str | None, user_id: str | None = None,
) -> bool:
    """Setzt oder löscht (None) den Skills-Override einer Conversation.
    Returnt True wenn die Conversation existiert und der Owner-Check passt."""
    sql = "UPDATE conversations SET skills_override = ? WHERE id = ?"
    params: tuple = (override_json, cid)
    if user_id is not None:
        sql += " AND user_id = ?"
        params = params + (user_id,)
    async with get_db() as db:
        cur = await db.execute(sql, params)
        await db.commit()
        affected = cur.rowcount
    return affected > 0


# ---------- Messages ----------

async def add_message(
    cid: str,
    role: str,
    content: str,
    tokens: int = 0,
    attachment_ids: list[str] | None = None,
) -> int:
    """Speichert eine Message. Aktualisiert last_message_at — total_tokens NICHT
    (das setzt der Caller via set_total_tokens auf den aktuellen Kontextstand)."""
    attach_json = json.dumps(attachment_ids or [])
    now = _now_iso()
    async with get_db() as db:
        cur = await db.execute(
            """
            INSERT INTO messages(conversation_id, role, content, created_at, tokens, attachment_ids)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (cid, role, content, now, tokens, attach_json),
        )
        await db.execute(
            "UPDATE conversations SET last_message_at = ? WHERE id = ?",
            (now, cid),
        )
        await db.commit()
        msg_id = cur.lastrowid
    return msg_id or 0


async def set_total_tokens(cid: str, value: int) -> None:
    """Setzt conversation.total_tokens auf den aktuellen Kontextstand (nicht
    additiv). Soll nach jedem erfolgreichen Assistant-Turn aufgerufen werden mit
    `input + cache_read + cache_creation + output` aus der Anthropic-Usage."""
    async with get_db() as db:
        await db.execute(
            "UPDATE conversations SET total_tokens = ? WHERE id = ?",
            (value, cid),
        )
        await db.commit()


async def list_messages(cid: str) -> list[dict]:
    async with get_db() as db:
        cur = await db.execute(
            """
            SELECT id, conversation_id, role, content, created_at, tokens, attachment_ids
            FROM messages
            WHERE conversation_id = ?
            ORDER BY id ASC
            """,
            (cid,),
        )
        rows = await cur.fetchall()
    out = []
    for row in rows:
        d = dict(row)
        d["attachment_ids"] = json.loads(d["attachment_ids"] or "[]")
        out.append(d)
    return out


async def truncate_after(cid: str, message_id: int) -> int:
    """Verwirft alle Nachrichten NACH `message_id` in diesem Chat.

    Die Nachricht mit `message_id` selbst bleibt stehen: der Nutzer springt zu
    einer Antwort zurueck, die ihm gefallen hat, und will genau die behalten.

    Rueckgabe ist die Zahl der geloeschten Nachrichten.

    Die Anhaenge bleiben bewusst liegen. Eine Attachment-ID kann in mehreren
    Nachrichten stehen (etwa nachdem ein Bild als Vorlage weiterverwendet
    wurde), und ein verwaistes Bild ist harmloser als ein fehlendes. Der Preis
    dafuer ist, dass wiederholte Ruecksprunge Plattenplatz liegenlassen; ein
    Aufraeumen ungenutzter Anhaenge waere eine eigene Wartungsaufgabe.

    Der Volltext-Index zieht ueber den Trigger `messages_fts_delete` von selbst
    mit; verworfene Nachrichten sind also auch aus der Suche verschwunden.
    """
    async with get_db() as db:
        cur = await db.execute(
            "DELETE FROM messages WHERE conversation_id = ? AND id > ?",
            (cid, message_id),
        )
        removed = cur.rowcount or 0
        # Den Token-Stand und den Zeitstempel der letzten Nachricht mitziehen,
        # sonst zeigt die Chatliste weiter auf etwas, das es nicht mehr gibt.
        cur = await db.execute(
            "SELECT COALESCE(SUM(tokens), 0) AS t, MAX(created_at) AS last "
            "FROM messages WHERE conversation_id = ?",
            (cid,),
        )
        row = await cur.fetchone()
        await db.execute(
            "UPDATE conversations SET total_tokens = ?, last_message_at = ? WHERE id = ?",
            (row["t"] if row else 0, row["last"] if row else None, cid),
        )
        await db.commit()
    return removed


async def auto_rename_if_needed(
    cid: str, first_user_message: str, user_id: str | None = None,
) -> str | None:
    """Wenn die Konversation noch 'Neuer Chat' heißt, ersetze durch sinnvollen Titel.

    `user_id` ist optional (Backward-Compat); wenn gegeben, wird der Owner-
    Check beim Lesen/Update mitgemacht — Defense in Depth, falls ein Caller
    den Ownership-Check vergisst.
    """
    conv = await get_conversation(cid, user_id=user_id)
    if not conv or conv["title"] != "Neuer Chat":
        return None
    new_title = first_user_message.strip().split("\n")[0]
    if len(new_title) > 60:
        new_title = new_title[:57] + "…"
    if not new_title:
        return None
    await update_conversation_title(cid, new_title, user_id=user_id)
    return new_title


# ---------- Attachments ----------

async def add_attachment(filename: str, mime_type: str, size_bytes: int, path: Path,
                         user_id: str | None = None) -> str:
    aid = _new_id("att")
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO attachments(id, filename, mime_type, size_bytes, path, uploaded_at, user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (aid, filename, mime_type, size_bytes, str(path), _now_iso(), user_id),
        )
        await db.commit()
    return aid


async def get_attachment(aid: str, user_id: str | None = None) -> dict | None:
    sql = "SELECT * FROM attachments WHERE id = ?"
    params: tuple = (aid,)
    if user_id is not None:
        sql += " AND user_id = ?"
        params = (aid, user_id)
    async with get_db() as db:
        cur = await db.execute(sql, params)
        row = await cur.fetchone()
    return dict(row) if row else None


async def set_attachment_transcript(aid: str, text: str) -> None:
    async with get_db() as db:
        await db.execute("UPDATE attachments SET transcript = ? WHERE id = ?", (text, aid))
        await db.commit()


async def get_attachments(ids: list[str]) -> list[dict]:
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    async with get_db() as db:
        cur = await db.execute(
            f"SELECT * FROM attachments WHERE id IN ({placeholders})",
            ids,
        )
        rows = await cur.fetchall()
    return [dict(row) for row in rows]


# ---------- Gems (Custom Agents) ----------

async def create_gem(
    *,
    user_id: str | None,
    name: str,
    emoji: str = "",
    description: str = "",
    instructions: str = "",
    conversation_starters: str | None = None,  # JSON-Array-String
    model: str | None = None,
    effort: str | None = None,
    skills: str | None = None,                  # JSON SkillsDto-String
    is_builtin: bool = False,
    gem_id: str | None = None,
) -> str:
    gid = gem_id or _new_id("gem")
    now = _now_iso()
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO gems(id, user_id, name, emoji, description, instructions,
                             conversation_starters, model, effort, skills,
                             is_builtin, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (gid, user_id, name, emoji, description, instructions,
             conversation_starters, model, effort, skills,
             1 if is_builtin else 0, now, now),
        )
        await db.commit()
    return gid


async def get_gem(gem_id: str, user_id: str | None = None) -> dict | None:
    """Liefert das Gem, wenn es dem User gehört ODER ein Built-in ist."""
    sql = "SELECT * FROM gems WHERE id = ?"
    params: tuple = (gem_id,)
    if user_id is not None:
        sql += " AND (user_id = ? OR is_builtin = 1)"
        params = (gem_id, user_id)
    async with get_db() as db:
        cur = await db.execute(sql, params)
        row = await cur.fetchone()
    return dict(row) if row else None


async def list_gems(user_id: str) -> list[dict]:
    """Alle Gems des Users plus alle Built-ins. Eigene zuerst, Built-ins zuletzt."""
    async with get_db() as db:
        cur = await db.execute(
            """
            SELECT * FROM gems
            WHERE user_id = ? OR is_builtin = 1
            ORDER BY is_builtin ASC, updated_at DESC
            """,
            (user_id,),
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def update_gem(
    gem_id: str, user_id: str, *,
    name: str, emoji: str, description: str, instructions: str,
    conversation_starters: str | None, model: str | None,
    effort: str | None, skills: str | None,
) -> bool:
    """Voll-Update. Nur eigene, nicht-eingebaute Gems. Returnt False wenn nichts
    getroffen (fremd / built-in / nicht existent)."""
    async with get_db() as db:
        cur = await db.execute(
            """
            UPDATE gems SET name=?, emoji=?, description=?, instructions=?,
                            conversation_starters=?, model=?, effort=?, skills=?,
                            updated_at=?
            WHERE id=? AND user_id=? AND is_builtin=0
            """,
            (name, emoji, description, instructions, conversation_starters,
             model, effort, skills, _now_iso(), gem_id, user_id),
        )
        await db.commit()
        return (cur.rowcount or 0) > 0


def _unlink_all(paths: list[str]) -> None:
    for p in paths:
        try:
            Path(p).unlink(missing_ok=True)
        except OSError:
            pass


async def _orphan_gem_attachments(
    db: aiosqlite.Connection, attachment_ids: list[str],
) -> list[str]:
    """Löscht attachments-Zeilen für Gem-Dateien, die von KEINER gem_files-Zeile
    mehr referenziert werden, und gibt ihre Disk-Pfade zurück (Caller unlinkt
    nach dem Commit). Läuft innerhalb einer offenen `db`-Connection."""
    paths: list[str] = []
    for aid in attachment_ids:
        cur = await db.execute(
            "SELECT COUNT(*) FROM gem_files WHERE attachment_id=?", (aid,),
        )
        if (await cur.fetchone())[0]:
            continue  # noch von einem anderen Gem referenziert → behalten
        cur = await db.execute("SELECT path FROM attachments WHERE id=?", (aid,))
        row = await cur.fetchone()
        if row and row[0]:
            paths.append(row[0])
        await db.execute("DELETE FROM attachments WHERE id=?", (aid,))
    return paths


async def delete_gem(gem_id: str, user_id: str) -> bool:
    """Löscht ein eigenes Gem inkl. gem_files-Verknüpfungen, räumt verwaiste
    Wissensdateien (attachments-Zeile + Disk-Datei) auf und entkoppelt
    Conversations, die auf dieses Gem zeigten. Built-ins bleiben."""
    paths: list[str] = []
    async with get_db() as db:
        cur = await db.execute(
            "DELETE FROM gems WHERE id=? AND user_id=? AND is_builtin=0",
            (gem_id, user_id),
        )
        affected = cur.rowcount or 0
        if affected:
            cur = await db.execute(
                "SELECT attachment_id FROM gem_files WHERE gem_id=?", (gem_id,),
            )
            aids = [r[0] for r in await cur.fetchall()]
            await db.execute("DELETE FROM gem_files WHERE gem_id=?", (gem_id,))
            paths = await _orphan_gem_attachments(db, aids)
            # Conversations entkoppeln → werden zu normalen Chats (kein dangling gem_id).
            await db.execute(
                "UPDATE conversations SET gem_id=NULL WHERE gem_id=?", (gem_id,),
            )
        await db.commit()
    _unlink_all(paths)
    return affected > 0


async def add_gem_file(gem_id: str, attachment_id: str) -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT OR IGNORE INTO gem_files(gem_id, attachment_id, created_at) "
            "VALUES (?, ?, ?)",
            (gem_id, attachment_id, _now_iso()),
        )
        await db.commit()


async def remove_gem_file(gem_id: str, attachment_id: str) -> bool:
    """Entkoppelt eine Datei vom Gem und räumt die attachments-Zeile + Disk-Datei
    weg, falls sie von keinem Gem mehr referenziert wird."""
    paths: list[str] = []
    async with get_db() as db:
        cur = await db.execute(
            "DELETE FROM gem_files WHERE gem_id=? AND attachment_id=?",
            (gem_id, attachment_id),
        )
        affected = (cur.rowcount or 0) > 0
        if affected:
            paths = await _orphan_gem_attachments(db, [attachment_id])
        await db.commit()
    _unlink_all(paths)
    return affected


async def get_gem_file_ids(gem_id: str) -> list[str]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT attachment_id FROM gem_files WHERE gem_id=? ORDER BY created_at ASC",
            (gem_id,),
        )
        rows = await cur.fetchall()
    return [r["attachment_id"] for r in rows]


async def get_gem_files(gem_id: str) -> list[dict]:
    """Attachment-Zeilen für alle Dateien eines Gems (für die UI-Liste)."""
    async with get_db() as db:
        cur = await db.execute(
            """
            SELECT a.* FROM gem_files gf
            JOIN attachments a ON a.id = gf.attachment_id
            WHERE gf.gem_id = ?
            ORDER BY gf.created_at ASC
            """,
            (gem_id,),
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


# Eingebautes Beispiel-Gem: findet ein passendes Meme aus dem Netz und
# verlinkt/bettet es im Chat ein. Fester ID, damit der Seed idempotent ist.
_BUILTIN_MEME_GEM_ID = "gem_builtin_meme"

_MEME_GEM_DESC = (
    "Beschreib mir eine Situation — ich such dir ein passendes Meme aus dem "
    "Netz und verlinke es hier im Chat."
)

_MEME_GEM_INSTRUCTIONS = """Du bist „Meme-Finder". Der User beschreibt dir eine Situation, Stimmung oder einen Moment — du findest dazu ein passendes, bekanntes Meme aus dem Internet und teilst es im Chat.

Vorgehen:
1. Nutze die Websuche, um ein passendes, möglichst bekanntes Meme zur beschriebenen Situation zu finden.
2. Besorge eine DIREKTE Bild-URL (endet auf .jpg, .jpeg, .png, .gif oder .webp) von einer seriösen Quelle (z.B. imgflip.com, i.redd.it, bekannte Meme-Seiten). Wenn du nur eine Seiten-URL hast, öffne sie mit dem WebFetch-Tool und zieh die direkte Bild-URL heraus.
3. Antworte KURZ und humorvoll auf Deutsch:
   - Ein Satz, warum das Meme passt.
   - Dann das Bild als Markdown einbetten: ![Meme](DIREKTE_BILD_URL)
   - Und ZUSÄTZLICH als klickbaren Link darunter: [Meme öffnen](DIREKTE_BILD_URL)

Regeln:
- Gib IMMER beides aus (eingebettetes Bild UND Link) — falls das Bild nicht lädt, funktioniert wenigstens der Link.
- Keine beleidigenden, hasserfüllten oder NSFW-Memes. Bleib freundlich und lustig.
- Wenn du partout kein gutes Meme findest, sag das ehrlich und beschreib stattdessen kurz ein passendes Meme in Worten.
- Halte dich kurz — kein langer Text, das Meme ist der Star."""

_MEME_GEM_STARTERS = [
    "Mein Code kompiliert endlich nach 3 Stunden",
    "Wenn das Meeting auch eine E-Mail hätte sein können",
    "Montagmorgen-Stimmung",
    "Wenn der Kunde sagt: nur eine kleine Änderung",
]


async def _seed_builtin_gems(db: aiosqlite.Connection) -> None:
    """Legt eingebaute Gems an (idempotent). Läuft mit der init_db-Connection."""
    cur = await db.execute("SELECT id FROM gems WHERE id = ?", (_BUILTIN_MEME_GEM_ID,))
    if await cur.fetchone():
        return
    now = _now_iso()
    starters = json.dumps(_MEME_GEM_STARTERS, ensure_ascii=False)
    skills = json.dumps({"web_search": True, "web_fetch": True, "code_execution": False})
    await db.execute(
        """
        INSERT INTO gems(id, user_id, name, emoji, description, instructions,
                         conversation_starters, model, effort, skills,
                         is_builtin, created_at, updated_at)
        VALUES (?, NULL, ?, ?, ?, ?, ?, NULL, ?, ?, 1, ?, ?)
        """,
        (_BUILTIN_MEME_GEM_ID, "Meme-Finder", "😂", _MEME_GEM_DESC,
         _MEME_GEM_INSTRUCTIONS, starters, "low", skills, now, now),
    )


# ---------- Search ----------

def _escape_fts_query(q: str) -> str:
    """FTS5-Query escapen. Wir machen einen einfachen MATCH mit Prefix-Suchen pro Token."""
    # Sonderzeichen raus, dann pro Token ein * anhängen für Prefix-Match
    tokens = [t for t in q.replace('"', " ").replace("'", " ").split() if t.strip()]
    if not tokens:
        return ""
    return " ".join(f'"{t}"*' for t in tokens)


async def search_messages(query: str, limit: int = 30,
                          user_id: str | None = None) -> list[dict]:
    """Volltextsuche über alle Messages. Wenn user_id gegeben: nur Treffer
    in Konversationen dieses Users."""
    fts_q = _escape_fts_query(query)
    if not fts_q:
        return []
    extra_where = ""
    params: tuple = (fts_q,)
    if user_id is not None:
        # Gesperrte Chats (locked=1) aus der Volltextsuche ausschließen — sonst
        # würde ein Snippet den Klartext eines gesperrten Chats zeigen, ohne dass
        # der PIN-/Fingerabdruck-Riegel je greift. Erst nach Entsperren (locked=0)
        # taucht der Chat wieder in Treffern auf.
        extra_where = (
            "AND fts.conversation_id IN "
            "(SELECT id FROM conversations WHERE user_id = ? AND locked = 0)"
        )
        params = (fts_q, user_id)
    params = params + (limit,)
    async with get_db() as db:
        cur = await db.execute(
            f"""
            SELECT
                fts.conversation_id,
                fts.message_id,
                fts.role,
                fts.created_at,
                fts.title AS conversation_title,
                snippet(messages_fts, 0, '[[', ']]', '…', 24) AS snippet
            FROM messages_fts AS fts
            WHERE messages_fts MATCH ? {extra_where}
            ORDER BY rank
            LIMIT ?
            """,
            params,
        )
        rows = await cur.fetchall()
    return [dict(row) for row in rows]


# ---------- Users + Sessions ----------

# Cols für den AUTH-Layer: hier ist password_hash drin, weil der Login-Flow
# (verify_password) ihn braucht UND require_user/require_admin den hash für
# das change-password-Endpoint mitschickt. Die /me- und /users-Endpoints
# filtern via `_user_public()` in server.py — den hash mit über die Wire
# zu schicken passiert nicht. Wenn neue Endpoints das User-Dict zurückgeben,
# MÜSSEN sie ebenfalls `_user_public()` durchschicken.
_USER_PUBLIC_COLS = (
    "id, name, token, must_change_password, is_admin, created_at, password_hash"
)


async def get_user_by_session_token(token: str) -> dict | None:
    """Schaut Session-Token nach. Aktualisiert last_seen_at. Returnt User."""
    if not token:
        return None
    now = _now_iso()
    _prefixed = "u." + _USER_PUBLIC_COLS.replace(", ", ", u.")
    async with get_db() as db:
        cur = await db.execute(
            f"""
            SELECT {_prefixed}
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token = ?
            """,
            (token,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        await db.execute(
            "UPDATE sessions SET last_seen_at = ? WHERE token = ?", (now, token),
        )
        await db.commit()
    return dict(row)


async def get_user_by_token(token: str) -> dict | None:
    """LEGACY: schaut den Token im users.token-Feld nach (Pre-Session-Era).

    Nur noch erlaubt, wenn der User KEIN Passwort gesetzt hat (= Migration aus
    der Token-Only-Zeit, erster Login muss noch durchgehen). Sobald ein User
    ein Passwort hat, ist sein Legacy-Token tot.
    """
    if not token:
        return None
    async with get_db() as db:
        cur = await db.execute(
            f"SELECT {_USER_PUBLIC_COLS} FROM users WHERE token = ?",
            (token,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        user = dict(row)
        if user.get("password_hash"):
            # Legacy-Token darf nur akzeptiert werden, solange kein Passwort
            # gesetzt ist. Wenn ja → ungültig.
            return None
        return user


async def get_user_by_name(name: str) -> dict | None:
    """Lookup per Username (case-insensitive). Für Login."""
    if not name:
        return None
    async with get_db() as db:
        cur = await db.execute(
            f"SELECT {_USER_PUBLIC_COLS} FROM users WHERE name = ? COLLATE NOCASE",
            (name.strip(),),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_user_by_id(user_id: str) -> dict | None:
    async with get_db() as db:
        cur = await db.execute(
            f"SELECT {_USER_PUBLIC_COLS} FROM users WHERE id = ?",
            (user_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def list_users() -> list[dict]:
    """Listet Users (ohne password_hash nach außen — wird vom Endpoint gefiltert)."""
    async with get_db() as db:
        cur = await db.execute(
            f"SELECT {_USER_PUBLIC_COLS} FROM users ORDER BY is_admin DESC, name",
        )
        return [dict(r) for r in await cur.fetchall()]


async def create_user(name: str, password: str, is_admin: bool = False,
                      must_change_password: bool = True) -> dict:
    """Legt einen User mit Passwort an. `must_change_password=True` bedeutet:
    User MUSS sein Passwort beim ersten Login ändern.

    Returnt das User-dict inkl. password_hash, damit `_user_public()` beim
    Caller has_password korrekt meldet — der Hash wird dort gefiltert und nie
    über die Wire geschickt. Der Caller hat das Klartext-PW sowieso schon, der
    Server-Endpoint zeigt es einmal im Admin-UI an.
    """
    user_id = _new_id("usr")
    legacy_token = secrets.token_urlsafe(24)  # token-Spalte ist NOT NULL
    pw_hash = hash_password(password)
    created_at = _now_iso()
    async with get_db() as db:
        await db.execute(
            "INSERT INTO users (id, name, token, password_hash, must_change_password, "
            "is_admin, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, name, legacy_token, pw_hash,
             1 if must_change_password else 0, 1 if is_admin else 0, created_at),
        )
        await db.commit()
    return {
        "id": user_id, "name": name,
        # Include the hash so `_user_public()` reports has_password correctly;
        # _user_public strips it out and only emits the bool, never the value.
        "password_hash": pw_hash,
        "must_change_password": 1 if must_change_password else 0,
        "is_admin": 1 if is_admin else 0, "created_at": created_at,
    }


async def rename_user(user_id: str, name: str) -> None:
    """Aendert den Anzeige- und Anmeldenamen. Alles andere haengt an der ID,
    Sessions bleiben gueltig. Doppelte Namen verhindert der Unique-Index."""
    async with get_db() as db:
        await db.execute("UPDATE users SET name = ? WHERE id = ?", (name, user_id))
        await db.commit()


async def set_must_change_password(user_id: str, value: bool) -> None:
    """Setzt das must_change_password-Flag separat — z.B. wenn ein Legacy-User
    sich mit altem Token einloggt und wir ihm sofort einen Forced-Change
    aufzwingen wollen."""
    async with get_db() as db:
        await db.execute(
            "UPDATE users SET must_change_password = ? WHERE id = ?",
            (1 if value else 0, user_id),
        )
        await db.commit()


async def set_user_password(user_id: str, password: str,
                            must_change: bool = False) -> None:
    """Setzt ein neues Passwort. `must_change=True` zwingt zum erneuten Ändern
    beim nächsten Login (für Admin-Reset). Sessions des Users werden NICHT
    automatisch invalidiert — das macht der Caller je nach Kontext (Logout-
    all bei Admin-Reset, Logout-other-only bei User-Self-Change)."""
    pw_hash = hash_password(password)
    async with get_db() as db:
        await db.execute(
            "UPDATE users SET password_hash = ?, must_change_password = ? WHERE id = ?",
            (pw_hash, 1 if must_change else 0, user_id),
        )
        await db.commit()


async def delete_user(user_id: str) -> None:
    """Löscht einen User UND alle seine Daten (Conversations cascade → Messages,
    Attachments separat, KV-Settings, Sessions)."""
    async with get_db() as db:
        # Attachments löschen — Dateien auf Disk müssen separat aufgeräumt werden,
        # holen wir die Pfade vorher.
        cur = await db.execute(
            "SELECT path FROM attachments WHERE user_id = ?", (user_id,),
        )
        paths = [r[0] for r in await cur.fetchall()]
        await db.execute("DELETE FROM attachments WHERE user_id = ?", (user_id,))
        await db.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,))
        await db.execute("DELETE FROM kv_settings WHERE scope = ?", (user_id,))
        await db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        # Gems des Users + deren Datei-Verknüpfungen (die Attachment-Dateien
        # selbst hängen an user_id und werden oben schon mit-gelöscht/-unlinkt).
        await db.execute(
            "DELETE FROM gem_files WHERE gem_id IN (SELECT id FROM gems WHERE user_id = ?)",
            (user_id,),
        )
        await db.execute("DELETE FROM gems WHERE user_id = ?", (user_id,))
        await db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        await db.commit()
    for p in paths:
        try:
            Path(p).unlink(missing_ok=True)
        except OSError:
            pass


async def count_admins() -> int:
    async with get_db() as db:
        cur = await db.execute("SELECT COUNT(*) FROM users WHERE is_admin = 1")
        row = await cur.fetchone()
        return row[0] if row else 0


# ---------- Sessions ----------

async def create_session(user_id: str, user_agent: str | None = None) -> str:
    """Erzeugt eine neue Session für einen User. Returnt das Session-Token."""
    token = _new_session_token()
    now = _now_iso()
    async with get_db() as db:
        await db.execute(
            "INSERT INTO sessions (token, user_id, created_at, last_seen_at, user_agent) "
            "VALUES (?, ?, ?, ?, ?)",
            (token, user_id, now, now, (user_agent or "")[:200] or None),
        )
        await db.commit()
    return token


async def delete_session(token: str) -> bool:
    """Logout: einzelne Session löschen. Returnt True wenn was gelöscht wurde."""
    if not token:
        return False
    async with get_db() as db:
        cur = await db.execute("DELETE FROM sessions WHERE token = ?", (token,))
        await db.commit()
        affected = cur.rowcount
    return affected > 0


async def delete_sessions_for_user(user_id: str, except_token: str | None = None) -> int:
    """Alle Sessions eines Users löschen — z.B. nach Admin-PW-Reset oder
    User-PW-Change ('aus allen anderen Geräten ausloggen'). `except_token`
    erlaubt das Behalten der aktuellen Session.
    Returnt Anzahl gelöschter Sessions.
    """
    async with get_db() as db:
        if except_token:
            cur = await db.execute(
                "DELETE FROM sessions WHERE user_id = ? AND token != ?",
                (user_id, except_token),
            )
        else:
            cur = await db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        await db.commit()
        affected = cur.rowcount
    return affected


async def list_sessions_for_user(user_id: str) -> list[dict]:
    """Aktive Sessions eines Users — für Settings-Screen 'aktive Geräte'."""
    async with get_db() as db:
        cur = await db.execute(
            "SELECT token, created_at, last_seen_at, user_agent FROM sessions "
            "WHERE user_id = ? ORDER BY last_seen_at DESC",
            (user_id,),
        )
        return [dict(r) for r in await cur.fetchall()]


# ---------- KV-Settings ----------

async def kv_get_all(scope: str = "default") -> dict[str, str]:
    """Liest alle UI-Settings für einen Scope. Returnt {key: value}."""
    async with get_db() as db:
        cur = await db.execute(
            "SELECT key, value FROM kv_settings WHERE scope = ?", (scope,),
        )
        return {row["key"]: row["value"] for row in await cur.fetchall()}


async def kv_set_many(values: dict[str, str], scope: str = "default") -> None:
    """Schreibt mehrere UI-Settings auf einmal — upsert pro Key."""
    now = _now_iso()
    async with get_db() as db:
        await db.executemany(
            """
            INSERT INTO kv_settings (scope, key, value, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(scope, key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            [(scope, k, str(v), now) for k, v in values.items()],
        )
        await db.commit()


async def reindex_fts() -> int:
    """Baut den FTS-Index neu auf — nützlich bei bestehender DB ohne FTS-Einträge."""
    async with get_db() as db:
        # Vorhandene FTS-Einträge wegwerfen
        await db.execute("DELETE FROM messages_fts")
        # Aus messages neu befüllen
        cur = await db.execute(
            """
            INSERT INTO messages_fts (content, title, conversation_id, message_id, role, created_at)
            SELECT m.content,
                   (SELECT title FROM conversations c WHERE c.id = m.conversation_id),
                   m.conversation_id, m.id, m.role, m.created_at
            FROM messages m
            """
        )
        await db.commit()
        # Count
        count_cur = await db.execute("SELECT COUNT(*) FROM messages_fts")
        row = await count_cur.fetchone()
        return row[0] if row else 0
