# Connecting Desis

A Flask web app for connecting travelers (trip matching, chat, blog, admin portal).

## Stack

- **Backend:** Flask 3, Flask-SQLAlchemy, Flask-Login, Flask-Migrate (Alembic), Flask-Mail, Flask-WTF (CSRF), Flask-CORS
- **Database:** PostgreSQL in production, SQLite for local dev
- **Auth:** Email/password + Google OAuth (implemented manually in `app/routes/auth.py`, not via flask-dance)
- **Server:** Gunicorn
- **File uploads:** local disk (`app/static/uploads`) — see `SETUP.md` for migrating to Google Cloud Storage

## Deployment

**Live/production deploys run on [Railway](https://railway.app).** Railway is the PaaS hosting the app — it:
- Builds and runs the app from the `Procfile` (`web: gunicorn run:app --bind 0.0.0.0:$PORT ...`)
- Provides a managed PostgreSQL database and injects its connection string as the `DATABASE_URL` env var
- Injects the `PORT` env var the app binds to
- Runs whatever env vars are set in the Railway project dashboard (Settings → Variables) — that's where production secrets (`FLASK_SECRET_KEY`, `DATABASE_URL`, `MAIL_PASSWORD`, OAuth credentials, etc.) live, not in this repo

There's also a `Dockerfile` and `cloudbuild.yaml` in this repo for deploying to **Google Cloud Run + Cloud SQL** instead — that was an earlier/alternate deployment path (see `SETUP.md` for the full GCP walkthrough). **Confirm with whoever has the Railway/GCP dashboard access which one is actually live before assuming** — the git history and current code (SSL handling tuned for Railway's Postgres, dynamic `$PORT`) point to Railway being the active one, but this wasn't verified against a live dashboard.

To deploy new code: push to `main` on GitHub — if a Railway auto-deploy is wired to this repo, it redeploys automatically. Otherwise deploy manually from the Railway CLI/dashboard.

## Database

- **Production:** PostgreSQL, connection string comes from `DATABASE_URL` (Railway sets this automatically for its managed Postgres add-on). The app rewrites `postgres://` → `postgresql://` and requires SSL (`sslmode=require`) automatically when it detects a `postgresql://` URL — see `app/__init__.py`.
- **Local dev:** defaults to SQLite (`sqlite:///dev.db`) if `DATABASE_URL` isn't set.
- **Migrations:** Flask-Migrate/Alembic, files in `migrations/`. Run `flask db upgrade` to apply, `flask db migrate -m "..."` to generate a new one after changing `app/models.py`.

## Environment variables

Yes — there's a local `.env` file (gitignored, not committed) with real values for local dev. `.env.example` is the committed template. Copy it to get started:

```bash
cp .env.example .env
```

| Variable | Purpose |
|---|---|
| `FLASK_SECRET_KEY` | Flask session signing key |
| `FLASK_ENV` | `development` or `production` (gates OAuth insecure-transport flag) |
| `DATABASE_URL` | Postgres connection string in prod; omit/leave as SQLite for local dev |
| `GOOGLE_OAUTH_CLIENT_ID` / `_SECRET` | Google login |
| `FACEBOOK_OAUTH_CLIENT_ID` / `_SECRET` | Present in `.env.example` but not currently wired up in `app/routes/auth.py` |
| `MAIL_SERVER` / `MAIL_PORT` / `MAIL_USE_TLS` / `MAIL_USERNAME` / `MAIL_PASSWORD` / `MAIL_DEFAULT_SENDER` | Outgoing email (Gmail SMTP by default); email sending is skipped if `MAIL_PASSWORD` is unset |
| `UPLOAD_FOLDER` | Where uploaded photos are saved |
| `MAX_CONTENT_LENGTH` | Max upload size in bytes |
| `ADMIN_EMAIL` | Reference value for the admin account |

In production these live in the Railway project's **Variables** tab, not in a committed file.

## Running locally

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # then edit values as needed

flask db upgrade        # applies migrations (SQLite by default)
python run.py           # http://localhost:5001
```

To make a user an admin:

```bash
flask shell
>>> from app import db
>>> from app.models import User
>>> u = User.query.filter_by(email='your@email.com').first()
>>> u.is_admin = True
>>> db.session.commit()
```

## Project layout

```
app/
  __init__.py       # app factory, config, extension init
  models.py         # SQLAlchemy models
  routes/           # blueprints: main, auth, trips, chat, admin, blog
  static/           # CSS/JS/uploads
  templates/         # Jinja templates
migrations/         # Alembic migrations
run.py              # local dev entrypoint
Procfile            # Railway/Heroku-style start command (gunicorn)
Dockerfile          # container build (used by the Cloud Run path)
cloudbuild.yaml     # GCP Cloud Build config (Cloud Run path, see SETUP.md)
SETUP.md            # detailed GCP Cloud Run + Cloud SQL setup guide
```

## Further reading

See `SETUP.md` for the full GCP Cloud Run/Cloud SQL setup guide (only relevant if that deployment path is the one actually in use).
