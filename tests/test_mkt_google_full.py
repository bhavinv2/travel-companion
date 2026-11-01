"""Google in full, and our own visitors, on the Promotion dashboard (2026-11-01).

    boards      the built-in Google Analytics, Google search and Our visitors boards check out, open for anybody with
                the dashboard, and every ready-made box the designer offers is a good box
    analytics   several numbers of one box are one question to Google (the columns describe the same rows); a number
                GA's screens show but its API does not (time engaged per visitor) is worked out; hours and days of
                the week keep their order and their noughts
    search      each kind of search asked for and added up; where we came worked out from each search's position;
                how Google showed us in our words; our sitemaps and our pages in Google's index
    visitors    our own record as a source: visitors, visits, pages, by country, hour and way in, with each group's
                own change; who is on the site now; one by one for staff only, the address masked for a masked role
    came back   who came back week by week (GA's Retention report), of the website and of our own visitors
    the screen  Inbox › Visitors lists each visitor, each internet address or each page opened, for any dates kept
"""
import json
import os
import sys
from datetime import datetime, timedelta
from html import unescape

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import login, make_user  # noqa: E402
from app import db as _db  # noqa: E402
from app.models import CrmLiveChat, CrmVisitor, CrmVisitorPage, WorkspaceRole  # noqa: E402
from test_mkt_dashboards import _key, _run, _by_label  # noqa: E402

BLR, LON = '49.207.192.10', '81.2.69.142'


@pytest.fixture()
def influencer(app, db):
    u = make_user('promo2@test.com', 'promo2')
    u.set_roles(['user', 'influencer'])
    _db.session.commit()
    return u


def _visitor(vid, ip, country, code, city, device='phone', source='Google', pages=(), first=None, here=False):
    """A visitor and their pages: [(minutes ago, url, visit, secs, came_from)]."""
    now = datetime.utcnow()
    v = CrmVisitor(vid=vid * 4, site='nriparentservice.com', ip=ip, country=country, country_code=code, city=city,
                   region=None, device=device, browser='Chrome', os='Android' if device == 'phone' else 'Windows',
                   source=source, first_at=first or now - timedelta(days=3), last_at=now - timedelta(seconds=30)
                   if here else now - timedelta(hours=2), visits=max([p[2] for p in pages] or [1]), pages=len(pages),
                   page_url='https://nriparentservice.com' + (pages[0][1] if pages else '/'), page_title='Home')
    _db.session.add(v)
    _db.session.flush()
    for ago, url, visit, secs, came in pages:
        _db.session.add(CrmVisitorPage(visitor_id=v.id, at=now - timedelta(minutes=ago),
                                       url='https://nriparentservice.com' + url, title=url, visit=visit, secs=secs,
                                       came_from=came))
    _db.session.commit()
    return v


@pytest.fixture()
def seen(app, db):
    a = _visitor('a1b2', BLR, 'India', 'IN', 'Bengaluru', pages=[(30, '/travel-insurance', 1, 40, 'Google'),
                                                                 (25, '/sahayak', 1, 20, None),
                                                                 (5, '/travel-insurance', 2, 60, 'WhatsApp')],
                 here=True)
    b = _visitor('c3d4', LON, 'United Kingdom', 'GB', 'London', device='computer', source='Direct',
                 pages=[(60 * 30, '/travel-insurance', 1, 10, 'Direct')])
    c = _visitor('e5f6', BLR, 'India', 'IN', 'Bengaluru', device='computer', source='Facebook',
                 pages=[(60 * 24 * 40, '/blog', 1, 90, 'Facebook')])            # 40 days ago: the days before
    _db.session.add(CrmLiveChat(visitor_id=b.id, token='t' * 32, started_at=datetime.utcnow()))
    _db.session.commit()
    return a, b, c


# ================================================================================================ boards

