"""Roles: who can do what. Every check here hits the server directly, not just the buttons."""
import pytest
from conftest import uid_of

from backend.db import get_db
from backend.services import users

ADMIN_ONLY_PAGES = ("/admin/users",)
SUPERADMIN_ONLY_PAGES = ("/admin/activity", "/admin/activity?user=1", "/admin/estimates",
                         "/admin/estimates?user=1", "/admin/users/1")


def role_of(app, username: str) -> str:
    with app.app_context():
        return users.get_by_username(username)["role"]


# ------------------------------------------------------------------ registration

def test_signup_creates_a_normal_user_who_is_signed_in(app, make_browser, boss):
    b = make_browser()
    resp = b.post("/signup", {"username": "ali", "full_name": "Ali", "password": "alipass12", "confirm": "alipass12"})
    assert resp.status_code == 302
    assert b.get("/").status_code == 200                          # signed in straight away, no approval
    me = b.api("GET", "/api/me").get_json()
    assert me["role"] == "user" and me["is_admin"] is False
    b.logout()
    assert b.login("ali", "alipass12").status_code == 302         # and can sign in again later


def test_signup_ignores_any_role_sent_in_the_request(app, make_browser):
    b = make_browser()
    b.post("/signup", {"username": "sneaky", "password": "sneaky123", "confirm": "sneaky123",
                       "role": "superadmin", "is_admin": "on", "is_superadmin": "1"})
    assert role_of(app, "sneaky") == "user"
    assert b.get("/admin/users").status_code == 403


def test_signup_works_on_an_empty_database_without_creating_an_admin(app, make_browser):
    b = make_browser()
    b.post("/signup", {"username": "first", "password": "first1234", "confirm": "first1234"})
    assert role_of(app, "first") == "user"
    assert b.get("/admin/users").status_code == 403


# ------------------------------------------------------------------ normal users

@pytest.mark.parametrize("url", ADMIN_ONLY_PAGES + SUPERADMIN_ONLY_PAGES)
def test_user_cannot_open_admin_pages(make_user, boss, url):
    assert make_user("ali").get(url).status_code == 403


def test_user_cannot_post_admin_actions(app, make_user, boss):
    ali = make_user("ali")
    make_user("zara", login=False)
    zid = uid_of(app, "zara")
    for action in ("disable", "enable", "delete", "reset", "promote", "revoke"):
        assert ali.post(f"/admin/users/{zid}/{action}", {"password": "whatever12"}).status_code == 403
    assert ali.post(f"/admin/users/{uid_of(app, 'ali')}/promote").status_code == 403   # not even themselves
    assert ali.post("/admin/users/add", {"username": "x", "password": "longenough"}).status_code == 403
    assert role_of(app, "zara") == "user" and role_of(app, "ali") == "user"


# ------------------------------------------------------------------ normal admins

def test_admin_sees_users_list_but_not_sign_in_history(make_user, boss):
    page = make_user("adam", role="admin").get("/admin/users").get_data(as_text=True)
    assert "boss" in page and "Last sign-in" not in page and "Make admin" not in page


@pytest.mark.parametrize("url", SUPERADMIN_ONLY_PAGES)
def test_admin_cannot_open_super_admin_pages(make_user, boss, url):
    assert make_user("adam", role="admin").get(url).status_code == 403


def test_admin_can_add_normal_users_only(app, make_user, boss):
    adam = make_user("adam", role="admin")
    assert adam.post("/admin/users/add", {"username": "newbie", "password": "newbie123"}).status_code == 302
    assert role_of(app, "newbie") == "user"
    resp = adam.post("/admin/users/add", {"username": "newadmin", "password": "newadmin1", "is_admin": "on"})
    assert resp.status_code == 403
    with app.app_context():
        assert users.get_by_username("newadmin") is None


def test_admin_can_manage_normal_users(app, make_user, make_browser, boss):
    adam = make_user("adam", role="admin")
    make_user("ali", login=False)
    aid = uid_of(app, "ali")
    assert adam.post(f"/admin/users/{aid}/reset", {"password": "brandnew1"}).status_code == 302
    assert make_browser().login("ali", "brandnew1").status_code == 302
    assert adam.post(f"/admin/users/{aid}/disable").status_code == 302
    assert make_browser().login("ali", "brandnew1").status_code == 401
    assert adam.post(f"/admin/users/{aid}/enable").status_code == 302


def test_admin_cannot_delete_users(app, make_user, boss):
    adam = make_user("adam", role="admin")
    make_user("ali", login=False)
    assert adam.post(f"/admin/users/{uid_of(app, 'ali')}/delete").status_code == 403
    with app.app_context():
        assert users.get_by_username("ali") is not None


def test_admin_cannot_promote_or_revoke(app, make_user, boss):
    adam = make_user("adam", role="admin")
    make_user("ali", login=False)
    make_user("eve", role="admin", login=False)
    assert adam.post(f"/admin/users/{uid_of(app, 'ali')}/promote").status_code == 403
    assert adam.post(f"/admin/users/{uid_of(app, 'eve')}/revoke").status_code == 403
    assert role_of(app, "ali") == "user" and role_of(app, "eve") == "admin"


