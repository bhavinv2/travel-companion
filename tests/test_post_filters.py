"""The shared post-filter engine, and the popup both consoles render from it.

Two things are being protected here. One: every filter has to produce valid SQL on both the
Postgres of production and the SQLite of these tests — the JSON-array filters are the ones that
have bitten before, because these columns are `json`, not `jsonb`. Two: filters have to AND,
which is the whole point of the popup — "posted this week AND departing in March AND arriving in
Dallas" must narrow three times, not return the union.
"""
from datetime import date, datetime, timedelta

import pytest

from conftest import login, logout
from app import db as _db
from app.models import CompanionRequest, ContactPoint
from app.services import post_filters

SOON = date.today() + timedelta(days=5)
LATER = date.today() + timedelta(days=90)


@pytest.fixture()
def posts(app, db):
    """Two live posts with deliberately opposite attributes, plus a closed one."""
    def mk(**kw):
        status = kw.pop('status', 'open')
        fields = dict(travel_type='air', trip_type='one_way', role='seeking_help', source='whatsapp')
        fields.update(kw)                      # a caller's own trip_type/role/source wins
        trip = CompanionRequest(**fields)
        trip.set_status(status)
        _db.session.add(trip)
        return trip

    ravi = mk(poster_name='Ravi', flying_from='Hyderabad (HYD)', destination='Dallas (DFW)',
              origin_iata='HYD', dest_iata='DFW', from_date=SOON, airline='Qatar Airways',
              flight_number='QR573', traveler_age_group='60_plus', traveler_gender='female',
              traveller_needs=['wheelchair'], preferred_languages=['Telugu'],
              category='Family visit', on_behalf_of='mother', ticket_booked=True)
    lakshmi = mk(poster_name='Lakshmi', flying_from='Mumbai (BOM)', destination='London (LHR)',
                 origin_iata='BOM', dest_iata='LHR', from_date=LATER,
                 to_date=LATER + timedelta(days=20), trip_type='round_trip',
                 airline='British Airways', flight_number='BA138', traveller_needs=['toddler'],
                 preferred_languages=['Hindi'], source='facebook', role='offering_help',
                 from_date_flexible=True)
    gone = mk(poster_name='Travelled', flying_from='Delhi (DEL)', destination='Toronto (YYZ)',
              origin_iata='DEL', dest_iata='YYZ', from_date=SOON, status='closed')
    _db.session.flush()
    _db.session.add(ContactPoint(trip=ravi, type='whatsapp', value='+91 90000 00001',
                                 consent_to_share=True))
    _db.session.add(ContactPoint(trip=lakshmi, type='email', value='l@example.com',
                                 consent_to_share=False))
    _db.session.commit()
    return {'ravi': ravi.id, 'lakshmi': lakshmi.id, 'closed': gone.id}


def listed(client, url, posts):
    """Which fixture posts a listing page shows."""
    html = client.get(url).data.decode()
    return {name for name, tid in posts.items()
            if '#%d<' % tid in html or 'trip-%d"' % tid in html}


# ---------------------------------------------------------------------------
# One filter at a time, through the CS list
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('query, expected', [
    ('', {'ravi', 'lakshmi'}),                              # closed is not working stock
    ('status=closed', {'closed'}),
    ('status=open', {'ravi', 'lakshmi'}),
    ('dest=DFW', {'ravi'}),                                 # IATA
    ('dest=Dallas', {'ravi'}),                              # or the display name
    ('origin=Mumbai', {'lakshmi'}),
    ('airline=qatar', {'ravi'}),                            # case-insensitive
    ('flight=BA138', {'lakshmi'}),
    ('trip_type=round_trip', {'lakshmi'}),
    ('flex=yes', {'lakshmi'}),
    ('flex=no', {'ravi'}),
    ('ticket=yes', {'ravi'}),
    ('source=facebook', {'lakshmi'}),
    ('role=offering_help', {'lakshmi'}),
    ('category=Family+visit', {'ravi'}),
    ('age=60_plus', {'ravi'}),
    ('gender=female', {'ravi'}),
    ('need=wheelchair', {'ravi'}),                          # JSON array column
    ('need=toddler', {'lakshmi'}),
    ('language=Telugu', {'ravi'}),                          # JSON array column
    ('on_behalf=mother', {'ravi'}),
    ('contact_type=whatsapp', {'ravi'}),
    ('contact_type=email', {'lakshmi'}),
    ('consent=yes', {'ravi'}),
    ('consent=no', {'lakshmi'}),
    ('matched=no', {'ravi', 'lakshmi'}),                    # nothing is matched in this fixture
    ('matched=yes', set()),
    ('claimed=no', {'ravi', 'lakshmi'}),
])
def test_each_filter_narrows_the_cs_list(client, cs_user, posts, query, expected):
    login(client, 'cs@test.com')
    assert listed(client, '/cs/posts?' + query, posts) == expected