def test_the_built_in_boards_check_out(app):
    from app.services import mkt_dashboards as md, mkt_engine as eng
    with app.test_request_context('/'):
        assert list(md.BOARDS) == ['overview', 'google', 'search', 'visitors']
        for key in md.BOARDS:
            boxes = md.board(key)
            ids = [b['id'] for b in boxes]
            assert len(ids) == len(set(ids)) and len(boxes) <= md.MAX_BOXES, key
            for a in boxes:
                assert not any(md._overlaps(a, b) for b in boxes if b is not a), (key, a['id'])
        for _group, name, box in md.SUGGESTIONS:
            eng.clean_box(box)
        google = md.board('google')
        assert {b['chart'] for b in md.board('search')} >= {'indexing', 'sitemaps'}
        assert any(b['chart'] == 'people' for b in md.board('visitors'))
        assert [b.get('of') for b in google + md.board('visitors') if b['chart'] == 'retention'] == ['website',
                                                                                                    'visitors']
        assert all(md.is_async(b) for b in google if b['chart'] != 'text'), 'Google boxes come after the page'


def test_every_board_opens_for_the_promotion_team(client, influencer, seen):
    login(client, influencer.email)
    for d in ('google', 'search', 'visitors', 'overview'):
        r = client.get('/promotion?d=' + d)
        assert r.status_code == 200, d
    html = unescape(client.get('/promotion?d=visitors').get_data(as_text=True))
    assert 'Our visitors, as we record them' in html and 'Every visitor, page by page' not in html
    assert 'Google Analytics' in html and 'Google search' in html, 'the switcher names every board'
    assert BLR not in html, 'nobody is listed one by one in the page itself'
    one = client.get('/promotion/box?d=visitors&b=v2').get_json()
    assert one['hidden'] and 'staff' in one['message']


def test_a_designer_can_start_from_a_board(client, app, admin_user):
    from app.models import MktDashboard
    login(client, admin_user.email)
    client.post('/promotion/designer/new', data={'name': 'Search work', 'start': 'search'})
    d = MktDashboard.query.filter_by(name='Search work').one()
    assert any(b['chart'] == 'indexing' for b in d.draft)


# ================================================================================================ Analytics

def test_several_numbers_are_one_question_to_google(app, admin_user, monkeypatch):
    from app.services import ga4
    _, key = _key()
    calls = []

    def fake_post(pid, method, body, k):
        calls.append(body)
        names = [m['name'] for m in body['metrics']]
        dims = [d['name'] for d in body.get('dimensions', [])]
        values = {'screenPageViews': (90, 30), 'activeUsers': (30, 10), 'userEngagementDuration': (600, 500)}
        if dims == ['pagePath']:
            rows = [('/travel-insurance', [values[n][0] for n in names]), ('/sahayak', [values[n][1] for n in names])]
        elif dims == ['hour']:
            rows = [('9', [5]), ('21', [7])]
        else:
            rows = []
        tot = [sum(r[1][i] for r in rows) for i in range(len(names))]
        return {'rows': [{'dimensionValues': [{'value': a}], 'metricValues': [{'value': str(v)} for v in vals]}
                         for a, vals in rows],
                'totals': [{'metricValues': [{'value': str(v)} for v in tot]}]}
    monkeypatch.setattr(ga4, '_post', fake_post)
    with app.test_request_context('/'):
        ga4.save('412345678', json.dumps(key), by=admin_user)
        r = _run({'chart': 'table', 'group': 'page', 'compare': False,
                  'metrics': [{'source': 'website', 'measure': 'screenPageViews'},
                              {'source': 'website', 'measure': 'activeUsers'},
                              {'source': 'website', 'measure': 'avgEngagement'}]}, admin_user)
        assert len(calls) == 1, 'three columns, one report'
        assert [m['name'] for m in calls[0]['metrics']] == ['screenPageViews', 'activeUsers', 'userEngagementDuration']
        assert r['labels'] == ['/travel-insurance', '/sahayak']
        assert [s['data'] for s in r['series']] == [[90, 30], [30, 10], [20, 50]], 'time engaged = time / visitors'
        assert r['series'][2]['unit'] == 'seconds'
        hours = _run({'chart': 'bar', 'group': 'hour', 'compare': False,
                      'metrics': [{'source': 'website', 'measure': 'sessions'}]}, admin_user)
        assert len(hours['labels']) == 24 and hours['labels'][9] == '09:00'
        assert hours['series'][0]['data'][9] == 5 and hours['series'][0]['data'][21] == 7 and sum(
            hours['series'][0]['data']) == 12


