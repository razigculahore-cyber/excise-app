from conftest import ESTIMATE

from backend.db import get_db


def test_api_requires_login(browser):
    assert browser.api("GET", "/api/estimates").status_code == 401
    assert browser.get("/api/health").get_json() == {"status": "ok"}


def test_save_list_and_reopen(admin):
    resp = admin.api("POST", "/api/estimates", ESTIMATE)
    assert resp.status_code == 201
    est = resp.get_json()["estimate"]
    assert est["total"] == 123456.5 and est["inputs"]["vehicle"] == "car"

    assert len(admin.api("GET", "/api/estimates").get_json()["estimates"]) == 1
    assert "Corolla for Mr A" in admin.get("/estimates").get_data(as_text=True)

    page = admin.get(f"/?estimate={est['id']}").get_data(as_text=True)
    assert 'id="preload"' in page and '"vehicle": "car"' in page


def test_api_post_needs_csrf_header(admin):
    resp = admin.c.post("/api/estimates", json=ESTIMATE)
    assert resp.status_code == 400 and "CSRF" in resp.get_json()["error"]


def test_invalid_estimate_rejected(admin):
    bad = dict(ESTIMATE, total="lots")
    assert admin.api("POST", "/api/estimates", bad).status_code == 400
    assert admin.api("POST", "/api/estimates", dict(ESTIMATE, lines=[])).status_code == 400


def test_estimates_are_private_to_each_user(make_browser, admin):
    est_id = admin.api("POST", "/api/estimates", ESTIMATE).get_json()["estimate"]["id"]

    other = make_browser()
    other.post("/signup", {"username": "zara", "password": "zarapass1", "confirm": "zarapass1"})
    assert other.api("GET", "/api/estimates").get_json()["estimates"] == []
    assert other.get(f"/?estimate={est_id}").status_code == 404
    assert other.api("DELETE", f"/api/estimates/{est_id}").status_code == 404
    assert other.post(f"/estimates/{est_id}/delete").status_code == 404

    assert len(admin.api("GET", "/api/estimates").get_json()["estimates"]) == 1


def test_delete_own_estimate(admin):
    est_id = admin.api("POST", "/api/estimates", ESTIMATE).get_json()["estimate"]["id"]
    assert admin.post(f"/estimates/{est_id}/delete").status_code == 302
    assert admin.api("GET", "/api/estimates").get_json()["estimates"] == []


def test_deleting_user_removes_their_estimates(app, make_browser, admin):
    staff = make_browser()
    staff.post("/signup", {"username": "omar", "password": "omarpass1", "confirm": "omarpass1"})
    staff.api("POST", "/api/estimates", ESTIMATE)
    uid = staff.api("GET", "/api/me").get_json()["id"]

    admin.post(f"/admin/users/{uid}/delete")
    with app.app_context():
        db = get_db()
        assert db.execute("SELECT COUNT(*) AS n FROM users WHERE id = %s", (uid,)).fetchone()["n"] == 0
        assert db.execute("SELECT COUNT(*) AS n FROM estimates WHERE user_id = %s", (uid,)).fetchone()["n"] == 0
