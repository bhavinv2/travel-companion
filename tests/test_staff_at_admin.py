"""The staff console at the domain's root (APP_STAFF_MOUNTS, 2026-11-03): nriparentservice.com/admin/cs/... is the
app's /cs/..., /admin/... its /admin/...; the old /travel-companions/cs/... and /travel-companions/admin/... addresses
redirect there, a POST to them is still answered, and every link a staff page builds says the new address. Through
the Worker and on Railway's own address nothing changes."""
import pytest

from app import create_app, db as _db
from conftest import make_user

PREFIX = '/travel-companions'
SITE = 'https://nriparentservice.com'


@pytest.fixture()
def dapp(tmp_path):
    app = create_app({
        'TESTING': True, 'WTF_CSRF_ENABLED': False, 'SQLALCHEMY_DATABASE_URI': 'sqlite://',
        'UPLOAD_FOLDER': str(tmp_path / 'uploads'), 'PRIVATE_UPLOAD_FOLDER': str(tmp_path / 'private'),
        'MAIL_PASSWORD': None, 'APP_URL_PREFIX': PREFIX, 'APP_PUBLIC_HOST': 'nriparentservice.com',
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


def admin(dc):
    u = make_user('boss@test.com', 'boss', role='admin')
    u.is_admin = True
    _db.session.commit()
    r = dc.post(PREFIX + '/auth/login', base_url=SITE, data={'email': u.email, 'password': 'password123'})
    assert r.status_code in (302, 303), r.status_code
    return u


def loc(r):
    return r.headers['Location'].replace(SITE, '')


def test_the_old_addresses_move_to_admin(dc):
    r = dc.get(PREFIX + '/cs/crm/?view=list&p=all', base_url=SITE)
    assert r.status_code == 301 and loc(r) == '/admin/cs/crm/?view=list&p=all'
    r = dc.get(PREFIX + '/admin/health', base_url=SITE)
    assert r.status_code == 301 and loc(r) == '/admin/health'
    r = dc.get(PREFIX + '/admin/crm/checks', base_url=SITE)
    assert r.status_code == 301 and loc(r) == '/admin/crm/checks'
    # the rest of the app stays where it is
    assert dc.get(PREFIX + '/auth/login', base_url=SITE).status_code == 200
    # a POST is answered where it was sent (a webhook written down somewhere), never redirected
    r = dc.post(PREFIX + '/cs/crm/checks/tick', base_url=SITE, json={})
    assert r.status_code not in (301, 307, 308)              # signed out: sent to sign in, but not moved


def test_signing_in_lands_on_the_new_address(dc):
    r = dc.get('/admin/cs/crm/', base_url=SITE)
    assert r.status_code == 302 and '/auth/login' in loc(r) and 'admin%2Fcs%2Fcrm' in loc(r).replace('/', '%2F')


def test_the_console_answers_at_admin_and_its_links_say_so(dc):
    admin(dc)
    page = dc.get('/admin/cs/crm/checks', base_url=SITE)
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert 'href="/admin/cs/crm/' in html or 'href="/admin/crm/' in html
    assert 'href="%s/cs/' % PREFIX not in html and 'href="%s/admin/' % PREFIX not in html
    assert '<meta name="app-mounts" content=\'[["/admin/cs", "/cs"], ["/admin", "/admin"]]\'/>' in html
    r = dc.get('/admin/health', base_url=SITE)
    assert r.status_code == 200 and 'href="%s/admin/' % PREFIX not in r.get_data(as_text=True)
    assert dc.get('/admin/crm/', base_url=SITE).status_code == 200
    # a favourite of a screen at its new address is understood (page_address.parse)
    r = dc.post(PREFIX + '/my/favourites/add', base_url=SITE,
                data={'next': '/admin/crm/inbox?who=mine', 'label': 'My chats'})
    assert r.status_code == 302 and loc(r) == '/admin/crm/inbox?who=mine'
    from app.models import StaffFavourite
    f = StaffFavourite.query.one()
    assert f.endpoint == 'admin_crm.inbox' and f.params == {'who': 'mine'}


def test_robots_keep_search_engines_out_of_admin(dc):
    body = dc.get('/robots.txt', base_url=SITE).get_data(as_text=True)
    assert 'Disallow: /admin/\n' in body and 'Disallow: %s/cs/' % PREFIX in body


def test_through_the_worker_nothing_moves(dc):
    r = dc.get(PREFIX + '/cs/crm/', base_url=SITE, headers={'X-Forwarded-Prefix': PREFIX})
    assert not (r.status_code == 301 and loc(r).startswith('/admin/cs'))


def test_the_installed_staff_app_starts_inside_its_scope(dc):
    m = dc.get(PREFIX + '/manifest.webmanifest', base_url=SITE).get_json()
    assert m['start_url'] == '/admin/cs/crm/today' and m['start_url'].startswith(m['scope'])
