"""CSRF protection, security headers and the login / admin / Super Admin guards."""
import secrets
from functools import wraps

from flask import abort, current_app, g, jsonify, redirect, request, session, url_for

from .permissions import is_admin, is_superadmin
from .services import users

# Fonts come from Google; everything else is served by this app. No inline scripts.
CSP = ("default-src 'self'; "
       "style-src 'self' https://fonts.googleapis.com; "
       "font-src https://fonts.gstatic.com; "
       "img-src 'self' data:; "
       "frame-ancestors 'none'; base-uri 'self'; form-action 'self'")


def csrf_token() -> str:
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


def check_csrf():
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        sent = request.form.get("csrf") or request.headers.get("X-CSRF-Token", "")
        if not sent or not secrets.compare_digest(sent, session.get("csrf", "")):
            if request.path.startswith("/api/"):
                return jsonify(error="CSRF token missing or expired. Refresh the page."), 400
            abort(400, "Form expired. Go back, refresh the page and try again.")
    return None


def security_headers(resp):
    # Stop the browser showing protected pages from cache after logout
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "same-origin"
    resp.headers["Content-Security-Policy"] = CSP
    if current_app.config["SESSION_COOKIE_SECURE"]:
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return resp


def client_ip() -> str:
    # Behind Vercel, ProxyFix (TRUST_PROXY=1) has already put the visitor's address here
    return request.remote_addr or "?"


def start_session(user) -> None:
    """Sign `user` in on this browser. Remembers the account's session version (see _load_user)."""
    session.clear()
    session.permanent = True
    session["user_id"] = user["id"]
    session["ver"] = user["session_version"]


def safe_next(target: str | None) -> str:
    # Only allow redirects back into this site
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return url_for("main.calculator")


def _load_user():
    """The signed-in, active user, or None. A password, role or status change since sign-in
    bumps the account's session_version, which signs out every older session."""
    uid = session.get("user_id")
    if uid is None:
        return None
    user = users.get_active(uid)
    if user is None or user["session_version"] != session.get("ver"):
        return None
    return user


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = _load_user()
        if user is None:
            session.clear()
            return redirect(url_for("auth.login", next=request.path))
        g.user = user
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    """Admins and the Super Admin."""
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not is_admin(g.user):
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def superadmin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not is_superadmin(g.user):
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def api_login_required(view):
    """Like login_required, but answers with JSON 401 instead of redirecting."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = _load_user()
        if user is None:
            return jsonify(error="Not signed in."), 401
        g.user = user
        return view(*args, **kwargs)
    return wrapped
