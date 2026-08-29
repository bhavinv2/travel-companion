# Connecting Desis

A Flask web app that helps Desi travellers find companions on the same route. Phase 2 adds a customer-service
console for posts gathered from Facebook / other sites, a consent-based contact-sharing model and a claim flow.
There is no native mobile app: the site is responsive and is the mobile experience (audited at 320–390 px).
See `../doc/PROJECT_ANALYSIS.md`, `../doc/PHASE2_PLAN_ANALYSIS.md` and `../doc/PHASE2A_CHANGELOG.md`.

## Stack

- **Backend:** Flask 3, Flask-SQLAlchemy, Flask-Login, Flask-Migrate (Alembic), Flask-Mail, Flask-WTF (CSRF)
- **Database:** PostgreSQL in production, SQLite for local dev
- **Auth:** Email/password + Google OAuth (implemented manually in `app/routes/auth.py`)
- **Roles:** `user`, `cs` (customer service — can use `/cs/`), `admin` (everything)
- **Server:** Gunicorn
- **File uploads:** local disk — public images under `app/static/uploads`, private documents (ticket attachments)
  under `instance/private_uploads` served via `/files/private/<key>` to the owner/CS only. `app/services/storage.py`
  is the seam for moving to GCS/S3 (see `SETUP.md`).

## Deployment

**Live/production deploys run on [Railway](https://railway.app)** from the `Procfile`. Railway provides Postgres
(`DATABASE_URL`) and `PORT`; secrets live in the project's Variables tab. `Dockerfile` + `cloudbuild.yaml` are an
alternate Google Cloud Run path (see `SETUP.md`).

> The app **refuses to start in production without `FLASK_SECRET_KEY`** (or `SECRET_KEY`). Set it before deploying.

To deploy: push to `main`; run `flask db upgrade` (and once, `flask backfill-locations`) against production.

## Database

- Prod: PostgreSQL via `DATABASE_URL` (`postgres://` is rewritten to `postgresql://`, `sslmode=require` applied).
- Dev: SQLite `sqlite:///dev.db` when `DATABASE_URL` is unset.
- Migrations: `flask db upgrade` applies; `flask db migrate -m "..."` generates after editing `app/models.py`.

## Environment variables

Copy `.env.example` to `.env`.

| Variable | Purpose |
|---|---|
| `FLASK_SECRET_KEY` | Session/CSRF signing key — **required in production** |
| `FLASK_ENV` | `development` or `production` |
| `DATABASE_URL` | Postgres URL in prod; unset → SQLite |
| `GOOGLE_OAUTH_CLIENT_ID` / `_SECRET` | Google login |
| `MAIL_*` | Outgoing e-mail (skipped if `MAIL_PASSWORD` unset) |
| `UPLOAD_FOLDER` / `PRIVATE_UPLOAD_FOLDER` | Public / private upload locations |
| `MAX_CONTENT_LENGTH` | Max upload size (bytes) |
| `SITE_URL` | Absolute site URL used in e-mails / links |
| `SUPPORT_EMAIL` | Shown on help/legal/claim pages |
| `CLAIM_TOKEN_DAYS` | Validity of claim links (default 14) |
| `CLAIM_SHOW_ROUTE` | Show route/dates on the claim page (default True) |
| `JOBS_SECRET` | Enables `POST /internal/jobs/run` (header `X-Jobs-Secret`) for the escalation/housekeeping job; unset = disabled |
| `RETENTION_DAYS` | Days after departure before ticket attachments are deleted (default 30) |
| `RATELIMIT_ENABLED` | In-process rate limiting on auth/write endpoints (default True) |
| `MATCH_WEIGHTS` | JSON overrides for matching weights, e.g. `{"route": 40, "flight": 10}` |
| `STORAGE_BACKEND` | `local` (default) or `s3` — with `S3_BUCKET`, `S3_REGION`, `S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_PUBLIC_BASE_URL` (requires `pip install boto3`) |
| `MAIL_PROVIDER` | `smtp` (default, Flask-Mail) or `sendgrid` with `SENDGRID_API_KEY` |

## Scheduled job

Run every ~15 minutes from an external scheduler (Railway cron service, Cloud Scheduler, GitHub Actions):

```bash
curl -X POST -H "X-Jobs-Secret: $JOBS_SECRET" https://<host>/internal/jobs/run
# or, from a shell with the app installed:
flask run-jobs
```

It escalates matches where a notified side has been silent (2 h / 12 h / 24 h depending on days to departure),
closes posts whose departure date has passed, and applies retention (attachments after `RETENTION_DAYS`,
never-confirmed CS posts after departure, stale claim tokens). `GET /healthz` is available for platform health checks.

## Running locally

```bash
python -m venv venv
venv\Scripts\activate            # source venv/bin/activate on Mac/Linux
pip install -r requirements.txt pytest
copy .env.example .env           # then edit

set FLASK_APP=run.py             # export on Mac/Linux
flask db upgrade
python run.py                    # http://localhost:5001
pytest -q tests
```

## Management commands

```bash
flask set-role you@example.com cs      # user | cs | admin
flask make-admin you@example.com
flask backfill-locations               # fill origin_/dest_ iata/city/metro on existing posts
flask run-jobs                         # escalation + close departed posts (see Scheduled job)
```

## Project layout

```
app/
  __init__.py       # app factory, config, extension init, context globals
  models.py         # SQLAlchemy models (+ status/role/contact-type constants)
  options.py        # shared option lists for forms
  cli.py            # flask management commands
  routes/           # blueprints: main, auth, trips, chat, admin, blog, notifications, cs, claim, files, matches
  services/         # locations (IATA/metro), contacts, storage, matching (scores), bridge (notify), mailer
  static/           # CSS/JS/uploads; airports.json / airlines.json reference data
  templates/        # Jinja templates (cs/, claim/, admin/, auth/, pages/, trips/, chat/)
migrations/         # Alembic migrations
tests/              # pytest suite (in-memory SQLite)
run.py              # local dev entrypoint
Procfile / Dockerfile / cloudbuild.yaml   # deployment
SETUP.md            # GCP walkthrough (note: local port is 5001, and migrations/ already exists — skip `flask db init`)
```

## Key URLs

| URL | Who | What |
|---|---|---|
| `/` | everyone | landing, post/search form, my trips, carousel |
| `/trips` | everyone | all open posts |
| `/connections`, `/inbox` | users | connection requests, chat |
| `/cs/` | cs/admin | queues (needs action, departing soon, new, repeats, awaiting claim, closed) |
| `/cs/posts`, `/cs/posts/new`, `/cs/posts/<id>` | cs/admin | intake list / form / detail with claim link & actions |
| `/cs/posts/<id>/matches`, `/cs/matches` | cs/admin | ranked matches with notify / intro text / dismiss; match queue |
| `/cs/import` | cs/admin | Excel/CSV import (scraper-compatible) with preview and de-duplication |
| `/cs/metrics` | cs/admin | claim rate, time-to-match, % manual, connected/escalation rates, weight-tuning hints |
| `/auth/forgot-password`, `/auth/reset/<token>`, `/auth/verify/<token>` | everyone | password reset and e-mail verification |
| `/dashboard` | users | your matches, your posts (modify in place), open requests with filters |
| `/claim/<token>` | invited person | confirm a CS-created post and add contact details with consent |
| `/match/<token>` | matched traveller | the other traveller's consented contact details; contacted / not suitable / report |
| `/api/trip/<id>/matches`, `/api/matches/<id>/notify` | post owner | matches for my post; share my contact & notify both sides |
| `/admin/` | admin | users (roles), listings, feedback, blog |
