"""Multi-role accounts, admin-created accounts and the configurable option lists (/admin/options)."""
import re

from conftest import login, logout, make_user, TRIP_JSON
from app import options
from app.models import User, CompanionRequest
from app.services import locations


def _roles_rows(extra=()):
    return [dict(r) for r in options.DEFAULT_USER_ROLES] + list(extra)


# ---------------------------------------------------------------------------
# Multi-role accounts
# ---------------------------------------------------------------------------

def test_multi_role_account_switches_between_staff_and_traveller_views(client, db, user):
    user.set_roles(['user', 'cs'])
    db.session.commit()
    assert user.is_cs and not user.is_admin and user.is_traveller and user.effective_role == 'cs'
    assert user.role_keys == ['user', 'cs']
    assert login(client, 'bob@test.com').headers['Location'].endswith('/auth/choose-portal')  # multi-role: pick a portal
    assert client.get('/auth/choose-portal?to=cs').headers['Location'].endswith('/cs/')
    assert client.get('/dashboard').headers['Location'].endswith('/cs/')
    html = client.get('/cs/').data.decode()
    assert 'portal-switch' in html and 'Traveller</span>' in html      # switcher, not a separate row
    assert client.get('/switch-view/traveller').headers['Location'].endswith('/dashboard')
    page = client.get('/dashboard')
    assert page.status_code == 200
    html = page.data.decode()
    assert 'All Trips' in html and 'portal-switch' in html and 'staff-tag' not in html
    assert client.get('/cs/').status_code == 200                                     # CS console still allowed
    client.get('/switch-view/staff')
    assert client.get('/dashboard').status_code == 302
    logout(client)
    # a pure CS account has no traveller view to switch to
    make_user('agent@test.com', 'agent', role='cs')
    login(client, 'agent@test.com')
    assert client.get('/switch-view/traveller').headers['Location'].endswith('/cs/')
    assert client.get('/dashboard').status_code == 302
    logout(client)
    assert client.get('/dashboard').status_code == 302                              # view flag gone after logout


def test_legacy_rows_and_default_roles(client, db, user, admin_user):
    assert user.roles == ['user'] and admin_user.roles == ['admin']                 # filled on insert
    legacy = User(email='old@test.com', username='old', role='cs', is_admin=False)
    legacy.set_password('password123')
    legacy.roles = None
    db.session.add(legacy)
    db.session.commit()
    legacy.roles = None                                                             # simulate a pre-migration row
    assert legacy.role_keys == ['cs'] and legacy.is_cs


def test_admin_assigns_roles(client, db, user, admin_user):
    login(client, 'admin@test.com')
    r = client.post(f'/admin/users/{user.id}/roles', json={'roles': ['user', 'cs']})
    assert r.status_code == 200 and r.get_json()['level'] == 'cs'
    assert db.session.get(User, user.id).is_cs
    r = client.post(f'/admin/users/{user.id}/roles', json={'roles': ['admin']})
    assert r.get_json()['level'] == 'admin' and db.session.get(User, user.id).is_admin
    r = client.post(f'/admin/users/{user.id}/roles', json={'roles': []})
    assert r.get_json()['roles'] == ['user'] and not db.session.get(User, user.id).is_cs
    assert client.post(f'/admin/users/{user.id}/roles', json={'roles': ['ninja']}).status_code == 400
    assert client.post(f'/admin/users/{admin_user.id}/roles', json={'roles': ['user']}).status_code == 400
    html = client.get('/admin/users').data.decode()
    assert 'Add account' in html and f'id="roles-{user.id}"' in html
    logout(client)
    login(client, 'bob@test.com')
    assert client.post(f'/admin/users/{user.id}/roles', json={'roles': ['admin']}).status_code == 302


def test_custom_role_with_cs_access_level(client, db, user, admin_user):
    login(client, 'admin@test.com')
    r = client.post('/admin/options/roles', json={'items': _roles_rows([{'key': 'moderator', 'label': 'Moderator', 'level': 'cs'}])})
    assert r.status_code == 200, r.get_json()
    assert options.role_level('moderator') == 'cs'
    assert client.post(f'/admin/users/{user.id}/roles', json={'roles': ['moderator']}).get_json()['level'] == 'cs'
    html = client.get('/admin/users').data.decode()
    assert 'Moderator' in html
    logout(client)
    assert login(client, 'bob@test.com').headers['Location'].endswith('/cs/')
    assert client.get('/cs/').status_code == 200
    logout(client)
    # lowering the role's level re-syncs every account holding it
    login(client, 'admin@test.com')
    client.post('/admin/options/roles', json={'items': _roles_rows([{'key': 'moderator', 'label': 'Moderator', 'level': 'user'}])})
    assert not db.session.get(User, user.id).is_cs
    # built-ins cannot be dropped or re-levelled
    r = client.post('/admin/options/roles', json={'items': [{'key': 'admin', 'label': 'Boss', 'level': 'user'}]})
    keys = {x['key']: x for x in r.get_json()['rows']}
    assert set(keys) >= {'user', 'cs', 'admin'} and keys['admin']['level'] == 'admin' and keys['admin']['label'] == 'Boss'


