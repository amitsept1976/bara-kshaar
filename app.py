import logging
from flask import Flask, flash, redirect, render_template, request, session, url_for
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy import or_
from werkzeug.security import check_password_hash, generate_password_hash

from config import Config
from models import Remedy, User, Appointment, db
from seeds import REMEDY_SEEDS

# Configure logging
logger = logging.getLogger(__name__)

MONTH_DEFICIENT_SALT = {
    1: "Calc Phos",
    2: "Nat Mur",
    3: "Ferr Phos",
    4: "Kali Phos",
    5: "Nat Sulph",
    6: "Kali Mur",
    7: "Calc Flour",
    8: "Mag Phos",
    9: "Kali Sulph",
    10: "Nat Phos",
    11: "Calc Sulph",
    12: "Silicae",
}


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
        try:
            db.create_all()
            print("✓ Database tables created successfully", flush=True)
            logger.info("Database tables created successfully")
        except Exception as e:
            print(f"✗ Error creating database tables: {e}", flush=True)
            logger.error(f"Error creating database tables: {e}", exc_info=True)
        
        try:
            _seed_database_if_empty()
            print("✓ Database seeding completed", flush=True)
            logger.info("Database seeding completed")
        except Exception as e:
            print(f"✗ Error seeding database: {e}", flush=True)
            logger.error(f"Error seeding database: {e}", exc_info=True)

    # Register CLI commands
    _register_cli_commands(app)

    # Register routes
    _register_routes(app)

    return app


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
    @app.route("/health", methods=["GET"])
    def health():
        """Health check endpoint to verify database connectivity."""
        try:
            db.session.execute("SELECT 1")
            return {"status": "ok", "database": "connected"}, 200
        except Exception as e:
            logger.error(f"Health check failed: {e}", exc_info=True)
            return {"status": "error", "database": "disconnected", "error": str(e)}, 500

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
            return redirect(url_for("health_assessment"))

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

            try:
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
                print(f"✓ User registered successfully: {username}", flush=True)
                logger.info(f"User registered successfully: {username}")
            except IntegrityError as e:
                db.session.rollback()
                print(f"✗ IntegrityError during registration: {e}", flush=True)
                logger.error(f"IntegrityError during registration for {username}: {e}", exc_info=True)
                flash("That username or email is already in use.", "error")
                return render_template("register.html", current_user=_get_current_user()), 409
            except SQLAlchemyError as e:
                db.session.rollback()
                print(f"✗ Database error during registration: {e}", flush=True)
                logger.error(f"Database error during registration for {username}: {e}", exc_info=True)
                flash("Unable to create account right now. Please try again.", "error")
                return render_template("register.html", current_user=_get_current_user()), 500

            session["user_id"] = new_user.id
            session["username"] = new_user.username
            flash("Registration successful. Welcome!", "success")
            return redirect(url_for("health_assessment"))

        return render_template("register.html", current_user=_get_current_user())

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        flash("You have been logged out.", "success")
        return redirect(url_for("index"))

    @app.route("/health-assessment", methods=["GET", "POST"])
    def health_assessment():
        """Health assessment form to collect user health information."""
        if request.method == "POST":
            dob = request.form.get("dob", "").strip()
            ailment1 = request.form.get("ailment1", "").strip()
            ailment2 = request.form.get("ailment2", "").strip()
            family_history = request.form.get("family_history", "").strip()

            # Validation
            if not all([dob, ailment1, ailment2, family_history]):
                flash("All fields are required.", "error")
                return render_template("health_assessment.html", current_user=_get_current_user()), 400

            # Validate date of birth format (MM/DD)
            if not _validate_dob_format(dob):
                flash("Date of birth must be in MM/DD format (e.g., 03/21).", "error")
                return render_template("health_assessment.html", current_user=_get_current_user()), 400

            # Validate character limits
            if len(ailment1) > 400 or len(ailment2) > 400 or len(family_history) > 400:
                flash("One or more fields exceed the 400 character limit.", "error")
                return render_template("health_assessment.html", current_user=_get_current_user()), 400

            print(f"Health assessment submitted - DOB: {dob}, Ailments: {len(ailment1)} & {len(ailment2)} chars, Family history: {len(family_history)} chars", flush=True)
            logger.info(f"Health assessment submitted - DOB: {dob}")

            # Store in session for now (or redirect to results)
            session["health_data"] = {
                "dob": dob,
                "ailment1": ailment1,
                "ailment2": ailment2,
                "family_history": family_history,
            }

            month = _extract_month_from_dob(dob)
            deficient_salt = MONTH_DEFICIENT_SALT.get(month)

            if deficient_salt:
                flash(
                    f"Derived deficient salt from birth month {month}: {deficient_salt}.",
                    "success",
                )
            else:
                flash("Could not derive deficient salt from the provided date of birth.", "error")

            return render_template(
                "health_assessment.html",
                current_user=_get_current_user(),
                deficient_salt=deficient_salt,
                birth_month=month,
                submitted_dob=dob,
            )

        return render_template("health_assessment.html", current_user=_get_current_user())

    # API endpoints for appointments
    @app.route("/api/appointments", methods=["GET"])
    def api_appointments():
        """Get all appointments for the current user."""
        current_user = _get_current_user()
        if not current_user:
            return {"error": "Not authenticated"}, 401

        appointments = Appointment.query.filter_by(user_id=current_user.id).all()
        return [apt.to_dict() for apt in appointments]

    @app.route("/api/appointments", methods=["POST"])
    def create_appointment():
        """Create a new appointment."""
        current_user = _get_current_user()
        if not current_user:
            return {"error": "Not authenticated"}, 401

        data = request.get_json()
        date_str = data.get("date", "").strip()
        time_str = data.get("time", "").strip()
        notes = data.get("notes", "").strip()

        # Validate inputs
        if not date_str or not time_str:
            return {"success": False, "message": "Date and time are required"}, 400

        try:
            from datetime import datetime
            apt_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return {"success": False, "message": "Invalid date format"}, 400

        # Validate time format HH:MM
        if not _validate_time_format(time_str):
            return {"success": False, "message": "Invalid time format (HH:MM)"}, 400

        try:
            appointment = Appointment(
                user_id=current_user.id,
                appointment_date=apt_date,
                appointment_time=time_str,
                notes=notes if notes else None,
            )
            db.session.add(appointment)
            db.session.commit()
            logger.info(f"Appointment created for user {current_user.username}: {apt_date} at {time_str}")
            return {"success": True, "appointment": appointment.to_dict()}
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error creating appointment: {e}", exc_info=True)
            return {"success": False, "message": "Error creating appointment"}, 500

    @app.route("/api/appointments/<int:appointment_id>", methods=["PUT"])
    def update_appointment(appointment_id):
        """Update an existing appointment."""
        current_user = _get_current_user()
        if not current_user:
            return {"error": "Not authenticated"}, 401

        appointment = Appointment.query.filter_by(id=appointment_id, user_id=current_user.id).first()
        if not appointment:
            return {"success": False, "message": "Appointment not found"}, 404

        data = request.get_json()
        date_str = data.get("date", "").strip()
        time_str = data.get("time", "").strip()
        notes = data.get("notes", "").strip()

        try:
            from datetime import datetime
            if date_str:
                appointment.appointment_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            if time_str:
                if not _validate_time_format(time_str):
                    return {"success": False, "message": "Invalid time format (HH:MM)"}, 400
                appointment.appointment_time = time_str
            if notes or notes == "":
                appointment.notes = notes if notes else None

            db.session.commit()
            logger.info(f"Appointment {appointment_id} updated for user {current_user.username}")
            return {"success": True, "appointment": appointment.to_dict()}
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error updating appointment {appointment_id}: {e}", exc_info=True)
            return {"success": False, "message": "Error updating appointment"}, 500

    @app.route("/api/appointments/<int:appointment_id>", methods=["DELETE"])
    def delete_appointment(appointment_id):
        """Delete an appointment."""
        current_user = _get_current_user()
        if not current_user:
            return {"error": "Not authenticated"}, 401

        appointment = Appointment.query.filter_by(id=appointment_id, user_id=current_user.id).first()
        if not appointment:
            return {"success": False, "message": "Appointment not found"}, 404

        try:
            db.session.delete(appointment)
            db.session.commit()
            logger.info(f"Appointment {appointment_id} deleted for user {current_user.username}")
            return {"success": True}
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error deleting appointment {appointment_id}: {e}", exc_info=True)
            return {"success": False, "message": "Error deleting appointment"}, 500


def _validate_dob_format(dob: str) -> bool:
    """Validate date of birth in MM/DD format."""
    if not dob or len(dob) != 5 or dob[2] != '/':
        return False
    
    try:
        month, day = dob.split('/')
        month_int = int(month)
        day_int = int(day)
        return 1 <= month_int <= 12 and 1 <= day_int <= 31
    except (ValueError, AttributeError):
        return False


def _extract_month_from_dob(dob: str) -> int | None:
    """Extract birth month from MM/DD date string."""
    if not _validate_dob_format(dob):
        return None
    try:
        return int(dob.split("/")[0])
    except (ValueError, AttributeError, IndexError):
        return None


def _validate_time_format(time_str: str) -> bool:
    """Validate time in HH:MM format."""
    if not time_str or len(time_str) != 5 or time_str[2] != ':':
        return False
    
    try:
        hour, minute = time_str.split(':')
        hour_int = int(hour)
        minute_int = int(minute)
        return 0 <= hour_int <= 23 and 0 <= minute_int <= 59
    except (ValueError, AttributeError):
        return False


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