# ================================================================================================ Search Console

def test_kinds_of_search_bands_and_how_google_showed_us(app, admin_user, monkeypatch):
    from app.services import ga4, gsc
    _, key = _key()
    bodies = []

    def fake(site, body, k):
        bodies.append(body)
        dims, kind = body['dimensions'], body['type']
        if kind == 'discover':
            raise ga4.GAError('Discover has no searches')
        rows = []
        if dims == ['query']:
            rows = [(['nri parent care'], 10, 100, 2.0), (['visitor insurance'], 4, 400, 14.0),
                    (['parents travel'], 1, 50, 35.0)] if kind == 'web' else []
        elif dims == ['searchAppearance']:
            rows = [(['REVIEW_SNIPPET'], 3, 30, 4.0), (['FAQ_RICH_RESULT'], 1, 20, 6.0)]
        elif not dims:
            rows = [([], {'web': 15, 'image': 2}.get(kind, 0), 600, 9.0)]
        return {'rows': [{'keys': k_, 'clicks': c, 'impressions': i, 'ctr': 0, 'position': p} for k_, c, i, p in rows]}
    monkeypatch.setattr(gsc, '_post', fake)
    with app.test_request_context('/'):
        ga4.save('', json.dumps(key), by=admin_user, sc_site='sc-domain:nriparentservice.com')
        kinds = _run({'chart': 'table', 'group': 'type', 'top': 0, 'compare': False,
                      'metrics': [{'source': 'search', 'measure': 'clicks'}]}, admin_user)
        assert _by_label(kinds)['Web'] == 15 and _by_label(kinds)['Images'] == 2
        assert 'Discover' not in kinds['labels'] and any('Discover' in n for n in kinds['notes'])
        assert {b['type'] for b in bodies} >= {'web', 'image', 'video', 'news', 'googleNews'}
        bands = _run({'chart': 'bar', 'group': 'band', 'top': 0, 'compare': False,
                      'metrics': [{'source': 'search', 'measure': 'impressions'}]}, admin_user)
        assert bands['labels'] == ['Top 3', '11th to 20th (second page)', '21st to 50th']
        assert _by_label(bands)['11th to 20th (second page)'] == 400
        near = _run({'chart': 'table', 'group': 'query', 'compare': False,
                     'metrics': [{'source': 'search', 'measure': 'impressions',
                                  'filters': {'band': ['11th to 20th (second page)']}}]}, admin_user)
        assert near['labels'] == ['visitor insurance'] and near['total'] == 400
        shown = _run({'chart': 'table', 'group': 'appearance', 'compare': False,
                      'metrics': [{'source': 'search', 'measure': 'clicks'}]}, admin_user)
        assert shown['labels'] == ['Review stars', 'FAQ']


