# bara-kshaar
A minimal Flask application that lets you search the 12 tissue‑salt remedies.

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
   ```

3. Initialise the database and seed the twelve salts:

   ```bash
   flask --app app init-db
   ```

4. Start the development server:

   ```bash
   flask --app app run --reload
   ```

## Project layout

- `app.py` – application factory, routing, CLI helpers
- `config.py` – configuration class (reads from environment / `.env`)
- `models.py` – SQLAlchemy models
- `templates/` – Jinja2 templates
- `static/` – static assets (header image, CSS, …)