def test_date_filters_read_the_right_column(client, cs_user, posts):
    login(client, 'cs@test.com')
    mid = (date.today() + timedelta(days=30)).isoformat()
    assert listed(client, '/cs/posts?dep_from=%s' % mid, posts) == {'lakshmi'}
    assert listed(client, '/cs/posts?dep_to=%s' % mid, posts) == {'ravi'}
    # only the round trip has a return date at all
    assert listed(client, '/cs/posts?ret_from=%s' % LATER.isoformat(), posts) == {'lakshmi'}
    # posted-on is about when it reached us, not when anyone flies. created_at is UTC and the
    # listings print it as UTC, so the range is UTC -- which only differs from the local date
    # for part of the day, and that is exactly when this used to break.
    utc_today = datetime.utcnow().date()
    assert listed(client, '/cs/posts?posted_from=%s' % utc_today.isoformat(), posts) == {'ravi', 'lakshmi'}
    assert listed(client, '/cs/posts?posted_to=%s' % (utc_today - timedelta(days=1)).isoformat(), posts) == set()
    # today counts as "posted on or before today" -- the whole day, not midnight
    assert listed(client, '/cs/posts?posted_to=%s' % utc_today.isoformat(), posts) == {'ravi', 'lakshmi'}


def test_a_date_range_is_one_filter_with_two_bounds(client, cs_user, posts):
    """dep_from/dep_to are two URL params but one idea -- one control, one chip."""
    login(client, 'cs@test.com')
    soon = (date.today() + timedelta(days=10)).isoformat()
    html = client.get('/cs/posts?dep_from=%s&dep_to=%s' % (date.today().isoformat(), soon)).data.decode()
    assert html.count('data-pf-clear="dep_from,dep_to"') == 1        # one chip, clearing both
    assert 'Departure:' in html
    assert listed(client, '/cs/posts?dep_from=%s&dep_to=%s' % (date.today().isoformat(), soon), posts) == {'ravi'}


def test_a_backwards_range_is_read_the_way_it_was_meant(client, cs_user, posts):
    """Typing the later date first is a slip, not a request for nothing."""
    login(client, 'cs@test.com')
    late, early = (date.today() + timedelta(days=10)).isoformat(), date.today().isoformat()
    assert listed(client, '/cs/posts?dep_from=%s&dep_to=%s' % (late, early), posts) == {'ravi'}


def test_filters_combine_by_narrowing(client, cs_user, posts):
    """The ask: date, then date + departure, then date + departure + arrival."""
    login(client, 'cs@test.com')
    today = date.today().isoformat()
    assert listed(client, '/cs/posts?dep_from=%s' % today, posts) == {'ravi', 'lakshmi'}
    assert listed(client, '/cs/posts?dep_from=%s&origin=Mumbai' % today, posts) == {'lakshmi'}
    assert listed(client, '/cs/posts?dep_from=%s&origin=Mumbai&dest=London' % today, posts) == {'lakshmi'}
    # contradictory filters return nothing rather than the union
    assert listed(client, '/cs/posts?origin=Mumbai&dest=Dallas', posts) == set()
    assert listed(client, '/cs/posts?need=wheelchair&source=facebook', posts) == set()


def test_free_text_search_still_works_alongside_the_filters(client, cs_user, posts):
    login(client, 'cs@test.com')
    assert listed(client, '/cs/posts?q=Ravi', posts) == {'ravi'}
    assert listed(client, '/cs/posts?q=Ravi&need=toddler', posts) == set()


