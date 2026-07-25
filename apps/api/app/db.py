from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Iterator

from .config import settings
from .security import hash_password

_lock = threading.Lock()


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def json_loads(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    return json.loads(value)


def connect() -> sqlite3.Connection:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    with _lock:
        conn = connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    if column not in table_columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_db() -> None:
    with transaction() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
              id TEXT PRIMARY KEY,
              username TEXT UNIQUE NOT NULL,
              display_name TEXT NOT NULL,
              password_hash TEXT NOT NULL,
              role TEXT NOT NULL,
              active INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS invites (
              id TEXT PRIMARY KEY,
              code TEXT UNIQUE NOT NULL,
              note TEXT,
              expires_at TEXT,
              max_uses INTEGER NOT NULL DEFAULT 1,
              used_count INTEGER NOT NULL DEFAULT 0,
              revoked_at TEXT,
              created_by TEXT NOT NULL,
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS credentials (
              id TEXT PRIMARY KEY,
              user_id TEXT UNIQUE NOT NULL,
              provider_alias TEXT NOT NULL,
              provider_type TEXT,
              model_name TEXT NOT NULL,
              reasoning_effort TEXT NOT NULL,
              base_url TEXT,
              api_key_encrypted TEXT NOT NULL,
              masked_api_key TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS works (
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              title TEXT NOT NULL,
              prompt TEXT NOT NULL,
              style TEXT NOT NULL,
              target_chapters INTEGER,
              budget_usd REAL,
              advance_mode TEXT NOT NULL,
              status TEXT NOT NULL,
              current_phase TEXT NOT NULL,
              current_flow TEXT NOT NULL,
              completed_chapters INTEGER NOT NULL DEFAULT 0,
              last_error TEXT,
              active_run_id TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS runs (
              id TEXT PRIMARY KEY,
              work_id TEXT NOT NULL,
              user_id TEXT NOT NULL,
              status TEXT NOT NULL,
              mode TEXT NOT NULL,
              container_name TEXT,
              pid INTEGER,
              meta_json TEXT,
              started_at TEXT,
              ended_at TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            """
        )
        migrate_db(conn)
        ensure_bootstrap_admin(conn)


def migrate_db(conn: sqlite3.Connection) -> None:
    ensure_column(conn, "users", "must_change_password", "must_change_password INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "users", "password_changed_at", "password_changed_at TEXT")
    ensure_column(conn, "users", "last_login_at", "last_login_at TEXT")

    ensure_column(conn, "credentials", "last_test_status", "last_test_status TEXT")
    ensure_column(conn, "credentials", "last_test_message", "last_test_message TEXT")
    ensure_column(conn, "credentials", "last_tested_at", "last_tested_at TEXT")

    conn.execute(
        "UPDATE users SET must_change_password=1 WHERE role='admin' AND username=? AND COALESCE(password_changed_at,'')=''",
        (settings.bootstrap_admin_username,),
    )


def ensure_bootstrap_admin(conn: sqlite3.Connection) -> None:
    existing = conn.execute("SELECT id FROM users WHERE role='admin' LIMIT 1").fetchone()
    if existing:
        return
    now = utcnow()
    conn.execute(
        """
        INSERT INTO users (
          id, username, display_name, password_hash, role, active,
          must_change_password, password_changed_at, last_login_at, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, 'admin', 1, 1, NULL, NULL, ?, ?)
        """,
        (
            new_id("usr"),
            settings.bootstrap_admin_username,
            settings.bootstrap_admin_display_name,
            hash_password(settings.bootstrap_admin_password),
            now,
            now,
        ),
    )
