"""User accounts, roles, passwords and the failed-login lockout."""
import time

from flask import current_app
from psycopg.errors import InsufficientPrivilege, UniqueViolation
from werkzeug.security import check_password_hash, generate_password_hash

from ..db import get_db
from ..permissions import ADMIN, SUPERADMIN, USER

# Checked when the username doesn't exist, so a wrong username takes as long as a wrong password
_DUMMY_HASH = generate_password_hash("not-a-real-password")


class UsernameTaken(Exception):
    pass


class SuperAdminExists(Exception):
    pass


class ProtectedAccount(Exception):
    """The database refused to delete or demote the Super Admin."""


def count() -> int:
    return get_db().execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]


def get(uid: int):
    return get_db().execute("SELECT * FROM users WHERE id = %s", (uid,)).fetchone()


def get_active(uid: int):
    return get_db().execute("SELECT * FROM users WHERE id = %s AND is_active", (uid,)).fetchone()


def get_by_username(username: str):
    return get_db().execute(
        "SELECT * FROM users WHERE lower(username) = lower(%s)", (username,)).fetchone()


def superadmin():
    return get_db().execute("SELECT * FROM users WHERE role = %s", (SUPERADMIN,)).fetchone()


def list_all():
    return get_db().execute("""
        SELECT *, (SELECT COUNT(*) FROM estimates e WHERE e.user_id = users.id) AS estimate_count
        FROM users
        ORDER BY CASE role WHEN 'superadmin' THEN 0 WHEN 'admin' THEN 1 ELSE 2 END, lower(username)""").fetchall()


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


def _insert(username: str, full_name: str, password: str, role: str) -> int:
    try:
        row = get_db().execute(
            "INSERT INTO users (username, full_name, password_hash, role) VALUES (%s, %s, %s, %s) RETURNING id",
            (username, full_name, generate_password_hash(password), role)).fetchone()
    except UniqueViolation as e:
        if e.diag.constraint_name == "users_one_superadmin":
            raise SuperAdminExists() from None
        raise UsernameTaken(username) from None
    return row["id"]


def create(username: str, full_name: str, password: str, role: str = USER) -> int:
    """Create a normal user or an admin. A Super Admin can only come from create_superadmin()."""
    if role not in (USER, ADMIN):
        raise ValueError(f"create() can't make a {role!r} account")
    return _insert(username, full_name, password, role)


def create_superadmin(username: str, full_name: str, password: str) -> int:
    """Create the one Super Admin (terminal only). Fails if one already exists, even under a race."""
    if superadmin() is not None:
        raise SuperAdminExists()
    return _insert(username, full_name, password, SUPERADMIN)


def verify(user, password: str) -> bool:
    if not user:
        check_password_hash(_DUMMY_HASH, password)
        return False
    return check_password_hash(user["password_hash"], password)


def set_password(uid: int, password: str) -> int:
    """Set a new password and sign out every session of that account. Returns the new session version."""
    return get_db().execute(
        "UPDATE users SET password_hash = %s, session_version = session_version + 1 WHERE id = %s"
        " RETURNING session_version", (generate_password_hash(password), uid)).fetchone()["session_version"]


def set_active(uid: int, active: bool) -> None:
    get_db().execute(
        "UPDATE users SET is_active = %s, session_version = session_version + 1 WHERE id = %s", (active, uid))


def set_role(uid: int, role: str) -> None:
    """Make an account a normal user or an admin. The Super Admin can't be changed this way."""
    if role not in (USER, ADMIN):
        raise ValueError(f"set_role() can't grant {role!r}")
    try:
        get_db().execute(
            "UPDATE users SET role = %s, session_version = session_version + 1 WHERE id = %s", (role, uid))
    except InsufficientPrivilege:
        raise ProtectedAccount() from None


def delete(uid: int) -> None:
    try:
        get_db().execute("DELETE FROM users WHERE id = %s", (uid,))
    except InsufficientPrivilege:
        raise ProtectedAccount() from None


def touch_login(uid: int) -> None:
    get_db().execute("UPDATE users SET last_login = now() WHERE id = %s", (uid,))


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
