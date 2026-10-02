"""The influencer role and its read-only dashboard.

Whoever promotes the service needs to know how much is happening and what people are saying.
They do not need the people. The thing worth protecting here is that distinction: the role must
not quietly become a way into the consoles, and the dashboard must not print anybody's contact
details.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import login, make_user  # noqa: E402
from app import db as _db  # noqa: E402
from app.models import ContactMessage, Feedback, User  # noqa: E402

PAGE = '/promotion'


@pytest.fixture()
def influencer(app, db):
    u = make_user('promo@test.com', 'promo')
    u.set_roles(['user', 'influencer'])
    _db.session.add(u)
    _db.session.commit()
    return u


@pytest.fixture()
def some_activity(app, db, user):
    bob = User.query.filter_by(email='bob@test.com').one()
    _db.session.add_all([
        ContactMessage(name='Asha', email='asha@example.com', message='about a trip',
                       topic='companion'),
        ContactMessage(name='Ravi', email='ravi@example.com', message='about cover',
                       topic='insurance'),
        ContactMessage(name='Meena', email='meena@example.com', message='general question',
                       topic='general'),
        Feedback(user_id=bob.id, rating=5, comment='My mother was never alone.',
                 site='companion', is_approved=True),
        Feedback(user_id=bob.id, rating=4, comment='Not approved yet.', site='insurance'),
    ])
    _db.session.commit()


# ---------------------------------------------------------------------------
# Who gets in
# ---------------------------------------------------------------------------

def test_the_influencer_can_open_it(client, db, influencer):
    login(client, 'promo@test.com')
    assert client.get(PAGE).status_code == 200


def test_an_admin_can_open_it(client, db, admin_user):
    login(client, 'admin@test.com')
    assert client.get(PAGE).status_code == 200


def test_an_ordinary_traveller_cannot(client, db, user):
    login(client, 'bob@test.com')
    r = client.get(PAGE)
    assert r.status_code == 302 and PAGE not in r.headers['Location']


def test_signed_out_is_sent_to_sign_in(client, db):
    r = client.get(PAGE)
    assert r.status_code == 302
    assert '/auth/login' in r.headers['Location']


def test_the_role_does_not_open_the_consoles(client, db, influencer):
    """It is a traveller-level role on purpose. The CS console shows enquirers' names, e-mail
    addresses and phone numbers -- which is not needed to say how busy we are."""
    assert influencer.is_influencer is True
    assert influencer.is_cs is False
    assert influencer.is_admin is False

    login(client, 'promo@test.com')
    for closed in ('/cs/', '/cs/voices', '/admin/users'):
        assert client.get(closed).status_code in (302, 403), closed


# ---------------------------------------------------------------------------
# What it shows
# ---------------------------------------------------------------------------

def test_it_counts_each_service_separately(client, db, influencer, some_activity):
    login(client, 'promo@test.com')
    html = client.get(PAGE).data.decode()
    for label in ('Travel Companion', 'Travel Insurance', 'Sahayak', 'General enquiry'):
        assert label in html, label


def test_it_quotes_published_reviews(client, db, influencer, some_activity):
    login(client, 'promo@test.com')
    html = client.get(PAGE).data.decode()
    assert 'My mother was never alone.' in html
    assert 'Not approved yet.' not in html, 'only what somebody approved for publication'


def test_it_never_prints_who_wrote_in(client, db, influencer, some_activity):
    """Counts and published reviews. The enquirers themselves are not part of promoting."""
    login(client, 'promo@test.com')
    html = client.get(PAGE).data.decode()
    for private in ('asha@example.com', 'ravi@example.com', 'meena@example.com',
                    'about a trip', 'general question'):
        assert private not in html, private


def test_there_is_nothing_on_it_to_press(client, db, influencer, some_activity):
    """"Read-only as of now" is enforced by there being nothing that writes, rather than by a
    flag somebody could flip by accident.

    Asserted against the template source and the route rather than by slicing the rendered page:
    the shared shell around it has a newsletter form and a chat button, and a test that has to
    guess where the page ends tests the guess.
    """
    login(client, 'promo@test.com')
    assert client.get(PAGE).status_code == 200
    assert client.post(PAGE).status_code == 405, 'the route must not accept a write at all'

    tpl = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'app', 'templates', 'pages', 'promo_dashboard.html')
    body = open(tpl, encoding='utf-8').read().lower()
    for writes in ('<form', '<button', '<input', 'method="post"'):
        assert writes not in body, writes


def test_an_average_needs_enough_reviews_behind_it(client, db, influencer, user):
    """Below a handful, a specific average reads as invented -- and this number goes in a video."""
    bob = User.query.filter_by(email='bob@test.com').one()
    _db.session.add(Feedback(user_id=bob.id, rating=5, comment='Only one.', site='companion',
                             is_approved=True))
    _db.session.commit()
    from app.services import promo
    rows = {r['key']: r for r in promo.reviews()['rows']}
    assert rows['companion']['count'] == 1
    assert rows['companion']['avg'] is None

    for i in range(2):
        _db.session.add(Feedback(user_id=bob.id, rating=4, comment='More %d' % i,
                                 site='companion', is_approved=True))
    _db.session.commit()
    rows = {r['key']: r for r in promo.reviews()['rows']}
    assert rows['companion']['avg'] is not None
