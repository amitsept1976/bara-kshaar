from flask import Flask, flash, redirect, render_template, request, session, url_for
from sqlalchemy import or_
from werkzeug.security import check_password_hash, generate_password_hash

from config import Config
from models import Remedy, User, db
from seeds import REMEDY_SEEDS


def _normalize_prompt(prompt: str) -> str:
    """Collapse extra whitespace in a prompt pulled from seeds."""
    return " ".join(prompt.split())


def _build_search_prompts(
    visible_limit: int = 8,
    suggestion_limit: int = 60,
) -> tuple[list[str], list[str]]:
    """Build user-facing search prompts from the seeded symptom phrases."""
    all_prompts: list[str] = []
    seen: set[str] = set()

    for prompt, _ in REMEDY_SEEDS:
        normalized = _normalize_prompt(prompt)
        if not normalized:
            continue

        key = normalized.casefold()
        if key in seen:
            continue

        seen.add(key)
        all_prompts.append(normalized)

    visible_prompts = [
        prompt
        for prompt in all_prompts
        if prompt[0].isupper()
        and len(prompt) <= 40
        and len(prompt.split()) <= 5
        and not any(char.isdigit() for char in prompt)
        and "(" not in prompt
    ]

    if len(visible_prompts) < visible_limit:
        for prompt in all_prompts:
            if prompt not in visible_prompts:
                visible_prompts.append(prompt)
            if len(visible_prompts) >= visible_limit:
                break

    return visible_prompts[:visible_limit], all_prompts[:suggestion_limit]


SEARCH_PROMPTS, SEARCH_SUGGESTIONS = _build_search_prompts()


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


def _update_database_from_seeds() -> None:
    """Update the database with current seed data, replacing all existing remedies."""
    print(f"Updating database with {len(REMEDY_SEEDS)} remedies from seeds.py...")

    # Clear existing remedies
    Remedy.query.delete()
    db.session.commit()

    # Add new remedies from seeds
    for name, full_name in REMEDY_SEEDS:
        remedy = Remedy(
            name=name,
            full_name=full_name,
            description=f"Traditional remedy: {full_name}.",
            keywords=f"{name.lower()} {full_name.lower()}"
        )
        db.session.add(remedy)

    db.session.commit()
    print(f"Successfully updated database with {len(REMEDY_SEEDS)} remedies")


def _register_cli_commands(app: Flask) -> None:
    """Register Flask CLI commands."""
    @app.cli.command("init-db")
    def init_db():
        """Create database tables and seed initial data if necessary."""
        db.create_all()
        _seed_database_if_empty()
        print("Database initialized")

    @app.cli.command("update-db")
    def update_db():
        """Update database with current seed data, replacing existing remedies."""
        _update_database_from_seeds()


def _register_routes(app: Flask) -> None:
    """Register application routes."""
    @app.route("/", methods=["GET"])
    def index():
        query = request.args.get("q", "").strip()
        remedies = _search_remedies(query) if query else []
        return render_template(
            "index.html",
            query=query,
            remedies=remedies,
            prompt_examples=SEARCH_PROMPTS,
            prompt_suggestions=SEARCH_SUGGESTIONS,
            current_user=_get_current_user(),
        )

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")

            user = User.query.filter_by(username=username).first() if username else None
            if not user or not check_password_hash(user.password_hash, password):
                flash("Invalid username or password.", "error")
                return render_template("login.html", current_user=_get_current_user()), 401

            session["user_id"] = user.id
            session["username"] = user.username
            flash("You are now logged in.", "success")
            return redirect(url_for("index"))

        return render_template("login.html", current_user=_get_current_user())

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")

            if not username or not email or not password:
                flash("Username, email, and password are required.", "error")
                return render_template("register.html", current_user=_get_current_user()), 400

            if len(password) < 8:
                flash("Password must be at least 8 characters long.", "error")
                return render_template("register.html", current_user=_get_current_user()), 400

            if User.query.filter_by(username=username).first():
                flash("That username is already taken.", "error")
                return render_template("register.html", current_user=_get_current_user()), 409

            if User.query.filter_by(email=email).first():
                flash("That email is already registered.", "error")
                return render_template("register.html", current_user=_get_current_user()), 409

            new_user = User(
                username=username,
                email=email,
                password_hash=generate_password_hash(password),
            )
            db.session.add(new_user)
            db.session.commit()

            session["user_id"] = new_user.id
            session["username"] = new_user.username
            flash("Registration successful. Welcome!", "success")
            return redirect(url_for("index"))

        return render_template("register.html", current_user=_get_current_user())

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        flash("You have been logged out.", "success")
        return redirect(url_for("index"))


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


def _get_current_user() -> User | None:
    """Return the logged-in user from session if present."""
    user_id = session.get("user_id")
    if not user_id:
        return None
    return db.session.get(User, user_id)


# Create a global application instance for CLI and WSGI servers
app = create_app()

if __name__ == "__main__":
    # Development server with debug enabled
    app.run(debug=True)