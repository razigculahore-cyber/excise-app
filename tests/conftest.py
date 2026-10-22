import html
import os
import re
import uuid

import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from backend import create_app
from backend.db import connect, init_db
from backend.services import users


def pytest_addoption(parser):
    parser.addoption("--postgres", action="store_true", help="Use isolated local PostgreSQL test schemas")


# This helper belongs to tests only. Runtime never accepts offline:// URLs.
_real_connect = connect

def connect(url, *args, **kwargs):
    if url.startswith("offline://"):
        from offline_db import OfflineDB
        return OfflineDB(url.removeprefix("offline://"))
    return _real_connect(url, *args, **kwargs)


@pytest.fixture()
def database_url(tmp_path, request, monkeypatch):
    import backend.db
    monkeypatch.setattr(backend.db, "connect", connect)
    monkeypatch.setattr("backend.migrate.connect", connect)
    if not request.config.getoption("--postgres"):
        url = "offline://" + str(tmp_path / "test.sqlite")
        with connect(url):
            pass
        yield url
        return
    base = os.environ.get("TEST_DATABASE_URL", "")
    info = conninfo_to_dict(base)
    if info.get("host") not in ("localhost", "127.0.0.1", "::1") or not info.get("dbname", "").endswith("_test"):
        pytest.fail("--postgres requires local TEST_DATABASE_URL with database name ending _test")
    schema = "excise_test_" + uuid.uuid4().hex
    # Local-only test server may omit TLS. Application runtime still enforces TLS.
    import psycopg
    from psycopg.rows import dict_row
    from backend.db import PostgresConnection
    def local_connect(url, *args, **kwargs):
        return PostgresConnection(psycopg.connect(url, autocommit=True, row_factory=dict_row))
    monkeypatch.setattr(backend.db, "connect", local_connect)
    monkeypatch.setattr("backend.migrate.connect", local_connect)
    monkeypatch.setattr("backend.migrations.connect", local_connect)
    with local_connect(base) as control:
        control.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        url = make_conninfo(base, options=f"-c search_path={schema} -c timezone=UTC")
        try:
            init_db(url)
            init_db(url)
            yield url
        finally:
            control.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture()
def app(tmp_path, database_url):
    return create_app({"TESTING": True, "SECRET_KEY": "test", "ALLOW_SIGNUP": True,
                       "DATABASE_URL": database_url, "DATABASE_URL_UNPOOLED": database_url}, instance_dir=str(tmp_path))


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
def make_user(app):
    """make_user("ali", role="admin") -> a Browser signed in as a new account with that role."""
    def make(username: str, role: str = "user", password: str | None = None, login: bool = True) -> Browser:
        password = password or f"{username}pass1"
        with app.app_context():
            if role == "superadmin":
                users.create_superadmin(username, f"{username.title()} Person", password)
            else:
                users.create(username, f"{username.title()} Person", password, role=role)
        b = Browser(app.test_client())
        if login:
            assert b.login(username, password).status_code == 302
        return b
    return make


@pytest.fixture()
def boss(make_user):
    """The Super Admin 'boss' (password adminpass1), created as the terminal command does, signed in."""
    return make_user("boss", role="superadmin", password="adminpass1")


def uid_of(app, username: str) -> int:
    with app.app_context():
        return users.get_by_username(username)["id"]


def flashes(resp) -> str:
    return html.unescape(" ".join(re.findall(r'<li class="(?:ok|error)">([^<]*)</li>', resp.get_data(as_text=True))))


ESTIMATE = {
    "title": "Corolla for Mr A",
    "summary": "New registration · Motor car · Filer",
    "total": 123456.5,
    "inputs": {"txn": "new", "vehicle": "car", "cc": "1300", "invoiceDate": "2026-07-01", "regDate": "2026-10-20"},
    "lines": [{"label": "Registration fee", "amount": 100000}, {"label": "Platform", "amount": 23456.5}],
}
