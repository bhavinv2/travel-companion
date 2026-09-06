# Connecting Desis
.\.venv\Scripts\Activate.ps1
python run.py

A Flask web app that helps Desi travellers find companions on the same route. Phase 2 adds a customer-service
console for posts gathered from Facebook / other sites, a consent-based contact-sharing model and a claim flow.
There is no native mobile app: the site is responsive and is the mobile experience (audited at 320–390 px).
See `../doc/PROJECT_ANALYSIS.md`, `../doc/PHASE2_PLAN_ANALYSIS.md` and `../doc/PHASE2A_CHANGELOG.md`.

## Stack

- **Backend:** Flask 3, Flask-SQLAlchemy, Flask-Login, Flask-Migrate (Alembic), Flask-Mail, Flask-WTF (CSRF)
- **Database:** PostgreSQL in production, SQLite for local dev
- **Auth:** Email/password + Google OAuth (implemented manually in `app/routes/auth.py`)
- **Roles:** an account holds one or more roles. Built-in: `user` (traveller screens), `cs` (customer service, the
  `/cs/` console), `admin` (everything). Admins can define extra roles with one of those three access levels at
  `/admin/options`. Staff accounts land in their console and never see the traveller screens; an account that is
  both traveller and staff can switch views from the user menu.
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
| `SCRAPER_ENABLED` | Admin web scraper at `/cs/scraper` (default True; needs `playwright install chromium`) |
| `SCRAPER_HEADED_TEACH` | Show "Teach in a browser window" — only when the app runs on the admin's own PC |
| `SCRAPER_MAX_WORKERS` / `SCRAPER_STALE_MINUTES` / `SCRAPER_ROWS_RETENTION_DAYS` | Concurrent scrapes per process (1), when a silent job is marked failed (10), how long non-imported scraped rows are kept (30) |
| `SCRAPER_EXPORT_DIR` / `SCRAPER_SESSION_DIR` | Export files and login-session files for scraping |
| `FETCHALL_CHROMIUM_ARGS` | Extra Chromium flags (e.g. `--no-sandbox` in a root container) |

## Admin: accounts, roles and configurable dropdowns

- **Users (`/admin/users`)** — tick any combination of roles per account (traveller + CS, CS + admin, ...);
  **Add account** creates a traveller / CS / admin directly (temporary password shown once, or a set-password
  e-mail).
- **Options & dropdowns (`/admin/options`)** — one tabbed screen for every list that used to be hard-coded:
  languages and post categories (chip editors), "posting for", "connect me to", traveller needs, user roles
  (+ access level), saved in `app_settings` key `options` and read live via `app/options.py` ->
  `get_list(name)` — no deploy needed; "Reset to defaults" restores the built-ins.
  **Airports and airlines live in DB tables** (`airports` seeded with the 8,804 bundled airports by migration
  `39cd7630a97b`; `airlines` seeded with the 993 bundled airlines by `6389d25b1557`): their tabs search the
  full lists and add/remove custom rows, picked up at once by the autocompletes (`/api/airports`,
  `/api/airlines`), route matching (`app/services/locations.py`) and the importer
  (`app/services/airlines.py`; both indexes cached 60 s with a bundled-file fallback while unseeded).

## Notification switches

Every notification and e-mail passes through `app/services/notify.py`. Two levels of control:

- **Admin — `/admin/notifications`**: a master switch that stops **all** notifications site-wide, plus
  **partial** switches by channel (e-mail / in-app) and by kind (match alerts, match introductions,
  connections, chat, announcements, CS alerts, account e-mails). Stored in the `app_settings` table, so it
  applies to every worker immediately; changes are logged. Suppressed match introductions leave the side
  *pending* without flagging CS.
- **Users — `/settings/notifications`**: mute everything, switch off e-mail, or mute individual kinds.
  Account e-mails (verification, password reset) cannot be muted by users.

## Admin web scraper

`/cs/scraper` (admins only) pulls travel-companion requests from other websites using the vendored
[`fetchall`](app/vendor/fetchall/VENDORED.md) scraper:

1. **New recipe** → enter the page URL. The app opens it in a hidden browser and lists any data feed it loads
   (CSV/JSON/XML/tables) — pick one and no teaching is needed.
2. Otherwise **teach** it: on your PC run `python -m fetchall teach <url>` (or, when the app itself runs on your PC
   with `SCRAPER_HEADED_TEACH=True`, click *Teach in a browser window*), then paste/upload the recipe JSON in the
   editor and use *Validate & preview*.
3. **Mapping** — scraped columns are auto-mapped to the post form fields (origin, destination, dates, flight,
   role, languages, contact, …); adjust with a live preview.
4. **Run** (incremental by default; runs in the background, progress polls) → review rows → select single/all →
   **Create posts** (unconfirmed, contact details unconsented — same rules as the Excel import; tick *publish
   now* only when the person already confirmed) → **Export** raw or mapped Excel (the mapped file re-imports at
   `/cs/import`).

Scheduled runs: enable a schedule on the recipe; the jobs endpoint / `flask run-jobs` starts due runs.
CLI: `flask scrape-import-recipe recipes/site.json --name site`, `flask scrape-run site [--max-pages N] [--max-rows N] [--full]`,
`flask scrape-list`, `flask scrape-recover`.

Deploying with scraping needs Chromium in the image — the `Dockerfile` runs `playwright install --with-deps chromium`
(≈400 MB) and runs as a non-root user; give the service ≥1 GB RAM. Without it the console still works for
reviewing/creating posts/exporting and shows "scraping not available".

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
flask set-role you@example.com user,cs # comma-separated role keys (see /admin/options)
flask make-admin you@example.com
flask backfill-locations               # fill origin_/dest_ iata/city/metro on existing posts
flask run-jobs                         # escalation + close departed posts (see Scheduled job)
flask seed-demo-match                  # two demo travellers (user1/user2) whose posts match each other; prints logins
```

## Project layout

```
app/
  __init__.py       # app factory, config, extension init, context globals
  models.py         # SQLAlchemy models (+ status/role/contact-type constants)
  options.py        # shared option lists for forms
  cli.py            # flask management commands
  routes/           # blueprints: main, auth, trips, chat, admin, blog, notifications, cs, claim, files, matches, imports, jobs, scraper
  services/         # locations, contacts, storage, matching, bridge, mailer, importer, jobs, scraper (+ scraper_worker)
  vendor/fetchall/  # vendored "show once, fetch all" scraper (see VENDORED.md)
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
| `/cs/scraper` | admin | web scraper: recipes, detect/teach, mapping, runs, rows → posts, Excel export |
| `/admin/notifications` | admin | stop notifications: all, or partial by channel / kind |
| `/admin/users`, `/admin/users/new` | admin | multi-role assignment, add accounts |
| `/admin/options` | admin | configurable dropdowns: languages, categories, needs, roles, airports, airlines |
| `/switch-view/<traveller\|staff>` | multi-role accounts | flip between the traveller site and the staff console |
| `/settings/notifications` | users | personal notification preferences (mute all, no e-mail, per kind) |
| `/auth/forgot-password`, `/auth/reset/<token>`, `/auth/verify/<token>` | everyone | password reset and e-mail verification |
| `/dashboard` | users | your matches, your posts (modify in place), open requests with filters |
| `/claim/<token>` | invited person | confirm a CS-created post and add contact details with consent |
| `/match/<token>` | matched traveller | the other traveller's consented contact details; contacted / not suitable / report |
| `/api/trip/<id>/matches`, `/api/matches/<id>/notify` | post owner | matches for my post; share my contact & notify both sides |
| `/admin/` | admin | users (roles), listings, feedback, blog |
