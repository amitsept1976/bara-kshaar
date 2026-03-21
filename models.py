from datetime import datetime

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Remedy(db.Model):
    __tablename__ = "remedies"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)  # e.g. "Calc fluor"
    full_name = db.Column(db.String(255), nullable=False)  # e.g. "Calcium fluoride"
    description = db.Column(db.Text, nullable=True)  # what it’s used for
    keywords = db.Column(db.Text, nullable=True)  # comma/space separated tags

    def __repr__(self) -> str:
        return f"<Remedy {self.name}>"


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    appointments = db.relationship(
        "Appointment",
        backref="user",
        lazy=True,
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<User {self.username}>"


class Appointment(db.Model):
    __tablename__ = "appointments"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    appointment_date = db.Column(db.Date, nullable=False)
    appointment_time = db.Column(db.String(5), nullable=False)  # HH:MM format
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    def __repr__(self) -> str:
        return f"<Appointment {self.user_id} on {self.appointment_date} at {self.appointment_time}>"

    def to_dict(self) -> dict[str, str | int | None]:
        """Convert appointment to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "date": self.appointment_date.isoformat(),
            "time": self.appointment_time,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
        }