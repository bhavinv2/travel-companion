import os
import logging
from datetime import timedelta
from datetime import datetime
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_mail import Mail
from flask_wtf.csrf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv

load_dotenv()

db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()
mail = Mail()
csrf = CSRFProtect()

log = logging.getLogger(__name__)


def _env_bool(name, default):
    """Boolean env var that accepts True/true/1/yes/on (Railway dashboards store lowercase 'true')."""
    v = os.environ.get(name)
    if v is None or v.strip() == '':
        return default
    return v.strip().lower() in ('1', 'true', 'yes', 'on')


def create_app(test_config=None):
    app = Flask(__name__)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    is_production = os.environ.get('FLASK_ENV') == 'production'

    db_url = os.environ.get('DATABASE_URL', 'sqlite:///dev.db')
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)

    # Secret key: never silently fall back to a known value in production.
    secret = os.environ.get('SECRET_KEY') or os.environ.get('FLASK_SECRET_KEY')
    if not secret and not test_config:
        if is_production or db_url.startswith('postgresql://'):
            raise RuntimeError(
                'FLASK_SECRET_KEY (or SECRET_KEY) must be set in production. '
                'Refusing to start with the insecure default.'
            )
        secret = 'dev-secret-key'
        log.warning('Using insecure default SECRET_KEY — development only.')
    app.config['SECRET_KEY'] = secret or 'test-secret-key'

    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['UPLOAD_FOLDER'] = os.environ.get('UPLOAD_FOLDER', 'app/static/uploads')
    # Private uploads (ticket attachments etc.) live OUTSIDE /static and are served via an authorised route.
    app.config['PRIVATE_UPLOAD_FOLDER'] = os.environ.get('PRIVATE_UPLOAD_FOLDER', 'instance/private_uploads')
    app.config['MAX_CONTENT_LENGTH'] = int(os.environ.get('MAX_CONTENT_LENGTH', 16777216))

    # Site / Phase 2 settings
    app.config['SITE_URL'] = os.environ.get('SITE_URL', 'https://connectingdesis.com').rstrip('/')
    app.config['CLAIM_TOKEN_DAYS'] = int(os.environ.get('CLAIM_TOKEN_DAYS', 14))
    # Whether the claim page shows the route/dates of the CS-created post to the person claiming it.
    app.config['CLAIM_SHOW_ROUTE'] = _env_bool('CLAIM_SHOW_ROUTE', True)
    app.config['SUPPORT_EMAIL'] = os.environ.get('SUPPORT_EMAIL', 'support@connectingdesis.com')
    # Shared secret for the scheduler endpoint POST /internal/jobs/run (header X-Jobs-Secret). Unset = disabled.
    app.config['JOBS_SECRET'] = os.environ.get('JOBS_SECRET')
    app.config['RETENTION_DAYS'] = int(os.environ.get('RETENTION_DAYS', 30))
    app.config['RATELIMIT_ENABLED'] = _env_bool('RATELIMIT_ENABLED', True)
    # Optional per-criterion overrides for the matching engine, e.g. {"route": 40, "date": 20}
    try:
        import json as _json
        app.config['MATCH_WEIGHTS'] = _json.loads(os.environ.get('MATCH_WEIGHTS') or '{}')
    except ValueError:
        app.config['MATCH_WEIGHTS'] = {}
        log.warning('MATCH_WEIGHTS is not valid JSON — ignoring')
    # Storage: local (default) or s3 (any S3-compatible bucket)
    app.config['STORAGE_BACKEND'] = os.environ.get('STORAGE_BACKEND', 'local')
    app.config['S3_BUCKET'] = os.environ.get('S3_BUCKET')
    app.config['S3_REGION'] = os.environ.get('S3_REGION')
    app.config['S3_ENDPOINT_URL'] = os.environ.get('S3_ENDPOINT_URL')
    app.config['S3_ACCESS_KEY_ID'] = os.environ.get('S3_ACCESS_KEY_ID')
    app.config['S3_SECRET_ACCESS_KEY'] = os.environ.get('S3_SECRET_ACCESS_KEY')
    app.config['S3_PUBLIC_BASE_URL'] = os.environ.get('S3_PUBLIC_BASE_URL')
    # Mail provider: smtp (Flask-Mail) or sendgrid
    app.config['MAIL_PROVIDER'] = os.environ.get('MAIL_PROVIDER', 'smtp')
    app.config['SENDGRID_API_KEY'] = os.environ.get('SENDGRID_API_KEY')
    # Admin web scraping (vendored fetchall). Teaching in-app needs a desktop: SCRAPER_HEADED_TEACH=True locally only.
    app.config['SCRAPER_ENABLED'] = _env_bool('SCRAPER_ENABLED', True)
    app.config['SCRAPER_HEADED_TEACH'] = _env_bool('SCRAPER_HEADED_TEACH', False)
    app.config['SCRAPER_MAX_WORKERS'] = int(os.environ.get('SCRAPER_MAX_WORKERS', 1))
    app.config['SCRAPER_STALE_MINUTES'] = int(os.environ.get('SCRAPER_STALE_MINUTES', 10))
    app.config['SCRAPER_ROWS_RETENTION_DAYS'] = int(os.environ.get('SCRAPER_ROWS_RETENTION_DAYS', 30))
    app.config['SCRAPER_EXPORT_DIR'] = os.environ.get('SCRAPER_EXPORT_DIR', 'instance/scraper_exports')
    app.config['SCRAPER_SESSION_DIR'] = os.environ.get('SCRAPER_SESSION_DIR', 'instance/scraper_sessions')
    app.config['SCRAPER_TEACH_DEADLINE_SECONDS'] = int(os.environ.get('SCRAPER_TEACH_DEADLINE_SECONDS', 900))
    app.config['SCRAPER_INLINE'] = False            # tests/CLI: execute jobs synchronously
    app.config['SCRAPER_FORCE_AVAILABLE'] = None    # tests: pretend Playwright is (un)available

    # Mail
    app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
    app.config['MAIL_USE_TLS'] = _env_bool('MAIL_USE_TLS', True)
    app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
    app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
    app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER', 'noreply@connectingdesis.com')

    # OAuth
    app.config['GOOGLE_OAUTH_CLIENT_ID'] = os.environ.get('GOOGLE_OAUTH_CLIENT_ID')
    app.config['GOOGLE_OAUTH_CLIENT_SECRET'] = os.environ.get('GOOGLE_OAUTH_CLIENT_SECRET')
    app.config['FACEBOOK_OAUTH_CLIENT_ID'] = os.environ.get('FACEBOOK_OAUTH_CLIENT_ID')
    app.config['FACEBOOK_OAUTH_CLIENT_SECRET'] = os.environ.get('FACEBOOK_OAUTH_CLIENT_SECRET')

    if test_config:
        app.config['RATELIMIT_ENABLED'] = False   # tests opt in explicitly
        app.config.update(test_config)

    if app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgresql://'):
        # Managed Postgres (Cloud SQL, Neon, Railway) needs TLS; a local server usually has ssl=off,
        # so PGSSLMODE=disable makes local development work without weakening the production default.
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
            'connect_args': {'sslmode': os.environ.get('PGSSLMODE', 'require')},
            'pool_pre_ping': True,
        }

    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    mail.init_app(app)
    csrf.init_app(app)

    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = 'info'

    IST = timedelta(hours=5, minutes=30)

    @app.template_filter('ist')
    def _ist(value, fmt='%d %b %Y, %H:%M'):
        """Render a stored UTC datetime in India Standard Time.

        A fixed offset rather than a named zone on purpose: IST has never observed DST, so
        +05:30 is exact, and zoneinfo needs a tz database that is not present on every host
        this runs on.
        """
        if value is None:
            return ''
        return (value + IST).strftime(fmt) + ' IST'

    @app.url_defaults
    def _static_cache_bust(endpoint, values):
        """Stamp every /static URL with the file's mtime.

        Without it a changed stylesheet can sit behind a browser cache for hours, and the
        page you are looking at is not the page that was deployed -- which is impossible to
        tell apart from a bug in the CSS itself.
        """
        if endpoint != 'static' or 'filename' not in values:
            return
        try:
            values['v'] = int(os.stat(os.path.join(app.static_folder, values['filename'])).st_mtime)
        except OSError:
            pass

    from app.models import User
    # importing this registers the flush hook that keeps trip_legs in step with a post's
    # route; matching reads those rows, so it has to be loaded before the first request
    from app.services import legs as _legs  # noqa: F401

    @login_manager.user_loader
    def load_user(user_id):
        user = db.session.get(User, int(user_id))
        # Deactivated accounts lose their session immediately (not only at next login).
        if user and not user.is_active:
            return None
        return user

    # Register blueprints
    from app.routes.main import main_bp
    from app.routes.auth import auth_bp
    from app.routes.trips import trips_bp
    from app.routes.chat import chat_bp
    from app.routes.admin import admin_bp
    from app.routes.blog import blog_bp
    from app.routes.notifications import notifications_bp
    from app.routes.cs import cs_bp
    from app.routes.claim import claim_bp
    from app.routes.files import files_bp
    from app.routes.matches import matches_bp
    from app.routes.imports import imports_bp
    from app.routes.jobs import jobs_bp
    from app.routes.scraper import scraper_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(trips_bp, url_prefix='/api')
    app.register_blueprint(chat_bp)
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(blog_bp)
    app.register_blueprint(notifications_bp, url_prefix='/api/notifications')
    app.register_blueprint(cs_bp, url_prefix='/cs')
    app.register_blueprint(claim_bp)
    app.register_blueprint(files_bp)
    app.register_blueprint(matches_bp)
    app.register_blueprint(imports_bp)
    app.register_blueprint(jobs_bp)
    app.register_blueprint(scraper_bp, url_prefix='/cs/scraper')

    from app import cli
    cli.register(app)

    # ---- i18n: Flask-Babel renders the curated translations server-side; the Google
    # Translate widget stays on as a fallback for strings we have not translated yet.
    from flask_babel import Babel

    def get_locale():
        from flask import request, has_request_context
        if not has_request_context():
            return 'en'
        lang = request.args.get('lang') or request.cookies.get('lang')
        if not lang:
            try:
                from flask_login import current_user
                if getattr(current_user, 'is_authenticated', False):
                    lang = current_user.language_preference
            except Exception:
                lang = None
        lang = (lang or 'en').split('-')[0].lower()
        if not (lang.isalpha() and 2 <= len(lang) <= 3):
            return 'en'
        try:
            from babel import Locale
            Locale.parse(lang)               # unknown codes crash Babel later - fall back now
        except Exception:
            return 'en'
        return lang

    Babel(app, locale_selector=get_locale)

    # Template `_()`: admin overrides saved at /admin/options (app_settings key
    # 'translation_overrides') win over the compiled .mo catalogs - editable without a deploy.
    from flask_babel import gettext as _babel_gettext

    def _tr(s, **kw):
        try:
            from app.services import settings as _settings
            ovr = (_settings.get_setting('translation_overrides', {}) or {}).get(get_locale(), {})
            val = ovr.get(s)
            if val:
                return val % kw if kw else val
        except Exception:
            pass
        return _babel_gettext(s, **kw)

    app.jinja_env.globals.update(_=_tr, gettext=_tr)

    @app.context_processor
    def inject_theme():
        """Active colour theme as CSS custom properties. Falls back to the shipped palette
        if the settings table is not reachable, so a page never renders unstyled."""
        try:
            from app.services import theming
            return {'THEME_CSS': theming.css()}
        except Exception:
            log.warning('Could not load the colour theme; using the stylesheet defaults')
            return {'THEME_CSS': ''}

    @app.context_processor
    def inject_globals():
        from app.models import (CONTACT_TYPE_ICONS, CONTACT_TYPES, CONTACT_TYPE_LABELS,
                                TRIP_ROLES, TRIP_ROLE_LABELS, AGE_GROUPS, AGE_GROUP_LABELS,
                                GENDERS, PREF_GENDERS)
        from app import options
        return {
            'now': datetime.utcnow,
            'CONTACT_TYPE_ICONS': CONTACT_TYPE_ICONS,
            'CONTACT_TYPES': CONTACT_TYPES,
            'CONTACT_TYPE_LABELS': CONTACT_TYPE_LABELS,
            'TRIP_ROLES': TRIP_ROLES,
            'TRIP_ROLE_LABELS': TRIP_ROLE_LABELS,
            'AGE_GROUPS': AGE_GROUPS,
            'AGE_GROUP_LABELS': AGE_GROUP_LABELS,
            'GENDERS': GENDERS,
            'PREF_GENDERS': PREF_GENDERS,
            'OPT': options,
            'CURRENT_LANG': get_locale(),
            'SITE_URL': app.config['SITE_URL'],
            'SUPPORT_EMAIL': app.config['SUPPORT_EMAIL'],
        }

    for folder in (app.config['UPLOAD_FOLDER'], app.config['PRIVATE_UPLOAD_FOLDER'],
                   app.config['SCRAPER_EXPORT_DIR'], app.config['SCRAPER_SESSION_DIR']):
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError:
            log.warning('Could not create folder %s', folder)

    return app
