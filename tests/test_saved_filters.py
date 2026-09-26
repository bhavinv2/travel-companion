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


# ---------------------------------------------------------------------------
# The drawer has to submit the intent, or none of the above matters
# ---------------------------------------------------------------------------

def test_the_drawer_submits_the_preset_itself(client, db, cs_user):
    """The preset dropdown had no `name`, so it was never submitted: picking "Departing today"
    filled the two date boxes and the server only ever saw dep_from=…&dep_to=…. Every view saved
    through the UI would have frozen on the day it was made -- and the chip said so out loud,
    "Departure: 26 Sep 2026 to 26 Sep 2026". The whole feature turned on this one attribute."""
    login(client, 'cs@test.com')
    html = client.get('/cs/posts').data.decode()
    assert 'class="pf-preset" name="dep"' in html
    assert 'class="pf-preset" name="posted"' in html


def test_a_preset_in_the_url_is_shown_as_chosen(client, db, cs_user):
    """Coming back to a saved view, the drawer has to show the preset selected -- otherwise
    re-applying silently converts it into fixed dates."""
    login(client, 'cs@test.com')
    html = client.get('/cs/posts?dep=today').data.decode()
    dep = html.split('name="dep"', 1)[1].split('</select>', 1)[0]
    chosen = [line for line in dep.splitlines() if 'selected' in line]
    assert len(chosen) == 1 and 'Departing today' in chosen[0], chosen


def test_the_saved_views_bar_travels_with_the_results(db):
    """On the CS console a filter apply swaps in only the results fragment. The bar was left
    outside it, so its "Save this view" button never noticed that filters had been applied --
    which is why it looked like there was no way to save."""
    import os
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'app', 'templates', 'cs')
    partial = open(os.path.join(root, '_posts_results.html'), encoding='utf-8').read()
    outer = open(os.path.join(root, 'posts.html'), encoding='utf-8').read()
    assert 'saved_filter_bar(' in partial
    assert 'saved_filter_bar(' not in outer        # or it would render twice


def test_there_is_always_a_way_to_start(client, db, cs_user):
    """With no filters set there is nothing to save, but hiding the button meant somebody landing
    on the page had no visible route in. It stays, and opens the filters instead."""
    login(client, 'cs@test.com')
    html = client.get('/cs/posts').data.decode()
    assert 'Save this view' in html
    assert 'data-pf-open' in html.split('sv-bar-acts', 1)[1].split('</span>', 1)[0]


def test_a_new_view_is_marked_for_a_few_days(agent, db):
    """So a colleague who was off on Friday still notices a view shared while they were away --
    and so the strip is not permanently decorated once everyone has seen it."""
    from datetime import datetime, timedelta
    fresh = saved_filters.create(agent, 'Fresh', {'dep': 'today'})
    old = saved_filters.create(agent, 'Old', {'dep': 'tomorrow'})
    old.created_at = datetime.utcnow() - timedelta(days=saved_filters.NEW_FOR_DAYS + 1)
    _db.session.commit()
    _db.session.expire_all()

    by_name = {f.name: f for f in saved_filters.for_user(agent)}
    assert by_name['Fresh'].is_new is True
    assert by_name['Old'].is_new is False


def test_the_new_badge_shows_on_the_listing(client, db, cs_user, agent):
    saved_filters.create(agent, 'Just saved', {'dep': 'today'})
    login(client, 'cs@test.com')
    html = client.get('/cs/posts').data.decode()
    assert 'sv-new' in html and '>New<' in html


def test_saving_never_sends_you_to_a_bare_fragment(client, db, cs_user):
    """The CS console renders the results fragment alone when `partial` is set. The save form was
    copying every query param into hidden inputs, `partial` included, so the redirect after saving
    came back as unstyled markup with no layout at all."""
    login(client, 'cs@test.com')
    r = client.post('/saved-filters/save', data={
        'name': 'From a live filter', 'from': 'cs', 'dep': 'today',
        'partial': '1', 'page': '2', 'view': '7'})
    assert r.status_code == 302
    assert 'partial' not in r.headers['Location']
    assert 'page=' not in r.headers['Location']
    # and the stored filter is not polluted with them either
    f = SavedFilter.query.filter_by(name='From a live filter').one()
    assert f.params == {'dep': 'today'}


def test_rename_is_offered_as_a_real_control(client, db, cs_user, agent):
    """It was inside a <details> popover that clipped against the row below it."""
    saved_filters.create(agent, 'Needs a better name', {'dep': 'today'})
    login(client, 'cs@test.com')
    html = client.get('/saved-filters/?from=cs').data.decode()
    assert 'data-sv-rename' in html and 'svRenameDlg' in html
    assert '<details' not in html
    # the action is generated by Jinja, so it carries the app's URL prefix
    assert 'data-sv-rename="/saved-filters/' in html
