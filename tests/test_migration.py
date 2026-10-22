"""The one-time SQLite -> PostgreSQL copy. Uses a made-up SQLite file in the old format, never the real one."""
import hashlib
import sqlite3

import pytest
from werkzeug.security import generate_password_hash

from backend import migrate
from backend.services import estimates, users

# The schema the app used before PostgreSQL (from the initial commit)
OLD_SCHEMA = """
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL COLLATE NOCASE,
    full_name TEXT NOT NULL DEFAULT '', password_hash TEXT NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    last_login TEXT);
CREATE TABLE failed_logins (username TEXT NOT NULL COLLATE NOCASE, ip TEXT NOT NULL, at REAL NOT NULL);
CREATE TABLE estimates (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL, summary TEXT NOT NULL DEFAULT '', total REAL NOT NULL, inputs TEXT NOT NULL,
    lines TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')));
CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    user_id INTEGER, username TEXT NOT NULL DEFAULT '', event TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '',
    ip TEXT NOT NULL DEFAULT '');
"""


@pytest.fixture()
def old_db(tmp_path):
    """A small SQLite file like instance/users.db, with gaps in the IDs as real data has."""
    path = tmp_path / "users.db"
    db = sqlite3.connect(path)
    db.executescript(OLD_SCHEMA)
    rows = [(1, "Boss", "The Boss", generate_password_hash("bosspass1"), 1, 1, "2026-10-20 19:13:00",
             "2026-10-21 01:30:00"),
            (3, "ali", "", generate_password_hash("alipass12"), 0, 1, "2026-10-20 20:00:00", None),
            (4, "eve", "Eve", generate_password_hash("evepass12"), 1, 0, "2026-10-20 21:00:00", None)]
    db.executemany("INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    db.execute("INSERT INTO estimates VALUES (7, 3, 'Ali car', 's', 1234.5, '{\"cc\": \"1300\"}',"
               " '[{\"label\": \"Fee\", \"amount\": 1234.5}]', '2026-10-21 00:15:00')")
    db.execute("INSERT INTO audit_log VALUES (5, '2026-10-20 19:13:00', 1, 'Boss', 'setup', '', '127.0.0.1')")
    db.execute("INSERT INTO failed_logins VALUES ('ali', '127.0.0.1', 1760000000.5)")
    db.commit()
    db.close()
    return path


def digest(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_dry_run_checks_everything_and_writes_nothing(app, database_url, old_db):
    before = digest(old_db)
    counts = migrate.run(str(old_db), database_url, "boss", dry_run=True)
    assert counts == {"users": 3, "estimates": 1, "audit_log": 1, "failed_logins": 1}
    assert digest(old_db) == before                               # SQLite file untouched
    with app.app_context():
        assert users.count() == 0                                  # rolled back


def test_real_copy_preserves_everything(app, database_url, old_db, make_browser):
    if database_url.startswith("offline://"):
        pytest.skip("PostgreSQL import requires --postgres")
    before = digest(old_db)
    migrate.run(str(old_db), database_url, "boss", dry_run=False, check_password="bosspass1")
    assert digest(old_db) == before
    with app.app_context():
        boss = users.get_by_username("boss")
        assert boss["id"] == 1 and boss["username"] == "Boss" and boss["role"] == "superadmin"
        assert boss["created_at"] == "2026-10-20 19:13:00"         # same Pakistan time as before
        assert users.get(3)["role"] == "user"
        eve = users.get(4)
        assert eve["role"] == "admin" and not eve["is_active"]
        est = estimates.get_for(3, 7)
        assert est["total"] == 1234.5 and est["inputs"] == {"cc": "1300"} and est["created_at"] == "2026-10-21 00:15:00"
        new_id = users.create("newbie", "", "newbie123")
        assert new_id == 5                                          # IDs continue after the copied ones

    # Existing passwords keep working, and roles are live
    b = make_browser()
    assert b.login("boss", "bosspass1").status_code == 302
    assert b.get("/admin/activity").status_code == 200
    assert make_browser().login("ali", "alipass12").status_code == 302


def test_refuses_a_target_that_already_has_data(app, database_url, old_db, boss):
    if database_url.startswith("offline://"):
        pytest.skip("PostgreSQL import requires --postgres")
    with pytest.raises(migrate.MigrationError, match="already has data"):
        migrate.run(str(old_db), database_url, "boss", dry_run=False)
    with app.app_context():
        assert users.count() == 1                                   # only the existing account


def test_wrong_password_check_rolls_everything_back(app, database_url, old_db):
    with pytest.raises(migrate.MigrationError, match="password"):
        migrate.run(str(old_db), database_url, "boss", dry_run=False, check_password="wrong-pass")
    with app.app_context():
        assert users.count() == 0


@pytest.mark.parametrize("name, message", [("nobody", "no account"), ("ali", "active admin"), ("eve", "active admin")])
def test_super_admin_must_be_an_existing_active_admin(database_url, old_db, name, message):
    with pytest.raises(migrate.MigrationError, match=message):
        migrate.run(str(old_db), database_url, name, dry_run=True)


def test_missing_sqlite_file(database_url, tmp_path):
    with pytest.raises(migrate.MigrationError, match="No SQLite"):
        migrate.run(str(tmp_path / "nope.db"), database_url, "boss")


def test_command_dry_run(app, old_db, monkeypatch, database_url):
    monkeypatch.setenv("MIGRATION_TARGET", "postgresql://localhost/excise_test" if database_url.startswith("offline://") else database_url)
    result = app.test_cli_runner().invoke(args=["migrate-sqlite", "--sqlite", str(old_db), "--superadmin", "boss",
                                                "--target", "MIGRATION_TARGET", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "Dry run OK" in result.output and "secret" not in result.output.lower()


def test_command_real_run_needs_the_host_typed(app, old_db, monkeypatch, database_url):
    monkeypatch.setenv("MIGRATION_TARGET", "postgresql://localhost/excise_test" if database_url.startswith("offline://") else database_url)
    result = app.test_cli_runner().invoke(args=["migrate-sqlite", "--sqlite", str(old_db), "--superadmin", "boss",
                                                "--target", "MIGRATION_TARGET"], input="wrong-host\n")
    assert result.exit_code != 0 and "didn't match" in result.output
    with app.app_context():
        assert users.count() == 0
