import html
import re

import pytest

from backend import create_app


def pytest_addoption(parser):
    parser.addoption("--postgres", action="store_true", help="Run against isolated schemas on local TEST_DATABASE_URL ending in _test")


@pytest.fixture()
def app(tmp_path, request, monkeypatch):
    app = create_app({"TESTING": True, "SECRET_KEY": "test", "ALLOW_SIGNUP": True}, instance_dir=str(tmp_path))
    if not request.config.getoption("--postgres"):
        yield app
        return
    import os
    import uuid
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict
    from psycopg.rows import dict_row
    from backend.db import PostgresConnection
    from backend.migrations import migrate
    url = os.environ.get("TEST_DATABASE_URL", "")
    options = conninfo_to_dict(url)
    if options.get("host") not in ("localhost", "127.0.0.1", "::1") or not options.get("dbname", "").endswith("_test"):
        pytest.fail("--postgres requires a local TEST_DATABASE_URL with database name ending _test")
    schema = "excise_test_" + uuid.uuid4().hex
    with psycopg.connect(url, autocommit=True, row_factory=dict_row) as control:
        control.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        def test_connect(_url):
            return PostgresConnection(psycopg.connect(url, options=f"-c search_path={schema} -c timezone=UTC", row_factory=dict_row))
        monkeypatch.setattr("backend.db.connect", test_connect)
        try:
            with test_connect(url).raw as raw:
                migrate(raw)
                migrate(raw)
            app.config["DATABASE_URL"] = url
            yield app
        finally:
            control.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


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
    browser.post("/setup", {"username": "boss", "full_name": "The Boss", "password": "adminpass1", "confirm": "adminpass1"})
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
