"""Subpath deployment: https://nriparentservice.com/travel-companions/ (see PrefixMiddleware).

The bare Railway domain must keep working unprefixed as a test address, and under the prefix every
generated URL — page links, static assets, redirects, OAuth callbacks, absolute URLs — must carry it.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db as _db  # noqa: E402

PREFIX = '/travel-companions'
HOST = 'nriparentservice.com'


@pytest.fixture()
def papp(tmp_path):
    app = create_app({
        'TESTING': True, 'WTF_CSRF_ENABLED': False, 'SQLALCHEMY_DATABASE_URI': 'sqlite://',
        'UPLOAD_FOLDER': str(tmp_path / 'uploads'), 'PRIVATE_UPLOAD_FOLDER': str(tmp_path / 'private'),
        'MAIL_PASSWORD': None, 'SITE_URL': f'https://{HOST}{PREFIX}',
        'APP_URL_PREFIX': PREFIX, 'APP_PUBLIC_HOST': HOST,
    })
    with app.app_context():
        _db.create_all()
        from app.services import settings, locations, airlines
        settings.clear_cache(); locations.reset_cache(); airlines.reset_cache()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def pclient(papp):
    return papp.test_client()


def test_prefixed_request_renders_prefixed_links_and_assets(pclient):
    r = pclient.get(f'{PREFIX}/')
    assert r.status_code == 200
    html = r.data.decode()
    assert f'href="{PREFIX}/static/css/' in html
    assert f'src="{PREFIX}/static/js/app-root.js' in html
    assert f'<meta name="app-root" content="{PREFIX}">' in html      # what the browser-side shim reads
    assert f'href="{PREFIX}/auth/login"' in html or f'"{PREFIX}/auth/login"' in html
    assert 'href="/static/' not in html and "url('/static/" not in html and 'url("/static/' not in html
    # the static file is actually served at the prefixed path
    assert pclient.get(f'{PREFIX}/static/js/app-root.js').status_code == 200


def test_bare_railway_domain_still_works_without_a_prefix(pclient):
    """The Railway URL stays usable as a test address: nothing is prefixed there."""
    r = pclient.get('/', base_url='https://travel-companion-production-261c.up.railway.app')
    assert r.status_code == 200
    html = r.data.decode()
    assert 'href="/static/css/' in html
    assert '<meta name="app-root" content="">' in html
    assert f'href="{PREFIX}/static/' not in html and f'href="{PREFIX}/auth/' not in html
    # ...but canonical still names the public site, so the test domain is never what gets indexed
    assert f'<link rel="canonical" href="https://{HOST}{PREFIX}/">' in html


def test_proxy_that_strips_the_path_can_announce_it_with_a_header(pclient):
    r = pclient.get('/', headers={'X-Forwarded-Prefix': PREFIX})
    assert r.status_code == 200
    assert f'href="{PREFIX}/static/css/' in r.data.decode()


def test_login_redirect_and_deep_links_keep_the_prefix(pclient):
    # a protected deep link, opened directly (browser refresh / pasted URL)
    r = pclient.get(f'{PREFIX}/dashboard')
    assert r.status_code == 302
    assert r.headers['Location'].startswith(f'{PREFIX}/auth/login')
    assert f'next={PREFIX.replace("/", "%2F")}%2Fdashboard' in r.headers['Location']
    # every route is server-rendered, so nested paths need no client-side fallback
    for path in ('/auth/login', '/auth/register', '/trips', '/help', '/privacy', '/terms'):
        assert pclient.get(PREFIX + path).status_code == 200, path


def test_absolute_urls_use_the_public_site_not_the_proxy_hop(papp):
    """OAuth redirect_uri, canonical/og URLs and e-mails must say nriparentservice.com."""
    # simulate the Worker -> Railway hop: Host is the Railway domain, path carries the prefix
    client = papp.test_client()
    r = client.get(f'{PREFIX}/', base_url='https://travel-companion-production-261c.up.railway.app')
    html = r.data.decode()
    assert f'<link rel="canonical" href="https://{HOST}{PREFIX}/">' in html
    assert f'content="https://{HOST}{PREFIX}/static/img/landing/l2.jpg' in html      # og:image, no double prefix
    # Google OAuth redirect_uri comes out of url_for(_external=True) inside a real request
    r = client.get(f'{PREFIX}/auth/google', base_url='https://travel-companion-production-261c.up.railway.app')
    assert r.status_code == 302 and 'accounts.google.com' in r.headers.get('Location', '')
    from urllib.parse import parse_qs, urlparse
    redirect_uri = parse_qs(urlparse(r.headers['Location']).query)['redirect_uri'][0]
    assert redirect_uri == f'https://{HOST}{PREFIX}/auth/google/authorized'


def test_sitemap_and_robots_point_at_the_prefixed_site(pclient):
    xml = pclient.get(f'{PREFIX}/sitemap.xml').data.decode()
    assert f'<loc>https://{HOST}{PREFIX}/</loc>' in xml
    assert f'<loc>https://{HOST}{PREFIX}/trips</loc>' in xml
    assert f'https://{HOST}{PREFIX}/sitemap.xml' in pclient.get(f'{PREFIX}/robots.txt').data.decode()


def test_api_calls_work_under_the_prefix(pclient):
    r = pclient.get(f'{PREFIX}/api/airports?q=hyd')
    assert r.status_code == 200 and r.is_json
    # and the unprefixed path is NOT served when a prefix is configured and the path lacks it —
    # it is passed through untouched, which is exactly what the Railway test domain needs
    assert pclient.get('/api/airports?q=hyd').status_code == 200


# ---------------------------------------------------------------------------
# Sibling entry points (/travel-insurance)
# ---------------------------------------------------------------------------
# Travel insurance is its own product, so its public address sits beside the companion prefix
# rather than inside it. The middleware treats such a path as an entry point, not a second mount:
# the page answers there, but every link it renders still carries the one canonical prefix, so the
# whole app never becomes reachable at two sets of URLs.

ALIAS = '/travel-insurance'


def test_the_insurance_page_answers_on_its_own_top_level_path(pclient):
    r = pclient.get(ALIAS)
    assert r.status_code == 200
    assert 'Travel Insurance for Every Journey' in r.data.decode()


def test_the_same_page_still_answers_inside_the_prefix(pclient):
    """url_for builds the prefixed one for internal links, so it cannot 404."""
    assert pclient.get(f'{PREFIX}{ALIAS}').status_code == 200


def test_links_on_the_sibling_url_keep_the_canonical_prefix(pclient):
    """Otherwise a click from this page would leave the proxied path and 404 on the main site."""
    import re
    html = pclient.get(ALIAS).data.decode()
    links = set(re.findall(r'(?:href|src)="(/[^"]*)"', html))
    assert links, 'page should render absolute in-app links'
    assert [l for l in links if not l.startswith(PREFIX + '/')] == []


def test_both_addresses_name_the_same_canonical_one(pclient):
    """Same page at two URLs: search engines are told which counts rather than left to guess."""
    import re
    canon = f'https://{HOST}{ALIAS}'
    for path in (ALIAS, f'{PREFIX}{ALIAS}'):
        html = pclient.get(path).data.decode()
        assert re.search(r'rel="canonical" href="([^"]+)"', html).group(1) == canon


def test_an_alias_does_not_mount_the_whole_app_a_second_time(pclient):
    """Only the insurance route lives out there; everything else stays behind the one prefix."""
    assert pclient.get(f'{ALIAS}/dashboard').status_code == 404
    assert pclient.get(f'{ALIAS}/auth/login').status_code == 404
