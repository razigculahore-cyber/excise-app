"""Admin console: manage user accounts; the Super Admin also sees activity and everyone's estimates.

Every action is checked with permissions.can() here on the server; the templates only use it to
decide which buttons to show.
"""
from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for

from ..permissions import ADMIN, ROLE_LABELS, USER, can
from ..security import admin_required, client_ip, superadmin_required
from ..services import audit, estimates, users

bp = Blueprint("admin", __name__, url_prefix="/admin")

ACTIONS = ("disable", "enable", "delete", "reset", "promote", "revoke")


@bp.route("/users")
@admin_required
def user_list():
    return render_template("admin/users.html", users=users.list_all(),
                           min_len=current_app.config["MIN_PASSWORD_LENGTH"])


@bp.route("/users/add", methods=["POST"])
@admin_required
def add_user():
    username = request.form.get("username", "").strip()
    full_name = request.form.get("full_name", "").strip()
    pw = request.form.get("password", "")
    role = ADMIN if request.form.get("is_admin") == "on" else USER
    if role == ADMIN and not can(g.user, "add_admin"):
        abort(403)
    problem = users.username_problem(username) or users.password_problem(pw)
    if problem:
        flash(problem, "error")
        return redirect(url_for("admin.user_list"))
    try:
        users.create(username, full_name, pw, role=role)
    except users.UsernameTaken:
        flash(f"The username {username} is already taken.", "error")
        return redirect(url_for("admin.user_list"))
    audit.log("user_added", g.user, detail=f"{username} ({role})", ip=client_ip())
    flash(f"Added {username}. Give them their password in person.", "ok")
    return redirect(url_for("admin.user_list"))


@bp.route("/users/<int:uid>/<action>", methods=["POST"])
@admin_required
def user_action(uid: int, action: str):
    target = users.get(uid)
    if target is None or action not in ACTIONS:
        abort(404)
    name = target["username"]
    ip = client_ip()

    if action in ("disable", "delete") and uid == g.user["id"]:
        flash("You can't disable or delete your own account.", "error")
        return redirect(url_for("admin.user_list"))
    if not can(g.user, action, target):
        abort(403)

    try:
        if action == "disable":
            users.set_active(uid, False)
            audit.log("user_disabled", g.user, detail=name, ip=ip)
            flash(f"{name} can no longer sign in.", "ok")
        elif action == "enable":
            users.set_active(uid, True)
            users.clear_failures(name)
            audit.log("user_enabled", g.user, detail=name, ip=ip)
            flash(f"{name} can sign in again.", "ok")
        elif action == "delete":
            users.delete(uid)
            audit.log("user_deleted", g.user, detail=name, ip=ip)
            flash(f"Deleted {name} and their saved estimates.", "ok")
        elif action == "promote":
            users.set_role(uid, ADMIN)
            audit.log("role_granted", g.user, detail=name, ip=ip)
            flash(f"{name} is now an admin.", "ok")
        elif action == "revoke":
            users.set_role(uid, USER)
            audit.log("role_revoked", g.user, detail=name, ip=ip)
            flash(f"{name} is no longer an admin.", "ok")
        elif action == "reset":
            pw = request.form.get("password", "")
            problem = users.password_problem(pw)
            if problem:
                flash(problem, "error")
            else:
                users.set_password(uid, pw)
                users.clear_failures(name)
                audit.log("password_reset", g.user, detail=name, ip=ip)
                flash(f"New password set for {name}. They've been signed out everywhere.", "ok")
    except users.ProtectedAccount:
        abort(403)
    # The Super Admin's profile page posts back=profile so it returns there
    if request.form.get("back") == "profile" and action != "delete":
        return redirect(url_for("admin.user_detail", uid=uid))
    return redirect(url_for("admin.user_list"))


# ------------------------------------------------------------------ Super Admin only

@bp.route("/users/<int:uid>")
@superadmin_required
def user_detail(uid: int):
    target = users.get(uid)
    if target is None:
        abort(404)
    return render_template("admin/user.html", target=target, role_labels=ROLE_LABELS,
                           estimates=estimates.list_all(user_id=uid, limit=200),
                           rows=audit.recent(limit=100, user=target), labels=audit.EVENT_LABELS,
                           min_len=current_app.config["MIN_PASSWORD_LENGTH"])


@bp.route("/estimates")
@superadmin_required
def all_estimates():
    owner = None
    uid = request.args.get("user", type=int)
    if uid is not None:
        owner = users.get(uid)
        if owner is None:
            abort(404)
    return render_template("admin/estimates.html", estimates=estimates.list_all(user_id=uid),
                           owner=owner, total=estimates.total_count(), people=users.list_all())


@bp.route("/estimates/<int:estimate_id>")
@superadmin_required
def estimate_detail(estimate_id: int):
    est = estimates.get_any(estimate_id)
    if est is None:
        abort(404)
    return render_template("admin/estimate.html", e=est)


@bp.route("/activity")
@superadmin_required
def activity():
    person = None
    uid = request.args.get("user", type=int)
    if uid is not None:
        person = users.get(uid)
        if person is None:
            abort(404)
    sign_ins = request.args.get("only") == "signins"
    return render_template("admin/activity.html", rows=audit.recent(user=person, sign_ins_only=sign_ins),
                           labels=audit.EVENT_LABELS, people=users.list_all(), person=person, sign_ins=sign_ins)
