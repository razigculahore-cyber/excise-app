"""Admin console: manage user accounts and review activity."""
from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for

from ..security import admin_required, client_ip
from ..services import audit, users

bp = Blueprint("admin", __name__, url_prefix="/admin")


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
    is_admin = request.form.get("is_admin") == "on"
    problem = users.username_problem(username) or users.password_problem(pw)
    if problem:
        flash(problem, "error")
        return redirect(url_for("admin.user_list"))
    try:
        users.create(username, full_name, pw, is_admin=is_admin)
    except users.UsernameTaken:
        flash(f"The username {username} is already taken.", "error")
        return redirect(url_for("admin.user_list"))
    audit.log("user_added", g.user, detail=f"{username} ({'admin' if is_admin else 'staff'})", ip=client_ip())
    flash(f"Added {username}. Give them their password in person.", "ok")
    return redirect(url_for("admin.user_list"))


@bp.route("/users/<int:uid>/<action>", methods=["POST"])
@admin_required
def user_action(uid: int, action: str):
    # Serialize account removals so concurrent requests cannot remove the last admins.
    from ..db import get_db
    db = get_db()
    if getattr(db, "postgres", False):
        db.execute("LOCK TABLE users IN EXCLUSIVE MODE")
    target = users.get(uid)
    if target is None or action not in ("disable", "enable", "delete", "reset"):
        abort(404)
    name = target["username"]
    ip = client_ip()

    if action in ("disable", "delete") and uid == g.user["id"]:
        flash("You can't disable or delete your own account.", "error")
    elif action in ("disable", "delete") and target["is_admin"] and users.other_active_admins(uid) == 0:
        flash("Keep at least one active admin.", "error")
    elif action == "disable":
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
    elif action == "reset":
        pw = request.form.get("password", "")
        problem = users.password_problem(pw)
        if problem:
            flash(problem, "error")
        else:
            users.set_password(uid, pw)
            users.clear_failures(name)
            audit.log("password_reset", g.user, detail=name, ip=ip)
            flash(f"New password set for {name}.", "ok")
    return redirect(url_for("admin.user_list"))


@bp.route("/activity")
@admin_required
def activity():
    return render_template("admin/activity.html", rows=audit.recent(), labels=audit.EVENT_LABELS)
