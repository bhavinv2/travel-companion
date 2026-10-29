"""The Promotion dashboard's engine, the Dashboard designer and Google Analytics (2026-10-29).

What is worth protecting: the numbers are right (India -> abroad is where a trip starts and ends, a filter and a
grouping combine, a time line has its zeros), no box can be made to print a person, leads stay with staff, a draft
is never on anybody's screen until it is published, and the Google key is sealed and never shown again.
"""
import base64
import json
import os
import re
import sys
from datetime import date, datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import login, logout, make_user  # noqa: E402
from app import db as _db  # noqa: E402
from app.models import CompanionRequest, ContactMessage, InsuranceQuote, MktDashboard  # noqa: E402


@pytest.fixture()
def influencer(app, db):
    u = make_user('promo@test.com', 'promo')
    u.set_roles(['user', 'influencer'])
    _db.session.commit()
    return u


@pytest.fixture()
def trips(app, db, user):
    now = datetime.utcnow()
    for i, (o, d) in enumerate([('HYD', 'DFW'), ('HYD', 'JFK'), ('BOM', 'LHR'), ('DFW', 'HYD'), ('BOM', 'DEL'),
                                ('LHR', 'JFK')]):
        _db.session.add(CompanionRequest(
            user_id=user.id, travel_type='air', trip_type='one_way', origin_iata=o, dest_iata=d, origin_city=o,
            dest_city=d, from_date=date.today() + timedelta(days=5 + i), created_at=now - timedelta(days=i % 3),
            role='seeking_help', status='open', poster_name='Asha Secret', traveler_name='Asha Secret',
            traveller_needs=['wheelchair'], preferred_languages=['Telugu']))
    _db.session.add(ContactMessage(name='Asha Secret', email='asha@example.com', message='a private message',
                                   topic='companion'))
    _db.session.add(InsuranceQuote(email='ravi@example.com', phone='+919800000000', insurance_type='visitors',
                                   citizenship='IND', start_date=date.today(), end_date=date.today() + timedelta(days=40),
                                   travellers=[{'age': '68'}, {'age': '71'}]))
    _db.session.commit()


def _run(raw, user=None, key='last_30'):
    from app.services import mkt_engine as eng
    return eng.run(eng.clean_box(raw), eng.period_for(key), user)


def _by_label(r):
    return dict(zip(r['labels'], r['series'][0]['data']))


# ================================================================================================ the numbers

def test_india_to_abroad_is_where_a_trip_starts_and_ends(app, trips, admin_user):
    with app.test_request_context('/'):
        r = _run({'chart': 'donut', 'metrics': [{'source': 'trips'}], 'group': 'direction'}, admin_user)
    assert _by_label(r) == {'India → abroad': 3, 'Abroad → India': 1, 'Within India': 1, 'Between other countries': 1}
    assert r['total'] == 6


def test_a_filter_and_a_grouping_combine(app, trips, admin_user):
    with app.test_request_context('/'):
        r = _run({'chart': 'hbar', 'metrics': [{'source': 'trips', 'filters': {'direction': ['India → abroad']}}],
                  'group': 'dest_country'}, admin_user)
    assert _by_label(r) == {'United States': 2, 'United Kingdom': 1}


def test_a_time_line_has_its_zeros_and_a_previous_period(app, trips, admin_user):
    with app.test_request_context('/'):
        r = _run({'chart': 'line', 'metrics': [{'source': 'trips'}], 'group': 'day'}, admin_user, key='last_7')
    assert len(r['labels']) == 7 and len(r['series'][0]['data']) == 7
    assert sum(r['series'][0]['data']) == r['total'] == 6
    assert r['prev'] == 0 and r['change'] is None, 'nothing the week before: no percentage to invent'


def test_upcoming_travel_looks_ahead(app, trips, admin_user):
    with app.test_request_context('/'):
        r = _run({'chart': 'stacked', 'metrics': [{'source': 'trips', 'date': 'travel'}], 'group': 'month',
                  'split': 'direction', 'range': 'next_90', 'compare': False}, admin_user)
    assert r['total'] == 6 and r['prev'] is None
    assert {s['name'] for s in r['series']} >= {'India → abroad', 'Abroad → India'}


