import os

from dotenv import load_dotenv

# read a .env file if present so that environment variables can be defined there
load_dotenv()


def _env_bool(name: str, default: bool = False) -> bool:
    """Parse boolean environment variables consistently."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_first(*names: str, default: str = "") -> str:
    """Return the first non-empty environment variable value from a list of names."""
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return default


def _env_int(*names: str, default: int) -> int:
    """Return the first integer environment variable value from a list of names."""
    for name in names:
        value = os.getenv(name)
        if value is None or not value.strip():
            continue
        try:
            return int(value.strip())
        except ValueError:
            continue
    return default


def _normalize_database_url(url: str) -> str:
    """Normalize provider URLs (e.g., Render/Heroku) for SQLAlchemy."""
    if not url:
        return url

    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)

    return url


class Config:
    # Prefer DATABASE_URL from environment (e.g. Heroku/Render), then fallback local.
    SQLALCHEMY_DATABASE_URI = _normalize_database_url(
        os.getenv(
            "DATABASE_URL",
            "postgresql://username:password@localhost:5432/remedies_db",
        )
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # pool_pre_ping re-tests connections before use, preventing OperationalError on
    # Render/Heroku when the app wakes from sleep and the pool has stale connections.
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }

    # a real deployment should override this via an env var or .env file
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")

    # SMTP email configuration
    MAIL_SERVER = _env_first("MAIL_SERVER", "SMTP_SERVER", "EMAIL_HOST")
    MAIL_PORT = _env_int("MAIL_PORT", "SMTP_PORT", "EMAIL_PORT", default=587)
    MAIL_USERNAME = _env_first(
        "MAIL_USERNAME",
        "SMTP_USERNAME",
        "SMTP_USER",
        "EMAIL_HOST_USER",
        "EMAIL_USER",
    )
    MAIL_PASSWORD = _env_first(
        "MAIL_PASSWORD",
        "SMTP_PASSWORD",
        "SMTP_PASS",
        "EMAIL_HOST_PASSWORD",
        "EMAIL_PASSWORD",
    )
    MAIL_USE_TLS = _env_bool("MAIL_USE_TLS", default=_env_bool("EMAIL_USE_TLS", default=True))
    MAIL_USE_SSL = _env_bool("MAIL_USE_SSL", default=_env_bool("EMAIL_USE_SSL", default=False))
    MAIL_FROM = _env_first(
        "MAIL_FROM",
        "SMTP_FROM",
        "EMAIL_FROM",
        "FROM_EMAIL",
        "DEFAULT_FROM_EMAIL",
        default=MAIL_USERNAME,
    )

    # Admin notifications
    ADMIN_EMAIL = _env_first("ADMIN_EMAIL", "ALERT_EMAIL")
    ADMIN_API_TOKEN = _env_first("ADMIN_API_TOKEN")
