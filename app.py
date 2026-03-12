from flask import Flask, render_template, request
from config import Config
from models import db, Remedy
from sqlalchemy import or_


def create_app():
    # an explicit static_folder argument makes it easier to reason about
    app = Flask(__name__, static_folder="static")
    app.config.from_object(Config)
    db.init_app(app)

    # database helpers exposed as `flask` CLI commands
    @app.cli.command("init-db")
    def init_db():
        """Create database tables and seed initial data if necessary."""
        db.create_all()
        _seed_if_empty()
        print("database initialized")

    def _seed_if_empty():
        # idempotent seeding; safe to run multiple times
        if Remedy.query.first():
            return
        salts = [
            ("Calc fluor", "Calcium fluoride"),
            ("Calc phos", "Calcium phosphate"),
            ("Calc sulph", "Calcium sulfate"),
            ("Ferrum phos", "Iron phosphate"),
            ("Kali mur", "Potassium chloride"),
            ("Kali phos", "Potassium phosphate"),
            ("Kali sul", "Potassium sulfate"),
            ("Mag phos", "Magnesium phosphate"),
            ("Nat mur", "Sodium chloride"),
            ("Nat phos", "Sodium phosphate"),
            ("Nat sulph", "Sodium sulfate"),
            ("Silicea", "Silicea"),
        ]
        for name, full_name in salts:
            r = Remedy(
                name=name,
                full_name=full_name,
                description=f"Traditional remedy: {full_name}.",
                keywords=f"{name.lower()} {full_name.lower()}"
            )
            db.session.add(r)
        db.session.commit()

    @app.route("/", methods=["GET"])
    def index():
        query = request.args.get("q", "").strip()
        remedies = []
        if query:
            q = f"%{query.lower()}%"
            remedies = Remedy.query.filter(
                or_(
                    Remedy.name.ilike(q),
                    Remedy.full_name.ilike(q),
                    Remedy.description.ilike(q),
                    Remedy.keywords.ilike(q),
                )
            ).all()
        return render_template("index.html", query=query, remedies=remedies)

    return app


# create a global application instance so that the CLI and WSGI servers can
# import it simply using `from app import app` or by pointing FLASK_APP=app
app = create_app()

if __name__ == "__main__":
    # development server with debug enabled
    app.run(debug=True)