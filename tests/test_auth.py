from conftest import flashes


def test_fresh_install_redirects_to_setup(browser):
    for url in ("/", "/login", "/signup"):
        resp = browser.get(url)
        assert resp.status_code == 302 and resp.headers["Location"].endswith("/setup")


def test_setup_creates_admin_once(admin):
    assert admin.get("/setup").headers["Location"].endswith("/login")
    assert admin.get("/admin/users").status_code == 200


def test_pages_require_login(admin):
    admin.logout()
    for url in ("/", "/estimates", "/account", "/admin/users", "/admin/activity"):
        resp = admin.get(url)
        assert resp.status_code == 302 and "/login" in resp.headers["Location"]


def test_wrong_password_rejected(admin):
    admin.logout()
    resp = admin.login("boss", "nope-nope")
    assert resp.status_code == 401
    assert "Wrong username or password" in flashes(resp)


def test_lockout_after_repeated_failures(admin):
    admin.logout()
    for _ in range(5):
        admin.login("boss", "wrong-pass")
    resp = admin.login("boss", "adminpass1")
    assert resp.status_code == 429


def test_post_without_csrf_rejected(admin):
    resp = admin.c.post("/admin/users/add", data={"username": "x", "password": "longenough"})
    assert resp.status_code == 400


def test_signup_gets_staff_account(make_browser, admin):
    staff = make_browser()
    resp = staff.post("/signup", {"username": "ali", "full_name": "Ali",
                                  "password": "staffpass1", "confirm": "staffpass1"})
    assert resp.status_code == 302
    assert staff.get("/").status_code == 200
    assert staff.get("/admin/users").status_code == 403
    assert staff.api("GET", "/api/me").get_json()["is_admin"] is False


def test_signup_can_be_disabled(app, make_browser, admin):
    app.config["ALLOW_SIGNUP"] = False
    resp = make_browser().post("/signup", {"username": "x", "password": "longenough", "confirm": "longenough"})
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/login")


def test_signup_rejects_duplicate_username(make_browser, admin):
    resp = make_browser().post("/signup", {"username": "BOSS", "password": "longenough", "confirm": "longenough"})
    assert resp.status_code == 409


def test_disabled_user_is_signed_out(make_browser, admin):
    admin.post("/admin/users/add", {"username": "sara", "password": "sarapass1"})
    sara = make_browser()
    sara.login("sara", "sarapass1")
    assert sara.get("/").status_code == 200

    uid = admin.api("GET", "/api/me").get_json()["id"] + 1
    admin.post(f"/admin/users/{uid}/disable")
    assert sara.get("/").status_code == 302


def test_cannot_remove_last_admin(admin):
    uid = admin.api("GET", "/api/me").get_json()["id"]
    resp = admin.post(f"/admin/users/{uid}/delete", follow_redirects=True)
    assert "can't disable or delete your own account" in flashes(resp)


def test_change_password(admin):
    resp = admin.post("/account", {"current": "adminpass1", "password": "newpass123", "confirm": "newpass123"})
    assert resp.status_code == 302
    admin.logout()
    assert admin.login("boss", "newpass123").status_code == 302


def test_open_redirect_blocked(admin):
    admin.logout()
    resp = admin.post("/login?next=//evil.example", {"username": "boss", "password": "adminpass1"})
    assert resp.headers["Location"] == "/"


def test_activity_log_records_sign_ins(admin):
    page = admin.get("/admin/activity").get_data(as_text=True)
    assert "Created first admin" in page and "Signed in" in page


def test_security_headers(admin):
    resp = admin.get("/")
    assert "frame-ancestors 'none'" in resp.headers["Content-Security-Policy"]
    assert resp.headers["Cache-Control"] == "no-store"
