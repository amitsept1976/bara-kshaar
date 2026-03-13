from flask import Flask, render_template, request
from sqlalchemy import or_

from config import Config
from models import db, Remedy
from seeds import REMEDY_SEEDS


def create_app() -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__, static_folder="static")
    app.config.from_object(Config)
    db.init_app(app)

    # Initialize database tables and seed data on app startup
    with app.app_context():
        db.create_all()
        _seed_database_if_empty()

    # Register CLI commands
    _register_cli_commands(app)

    # Register routes
    _register_routes(app)

    return app


def _register_cli_commands(app: Flask) -> None:
    """Register Flask CLI commands."""
    @app.cli.command("init-db")
    def init_db():
        """Create database tables and seed initial data if necessary."""
        db.create_all()
        _seed_database_if_empty()
        print("Database initialized")


def _seed_database_if_empty() -> None:
    """Seed the database with initial remedy data if empty."""
    if Remedy.query.first():
        return

    for name, full_name in REMEDY_SEEDS:
        remedy = Remedy(
            name=name,
            full_name=full_name,
            description=f"Traditional remedy: {full_name}.",
            keywords=f"{name.lower()} {full_name.lower()}"
        )
        db.session.add(remedy)
    db.session.commit()


def _register_routes(app: Flask) -> None:
    """Register application routes."""
    @app.route("/", methods=["GET"])
    def index():
        query = request.args.get("q", "").strip()
        remedies = _search_remedies(query) if query else []
        return render_template("index.html", query=query, remedies=remedies)


def _search_remedies(query: str) -> list[Remedy]:
    """Search for remedies based on the query string."""
    q = f"%{query.lower()}%"
    return Remedy.query.filter(
        or_(
            Remedy.name.ilike(q),
            Remedy.full_name.ilike(q),
            Remedy.description.ilike(q),
            Remedy.keywords.ilike(q),
        )
    ).all()


# Create a global application instance for CLI and WSGI servers
app = create_app()

if __name__ == "__main__":
    # Development server with debug enabled
    app.run(debug=True)