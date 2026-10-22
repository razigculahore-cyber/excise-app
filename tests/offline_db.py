"""Offline-only DB-API double for Flask behavior tests, never selected by production code.

This validates application behavior; it cannot validate PostgreSQL SQL or concurrency.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import current_app
from psycopg.errors import CheckViolation, InsufficientPrivilege, UniqueViolation
from psycopg.types.json import Jsonb

from backend.db import Row

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL, full_name TEXT NOT NULL DEFAULT '',
 password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('user','admin','superadmin')),
 is_active INTEGER NOT NULL DEFAULT 1, session_version INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, last_login TEXT,
 CHECK(role <> 'superadmin' OR is_active));
CREATE UNIQUE INDEX IF NOT EXISTS users_username_key ON users(lower(username));
CREATE UNIQUE INDEX IF NOT EXISTS users_one_superadmin ON users(role) WHERE role='superadmin';
CREATE TRIGGER IF NOT EXISTS protect_delete BEFORE DELETE ON users WHEN OLD.role='superadmin'
 BEGIN SELECT RAISE(ABORT,'protected superadmin'); END;
CREATE TRIGGER IF NOT EXISTS protect_role BEFORE UPDATE OF role ON users WHEN OLD.role='superadmin' AND NEW.role<>'superadmin'
 BEGIN SELECT RAISE(ABORT,'protected superadmin'); END;
CREATE TABLE IF NOT EXISTS estimates (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 title TEXT NOT NULL, summary TEXT NOT NULL DEFAULT '',total REAL NOT NULL,inputs TEXT NOT NULL,lines TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS audit_log (
 id INTEGER PRIMARY KEY AUTOINCREMENT,at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,user_id INTEGER,
 username TEXT NOT NULL DEFAULT '',event TEXT NOT NULL,detail TEXT NOT NULL DEFAULT '',ip TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS failed_logins(username TEXT NOT NULL,ip TEXT NOT NULL,at REAL NOT NULL);
"""


class Cursor:
    def __init__(self, cursor):
        self.cursor = cursor
        self.rowcount = cursor.rowcount

    def _row(self, row):
        if row is None:
            return None
        result = Row(dict(row))
        for key in ('created_at', 'last_login', 'at'):
            value = result.get(key)
            if isinstance(value, str):
                stamp = datetime.fromisoformat(value)
                stamp = stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
                zone = current_app.config.get('APP_TIMEZONE', 'Asia/Karachi') if current_app else 'Asia/Karachi'
                result[key] = stamp.astimezone(ZoneInfo(zone)).strftime('%Y-%m-%d %H:%M:%S')
        return result

    def fetchone(self):
        return self._row(self.cursor.fetchone())

    def fetchall(self):
        return [self._row(row) for row in self.cursor.fetchall()]


class OfflineDB:
    postgres = False

    def __init__(self, path):
        self.raw = sqlite3.connect(path, isolation_level=None)
        self.raw.row_factory = sqlite3.Row
        self.raw.execute('PRAGMA foreign_keys=ON')
        self.raw.executescript(SCHEMA)

    def execute(self, statement, params=()):
        statement = statement.replace('%s', '?').replace('now()', 'CURRENT_TIMESTAMP')
        if 'event = ANY(?)' in statement:
            events = params[0]
            statement = statement.replace('event = ANY(?)', 'event IN (' + ','.join('?' for _ in events) + ')')
            params = (*events, *params[1:])
        params = tuple(json.dumps(p.obj) if isinstance(p, Jsonb) else p for p in params)
        try:
            return Cursor(self.raw.execute(statement, params))
        except sqlite3.IntegrityError as error:
            if 'protected' in str(error):
                raise InsufficientPrivilege('protected') from None
            if 'CHECK constraint' in str(error):
                raise CheckViolation('check failed') from None
            raise UniqueViolation('unique conflict') from None

    @contextmanager
    def transaction(self):
        self.raw.execute('BEGIN IMMEDIATE')
        try:
            yield self
            self.raw.commit()
        except BaseException:
            self.raw.rollback()
            raise

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        self.raw.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
