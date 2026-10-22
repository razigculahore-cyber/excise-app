"""The Super Admin sees everyone's estimates and activity, read-only; nobody else does."""
from conftest import ESTIMATE, uid_of


def save(browser, title: str) -> int:
    resp = browser.api("POST", "/api/estimates", dict(ESTIMATE, title=title))
    assert resp.status_code == 201
    return resp.get_json()["estimate"]["id"]


def test_super_admin_sees_all_estimates_with_owners(make_user, boss):
    ali, zara = make_user("ali"), make_user("zara")
    save(ali, "Ali's Corolla")
    save(zara, "Zara's Civic")
    page = boss.get("/admin/estimates").get_data(as_text=True)
    assert "Ali&#39;s Corolla" in page and "Zara&#39;s Civic" in page and "zara" in page


def test_super_admin_filters_estimates_by_user(app, make_user, boss):
    ali, zara = make_user("ali"), make_user("zara")
    save(ali, "Ali one")
    save(zara, "Zara one")
    page = boss.get(f"/admin/estimates?user={uid_of(app, 'ali')}").get_data(as_text=True)
    assert "Ali one" in page and "Zara one" not in page
    assert boss.get("/admin/estimates?user=99999").status_code == 404


def test_super_admin_views_one_estimate_in_detail(make_user, boss):
    est_id = save(make_user("ali"), "Detail check")
    page = boss.get(f"/admin/estimates/{est_id}").get_data(as_text=True)
    assert "Detail check" in page and "Registration fee" in page and "ali" in page
    assert boss.get("/admin/estimates/99999").status_code == 404


def test_super_admin_cannot_delete_other_users_estimates(make_user, boss):
    ali = make_user("ali")
    est_id = save(ali, "Keep me")
    assert boss.post(f"/estimates/{est_id}/delete").status_code == 404
    assert boss.api("DELETE", f"/api/estimates/{est_id}").status_code == 404
    assert boss.post(f"/admin/estimates/{est_id}/delete").status_code in (404, 405)
    assert len(ali.api("GET", "/api/estimates").get_json()["estimates"]) == 1


def test_super_admin_keeps_own_private_estimates(make_user, boss):
    save(boss, "Boss's own")
    save(make_user("ali"), "Ali's")
    mine = boss.api("GET", "/api/estimates").get_json()["estimates"]
    assert [e["title"] for e in mine] == ["Boss's own"]


def test_user_profile_shows_estimates_and_sign_in_history(app, make_user, make_browser, boss):
    ali = make_user("ali")
    save(ali, "Profile estimate")
    make_browser().login("ali", "wrong-one")                           # a failed sign-in under ali's name
    page = boss.get(f"/admin/users/{uid_of(app, 'ali')}").get_data(as_text=True)
    assert "Profile estimate" in page and "Signed in" in page and "Failed sign-in" in page


def test_activity_filter_by_user_and_sign_ins(app, make_user, boss):
    make_user("ali")
    boss.post(f"/admin/users/{uid_of(app, 'ali')}/promote")
    page = boss.get(f"/admin/activity?user={uid_of(app, 'ali')}").get_data(as_text=True)
    assert "ali" in page and "Made a user admin" not in page          # that row belongs to boss
    page = boss.get("/admin/activity?only=signins").get_data(as_text=True)
    assert "Signed in" in page and "Made a user admin" not in page
    assert "Made a user admin" in boss.get("/admin/activity").get_data(as_text=True)


def test_nobody_else_sees_other_users_estimates(make_user, boss):
    ali = make_user("ali")
    est_id = save(ali, "Private")
    for intruder in (make_user("zara"), make_user("adam", role="admin")):
        assert intruder.get(f"/?estimate={est_id}").status_code == 404
        assert intruder.get(f"/admin/estimates/{est_id}").status_code == 403
        assert intruder.api("DELETE", f"/api/estimates/{est_id}").status_code == 404
        assert "Private" not in intruder.get("/estimates").get_data(as_text=True)
        assert intruder.api("GET", "/api/estimates").get_json()["estimates"] == []


def test_nav_shows_only_allowed_links(make_user, boss):
    assert "All estimates" in boss.get("/").get_data(as_text=True)
    admin_page = make_user("adam", role="admin").get("/").get_data(as_text=True)
    assert "Users" in admin_page and "All estimates" not in admin_page and "Activity" not in admin_page
    user_page = make_user("ali").get("/").get_data(as_text=True)
    assert ">Users<" not in user_page and ">User<" in user_page        # role label renamed from Staff