def test_our_sitemaps_and_our_pages_in_googles_index(app, admin_user, monkeypatch):
    from app.services import ga4, gsc

    class R:
        status_code = 200

        def __init__(self, data):
            self.data = data

        def json(self):
            return self.data
    _, key = _key()
    monkeypatch.setattr(ga4, '_access_token', lambda k: 'token')
    monkeypatch.setattr(gsc.requests, 'get', lambda url, **kw: R({'sitemap': [
        {'path': 'https://nriparentservice.com/sitemap.xml', 'lastSubmitted': '2026-10-20T10:00:00.000Z',
         'lastDownloaded': '2026-10-31T01:30:00.000Z', 'isPending': False, 'errors': '0', 'warnings': '2',
         'contents': [{'type': 'web', 'submitted': '42'}]}]}))
    asked = []

    def post(url, json=None, **kw):
        if 'urlInspection' in url:
            asked.append(json['inspectionUrl'])
            ok = json['inspectionUrl'].endswith('/travel-insurance') or json['inspectionUrl'].endswith('.com/')
            return R({'inspectionResult': {'indexStatusResult': {
                'verdict': 'PASS' if ok else 'NEUTRAL',
                'coverageState': 'Submitted and indexed' if ok else 'Crawled - currently not indexed',
                'lastCrawlTime': '2026-10-30T04:12:55Z', 'crawledAs': 'MOBILE', 'robotsTxtState': 'ALLOWED'}}})
        return R({'rows': [{'keys': ['https://nriparentservice.com/travel-insurance'], 'clicks': 9, 'impressions': 300,
                            'position': 5.0},
                           {'keys': ['https://nriparentservice.com/blog/x'], 'clicks': 1, 'impressions': 80,
                            'position': 22.0}]})
    monkeypatch.setattr(gsc.requests, 'post', post)
    with app.test_request_context('/'):
        ga4.save('', json.dumps(key), by=admin_user, sc_site='https://nriparentservice.com/')
        maps = _run({'chart': 'sitemaps'}, admin_user)
        assert maps['ok'] and maps['rows'][0]['urls'] == 42 and maps['rows'][0]['warnings'] == 2
        assert maps['rows'][0]['read'].startswith('31 Oct 2026')
        ix = _run({'chart': 'indexing', 'top': 5}, admin_user)
        assert ix['ok'] and ix['checked'] == 3 and ix['indexed'] == 2 and ix['not'] == 1
        assert asked[0] == 'https://nriparentservice.com/', 'the home page first'
        assert {r['state'] for r in ix['rows']} == {'In Google', 'Not in Google'}
        n = len(asked)
        _run({'chart': 'indexing', 'top': 5}, admin_user)
        assert len(asked) == n, 'a page checked is kept for hours: Google allows 2,000 a day'


# ================================================================================================ our visitors

def test_our_visitors_as_a_source(app, admin_user, seen):
    with app.test_request_context('/'):
        tot = _run({'chart': 'number', 'metrics': [{'source': 'visitors', 'measure': 'visitors'}]}, admin_user)
        assert tot['total'] == 2 and tot['prev'] == 1, 'two this month, one the month before'
        visits = _run({'chart': 'number', 'metrics': [{'source': 'visitors', 'measure': 'visits'}]}, admin_user)
        assert visits['total'] == 3
        pages = _run({'chart': 'number', 'metrics': [{'source': 'visitors', 'measure': 'count'}]}, admin_user)
        assert pages['total'] == 4
        by_country = _run({'chart': 'table', 'group': 'country',
                           'metrics': [{'source': 'visitors', 'measure': 'visitors'}]}, admin_user)
        assert _by_label(by_country) == {'India': 1, 'United Kingdom': 1}
        assert by_country['row_change'][by_country['labels'].index('India')] == 0.0, 'one now, one before'
        way_in = _run({'chart': 'donut', 'group': 'source', 'metrics': [{'source': 'visitors', 'measure': 'visits'}]},
                      admin_user)
        assert _by_label(way_in) == {'Google': 1, 'WhatsApp': 1, 'Direct': 1}, 'each visit its own way in'
        hours = _run({'chart': 'bar', 'group': 'hour', 'metrics': [{'source': 'visitors', 'measure': 'count'}]}, admin_user)
        assert len(hours['labels']) == 24 and sum(hours['series'][0]['data']) == 4
        week = _run({'chart': 'bar', 'group': 'weekday', 'metrics': [{'source': 'visitors', 'measure': 'count'}]}, admin_user)
        assert week['labels'][0] == 'Monday' and len(week['labels']) == 7
        chat = _run({'chart': 'number', 'metrics': [{'source': 'visitors', 'measure': 'chatters'}]}, admin_user)
        assert chat['total'] == 1
        landing = _run({'chart': 'table', 'group': 'landing', 'metrics': [{'source': 'visitors', 'measure': 'visits'}]},
                       admin_user)
        assert _by_label(landing) == {'/travel-insurance': 3}
        now = _run({'chart': 'live', 'group': 'country', 'metrics': [{'source': 'visitors_now'}]}, admin_user)
        assert now['total'] == 1 and _by_label(now) == {'India': 1} and len(now['minutes']) == 30
        assert sum(now['minutes']) == 2 and now['live_words'] == 'right now', 'pages 25 and 5 minutes ago'


