"""Database setup is explicit and safe to repeat."""
from backend.db import SCHEMA_VERSION, connect, init_db
from backend.services import users


def test_init_db_is_safe_to_run_again(app, database_url, boss):
    init_db(database_url)
    init_db(database_url)
    with app.app_context():
        assert users.get_by_username("boss")["role"] == "superadmin"   # existing data untouched
    with connect(database_url) as db:
        assert db.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()["v"] == SCHEMA_VERSION


def test_init_db_command(app):
    result = app.test_cli_runner().invoke(args=["init-db"])
    assert result.exit_code == 0 and "ready" in result.output


def test_app_start_does_not_touch_the_schema(database_url, tmp_path, monkeypatch):
    import backend
    called = []
    monkeypatch.setattr(backend, "init_db", lambda *a: called.append(a))
    backend.create_app({"DATABASE_URL": database_url, "SECRET_KEY": "x"}, instance_dir=str(tmp_path))
    assert called == []


def test_timestamps_are_stored_utc_and_shown_in_pakistan_time(app, boss):
    from backend.db import get_db
    with app.app_context():
        db = get_db()
        db.execute("UPDATE users SET last_login = '2026-01-01 00:00:00+00' WHERE username = 'boss'")
        assert users.get_by_username("boss")["last_login"] == "2026-01-01 05:00:00"


def test_sql_injection_in_username_is_harmless(app, make_browser, boss):
    b = make_browser()
    resp = b.login("boss' OR '1'='1", "anything1")
    assert resp.status_code == 401
    resp = b.post("/signup", {"username": "x');DROP_TABLE_users;--", "password": "longenough", "confirm": "longenough"})
    assert resp.status_code == 302
    with app.app_context():
        assert users.count() == 2
