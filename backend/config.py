"""Settings, read once from the environment when the app starts."""
import os
import secrets
from datetime import timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

try:
    # On your computer, settings such as DATABASE_URL come from .env (never committed).
    # python-dotenv is a dev-only package; on Vercel the variables are set in the dashboard.
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, ".env"))
except ImportError:
    pass


def _flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def load_secret_key(instance_dir: str) -> str:
    """Create a random secret key once and keep it, so logins survive restarts."""
    os.makedirs(instance_dir, exist_ok=True)
    path = os.path.join(instance_dir, "secret_key")
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(secrets.token_hex(32))
    with open(path) as f:
        return f.read().strip()


def build_config(instance_dir: str = INSTANCE_DIR) -> dict:
    return {
        "SECRET_KEY": os.environ.get("SECRET_KEY") or load_secret_key(instance_dir),
        # PostgreSQL connection string (Neon). Never hard-code it; set it in .env or on Vercel.
        "DATABASE_URL": os.environ.get("DATABASE_URL", ""),
        # Times are stored in UTC and shown in this zone
        "APP_TIMEZONE": os.environ.get("APP_TIMEZONE", "Asia/Karachi"),
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        # Set HTTPS=1 when the app is served over https (e.g. online hosting)
        "SESSION_COOKIE_SECURE": _flag("HTTPS", False),
        "PERMANENT_SESSION_LIFETIME": timedelta(hours=8),
        # Set ALLOW_SIGNUP=0 so only an admin can create accounts
        "ALLOW_SIGNUP": _flag("ALLOW_SIGNUP", True),
        "MIN_PASSWORD_LENGTH": 8,
        "MAX_FAILED_ATTEMPTS": 5,          # wrong passwords allowed...
        "LOCKOUT_SECONDS": 15 * 60,        # ...within this window before the account is locked
        "MAX_SAVED_ESTIMATES": 500,        # per user
    }
