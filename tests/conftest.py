import html
import os
import re
import uuid

import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from backend import create_app
from backend.db import connect, init_db


def _where(url: str) -> tuple:
    info = conninfo_to_dict(url)
    return (info.get("host", "").replace("-pooler", ""), info.get("dbname"))


@pytest.fixture(scope="session")
def database_url():
    """A throwaway schema on the TEST database (never the real one), dropped after the run."""
    base = os.environ.get("TEST_DATABASE_URL", "")
    if not base:
        pytest.exit("Set TEST_DATABASE_URL in .env to a Neon test branch (see .env.example).", returncode=2)
    production = os.environ.get("PRODUCTION_DATABASE_URL")
    if production and _where(production) == _where(base):
        pytest.exit("TEST_DATABASE_URL points at the production database. Use the Neon dev branch.", returncode=2)

    schema = f"test_{uuid.uuid4().hex[:12]}"
    with connect(base) as db:
        db.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    url = make_conninfo(base, options=f"-c search_path={schema}")
    init_db(url)
    yield url
    with connect(base) as db:
        db.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture()
def app(tmp_path, database_url):
    with connect(database_url) as db:
        db.execute("TRUNCATE users, failed_logins, estimates, audit_log RESTART IDENTITY CASCADE")
    return create_app({"TESTING": True, "SECRET_KEY": "test", "DATABASE_URL": database_url},
                      instance_dir=str(tmp_path))


class Browser:
    """A test client that remembers the CSRF token, like a real browser tab would."""

    def __init__(self, client):
        self.c = client

    def token(self) -> str:
        with self.c.session_transaction() as s:
            s.setdefault("csrf", "tok")
            return s["csrf"]

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def post(self, url, data=None, **kw):
        data = dict(data or {})
        data.setdefault("csrf", self.token())
        return self.c.post(url, data=data, **kw)

    def api(self, method, url, json=None):
        return self.c.open(url, method=method, json=json, headers={"X-CSRF-Token": self.token()})

    def login(self, username, password):
        return self.post("/login", {"username": username, "password": password})

    def logout(self):
        return self.post("/logout")


@pytest.fixture()
def browser(app):
    return Browser(app.test_client())


@pytest.fixture()
def make_browser(app):
    return lambda: Browser(app.test_client())


@pytest.fixture()
def admin(browser):
    """A fresh install with an admin 'boss' created and signed in."""
    browser.post("/setup", {"username": "boss", "full_name": "The Boss",
                            "password": "adminpass1", "confirm": "adminpass1"})
    assert browser.login("boss", "adminpass1").status_code == 302
    return browser


def flashes(resp) -> str:
    return html.unescape(" ".join(re.findall(r'<li class="(?:ok|error)">([^<]*)</li>', resp.get_data(as_text=True))))


ESTIMATE = {
    "title": "Corolla for Mr A",
    "summary": "New registration · Motor car · Filer",
    "total": 123456.5,
    "inputs": {"txn": "new", "vehicle": "car", "cc": "1300", "invoiceDate": "2026-07-01", "regDate": "2026-10-20"},
    "lines": [{"label": "Registration fee", "amount": 100000}, {"label": "Platform", "amount": 23456.5}],
}
