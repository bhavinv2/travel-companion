"""The filter panel's /api/search parameters and its presence on the three trip screens."""
from datetime import date, timedelta

from conftest import login, make_user
from test_matching import _make
from app import db as _db


D20 = date.today() + timedelta(days=20)
D25 = date.today() + timedelta(days=25)


def _ids(res):
    return sorted(r['id'] for r in res.get_json()['results'])


def test_search_filters_by_booking_status(app, db, client, user, other_user):
    booked = _make(db, user, ticket_booked=True)
    planned = _make(db, other_user, ticket_booked=False)
    assert _ids(client.post('/api/search', json={'booking': 'booked'})) == [booked.id]
    assert _ids(client.post('/api/search', json={'booking': 'planned'})) == [planned.id]
    assert _ids(client.post('/api/search', json={})) == sorted([booked.id, planned.id])


def test_search_filters_by_trip_type(app, db, client, user, other_user):
    oneway = _make(db, user)                                 # one_way (the _make default)
    multi = _make(db, other_user, trip_type='multi_destination', flying_from=None, destination=None,
                  legs=[{'from': 'Hyderabad (HYD)', 'to': 'Dubai (DXB)', 'date': D20.isoformat()},
                        {'from': 'Dubai (DXB)', 'to': 'Dallas (DFW)', 'date': D20.isoformat()}])
    assert client.post('/api/search', json={}).get_json()['count'] == 2
    assert _ids(client.post('/api/search', json={'trip_types': ['one_way']})) == [oneway.id]
    assert _ids(client.post('/api/search', json={'trip_types': ['multi_destination']})) == [multi.id]
    assert _ids(client.post('/api/search', json={'trip_types': ['one_way', 'multi_destination']})) == sorted([oneway.id, multi.id])


def test_search_filters_by_companion_gender(app, db, client, user, other_user, third_user):
    f = _make(db, user, traveler_gender='female')
    m = _make(db, other_user, traveler_gender='male')
    _make(db, third_user)                                   # gender not given: hidden once filtering
    assert _ids(client.post('/api/search', json={'genders': ['female']})) == [f.id]
    assert _ids(client.post('/api/search', json={'genders': ['male', 'female']})) == sorted([f.id, m.id])
    assert client.post('/api/search', json={}).get_json()['count'] == 3


def test_search_verified_users_only(app, db, client, user, other_user):
    verified = _make(db, user)
    _make(db, other_user)
    user.is_verified = True
    _db.session.commit()
    assert _ids(client.post('/api/search', json={'verified_only': True})) == [verified.id]


def test_search_flex_days_widens_the_departure_window(app, db, client, user, other_user):
    on_day = _make(db, user, from_date=D20)
    later = _make(db, other_user, from_date=D25)
    day = D20.isoformat()
    assert _ids(client.post('/api/search', json={'from_date': day, 'flex_days': 0})) == [on_day.id]
    assert _ids(client.post('/api/search', json={'from_date': day, 'flex_days': 7})) == sorted([on_day.id, later.id])
    # without flex_days the old 3-day default window still applies
    assert _ids(client.post('/api/search', json={'from_date': day})) == [on_day.id]
    # nonsense flexibility falls back rather than erroring
    assert client.post('/api/search', json={'from_date': day, 'flex_days': 'lots'}).status_code == 200


def test_airport_search_ranks_the_meant_airport_first(app, client):
    """Typing an IATA or a city prefix must surface that airport, not a substring match that
    merely contains the letters (the bug: "del" showed Adelaide / Ciudad del Este, not Delhi)."""
    def first(q):
        r = client.get(f'/api/airports?q={q}')
        assert r.status_code == 200
        data = r.get_json()
        return data[0] if data else None

    top = first('del')
    assert top and top['iata'] == 'DEL', top          # exact IATA wins outright
    assert first('hyd')['iata'] == 'HYD'
    # a city-name prefix beats a mid-word substring
    cities = [a['city'] for a in client.get('/api/airports?q=mumb').get_json()]
    assert cities and cities[0] == 'Mumbai'


def test_filter_panel_renders_on_all_three_screens(app, db, client):
    page = client.get('/trips')
    assert page.status_code == 200
    assert b'atfPanel' in page.data and b'Booking status' in page.data and b'Verified users' in page.data

    make_user('filters@test.com', 'filters')
    login(client, 'filters@test.com')
    dash = client.get('/dashboard')
    assert dash.status_code == 200
    assert b'dafPanel' in dash.data                        # Desis on Move tab: full panel
    assert b'mtfPanel' in dash.data                        # My trips tab: reduced panel
    assert b'dafGender' in dash.data and b'mtfGender' not in dash.data  # reduced panel: no companion sections
