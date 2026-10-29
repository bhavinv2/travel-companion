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


class PrefixMiddleware:
    """Serve the whole app under a URL prefix such as /travel-companions, behind a reverse proxy.

    This is the server-rendered equivalent of a router "basename": once SCRIPT_NAME is set, every
    url_for() (routes, static files, redirects, Flask-Login's login redirect, OAuth callback URLs)
    comes out prefixed, so the templates need no per-link changes.

    Two proxy styles are accepted, so the Cloudflare Worker can be written either way:
      * path preserved  -> /travel-companions/dashboard arrives as-is: strip it into SCRIPT_NAME
      * path stripped   -> /dashboard arrives with X-Forwarded-Prefix: /travel-companions
    A request that carries neither (the bare Railway domain, local dev) is passed through
    untouched, which keeps the Railway URL working as a test address.

    public_host: when the prefix is active, the request's host/scheme are set to the public site
    so that absolute URLs (OAuth redirect_uri, sitemap, e-mails) and Flask-WTF's Referer check
    use nriparentservice.com rather than whatever Host the proxy hop presented.
    """

    def __init__(self, wsgi_app, prefix='', public_host='', public_scheme='https', aliases=()):
        self.wsgi_app = wsgi_app
        self.prefix = ('/' + prefix.strip('/')) if prefix and prefix.strip('/') else ''
        self.public_host = (public_host or '').strip()
        self.public_scheme = public_scheme
        # Public paths that sit BESIDE the prefix rather than inside it -- /travel-insurance is
        # its own product and reads wrong nested under /travel-companions. See __call__.
        self.aliases = [('/' + a.strip('/')) for a in aliases if a and a.strip('/')]

    def __call__(self, environ, start_response):
        header = (environ.get('HTTP_X_FORWARDED_PREFIX') or '').strip()
        header = ('/' + header.strip('/')) if header.strip('/') else ''
        prefix = header or self.prefix
        path = environ.get('PATH_INFO', '') or '/'
        active = False
        # Which door this request came in by. Two of them land on byte-identical WSGI environs --
        # /travel-companions/travel-insurance and /travel-insurance both end up with PATH_INFO
        # '/travel-insurance' and SCRIPT_NAME '/travel-companions' -- so the app cannot tell them
        # apart afterwards, and one of them has to redirect to the other.
        environ['app.entry'] = 'root'
        if prefix and (path == prefix or path.startswith(prefix + '/')):
            environ['SCRIPT_NAME'] = (environ.get('SCRIPT_NAME') or '') + prefix
            environ['PATH_INFO'] = path[len(prefix):] or '/'
            environ['app.entry'] = 'prefix'
            active = True
        elif any(path == a or path.startswith(a + '/') for a in self.aliases):
            # An alias is an ENTRY POINT, not a second mount: SCRIPT_NAME still says
            # /travel-companions, so every link, asset and redirect this request renders keeps the
            # one canonical prefix, and the app is not reachable twice at two sets of URLs.
            # PATH_INFO is left alone because /travel-insurance is a real route in this app.
            environ['SCRIPT_NAME'] = (environ.get('SCRIPT_NAME') or '') + prefix
            environ['app.entry'] = 'alias'
            active = True
        elif header:
            environ['SCRIPT_NAME'] = (environ.get('SCRIPT_NAME') or '') + header
            active = True
        if active and self.public_host:
            environ['HTTP_HOST'] = self.public_host
            environ['wsgi.url_scheme'] = self.public_scheme
        return self.wsgi_app(environ, start_response)


def wants_json(request):
    """Whether this request came from a script rather than from somebody navigating.

    Used to decide what an error looks like. Sec-Fetch-Mode is the reliable modern signal and
    every browser that matters sends it; the rest are for older clients and for our own fetch()
    calls, which set X-Requested-With.
    """
    if request.path.startswith('/api/') or '/api/' in request.path:
        return True
    if request.is_json or request.accept_mimetypes.best == 'application/json':
        return True
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return True
    if 'X-CSRFToken' in request.headers:
        return True
    mode = request.headers.get('Sec-Fetch-Mode')
    return bool(mode) and mode != 'navigate'


def _env_bool(name, default):
    """Boolean env var that accepts True/true/1/yes/on (Railway dashboards store lowercase 'true')."""
    v = os.environ.get(name)
    if v is None or v.strip() == '':
        return default
    return v.strip().lower() in ('1', 'true', 'yes', 'on')


