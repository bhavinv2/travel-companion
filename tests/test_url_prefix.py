"""Links that have to survive being served under a URL prefix.

In production this app answers at /travel-companions/, and PrefixMiddleware puts that in
SCRIPT_NAME so url_for() writes it into every link. Anything NOT built with url_for misses it --
a path a route passed as a string, a `next` taken from request.path, a link stored in a
notification row -- and points at the site root, which is a different site entirely.

Every one of those is a 404 that cannot happen locally, where the prefix is empty, and so gets
found by whoever is using the console rather than by anybody testing it. That is what this file
is for: the prefix is switched on, and the links are read out of the rendered page.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import login, make_user  # noqa: E402
from app import create_app, db as _db  # noqa: E402
from app.models import ContactMessage, Notification, User  # noqa: E402

PREFIX = '/travel-companions'


@pytest.fixture()
def papp(tmp_path):
    """The app as production serves it: mounted under a prefix, on a real host name."""
    app = create_app({
        'TESTING': True,
        'WTF_CSRF_ENABLED': False,
        'SQLALCHEMY_DATABASE_URI': 'sqlite://',
        'UPLOAD_FOLDER': str(tmp_path / 'uploads'),
        'PRIVATE_UPLOAD_FOLDER': str(tmp_path / 'private'),
        'SERVER_NAME': 'nriparentservice.com',
        'MAIL_PASSWORD': None,
        'APP_URL_PREFIX': PREFIX,
    })
    with app.app_context():
        _db.create_all()
        from app.services import settings as _settings
        _settings.clear_cache()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def pclient(papp):
    return papp.test_client()


@pytest.fixture()
def cs(papp):
    u = make_user('cs@test.com', 'cs', role='cs')
    _db.session.add(u)
    _db.session.commit()
    return u


def get(client, path, **kw):
    return client.get(PREFIX + path, base_url='https://nriparentservice.com', **kw)


def signin(client):
    return client.post(PREFIX + '/auth/login', data={'email': 'cs@test.com', 'password': 'password123'},
                       base_url='https://nriparentservice.com')


# ---------------------------------------------------------------------------
# Links the page renders
# ---------------------------------------------------------------------------

def test_the_move_to_buttons_come_back_to_this_screen(pclient, cs):
    """They post a `next` and the route redirects to it. Built from request.path it was
    /cs/voices, which under the prefix is somebody else's website -- the state changed and the
    agent landed on a 404, so it looked like nothing had happened."""
    _db.session.add(ContactMessage(name='Asha', email='a@example.com', message='hello there'))
    _db.session.commit()
    signin(pclient)

    html = get(pclient, '/cs/voices?tab=contact').data.decode()
    assert 'name="next" value="%s/cs/voices' % PREFIX in html


def test_the_notification_log_filters_stay_inside_the_app(pclient, cs):
    """Reset, and the username links that filter by user. Both were built from a hardcoded
    '/cs/notifications' the route passed in as a string."""
    _db.session.add(Notification(user_id=cs.id, type='broadcast', title='Hello', link='/connections'))
    _db.session.commit()
    signin(pclient)

    html = get(pclient, '/cs/notifications').data.decode()
    assert 'href="%s/cs/notifications"' % PREFIX in html, 'Reset'
    assert 'href="%s/cs/notifications?user_id=%d"' % (PREFIX, cs.id) in html, 'filter by user'


def test_a_stored_notification_link_is_moved_inside_the_app(pclient, cs):
    """Rows written before anybody deployed under a prefix hold bare paths like /connections."""
    _db.session.add(Notification(user_id=cs.id, type='broadcast', title='Hello', link='/connections'))
    _db.session.commit()
    signin(pclient)

    html = get(pclient, '/cs/notifications').data.decode()
    assert 'href="%s/connections"' % PREFIX in html
    assert 'href="/connections"' not in html


def test_signing_in_returns_to_the_page_that_asked(pclient, cs):
    r = get(pclient, '/cs/posts')
    assert r.status_code == 302
    assert 'next=%2Ftravel-companions%2Fcs%2Fposts' in r.headers['Location']


# ---------------------------------------------------------------------------
# One address per page
# ---------------------------------------------------------------------------

def test_the_prefixed_spelling_of_a_front_door_redirects_to_it(papp):
    """/travel-insurance is its own front door and answers beside the prefix. The app also routes
    the prefixed spelling, so the same page had two addresses -- which splits its search ranking
    and halves every number in its analytics."""
    papp.config['TESTING'] = False
    try:
        c = papp.test_client()
        for alias in ('/travel-insurance', '/sahayak'):
            r = c.get(PREFIX + alias, base_url='https://nriparentservice.com')
            assert r.status_code == 301, alias
            assert r.headers['Location'].endswith(alias), r.headers['Location']
    finally:
        papp.config['TESTING'] = True


def test_the_app_itself_is_not_redirected(papp):
    """Only the front doors have a second spelling; everything else lives under the prefix."""
    papp.config['TESTING'] = False
    try:
        r = papp.test_client().get(PREFIX + '/auth/login', base_url='https://nriparentservice.com')
        assert r.status_code == 200
    finally:
        papp.config['TESTING'] = True


def test_plain_http_is_sent_to_https(papp):
    """Logins, admin sessions and people's phone numbers go over this connection."""
    papp.config['TESTING'] = False
    try:
        r = papp.test_client().get(PREFIX + '/', base_url='http://nriparentservice.com')
        assert r.status_code == 301
        assert r.headers['Location'].startswith('https://')
    finally:
        papp.config['TESTING'] = True


def test_localhost_is_left_alone(papp):
    """There is no certificate on a development machine, so the same rule would make the app
    unreachable while it is being worked on."""
    papp.config['TESTING'] = False
    papp.config['SERVER_NAME'] = 'localhost'
    try:
        r = papp.test_client().get(PREFIX + '/auth/login', base_url='http://localhost')
        assert r.status_code == 200
    finally:
        papp.config['TESTING'] = True
        papp.config['SERVER_NAME'] = 'nriparentservice.com'


# ---------------------------------------------------------------------------
# Where a `next` may point
# ---------------------------------------------------------------------------

def test_a_next_cannot_point_off_the_site(papp):
    """It arrives in a form body on a page anybody can reach. A full URL in a redirect is how a
    phishing page gets to claim it was reached from ours."""
    from app.services.urls import safe_next
    with papp.test_request_context('/'):
        assert safe_next('/cs/voices') == '/cs/voices'
        assert safe_next('https://evil.example.com') is None
        assert safe_next('//evil.example.com') is None
        assert safe_next('') is None
        assert safe_next(None) is None
