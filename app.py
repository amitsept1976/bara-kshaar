from flask import Flask, render_template, request
from config import Config
from models import db, Remedy
from sqlalchemy import or_

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)

    @app.before_first_request
    def create_tables():
        db.create_all()
        seed_if_empty()

    def seed_if_empty():
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

if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)