"""The site's menu, the same on every public page of nriparentservice.com (base.html, landing.html, _footer.html).

    Home        the site's home page, /home -- never the companion app's first page, and marked on /home itself
    Services    Travel Companion, Travel Insurance and Sahayak (ours), then the group's other sites in a new tab
    the rest    Blog, About Us, Contact Us; the page you are on is marked
    before      on Railway's own address the domain's root is not ours, so Home is the companion app's first page
"""
import re

import pytest

from app import create_app, db as _db
from conftest import make_user

PREFIX = '/travel-companions'
SITE = 'https://nriparentservice.com'
PAGES = ['/home', '/about-us', '/blog', '/travel-insurance', '/sahayak', '/contact-us', '/privacy-policy',
         '/terms-and-conditions', PREFIX + '/trips', PREFIX + '/help', PREFIX + '/reviews', PREFIX + '/how-it-works']


@pytest.fixture()
def dapp(tmp_path):
    app = create_app({
        'TESTING': True,
        'WTF_CSRF_ENABLED': False,
        'SQLALCHEMY_DATABASE_URI': 'sqlite://',
        'UPLOAD_FOLDER': str(tmp_path / 'uploads'),
        'PRIVATE_UPLOAD_FOLDER': str(tmp_path / 'private'),
        'MAIL_PASSWORD': None,
        'APP_URL_PREFIX': PREFIX,
        'APP_PUBLIC_HOST': 'nriparentservice.com',
    })
    with app.app_context():
        _db.create_all()
        from app.services import settings as _settings
        _settings.clear_cache()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def dc(dapp):
    return dapp.test_client()


def page(c, path, site=SITE):
    r = c.get(path, base_url=site)
    assert r.status_code == 200, (path, r.status_code, r.headers.get('Location'))
    return r.get_data(as_text=True)


def menu(html):
    """{label: (href, marked)} for the header's links, the Services menu included."""
    nav = re.search(r'<ul class="nav-links" id="navLinks">(.*?)\n    </ul>\n', html, re.S).group(1)
    out = {}
    for attrs, label in re.findall(r'<a ([^>]*)>(.*?)</a>', nav, re.S):
        label = re.sub(r'<[^>]+>', '', label).strip()
        href = re.search(r'href="([^"]*)"', attrs).group(1)
        out[label] = (href, 'class="active"' in attrs or 'class="on"' in attrs)
    return out


def footer(html):
    foot = re.search(r'<footer class="ftr">(.*?)</footer>', html, re.S).group(1)
    return {re.sub(r'<[^>]+>', '', label).strip(): href
            for href, label in re.findall(r'<a [^>]*?href="([^"]*)"[^>]*>(.*?)</a>', foot, re.S)}


def test_every_public_page_has_the_same_menu(dc):
    for path in PAGES:
        m = menu(page(dc, path))
        assert m['Home'][0] == '/home', path
        assert m['Blog'][0] == '/blog', path
        assert m['About Us'][0] == '/about-us', path
        assert m['Contact Us'][0] == '/contact-us', path
        assert m['Travel Companion'][0] == PREFIX + '/', path
        assert m['Travel Insurance'][0] == '/travel-insurance', path
        assert m['Sahayak'][0] == '/sahayak', path
        assert 'Traveller Blogs' not in m and 'How It Works' not in m, path


def test_home_is_in_the_menu_on_the_home_page_and_marked(dc):
    html = page(dc, '/home')
    m = menu(html)
    assert m['Home'] == ('/home', True)
    assert not any(marked for label, (href, marked) in m.items() if label != 'Home')
    assert 'class="nav-logo"' in html and re.search(r'<a href="/home" class="nav-logo">', html)


@pytest.mark.parametrize('path, marked', [
    ('/about-us', 'About Us'), ('/blog', 'Blog'), ('/contact-us', 'Contact Us'),
    ('/travel-insurance', 'Travel Insurance'), ('/sahayak', 'Sahayak'), (PREFIX + '/trips', 'Travel Companion')])
