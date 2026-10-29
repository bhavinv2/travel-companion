"""Site-wide GA4 / Google Tag Manager / second Ads account / Search Console verification.

Same shape as test_ads_tracking.py, and for the same reason: these tags load on every page, so
a mistake here is not one quiet pixel but every pixel, everywhere, all at once -- a developer's
laptop reporting as real traffic site-wide, or a tag that silently stops loading in production.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import analytics  # noqa: E402


LIVE = {'HTTP_HOST': 'nriparentservice.com'}


@pytest.fixture()
def live(app):
    """A request that looks like production -- see test_ads_tracking.py for why both of these
    have to change together."""
    app.config['TESTING'] = False
    app.config['SERVER_NAME'] = 'nriparentservice.com'
    yield
    app.config['TESTING'] = True
    app.config['SERVER_NAME'] = 'localhost'


# ---------------------------------------------------------------------------
# When it does not load
# ---------------------------------------------------------------------------

def test_nothing_loads_on_localhost(app, live):
    """A developer's laptop reporting as a site visit, all day, every day."""
    with app.test_request_context('/', environ_overrides={'HTTP_HOST': '127.0.0.1:8080'}):
        assert analytics.enabled() is False
    with app.test_request_context('/', environ_overrides={'HTTP_HOST': 'localhost:5000'}):
        assert analytics.enabled() is False


def test_nothing_loads_in_tests(app):
    with app.test_request_context('/', environ_overrides=LIVE):
        assert app.config['TESTING'] is True
        assert analytics.enabled() is False


def test_a_page_without_tracking_carries_no_tag_but_still_verifies(client, db):
    """The one tag that is NOT gated: Search Console checks the live domain, so hiding it in
    dev protects nothing and risks someone "fixing" a blank-looking page by deleting it."""
    html = client.get('/').data.decode()
    assert 'googletagmanager.com' not in html
    assert 'G-NPHSR9PNTC' not in html
    assert 'AW-18413942725' not in html
    assert 'google-site-verification' in html


# ---------------------------------------------------------------------------
# When it does
# ---------------------------------------------------------------------------

def test_every_page_carries_the_same_tags(app, db, live):
    """The base.html include, exercised on a page that extends it and one that does not."""
    c = app.test_client()
    for path in ('/', '/auth/login', '/trips'):
        html = c.get(path, environ_overrides=LIVE,
                     base_url='https://nriparentservice.com').data.decode()
        assert 'googletagmanager.com/gtag/js?id=G-NPHSR9PNTC' in html, path
        assert 'googletagmanager.com/gtm.js' in html, path
        assert 'GTM-KGHBGZGM' in html, path
        assert 'googletagmanager.com/gtag/js?id=AW-18413942725' in html, path
        assert 'google-site-verification' in html, path


def test_noscript_fallback_is_on_landing_pages_only(app, db, live):
    """GTM's own instructions put the noscript snippet everywhere the script tag is; this site
    deliberately narrows that to the pages paid traffic actually lands on -- see
    _gtm_noscript.html. A page losing it silently is the same failure mode as never adding it:
    an ad-blocked or JS-disabled visitor's pageview goes uncounted exactly where it mattered."""
    c = app.test_client()
    noscript = 'googletagmanager.com/ns.html?id=GTM-KGHBGZGM'
    for path in ('/', '/travel-insurance', '/sahayak'):
        html = c.get(path, environ_overrides=LIVE,
                     base_url='https://nriparentservice.com').data.decode()
        assert noscript in html, '%s should carry the GTM noscript fallback' % path
    for path in ('/auth/login', '/trips'):
        html = c.get(path, environ_overrides=LIVE,
                     base_url='https://nriparentservice.com').data.decode()
        assert noscript not in html, '%s should not carry the GTM noscript fallback' % path


def test_the_insurance_ads_account_is_not_duplicated(app, db, live):
    """This account used to load a second time from insurance/landing.html's own extra_head --
    a duplicate gtag('config', ...) call double-counts that page's pageviews for the account.
    Exactly one gtag('config', 'AW-18430711486') now, from base.html via _analytics.html."""
    html = app.test_client().get('/travel-insurance', environ_overrides=LIVE,
                                 base_url='https://nriparentservice.com').data.decode()
    assert html.count("gtag('config', \"AW-18430711486\")") == 1


def test_ids_can_be_changed_without_a_deploy(app, live, monkeypatch):
    monkeypatch.setenv('GA4_ID', 'G-TEST123')
    monkeypatch.setenv('GTM_ID', 'GTM-TEST456')
    with app.test_request_context('/', environ_overrides=LIVE):
        assert analytics.ga4_id() == 'G-TEST123'
        assert analytics.gtm_id() == 'GTM-TEST456'


def test_site_verification_has_both_attributes(app, db, live):
    """The pasted snippet this was added from merged name= and content= into one malformed
    attribute with no content at all -- Search Console would never have seen a token."""
    html = app.test_client().get('/', environ_overrides=LIVE,
                                 base_url='https://nriparentservice.com').data.decode()
    assert '<meta name="google-site-verification" content="WzvybcLxnJKDG6UvLhtOCjOOJLR86bnoWng1yR_qxW0"' in html


# ---------------------------------------------------------------------------
# The tawk.to chat bubble (services/tawk.widget_here): the same gate as the tags
# ---------------------------------------------------------------------------

TAWK = 'embed.tawk.to/'


def test_the_chat_bubble_is_on_the_public_pages(app, db, live):
    c = app.test_client()
    for path in ('/', '/travel-insurance', '/contact-us', '/trips'):
        html = c.get(path, environ_overrides=LIVE, base_url='https://nriparentservice.com').data.decode()
        assert TAWK in html and '6a024ea8e784421c33cd4277/1jocg6h2o' in html, path
        assert html.count('Tawk_API = Tawk_API') == 1, path


def test_no_chat_bubble_in_the_tests_on_a_laptop_or_for_staff(app, db, client, admin_user, live):
    from conftest import login
    with app.test_request_context('/', environ_overrides={'HTTP_HOST': '127.0.0.1:8080'}):
        from app.services import tawk
        assert tawk.widget_here() == ''
    login(client, admin_user.email)
    html = client.get('/admin/health', environ_overrides=LIVE, base_url='https://nriparentservice.com').data.decode()
    assert TAWK not in html, 'staff answer the chats; the bubble is for visitors'


def test_the_bubble_can_be_switched_off_or_changed(app, db, live, monkeypatch):
    from app.services import tawk
    monkeypatch.setenv('TAWK_WIDGET', '')
    assert tawk.widget() == ''
    monkeypatch.setenv('TAWK_WIDGET', 'not a widget"><script>')
    assert tawk.widget() == '', 'only something shaped like a tawk widget reaches the page'
    monkeypatch.setenv('TAWK_WIDGET', 'abcdef0123456789abcdef01/1abcdef2')
    assert tawk.widget() == 'abcdef0123456789abcdef01/1abcdef2'
