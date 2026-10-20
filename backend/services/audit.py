"""Activity log of sign-ins and account changes, shown to admins."""
from ..db import get_db

EVENT_LABELS = {
    "login": "Signed in",
    "login_failed": "Failed sign-in",
    "login_locked": "Sign-in blocked (too many attempts)",
    "logout": "Signed out",
    "signup": "Created own account",
    "setup": "Created first admin",
    "password_changed": "Changed own password",
    "user_added": "Added user",
    "user_disabled": "Disabled user",
    "user_enabled": "Enabled user",
    "user_deleted": "Deleted user",
    "password_reset": "Reset a user's password",
}


def log(event: str, user=None, username: str = "", detail: str = "", ip: str = "") -> None:
    db = get_db()
    db.execute(
        "INSERT INTO audit_log (user_id, username, event, detail, ip) VALUES (?, ?, ?, ?, ?)",
        (user["id"] if user else None, user["username"] if user else username, event, detail[:200], ip))
    db.commit()


def recent(limit: int = 200):
    return get_db().execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
