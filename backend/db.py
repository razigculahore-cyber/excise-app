"""PostgreSQL connection per request, plus the schema (created by `flask init-db`)."""
from datetime import datetime
from zoneinfo import ZoneInfo

import psycopg
from flask import current_app, g
from psycopg.rows import dict_row

SCHEMA_VERSION = 1

# Times are stored in UTC (timestamptz). Rows come back with them already turned into local
# 'YYYY-MM-DD HH:MM:SS' text (APP_TIMEZONE, Asia/Karachi by default), as the pages have always shown.
SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username      TEXT NOT NULL,
    full_name     TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    is_admin      BOOLEAN NOT NULL DEFAULT FALSE,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login    TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS users_username_key ON users (lower(username));
CREATE TABLE IF NOT EXISTS failed_logins (
    username TEXT NOT NULL,
    ip       TEXT NOT NULL,
    at       DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_failed_logins_user ON failed_logins (lower(username), ip);
CREATE TABLE IF NOT EXISTS estimates (
    id         INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title      TEXT NOT NULL,
    summary    TEXT NOT NULL DEFAULT '',
    total      DOUBLE PRECISION NOT NULL,
    inputs     TEXT NOT NULL,
    lines      TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_estimates_user ON estimates (user_id, id DESC);
CREATE TABLE IF NOT EXISTS audit_log (
    id       INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id  INTEGER,
    username TEXT NOT NULL DEFAULT '',
    event    TEXT NOT NULL,
    detail   TEXT NOT NULL DEFAULT '',
    ip       TEXT NOT NULL DEFAULT ''
);
"""


def local_rows(tz: str):
    """Row factory: dict rows with every timestamp shown as local time text."""
    zone = ZoneInfo(tz)

    def factory(cursor):
        make = dict_row(cursor)

        def row(values):
            d = make(values)
            for k, v in d.items():
                if isinstance(v, datetime):
                    d[k] = v.astimezone(zone).strftime("%Y-%m-%d %H:%M:%S")
            return d
        return row
    return factory


def connect(url: str, tz: str = "Asia/Karachi") -> psycopg.Connection:
    # autocommit: each statement commits on its own; use `with db.transaction():` to group writes.
    # prepare_threshold=None: Neon's pooled endpoint (PgBouncer) can't keep prepared statements.
    return psycopg.connect(url, autocommit=True, row_factory=local_rows(tz),
                           prepare_threshold=None, connect_timeout=10)


def get_db() -> psycopg.Connection:
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE_URL"], current_app.config["APP_TIMEZONE"])
    return g.db


def close_db(_exc=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(url: str) -> None:
    """Create any missing tables. Safe to run again; it never drops or changes data."""
    with connect(url) as db, db.transaction():
        db.execute(SCHEMA)
        db.execute("INSERT INTO schema_version (version) VALUES (%s) ON CONFLICT DO NOTHING", (SCHEMA_VERSION,))
