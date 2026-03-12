from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Remedy(db.Model):
    __tablename__ = "remedies"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)          # e.g. "Calc fluor"
    full_name = db.Column(db.String(200), nullable=False)     # e.g. "Calcium fluoride"
    description = db.Column(db.Text, nullable=True)           # what it’s used for
    keywords = db.Column(db.Text, nullable=True)              # comma/space separated tags

    def __repr__(self):
        return f"<Remedy {self.name}>"