# ---------------------------------------------------------------------------
# Admin creates accounts
# ---------------------------------------------------------------------------

def test_admin_creates_account_with_generated_password(client, db, admin_user):
    login(client, 'admin@test.com')
    assert client.get('/admin/users/new').status_code == 200
    r = client.post('/admin/users/new', data={'email': 'New.Agent@test.com', 'username': 'newagent', 'first_name': 'Nia',
                                              'roles': ['user', 'cs']}, follow_redirects=True)
    assert r.status_code == 200
    m = re.search(r'Temporary password for new\.agent@test\.com: (\S+) -', r.data.decode())
    assert m, 'generated password not shown'
    u = User.query.filter_by(email='new.agent@test.com').first()
    assert u.is_verified and u.role_keys == ['user', 'cs'] and u.is_cs
    logout(client)
    assert login(client, 'new.agent@test.com', m.group(1)).headers['Location'].endswith('/auth/choose-portal')
    assert client.get('/auth/choose-portal?to=cs').headers['Location'].endswith('/cs/')
    logout(client)
    # explicit password, duplicates rejected
    login(client, 'admin@test.com')
    r = client.post('/admin/users/new', data={'email': 'new.agent@test.com', 'username': 'other', 'password': 'Secret#123'})
    assert r.status_code == 200 and b'already registered' in r.data
    r = client.post('/admin/users/new', data={'email': 'two@test.com', 'username': 'newagent', 'password': 'short'})
    assert b'already taken' in r.data and b'at least 8' in r.data
    r = client.post('/admin/users/new', data={'email': 'two@test.com', 'username': 'two', 'password': 'Secret#123'})
    assert r.status_code == 302 and User.query.filter_by(email='two@test.com').first().role_keys == ['user']


# ---------------------------------------------------------------------------
# Configurable option lists
# ---------------------------------------------------------------------------

def test_pager_windows_long_page_lists(client, db, admin_user):
    # 30 users at 2 per page -> 16 pages; the pager must window with ellipses, not list all 16
    for i in range(28):
        make_user(f'p{i:02d}@test.com', f'pager{i:02d}')
    html = client.get('/auth/login') and None
    login(client, 'admin@test.com')
    html = client.get('/admin/users?per_page=2&page=8').data.decode()
    pager = html.split('class="pagination"')[1].split('</div>')[0]
    assert '<span class="page current">8</span>' in pager and '&hellip;' in pager
    assert '>1<' in pager and '>7<' in pager and '>9<' in pager
    assert '>5<' not in pager and '>11<' not in pager          # windowed, not every page


def test_admin_lists_are_paginated(client, db, admin_user, user, other_user):
    login(client, 'admin@test.com')
    html = client.get('/admin/users?per_page=2').data.decode()
    assert '<span class="page current">1</span>' in html and '&rsaquo;' in html and 'pg-arrow' in html
    html = client.get('/admin/users?per_page=2&page=2').data.decode()
    assert '<span class="page current">2</span>' in html and '&lsaquo;' in html
    assert 'pg-arrow' not in client.get('/admin/users').data.decode()   # a single page shows no pager
    assert client.get('/admin/listings').status_code == 200
    # contact + feedback were merged into User Voices; the old URLs keep working as redirects
    for old_url, tab in (('/admin/feedback', 'feedback'), ('/admin/contact', 'contact')):
        r = client.get(old_url)
        assert r.status_code == 302 and f'tab={tab}' in r.headers['Location']
    assert client.get('/admin/voices?tab=feedback').status_code == 200


def test_options_page_and_lists_drive_the_forms(client, db, admin_user, user):
    login(client, 'admin@test.com')
    html = client.get('/admin/options').data.decode()
    for title in ('Languages', 'Post categories', 'User roles', 'Airports', 'Airlines', 'Traveller needs'):
        assert title in html
    r = client.post('/admin/options/languages', json={'items': [{'value': 'English'}, {'value': ' Konkani '}]})
    assert r.status_code == 200 and r.get_json()['customised'] is True
    assert options.get_list('languages') == ['English', 'Konkani'] and options.LANGUAGES == ['English', 'Konkani']
    assert client.post('/admin/options/languages', json={'items': [{'value': 'Hindi'}, {'value': 'hindi'}]}).status_code == 400
    assert client.post('/admin/options/languages', json={'items': []}).status_code == 400
    r = client.post('/admin/options/categories', json={'items': [{'value': 'Medical travel'}, {'value': 'Wedding'}]})
    assert r.status_code == 200
    r = client.post('/admin/options/traveller_needs', json={'items': [{'key': '', 'label': 'Sign language'}, ['wheelchair', 'Wheelchair']]})
    assert r.status_code == 200 and options.get_list('traveller_needs') == [('sign_language', 'Sign language'), ('wheelchair', 'Wheelchair')]
    assert client.post('/admin/options/on_behalf_of', json={'items': [{'key': 'x', 'label': 'A'}, {'key': 'x', 'label': 'B'}]}).status_code == 400
    assert client.get('/admin/options/nope', json={}).status_code == 404 or client.post('/admin/options/nope', json={}).status_code == 404
    # CS form shows the new category and stores it
    html = client.get('/cs/posts/new').data.decode()
    assert 'Wedding' in html and 'Konkani' in html and 'Sign language' in html
    logout(client)
    # traveller sees the new values on the post form and dashboard filter and can save a category
    login(client, 'bob@test.com')
    client.get('/switch-view/traveller')
    assert 'Wedding' in client.get('/').data.decode() and 'Konkani' in client.get('/dashboard').data.decode()
    r = client.post('/api/post-trip', json={**TRIP_JSON, 'from_date': '2099-12-01', 'category': 'Wedding'})
    assert r.status_code == 201 and CompanionRequest.query.first().category == 'Wedding'
    logout(client)
    # reset brings the defaults back
    login(client, 'admin@test.com')
    r = client.post('/admin/options/languages/reset', json={})
    assert r.get_json()['customised'] is False and 'Telugu' in options.get_list('languages')


