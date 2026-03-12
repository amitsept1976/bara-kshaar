import os
from dotenv import load_dotenv

# read a .env file if present so that environment variables can be defined there
load_dotenv()

class Config:
    # prefer DATABASE_URL from environment (e.g. for Heroku).  fallback to local postgres
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "postgresql://username:password@localhost:5432/remedies_db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # a real deployment should override this via an env var or .env file
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
