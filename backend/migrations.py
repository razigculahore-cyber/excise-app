"""Explicit, transactional schema and read-only-source import commands."""
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import click
from flask import current_app
from psycopg import sql
from psycopg.types.json import Jsonb

from .db import connect, DatabaseUnavailable

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"
TABLES = ("users", "estimates", "audit_log", "failed_logins")


def migrate(raw):
    """One atomic migration transaction, serialized across deployment processes."""
    with raw.transaction():
        raw.execute("SELECT pg_advisory_xact_lock(728419002)")
        raw.execute("CREATE TABLE IF NOT EXISTS excise_schema_migrations (version TEXT PRIMARY KEY, checksum TEXT NOT NULL, applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        for path in sorted(MIGRATIONS.glob("*.sql")):
            source = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(source.encode()).hexdigest()
            existing = raw.execute("SELECT checksum FROM excise_schema_migrations WHERE version=%s", (path.name,)).fetchone()
            if existing:
                if existing["checksum"] != checksum:
                    raise ValueError("Applied migration checksum mismatch")
                continue
            raw.execute(source, prepare=False)
            raw.execute("INSERT INTO excise_schema_migrations(version,checksum) VALUES (%s,%s)", (path.name, checksum))


def read_source(path, source_timezone):
    """SQLite read-only snapshot; no writes, checkpoint or schema changes."""
    zone = ZoneInfo(source_timezone)
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as source:
        source.row_factory = sqlite3.Row
        source.execute("BEGIN")
        rows = {table: [dict(r) for r in source.execute(f'SELECT * FROM {table}')] for table in TABLES}
    names = [r["username"].lower() for r in rows["users"]]
    if len(names) != len(set(names)):
        raise ValueError("Case-insensitive username conflict in source")
    ids = {r["id"] for r in rows["users"]}
    if any(r["user_id"] not in ids for r in rows["estimates"]):
        raise ValueError("Source contains orphan estimates")
    for table, records in rows.items():
        for record in records:
            for key in ("created_at", "last_login", "at"):
                value = record.get(key)
                if value is not None and (key != "at" or table == "audit_log"):
                    stamp = datetime.fromisoformat(value)
                    record[key] = (stamp if stamp.tzinfo else stamp.replace(tzinfo=zone)).astimezone(timezone.utc)
            if table == "estimates":
                for key in ("inputs", "lines"):
                    record[key] = json.loads(record[key])
    return rows


def import_rows(raw, rows):
    """Fail closed on populated destinations; reruns never duplicate records."""
    with raw.transaction():
        raw.execute("LOCK TABLE users, estimates, audit_log, failed_logins IN EXCLUSIVE MODE")
        for table in TABLES:
            if raw.execute(sql.SQL("SELECT COUNT(*) AS n FROM {}").format(sql.Identifier(table))).fetchone()["n"]:
                raise ValueError("Destination must be empty; no records were imported")
        for table, records in rows.items():
            for record in records:
                columns = list(record)
                values = [Jsonb(record[k]) if k in ("inputs", "lines") else record[k] for k in columns]
                raw.execute(sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                    sql.Identifier(table), sql.SQL(',').join(map(sql.Identifier, columns)),
                    sql.SQL(',').join(sql.Placeholder() for _ in columns)), values)
            n = raw.execute(sql.SQL("SELECT COUNT(*) AS n FROM {}").format(sql.Identifier(table))).fetchone()["n"]
            if n != len(records):
                raise ValueError("Imported row count mismatch")
        # ALTER SEQUENCE is transactional, unlike setval(). Only allowlisted table names are used.
        for table in ("users", "estimates", "audit_log"):
            next_id = max((r["id"] for r in rows[table]), default=0) + 1
            seq = raw.execute("SELECT pg_get_serial_sequence(%s, 'id') AS seq", (table,)).fetchone()["seq"]
            parts = seq.split('.')
            raw.execute(sql.SQL("ALTER SEQUENCE {} RESTART WITH {}").format(sql.Identifier(*parts), sql.Literal(next_id)))


def register_commands(app):
    def connection():
        url = current_app.config["DATABASE_URL"]
        if not url:
            raise click.ClickException("DATABASE_URL is required")
        return connect(url).raw

    @app.cli.command("db-migrate")
    @click.option("--confirm-write", is_flag=True, help="Approve additive schema writes to the configured destination.")
    def db_migrate(confirm_write):
        if not confirm_write:
            click.echo("Pending migration files: " + ', '.join(p.name for p in sorted(MIGRATIONS.glob('*.sql'))))
            click.echo("No connection or writes made. Review SQL and use --confirm-write to apply.")
            return
        try:
            with connection() as raw:
                migrate(raw)
        except Exception:
            raise click.ClickException("Migration failed; transaction rolled back. Check destination and schema compatibility.") from None
        click.echo("Migrations applied.")

    @app.cli.command("db-import-sqlite")
    @click.argument("source", type=click.Path(exists=True, dir_okay=False))
    @click.option("--source-timezone", required=True, help="IANA timezone used by the original SQLite server.")
    @click.option("--dry-run", is_flag=True, help="Validate source only; never connect to destination.")
    @click.option("--confirm-write", is_flag=True, help="Approve import including preserved accounts into an empty destination.")
    def db_import(source, source_timezone, dry_run, confirm_write):
        try:
            rows = read_source(source, source_timezone)
            click.echo("Source row counts: " + json.dumps({k: len(v) for k, v in rows.items()}))
            if dry_run or not confirm_write:
                click.echo("Dry run: source unchanged; destination not contacted.")
                return
            with connection() as raw:
                import_rows(raw, rows)
        except Exception:
            raise click.ClickException("Import failed. Check source timezone, integrity, migrations and empty destination. No partial import committed.") from None
        click.echo("Import verified and committed; original SQLite unchanged.")