from flask import Request as _FlaskRequest  # noqa: E402

# Uploads bigger than MAX_CONTENT_LENGTH, allowed on these screens only. The sales team's workbook
# is 24 MB of mostly empty formatted cells; raising the limit everywhere to take it would let every
# public form accept that much too.
BIG_UPLOADS = {'crm.import_sheet': 64 * 1024 * 1024, 'admin_crm.import_sheet': 64 * 1024 * 1024,
               # Word documents with a zip of their pictures (blog_engine caps each picture and the zip)
               'admin.blog_import': 96 * 1024 * 1024,
               # a video in a blog post (MP4 or WebM)
               'admin.blog_video': 150 * 1024 * 1024}


class AppRequest(_FlaskRequest):
    @property
    def max_content_length(self):
        big = BIG_UPLOADS.get(self.endpoint or '')
        return big if big else super().max_content_length


def create_app(test_config=None):
    app = Flask(__name__)
    app.request_class = AppRequest
    # Optional subpath deployment (https://nriparentservice.com/travel-companions/): see PrefixMiddleware.
    app.config['APP_URL_PREFIX'] = os.environ.get('APP_URL_PREFIX', '').strip()
    app.config['APP_PUBLIC_HOST'] = os.environ.get('APP_PUBLIC_HOST', '').strip()
    # Top-level paths this app answers on besides its prefix. They only ever reach us if the proxy
    # in front routes them here, so listing one costs nothing until that rule exists.
    app.config['APP_ALIAS_PATHS'] = [p for p in (
        os.environ.get('APP_ALIAS_PATHS', '/travel-insurance,/sahayak,/contact-us').split(',')) if p.strip()]
    if test_config:
        for k in ('APP_URL_PREFIX', 'APP_PUBLIC_HOST'):
            if k in test_config:
                app.config[k] = test_config[k]
    app.wsgi_app = PrefixMiddleware(app.wsgi_app, prefix=app.config['APP_URL_PREFIX'],
                                    public_host=app.config['APP_PUBLIC_HOST'],
                                    aliases=app.config['APP_ALIAS_PATHS'])
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    is_production = os.environ.get('FLASK_ENV') == 'production'

    db_url = os.environ.get('DATABASE_URL', 'sqlite:///dev.db')
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)
    # Name the PostgreSQL driver explicitly rather than leaving it to whatever SQLAlchemy
    # defaults to. A bare `postgresql://` means psycopg2 on SQLAlchemy 2.0 and psycopg 3 on 2.1,
    # so an unrelated rebuild picking up the newer version took production down with
    # "No module named 'psycopg'" at import -- every gunicorn worker died before serving a byte.
    # A URL that already names a driver we can import is left exactly as it is.
    if db_url.startswith('postgresql'):
        scheme, _, rest = db_url.partition('://')
        _, _, named = scheme.partition('+')

        def _usable(module):
            try:
                __import__(module)
                return True
            except ImportError:
                return False

        if not named or not _usable(named):
            driver = next((d for d in ('psycopg2', 'psycopg') if _usable(d)), None)
            if driver:
                if named:
                    log.warning('DATABASE_URL asks for %s, which is not installed; using %s.',
                                named, driver)
                db_url = 'postgresql+%s://%s' % (driver, rest)

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
    # Flask-WTF's default is 3600s: a CS agent who opens "New post", takes a call and submits an
    # hour later loses the whole form. The token is still tied to the signed session cookie, so
    # letting it live as long as the session does not weaken CSRF protection.
    _csrf_limit = os.environ.get('WTF_CSRF_TIME_LIMIT')
    app.config['WTF_CSRF_TIME_LIMIT'] = int(_csrf_limit) if _csrf_limit and _csrf_limit.isdigit() else None

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
    # Sales CRM: other websites allowed to post leads to /api/leads (comma separated origins), and
    # the lead source a WhatsApp message from a number we have never seen is filed under
    app.config['CRM_INTAKE_ORIGINS'] = os.environ.get('CRM_INTAKE_ORIGINS', '')
    app.config['WACRM_SOURCE_KEY'] = os.environ.get('WACRM_SOURCE_KEY', 'wa-india')
    app.config['WA_SYNC_INLINE'] = False   # tests: tell the WhatsApp CRM right after the commit, in this thread
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

    @login_manager.unauthorized_handler
    def _unauthorized():
        """What an unauthenticated request gets.

        A page gets the login screen, as before. A fetch() gets 401 and a JSON body, because the
        alternative does real damage: Flask-Login answers with a redirect to auth.login?next=
        <that URL>, the login view writes that into session['next'], and the next sign-in obeys
        it. Every page polls /api/unread-count, so signing in with Google landed people on a
        JSON endpoint -- set by a background poll they never saw.
        """
        from flask import flash, jsonify, redirect, request, url_for

        if wants_json(request):
            return jsonify(error='Please sign in.', authenticated=False), 401
        flash('Please sign in to continue.', 'info')
        # here(), so the prefix survives; no `next` at all for a non-navigation
        from app.services.urls import here
        return redirect(url_for('auth.login', next=here()))

    IST = timedelta(hours=5, minutes=30)
    app.config['IST_OFFSET'] = IST

    @app.template_filter('contact_display')
    def _contact_display(value, ctype):
        """{{ value|contact_display(type) }} -- see services/contacts.display."""
        from app.services import contacts
        return contacts.display(ctype, value)

    @app.template_filter('ist')
    def _ist(value, fmt='%d %b %Y, %H:%M'):
        """Render a stored UTC datetime in India Standard Time, labelled.

        A fixed offset rather than a named zone on purpose: IST has never observed DST, so
        +05:30 is exact, and zoneinfo needs a tz database that is not present on every host
        this runs on.

        Every timestamp in the database is UTC, because that is the only sane thing to store.
        Nobody reading this app is in UTC, though: the team and almost every traveller are on
        IST, so a row that says 18:40 for something that happened at midnight is not a small
        inaccuracy, it is a wrong answer. Storage stays UTC; display is converted here.
        """
        if value is None:
            return ''
        # the zone the header's clock switch chose (services/clock.py) -- India unless somebody picked another
        from app.services import clock
        return clock.fmt(value, fmt) + ' ' + clock.label(value)

    @app.template_filter('istd')
    def _istd(value, fmt='%Y-%m-%d'):
        """The same conversion for a date-only display.

        No "IST" suffix: a bare date does not need a clock label, and the conversion still
        matters -- anything recorded after 18:30 UTC belongs to the NEXT day in India, so
        printing the raw UTC date is off by one for a quarter of every day.

        Pass a plain `date` (a trip's departure, a policy's start) and it is returned untouched:
        those are calendar dates with no time zone, and shifting them would invent a change
        nobody made.
        """
        if value is None:
            return ''
        if not isinstance(value, datetime):
            return value.strftime(fmt)
        from app.services import clock
        return clock.fmt(value, fmt)

    # the header's clock switch, and any template that prints a time (services/clock.py)
    @app.template_global('CLOCK')
    def _clock_switcher():
        from app.services import clock
        return clock.switcher()

    @app.template_global('LOCAL')
    def _clock_local(value):
        """A stored UTC datetime as the chosen zone's wall clock -- for .strftime in a template."""
        from app.services import clock
        return clock.local(value)

    @app.template_global('TZ')
    def _clock_label(value=None):
        """What the chosen zone is called now (or at `value`): IST, EDT, PST, UTC."""
        from app.services import clock
        return clock.label(value)

    # Whether to send http traffic to https. On by default in production; a deployment that
    # genuinely terminates TLS somewhere we cannot see can turn it off rather than loop.
    app.config['FORCE_HTTPS'] = _env_bool('FORCE_HTTPS', is_production)

    @app.before_request
    def _one_address_over_https():
        """Two rules about the address bar, both of which only ever bite in production.

        https: the site handles logins, admin sessions and people's phone numbers. Railway
        terminates TLS and ProxyFix reads X-Forwarded-Proto, so request.is_secure is the truth
        about the original hop. Localhost is exempt because there is no certificate there.

        One address per page: /travel-insurance answers beside the prefix as its own front door,
        and the prefixed spelling of it answers too, because the app really does route that path.
        Two addresses for one page splits its search ranking and makes every analytics number
        half of itself. The bare one is canonical -- it is what the canonical tag, the sitemap and
        every printed link already say -- so the prefixed one redirects to it, permanently.
        """
        from flask import redirect, request

        if app.config.get('TESTING'):
            return None
        host = (request.host or '').split(':')[0].lower()
        local = host in ('localhost', '127.0.0.1', '0.0.0.0', '[::1]')

        if app.config['FORCE_HTTPS'] and not request.is_secure and not local:
            return redirect(request.url.replace('http://', 'https://', 1), code=301)

        if request.environ.get('app.entry') == 'prefix' and request.method in ('GET', 'HEAD'):
            aliases = app.config.get('APP_ALIAS_PATHS') or []
            path = request.path
            for alias in aliases:
                alias = '/' + alias.strip('/')
                if path == alias or path.startswith(alias + '/'):
                    target = path + (('?' + request.query_string.decode('latin-1'))
                                     if request.query_string else '')
                    return redirect(target, code=301)
        return None

    @app.after_request
    def _hsts(response):
        """Tell the browser not to try http again. Only on a connection that is already secure --
        sending it over http would be advice nobody should take from an unauthenticated hop."""
        from flask import request

        if request.is_secure and app.config.get('FORCE_HTTPS') and not app.config.get('TESTING'):
            response.headers.setdefault('Strict-Transport-Security',
                                        'max-age=31536000; includeSubDomains')
        return response

    @app.before_request
    def _signed_in_guard():
        """Before the page guard: a browser that was signed out elsewhere or left idle is signed out here, and two-step
        sign-in is asked for before anything else opens (services/signin.py)."""
        from flask import g
        from app.services import signin
        # the person is read afresh for every request: an app context that outlives one (the tests keep one open)
        # must not hand the next request the previous one's user
        g.pop('_login_user', None)
        return signin.guard()

    @app.before_request
    def _page_guard():
        """Stop a staff member opening a page their roles do not give them.

        Hiding a link is not access control -- the URL is still there, and a bookmark or a
        colleague's pasted link reaches it. This runs before every request, so the menu and the
        door read the same roles (services/access.py).
        """
        from app.services import access
        return access.guard()

    @app.after_request
    def _whats_new_seen(response):
        """Move this person's "seen" mark on when they open a list the widget counts by time.

        After the request rather than inside the four routes, so the rule lives in one place
        (whats_new.SEEN_BY_ENDPOINT) and a fifth list is one line there. Only a successful GET:
        a failed or redirected request has not shown anybody anything.
        """
        from flask import request
        from flask_login import current_user
        from app.services import whats_new

        key = whats_new.SEEN_BY_ENDPOINT.get(request.endpoint or '')
        if not key or request.method != 'GET' or response.status_code != 200:
            return response
        if not getattr(current_user, 'is_authenticated', False) or not current_user.is_cs:
            return response
        try:
            whats_new.mark_seen(current_user, key)
            db.session.commit()
        except Exception:                          # noqa: BLE001 -- a mark is not worth a 500
            db.session.rollback()
        return response

    from flask_wtf.csrf import CSRFError

    @app.errorhandler(CSRFError)
    def _csrf_error(e):
        """Send the user back to the form with a message instead of a bare 400 page."""
        from flask import flash, jsonify, redirect, request

        # fetch() calls send the token as a header; a redirect would hand them an HTML page with 200
        if wants_json(request):
            return jsonify(error='Your session expired. Please reload the page and try again.'), 400
        flash('Your session expired before the form was sent. Please fill it in again and submit.',
              'warning')
        back = request.referrer
        if not back or not back.startswith(request.host_url):
            back = request.url
        return redirect(back)

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
        # "<id>" or "<id>.<session version>" (User.get_id): a raised version signs every older session out
        uid, _, version = str(user_id).partition('.')
        if not uid.isdigit():
            return None
        user = db.session.get(User, int(uid))
        # Deactivated accounts lose their session immediately (not only at next login).
        if user is None or not user.is_active:
            return None
        if (user.session_version or 0) != (int(version) if version.isdigit() else 0):
            return None
        return user

    # Register blueprints
    from app.routes.main import main_bp
    from app.routes.insurance import insurance_bp
    from app.routes.sahayak import sahayak_bp
    from app.routes.auth import auth_bp
    from app.routes.trips import trips_bp
    from app.routes.chat import chat_bp
    from app.routes.admin import admin_bp
    from app.routes import admin_blog  # noqa: F401 -- adds the blog studio's screens to admin_bp
    from app.routes.blog import blog_bp
    from app.routes.notifications import notifications_bp
    from app.routes.cs import cs_bp
    from app.routes.claim import claim_bp
    from app.routes.files import files_bp
    from app.routes.matches import matches_bp
    from app.routes.imports import imports_bp
    from app.routes.jobs import jobs_bp
    from app.routes.scraper import scraper_bp
    from app.routes.saved_views import saved_bp
    from app.routes.favourites import my_bp
    from app.routes.crm import crm_bp, crm_public_bp
    from app.routes import crm_setup  # noqa: F401 -- Set-up -> Pipelines: its rules are on crm_bp, before it is registered
    from app.routes import crm_wa  # noqa: F401 -- Quick replies, WhatsApp connection, What goes out by itself: rules on crm_bp, before it is registered
    from app.routes import crm_people  # noqa: F401 -- Contacts, Find a person, downloads and imports: rules on crm_bp, before it is registered
    from app.routes import crm_forecast  # noqa: F401 -- Forecast and Targets: rules on crm_bp, before it is registered
    from app.routes import crm_control  # noqa: F401 -- Recycle bin, being away, what a stage needs: rules on crm_bp, before it is registered
    from app.routes import crm_family  # noqa: F401 -- Families, merge, files: rules on crm_bp, before it is registered
    from app.routes import crm_quotes, crm_views, crm_report_builder, crm_lead_ads  # noqa: F401 -- Quotes, saved views, report builder, lead ads: rules on crm_bp / crm_public_bp, before they are registered
    from app.routes import crm_activities  # noqa: F401 -- Tasks, Calendar, e-mail: rules on crm_bp / crm_public_bp, before they are registered
    from app.routes import crm_rules  # noqa: F401 -- Automation rules, scoring, AI on the lead page, offers consent: rules on crm_bp, before it is registered
    from app.routes import crm_integrations  # noqa: F401 -- Set-up > Integrations and tawk.to's webhook: rules on crm_bp / crm_public_bp, before they are registered
    from app.routes import crm_inbox  # noqa: F401 -- Inbox > All conversations: rules on crm_bp, before it is registered
    from app.routes import channels as channels_routes  # noqa: F401 -- Set-up > Channels (WhatsApp numbers) and Meta's webhook for them: rules on crm_bp / crm_public_bp, before they are registered

    from app.services import crm_access, crm_audit, crm_bin, crm_scope
    crm_bin.register()          # removed leads are hidden everywhere (the recycle bin)
    crm_access.register()       # a role may see only its own / its team's leads
    crm_audit.register()        # the history of every change to a lead or a person
    crm_scope.register()        # every workspace has its own CRM: leads, contacts, pipelines, numbers
    from app.services import crm_rules as _crm_rules
    _crm_rules.register()       # automation rules and lead scores: worked out after each save's commit
    app.register_blueprint(main_bp)
    app.register_blueprint(insurance_bp)
    app.register_blueprint(sahayak_bp)
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
    app.register_blueprint(saved_bp)
    app.register_blueprint(my_bp)
    app.register_blueprint(crm_bp, url_prefix='/cs/crm')
    # the same Sales CRM inside the admin portal, with the admin menu (see routes/crm.py)
    app.register_blueprint(crm_bp, url_prefix='/admin/crm', name='admin_crm')
    app.register_blueprint(crm_public_bp)
    # workspaces, roles and teams; WhatsApp (the WhatsApp CRM inside the portal)
    from app.routes.workspace import workspace_bp
    from app.routes.messaging import messaging_bp
    app.register_blueprint(workspace_bp)
    from app.routes.security import security_bp
    app.register_blueprint(security_bp)
    app.register_blueprint(messaging_bp)
    # the Promotion dashboard's boxes and the Dashboard designer (/promotion/...)
    from app.routes.marketing import marketing_bp
    app.register_blueprint(marketing_bp)

    from app import cli
    cli.register(app)

    # A global, not a context value: the delete macros (admin/_hard_delete.html) are imported without
    # context, and must hide themselves from everybody but a Super admin wherever they are used.
    def _can_delete():
        from flask_login import current_user
        from app.services import access
        return access.can(current_user, 'delete_records')
    app.jinja_env.globals['CAN_DELETE'] = _can_delete
    from app.services import role_rights
    app.jinja_env.globals['LOOK_ONLY_HERE'] = role_rights.look_only_here     # the page heading's notice
    from app.services import crm_mask                                           # hidden contact details
    app.jinja_env.globals.update(MASKED=crm_mask.hidden, MASK_PHONE=crm_mask.phone, MASK_EMAIL=crm_mask.email)

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
        from flask_login import current_user
        from app.services import (access, ads, analytics, contact_form, cs_access,
                                  insurance_countries, nav_badges, nri_services, offices, phone,
                                  portals, products, tawk, urls, wacrm_team, whats_new)
        return {
            # Site-wide GA4 / GTM / second Ads account / Search Console verification -- see
            # app/services/analytics.py and _analytics.html. ADS_ACCOUNT_ID reuses ads.py's own
            # account+enabled check (the travel-insurance page's conversion tracking) so that
            # account is only ever initialised once, from here, instead of also inline on that
            # page.
            'ANALYTICS_ENABLED': analytics.enabled(),
            'GA4_ID': analytics.ga4_id(),
            'GTM_ID': analytics.gtm_id(),
            'ADS2_ID': analytics.ads2_id(),
            'GOOGLE_SITE_VERIFICATION': analytics.site_verification(),
            'ADS_ACCOUNT_ID': ads.account_id() if ads.enabled() else '',
            # the tawk.to chat bubble on the public pages (services/tawk.widget_here, _tawk.html)
            'TAWK_WIDGET': tawk.widget_here(),
            # Templates use this for "today" in date inputs. Between 18:30 and 00:00 IST,
            # utcnow() is still yesterday in India, which would let somebody pick a date that
            # has already gone or block one that has not.
            'now': lambda: datetime.utcnow() + IST,
            'INSURANCE_DESTINATIONS': insurance_countries,
            # The staff menu and "may this person open that page", from workspace roles.
            # Functions, so a public page never runs the queries behind them.
            'STAFF_NAV': lambda active=None: access.nav(current_user, active),
            'CAN': lambda page: access.can(current_user, page),
            'TABS_FOR': lambda page: access.tabs_for(page),
            'WORKSPACE': lambda: access.current_workspace(current_user),
            # a workspace's business WhatsApp number: {'phone', 'state': live / planned / none}
            'WA_NUMBER': lambda ws: wacrm_team.number_of(ws),
            # the account menu's "Working as": the roles one can take, and the one taken (None: everything)
            'ROLE_CHOICES': lambda: access.roles_to_act(current_user),
            'IST_OFFSET': timedelta(hours=5, minutes=30),
            'ACTING': lambda: access.acting_role(current_user),
            'CS_ACCESS': cs_access,
            # The function, not the counts: only a staff sidebar calls it, so a public page
            # never runs the queries behind it.
            'NAV_BADGES': nav_badges.unread,
            # the floating "what's new" button on staff pages; same reasoning as above
            'WHATS_NEW': whats_new.safe_snapshot,
            'PORTAL_SWITCHER': portals.switcher,
            'NRI_SERVICES': nri_services.resolved(),
            # For linking TO /travel-insurance or /sahayak: those answer beside the app's prefix,
            # so url_for would offer the in-prefix address instead of the one they are known by.
            'public_url': urls.public_url,
            # for the paths Python did not build with url_for -- a stored notification
            # link, a `base` passed as a string -- and for "where am I" in a next field
            'app_url': urls.app_url,
            # the public product switcher under the logo
            'PRODUCTS': products,
            # the one definition of what "contact us" asks for, shared by the popup and /contact
            'CONTACT_FORM': contact_form,
            # one dialling-code list and one validity rule, for every form that asks
            'PHONE': phone,
            # every published WhatsApp number, optionally for one page. A list, so a
            # country can be added in the admin screen rather than in the markup.
            'WA_NUMBERS': offices.numbers,
            'WA_GREETING': offices.greeting,
            # which product this page belongs to, so the footer's one chooser shows the numbers
            # for the page it is on rather than every number on the site
            'WA_SITE': offices.current_site,
            # the published support address for a page, from the same admin screen as the
            # numbers. '' when none is published, so a caller can fall back rather than print
            # a mailbox nobody is watching.
            'CONTACT_EMAIL': offices.email,
            'here': urls.here,
            'NRI_SOCIAL': nri_services.SOCIAL,
            'INSURANCE_PARTNER_NAME': nri_services.INSURANCE_PARTNER_NAME,
            'INSURANCE_PARTNER_URL': nri_services.INSURANCE_PARTNER_URL,
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
            # the address published in Admin -> Landing page for this page, falling back to the
            # configured one -- not the configured one outright, which no screen could change
            'SUPPORT_EMAIL': offices.support_address(),
        }

    for folder in (app.config['UPLOAD_FOLDER'], app.config['PRIVATE_UPLOAD_FOLDER'],
                   app.config['SCRAPER_EXPORT_DIR'], app.config['SCRAPER_SESSION_DIR']):
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError:
            log.warning('Could not create folder %s', folder)

    return app