def test_visitors_one_by_one_are_for_staff_and_masked_for_a_masked_role(app, admin_user, influencer, seen):
    from app.services import access
    with app.test_request_context('/'):
        hidden = _run({'chart': 'people', 'top': 5}, influencer)
        assert hidden['hidden'] and 'staff' in hidden['message']
        r = _run({'chart': 'people', 'top': 5}, admin_user)
        assert r['ok'] and r['now'] == 1 and r['rows'][0]['here'] and r['rows'][0]['ip'] == BLR
        assert len(r['rows']) == 3 and r['rows'][0]['open'].endswith('?v=%d' % seen[0].id)
        assert any(x['chatted'] for x in r['rows'])
        ws = access.ensure_defaults()
        agent = make_user('mask2@test.com', 'mask2', role='cs')
        role = WorkspaceRole(workspace_id=ws.id, name='Masked', pages=sorted(access.CS_ROLE_PAGES),
                             rights={'view': [], 'remove': True, 'mask': True})
        _db.session.add(role)
        _db.session.flush()
        access.add_member(ws, agent, role=role)
        _db.session.commit()
        access._cache().clear()
        masked = _run({'chart': 'people', 'top': 5}, agent)
        assert masked['ok'] and masked['rows'][0]['ip'] == '49.207.•.•'


def test_no_visitor_box_prints_an_address(app, admin_user, seen):
    from app.services import mkt_engine as eng
    with app.test_request_context('/'):
        for key in ('visitors', 'visitors_now'):
            s = eng.source(key)
            for d in s.dims:
                r = eng.run(eng.clean_box({'chart': 'table', 'metrics': [{'source': key}], 'group': d, 'top': 0}),
                            eng.period_for('last_30'), admin_user)
                assert BLR not in json.dumps(r) and LON not in json.dumps(r), (key, d)


# ================================================================================================ who came back

def _ist(day, hour=12):
    from app.services.mkt_engine import IST
    return datetime.combine(day, datetime.min.time()) + timedelta(hours=hour) - IST


def test_who_came_back_of_our_visitors(app, db, admin_user):
    from app.services import mkt_engine as eng
    monday = eng.today() - timedelta(days=eng.today().weekday())
    two_ago = monday - timedelta(weeks=2)
    for vid, days in (('back', (1, 8)), ('once', (2,)), ('new', ())):
        first = _ist(two_ago + timedelta(days=days[0])) if days else _ist(monday, 0)
        v = CrmVisitor(vid=vid * 8, first_at=first, last_at=first)
        _db.session.add(v)
        _db.session.flush()
        for d in days or (None,):
            _db.session.add(CrmVisitorPage(visitor_id=v.id, at=_ist(two_ago + timedelta(days=d)) if d else first,
                                           url='https://nriparentservice.com/', visit=1))
    _db.session.commit()
    with app.test_request_context('/'):
        box = eng.clean_box({'chart': 'retention', 'top': 4, 'of': 'visitors'})
        assert box['of'] == 'visitors' and eng.clean_box({'chart': 'retention', 'of': 'x', 'top': 99}) == dict(
            eng.clean_box({'chart': 'retention'}), top=12)
        r = _run(box, admin_user)
    assert r['ok'] and r['kind'] == 'retention' and r['starts_on'] == 'Monday' and r['weeks'] == 4
    assert [row['start'] for row in r['rows']] == [(monday - timedelta(weeks=n)).isoformat() for n in (2, 1, 0)], (
        'the weeks before anybody came are left out')
    came, last, now = r['rows']
    assert came['size'] == 2 and came['cells'] == [{'n': 1, 'pct': 50.0}, {'n': 0, 'pct': 0.0}, None]
    assert last['size'] == 0 and last['cells'] == [{'n': 0, 'pct': None}, None, None]
    assert now['size'] == 1 and now['cells'] == [None, None, None], 'weeks not begun are blank, not nought'
    assert r['average'] == [50.0, 0.0, None] and r['size'] == 3