def test_the_page_you_are_on_is_marked(dc, path, marked):
    m = menu(page(dc, path))
    assert m[marked][1], (path, m)
    assert not m['Home'][1]
    if marked in ('Travel Insurance', 'Sahayak', 'Travel Companion'):
        assert m['Services'][1]


def test_services_lists_ours_then_the_groups_other_sites_in_a_new_tab(dc):
    html = page(dc, '/home')
    nav = re.search(r'<ul class="nav-svc-menu">(.*?)</ul>', html, re.S).group(1)
    hrefs = re.findall(r'href="([^"]*)"', nav)
    assert hrefs[:3] == [PREFIX + '/', '/travel-insurance', '/sahayak']
    assert all(h.startswith('https://') for h in hrefs[3:]) and hrefs[3:]
    assert 'book-a-sahayak' not in html                           # /sahayak is where a Sahayak is booked now
    assert nav.count('target="_blank"') == len(hrefs) - 3


def test_the_footer_says_the_same(dc):
    f = footer(page(dc, '/travel-insurance'))
    assert f['Home'] == '/home'
    assert f['About Us'] == '/about-us' and f['Blog'] == '/blog' and f['Contact Us'] == '/contact-us'
    assert f['Travel Companion'] == PREFIX + '/' and f['Sahayak'] == '/sahayak'
    assert f['Privacy Policy'] == '/privacy-policy' and f['Terms and Conditions'] == '/terms-and-conditions'
    html = page(dc, '/blog')
    assert re.search(r'<a class="ftr-logo" href="/home">', html)


def test_signing_in_from_a_front_door_comes_back_to_its_own_address(dc):
    m = menu(page(dc, '/travel-insurance'))
    assert m['Sign In'][0] == PREFIX + '/auth/login?next=/travel-insurance'
    assert m['Sign Up'][0] == PREFIX + '/auth/register?next=/travel-insurance'


def test_the_companion_landing_has_the_site_menu(dc):
    html = page(dc, PREFIX + '/')
    nav = re.search(r'<nav class="nav" aria-label="Main">(.*?)</nav>', html, re.S).group(1)
    assert re.search(r'<a href="/home">Home</a>', nav)
    for href in ('/blog', '/about-us', '/contact-us', PREFIX + '/trips', '/travel-insurance', '/sahayak'):
        assert 'href="%s"' % href in nav, href
    assert 'Traveller Blogs' not in nav
    assert re.search(r'<a class="logo" href="/home"', html)


def test_the_sign_in_pages_go_back_to_the_home_page(dc):
    for path in ('/auth/login', '/auth/register'):
        html = page(dc, PREFIX + path)
        assert re.search(r'<a class="back" href="/home">', html), path


def test_signed_in_the_menu_adds_my_dashboard_and_home_stays_home(dapp, dc):
    make_user('ravi@test.com', 'ravi')
    r = dc.post(PREFIX + '/auth/login', base_url=SITE, data={'email': 'ravi@test.com', 'password': 'password123'})
    assert r.status_code == 302
    html = page(dc, PREFIX + '/dashboard')
    m = menu(html)
    assert m['Home'][0] == '/home'
    assert m['My Dashboard'] == (PREFIX + '/dashboard', True)
    assert 'Sign In' not in m
    # the user menu's way back to the companion app says which it is
    assert re.search(r'href="%s/"><i class="fa-solid fa-plane-up"></i> Travel Companion</a>' % PREFIX, html)


def test_on_railways_own_address_home_is_the_companion_app(dc):
    """The domain's root is not ours there (or before the switch), so /home would be somebody else's page."""
    m = menu(page(dc, '/travel-insurance', site='https://travel-companion-production.up.railway.app'))
    assert m['Home'][0] in ('/', PREFIX + '/')
