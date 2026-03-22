# bara-kshaar
A minimal Flask application that lets you search the 12 tissue‑salt remedies.

## Functionality summary

- Remedy search across name, full name, description, and keywords.
- User authentication with registration, login, logout, and session-based current user handling.
- Health assessment form with validation for DOB format (`MM/DD`) and input length checks.
- Symptom-to-remedy ranking and recommended tissue-salt suggestions based on submitted health text.
- Appointment management APIs for authenticated users:
   - Create appointment
   - Update appointment
   - Delete appointment
   - List own appointments
- Email notifications to both user and admin for:
   - New registration
   - New appointment
   - Appointment changes
   - Appointment deletion
- One-day-prior appointment reminders via CLI job and protected admin API trigger.
- Duplicate reminder protection using a reminder log table (one reminder per appointment per reminder day).
- Health check endpoint for database connectivity verification.

## API reference table

| Endpoint | Method | Auth | Description |
| --- | --- | --- | --- |
| /health | GET | No | Health check for database connectivity. |
| / | GET | No | Home page with remedy search. |
| /login | GET, POST | No | Render login form and authenticate user. |
| /register | GET, POST | No | Render registration form and create new user account. |
| /logout | POST | Yes (session) | Clear session and log out current user. |
| /health-assessment | GET, POST | No | Render and submit health assessment form; calculates recommendations. |
| /api/appointments | GET | Yes (session) | List appointments for current logged-in user. |
| /api/appointments | POST | Yes (session) | Create appointment. Body: date, time, notes (optional). |
| /api/appointments/{appointment_id} | PUT | Yes (session) | Update existing appointment date, time, or notes. |
| /api/appointments/{appointment_id} | DELETE | Yes (session) | Delete existing appointment. |
| /api/admin/send-appointment-reminders | POST | Admin | Trigger one-day-prior reminder job. Admin via X-Admin-Token header or admin session email. |

## Setup

1. Create a virtual environment and install dependencies:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. (Optional) create a `.env` file at the project root and override any of the
   configuration variables defined in `config.py`:

   ```ini
   DATABASE_URL=postgresql://user:pass@localhost:5432/remedies_db
   SECRET_KEY=some-long-secret
   MAIL_SERVER=smtp.example.com
   MAIL_PORT=587
   MAIL_USERNAME=your-smtp-username
   MAIL_PASSWORD=your-smtp-password
   MAIL_USE_TLS=True
   MAIL_USE_SSL=False
   MAIL_FROM=no-reply@example.com
   ADMIN_EMAIL=admin@example.com
   ADMIN_API_TOKEN=change-this-to-a-strong-random-token
   ```

3. Initialise the database and seed the twelve salts:

   ```bash
   flask --app app init-db
   ```

4. Start the development server:

   ```bash
   flask --app app run --reload
   ```

## Email notifications

The app sends notifications to both the user and admin for:

- New registration
- New appointment
- Appointment updates
- Appointment deletion

Run the next-day reminder job (appointments scheduled for tomorrow):

```bash
flask --app app send-appointment-reminders
```

You can also trigger reminders through a protected admin API endpoint:

```bash
curl -X POST http://localhost:5000/api/admin/send-appointment-reminders \
   -H "X-Admin-Token: your-admin-api-token"
```

The reminder system prevents duplicate reminders by recording one reminder per appointment per reminder day.

In production, schedule the above command to run once daily (for example via a cron job or your hosting provider's scheduler).

## Project layout

- `app.py` – application factory, routing, CLI helpers
- `config.py` – configuration class (reads from environment / `.env`)
- `models.py` – SQLAlchemy models
- `templates/` – Jinja2 templates
- `static/` – static assets (header image, CSS, …)

