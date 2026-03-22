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
    MAIL_SERVER = os.getenv("MAIL_SERVER", "")
    MAIL_PORT = int(os.getenv("MAIL_PORT", "587"))
    MAIL_USERNAME = os.getenv("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")
    MAIL_USE_TLS = _env_bool("MAIL_USE_TLS", default=True)
    MAIL_USE_SSL = _env_bool("MAIL_USE_SSL", default=False)
    MAIL_FROM = os.getenv("MAIL_FROM", MAIL_USERNAME)

    # Admin notifications
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")
    ADMIN_API_TOKEN = os.getenv("ADMIN_API_TOKEN", "")
