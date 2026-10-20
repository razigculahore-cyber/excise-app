"""User accounts, passwords and the failed-login lockout."""
import time

from flask import current_app
from psycopg.errors import UniqueViolation
from werkzeug.security import check_password_hash, generate_password_hash

from ..db import get_db


class UsernameTaken(Exception):
    pass


def count() -> int:
    return get_db().execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]


def get(uid: int):
    return get_db().execute("SELECT * FROM users WHERE id = %s", (uid,)).fetchone()


def get_active(uid: int):
    return get_db().execute("SELECT * FROM users WHERE id = %s AND is_active", (uid,)).fetchone()


def get_by_username(username: str):
    return get_db().execute(
        "SELECT * FROM users WHERE lower(username) = lower(%s)", (username,)).fetchone()


def list_all():
    return get_db().execute("""
        SELECT *, (SELECT COUNT(*) FROM estimates e WHERE e.user_id = users.id) AS estimate_count
        FROM users ORDER BY is_admin DESC, lower(username)""").fetchall()


def password_problem(pw: str, confirm: str | None = None) -> str | None:
    """Return a message explaining what's wrong with a new password, or None if it's fine."""
    min_len = current_app.config["MIN_PASSWORD_LENGTH"]
    if len(pw) < min_len:
        return f"Password must be at least {min_len} characters."
    if confirm is not None and pw != confirm:
        return "The two passwords don't match."
    return None


def username_problem(username: str) -> str | None:
    if not username:
        return "Enter a username."
    if len(username) > 40 or any(c.isspace() for c in username):
        return "Usernames can't contain spaces and must be 40 characters or fewer."
    return None


def create(username: str, full_name: str, password: str, is_admin: bool = False) -> int:
    try:
        row = get_db().execute(
            "INSERT INTO users (username, full_name, password_hash, is_admin) VALUES (%s, %s, %s, %s) RETURNING id",
            (username, full_name, generate_password_hash(password), is_admin)).fetchone()
    except UniqueViolation:
        raise UsernameTaken(username) from None
    return row["id"]


def verify(user, password: str) -> bool:
    return bool(user) and check_password_hash(user["password_hash"], password)


def set_password(uid: int, password: str) -> None:
    get_db().execute("UPDATE users SET password_hash = %s WHERE id = %s", (generate_password_hash(password), uid))


def set_active(uid: int, active: bool) -> None:
    get_db().execute("UPDATE users SET is_active = %s WHERE id = %s", (active, uid))


def delete(uid: int) -> None:
    get_db().execute("DELETE FROM users WHERE id = %s", (uid,))


def touch_login(uid: int) -> None:
    get_db().execute("UPDATE users SET last_login = now() WHERE id = %s", (uid,))


def other_active_admins(uid: int) -> int:
    return get_db().execute(
        "SELECT COUNT(*) AS n FROM users WHERE is_admin AND is_active AND id != %s", (uid,)).fetchone()["n"]


# ------------------------------------------------------------------ lockout

def recent_failures(username: str, ip: str) -> int:
    cutoff = time.time() - current_app.config["LOCKOUT_SECONDS"]
    db = get_db()
    db.execute("DELETE FROM failed_logins WHERE at < %s", (cutoff,))
    return db.execute(
        "SELECT COUNT(*) AS n FROM failed_logins WHERE lower(username) = lower(%s) AND ip = %s",
        (username, ip)).fetchone()["n"]


def record_failure(username: str, ip: str) -> None:
    get_db().execute("INSERT INTO failed_logins (username, ip, at) VALUES (%s, %s, %s)", (username, ip, time.time()))


def clear_failures(username: str, ip: str | None = None) -> None:
    db = get_db()
    if ip is None:
        db.execute("DELETE FROM failed_logins WHERE lower(username) = lower(%s)", (username,))
    else:
        db.execute("DELETE FROM failed_logins WHERE lower(username) = lower(%s) AND ip = %s", (username, ip))
