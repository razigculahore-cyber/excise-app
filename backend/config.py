"""Settings, read once from the environment when the app starts."""
import os
import secrets
from datetime import timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
# Served at /static/... by Flask locally and by Vercel's CDN in production (Vercel serves public/ directly)
STATIC_DIR = os.path.join(BASE_DIR, "public", "static")

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


def app_env() -> str:
    """'production' on Vercel (it sets VERCEL=1) unless APP_ENV says otherwise; else 'development'."""
    return os.environ.get("APP_ENV") or ("production" if os.environ.get("VERCEL") else "development")


def build_config(instance_dir: str = INSTANCE_DIR) -> dict:
    production = app_env() == "production"
    secret = os.environ.get("SECRET_KEY", "")
    if production and len(secret) < 32:
        # Vercel's disk is read-only and per-instance, so the key must come from the environment
        raise RuntimeError("SECRET_KEY must be set (at least 32 characters) when APP_ENV=production.")
    secure = _flag("HTTPS", production)
    return {
        "APP_ENV": "production" if production else "development",
        "SECRET_KEY": secret or load_secret_key(instance_dir),
        # PostgreSQL connection string (Neon). Never hard-code it; set it in .env or on Vercel.
        "DATABASE_URL": os.environ.get("DATABASE_URL", ""),
        # Optional direct (non-pooled) connection for `flask init-db` and migrations
        "DATABASE_URL_UNPOOLED": os.environ.get("DATABASE_URL_UNPOOLED", ""),
        # Times are stored in UTC and shown in this zone
        "APP_TIMEZONE": os.environ.get("APP_TIMEZONE", "Asia/Karachi"),
        # Trust X-Forwarded-For/-Proto from one proxy (Vercel) so client IPs and https are seen correctly
        "TRUST_PROXY": _flag("TRUST_PROXY", production),
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        # HTTPS=1 (the default in production): cookie only sent over https, and HSTS is switched on
        "SESSION_COOKIE_SECURE": secure,
        # The __Host- prefix makes browsers refuse the cookie unless it is Secure and for this site only
        "SESSION_COOKIE_NAME": "__Host-session" if secure else "session",
        "PERMANENT_SESSION_LIFETIME": timedelta(hours=8),
        "MAX_CONTENT_LENGTH": 256 * 1024,  # no request needs more; stops oversized posts early
        # Set ALLOW_SIGNUP=0 so only an admin can create accounts
        "ALLOW_SIGNUP": _flag("ALLOW_SIGNUP", True),
        "MIN_PASSWORD_LENGTH": 8,
        "MAX_FAILED_ATTEMPTS": 5,          # wrong passwords allowed...
        "LOCKOUT_SECONDS": 15 * 60,        # ...within this window before the account is locked
        "MAX_SAVED_ESTIMATES": 500,        # per user
    }
