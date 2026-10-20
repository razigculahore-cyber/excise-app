"""One-time copy of the old SQLite database (instance/users.db) into PostgreSQL.

    flask migrate-sqlite --superadmin USERNAME --dry-run     # full rehearsal, then rolled back
    flask migrate-sqlite --superadmin USERNAME               # the real copy (asks you to confirm)

- The SQLite file is opened read-only and never changed.
- The target must have no users, estimates or activity yet; otherwise nothing is written.
- Everything happens in one transaction: it all lands, or none of it does.
- IDs, usernames, password hashes, estimates and activity are copied as they are. The chosen admin
  becomes the Super Admin; other admins stay admins; everyone else is a normal user.
- SQLite stored this computer's local time; it is read as --source-timezone and stored as UTC.
"""
import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import click
import psycopg
from flask import current_app
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from werkzeug.security import check_password_hash

from .db import SCHEMA, SCHEMA_VERSION, connect
from .permissions import ADMIN, SUPERADMIN, USER

TABLES = ("users", "estimates", "audit_log", "failed_logins")


class MigrationError(Exception):
    pass


def read_sqlite(path: str) -> dict[str, list[dict]]:
    """All rows of the old database, opened read-only so the file can't be changed."""
    import sqlite3

    if not os.path.isfile(path):
        raise MigrationError(f"No SQLite database at {path}.")
    src = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    try:
        # Table names come from the fixed TABLES list above, never from input
        return {t: [dict(r) for r in src.execute(f"SELECT * FROM {t} ORDER BY rowid")]  # noqa: S608
                for t in TABLES}
    except sqlite3.Error as e:
        raise MigrationError(f"Couldn't read the SQLite database: {e}") from None
    finally:
        src.close()


def _when(text: str | None, zone: ZoneInfo) -> datetime | None:
    if not text:
        return None
    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=zone)


def prepare(data: dict[str, list[dict]], superadmin: str, source_tz: str) -> dict[str, list[dict]]:
    """Check the old data and turn it into rows for PostgreSQL. Raises MigrationError on any problem."""
    zone = ZoneInfo(source_tz)
    seen: dict[str, str] = {}
    for u in data["users"]:
        key = u["username"].lower()
        if key in seen:
            raise MigrationError(f"Usernames {seen[key]!r} and {u['username']!r} differ only in capitals.")
        seen[key] = u["username"]

    chosen = [u for u in data["users"] if u["username"].lower() == superadmin.lower()]
    if not chosen:
        raise MigrationError(f"There is no account called {superadmin!r} in the SQLite database.")
    if not chosen[0]["is_admin"] or not chosen[0]["is_active"]:
        raise MigrationError(f"{superadmin!r} must be an active admin to become the Super Admin.")

    user_ids = {u["id"] for u in data["users"]}
    users = [{
        "id": u["id"], "username": u["username"], "full_name": u["full_name"] or "",
        "password_hash": u["password_hash"],
        "role": SUPERADMIN if u["id"] == chosen[0]["id"] else (ADMIN if u["is_admin"] else USER),
        "is_active": bool(u["is_active"]),
        "created_at": _when(u["created_at"], zone), "last_login": _when(u["last_login"], zone),
    } for u in data["users"]]

    estimates = []
    for e in data["estimates"]:
        if e["user_id"] not in user_ids:
            raise MigrationError(f"Estimate {e['id']} belongs to a user that doesn't exist.")
        try:
            json.loads(e["inputs"])
            json.loads(e["lines"])
        except (TypeError, ValueError):
            raise MigrationError(f"Estimate {e['id']} has damaged data.") from None
        estimates.append({**e, "created_at": _when(e["created_at"], zone)})

    audit = [{**a, "at": _when(a["at"], zone)} for a in data["audit_log"]]
    return {"users": users, "estimates": estimates, "audit_log": audit,
            "failed_logins": [dict(f) for f in data["failed_logins"]]}


def _insert(db: psycopg.Connection, table: str, rows: list[dict], identity: bool) -> None:
    if not rows:
        return
    cols = list(rows[0])
    stmt = sql.SQL("INSERT INTO {} ({}) {} VALUES ({})").format(
        sql.Identifier(table),
        sql.SQL(", ").join(map(sql.Identifier, cols)),
        sql.SQL("OVERRIDING SYSTEM VALUE" if identity else ""),
        sql.SQL(", ").join(sql.Placeholder() * len(cols)))
    with db.cursor() as cur:
        cur.executemany(stmt, [tuple(r[c] for c in cols) for r in rows])


def _count(db: psycopg.Connection, table: str) -> int:
    return db.execute(sql.SQL("SELECT COUNT(*) AS n FROM {}").format(
        sql.Identifier(table))).fetchone()["n"]