def test_several_numbers_share_one_box(app, trips, admin_user):
    with app.test_request_context('/'):
        r = _run({'chart': 'line', 'metrics': [{'source': 'trips', 'label': 'Trips'},
                                               {'source': 'enquiries', 'label': 'Enquiries'}], 'group': 'auto'},
                 admin_user)
    assert [s['name'] for s in r['series']] == ['Trips', 'Enquiries']
    assert all(len(s['data']) == len(r['labels']) for s in r['series'])
    assert [s['total'] for s in r['series']] == [6, 1]


def test_insurance_counts_each_traveller_age(app, trips, admin_user):
    with app.test_request_context('/'):
        r = _run({'chart': 'bar', 'metrics': [{'source': 'insurance'}], 'group': 'ages'}, admin_user)
        d = _run({'chart': 'donut', 'metrics': [{'source': 'insurance'}], 'group': 'direction'}, admin_user)
    assert _by_label(r) == {'60–69': 1, '70–79': 1}
    assert _by_label(d) == {'India → abroad': 1}, 'visitors cover is the USA: an Indian citizen going there'


def test_the_dates(app):
    from app.services import mkt_engine as eng
    t = eng.today()
    assert eng.period_for('last_365').days == 365
    assert eng.auto_grain(eng.period_for('last_365')) == 'month'
    assert eng.auto_grain(eng.period_for('last_30')) == 'day'
    p = eng.period_for('custom', '2026-01-05', '2026-02-10')
    assert (p.start, p.end, p.days) == (date(2026, 1, 5), date(2026, 2, 10), 37)
    assert p.previous().end == date(2026, 1, 4) and p.previous().days == 37
    future = eng.period_for('custom', (t + timedelta(days=50)).isoformat(), (t + timedelta(days=90)).isoformat())
    assert future.end <= t, 'a custom period stops at today'
    assert eng.period_for('nonsense').key == 'last_30'
    assert len(eng.buckets(eng.period_for('all'), eng.fit_grain(eng.period_for('all'), 'day'))) <= eng.MAX_POINTS


def test_a_box_is_checked_against_the_catalogue(app):
    from app.services import mkt_engine as eng
    with app.test_request_context('/'):
        bad = [
            {'chart': 'nope', 'metrics': [{'source': 'trips'}]},
            {'chart': 'bar', 'metrics': [{'source': 'people_emails'}]},
            {'chart': 'bar', 'metrics': [{'source': 'trips', 'measure': 'DROP TABLE'}]},
            {'chart': 'bar', 'metrics': [{'source': 'trips'}], 'group': 'poster_name'},
            {'chart': 'bar', 'metrics': [{'source': 'trips', 'filters': {'email': ['x']}}]},
            {'chart': 'bar', 'metrics': [{'source': 'trips'}], 'group': 'direction', 'split': 'direction'},
            {'chart': 'bar', 'metrics': [{'source': 'website'}, {'source': 'trips'}], 'group': 'country'},
            {'chart': 'live', 'metrics': [{'source': 'website_now'}, {'source': 'trips'}]},
            {'chart': 'line', 'metrics': [{'source': 'website_now'}], 'group': 'day'},
        ]
        for raw in bad:
            with pytest.raises(eng.EngineError):
                eng.clean_box(raw)
        ok = eng.clean_box({'chart': 'line', 'metrics': [{'source': 'website'}, {'source': 'trips'}], 'group': 'month',
                            'x': 40, 'w': 99, 'title': 'x' * 500})
        assert ok['x'] == 11 and ok['w'] == 1 and len(ok['title']) == 90


def test_no_box_can_print_a_person(app, trips, admin_user):
    """Every dimension of every source of ours, on data full of a name, an e-mail and a phone number."""
    from app.services import mkt_engine as eng
    with app.test_request_context('/'):
        for s in eng.sources().values():
            if s.kind == 'ga':
                continue
            for d in s.dims:
                r = eng.run(eng.clean_box({'chart': 'table', 'metrics': [{'source': s.key}], 'group': d, 'top': 0}),
                            eng.period_for('all'), admin_user)
                text = json.dumps(r, ensure_ascii=False)
                for private in ('Asha', 'asha@example.com', 'ravi@example.com', '9800000000', 'a private message'):
                    assert private not in text, (s.key, d, private)


def test_lead_numbers_are_for_staff(app, influencer, admin_user):
    with app.test_request_context('/'):
        hidden = _run({'chart': 'number', 'metrics': [{'source': 'leads'}]}, influencer)
        shown = _run({'chart': 'number', 'metrics': [{'source': 'leads'}]}, admin_user)
    assert hidden['hidden'] and 'staff' in hidden['message']
    assert shown['ok'] and shown['total'] == 0


