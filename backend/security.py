"""CSRF protection, security headers and the login/admin guards."""
import secrets
from functools import wraps

from flask import abort, g, jsonify, redirect, request, session, url_for

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
    return resp


def client_ip() -> str:
    return request.remote_addr or "?"


def safe_next(target: str | None) -> str:
    # Only allow redirects back into this site
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return url_for("main.calculator")


def _load_user():
    uid = session.get("user_id")
    return users.get_active(uid) if uid is not None else None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if users.count() == 0:
            return redirect(url_for("auth.setup"))
        user = _load_user()
        if user is None:
            session.clear()
            return redirect(url_for("auth.login", next=request.path))
        g.user = user
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not g.user["is_admin"]:
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
