import html
import re

import pytest

from backend import create_app


@pytest.fixture()
def app(tmp_path):
    return create_app({"TESTING": True, "SECRET_KEY": "test"}, instance_dir=str(tmp_path))


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