# ================================================================================================ the page

def test_the_overview_renders_for_any_dates(client, trips, influencer):
    login(client, influencer.email)
    for q in ('', '?range=last_7', '?range=last_365', '?range=all', '?range=custom&from=2026-01-01&to=2026-03-31',
              '?range=custom&from=junk&to=', '?range=yesterday&d=999'):
        r = client.get('/promotion' + q)
        assert r.status_code == 200, q
    html = client.get('/promotion?range=last_365').data.decode()
    assert 'Last 12 months' in html and 'From India: where they fly to' in html
    assert 'New leads' in html and 'Only staff see the numbers in this box.' in html


def test_a_website_box_is_fetched_after_the_page(client, influencer):
    login(client, influencer.email)
    html = client.get('/promotion').data.decode()
    assert re.search(r'data-box="o2"\s+data-chart="number" data-async="1"', html)
    r = client.get('/promotion/box?d=overview&b=o2&range=last_30').get_json()
    assert r['ok'] is False and 'not connected' in r['message']
    assert client.get('/promotion/box?d=overview&b=nope').status_code == 404
    assert client.get('/promotion/live').get_json() == {'ok': False, 'connected': False}


# ================================================================================================ the designer

def _box(**kw):
    out = {'id': 'a1', 'chart': 'hbar', 'title': 'From India', 'metrics': [{'source': 'trips', 'filters':
           {'direction': ['India → abroad']}}], 'group': 'dest_country', 'x': 0, 'y': 0, 'w': 6, 'h': 5}
    out.update(kw)
    return out


def test_a_dashboard_is_seen_only_once_it_is_published(client, trips, admin_user, influencer):
    login(client, admin_user.email)
    r = client.post('/promotion/designer/new', data={'name': 'Diwali campaign', 'start': 'blank'})
    d = MktDashboard.query.filter_by(name='Diwali campaign').one()
    assert r.status_code == 302 and r.headers['Location'].endswith('/promotion/designer/%d' % d.id)
    assert client.get('/promotion/designer/%d' % d.id).status_code == 200
    saved = client.post('/promotion/designer/%d/save' % d.id, json={'name': 'Diwali campaign', 'boxes': [
        _box(), _box(id='a2', title='Overlapping', x=2, y=1)]}).get_json()
    assert saved['ok'] and saved['published'] is False
    assert saved['boxes'][1]['y'] >= 5, 'a box laid over another is moved down'
    logout(client)

    login(client, influencer.email)
    assert 'Diwali campaign' not in client.get('/promotion').data.decode()
    html = client.get('/promotion?d=%d&draft=1' % d.id).data.decode()
    assert '>From India</h2>' not in html and 'Diwali campaign' not in html, 'no draft for them: the Overview'
    logout(client)

    login(client, admin_user.email)
    client.post('/promotion/designer/%d/publish' % d.id)
    logout(client)
    login(client, influencer.email)
    html = client.get('/promotion?d=%d' % d.id).data.decode()
    assert 'Diwali campaign' in html and 'United States' in html
    assert client.get('/promotion/box?d=%d&b=a1' % d.id).get_json()['total'] == 3


def test_changes_wait_for_publish(client, trips, admin_user):
    login(client, admin_user.email)
    d = MktDashboard(name='Routes', draft=[_box()], position=1)
    _db.session.add(d)
    _db.session.commit()
    client.post('/promotion/designer/%d/publish' % d.id)
    client.post('/promotion/designer/%d/save' % d.id, json={'boxes': [_box(title='A new title')]})
    _db.session.refresh(d)
    assert d.has_changes and d.published[0]['title'] == 'From India'
    assert 'A new title' not in client.get('/promotion?d=%d' % d.id).data.decode()
    assert 'A new title' in client.get('/promotion?d=%d&draft=1' % d.id).data.decode(), 'the designer sees the draft'
    client.post('/promotion/designer/%d/discard' % d.id)
    _db.session.refresh(d)
    assert not d.has_changes


def test_a_dashboard_for_designers_only(client, trips, admin_user, influencer):
    d = MktDashboard(name='Work in progress', draft=[_box()], published=[_box()], audience='designers', position=1)
    _db.session.add(d)
    _db.session.commit()
    login(client, influencer.email)
    assert 'Work in progress' not in client.get('/promotion').data.decode()
    logout(client)
    login(client, admin_user.email)
    assert 'Work in progress' in client.get('/promotion').data.decode()