def test_airports_in_db_and_extra_airlines(client, db, admin_user):
    login(client, 'admin@test.com')
    # unseeded table falls back to the bundled list, so the app still knows every airport
    assert locations.normalize_location('HYD')['city'] == 'Hyderabad'
    r = client.post('/admin/options/airports/add', json={'iata': 'zzq', 'name': 'Testville International', 'city': 'Testville', 'country': 'IN'})
    assert r.status_code == 200, r.get_json()
    airport_id = r.get_json()['airport']['id']
    codes = [a['iata'] for a in client.get('/api/airports?q=testv').get_json()]
    assert 'ZZQ' in codes
    hit = locations.normalize_location('Testville')
    assert hit and hit['iata'] == 'ZZQ' and hit['display'] == 'Testville (ZZQ)'
    assert locations.normalize_location('zzq')['city'] == 'Testville'
    d = client.get('/admin/options/airports/search?q=testv').get_json()
    assert d['custom'] == 1 and d['results'][0]['iata'] == 'ZZQ' and d['results'][0]['custom']
    assert d['total'] > 8000                                                        # merged list, not just customs
    assert 'HYD' in [a['iata'] for a in client.get('/admin/options/airports/search?q=hyderabad').get_json()['results']]
    assert client.get('/admin/options/airports/search').get_json()['results'][0]['iata'] == 'ZZQ'
    # pagination: stable pages, clamped overflow, every page distinct
    d1 = client.get('/admin/options/airports/search?page=1&per_page=5').get_json()
    d2 = client.get('/admin/options/airports/search?page=2&per_page=5').get_json()
    assert d1['pages'] > 1 and len(d1['results']) == 5 and d2['page'] == 2
    assert [a['iata'] for a in d1['results']] != [a['iata'] for a in d2['results']]
    assert client.get('/admin/options/airports/search?page=99999&per_page=5').get_json()['page'] == d1['pages']
    assert client.get('/admin/options/airports/search?q=hyderabad&per_page=2').get_json()['matches'] >= 2
    assert client.post('/admin/options/airports/add', json={'iata': 'HYD', 'name': 'Dup'}).status_code == 400
    assert client.post('/admin/options/airports/add', json={'iata': 'ZZQQ', 'name': 'Bad'}).status_code == 400
    assert client.post('/admin/options/airports/add', json={'iata': 'ZQ1', 'name': ''}).status_code == 400
    # custom rows can be deleted, built-in DB rows cannot
    from app.models import Airport
    db.session.add(Airport(iata='QQ1', name='Base Field', city='Basetown', is_custom=False))
    db.session.commit()
    base_id = Airport.query.filter_by(iata='QQ1').first().id
    assert client.post(f'/admin/options/airports/{base_id}/delete', json={}).status_code == 400
    assert client.post(f'/admin/options/airports/{airport_id}/delete', json={}).get_json()['success']
    locations.reset_cache()
    # airlines: also DB-backed (file fallback while the table is unseeded)
    from app.services import airlines as airlines_svc
    from app.services.importer import _airline_name
    assert airlines_svc.name_for('QR') == 'Qatar Airways'
    code = next(c for c in ('ZZQ', 'ZZ9', 'Q9Z') if not airlines_svc.name_for(c))
    r = client.post('/admin/options/airlines/add', json={'iata': code.lower(), 'name': 'Zed Air', 'country': 'IN'})
    assert r.status_code == 200, r.get_json()
    airline_id = r.get_json()['airline']['id']
    assert any(a['iata'] == code for a in client.get('/api/airlines?q=zed').get_json())
    assert _airline_name(code.lower()) == 'Zed Air'
    d = client.get('/admin/options/airlines/search?q=zed').get_json()
    assert d['results'][0]['iata'] == code and d['results'][0]['custom'] and d['custom'] == 1
    assert client.post('/admin/options/airlines/add', json={'iata': 'QR', 'name': 'Dup'}).status_code == 400
    assert client.post('/admin/options/airlines/add', json={'iata': 'TOOLONG', 'name': 'Bad'}).status_code == 400
    assert client.post(f'/admin/options/airlines/{airline_id}/delete', json={}).get_json()['success']
    assert _airline_name(code) is None
    assert locations.normalize_location('Testville') is None
