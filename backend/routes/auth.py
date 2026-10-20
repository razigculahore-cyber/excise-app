"""Sign in, sign up, sign out and change password.

There is no web setup page: the Super Admin is created from the terminal (`flask create-superadmin`)
or by the SQLite migration, so no visitor can make themselves an admin.
"""
from flask import Blueprint, current_app, flash, g, redirect, render_template, request, session, url_for

from ..security import client_ip, login_required, safe_next, start_session
from ..services import audit, users

bp = Blueprint("auth", __name__)


def _signed_in() -> bool:
    uid = session.get("user_id")
    user = users.get_active(uid) if uid is not None else None
    return user is not None and user["session_version"] == session.get("ver")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if _signed_in():
        return redirect(url_for("main.calculator"))

    username = ""
    if request.method == "POST":
        cfg = current_app.config
        username = request.form.get("username", "").strip()
        pw = request.form.get("password", "")
        ip = client_ip()

        if users.recent_failures(username, ip) >= cfg["MAX_FAILED_ATTEMPTS"]:
            audit.log("login_locked", username=username, ip=ip)
            flash(f"Too many wrong attempts. Try again in {cfg['LOCKOUT_SECONDS'] // 60} minutes.", "error")
            return render_template("auth/login.html", username=username), 429

        user = users.get_by_username(username)
        password_ok = users.verify(user, pw)
        if user and user["is_active"] and password_ok:
            users.clear_failures(username, ip)
            users.touch_login(user["id"])
            audit.log("login", user, ip=ip)
            start_session(user)
            return redirect(safe_next(request.args.get("next")))

        users.record_failure(username, ip)
        audit.log("login_failed", username=username, ip=ip)
        if user and not user["is_active"] and password_ok:
            flash("This account is disabled. Ask the admin to enable it.", "error")
        else:
            flash("Wrong username or password.", "error")
        return render_template("auth/login.html", username=username), 401

    return render_template("auth/login.html", username=username)


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    if not current_app.config["ALLOW_SIGNUP"]:
        flash("Sign-up is turned off. Ask the admin to create an account for you.", "error")
        return redirect(url_for("auth.login"))
    if _signed_in():
        return redirect(url_for("main.calculator"))

    form = {"username": "", "full_name": ""}
    if request.method == "POST":
        form = {k: request.form.get(k, "").strip() for k in form}
        pw = request.form.get("password", "")
        problem = (users.username_problem(form["username"])
                   or users.password_problem(pw, request.form.get("confirm", "")))
        if problem:
            flash(problem, "error")
            return render_template("auth/signup.html", form=form), 400
        try:
            # Always a normal user: nothing in the request can choose the role
            uid = users.create(form["username"], form["full_name"], pw)
        except users.UsernameTaken:
            flash("That username is already taken.", "error")
            return render_template("auth/signup.html", form=form), 409
        users.touch_login(uid)
        user = users.get(uid)
        audit.log("signup", user, ip=client_ip())
        start_session(user)
        return redirect(url_for("main.calculator"))

    return render_template("auth/signup.html", form=form)


@bp.route("/logout", methods=["POST"])
def logout():
    uid = session.get("user_id")
    user = users.get(uid) if uid is not None else None
    if user:
        audit.log("logout", user, ip=client_ip())
    session.clear()
    flash("You've been signed out.", "ok")
    return redirect(url_for("auth.login"))


@bp.route("/account", methods=["GET", "POST"])
@login_required
def account():
    if request.method == "POST":
        if not users.verify(g.user, request.form.get("current", "")):
            flash("Your current password is wrong.", "error")
        else:
            pw = request.form.get("password", "")
            problem = users.password_problem(pw, request.form.get("confirm", ""))
            if problem:
                flash(problem, "error")
            else:
                # Signs out the account's other sessions; this browser stays signed in
                session["ver"] = users.set_password(g.user["id"], pw)
                audit.log("password_changed", g.user, ip=client_ip())
                flash("Password changed. Any other devices have been signed out.", "ok")
                return redirect(url_for("auth.account"))
    return render_template("auth/account.html")
