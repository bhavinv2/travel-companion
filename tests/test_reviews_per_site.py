"""Reviews, filed against the product they were written about.

Somebody who flew with a companion has said nothing about travel insurance, and the other way
round. One table and one moderation queue -- the same queue CS already works -- with a column
saying which page the review belongs on.

What is protected here is mostly that the column is set from the page the reviewer was on, not
from anything they had to choose, and that nothing published on one product leaks onto another.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import login  # noqa: E402
from app import db as _db  # noqa: E402
from app.models import Feedback, User  # noqa: E402


def leave(client, comment, site=None, rating=5):
    payload = {'rating': rating, 'comment': comment}
    if site is not None:
        payload['site'] = site
    return client.post('/api/feedback', json=payload)


def approve(fb):
    fb.is_approved = True
    _db.session.commit()


# ---------------------------------------------------------------------------
# Writing one
# ---------------------------------------------------------------------------

def test_a_review_is_saved_against_the_page_it_was_left_on(client, db, user):
    login(client, 'bob@test.com')
    assert leave(client, 'Cover sorted in ten minutes.', site='insurance').status_code == 200
    assert Feedback.query.one().site == 'insurance'


def test_a_review_with_no_product_is_a_companion_review(client, db, user):
    """Which is what every review was before this, and what the app's own form still sends."""
    login(client, 'bob@test.com')
    leave(client, 'My mother was never alone.')
    assert Feedback.query.one().site == 'companion'


def test_a_made_up_product_does_not_lose_somebody_their_review(client, db, user):
    """The worst case of guessing wrong is a review on the wrong page. The worst case of
    rejecting it is that somebody's words are gone."""
    login(client, 'bob@test.com')
    assert leave(client, 'Worth it.', site='../../etc').status_code == 200
    assert Feedback.query.one().site == 'companion'


# ---------------------------------------------------------------------------
# Where it appears
# ---------------------------------------------------------------------------

def test_approval_is_still_what_publishes_it(client, db, user):
    login(client, 'bob@test.com')
    leave(client, 'Cover sorted in ten minutes.', site='insurance')
    fb = Feedback.query.one()
    assert fb.is_approved is False
    assert 'Cover sorted in ten minutes.' not in client.get('/reviews?site=insurance').data.decode()

    approve(fb)
    assert 'Cover sorted in ten minutes.' in client.get('/reviews?site=insurance').data.decode()


def test_each_product_shows_only_its_own(client, db, user, other_user):
    bob = User.query.filter_by(email='bob@test.com').one()
    alice = User.query.filter_by(email='alice@test.com').one()
    _db.session.add_all([
        Feedback(user_id=bob.id, rating=5, comment='Flew with my mother.', site='companion',
                 is_approved=True),
        Feedback(user_id=alice.id, rating=5, comment='Bought cover in minutes.', site='insurance',
                 is_approved=True),
    ])
    _db.session.commit()

    companion = client.get('/reviews').data.decode()
    assert 'Flew with my mother.' in companion and 'Bought cover in minutes.' not in companion

    insurance = client.get('/reviews?site=insurance').data.decode()
    assert 'Bought cover in minutes.' in insurance and 'Flew with my mother.' not in insurance


def test_the_landing_page_shows_companion_reviews_only(client, db, user):
    bob = User.query.filter_by(email='bob@test.com').one()
    _db.session.add(Feedback(user_id=bob.id, rating=5, comment='Bought cover in minutes.',
                             site='insurance', is_approved=True, is_featured=True))
    _db.session.commit()
    assert 'Bought cover in minutes.' not in client.get('/').data.decode()


def test_the_average_is_worked_out_per_product(client, db, user, other_user):
    """An average pooled from flight companions and insurance buyers describes neither, and the
    page it appears on is about one of them."""
    bob = User.query.filter_by(email='bob@test.com').one()
    _db.session.add_all([Feedback(user_id=bob.id, rating=5, comment='c%d' % i, site='companion',
                                  is_approved=True) for i in range(3)])
    _db.session.add(Feedback(user_id=bob.id, rating=1, comment='i1', site='insurance',
                             is_approved=True))
    _db.session.commit()

    assert '5.0 average from 3' in client.get('/reviews').data.decode()
    # one review is not enough to quote an average from, whatever it says
    assert 'average from 1' not in client.get('/reviews?site=insurance').data.decode()


def test_the_form_says_which_product_it_is_collecting_for(client, db, user):
    """The reviewer arrived from one of them and should not have to tell us which."""
    login(client, 'bob@test.com')
    assert 'data-site="insurance"' in client.get('/reviews?site=insurance').data.decode()
    assert 'data-site="companion"' in client.get('/reviews').data.decode()


# ---------------------------------------------------------------------------
# The queue
# ---------------------------------------------------------------------------

def test_the_admin_queue_filters_by_product(client, db, admin_user, user):
    bob = User.query.filter_by(email='bob@test.com').one()
    _db.session.add_all([
        Feedback(user_id=bob.id, rating=5, comment='Flew with my mother.', site='companion'),
        Feedback(user_id=bob.id, rating=5, comment='Bought cover in minutes.', site='insurance'),
    ])
    _db.session.commit()

    login(client, 'admin@test.com')
    both = client.get('/admin/voices?tab=feedback').data.decode()
    assert 'Flew with my mother.' in both and 'Bought cover in minutes.' in both

    one = client.get('/admin/voices?tab=feedback&site=insurance').data.decode()
    assert 'Bought cover in minutes.' in one and 'Flew with my mother.' not in one


def test_the_pending_badge_counts_every_product(client, db, admin_user, user):
    """It is the badge saying somebody is waiting. Hiding two thirds of it behind a filter is how
    an insurance review sits unread while the tab says there is nothing to do."""
    bob = User.query.filter_by(email='bob@test.com').one()
    _db.session.add(Feedback(user_id=bob.id, rating=5, comment='Waiting.', site='insurance'))
    _db.session.commit()

    login(client, 'admin@test.com')
    html = client.get('/admin/voices?tab=feedback&site=companion').data.decode()
    tabs = html.split('hx-tabs', 1)[1].split('</div>', 1)[0]
    assert '>1<' in tabs or 'vt-n' in tabs
