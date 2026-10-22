"""Production settings: required secrets, secure cookies, proxy handling, safe errors, no disk writes."""
import os

import pytest

from backend import create_app
from backend.config import build_config

STRONG_KEY = "k" * 48


@pytest.fixture()
def production_env(monkeypatch, database_url):
    for name in ("HTTPS", "TRUST_PROXY", "APP_ENV", "VERCEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", STRONG_KEY)
    monkeypatch.setenv("DATABASE_URL", database_url)
    return monkeypatch


def test_production_requires_a_strong_secret_key(production_env, tmp_path):
    production_env.delenv("SECRET_KEY")
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        build_config(str(tmp_path))
    production_env.setenv("SECRET_KEY", "short")
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        build_config(str(tmp_path))


def test_vercel_counts_as_production(monkeypatch, tmp_path):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("VERCEL", "1")
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        build_config(str(tmp_path))


def test_production_never_writes_to_disk(production_env, tmp_path):
    instance = tmp_path / "instance"
    create_app(instance_dir=str(instance))
    assert not instance.exists()


def test_production_defaults_are_secure(production_env, tmp_path):
    cfg = build_config(str(tmp_path))
    assert cfg["SESSION_COOKIE_SECURE"] and cfg["TRUST_PROXY"] and cfg["SESSION_COOKIE_HTTPONLY"]
    assert cfg["SESSION_COOKIE_NAME"] == "__Host-session"
    assert cfg["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert cfg["SECRET_KEY"] == STRONG_KEY


def test_missing_database_url_fails_clearly(production_env, tmp_path):
    production_env.delenv("DATABASE_URL")
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        create_app(instance_dir=str(tmp_path))


def test_https_cookie_and_hsts(production_env, tmp_path):
    app = create_app(instance_dir=str(tmp_path))
    resp = app.test_client().get("/login", base_url="https://excise.example",
                                 headers={"X-Forwarded-Proto": "https", "X-Forwarded-For": "203.0.113.9"})
    assert resp.headers["Strict-Transport-Security"].startswith("max-age=")
    cookie = resp.headers.get("Set-Cookie", "")
    assert cookie.startswith("__Host-session=") and "Secure" in cookie and "HttpOnly" in cookie


def test_proxy_supplies_the_real_client_ip(production_env, tmp_path):
    app = create_app(instance_dir=str(tmp_path))
    c = app.test_client()
    c.get("/login", base_url="https://excise.example", headers={"X-Forwarded-Proto": "https"})
    with c.session_transaction(base_url="https://excise.example") as s:
        s["csrf"] = "tok"
    c.post("/login", base_url="https://excise.example", data={"csrf": "tok", "username": "x", "password": "y"},
           headers={"X-Forwarded-For": "203.0.113.9", "X-Forwarded-Proto": "https"})
    with app.app_context():
        from backend.db import get_db
        row = get_db().execute("SELECT ip FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    assert row["ip"] == "203.0.113.9"


def test_without_trust_proxy_forwarded_ip_is_ignored(app, browser):
    browser.c.post("/login", data={"csrf": browser.token(), "username": "x", "password": "y"},
                   headers={"X-Forwarded-For": "203.0.113.9"})
    with app.app_context():
        from backend.db import get_db
        row = get_db().execute("SELECT ip FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    assert row["ip"] != "203.0.113.9"


def test_server_errors_show_a_plain_page(app, browser):
    app.config["PROPAGATE_EXCEPTIONS"] = False

    @app.get("/boom")
    def boom():
        raise RuntimeError("postgresql://user:secret-password@host/db exploded")

    resp = browser.get("/boom")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 500 and "Something went wrong" in body
    assert "secret-password" not in body and "Traceback" not in body


def test_oversized_request_rejected(boss):
    resp = boss.api("POST", "/api/estimates", {"title": "x" * 300_000})
    assert resp.status_code == 413


def test_example_env_file_has_no_values():
    path = os.path.join(os.path.dirname(__file__), "..", ".env.example")
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                name, _, value = line.partition("=")
                assert value == "" or value in ("production", "1", "0", "Asia/Karachi"), name
