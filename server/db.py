"""Database layer for Ticket Tracker.

SQLite is the default and needs nothing installed.  Point DATABASE_URL at a
Postgres database (postgres://user:pass@host/db) to run against a hosted
database instead - see docs/DEPLOYMENT.md.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SQLITE_PATH = BASE_DIR / "data" / "ticket_tracker.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS users (
    id            {PK},
    username      TEXT NOT NULL UNIQUE,
    display_name  TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'staff',
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS buildings (
    id    {PK},
    name  TEXT NOT NULL UNIQUE,
    notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS residents (
    id          {PK},
    name        TEXT NOT NULL,
    building_id INTEGER REFERENCES buildings(id) ON DELETE SET NULL,
    room        TEXT NOT NULL DEFAULT '',
    allergies   TEXT NOT NULL DEFAULT '',
    diet        TEXT NOT NULL DEFAULT '',
    notes         TEXT NOT NULL DEFAULT '',
    consent_date  TEXT NOT NULL DEFAULT '',
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_residents_building ON residents(building_id);
CREATE INDEX IF NOT EXISTS idx_residents_name ON residents(name);

CREATE TABLE IF NOT EXISTS meal_items (
    id         {PK},
    name       TEXT NOT NULL UNIQUE,
    category   TEXT NOT NULL DEFAULT 'Other',
    tags       TEXT NOT NULL DEFAULT '',
    notes      TEXT NOT NULL DEFAULT '',
    active     INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tickets (
    id           {PK},
    resident_id  INTEGER NOT NULL REFERENCES residents(id) ON DELETE CASCADE,
    service_date TEXT NOT NULL,
    meal         TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'open',
    notes        TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    UNIQUE (resident_id, service_date, meal)
);
CREATE INDEX IF NOT EXISTS idx_tickets_date ON tickets(service_date);
CREATE INDEX IF NOT EXISTS idx_tickets_resident ON tickets(resident_id);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);

CREATE TABLE IF NOT EXISTS ticket_items (
    id        {PK},
    ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    item_id   INTEGER NOT NULL REFERENCES meal_items(id) ON DELETE CASCADE,
    qty       INTEGER NOT NULL DEFAULT 1,
    note      TEXT NOT NULL DEFAULT '',
    UNIQUE (ticket_id, item_id)
);
CREATE INDEX IF NOT EXISTS idx_ticket_items_ticket ON ticket_items(ticket_id);

CREATE TABLE IF NOT EXISTS audit_log (
    id         {PK},
    user_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action     TEXT NOT NULL,
    detail     TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);
"""


