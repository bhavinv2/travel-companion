import os
import logging
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
    app.config['CLAIM_SHOW_ROUTE'] = os.environ.get('CLAIM_SHOW_ROUTE', 'True') == 'True'
    app.config['SUPPORT_EMAIL'] = os.environ.get('SUPPORT_EMAIL', 'support@connectingdesis.com')
    # Shared secret for the scheduler endpoint POST /internal/jobs/run (header X-Jobs-Secret). Unset = disabled.
    app.config['JOBS_SECRET'] = os.environ.get('JOBS_SECRET')
    app.config['RETENTION_DAYS'] = int(os.environ.get('RETENTION_DAYS', 30))
    app.config['RATELIMIT_ENABLED'] = os.environ.get('RATELIMIT_ENABLED', 'True') == 'True'
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

    # Mail
    app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
    app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'True') == 'True'
    app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
    app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
    app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER', 'noreply@connectingdesis.com')

    # OAuth
    app.config['GOOGLE_OAUTH_CLIENT_ID'] = os.environ.get('GOOGLE_OAUTH_CLIENT_ID')
    app.config['GOOGLE_OAUTH_CLIENT_SECRET'] = os.environ.get('GOOGLE_OAUTH_CLIENT_SECRET')

    if test_config:
        app.config['RATELIMIT_ENABLED'] = False   # tests opt in explicitly
        app.config.update(test_config)

    if app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgresql://'):
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
            'connect_args': {'sslmode': 'require'},
            'pool_pre_ping': True,
        }

    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    mail.init_app(app)
    csrf.init_app(app)

    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = 'info'

    from app.models import User

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

    from app import cli
    cli.register(app)

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
            'SITE_URL': app.config['SITE_URL'],
            'SUPPORT_EMAIL': app.config['SUPPORT_EMAIL'],
        }

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['PRIVATE_UPLOAD_FOLDER'], exist_ok=True)

    return app