def test_admin_cannot_touch_other_admins_or_the_super_admin(app, make_user, boss):
    adam = make_user("adam", role="admin")
    make_user("eve", role="admin", login=False)
    for target in ("eve", "boss"):
        tid = uid_of(app, target)
        for action in ("reset", "disable", "delete", "revoke"):
            assert adam.post(f"/admin/users/{tid}/{action}", {"password": "takeover1"}).status_code == 403
    assert boss.get("/").status_code == 200                       # boss still signed in, password unchanged
    boss.logout()
    assert boss.login("boss", "adminpass1").status_code == 302


def test_admin_cannot_reset_own_password_from_admin_pages(app, make_user, boss):
    adam = make_user("adam", role="admin")
    assert adam.post(f"/admin/users/{uid_of(app, 'adam')}/reset", {"password": "another12"}).status_code == 403


# ------------------------------------------------------------------ Super Admin

def test_super_admin_promotes_and_revokes(app, make_user, boss):
    ali = make_user("ali")
    aid = uid_of(app, "ali")
    assert boss.post(f"/admin/users/{aid}/promote").status_code == 302
    assert role_of(app, "ali") == "admin"
    assert boss.post(f"/admin/users/{aid}/revoke").status_code == 302
    assert role_of(app, "ali") == "user"
    assert boss.post(f"/admin/users/{aid}/revoke").status_code == 403   # already a user
    assert ali.get("/").status_code == 302                              # role changes sign the person out


def test_super_admin_adds_an_admin(app, boss):
    resp = boss.post("/admin/users/add", {"username": "eve", "password": "evepass12", "is_admin": "on"})
    assert resp.status_code == 302
    assert role_of(app, "eve") == "admin"


def test_no_way_to_grant_super_admin_from_the_website(app, make_user, boss):
    make_user("ali", login=False)
    aid = uid_of(app, "ali")
    for action in ("superadmin", "make_superadmin", "promote_superadmin"):
        assert boss.post(f"/admin/users/{aid}/{action}").status_code == 404
    boss.post("/admin/users/add", {"username": "x2", "password": "longenough", "role": "superadmin"})
    assert role_of(app, "x2") == "user"


def test_super_admin_account_is_protected_on_the_website(app, boss):
    bid = uid_of(app, "boss")
    for action in ("disable", "delete", "revoke", "reset"):
        assert boss.post(f"/admin/users/{bid}/{action}", {"password": "x" * 10}).status_code in (302, 403)
    with app.app_context():
        me = users.get(bid)
        assert me["role"] == "superadmin" and me["is_active"]


def test_super_admin_deletes_users(app, make_user, boss):
    make_user("eve", role="admin", login=False)
    assert boss.post(f"/admin/users/{uid_of(app, 'eve')}/delete").status_code == 302
    with app.app_context():
        assert users.get_by_username("eve") is None


# ------------------------------------------------------------------ database-level guarantees

def test_database_allows_only_one_super_admin(app, boss):
    with app.app_context(), pytest.raises(users.SuperAdminExists):
        users.create_superadmin("second", "", "secondpass1")


def test_database_refuses_a_second_super_admin_even_without_the_app_check(app, boss):
    from psycopg.errors import UniqueViolation
    with app.app_context(), pytest.raises(UniqueViolation):
        get_db().execute("INSERT INTO users (username, password_hash, role) VALUES ('x', 'h', 'superadmin')")


def test_database_refuses_to_delete_demote_or_disable_the_super_admin(app, boss):
    from psycopg.errors import CheckViolation, InsufficientPrivilege
    bid = uid_of(app, "boss")
    with app.app_context():
        with pytest.raises(InsufficientPrivilege):
            get_db().execute("DELETE FROM users WHERE id = %s", (bid,))
        with pytest.raises(InsufficientPrivilege):
            get_db().execute("UPDATE users SET role = 'user' WHERE id = %s", (bid,))
        with pytest.raises(CheckViolation):
            get_db().execute("UPDATE users SET is_active = FALSE WHERE id = %s", (bid,))
        with pytest.raises(users.ProtectedAccount):
            users.set_role(bid, "user")


def test_create_rejects_super_admin_role(app):
    with app.app_context(), pytest.raises(ValueError):
        users.create("x", "", "longenough", role="superadmin")


# ------------------------------------------------------------------ terminal commands

def test_create_superadmin_command_runs_once(app):
    runner = app.test_cli_runner()
    first = runner.invoke(args=["create-superadmin", "chief", "--name", "Chief"], input="chiefpass1\nchiefpass1\n")
    assert first.exit_code == 0, first.output
    assert role_of(app, "chief") == "superadmin"
    second = runner.invoke(args=["create-superadmin", "other"], input="otherpass1\notherpass1\n")
    assert second.exit_code != 0 and "already exists" in second.output


def test_set_password_command(app, boss, make_browser):
    result = app.test_cli_runner().invoke(args=["set-password", "boss"], input="resetpass1\nresetpass1\n")
    assert result.exit_code == 0, result.output
    assert boss.get("/").status_code == 302                       # old session signed out
    assert make_browser().login("boss", "resetpass1").status_code == 302


def test_create_user_command(app):
    result = app.test_cli_runner().invoke(args=["create-user", "eve", "--admin"], input="evepass12\nevepass12\n")
    assert result.exit_code == 0, result.output
    assert role_of(app, "eve") == "admin"