class Database:
    """Small portability wrapper around SQLite / Postgres.

    Every query uses ``?`` placeholders; they are translated for Postgres.
    Query results are always a list of plain dicts.
    """

    def __init__(self, url: str | None = None):
        url = url or os.environ.get("DATABASE_URL") or f"sqlite:///{DEFAULT_SQLITE_PATH}"
        self.url = url
        self.is_postgres = url.startswith(("postgres://", "postgresql://"))
        if not self.is_postgres:
            raw = url[9:] if url.startswith("sqlite:///") else url
            self.sqlite_path = Path(raw).expanduser()

    # ------------------------------------------------------------------ conn
    @contextmanager
    def connect(self):
        if self.is_postgres:
            try:
                import psycopg  # type: ignore
                from psycopg.rows import dict_row  # type: ignore
            except ImportError as exc:  # pragma: no cover - optional dependency
                raise RuntimeError(
                    "Postgres support needs psycopg. Install it with: "
                    "pip install 'psycopg[binary]'"
                ) from exc
            conn = psycopg.connect(self.url, row_factory=dict_row)
            try:
                yield _PgConn(conn)
            finally:
                conn.close()
        else:
            self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.sqlite_path, timeout=15)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA busy_timeout = 15000")
            try:
                yield _SqliteConn(conn)
            finally:
                conn.close()

    # ----------------------------------------------------------------- query
    def query(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        with self.connect() as conn:
            cur = conn.execute(sql, tuple(params))
            rows = cur.fetchall()
            return [dict(r) for r in rows]

    def query_one(self, sql: str, params: Iterable[Any] = ()) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        """Run a statement. Returns lastrowid for INSERT, rowcount otherwise."""
        with self.connect() as conn:
            cur = conn.execute(sql, tuple(params))
            conn.commit()
            if sql.lstrip().upper().startswith("INSERT"):
                return cur.lastrowid if cur.lastrowid is not None else cur.rowcount
            return cur.rowcount

    def insert(self, table: str, data: dict) -> int:
        cols = list(data.keys())
        marks = ", ".join("?" for _ in cols)
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({marks})"
        if self.is_postgres:
            sql += " RETURNING id"
        sql = self._translate(sql)
        with self.connect() as conn:
            cur = conn.execute(sql, tuple(data[c] for c in cols))
            if self.is_postgres:
                row = cur.fetchone()
                new_id = dict(row)["id"] if row else 0
            else:
                new_id = cur.lastrowid
            conn.commit()
            return int(new_id or 0)

    def update(self, table: str, row_id: int, data: dict) -> int:
        if not data:
            return 0
        sets = ", ".join(f"{k} = ?" for k in data)
        sql = f"UPDATE {table} SET {sets} WHERE id = ?"
        with self.connect() as conn:
            cur = conn.execute(self._translate(sql), tuple(data.values()) + (row_id,))
            conn.commit()
            return cur.rowcount

    def executemany(self, sql: str, rows: Iterable[Iterable[Any]]) -> int:
        batch = [tuple(r) for r in rows]
        if not batch:
            return 0
        with self.connect() as conn:
            conn.executemany(self._translate(sql), batch)
            conn.commit()
        return len(batch)

    def delete(self, table: str, row_id: int) -> int:
        with self.connect() as conn:
            cur = conn.execute(self._translate(f"DELETE FROM {table} WHERE id = ?"), (row_id,))
            conn.commit()
            return cur.rowcount

    # ---------------------------------------------------------------- schema
    def init_schema(self) -> None:
        if self.is_postgres:
            schema = SCHEMA.replace("{PK}", "SERIAL PRIMARY KEY")
            with self.connect() as conn:
                conn.execute(schema)
                conn.commit()
        else:
            schema = SCHEMA.replace("{PK}", "INTEGER PRIMARY KEY AUTOINCREMENT")
            with self.connect() as conn:
                conn.execute("PRAGMA journal_mode = WAL")
                conn.executescript(schema)
                conn.commit()

    def _translate(self, sql: str) -> str:
        return sql.replace("?", "%s") if self.is_postgres else sql

    # -------------------------------------------------------------- migrate
    def migrate(self) -> None:
        """Lightweight migrations for databases created by older versions."""
        if self.is_postgres:  # pragma: no cover - requires Postgres
            with self.connect() as conn:
                row = conn.execute(
                    """SELECT 1 FROM information_schema.columns
                       WHERE table_name = 'residents' AND column_name = 'consent_date'"""
                )
                if not row.fetchall():
                    conn.execute(
                        "ALTER TABLE residents ADD COLUMN consent_date TEXT NOT NULL DEFAULT ''"
                    )
                    conn.commit()
        else:
            cols = {r["name"] for r in self.query("PRAGMA table_info(residents)")}
            if "consent_date" not in cols:
                self.execute(
                    "ALTER TABLE residents ADD COLUMN consent_date TEXT NOT NULL DEFAULT ''"
                )


class _SqliteConn:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def execute(self, sql: str, params: tuple = ()):
        return self._conn.execute(sql, params)

    def executemany(self, sql: str, rows: list[tuple]):
        self._conn.executemany(sql, rows)

    def executescript(self, sql: str):
        self._conn.executescript(sql)

    def commit(self):
        self._conn.commit()


class _PgConn:
    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql: str, params: tuple):
        cur = self._conn.cursor()
        cur.execute(sql.replace("?", "%s"), params)
        return _PgCursor(cur)

    def executemany(self, sql: str, rows: list[tuple]):
        with self._conn.cursor() as cur:
            cur.executemany(sql.replace("?", "%s"), rows)

    def commit(self):
        self._conn.commit()


class _PgCursor:
    def __init__(self, cur):
        self._cur = cur
        self.lastrowid = None
        self.rowcount = cur.rowcount

    def fetchall(self):
        return self._cur.fetchall()

    def fetchone(self):
        return self._cur.fetchone()
