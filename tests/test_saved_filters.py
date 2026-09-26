"""Saved views: a named set of filters that still means the right thing tomorrow.

The whole point of the feature is the last part. An agent who saves "departing today, from Delhi"
in September must see December's Delhi departures in December -- which is why the filter stores
`dep=today` rather than a pair of dates, and why most of what is protected here is that
distinction. A saved view that froze its dates would be a bookmark, and people already had those.
"""
import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import login  # noqa: E402
from app import db as _db  # noqa: E402
from app.models import SavedFilter, User  # noqa: E402
from app.services import post_filters, saved_filters  # noqa: E402


@pytest.fixture()
def agent(app, db, cs_user):
    return User.query.filter_by(email='cs@test.com').one()


@pytest.fixture()
def other(app, db):
    u = User(username='otheragent', email='other@test.com', role='cs')
    u.set_password('x')
    _db.session.add(u)
    _db.session.commit()
    return u


# ---------------------------------------------------------------------------
# The reason this exists: relative dates
# ---------------------------------------------------------------------------

def test_a_relative_range_is_resolved_on_the_day_it_is_opened(db):
    """`dep=today` is stored; the dates are worked out per request. This is the feature."""
    field = post_filters.FIELDS['dep']
    for when in (date(2026, 9, 26), date(2026, 9, 27), date(2027, 3, 14)):
        got = post_filters.preset_range(field, 'today', today=when)
        assert got['from'] == when and got['to'] == when, when

    tomorrow = post_filters.preset_range(field, 'tomorrow', today=date(2026, 9, 26))
    assert tomorrow['from'] == date(2026, 9, 27)


def test_a_saved_filter_keeps_the_intent_not_the_dates(agent, db):
    f = saved_filters.create(agent, 'Today ex-DEL', {'dep': 'today', 'origin': 'DEL'})
    assert f.params == {'dep': 'today', 'origin': 'DEL'}
    # nothing resembling a fixed date was stored
    assert 'dep_from' not in f.params and 'dep_to' not in f.params
    assert saved_filters.is_relative(f.params) is True


def test_typed_dates_are_stored_as_typed(agent, db):
    """Somebody who picked an exact range meant that range, and it must not drift."""
    f = saved_filters.create(agent, 'That week in November',
                             {'dep_from': '2026-11-01', 'dep_to': '2026-11-07'})
    assert f.params == {'dep_from': '2026-11-01', 'dep_to': '2026-11-07'}
    assert saved_filters.is_relative(f.params) is False


def test_the_engine_applies_a_relative_filter_to_the_query(client, db, cs_user):
    """End to end: the listing filters by the resolved dates, not by the literal string."""
    from app.models import CompanionRequest
    today = date.today()
    for when, who in ((today, 'flies today'), (today + timedelta(days=5), 'flies later')):
        _db.session.add(CompanionRequest(poster_name=who, flying_from='Delhi', destination='Dubai',
                                         from_date=when, status='open',
                                         travel_type='one_way', trip_type='one_way'))
    _db.session.commit()

    query, active = post_filters.apply(CompanionRequest.query, {'dep': 'today'})
    names = [r.poster_name for r in query.all()]
    assert names == ['flies today'], names
    assert active['dep']['preset'] == 'today'


# ---------------------------------------------------------------------------
# What gets stored
# ---------------------------------------------------------------------------

def test_only_real_filters_are_stored(agent, db):
    """A saved view is replayed straight into the query builder, so an unknown key would mean
    saving today's typo forever."""
    f = saved_filters.create(agent, 'Clean', {'origin': ' BOM ', 'made_up': 'x',
                                              'dep': 'not-a-preset'})
    assert f.params == {'origin': 'BOM'}


def test_a_view_needs_a_name_and_at_least_one_filter(agent, db):
    with pytest.raises(saved_filters.FilterError):
        saved_filters.create(agent, '', {'dep': 'today'})
    with pytest.raises(saved_filters.FilterError):
        saved_filters.create(agent, 'Nothing', {})


