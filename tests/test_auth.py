from conftest import flashes, uid_of


def test_fresh_install_shows_sign_in(browser):
    # No setup page: an empty database just shows the normal sign-in and sign-up pages
    assert browser.get("/").headers["Location"].startswith("/login")
    assert browser.get("/login").status_code == 200
    assert browser.get("/signup").status_code == 200


def test_setup_page_is_gone(browser):
    assert browser.get("/setup").status_code == 404
    resp = browser.post("/setup", {"username": "x", "password": "longenough", "confirm": "longenough"})
    assert resp.status_code == 404


def test_pages_require_login(boss):
    boss.logout()
    for url in ("/", "/estimates", "/account", "/admin/users", "/admin/activity", "/admin/estimates", "/admin/users/1"):
        resp = boss.get(url)
        assert resp.status_code == 302 and "/login" in resp.headers["Location"]


def test_wrong_password_rejected(boss):
    boss.logout()
    resp = boss.login("boss", "nope-nope")
    assert resp.status_code == 401
    assert "Wrong username or password" in flashes(resp)


def test_unknown_username_rejected_the_same_way(browser):
    resp = browser.login("nobody", "whatever1")
    assert resp.status_code == 401
    assert "Wrong username or password" in flashes(resp)


def test_username_is_case_insensitive(make_user, make_browser):
    make_user("Sana", login=False)
    assert make_browser().login("sana", "Sanapass1").status_code == 302


def test_lockout_after_repeated_failures(boss):
    boss.logout()
    for _ in range(5):
        boss.login("boss", "wrong-pass")
    resp = boss.login("boss", "adminpass1")
    assert resp.status_code == 429


def test_post_without_csrf_rejected(boss):
    resp = boss.c.post("/admin/users/add", data={"username": "x", "password": "longenough"})
    assert resp.status_code == 400


def test_signup_can_be_disabled(app, make_browser, boss):
    app.config["ALLOW_SIGNUP"] = False
    resp = make_browser().post("/signup", {"username": "x", "password": "longenough", "confirm": "longenough"})
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/login")


def test_signup_rejects_duplicate_username(make_browser, boss):
    resp = make_browser().post("/signup", {"username": "BOSS", "password": "longenough", "confirm": "longenough"})
    assert resp.status_code == 409


def test_disabled_user_is_signed_out(app, make_browser, boss):
    boss.post("/admin/users/add", {"username": "sara", "password": "sarapass1"})
    sara = make_browser()
    sara.login("sara", "sarapass1")
    assert sara.get("/").status_code == 200

    boss.post(f"/admin/users/{uid_of(app, 'sara')}/disable")
    assert sara.get("/").status_code == 302


def test_cannot_disable_or_delete_yourself(app, boss):
    uid = uid_of(app, "boss")
    resp = boss.post(f"/admin/users/{uid}/delete", follow_redirects=True)
    assert "can't disable or delete your own account" in flashes(resp)


def test_change_password(boss):
    resp = boss.post("/account", {"current": "adminpass1", "password": "newpass123", "confirm": "newpass123"})
    assert resp.status_code == 302
    boss.logout()
    assert boss.login("boss", "newpass123").status_code == 302


def test_open_redirect_blocked(boss):
    boss.logout()
    resp = boss.post("/login?next=//evil.example", {"username": "boss", "password": "adminpass1"})
    assert resp.headers["Location"] == "/"


def test_activity_log_records_sign_ins(boss):
    page = boss.get("/admin/activity").get_data(as_text=True)
    assert "Signed in" in page


def test_security_headers(boss):
    resp = boss.get("/")
    assert "frame-ancestors 'none'" in resp.headers["Content-Security-Policy"]
    assert resp.headers["Cache-Control"] == "no-store"
