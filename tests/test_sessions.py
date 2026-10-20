"""A password, role or status change signs the account out of its other sessions."""
from conftest import uid_of


def test_own_password_change_keeps_this_session_and_ends_others(make_user, make_browser):
    phone = make_user("ali")
    laptop = make_browser()
    assert laptop.login("ali", "alipass1").status_code == 302
    resp = phone.post("/account", {"current": "alipass1", "password": "newpass99", "confirm": "newpass99"})
    assert resp.status_code == 302
    assert phone.get("/").status_code == 200
    assert laptop.get("/").status_code == 302


def test_password_reset_by_admin_signs_user_out(app, make_user, boss):
    ali = make_user("ali")
    boss.post(f"/admin/users/{uid_of(app, 'ali')}/reset", {"password": "resetpass1"})
    assert ali.get("/").status_code == 302
    assert ali.api("GET", "/api/me").status_code == 401


def test_promotion_signs_user_out_and_new_session_has_admin_rights(app, make_user, boss):
    ali = make_user("ali")
    boss.post(f"/admin/users/{uid_of(app, 'ali')}/promote")
    assert ali.get("/").status_code == 302
    ali.login("ali", "alipass1")
    assert ali.get("/admin/users").status_code == 200


def test_revoked_admin_loses_access_immediately(app, make_user, boss):
    adam = make_user("adam", role="admin")
    assert adam.get("/admin/users").status_code == 200
    boss.post(f"/admin/users/{uid_of(app, 'adam')}/revoke")
    assert adam.get("/admin/users").status_code == 302
    adam.login("adam", "adampass1")
    assert adam.get("/admin/users").status_code == 403


def test_reenabled_user_must_sign_in_again(app, make_user, boss):
    ali = make_user("ali")
    uid = uid_of(app, "ali")
    boss.post(f"/admin/users/{uid}/disable")
    boss.post(f"/admin/users/{uid}/enable")
    assert ali.get("/").status_code == 302


def test_session_without_version_is_rejected(app, make_user):
    ali = make_user("ali")
    with ali.c.session_transaction() as s:
        s.pop("ver")
    assert ali.get("/").status_code == 302


def test_forged_user_id_in_session_is_useless_without_secret(app, make_user, boss):
    # Sessions are signed with SECRET_KEY: a cookie signed with another key is ignored
    from flask.sessions import SecureCookieSessionInterface
    other = app.__class__(__name__)
    other.secret_key = "not-the-real-key"
    forged = SecureCookieSessionInterface().get_signing_serializer(other).dumps(
        {"user_id": uid_of(app, "boss"), "ver": 1, "csrf": "tok"})
    c = app.test_client()
    c.set_cookie("session", forged)
    assert c.get("/admin/users").status_code == 302
