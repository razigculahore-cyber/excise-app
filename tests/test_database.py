"""Offline adapter, failure, import and configuration regression checks."""
import hashlib
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

import psycopg
import pytest

from backend import create_app
from backend.db import Cursor, DatabaseUnavailable, PostgresConnection, connect, get_db, init_sqlite as init_db
from backend.migrations import read_source
from backend.services import users
from backend.services.estimates import _row_to_dict


def test_missing_database_configuration(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_BACKEND", "postgres")
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        create_app(instance_dir=str(tmp_path))


def test_connection_failure_hides_credentials(monkeypatch):
    def fail(**kwargs):
        raise psycopg.OperationalError("sensitive-password")
    monkeypatch.setattr(psycopg, "connect", fail)
    with pytest.raises(DatabaseUnavailable) as error:
        connect("postgresql://user:sensitive-password@example.invalid/postgres")
    assert "sensitive-password" not in str(error.value)


def test_tls_required():
    with pytest.raises(DatabaseUnavailable):
        connect("postgresql://localhost/db?sslmode=disable")


def test_connection_uses_tls_and_timeout(monkeypatch):
    factory = Mock()
    monkeypatch.setattr(psycopg, "connect", factory)
    connect("postgresql://localhost/db")
    assert factory.call_args.kwargs["sslmode"] == "require"
    assert factory.call_args.kwargs["connect_timeout"] == 10


def test_adapter_binds_values_and_rolls_back():
    raw = Mock()
    db = PostgresConnection(raw)
    value = "x'); DELETE FROM users;--"
    db.execute("SELECT * FROM users WHERE username = ?", (value,))
    raw.execute.assert_called_once_with("SELECT * FROM users WHERE username = %s", (value,))
    raw.execute.side_effect = psycopg.OperationalError("offline")
    with pytest.raises(psycopg.OperationalError):
        db.execute("SELECT 1")
    db.close()
    raw.rollback.assert_called_once()
    raw.close.assert_called_once()


def test_postgres_timestamp_and_json_contract(app):
    raw = Mock()
    raw.fetchone.return_value = {"created_at": datetime(2026, 10, 22, 10, tzinfo=timezone.utc)}
    with app.app_context():
        assert Cursor(raw).fetchone()["created_at"] == "2026-10-22 15:00:00"
    row = dict(id=1, title="a", summary="", total=Decimal("123.50"), inputs={"cc": "1300"}, lines=[], created_at="2026-10-22")
    assert _row_to_dict(row)["total"] == 123.5
    assert _row_to_dict(row)["inputs"] == {"cc": "1300"}


def test_transaction_rollback(app):
    with app.app_context():
        db = get_db()
        try:
            with db.transaction():
                db.execute("INSERT INTO failed_logins(username,ip,at) VALUES (?,?,?)", ("x", "ip", 0))
                raise ValueError("rollback")
        except ValueError:
            pass
        assert db.execute("SELECT COUNT(*) FROM failed_logins").fetchone()[0] == 0


def test_duplicate_can_recover(app):
    with app.app_context():
        uid = users.create("MixedCase", "", "password123")
        with pytest.raises(users.UsernameTaken):
            users.create("mixedcase", "", "password123")
        assert users.get_by_username("MIXEDCASE")["id"] == uid
        assert users.create("another", "", "password123") > uid


def test_web_setup_cannot_create_an_admin(app):
    assert app.test_client().get("/setup").status_code == 404


def test_source_import_is_read_only_and_preserves_hash(tmp_path):
    path = tmp_path / "legacy.db"
    init_db(str(path))
    with sqlite3.connect(path) as source:
        source.execute("INSERT INTO users(id,username,password_hash,created_at) VALUES(7,'original','existing-hash','2026-10-22 15:00:00')")
        source.execute("INSERT INTO estimates(user_id,title,total,inputs,lines) VALUES(7,'Saved',1.5,'{}','[]')")
    before = hashlib.sha256(path.read_bytes()).digest()
    rows = read_source(path, "Asia/Karachi")
    assert hashlib.sha256(path.read_bytes()).digest() == before
    assert rows["users"][0]["password_hash"] == "existing-hash"
    assert rows["users"][0]["id"] == rows["estimates"][0]["user_id"] == 7
    assert rows["users"][0]["created_at"].hour == 10


def test_health_failure_sanitized(app, monkeypatch):
    def fail():
        raise DatabaseUnavailable("Database unavailable. Check server database configuration.")
    monkeypatch.setattr("backend.db.get_db", fail)
    response = app.test_client().get("/api/health")
    assert response.status_code == 503
    assert "error" in response.get_json()


def test_cli_migration_preview_does_not_connect(app, monkeypatch):
    monkeypatch.setattr("backend.migrations.connect", Mock(side_effect=AssertionError("must not connect")))
    response = app.test_cli_runner().invoke(args=["db-migrate"])
    assert response.exit_code == 0
    assert "001_initial.sql" in response.output


def test_cli_import_default_dry_run(app, monkeypatch):
    from pathlib import Path
    init_db(str(Path(app.instance_path) / "legacy.db"))
    monkeypatch.setattr("backend.migrations.connect", Mock(side_effect=AssertionError("must not connect")))
    response = app.test_cli_runner().invoke(args=["db-import-sqlite", str(__import__("pathlib").Path(app.instance_path) / "legacy.db"), "--source-timezone", "Asia/Karachi"])
    assert response.exit_code == 0
    assert "Dry run" in response.output


def test_lockout_case_insensitive(boss):
    admin = boss
    admin.logout()
    for _ in range(5):
        admin.login("BOSS", "wrong-password")
    assert admin.login("boss", "adminpass1").status_code == 429


def test_password_reset_and_activation(make_browser, boss):
    admin = boss
    admin.post("/admin/users/add", {"username": "staff", "password": "staffpass1"})
    from backend.services import users
    with admin.c.application.app_context():
        uid = users.get_by_username("staff")["id"]
        assert users.get(uid)["password_hash"] != "staffpass1"
    admin.post(f"/admin/users/{uid}/reset", {"password": "changedpass1"})
    staff = make_browser()
    assert staff.login("staff", "changedpass1").status_code == 302
    admin.post(f"/admin/users/{uid}/disable")
    assert staff.get("/").status_code == 302
    admin.post(f"/admin/users/{uid}/enable")
    assert staff.login("staff", "changedpass1").status_code == 302


def test_live_postgres_import_integrity_and_sequences(app, tmp_path):
    from backend.migrations import import_rows
    with app.app_context():
        db = get_db()
        if not getattr(db, "postgres", False):
            pytest.skip("requires --postgres and isolated local test database")
        path = tmp_path / "import.db"
        init_db(str(path))
        with sqlite3.connect(path) as source:
            source.execute("INSERT INTO users(id,username,password_hash) VALUES(77,'legacy','original-hash')")
            source.execute("INSERT INTO estimates(id,user_id,title,total,inputs,lines) VALUES(31,77,'legacy estimate',123.5,'{}','[]')")
            source.execute("INSERT INTO audit_log(user_id,event) VALUES(77,'login')")
            source.execute("INSERT INTO failed_logins VALUES('legacy','ip',100)")
        rows = read_source(path, "Asia/Karachi")
        # Finish any read transaction before opening the import's atomic block.
        db.rollback()
        import_rows(db.raw, rows)
        assert users.get(77)["password_hash"] == "original-hash"
        assert db.execute("SELECT user_id FROM estimates WHERE id = ?", (31,)).fetchone()[0] == 77
        assert users.create("next", "", "password123") == 78
        db.rollback()
        with pytest.raises(ValueError, match="Destination must be empty"):
            import_rows(db.raw, rows)
        assert users.count() == 2


def test_live_postgres_migration_checksum_guard(app):
    from backend.migrations import migrate
    with app.app_context():
        db = get_db()
        if not getattr(db, "postgres", False):
            pytest.skip("requires --postgres and isolated local test database")
        db.execute("UPDATE excise_schema_migrations SET checksum = ?", ("tampered",))
        db.commit()
        with pytest.raises(ValueError, match="checksum mismatch"):
            migrate(db.raw)
        assert users.count() == 0