def verify(db: psycopg.Connection, rows: dict[str, list[dict]]) -> dict[str, int]:
    """Compare the copy with the source. Raises MigrationError if anything doesn't match."""
    counts = {t: _count(db, t) for t in TABLES}
    for t in TABLES:
        if counts[t] != len(rows[t]):
            raise MigrationError(f"{t}: expected {len(rows[t])} rows, found {counts[t]}.")
    copied = {r["id"]: r for r in db.execute("SELECT id, username, password_hash, role FROM users").fetchall()}
    for u in rows["users"]:
        got = copied.get(u["id"])
        if not got or (got["username"], got["password_hash"], got["role"]) != (
                u["username"], u["password_hash"], u["role"]):
            raise MigrationError(f"User {u['id']} wasn't copied exactly.")
    if db.execute("SELECT COUNT(*) AS n FROM users WHERE role = %s", (SUPERADMIN,)).fetchone()["n"] != 1:
        raise MigrationError("Expected exactly one Super Admin.")
    orphans = db.execute("SELECT COUNT(*) AS n FROM estimates e LEFT JOIN users u ON u.id = e.user_id"
                         " WHERE u.id IS NULL").fetchone()["n"]
    if orphans:
        raise MigrationError(f"{orphans} estimates have no owner.")
    return counts


def run(sqlite_path: str, target_url: str, superadmin: str, source_tz: str = "Asia/Karachi",
        dry_run: bool = True, check_password: str | None = None) -> dict[str, int]:
    """Copy and verify. With dry_run the whole copy happens and is checked, then rolled back."""
    rows = prepare(read_sqlite(sqlite_path), superadmin, source_tz)
    with connect(target_url) as db:
        try:
            with db.transaction():
                db.execute(SCHEMA)
                db.execute("INSERT INTO schema_version (version) VALUES (%s) ON CONFLICT DO NOTHING",
                           (SCHEMA_VERSION,))
                busy = [t for t in ("users", "estimates", "audit_log") if _count(db, t)]
                if busy:
                    raise MigrationError(f"The target already has data in {', '.join(busy)}. Nothing was changed.")
                _insert(db, "users", rows["users"], identity=True)
                _insert(db, "estimates", rows["estimates"], identity=True)
                _insert(db, "audit_log", rows["audit_log"], identity=True)
                _insert(db, "failed_logins", rows["failed_logins"], identity=False)
                for t in ("users", "estimates", "audit_log"):
                    # New rows continue after the copied IDs
                    db.execute(sql.SQL(
                        "SELECT setval(pg_get_serial_sequence({t}, 'id'), COALESCE(MAX(id), 1), MAX(id) IS NOT NULL)"
                        " FROM {i}").format(t=sql.Literal(t), i=sql.Identifier(t)))
                counts = verify(db, rows)
                if check_password is not None:
                    row = db.execute("SELECT password_hash FROM users WHERE role = %s", (SUPERADMIN,)).fetchone()
                    if not check_password_hash(row["password_hash"], check_password):
                        raise MigrationError("That password doesn't match the Super Admin account. "
                                             "Nothing was changed.")
                if dry_run:
                    raise psycopg.Rollback()
        except psycopg.Error as e:
            raise MigrationError(f"The database refused the copy ({type(e).__name__}). Nothing was changed.") from None
    return counts


def describe(url: str) -> str:
    """Where a connection string points, without the password."""
    info = conninfo_to_dict(url)
    return f"{info.get('host', '?')}/{info.get('dbname', '?')}"


@click.command("migrate-sqlite")
@click.option("--sqlite", "sqlite_path", default=None, help="Old database file (default: instance/users.db).")
@click.option("--superadmin", required=True, help="Username of the existing admin who becomes the Super Admin.")
@click.option("--target", "target_env", default="DATABASE_URL_UNPOOLED", show_default=True,
              help="Name of the environment variable holding the target connection string (not the string itself).")
@click.option("--source-timezone", default="Asia/Karachi", show_default=True,
              help="Time zone of the computer that wrote the SQLite file.")
@click.option("--dry-run", is_flag=True, help="Do the whole copy and checks, then roll it back.")
@click.option("--check-login", is_flag=True, help="Ask for the Super Admin's password and check it still works.")
def command(sqlite_path, superadmin, target_env, source_timezone, dry_run, check_login) -> None:
    """Copy the old SQLite database into PostgreSQL (one time)."""
    sqlite_path = sqlite_path or os.path.join(current_app.instance_path, "users.db")
    url = os.environ.get(target_env)
    if not url and target_env == "DATABASE_URL_UNPOOLED":
        url = os.environ.get("DATABASE_URL")   # no direct string configured; the pooled one works too
    if not url:
        raise click.ClickException(f"{target_env} is not set.")
    where = describe(url)
    click.echo(f"Source: {sqlite_path} (read-only)\nTarget: {where}{'  [DRY RUN]' if dry_run else ''}")
    if not dry_run:
        typed = click.prompt("This writes to the target database. Type its host name to continue")
        if typed.strip() != where.split("/")[0]:
            raise click.ClickException("Host name didn't match. Nothing was changed.")
    password = click.prompt("Super Admin's current password", hide_input=True) if check_login else None
    try:
        counts = run(sqlite_path, url, superadmin, source_timezone, dry_run=dry_run, check_password=password)
    except MigrationError as e:
        raise click.ClickException(str(e)) from None
    summary = ", ".join(f"{n} {t}" for t, n in counts.items())
    if dry_run:
        click.echo(f"Dry run OK: {summary} copied and verified, then rolled back. Nothing was changed.")
    else:
        click.echo(f"Done: {summary} copied and verified. '{superadmin}' is the Super Admin.")
    if check_login:
        click.echo("The Super Admin password works against the copied account.")
