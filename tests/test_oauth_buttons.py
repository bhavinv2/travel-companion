"""Social sign-in buttons appear only for providers that are actually configured.

A button for an unconfigured provider is a dead end: auth.google_login / facebook_login just
flash "not configured" and bounce back, so it must not be shown at all.
"""


def _make(tmp_path, **cfg):
    from app import create_app
    base = {'TESTING': True, 'WTF_CSRF_ENABLED': False, 'SQLALCHEMY_DATABASE_URI': 'sqlite://',
            'UPLOAD_FOLDER': str(tmp_path / 'u'), 'PRIVATE_UPLOAD_FOLDER': str(tmp_path / 'p'),
            'MAIL_PASSWORD': None}
    base.update(cfg)
    app = create_app(base)
    from app import db as _db
    with app.app_context():
        _db.create_all()
    return app


def test_no_buttons_when_neither_provider_is_configured(tmp_path):
    app = _make(tmp_path, GOOGLE_OAUTH_CLIENT_ID=None, FACEBOOK_OAUTH_CLIENT_ID=None)
    for path in ('/auth/login', '/auth/register'):
        html = app.test_client().get(path).data.decode()
        assert 'Continue with Google' not in html and 'Continue with Facebook' not in html
        # check the markup, not the stylesheet (which always defines .social-btns)
        assert '<div class="social-btns">' not in html
        assert 'or sign in with email' not in html and 'or sign up with email' not in html


def test_only_the_configured_provider_is_offered(tmp_path):
    app = _make(tmp_path, GOOGLE_OAUTH_CLIENT_ID='g-id', FACEBOOK_OAUTH_CLIENT_ID=None)
    for path in ('/auth/login', '/auth/register'):
        html = app.test_client().get(path).data.decode()
        assert 'Continue with Google' in html
        assert 'Continue with Facebook' not in html


def test_both_pages_offer_both_providers_when_configured(tmp_path):
    """Register used to offer Google only, while login offered both."""
    app = _make(tmp_path, GOOGLE_OAUTH_CLIENT_ID='g-id', FACEBOOK_OAUTH_CLIENT_ID='f-id')
    for path in ('/auth/login', '/auth/register'):
        html = app.test_client().get(path).data.decode()
        assert 'Continue with Google' in html, path
        assert 'Continue with Facebook' in html, path


def test_callback_urls_follow_the_deployment(tmp_path):
    """Whatever host/prefix the app is reached on is what Google/Facebook must whitelist."""
    app = _make(tmp_path, GOOGLE_OAUTH_CLIENT_ID='g-id', FACEBOOK_OAUTH_CLIENT_ID='f-id',
                APP_URL_PREFIX='/travel-companions', APP_PUBLIC_HOST='nriparentservice.com')
    c = app.test_client()
    from urllib.parse import parse_qs, urlparse
    for provider, expected in (('google', '/auth/google/authorized'),
                               ('facebook', '/auth/facebook/authorized')):
        r = c.get(f'/travel-companions/auth/{provider}')
        assert r.status_code == 302
        uri = parse_qs(urlparse(r.headers['Location']).query)['redirect_uri'][0]
        assert uri == f'https://nriparentservice.com/travel-companions{expected}', uri
