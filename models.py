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


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    def __repr__(self):
        return f"<User {self.username}>"