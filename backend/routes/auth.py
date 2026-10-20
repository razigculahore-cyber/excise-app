"""First-run setup, sign in, sign up, sign out and change password."""
from flask import (Blueprint, current_app, flash, g, redirect, render_template,
                   request, session, url_for)

from ..security import client_ip, login_required, safe_next
from ..services import audit, users

bp = Blueprint("auth", __name__)


def _start_session(uid: int) -> None:
    session.clear()
    session.permanent = True
    session["user_id"] = uid


def _signed_in() -> bool:
    uid = session.get("user_id")
    return uid is not None and users.get_active(uid) is not None


@bp.route("/setup", methods=["GET", "POST"])
def setup():
    """First run only: create the admin account."""
    if users.count() > 0:
        return redirect(url_for("auth.login"))
    form = {"username": "", "full_name": ""}
    if request.method == "POST":
        form = {k: request.form.get(k, "").strip() for k in form}
        pw = request.form.get("password", "")
        problem = (users.username_problem(form["username"])
                   or users.password_problem(pw, request.form.get("confirm", "")))
        if problem:
            flash(problem, "error")
        else:
            uid = users.create(form["username"], form["full_name"], pw, is_admin=True)
            audit.log("setup", users.get(uid), ip=client_ip())
            flash("Admin account created. Sign in to continue.", "ok")
            return redirect(url_for("auth.login"))
    return render_template("auth/setup.html", form=form)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if users.count() == 0:
        return redirect(url_for("auth.setup"))
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
        if user and user["is_active"] and users.verify(user, pw):
            users.clear_failures(username, ip)
            users.touch_login(user["id"])
            audit.log("login", user, ip=ip)
            _start_session(user["id"])
            return redirect(safe_next(request.args.get("next")))

        users.record_failure(username, ip)
        audit.log("login_failed", username=username, ip=ip)
        if user and not user["is_active"] and users.verify(user, pw):
            flash("This account is disabled. Ask the admin to enable it.", "error")
        else:
            flash("Wrong username or password.", "error")
        return render_template("auth/login.html", username=username), 401

    return render_template("auth/login.html", username=username)


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    if users.count() == 0:
        return redirect(url_for("auth.setup"))
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
            uid = users.create(form["username"], form["full_name"], pw)
        except users.UsernameTaken:
            flash("That username is already taken.", "error")
            return render_template("auth/signup.html", form=form), 409
        user = users.get(uid)
        users.touch_login(uid)
        audit.log("signup", user, ip=client_ip())
        _start_session(uid)
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
                users.set_password(g.user["id"], pw)
                audit.log("password_changed", g.user, ip=client_ip())
                flash("Password changed.", "ok")
                return redirect(url_for("auth.account"))
    return render_template("auth/account.html")
