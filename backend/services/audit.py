"""Activity log of sign-ins and account changes, shown to the Super Admin."""
from ..db import get_db

EVENT_LABELS = {
    "login": "Signed in",
    "login_failed": "Failed sign-in",
    "login_locked": "Sign-in blocked (too many attempts)",
    "logout": "Signed out",
    "signup": "Created own account",
    "setup": "Created Super Admin",
    "password_changed": "Changed own password",
    "user_added": "Added user",
    "user_disabled": "Disabled user",
    "user_enabled": "Enabled user",
    "user_deleted": "Deleted user",
    "password_reset": "Reset a user's password",
    "role_granted": "Made a user admin",
    "role_revoked": "Removed admin rights",
}
SIGN_IN_EVENTS = ("login", "login_failed", "login_locked", "logout", "signup")


def log(event: str, user=None, username: str = "", detail: str = "", ip: str = "") -> None:
    get_db().execute(
        "INSERT INTO audit_log (user_id, username, event, detail, ip) VALUES (%s, %s, %s, %s, %s)",
        (user["id"] if user else None, user["username"] if user else username, event, detail[:200], ip))


def recent(limit: int = 200, user=None, sign_ins_only: bool = False):
    """Newest first. With `user`, only that account's rows, including failed sign-ins under its name."""
    sql = "SELECT * FROM audit_log"
    where, params = [], []
    if user is not None:
        where.append("(user_id = %s OR (user_id IS NULL AND lower(username) = lower(%s)))")
        params += [user["id"], user["username"]]
    if sign_ins_only:
        where.append("event = ANY(%s)")
        params.append(list(SIGN_IN_EVENTS))
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT %s"
    return get_db().execute(sql, (*params, limit)).fetchall()
