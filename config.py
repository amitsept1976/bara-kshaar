import os
from dotenv import load_dotenv

# read a .env file if present so that environment variables can be defined there
load_dotenv()


def _normalize_database_url(url: str) -> str:
    """Normalize provider URLs (e.g., Render/Heroku) for SQLAlchemy."""
    if not url:
        return url

    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)

    return url

class Config:
    # prefer DATABASE_URL from environment (e.g. for Heroku).  fallback to local postgres
    SQLALCHEMY_DATABASE_URI = _normalize_database_url(os.getenv(
        "DATABASE_URL",
        "postgresql://username:password@localhost:5432/remedies_db"
    ))
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # a real deployment should override this via an env var or .env file
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
