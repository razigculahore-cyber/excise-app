"""User accounts, passwords and the failed-login lockout."""
import sqlite3
import time
from psycopg.errors import UniqueViolation

from flask import current_app
from werkzeug.security import check_password_hash, generate_password_hash

from ..db import get_db, insert_id


class UsernameTaken(Exception):
    pass


def count() -> int:
    return get_db().execute("SELECT COUNT(*) FROM users").fetchone()[0]


def get(uid: int):
    return get_db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()


def get_active(uid: int):
    return get_db().execute("SELECT * FROM users WHERE id = ? AND is_active = 1", (uid,)).fetchone()


def get_by_username(username: str):
    return get_db().execute("SELECT * FROM users WHERE lower(username) = lower(?)", (username,)).fetchone()


def list_all():
    return get_db().execute("""
        SELECT u.*, (SELECT COUNT(*) FROM estimates e WHERE e.user_id = u.id) AS estimate_count
        FROM users u ORDER BY u.is_admin DESC, u.username""").fetchall()


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
    db = get_db()
    try:
        uid = insert_id(db,
            "INSERT INTO users (username, full_name, password_hash, is_admin) VALUES (?, ?, ?, ?)",
            (username, full_name, generate_password_hash(password), int(is_admin)))
        db.commit()
    except (sqlite3.IntegrityError, UniqueViolation):
        db.rollback()
        raise UsernameTaken(username) from None
    return uid


def verify(user, password: str) -> bool:
    return bool(user) and check_password_hash(user["password_hash"], password)


def set_password(uid: int, password: str) -> None:
    db = get_db()
    db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (generate_password_hash(password), uid))
    db.commit()


def set_active(uid: int, active: bool) -> None:
    db = get_db()
    db.execute("UPDATE users SET is_active = ? WHERE id = ?", (int(active), uid))
    db.commit()


def delete(uid: int) -> None:
    db = get_db()
    db.execute("DELETE FROM users WHERE id = ?", (uid,))
    db.commit()


def touch_login(uid: int) -> None:
    db = get_db()
    db.execute("UPDATE users SET last_login = datetime('now', 'localtime') WHERE id = ?", (uid,))
    db.commit()


def other_active_admins(uid: int) -> int:
    return get_db().execute(
        "SELECT COUNT(*) FROM users WHERE is_admin = 1 AND is_active = 1 AND id != ?", (uid,)).fetchone()[0]


# ------------------------------------------------------------------ lockout

def recent_failures(username: str, ip: str) -> int:
    cutoff = time.time() - current_app.config["LOCKOUT_SECONDS"]
    db = get_db()
    db.execute("DELETE FROM failed_logins WHERE at < ?", (cutoff,))
    db.commit()
    return db.execute(
        "SELECT COUNT(*) FROM failed_logins WHERE lower(username) = lower(?) AND ip = ?", (username, ip)).fetchone()[0]


def record_failure(username: str, ip: str) -> None:
    db = get_db()
    db.execute("INSERT INTO failed_logins (username, ip, at) VALUES (?, ?, ?)", (username, ip, time.time()))
    db.commit()


def clear_failures(username: str, ip: str | None = None) -> None:
    db = get_db()
    if ip is None:
        db.execute("DELETE FROM failed_logins WHERE lower(username) = lower(?)", (username,))
    else:
        db.execute("DELETE FROM failed_logins WHERE lower(username) = lower(?) AND ip = ?", (username, ip))
    db.commit()


def create_first_admin(username, full_name, password):
    db = get_db()
    if getattr(db, "postgres", False):
        db.execute("LOCK TABLE users IN EXCLUSIVE MODE")
    else:
        db.execute("BEGIN IMMEDIATE")
    if count():
        db.rollback()
        return None
    return create(username, full_name, password, is_admin=True)
