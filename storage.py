"""SQLite storage and duplicate-safe publishing claims."""
from __future__ import annotations

import hashlib
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from datetime import timedelta
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "opportunities.db"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=20000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


_INITIALIZED_PATHS = set()

def init_db():
    identity = str(DB_PATH.resolve())
    if identity in _INITIALIZED_PATHS and DB_PATH.exists():
        return
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS opportunities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_key TEXT NOT NULL UNIQUE,
            fingerprint TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL DEFAULT '',
            organization TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT 'Other',
            location TEXT NOT NULL DEFAULT '',
            deadline TEXT NOT NULL DEFAULT '',
            eligibility TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            apply_url TEXT NOT NULL DEFAULT '',
            image_path TEXT NOT NULL DEFAULT '',
            source_name TEXT NOT NULL DEFAULT '',
            source_url TEXT NOT NULL DEFAULT '',
            raw_text TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'review',
            telegram_text TEXT NOT NULL DEFAULT '',
            linkedin_text TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_opportunity_status ON opportunities(status, created_at);
        CREATE TABLE IF NOT EXISTS publications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            opportunity_id INTEGER NOT NULL REFERENCES opportunities(id),
            platform TEXT NOT NULL,
            slot_key TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'claim',
            remote_id TEXT NOT NULL DEFAULT '',
            error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(opportunity_id, platform),
            UNIQUE(platform, slot_key)
        );
        CREATE TABLE IF NOT EXISTS state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """)
        c.execute("CREATE TABLE IF NOT EXISTS duplicate_sources (source_key TEXT PRIMARY KEY, opportunity_id INTEGER NOT NULL, reason TEXT NOT NULL)")
        c.execute("CREATE TABLE IF NOT EXISTS weekly_roundups (week_key TEXT PRIMARY KEY, status TEXT NOT NULL, text TEXT NOT NULL, remote_id TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL)")
        c.execute("CREATE TABLE IF NOT EXISTS publication_parts (id INTEGER PRIMARY KEY, opportunity_id INTEGER NOT NULL, platform TEXT NOT NULL, remote_id TEXT NOT NULL, kind TEXT NOT NULL, created_at TEXT NOT NULL)")
        pub_columns = {row[1] for row in c.execute("PRAGMA table_info(publications)")}
        if 'destination' not in pub_columns:
            c.execute("ALTER TABLE publications ADD COLUMN destination TEXT NOT NULL DEFAULT ''")
        # Older databases do not have image_path. Add it in place without clearing data.
        current = {row[1] for row in c.execute("PRAGMA table_info(opportunities)")}
        if 'deadline_note' not in current:
            c.execute("ALTER TABLE opportunities ADD COLUMN deadline_note TEXT NOT NULL DEFAULT ''")
        if "image_path" not in current:
            c.execute("ALTER TABLE opportunities ADD COLUMN image_path TEXT NOT NULL DEFAULT ''")

    _INITIALIZED_PATHS.add(identity)

from dedup import canonical_url, find_match


def fingerprint(data: dict) -> str:
    # Identity belongs to the source record; cross-source matching is explicit.
    return hashlib.sha256(('source:' + data['source_key']).encode()).hexdigest()


def source_exists(source_key: str) -> bool:
    init_db()
    with db() as c:
        return c.execute("SELECT 1 FROM opportunities WHERE source_key=? UNION ALL SELECT 1 FROM duplicate_sources WHERE source_key=?", (source_key, source_key)).fetchone() is not None


def add_opportunity(data: dict) -> bool:
    init_db()
    now = utcnow()
    value = dict(data)
    value["source_key"] = value.get("source_key") or "manual:" + hashlib.sha256(
        (value.get("source_url", "") + value.get("raw_text", "") + value.get("title", "")).encode()
    ).hexdigest()
    value["fingerprint"] = fingerprint(value)
    columns = ("source_key", "fingerprint", "title", "organization", "category", "location", "deadline",
               "eligibility", "description", "apply_url", "source_name", "source_url", "raw_text",
               "telegram_text", "linkedin_text", "image_path", "deadline_note")
    fields = [value.get(col, "") for col in columns]
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        if c.execute("SELECT 1 FROM opportunities WHERE source_key=? UNION ALL SELECT 1 FROM duplicate_sources WHERE source_key=?", (value['source_key'], value['source_key'])).fetchone():
            return False
        found = find_match(value, c.execute("SELECT * FROM opportunities ORDER BY id").fetchall())
        if found and found[1] == 'exact':
            keeper = dict(found[0])
            # Fill missing facts only. Never overwrite conflicts, custom captions,
            # rejected decisions or already attempted/published records.
            attempted = c.execute('SELECT 1 FROM publications WHERE opportunity_id=?', (keeper['id'],)).fetchone()
            if not attempted and keeper['status'] != 'rejected':
                enrich = {key: value.get(key) for key in
                          ('organization', 'location', 'deadline', 'deadline_note',
                           'eligibility', 'description', 'apply_url', 'image_path')
                          if not keeper.get(key) and value.get(key)}
                if enrich:
                    assigns = ','.join(key + '=?' for key in enrich)
                    c.execute('UPDATE opportunities SET ' + assigns + ',updated_at=? WHERE id=?',
                              [*enrich.values(), now, keeper['id']])
            c.execute("INSERT OR IGNORE INTO duplicate_sources VALUES(?,?,?)", (value['source_key'], keeper['id'], found[2]))
            return False
        cursor = c.execute(
            f"INSERT OR IGNORE INTO opportunities ({','.join(columns)},status,created_at,updated_at) "
            f"VALUES ({','.join('?' for _ in columns)},'review',?,?)", fields + [now, now]
        )
        return cursor.rowcount == 1


def get_opportunities(status: str = "", limit: int = 150) -> list[dict]:
    init_db()
    with db() as c:
        if status:
            records = c.execute("SELECT * FROM opportunities WHERE status=? ORDER BY created_at DESC LIMIT ?", (status, limit))
        else:
            records = c.execute("SELECT * FROM opportunities ORDER BY created_at DESC LIMIT ?", (limit,))
        return [dict(r) for r in records.fetchall()]


def get_opportunity(opp_id: int) -> dict | None:
    init_db()
    with db() as c:
        row = c.execute("SELECT * FROM opportunities WHERE id=?", (opp_id,)).fetchone()
        return dict(row) if row else None


def update_opportunity(opp_id: int, changes: dict, status: str | None = None):
    allowed = ("title", "organization", "category", "location", "deadline", "eligibility",
               "description", "apply_url", "source_url", "telegram_text", "linkedin_text", "image_path", "deadline_note", "raw_text")
    filtered = {k: v for k, v in changes.items() if k in allowed}
    if status is not None:
        if status not in ("review", "approved", "rejected"):
            raise ValueError("Invalid status")
        filtered["status"] = status
    if not filtered:
        return
    filtered["updated_at"] = utcnow()
    assigns = ",".join(f"{k}=?" for k in filtered)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        if status == 'approved':
            current = c.execute("SELECT * FROM opportunities WHERE id=?", (opp_id,)).fetchone()
            value = dict(current) if current else {}
            value.update(filtered)
            found = find_match(value, c.execute("SELECT * FROM opportunities WHERE id<>? AND status<>'rejected'", (opp_id,)).fetchall())
            if found:
                raise ValueError(f"Duplicate check: matches #{found[0]['id']} ({found[2]}). Keep one record or correct the details before approval.")
        c.execute(f"UPDATE opportunities SET {assigns} WHERE id=?", [*filtered.values(), opp_id])


def claim_next(platform: str, slot_key: str, destination: str | None = None) -> dict | None:
    """Reserves ONE approved posting for the slot, atomically across processes."""
    if platform not in ("telegram", "linkedin"):
        raise ValueError("Unsupported platform")
    init_db()
    today = datetime.now(timezone(timedelta(hours=3))).date().isoformat()
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        occupied = c.execute("SELECT 1 FROM publications WHERE platform=? AND slot_key=?", (platform, slot_key)).fetchone()
        if occupied:
            return None
        row = c.execute("""
            SELECT o.* FROM opportunities o
            WHERE o.status='approved'
              AND (o.deadline='' OR o.deadline>=?)
              AND NOT EXISTS (
                SELECT 1 FROM publications p WHERE p.opportunity_id=o.id AND p.platform=?
            ) ORDER BY o.created_at ASC, o.id ASC
        """, (today, platform)).fetchall()
        previous = c.execute("SELECT o.* FROM publications p JOIN opportunities o ON o.id=p.opportunity_id WHERE p.platform=?", (platform,)).fetchall()
        from post_content import application_url
        from routing import telegram_destination
        row = next((r for r in row if application_url(dict(r))
                    and (platform != 'telegram' or telegram_destination(dict(r)))
                    and (not destination or telegram_destination(dict(r)) == destination)
                    and not find_match(dict(r), previous)), None)
        if not row:
            return None
        now = utcnow()
        c.execute("INSERT INTO publications(opportunity_id,platform,slot_key,created_at,updated_at) "
                  "VALUES(?,?,?,?,?)", (row["id"], platform, slot_key, now, now))
        if platform == 'telegram':
            destination = telegram_destination(dict(row))
            c.execute("UPDATE publications SET destination=? WHERE opportunity_id=? AND platform=?", (destination, row['id'], platform))
        result = dict(row)
        if platform == 'telegram':
            result['publication_destination'] = destination
        return result


def set_publication(opportunity_id: int, platform: str, status: str, remote_id: str = "", error: str = ""):
    with db() as c:
        c.execute("UPDATE publications SET status=?,remote_id=?,error=?,updated_at=? "
                  "WHERE opportunity_id=? AND platform=?",
                  (status, remote_id, error[:900], utcnow(), opportunity_id, platform))


def mark_manual_linkedin(opportunity_id: int) -> bool:
    init_db()
    with db() as c:
        cursor = c.execute("INSERT OR IGNORE INTO publications "
                           "(opportunity_id,platform,slot_key,status,created_at,updated_at) "
                           "VALUES(?, 'linkedin', ?, 'posted_manual', ?, ?)",
                           (opportunity_id, f"manual:{opportunity_id}", utcnow(), utcnow()))
        return cursor.rowcount == 1


def get_publications(limit: int = 100) -> list[dict]:
    init_db()
    with db() as c:
        return [dict(r) for r in c.execute("""
            SELECT p.*, o.title FROM publications p JOIN opportunities o ON o.id=p.opportunity_id
            ORDER BY p.created_at DESC LIMIT ?
        """, (limit,)).fetchall()]


def get_state(key: str, default: str = "") -> str:
    init_db()
    with db() as c:
        row = c.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def set_state(key: str, value: str):
    with db() as c:
        c.execute("INSERT INTO state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def duplicate_warning(opp):
    init_db()
    with db() as c:
        found = find_match(opp, c.execute("SELECT * FROM opportunities WHERE id<>? AND status<>'rejected'", (opp['id'],)).fetchall())
        return f"Possible duplicate of #{found[0]['id']}: {found[2]}. Approval is blocked until resolved." if found else ''


def record_publication_part(opportunity_id, platform, remote_id, kind):
    with db() as c:
        c.execute("INSERT INTO publication_parts(opportunity_id,platform,remote_id,kind,created_at) VALUES(?,?,?,?,?)", (opportunity_id,platform,remote_id,kind,utcnow()))