def test_a_bad_box_is_refused_with_words(client, admin_user):
    login(client, admin_user.email)
    d = MktDashboard(name='X', draft=[], position=1)
    _db.session.add(d)
    _db.session.commit()
    r = client.post('/promotion/designer/%d/save' % d.id, json={'boxes': [_box(group='poster_name')]})
    assert r.status_code == 400 and 'Box 1' in r.get_json()['error']
    _db.session.refresh(d)
    assert d.draft == []


def test_previewing_changes_nothing(client, trips, admin_user):
    login(client, admin_user.email)
    before = MktDashboard.query.count()
    r = client.post('/promotion/designer/preview', json={'box': _box(), 'range': 'last_30'}).get_json()
    assert r['ok'] and r['total'] == 3 and r['title'] == 'From India'
    bad = client.post('/promotion/designer/preview', json={'box': _box(chart='nope')})
    assert bad.status_code == 400
    assert MktDashboard.query.count() == before
    vals = client.get('/promotion/designer/options?source=trips&dim=dest_country').get_json()
    assert vals['ok'] and 'United States' in vals['values']


def test_who_may_design(client, trips, admin_user, influencer):
    from app.models import WorkspaceRole
    from app.services import access, role_rights
    ws = access.ensure_defaults()
    head = WorkspaceRole(workspace_id=ws.id, name='Marketing head',
                         pages=role_rights.profile_pages(role_rights.PROFILE_BY_KEY['marketing_head']))
    team = WorkspaceRole(workspace_id=ws.id, name='Marketing team',
                         pages=role_rights.profile_pages(role_rights.PROFILE_BY_KEY['marketing']))
    _db.session.add_all([head, team])
    _db.session.commit()
    meera = make_user('meera@test.com', 'meera', role='cs')
    access.add_member(ws, meera, role=head)
    tom = make_user('tom@test.com', 'tom', role='cs')
    access.add_member(ws, tom, role=team)

    login(client, 'meera@test.com')
    assert client.get('/promotion/designer').status_code == 200
    assert client.get('/promotion/designer/google').status_code == 200
    nav = client.get('/promotion').data.decode().split('admin-nav-items', 1)[1].split('</nav>', 1)[0]
    assert 'Dashboard designer' in nav and 'href="/promotion"' in nav
    logout(client)

    for who in ('tom@test.com', influencer.email):
        login(client, who)
        assert client.get('/promotion').status_code == 200
        r = client.get('/promotion/designer')
        assert r.status_code == 302 and '/promotion/designer' not in r.headers['Location'], who
        assert client.post('/promotion/designer/new', data={'name': 'Mine'}).status_code in (302, 403)
        assert client.post('/promotion/designer/preview', json={'box': _box()}).status_code == 403
        logout(client)
    assert MktDashboard.query.count() == 0


def test_a_marketing_head_profile_is_offered(app):
    from app.services import role_rights
    keys = [p['key'] for p in role_rights.presets()]
    assert 'marketing_head' in keys and 'marketing' in keys
    head = role_rights.PROFILE_BY_KEY['marketing_head']
    assert set(role_rights.profile_pages(head)) >= {'promo', 'mkt_design'}
    assert 'mkt_design' not in role_rights.profile_pages(role_rights.PROFILE_BY_KEY['marketing'])


# ================================================================================================ Google Analytics

def _key():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    pk = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = pk.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                           serialization.NoEncryption()).decode()
    return pk, {'type': 'service_account', 'client_email': 'dash@proj.iam.gserviceaccount.com', 'private_key': pem,
                'token_uri': 'https://oauth2.googleapis.com/token'}


def test_the_sign_in_is_signed_with_the_key(app):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from app.services import ga4
    pk, key = _key()
    token = ga4._jwt(key, 1700000000)
    head, claims, sig = token.split('.')
    pad = lambda s: base64.urlsafe_b64decode(s + '=' * (-len(s) % 4))   # noqa: E731
    body = json.loads(pad(claims))
    assert body['iss'] == key['client_email'] and body['scope'].endswith('analytics.readonly')
    assert body['exp'] - body['iat'] == 3600
    pk.public_key().verify(pad(sig), ('%s.%s' % (head, claims)).encode(), padding.PKCS1v15(), hashes.SHA256())