def test_a_hand_edited_url_cannot_break_the_page(client, cs_user, posts):
    """Anything unparseable is ignored: staff share these URLs, and a typo must not 500."""
    login(client, 'cs@test.com')
    junk = ('dep_from=yesterday&dep_to=%40%40&days=lots&status=deleted&trip_type=teleport'
            '&age=ancient&gender=%3Cscript%3E&consent=maybe&matched=perhaps&language=Klingon')
    r = client.get('/cs/posts?' + junk)
    assert r.status_code == 200
    assert listed(client, '/cs/posts?' + junk, posts) == {'ravi', 'lakshmi'}
    # none of it counts as an applied filter, so none of it reaches the chips or the dropdowns
    html = r.data.decode()
    for key in ('dep_from,dep_to', 'status', 'trip_type', 'age', 'gender',
                'consent', 'matched', 'language'):
        assert 'data-pf-clear="%s"' % key not in html, key


# ---------------------------------------------------------------------------
# Admin listings: same engine, different default
# ---------------------------------------------------------------------------

def test_admin_listings_take_the_same_filters(client, admin_user, posts):
    login(client, 'admin@test.com')
    assert listed(client, '/admin/listings', posts) == {'ravi', 'lakshmi', 'closed'}
    assert listed(client, '/admin/listings?status=open', posts) == {'ravi', 'lakshmi'}
    assert listed(client, '/admin/listings?dest=Toronto', posts) == {'closed'}
    assert listed(client, '/admin/listings?need=toddler', posts) == {'lakshmi'}
    window = 'dep_from=%s&dep_to=%s' % (date.today().isoformat(),
                                        (date.today() + timedelta(days=10)).isoformat())
    assert listed(client, '/admin/listings?' + window, posts) == {'ravi', 'closed'}


def test_the_two_consoles_differ_only_in_the_closed_default(client, cs_user, admin_user, posts):
    """CS works the live queue; admin is the archive view and shows everything."""
    login(client, 'cs@test.com')
    assert 'closed' not in listed(client, '/cs/posts', posts)
    logout(client)
    login(client, 'admin@test.com')
    assert 'closed' in listed(client, '/admin/listings', posts)


# ---------------------------------------------------------------------------
# The popup markup
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('who, url', [
    ('cs@test.com', '/cs/posts?dest=DFW&need=wheelchair'),
    ('admin@test.com', '/admin/listings?dest=DFW&need=wheelchair'),
])
def test_both_pages_render_the_same_drawer(client, cs_user, admin_user, posts, who, url):
    login(client, who)
    html = client.get(url).data.decode()

    assert 'id="pfDrawer"' in html
    # inside the filter form, which is what lets the existing form serialisation carry the fields
    assert html.index('id="pfDrawer"') > html.index('class="cs-filters"')
    # every declared filter has an input -- a range contributes its two date params
    for key, field in post_filters.FIELDS.items():
        names = [field['from_key'], field['to_key']] if field['kind'] == 'daterange' else [key]
        for name in names:
            assert 'name="%s"' % name in html, name
    # the applied ones come back as removable chips, and the button carries the count
    assert 'data-pf-clear="dest"' in html and 'data-pf-clear="need"' in html
    assert 'pf-count' in html
    assert 'Wheelchair Assistance' in html          # chip shows the label, not the raw value


def test_no_filter_means_no_chips_and_no_count(client, cs_user, posts):
    login(client, 'cs@test.com')
    html = client.get('/cs/posts').data.decode()
    assert 'id="pfDrawer"' in html                  # the drawer is always available
    assert 'pf-chip' not in html and 'pf-count' not in html


def test_one_control_per_date_idea(client, cs_user, posts):
    """The complaint that started this: six date boxes for three ideas is unreadable.

    Each range is a single preset dropdown; the two exact-date boxes belong to it and stay hidden
    until someone asks for them.
    """
    login(client, 'cs@test.com')
    html = client.get('/cs/posts').data.decode()
    drawer = html[html.index('id="pfDrawer"'):]

    ranges = [f for f in post_filters.FIELDS.values() if f['kind'] == 'daterange']
    assert len(ranges) == 3                                  # departure, return, posted
    assert drawer.count('data-pf-preset') == 3               # one control each
    assert drawer.count('data-pf-dates') == 3                # ...and one hidden pair each
    assert 'name="days"' not in drawer                       # the old duplicate window is gone


