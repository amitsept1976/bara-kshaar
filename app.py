import logging
import re
import secrets
import ssl
import smtplib
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from typing import TypedDict

from flask import Flask, current_app, flash, redirect, render_template, request, session, url_for
from sqlalchemy import or_, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.security import check_password_hash, generate_password_hash

from config import Config
from models import Appointment, AppointmentReminder, Remedy, User, db
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

STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "for",
    "from", "has", "have", "i", "in", "is", "it", "its", "my", "of", "on",
    "or", "that", "the", "their", "this", "to", "was", "were", "with", "you",
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


class RankedRemedy(TypedDict):
    name: str
    salts: list[str]
    score: int


def _to_bool(value: object, default: bool) -> bool:
    """Parse bool-like config values safely (supports env strings like 'False')."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        return default
    return bool(value)


def _get_mail_settings(config: dict | object) -> dict[str, object]:
    """Read normalized mail settings from Flask config and report missing requirements."""
    mail_server = str(config.get("MAIL_SERVER", "")).strip()
    mail_port = int(config.get("MAIL_PORT", 587))
    mail_username = str(config.get("MAIL_USERNAME", "")).strip()
    mail_password = str(config.get("MAIL_PASSWORD", "")).strip()
    mail_use_tls = _to_bool(config.get("MAIL_USE_TLS", True), default=True)
    mail_use_ssl = _to_bool(config.get("MAIL_USE_SSL", False), default=False)
    mail_from = str(config.get("MAIL_FROM", "")).strip() or mail_username
    admin_email = str(config.get("ADMIN_EMAIL", "")).strip().lower()

    missing: list[str] = []
    if not mail_server:
        missing.append("MAIL_SERVER or SMTP_SERVER")
    if not mail_from:
        missing.append("MAIL_FROM/EMAIL_FROM or MAIL_USERNAME")

    return {
        "mail_server": mail_server,
        "mail_port": mail_port,
        "mail_username": mail_username,
        "mail_password": mail_password,
        "mail_use_tls": mail_use_tls,
        "mail_use_ssl": mail_use_ssl,
        "mail_from": mail_from,
        "admin_email": admin_email,
        "missing": missing,
        "is_configured": not missing,
    }


def _log_startup_configuration(app: Flask) -> None:
    """Log deployment-critical configuration status during startup."""
    mail_settings = _get_mail_settings(app.config)
    if mail_settings["is_configured"]:
        logger.info(
            "Mail configuration loaded: host=%s port=%s tls=%s ssl=%s from=%s admin=%s",
            mail_settings["mail_server"],
            mail_settings["mail_port"],
            mail_settings["mail_use_tls"],
            mail_settings["mail_use_ssl"],
            mail_settings["mail_from"],
            mail_settings["admin_email"] or "(not set)",
        )
        return

    logger.warning(
        "Email notifications are disabled because required mail configuration is missing: %s. "
        "On Render, set these values in the service Environment tab rather than relying on a local .env file.",
        ", ".join(mail_settings["missing"]),
    )
    logger.warning(
        "For Gmail SMTP use: MAIL_SERVER=smtp.gmail.com, MAIL_PORT=587, MAIL_USE_TLS=True, "
        "MAIL_USE_SSL=False, MAIL_USERNAME=<gmail>, MAIL_PASSWORD=<google-app-password>."
    )


def create_app() -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__, static_folder="static")
    app.config.from_object(Config)
    _log_startup_configuration(app)
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

    @app.cli.command("send-appointment-reminders")
    def send_appointment_reminders() -> None:
        """Send reminder emails for appointments scheduled tomorrow."""
        result = _send_next_day_appointment_reminders()
        print(
            "Reminder processing complete. "
            f"Notified: {result['notified']}, "
            f"Skipped: {result['skipped_already_sent']}, "
            f"Failed: {result['failed']}, "
            f"Total candidates: {result['total_candidates']}"
        )


def _register_routes(app: Flask) -> None:
    """Register application routes."""
    def _render_health_assessment(**context: object) -> str:
        """Render health assessment template with current user injected."""
        return render_template(
            "health_assessment.html",
            current_user=_get_current_user(),
            **context,
        )

    @app.route("/health", methods=["GET"])
    def health():
        """Health check endpoint to verify database connectivity."""
        try:
            db.session.execute(text("SELECT 1"))
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
                _send_registration_notifications(new_user)
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
            height = request.form.get("height", "").strip()
            weight = request.form.get("weight", "").strip()
            ailment1 = request.form.get("ailment1", "").strip()
            ailment2 = request.form.get("ailment2", "").strip()
            ailment3 = request.form.get("ailment3", "").strip()
            family_history = request.form.get("family_history", "").strip()

            form_context = {
                "submitted_dob": dob,
                "submitted_height": height,
                "submitted_weight": weight,
                "submitted_ailment1": ailment1,
                "submitted_ailment2": ailment2,
                "submitted_ailment3": ailment3,
                "submitted_family_history": family_history,
            }

            # Validation
            if not all([dob, ailment1, ailment2, ailment3, family_history]):
                flash("All fields are required.", "error")
                return _render_health_assessment(**form_context), 400

            # Validate date of birth format (MM/DD)
            if not _validate_dob_format(dob):
                flash("Date of birth must be in MM/DD format (e.g., 03/21).", "error")
                return _render_health_assessment(**form_context), 400

            # Validate character limits
            if len(ailment1) > 400 or len(ailment2) > 400 or len(ailment3) > 400 or len(family_history) > 400:
                flash("One or more fields exceed the 400 character limit.", "error")
                return _render_health_assessment(**form_context), 400

            print(
                f"Health assessment submitted - DOB: {dob}, Height: {height or 'n/a'}, Weight: {weight or 'n/a'}, Ailments: {len(ailment1)} / {len(ailment2)} / {len(ailment3)} chars, Family history: {len(family_history)} chars",
                flush=True,
            )
            logger.info(f"Health assessment submitted - DOB: {dob}")

            # Store in session for now (or redirect to results)
            session["health_data"] = {
                "dob": dob,
                "height": height,
                "weight": weight,
                "ailment1": ailment1,
                "ailment2": ailment2,
                "ailment3": ailment3,
                "family_history": family_history,
            }

            month = _extract_month_from_dob(dob)
            deficient_salt = MONTH_DEFICIENT_SALT.get(month)
            ailment1_ranked_remedies = _rank_remedies_from_text(ailment1)
            ailment2_ranked_remedies = _rank_remedies_from_text(ailment2)
            ailment3_ranked_remedies = _rank_remedies_from_text(ailment3)
            family_history_ranked_remedies = _rank_remedies_from_text(family_history)

            ailment1_salts = _derive_salts_from_ranked_remedies(ailment1_ranked_remedies)
            ailment2_salts = _derive_salts_from_ranked_remedies(ailment2_ranked_remedies)
            ailment3_salts = _derive_salts_from_ranked_remedies(ailment3_ranked_remedies)
            family_history_salts = _derive_salts_from_ranked_remedies(family_history_ranked_remedies)

            all_ranked_remedies = _merge_ranked_remedies(
                ailment1_ranked_remedies,
                ailment2_ranked_remedies,
                ailment3_ranked_remedies,
                family_history_ranked_remedies,
            )
            remedy_recommended_salts = _derive_salts_from_ranked_remedies(all_ranked_remedies)
            all_recommended_salts = _merge_unique_salts(
                [deficient_salt] if deficient_salt else [],
                remedy_recommended_salts,
            )

            if all_recommended_salts:
                flash("Generated salt recommendations from your ailments and family history.", "success")
            else:
                flash("No remedy-based salt matches found for the submitted text.", "error")

            return _render_health_assessment(
                deficient_salt=deficient_salt,
                birth_month=month,
                ailment1_salts=ailment1_salts,
                ailment2_salts=ailment2_salts,
                ailment3_salts=ailment3_salts,
                family_history_salts=family_history_salts,
                all_recommended_salts=all_recommended_salts,
                all_ranked_remedies=all_ranked_remedies,
                **form_context,
            )

        return _render_health_assessment()

    @app.route("/api/health-assessment/autofill", methods=["GET"])
    def health_assessment_autofill():
        """Return ailment prompt suggestions derived from remedies dataset."""
        query = request.args.get("q", "").strip().lower()
        max_results = min(max(int(request.args.get("limit", 8)), 1), 20)

        if not query or len(query) < 2:
            return {"suggestions": []}

        suggestions = [
            prompt
            for prompt in SEARCH_SUGGESTIONS
            if query in prompt.lower()
        ][:max_results]

        return {"suggestions": suggestions}

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
            _send_appointment_created_notifications(current_user, appointment)
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
        old_date = appointment.appointment_date
        old_time = appointment.appointment_time
        old_notes = appointment.notes

        try:
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
            _send_appointment_updated_notifications(
                current_user,
                appointment,
                old_date,
                old_time,
                old_notes,
            )
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

        deleted_date = appointment.appointment_date
        deleted_time = appointment.appointment_time
        deleted_notes = appointment.notes

        try:
            db.session.delete(appointment)
            db.session.commit()
            logger.info(f"Appointment {appointment_id} deleted for user {current_user.username}")
            _send_appointment_deleted_notifications(
                current_user,
                appointment_id,
                deleted_date,
                deleted_time,
                deleted_notes,
            )
            return {"success": True}
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error deleting appointment {appointment_id}: {e}", exc_info=True)
            return {"success": False, "message": "Error deleting appointment"}, 500

    @app.route("/api/admin/send-appointment-reminders", methods=["POST"])
    def admin_send_appointment_reminders():
        """Admin endpoint to trigger one-day-prior reminder emails."""
        authorized, reason = _is_admin_request_authorized()
        if not authorized:
            return {"success": False, "message": reason}, 403

        result = _send_next_day_appointment_reminders()
        return {
            "success": True,
            "message": "Reminder job completed",
            "stats": result,
        }, 200

    @app.route("/api/admin/test-email", methods=["POST"])
    def admin_test_email():
        """Admin endpoint to send a one-off SMTP test email."""
        authorized, reason = _is_admin_request_authorized()
        if not authorized:
            return {"success": False, "message": reason}, 403

        payload = request.get_json(silent=True) or {}
        recipient = str(payload.get("to", "")).strip().lower()
        if not recipient:
            recipient = str(current_app.config.get("ADMIN_EMAIL", "")).strip().lower()

        if not recipient:
            return {
                "success": False,
                "message": "Recipient is required. Provide JSON {\"to\": \"email@example.com\"} or set ADMIN_EMAIL.",
            }, 400

        subject = str(payload.get("subject", "")).strip() or "Bara-Kshaar SMTP test email"
        body = str(payload.get("body", "")).strip() or (
            "This is a test email from Bara-Kshaar.\n\n"
            f"Sent at (UTC): {datetime.utcnow().isoformat(timespec='seconds')}\n"
            f"Authorized via: {reason}"
        )

        sent = _send_email(subject, body, [recipient])
        if not sent:
            return {
                "success": False,
                "message": "SMTP send failed. Check logs for provider/auth details.",
                "recipient": recipient,
            }, 502

        return {
            "success": True,
            "message": "Test email sent",
            "recipient": recipient,
        }, 200


def _build_email_recipients(user_email: str | None = None) -> tuple[list[str], str | None]:
    """Build normalized recipient list and return admin email separately."""
    admin_email_raw = str(current_app.config.get("ADMIN_EMAIL", "")).strip().lower()
    admin_email = admin_email_raw or None
    recipients: list[str] = []
    seen: set[str] = set()

    for email in [user_email, admin_email]:
        if not email:
            continue
        normalized = email.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        recipients.append(normalized)

    return recipients, admin_email


def _send_email(subject: str, body: str, recipients: list[str]) -> bool:
    """Send an email using SMTP settings from app config."""
    mail_settings = _get_mail_settings(current_app.config)
    mail_server = str(mail_settings["mail_server"])
    mail_port = int(mail_settings["mail_port"])
    mail_username = str(mail_settings["mail_username"])
    mail_password = str(mail_settings["mail_password"])
    mail_use_tls = bool(mail_settings["mail_use_tls"])
    mail_use_ssl = bool(mail_settings["mail_use_ssl"])
    mail_from = str(mail_settings["mail_from"])

    if not mail_settings["is_configured"]:
        logger.warning(
            "Skipping email because mail configuration is incomplete (%s). Subject: %s",
            ", ".join(mail_settings["missing"]),
            subject,
        )
        return False
    if not recipients:
        logger.warning("Skipping email (no recipients). Subject: %s", subject)
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = mail_from
    msg["To"] = ", ".join(recipients)
    msg["Reply-To"] = mail_from
    msg.set_content(body)

    try:
        ssl_context = ssl.create_default_context()
        if mail_use_ssl:
            with smtplib.SMTP_SSL(mail_server, mail_port, timeout=15, context=ssl_context) as smtp:
                if mail_username and mail_password:
                    smtp.login(mail_username, mail_password)
                smtp.send_message(msg, from_addr=mail_from, to_addrs=recipients)
        else:
            with smtplib.SMTP(mail_server, mail_port, timeout=15) as smtp:
                smtp.ehlo()
                if mail_use_tls:
                    smtp.starttls(context=ssl_context)
                    smtp.ehlo()
                if mail_username and mail_password:
                    smtp.login(mail_username, mail_password)
                smtp.send_message(msg, from_addr=mail_from, to_addrs=recipients)
    except Exception as e:
        logger.error("Failed to send email '%s': %s", subject, e, exc_info=True)
        return False

    logger.info("Email sent successfully. Subject: %s, Recipients: %s", subject, recipients)
    return True


def _send_user_and_admin_emails(
    user_email: str,
    user_subject: str,
    user_body: str,
    admin_subject: str,
    admin_body: str,
) -> bool:
    """Send user and admin notifications for a business event."""
    _, admin_email = _build_email_recipients(user_email)
    user_sent = _send_email(user_subject, user_body, [user_email])

    if admin_email and admin_email != user_email.strip().lower():
        admin_sent = _send_email(admin_subject, admin_body, [admin_email])
        if not admin_sent:
            logger.warning(
                "Admin notification was not delivered. Subject: %s, Recipient: %s",
                admin_subject,
                admin_email,
            )

    return user_sent


def _format_appointment_details(appointment_date: date, appointment_time: str, notes: str | None) -> str:
    """Render appointment details for outbound notifications."""
    notes_text = notes if notes else "(no notes provided)"
    return (
        f"Date: {appointment_date.isoformat()}\n"
        f"Time: {appointment_time}\n"
        f"Notes: {notes_text}"
    )


def _send_registration_notifications(user: User) -> None:
    """Send registration confirmation emails to user and admin."""
    user_subject = "Welcome to Bara-Kshaar - Registration successful"
    user_body = (
        f"Hello {user.username},\n\n"
        "Your registration was successful.\n"
        "You can now log in and manage your health assessments and appointments.\n\n"
        "Regards,\n"
        "Bara-Kshaar Team"
    )

    admin_subject = f"New user registration: {user.username}"
    admin_body = (
        "A new user has registered on Bara-Kshaar.\n\n"
        f"Username: {user.username}\n"
        f"Email: {user.email}\n"
        f"Registered at (UTC): {datetime.utcnow().isoformat(timespec='seconds')}"
    )

    _send_user_and_admin_emails(user.email, user_subject, user_body, admin_subject, admin_body)


def _send_appointment_created_notifications(user: User, appointment: Appointment) -> None:
    """Send appointment creation notifications to user and admin."""
    details = _format_appointment_details(
        appointment.appointment_date,
        appointment.appointment_time,
        appointment.notes,
    )

    user_subject = "Appointment booked successfully"
    user_body = (
        f"Hello {user.username},\n\n"
        "Your appointment has been booked.\n\n"
        f"{details}\n\n"
        "Regards,\n"
        "Bara-Kshaar Team"
    )

    admin_subject = f"New appointment booked by {user.username}"
    admin_body = (
        "A new appointment has been created.\n\n"
        f"User: {user.username} ({user.email})\n"
        f"Appointment ID: {appointment.id}\n"
        f"{details}"
    )

    _send_user_and_admin_emails(user.email, user_subject, user_body, admin_subject, admin_body)


def _send_appointment_updated_notifications(
    user: User,
    appointment: Appointment,
    old_date: date,
    old_time: str,
    old_notes: str | None,
) -> None:
    """Send appointment update notifications to user and admin."""
    old_details = _format_appointment_details(old_date, old_time, old_notes)
    new_details = _format_appointment_details(
        appointment.appointment_date,
        appointment.appointment_time,
        appointment.notes,
    )

    user_subject = "Appointment updated successfully"
    user_body = (
        f"Hello {user.username},\n\n"
        "Your appointment has been updated.\n\n"
        "Previous details:\n"
        f"{old_details}\n\n"
        "Updated details:\n"
        f"{new_details}\n\n"
        "Regards,\n"
        "Bara-Kshaar Team"
    )

    admin_subject = f"Appointment updated by {user.username}"
    admin_body = (
        "An appointment has been updated.\n\n"
        f"User: {user.username} ({user.email})\n"
        f"Appointment ID: {appointment.id}\n\n"
        "Previous details:\n"
        f"{old_details}\n\n"
        "Updated details:\n"
        f"{new_details}"
    )

    _send_user_and_admin_emails(user.email, user_subject, user_body, admin_subject, admin_body)


def _send_appointment_deleted_notifications(
    user: User,
    appointment_id: int,
    deleted_date: date,
    deleted_time: str,
    deleted_notes: str | None,
) -> None:
    """Send appointment deletion notifications to user and admin."""
    deleted_details = _format_appointment_details(deleted_date, deleted_time, deleted_notes)

    user_subject = "Appointment deleted"
    user_body = (
        f"Hello {user.username},\n\n"
        "Your appointment has been deleted.\n\n"
        f"Deleted appointment details:\n{deleted_details}\n\n"
        "Regards,\n"
        "Bara-Kshaar Team"
    )

    admin_subject = f"Appointment deleted by {user.username}"
    admin_body = (
        "An appointment has been deleted.\n\n"
        f"User: {user.username} ({user.email})\n"
        f"Appointment ID: {appointment_id}\n"
        f"Deleted appointment details:\n{deleted_details}"
    )

    _send_user_and_admin_emails(user.email, user_subject, user_body, admin_subject, admin_body)


def _send_next_day_appointment_reminders() -> dict[str, int]:
    """Send reminder emails for appointments scheduled for tomorrow."""
    tomorrow = datetime.utcnow().date() + timedelta(days=1)
    appointments = Appointment.query.filter_by(appointment_date=tomorrow).all()

    notified_count = 0
    skipped_count = 0
    failed_count = 0

    for appointment in appointments:
        existing_log = AppointmentReminder.query.filter_by(
            appointment_id=appointment.id,
            reminder_date=tomorrow,
        ).first()
        if existing_log:
            skipped_count += 1
            continue

        user = db.session.get(User, appointment.user_id)
        if not user:
            failed_count += 1
            continue

        details = _format_appointment_details(
            appointment.appointment_date,
            appointment.appointment_time,
            appointment.notes,
        )

        user_subject = "Reminder: Your appointment is tomorrow"
        user_body = (
            f"Hello {user.username},\n\n"
            "This is a reminder that your appointment is scheduled for tomorrow.\n\n"
            f"{details}\n\n"
            "Regards,\n"
            "Bara-Kshaar Team"
        )

        admin_subject = f"Reminder sent: {user.username}'s appointment tomorrow"
        admin_body = (
            "A next-day appointment reminder has been processed.\n\n"
            f"User: {user.username} ({user.email})\n"
            f"Appointment ID: {appointment.id}\n"
            f"{details}"
        )

        user_sent = _send_user_and_admin_emails(
            user.email,
            user_subject,
            user_body,
            admin_subject,
            admin_body,
        )
        if not user_sent:
            failed_count += 1
            continue

        reminder_log = AppointmentReminder(
            appointment_id=appointment.id,
            reminder_date=tomorrow,
        )
        db.session.add(reminder_log)
        try:
            db.session.commit()
            notified_count += 1
        except IntegrityError:
            db.session.rollback()
            skipped_count += 1
        except Exception as e:
            db.session.rollback()
            logger.error(
                "Error saving reminder log for appointment %s: %s",
                appointment.id,
                e,
                exc_info=True,
            )
            failed_count += 1

    logger.info(
        "Next-day reminder run completed. Notified=%s, Skipped=%s, Failed=%s, Total=%s",
        notified_count,
        skipped_count,
        failed_count,
        len(appointments),
    )
    return {
        "notified": notified_count,
        "skipped_already_sent": skipped_count,
        "failed": failed_count,
        "total_candidates": len(appointments),
    }


def _is_admin_request_authorized() -> tuple[bool, str]:
    """Authorize reminder endpoint via admin session email or API token."""
    configured_token = str(current_app.config.get("ADMIN_API_TOKEN", "")).strip()
    provided_token = request.headers.get("X-Admin-Token", "").strip()
    if configured_token and provided_token and secrets.compare_digest(provided_token, configured_token):
        return True, "authorized-by-token"

    current_user = _get_current_user()
    admin_email = str(current_app.config.get("ADMIN_EMAIL", "")).strip().lower()
    if current_user and admin_email and current_user.email.strip().lower() == admin_email:
        return True, "authorized-by-admin-user"

    return False, "Admin authorization required (admin login or X-Admin-Token)."


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


def _extract_candidate_terms(text: str, limit: int = 10) -> list[str]:
    """Extract meaningful search terms from free-text user input."""
    terms: list[str] = []
    seen: set[str] = set()
    for token in re.findall(r"[a-zA-Z]+", text.lower()):
        if len(token) < 3 or token in STOP_WORDS or token in seen:
            continue
        seen.add(token)
        terms.append(token)
        if len(terms) >= limit:
            break
    return terms


def _parse_salts_from_full_name(full_name: str) -> list[str]:
    """Extract short salt names from a remedy full_name string."""
    salts: list[str] = []
    seen: set[str] = set()
    for part in full_name.split(","):
        candidate = part.strip()
        if not candidate:
            continue
        short_name = candidate.split("(")[0].strip().strip(".-")
        if not short_name:
            continue
        key = short_name.casefold()
        if key in seen:
            continue
        seen.add(key)
        salts.append(short_name)
    return salts


def _rank_remedies_from_text(user_text: str, max_results: int = 8) -> list[RankedRemedy]:
    """Rank remedies from the remedies table by text overlap score."""
    text = user_text.strip()
    if not text:
        return []

    remedy_scores: dict[int, int] = {}
    remedies_by_id: dict[int, Remedy] = {}

    for remedy in _search_remedies(text):
        remedies_by_id[remedy.id] = remedy
        remedy_scores[remedy.id] = remedy_scores.get(remedy.id, 0) + 3

    for term in _extract_candidate_terms(text):
        for remedy in _search_remedies(term):
            remedies_by_id[remedy.id] = remedy
            remedy_scores[remedy.id] = remedy_scores.get(remedy.id, 0) + 1

    ranked_remedies = sorted(
        remedies_by_id.values(),
        key=lambda remedy: (
            -remedy_scores.get(remedy.id, 0),
            remedy.name.lower(),
        ),
    )

    ranked_items: list[RankedRemedy] = []
    for remedy in ranked_remedies[:max_results]:
        ranked_items.append(
            {
                "name": remedy.name,
                "salts": _parse_salts_from_full_name(remedy.full_name),
                "score": remedy_scores.get(remedy.id, 0),
            }
        )

    return ranked_items


def _derive_salts_from_ranked_remedies(ranked_remedies: list[RankedRemedy], max_salts: int = 8) -> list[str]:
    """Extract unique salts from ranked remedies while preserving rank order."""
    salts: list[str] = []
    seen_salts: set[str] = set()

    for ranked in ranked_remedies:
        for salt in ranked["salts"]:
            key = salt.casefold()
            if key in seen_salts:
                continue
            seen_salts.add(key)
            salts.append(salt)
            if len(salts) >= max_salts:
                return salts

    return salts


def _merge_ranked_remedies(
    *ranked_lists: list[RankedRemedy],
    max_results: int = 12,
) -> list[RankedRemedy]:
    """Merge ranked remedies across inputs and sort by total score descending."""
    merged_by_name: dict[str, RankedRemedy] = {}
    order: list[str] = []

    for ranked_list in ranked_lists:
        for ranked in ranked_list:
            name = str(ranked["name"])
            key = name.casefold()
            score = int(ranked["score"])
            salts = [str(salt) for salt in ranked["salts"]]

            if key not in merged_by_name:
                merged_by_name[key] = {
                    "name": name,
                    "score": score,
                    "salts": salts[:],
                }
                order.append(key)
                continue

            existing = merged_by_name[key]
            existing["score"] = int(existing["score"]) + score
            existing_salts = existing["salts"]
            seen_salts = {salt.casefold() for salt in existing_salts}
            for salt in salts:
                if salt.casefold() in seen_salts:
                    continue
                existing_salts.append(salt)
                seen_salts.add(salt.casefold())

    ranked_merged = sorted(
        merged_by_name.values(),
        key=lambda item: (
            -int(item["score"]),
            order.index(str(item["name"]).casefold()),
        ),
    )
    return ranked_merged[:max_results]


def _merge_unique_salts(*salt_lists: list[str]) -> list[str]:
    """Merge salt lists while preserving first-seen order and removing duplicates."""
    merged: list[str] = []
    seen: set[str] = set()

    for salt_list in salt_lists:
        for salt in salt_list:
            key = salt.casefold()
            if key in seen:
                continue
            seen.add(key)
            merged.append(salt)

    return merged


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