def test_the_key_is_sealed_and_never_shown(client, admin_user):
    from app.models import AppSetting
    from app.services import ga4
    _, key = _key()
    login(client, admin_user.email)
    bad = client.post('/promotion/designer/google', data={'property_id': 'G-NPHSR9PNTC', 'key_json': json.dumps(key)},
                      follow_redirects=True).data.decode()
    assert 'not the G-... measurement id' in bad.replace('&#34;', '"').replace('&#39;', "'") or 'measurement id' in bad
    assert not ga4.connected()
    client.post('/promotion/designer/google', data={'property_id': '412345678', 'key_json': json.dumps(key)})
    assert ga4.connected()
    stored = json.dumps(_db.session.get(AppSetting, ga4.SETTING).value)
    assert 'PRIVATE KEY' not in stored and '412345678' in stored
    page = client.get('/promotion/designer/google').data.decode()
    assert 'PRIVATE KEY' not in page and 'dash@proj.iam.gserviceaccount.com' in page
    # saving again without a key keeps the one saved
    client.post('/promotion/designer/google', data={'property_id': '412345679', 'key_json': ''})
    assert ga4.status()['property_id'] == '412345679' and ga4.connected()


def test_website_boxes_read_google_analytics(client, app, admin_user, monkeypatch):
    from app.services import ga4, mkt_engine as eng
    _, key = _key()
    calls = []

    def fake_post(pid, method, body, k):
        calls.append((method, body))
        dims = [d['name'] for d in body.get('dimensions', [])]
        if method == 'runRealtimeReport':
            rows = [('mobile', 7), ('desktop', 5)] if dims == ['deviceCategory'] else []
            return {'rows': [{'dimensionValues': [{'value': a}], 'metricValues': [{'value': str(n)}]} for a, n in rows],
                    'totals': [{'metricValues': [{'value': '12'}]}]}
        if dims == ['country']:
            rows = [('India', 120), ('United States', 80), ('(not set)', 3)]
        elif dims == ['date']:
            rows = [((eng.today() - timedelta(days=i)).strftime('%Y%m%d'), 10 + i) for i in range(3)]
        else:
            rows = []
        return {'rows': [{'dimensionValues': [{'value': a}], 'metricValues': [{'value': str(n)}]} for a, n in rows],
                'totals': [{'metricValues': [{'value': '190' if dims else '150'}]}]}
    monkeypatch.setattr(ga4, '_post', fake_post)
    with app.test_request_context('/'):
        ga4.save('412345678', json.dumps(key), by=admin_user)
        by_country = _run({'chart': 'hbar', 'metrics': [{'source': 'website', 'measure': 'activeUsers',
                                                        'filters': {'device': ['mobile']}}], 'group': 'country'},
                          admin_user)
        assert _by_label(by_country) == {'India': 120, 'United States': 80, 'Not known': 3}
        assert by_country['total'] == 190 and by_country['prev'] == 150
        flt = calls[0][1]['dimensionFilter']['filter']
        assert flt == {'fieldName': 'deviceCategory', 'inListFilter': {'values': ['mobile']}}
        line = _run({'chart': 'line', 'metrics': [{'source': 'website', 'measure': 'activeUsers'}], 'group': 'day'},
                    admin_user, key='last_7')
        assert len(line['labels']) == 7 and line['series'][0]['data'][-3:] == [12, 11, 10]
        live = _run({'chart': 'live', 'metrics': [{'source': 'website_now', 'measure': 'activeUsers'}],
                     'group': 'device'}, admin_user)
        assert live['total'] == 12 and _by_label(live) == {'Mobile': 7, 'Desktop': 5}
        n = len(calls)
        _run({'chart': 'hbar', 'metrics': [{'source': 'website', 'filters': {'device': ['mobile']}}],
              'group': 'country'}, admin_user)
        assert len(calls) == n, 'the same question within minutes is answered from memory'


def test_google_saying_no_is_said_in_words(app, admin_user, monkeypatch):
    from app.services import ga4

    class R:
        status_code = 403

        def json(self):
            return {'error': {'message': 'User does not have sufficient permissions'}}
    _, key = _key()
    monkeypatch.setattr(ga4, '_access_token', lambda k: 'token')
    monkeypatch.setattr(ga4.requests, 'post', lambda *a, **kw: R())
    with app.test_request_context('/'):
        ga4.save('412345678', json.dumps(key), by=admin_user)
        r = _run({'chart': 'number', 'metrics': [{'source': 'website'}]}, admin_user)
    assert r['ok'] is False and 'Property access management' in r['message'] and 'Viewer' in r['message']
