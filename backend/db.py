"""Request-scoped PostgreSQL persistence and explicit local SQLite compatibility."""
import os
import sqlite3

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL COLLATE NOCASE,
    full_name     TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    is_admin      INTEGER NOT NULL DEFAULT 0,
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    last_login    TEXT
);
CREATE TABLE IF NOT EXISTS failed_logins (
    username TEXT NOT NULL COLLATE NOCASE,
    ip       TEXT NOT NULL,
    at       REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS estimates (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title      TEXT NOT NULL,
    summary    TEXT NOT NULL DEFAULT '',
    total      REAL NOT NULL,
    inputs     TEXT NOT NULL,
    lines      TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_estimates_user ON estimates(user_id, id DESC);
CREATE TABLE IF NOT EXISTS audit_log (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    at       TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    user_id  INTEGER,
    username TEXT NOT NULL DEFAULT '',
    event    TEXT NOT NULL,
    detail   TEXT NOT NULL DEFAULT '',
    ip       TEXT NOT NULL DEFAULT ''
);
"""


def sqlite_connect(path: str) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def get_db():
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE_URL"])
    return g.db


def close_db(_exc=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_sqlite(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    db = sqlite_connect(path)
    try:
        with db:
            db.executescript(SCHEMA)
    finally:
        db.close()


class DatabaseUnavailable(Exception):
    """Sanitized connection failure, safe for HTTP responses."""


def connect(url, tz="Asia/Karachi"):
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.conninfo import conninfo_to_dict
    try:
        options = conninfo_to_dict(url)
        if options.get("sslmode", "require") not in ("require", "verify-ca", "verify-full"):
            raise ValueError("TLS is required")
        options.setdefault("sslmode", "require")
        options["options"] = options.get("options", "") + " -c timezone=UTC -c statement_timeout=15000"
        return PostgresConnection(psycopg.connect(**options, connect_timeout=10, row_factory=dict_row, autocommit=True, prepare_threshold=None))
    except (psycopg.Error, ValueError):
        raise DatabaseUnavailable("Database unavailable. Check server database configuration.") from None


class Row(dict):
    def __getitem__(self, key):
        return list(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


class Cursor:
    def __init__(self, cursor):
        self.cursor = cursor
        self.rowcount = cursor.rowcount

    def _row(self, row):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        if row is None:
            return None
        zone = ZoneInfo(current_app.config.get("APP_TIMEZONE", "Asia/Karachi")) if current_app else ZoneInfo("UTC")
        return Row({k: v.astimezone(zone).strftime("%Y-%m-%d %H:%M:%S") if isinstance(v, datetime) else v for k, v in row.items()})

    def fetchone(self):
        return self._row(self.cursor.fetchone())

    def fetchall(self):
        return [self._row(r) for r in self.cursor.fetchall()]


class PostgresConnection:
    """Small DB-API adapter retaining the existing service interfaces."""
    postgres = True

    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql, params=()):
        # Service queries have no literal question marks; all values remain bound parameters.
        if isinstance(sql, str):
            sql = sql.replace("?", "%s").replace("datetime('now', 'localtime')", "CURRENT_TIMESTAMP")
        # Single statements autocommit; transaction() manages rollback for grouped writes.
        return Cursor(self.raw.execute(sql, params))

    def __enter__(self):
        self.raw.__enter__()
        return self

    def __exit__(self, *args):
        return self.raw.__exit__(*args)

    def transaction(self):
        return self.raw.transaction()

    def cursor(self):
        return self.raw.cursor()

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        self.raw.rollback()
        self.raw.close()


def insert_id(db, sql, params):
    if getattr(db, "postgres", False):
        return db.execute(sql + " RETURNING id", params).fetchone()["id"]
    return db.execute(sql, params).lastrowid


def json_value(db, value):
    import json
    from psycopg.types.json import Jsonb
    return Jsonb(value) if getattr(db, "postgres", False) else json.dumps(value)


# Explicit CLI/programmatic migration entrypoint; never invoked at application startup.
SCHEMA_VERSION = 2

def init_db(url):
    from .migrations import migrate
    with connect(url).raw as raw:
        migrate(raw)