def test_names_are_unique_per_person_not_globally(agent, other, db):
    saved_filters.create(agent, 'Today', {'dep': 'today'})
    with pytest.raises(saved_filters.FilterError):
        saved_filters.create(agent, 'Today', {'dep': 'tomorrow'})
    # a colleague may use the same name for their own
    assert saved_filters.create(other, 'Today', {'dep': 'today'})


def test_it_reads_as_plain_english(agent, db):
    f = saved_filters.create(agent, 'Today ex-DEL', {'dep': 'today', 'origin': 'DEL'})
    assert saved_filters.describe(f.params) == ['Departure: Departing today', 'Departing from: DEL']


# ---------------------------------------------------------------------------
# Ownership
# ---------------------------------------------------------------------------

def test_a_private_view_is_invisible_to_colleagues(agent, other, db):
    f = saved_filters.create(agent, 'Mine', {'dep': 'today'})
    assert saved_filters.get_for(other, f.id) is None
    assert [x.name for x in saved_filters.for_user(other)] == []


def test_sharing_grants_use_but_never_edit(agent, other, db):
    f = saved_filters.create(agent, 'Team view', {'dep': 'today'}, shared=True)
    assert saved_filters.get_for(other, f.id) is not None          # they can open it
    assert saved_filters.owned_by(other, f.id) is None             # but not change it
    for action in (lambda: saved_filters.update(other, f.id, name='Hijacked'),
                   lambda: saved_filters.delete(other, f.id)):
        with pytest.raises(saved_filters.FilterError):
            action()
    assert SavedFilter.query.get(f.id).name == 'Team view'


def test_your_own_views_come_first(agent, other, db):
    saved_filters.create(other, 'Theirs', {'dep': 'today'}, shared=True)
    saved_filters.create(agent, 'Mine', {'dep': 'tomorrow'})
    assert [f.name for f in saved_filters.for_user(agent)] == ['Mine', 'Theirs']


def test_there_is_a_ceiling_on_how_many(agent, db):
    for i in range(saved_filters.MAX_PER_USER):
        saved_filters.create(agent, 'View %d' % i, {'dep': 'today'})
    with pytest.raises(saved_filters.FilterError):
        saved_filters.create(agent, 'One too many', {'dep': 'today'})


# ---------------------------------------------------------------------------
# On the page
# ---------------------------------------------------------------------------

def test_both_listings_offer_saved_views(client, db, cs_user):
    login(client, 'cs@test.com')
    html = client.get('/cs/posts').data.decode()
    assert 'sv-bar' in html and 'Saved views' in html


def test_opening_a_view_puts_its_filters_in_the_url(client, db, cs_user, agent):
    f = saved_filters.create(agent, 'Today ex-DEL', {'dep': 'today', 'origin': 'DEL'})
    login(client, 'cs@test.com')
    r = client.get('/saved-filters/open/%d' % f.id)
    assert r.status_code == 302
    assert 'dep=today' in r.headers['Location']
    assert 'origin=DEL' in r.headers['Location']
    # and it is recorded as used, so an unopened shortcut can be spotted later
    assert SavedFilter.query.get(f.id).use_count == 1


def test_opening_a_deleted_view_lands_on_the_listing(client, db, cs_user):
    """Muscle memory outliving a filter is not worth a 404 page."""
    login(client, 'cs@test.com')
    r = client.get('/saved-filters/open/999999')
    assert r.status_code == 302 and '/cs/posts' in r.headers['Location']


def test_saving_from_the_listing_keeps_only_the_filters(client, db, cs_user, agent):
    login(client, 'cs@test.com')
    r = client.post('/saved-filters/save', data={
        'name': 'Today ex-DEL', 'from': 'cs', 'dep': 'today', 'origin': 'DEL',
        'page': '3', 'q': 'ignored-by-the-engine'})
    assert r.status_code == 302
    f = SavedFilter.query.filter_by(owner_id=agent.id).one()
    assert f.params == {'dep': 'today', 'origin': 'DEL'}    # no paging, no free-text


def test_the_manage_screen_is_staff_only(client, db, other_user):
    login(client, 'alice@test.com')
    r = client.get('/saved-filters/', follow_redirects=False)
    assert r.status_code == 302 and '/saved-filters' not in r.headers['Location']