def test_who_came_back_of_the_website_is_googles_cohort_report(app, admin_user, monkeypatch):
    from app.services import ga4, mkt_engine as eng
    _, key = _key()
    bodies = []

    def fake_post(pid, method, body, k):
        bodies.append(body)
        first = body['cohortSpec']['cohorts'][1]['name']
        return {'rows': [{'dimensionValues': [{'value': first}, {'value': nth}],
                          'metricValues': [{'value': str(a)}, {'value': '10'}]} for nth, a in (('0000', 10), ('0001', 3))]}
    monkeypatch.setattr(ga4, '_post', fake_post)
    with app.test_request_context('/'):
        ga4.save('412345678', json.dumps(key), by=admin_user)
        r = _run({'chart': 'retention', 'top': 3}, admin_user)
    body = bodies[0]
    assert 'dateRanges' not in body and [d['name'] for d in body['dimensions']] == ['cohort', 'cohortNthWeek']
    assert body['cohortSpec']['cohortsRange'] == {'granularity': 'WEEKLY', 'startOffset': 0, 'endOffset': 2}
    cohorts = body['cohortSpec']['cohorts']
    assert len(cohorts) == 3 and all(c['dimension'] == 'firstSessionDate' for c in cohorts)
    for c in cohorts:
        a, b = (datetime.strptime(c['dateRange'][k], '%Y-%m-%d').date() for k in ('startDate', 'endDate'))
        assert a.weekday() == 6 and (b - a).days == 6, "Google's weeks begin on Sunday"
    assert r['starts_on'] == 'Sunday' and len(r['rows']) == 2 and r['rows'][0]['size'] == 10
    assert r['rows'][0]['cells'][0] == {'n': 3, 'pct': 30.0} and r['rows'][0]['start'] == cohorts[1]['name']
    assert eng.today() - datetime.strptime(r['rows'][-1]['start'], '%Y-%m-%d').date() < timedelta(days=7)


# ================================================================================================ the screen

def test_the_screen_by_visitor_by_address_and_by_page(client, admin_user, seen):
    login(client, admin_user.email)
    base = '/admin/messaging/visitors'
    by_ip = unescape(client.get(base + '?view=addresses&when=month').get_data(as_text=True))
    assert '2 addresses' in by_ip and BLR in by_ip and LON in by_ip
    assert by_ip.count('Bengaluru') >= 1 and 'Its visitors' in by_ip
    log = unescape(client.get(base + '?view=pages&when=month').get_data(as_text=True))
    assert '4 pages' in log and '/sahayak' in log and 'Visit 2 began here' in log
    today = (datetime.utcnow() + timedelta(hours=5, minutes=30)).date()
    old = (today - timedelta(days=40)).isoformat()
    then = unescape(client.get(base + '?when=custom&from=%s&to=%s' % (old, old)).get_data(as_text=True))
    assert '1 visitor' in then and 'Facebook' in then
    page_two = unescape(client.get(base + '?view=pages&when=custom&from=%s&to=%s' % (old, today.isoformat()))
                        .get_data(as_text=True))
    assert '5 pages' in page_two
    sheet = unescape(client.get('%s/%d' % (base, seen[0].id)).get_data(as_text=True))
    assert 'Also from this internet address' in sheet and 'Visitor #%d' % seen[2].id in sheet
    figures = unescape(client.get(base).get_data(as_text=True))
    assert 'Internet addresses · 7 days' in figures and 'Charts of our visitors' in figures