def test_the_route_fields_offer_the_same_autocomplete_as_the_post_form(client, cs_user, posts):
    """Nobody should have to guess how a city is spelled in our data."""
    login(client, 'cs@test.com')
    html = client.get('/cs/posts').data.decode()
    assert 'class="autocomplete-airport"' in html
    assert 'class="autocomplete-airline"' in html


# ---------------------------------------------------------------------------
# Engine-level
# ---------------------------------------------------------------------------

def test_every_declared_filter_builds_runnable_sql(app, db):
    """A filter that only breaks when someone picks it is worse than no filter."""
    samples = {
        'dep': {'dep_from': '2099-01-01', 'dep_to': '2099-12-31'},
        'ret': {'ret_from': '2099-02-01', 'ret_to': '2099-03-01'},
        'posted': {'posted_from': '2026-01-01', 'posted_to': '2026-12-31'},
        'flex': {'flex': 'yes'}, 'origin': {'origin': 'Hyderabad'}, 'dest': {'dest': 'DFW'},
        'airline': {'airline': 'Qatar'}, 'flight': {'flight': 'QR573'},
        'trip_type': {'trip_type': 'round_trip'}, 'ticket': {'ticket': 'no'},
        'status': {'status': 'open'}, 'source': {'source': 'facebook'},
        'role': {'role': 'seeking_help'}, 'category': {'category': 'Family visit'},
        'matched': {'matched': 'no'}, 'claimed': {'claimed': 'yes'}, 'anon': {'anon': 'no'},
        'age': {'age': '60_plus'}, 'gender': {'gender': 'female'},
        'pref_gender': {'pref_gender': 'female'}, 'need': {'need': 'wheelchair'},
        'language': {'language': 'Telugu'}, 'on_behalf': {'on_behalf': 'mother'},
        'contact_type': {'contact_type': 'whatsapp'}, 'consent': {'consent': 'yes'},
    }
    assert set(samples) == set(post_filters.FIELDS), 'a filter was added without a sample here'

    from werkzeug.datastructures import MultiDict
    everything = {}
    for key, args in samples.items():
        query, active = post_filters.apply(CompanionRequest.query, MultiDict(args))
        query.count()                       # executes; raises if the SQL is malformed
        assert list(active) == [key], key
        everything.update(args)

    # and all of them at once, which is what a keen user will do
    query, active = post_filters.apply(CompanionRequest.query, MultiDict(everything))
    assert query.count() == 0 and len(active) == len(samples)


def test_chips_read_in_drawer_order_with_human_labels(app, db):
    from werkzeug.datastructures import MultiDict
    _, active = post_filters.apply(CompanionRequest.query,
                                   MultiDict({'need': 'wheelchair', 'dep_from': '2099-01-01',
                                              'flex': 'yes'}))
    chips = post_filters.chips(active)
    assert [c['key'] for c in chips] == ['dep', 'flex', 'need']            # declaration order
    assert [c['value'] for c in chips] == ['from 01 Jan 2099', 'Yes', 'Wheelchair Assistance']
    assert [c['label'] for c in chips] == ['Departure', 'Dates flexible', 'Assistance needed']
    # a chip has to know every param it owns, or its X leaves half the filter behind
    assert [c['params'] for c in chips] == [['dep_from', 'dep_to'], ['flex'], ['need']]


def test_a_range_chip_reads_as_one_phrase(app, db):
    from werkzeug.datastructures import MultiDict
    for args, want in [({'dep_from': '2099-01-01', 'dep_to': '2099-03-04'},
                        '01 Jan 2099 to 04 Mar 2099'),
                       ({'dep_from': '2099-01-01'}, 'from 01 Jan 2099'),
                       ({'dep_to': '2099-03-04'}, 'until 04 Mar 2099')]:
        _, active = post_filters.apply(CompanionRequest.query, MultiDict(args))
        assert post_filters.chips(active)[0]['value'] == want


def test_sorting_covers_every_offered_option(app, db):
    for value, _label in post_filters.SORTS:
        post_filters.sort_query(CompanionRequest.query, value).count()
    # an unknown sort falls back rather than failing
    post_filters.sort_query(CompanionRequest.query, 'sideways').count()
