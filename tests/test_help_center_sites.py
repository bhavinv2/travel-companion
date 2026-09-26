"""The help centre, split by product.

It was one list of categories under one admin screen, and the travel-insurance and Sahayak pages
each read a category out of it by key. That worked and nobody could find it: the questions on the
insurance page were edited on a screen filed under Travel Companion, three clicks away from
anything to do with insurance.

Each product has its own screen now. The thing worth protecting is what that split makes easy to
get wrong -- this is still ONE settings blob, so a save that wrote only the rows on screen would
delete the other two products' questions without saying so.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import login  # noqa: E402
from app.services import help_center  # noqa: E402


CAT = {'key': 'travel_insurance', 'title': 'Travel insurance', 'icon': 'fa-shield-halved',
       'blurb': 'Cover and claims'}


def faq(cat, q, a, fid='x1'):
    return {'id': fid, 'category': cat, 'question': q, 'answer': a}


# ---------------------------------------------------------------------------
# The split itself
# ---------------------------------------------------------------------------

def test_every_product_starts_with_its_own_questions(app, db):
    assert {c['key'] for c in help_center.categories('companion')} == {
        'getting_started', 'privacy', 'matches', 'account'}
    assert [c['key'] for c in help_center.categories('insurance')] == ['travel_insurance']
    assert [c['key'] for c in help_center.categories('sahayak')] == ['sahayak']

    assert help_center.faqs('insurance'), 'the ten common answers ship, on the admin screen'
    assert not help_center.faqs('sahayak'), 'nothing true to say yet, so the section stays hidden'


def test_a_question_belongs_to_whatever_its_category_does(app, db):
    """A question carries no site of its own. Giving it one would let the two disagree, and then
    somebody would have to decide which of them is right."""
    help_center.save([CAT], [faq('travel_insurance', 'Is it mandatory?', 'Sometimes.')],
                     site='insurance')
    assert [f['question'] for f in help_center.faqs('insurance')] == ['Is it mandatory?']
    assert 'Is it mandatory?' not in [f['question'] for f in help_center.faqs('companion')]


def test_saving_one_product_leaves_the_others_alone(app, db):
    """The one that would have bitten: this is a single blob, and a save writes all of it."""
    before = len(help_center.faqs('companion'))
    assert before

    help_center.save([CAT], [faq('travel_insurance', 'Is it mandatory?', 'Sometimes.')],
                     site='insurance')

    assert len(help_center.faqs('companion')) == before
    assert [c['key'] for c in help_center.categories('sahayak')] == ['sahayak']


def test_resetting_one_product_leaves_the_others_alone(app, db):
    help_center.save([CAT], [], site='insurance')
    help_center.save([{'key': 'getting_started', 'title': 'Only this', 'icon': 'fa-rocket',
                       'blurb': ''}], [], site='companion')
    assert not help_center.faqs('companion')

    help_center.reset(site='companion')
    assert help_center.faqs('companion')
    assert not help_center.faqs('insurance'), 'the insurance edit must survive'


def test_rows_saved_before_the_split_land_where_they_were_being_read(app, db):
    """Existing installs have categories with no `site`. Two of them were already being read by
    the other two pages under a known key, so they move to where they belong rather than all
    piling into the companion app."""
    assert help_center.site_of({'key': 'travel_insurance'}) == 'insurance'
    assert help_center.site_of({'key': 'sahayak'}) == 'sahayak'
    assert help_center.site_of({'key': 'privacy'}) == 'companion'
    assert help_center.site_of({'key': 'travel_insurance', 'site': 'companion'}) == 'companion'


def test_an_unknown_site_is_not_taken_at_face_value(app, db):
    """It decides which rows a save replaces, so it never reaches that code straight from a
    query string."""
    assert help_center.clean_site('insurance') == 'insurance'
    assert help_center.clean_site('../companion') == 'companion'
    assert help_center.clean_site(None) == 'companion'


# ---------------------------------------------------------------------------
# The screens
# ---------------------------------------------------------------------------

def test_each_product_has_its_own_screen(client, db, admin_user):
    login(client, 'admin@test.com')
    for site, heading in (('companion', 'Travel Companion'), ('insurance', 'Travel Insurance'),
                          ('sahayak', 'Sahayak')):
        html = client.get('/admin/help?site=%s' % site).data.decode()
        assert 'Help &amp; FAQ &mdash; %s' % heading in html or heading in html, site
        assert 'name="site" value="%s"' % site in html, site


def test_the_screen_shows_only_its_own_questions(client, db, admin_user):
    login(client, 'admin@test.com')
    html = client.get('/admin/help?site=insurance').data.decode()
    assert 'What is travel insurance?' in html
    assert 'How do I post a trip?' not in html


def test_saving_from_a_screen_cannot_touch_another_product(client, db, admin_user):
    """The site comes from the form, not the query string: a stale URL must not be able to point
    a save at the wrong product's rows."""
    login(client, 'admin@test.com')
    before = len(help_center.faqs('companion'))

    client.post('/admin/help?site=companion', data={
        'site': 'insurance',
        'cat_key': ['travel_insurance'], 'cat_title': ['Travel insurance'],
        'cat_icon': ['fa-shield-halved'], 'cat_blurb': ['Cover'],
        'faq_id': ['ti1'], 'faq_category': ['travel_insurance'],
        'faq_question': ['Does it cover my parents?'], 'faq_answer': ['It depends on the plan.'],
    }, follow_redirects=True)

    assert [f['question'] for f in help_center.faqs('insurance')] == ['Does it cover my parents?']
    assert len(help_center.faqs('companion')) == before


def test_the_public_help_page_answers_for_the_app_it_belongs_to(client, db):
    """Travel insurance and Sahayak have their own pages. Mixing all three here would answer
    about a service the reader did not come for."""
    help_center.save([CAT], [faq('travel_insurance', 'Is it mandatory?', 'Sometimes.')],
                     site='insurance')
    html = client.get('/help').data.decode()
    assert 'How do I post a trip?' in html
    assert 'Is it mandatory?' not in html


def test_an_admin_only_screen(client, db, cs_user):
    login(client, 'cs@test.com')
    assert client.get('/admin/help?site=insurance').status_code in (302, 403)
