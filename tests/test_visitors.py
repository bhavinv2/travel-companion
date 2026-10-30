"""Visitors (2026-10-30): who is on our websites -- tawk.to's Visitors list, kept by us (services/visitors.py).

    the bubble    tells the app's own address when a page opens, while it shows and when it closes; a robot, a made-up
                  id or a browser we let go of leaves nothing; switched off, it tells nothing
    the visitor   where they are (our own copy of DB-IP's list, never asked of anybody per visit), browser and device,
                  how they first found us, each visit's pages and how long each showed; an address that came through
                  the forwarder is not theirs, so it is not kept; a chat links the browser to the person
    the screen    Inbox › Visitors: on the site now, the figures, filters, one visitor's pages and chats; masked roles
                  see addresses masked; the chat's own pane says where they are
    keeping       90 days after the last visit; the IP list comes by itself and a failed download keeps the old one
"""
import gzip
import json
from datetime import datetime, timedelta
from html import unescape

import pytest

from conftest import login, make_user
from app import db as _db
from app.models import CrmLiveChat, CrmVisitor, CrmVisitorPage
from app.services import livechat, settings, visitors

HERE = '/api/live-chat/here'
PAGE = '/admin/messaging/visitors'
VID = 'a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8'
PHONE = ('Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 '
         'Mobile Safari/537.36')
DESK = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 '
        'Safari/537.36 Edg/129.0.0.0')
BENGALURU, LONDON = '49.207.192.10', '81.2.69.142'


class FakeList:
    """DB-IP's list, as maxminddb hands its records back."""
    RECORDS = {BENGALURU: {'city': {'names': {'en': 'Bengaluru'}}, 'country': {'iso_code': 'IN', 'names': {'en': 'India'}},
                           'subdivisions': [{'names': {'en': 'Karnataka'}}]},
               LONDON: {'city': {'names': {'en': 'London'}}, 'country': {'iso_code': 'GB', 'names': {'en': 'United Kingdom'}},
                        'subdivisions': [{'names': {'en': 'England'}}]}}

    def get(self, ip):
        return self.RECORDS.get(ip)


@pytest.fixture()
def ip_list(monkeypatch):
    monkeypatch.setattr(visitors, '_reader', lambda: FakeList())


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setitem(visitors._purged, 'at', 0.0)


def say(client, kind='view', vid=VID, ip=BENGALURU, ua=PHONE, headers=None, **kw):
    body = {'vid': vid, 'kind': kind}
    if kind == 'view':
        body.update({'page': 'https://nriparentservice.com/travel-insurance', 'title': 'Travel insurance',
                     'ref': 'https://www.google.com/', 'lang': 'en-IN', 'tz': 'Asia/Kolkata', 'touch': 1})
    body.update(kw)
    return client.post(HERE, data=json.dumps(body), content_type='text/plain;charset=UTF-8',
                       headers=dict({'User-Agent': ua}, **(headers or {})), environ_base={'REMOTE_ADDR': ip})


def view(vid=VID, at=None, ip=BENGALURU, ua=PHONE, **kw):
    body = {'vid': vid, 'kind': 'view', 'page': 'https://nriparentservice.com/travel-insurance',
            'title': 'Travel insurance', 'ref': 'https://www.google.com/', 'tz': 'Asia/Kolkata'}
    body.update(kw)
    return visitors.ping(body, ua, ip, now=at)


def page(client, url):
    r = client.get(url)
    assert r.status_code == 200, (url, r.status_code)
    return unescape(r.get_data(as_text=True))


# ------------------------------------------------------------------------------------------------ the bubble

def test_a_page_view_makes_a_visitor_with_where_they_are(app, client, ip_list):
    r = say(client)
    assert r.status_code == 204
    v = CrmVisitor.query.one()
    assert (v.city, v.region, v.country, v.country_code, v.ip) == ('Bengaluru', 'Karnataka', 'India', 'IN', BENGALURU)
    assert (v.browser, v.os, v.device) == ('Chrome', 'Android', 'phone')
    assert (v.source, v.tz, v.lang, v.site) == ('Google', 'Asia/Kolkata', 'en-IN', 'nriparentservice.com')
    assert v.landing_url == v.page_url == 'https://nriparentservice.com/travel-insurance' and v.pages == 1
    p = CrmVisitorPage.query.one()
    assert (p.title, p.visit, p.came_from) == ('Travel insurance', 1, 'Google')
    assert visitors.here(v) and visitors.place(v) == 'Bengaluru, Karnataka, India'


def test_pages_visits_and_how_long_each_showed(app, ip_list):
    t0 = datetime(2026, 10, 30, 10, 0, 0)
    view(at=t0)
    visitors.ping({'vid': VID, 'kind': 'beat'}, PHONE, BENGALURU, now=t0 + timedelta(seconds=40))
    v = CrmVisitor.query.one()
    assert v.last_at == t0 + timedelta(seconds=40) and CrmVisitorPage.query.one().secs == 40
    visitors.ping({'vid': VID, 'kind': 'beat'}, PHONE, BENGALURU, now=t0 + timedelta(seconds=50))
    assert v.last_at == t0 + timedelta(seconds=40)             # "still here" is written at most every 20 seconds
    view(at=t0 + timedelta(seconds=90), page='https://nriparentservice.com/travel-insurance/canada/quotes/x',
         title='Your Canada quotes', ref='https://nriparentservice.com/travel-insurance')
    first, second = CrmVisitorPage.query.order_by(CrmVisitorPage.id).all()
    assert first.secs == 90 and second.came_from is None and v.pages == 2 and v.visits == 1
    assert v.source == 'Google'                                 # a link from our own page is not a new way in
    visitors.ping({'vid': VID, 'kind': 'leave'}, PHONE, BENGALURU, now=t0 + timedelta(seconds=130))
    assert v.gone_at is not None and not visitors.here(v, t0 + timedelta(seconds=131))
    assert second.secs == 40
    view(at=t0 + timedelta(hours=2), ref='', page='https://nriparentservice.com/?utm_source=whatsapp&utm_campaign=diwali')
    assert v.visits == 2 and v.pages == 3 and v.gone_at is None
    third = CrmVisitorPage.query.order_by(CrmVisitorPage.id.desc()).first()
    assert (third.visit, third.came_from) == (2, 'WhatsApp')
    assert v.source == 'Google' and v.campaign is None          # how they FIRST found us stays
    d = visitors.detail(v, t0 + timedelta(hours=2))
    assert [g['visit'] for g in d['visits']] == [2, 1] and d['visits'][1]['secs'] == 130


def test_a_computer_that_slept_on_our_page_starts_a_new_visit(app, ip_list):
    t0 = datetime(2026, 10, 30, 10, 0, 0)
    view(at=t0)
    visitors.ping({'vid': VID, 'kind': 'beat'}, PHONE, BENGALURU, now=t0 + timedelta(hours=3))
    v = CrmVisitor.query.one()
    assert v.visits == 2 and v.last_at == t0 + timedelta(hours=3) and CrmVisitorPage.query.count() == 2


def test_robots_made_up_ids_and_strangers_leave_nothing(app, client, ip_list):
    for ua in ('Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
               'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/129.0 Safari/537.36',
               ''):
        assert say(client, ua=ua).status_code == 204
    assert say(client, vid='short').status_code == 204
    assert say(client, vid='x' * 20 + '<script>').status_code == 204
    assert say(client, kind='beat', vid='b' * 36).status_code == 204          # a beat from a browser we do not know
    assert say(client, page='javascript:alert(1)').status_code == 204
    assert CrmVisitor.query.count() == 0


def test_switched_off_the_bubble_tells_nothing(app, client, admin_user, ip_list):
    settings.set_setting(livechat.SETTING, dict(livechat.config(), visitors=False))
    _db.session.commit()
    say(client)
    assert CrmVisitor.query.count() == 0
    js = client.get('/live-chat.js').get_data(as_text=True)
    assert '"track": false' in js and '"here": ""' in js
    login(client, admin_user.email)
    assert 'Recording visitors is switched off' in page(client, PAGE)


def test_the_bubble_tells_the_apps_own_address(app, client, monkeypatch):
    js = client.get('/live-chat.js').get_data(as_text=True)
    assert '"track": true' in js and '"here": ""' in js and "startVisit()" in js
    monkeypatch.setenv('RAILWAY_PUBLIC_DOMAIN', 'travel-companion-production-261c.up.railway.app')
    livechat._online['at'] = 0.0
    js = client.get('/live-chat.js').get_data(as_text=True)
    assert '"here": "https://travel-companion-production-261c.up.railway.app/api/live-chat/here"' in js
    app.config['VISITOR_PING_URL'] = 'https://portal.example.com/'
    js = client.get('/live-chat.js').get_data(as_text=True)
    assert '"here": "https://portal.example.com/api/live-chat/here"' in js


def test_an_address_through_the_forwarder_is_not_kept(app, client, admin_user, ip_list):
    say(client, ip='104.28.1.1', headers={'X-Forwarded-Prefix': '/travel-companions'})
    v = CrmVisitor.query.one()
    assert v.ip is None and v.country_code is None and visitors.place(v) == 'Time zone Asia/Kolkata'
    login(client, admin_user.email)
    html = page(client, PAGE)
    assert 'came without their address' in html and 'VISITOR_PING_URL' in html


# ------------------------------------------------------------------------------------------------ the visitor

def test_how_they_came(app):
    page_ = 'https://nriparentservice.com/travel-insurance'
    assert visitors.source_of(page_, '') == ('Direct', None)
    assert visitors.source_of(page_, 'https://www.google.co.in/') == ('Google', None)
    assert visitors.source_of(page_, 'https://nriparentservice.com/') == (None, None)
    assert visitors.source_of(page_, 'https://t.co/abc') == ('X', None)
    assert visitors.source_of(page_, 'https://l.facebook.com/') == ('Facebook', None)
    assert visitors.source_of(page_, 'https://wa.me/') == ('WhatsApp', None)
    assert visitors.source_of(page_, 'https://chatgpt.com/') == ('ChatGPT', None)
    assert visitors.source_of(page_, 'https://www.somebody-blog.in/post') == ('somebody-blog.in', None)
    assert visitors.source_of(page_ + '?gclid=abc', '') == ('Google Ads', None)
    assert visitors.source_of(page_ + '?utm_source=facebook&utm_medium=cpc&utm_campaign=parents', '') == \
        ('Facebook', 'facebook / cpc / parents')


def test_which_browser_and_device(app):
    iphone = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1'
    tab = 'Mozilla/5.0 (Linux; Android 13; SM-X200) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36'
    mac = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15'
    fb = iphone.replace('Safari/604.1', '[FBAN/FBIOS;FBAV/480.0]')
    assert visitors.device_of(iphone) == ('Safari', 'iOS', 'phone')
    assert visitors.device_of(tab) == ('Chrome', 'Android', 'tablet')
    assert visitors.device_of(DESK) == ('Edge', 'Windows', 'computer')
    assert visitors.device_of(mac) == ('Safari', 'macOS', 'computer')
    assert visitors.device_of(mac, touch=True) == ('Safari', 'iOS', 'tablet')        # an iPad asking for desktop pages
    assert visitors.device_of(fb)[0] == 'Facebook app'


def test_an_address_the_list_cannot_place(app, ip_list):
    assert visitors.locate('127.0.0.1') == {} and visitors.locate('10.1.2.3') == {} and visitors.locate('nonsense') == {}
    assert visitors.locate('8.8.4.4') == {}                    # not in this list
    view(ip='127.0.0.1')
    assert visitors.place(CrmVisitor.query.one()) == 'Local network'


def test_without_the_list_the_address_is_kept_and_placed_later(app, monkeypatch):
    monkeypatch.setattr(visitors, '_reader', lambda: None)
    view()
    v = CrmVisitor.query.one()
    assert v.ip == BENGALURU and v.country_code is None
    monkeypatch.setattr(visitors, '_reader', lambda: FakeList())
    view(at=datetime.utcnow() + timedelta(seconds=30))
    assert v.city == 'Bengaluru'


def test_a_chat_links_the_browser_to_the_person(app, client, admin_user, ip_list):
    say(client)
    r = client.post('/api/live-chat/start', data=json.dumps({
        'name': 'Meera Iyer', 'contact': 'meera@example.com', 'message': 'Is my mother covered?', 'topic': 'TI',
        'page': 'https://nriparentservice.com/travel-insurance', 'title': 'Travel insurance', 'vid': VID}),
        content_type='text/plain;charset=UTF-8')
    assert r.status_code == 201
    chat, v = CrmLiveChat.query.one(), CrmVisitor.query.one()
    assert chat.visitor_id == v.id and v.person_id == chat.person_id
    login(client, admin_user.email)
    pane = page(client, '/admin/messaging/live-chat/%d' % chat.person_id)
    assert 'Bengaluru, Karnataka, India · Chrome on Android · came from Google' in pane and 'Pages they read' in pane
    html = page(client, PAGE)
    assert 'Meera Iyer' in html and 'Chatted' in html
    one = page(client, '%s/%d' % (PAGE, v.id))
    assert 'Open the chat' in one and 'live-chat?chat=%d' % chat.person_id in one and 'Lead page' in one


# ------------------------------------------------------------------------------------------------ the screen

def test_the_screen_now_the_figures_and_one_visitor(app, client, admin_user, ip_list):
    say(client)
    say(client, vid='c' * 36, ip=LONDON, ua=DESK, ref='', page='https://nriparentservice.com/sahayak', title='Sahayak')
    login(client, admin_user.email)
    html = page(client, PAGE)
    assert 'On the site now' in html and 'Bengaluru, Karnataka, India' in html and 'London, England, United Kingdom' in html
    assert 'IP Geolocation by DB-IP' in html and 'Visitor #' in html
    assert 'data-now-count>2<' in html.replace(' ', '')
    now = page(client, PAGE + '/now')
    assert now.count('data-visitor=') == 2 and 'data-n="2"' in now
    gb = page(client, PAGE + '?country=GB')
    assert '1 visitor match' in gb
    assert '1 visitor match' in page(client, PAGE + '?q=Bengal')
    assert '1 visitor match' in page(client, PAGE + '?device=computer')
    assert '2 visitors match' in page(client, PAGE + '?chat=no')
    v = CrmVisitor.query.filter_by(city='London').one()
    one = page(client, '%s/%d' % (PAGE, v.id))
    assert 'Sahayak' in one and 'Edge on Windows' in one and 'Direct' in one and LONDON in one
    assert client.get('%s/%d' % (PAGE, 9999)).status_code == 404


def test_a_masked_role_sees_addresses_masked(app):
    assert visitors.show_ip(BENGALURU, masked=True) == '49.207.•.•'
    assert visitors.show_ip('2001:4860:4860::8888', masked=True) == '2001:4860:…'
    assert visitors.show_ip(BENGALURU) == BENGALURU and visitors.show_ip(None) == ''


def test_the_screen_is_for_staff_with_the_page(app, client, user):
    assert client.get(PAGE).status_code in (302, 401)
    login(client, user.email)
    assert client.get(PAGE).status_code != 200
    assert client.get(PAGE + '/now').status_code in (302, 403)


def test_the_menu_puts_visitors_beside_live_chat(app):
    from app.services import access
    assert access.PAGES['web_visitors']['links']['admin'] == 'messaging.visitors_page'
    chats = next(s for s in access.SECTIONS if s['key'] == 'inbox')['subs'][0]['pages']
    assert chats.index('web_visitors') == chats.index('web_chat') + 1


# ------------------------------------------------------------------------------------------------ keeping

def test_ninety_days_after_the_last_visit_they_are_let_go(app, ip_list):
    old = datetime.utcnow() - timedelta(days=visitors.KEEP_DAYS + 1)
    view(at=old)
    view(vid='d' * 36)
    v = CrmVisitor.query.filter_by(vid=VID).one()
    chat = CrmLiveChat(token='t' * 40, started_at=old, visitor_id=v.id)
    _db.session.add(chat)
    _db.session.commit()
    assert visitors.purge() == 1
    assert [x.vid for x in CrmVisitor.query.all()] == ['d' * 36] and CrmVisitorPage.query.count() == 1
    assert _db.session.get(CrmLiveChat, chat.id).visitor_id is None          # the chat stays, without the browser


class _Resp:
    def __init__(self, status, body=b''):
        self.status_code, self.body = status, body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError('HTTP %d' % self.status_code)

    def iter_content(self, n):
        yield self.body


def test_a_failed_download_keeps_the_list_we_have(app, monkeypatch, tmp_path):
    import requests
    app.instance_path = str(tmp_path)
    monkeypatch.setattr(requests, 'get', lambda url, **kw: _Resp(404))
    ok, said = visitors.refresh_geo(now=datetime(2026, 11, 1))
    assert not ok and 'no list for 2026-10' in said
    assert settings.get_setting(visitors.GEO_SETTING)['error'] == said
    (tmp_path / 'geo').mkdir(exist_ok=True)
    (tmp_path / 'geo' / visitors.GEO_FILE).write_bytes(b'the list we have')
    monkeypatch.setattr(requests, 'get', lambda url, **kw: _Resp(200, gzip.compress(b'not an ip list')))
    ok, said = visitors.refresh_geo(now=datetime(2026, 11, 1))
    assert not ok and 'could not be downloaded' in said
    assert (tmp_path / 'geo' / visitors.GEO_FILE).read_bytes() == b'the list we have'
    assert sorted(p.name for p in (tmp_path / 'geo').iterdir()) == [visitors.GEO_FILE]       # no lock, no part file
    st = visitors.geo_status()
    assert st['has'] and st['error'] == said


def test_the_list_is_fetched_by_itself_only_when_missing_or_old(app, monkeypatch, tmp_path):
    app.instance_path = str(tmp_path)
    started = []
    monkeypatch.setattr(visitors, 'refresh_geo_soon', lambda: started.append(1))
    monkeypatch.setitem(visitors._geo, 'tried', 0.0)
    assert not visitors.ensure_geo()                           # never by itself in tests
    app.config['VISITOR_GEO_AUTO'] = True
    assert visitors.ensure_geo() and started == [1]
    assert not visitors.ensure_geo()                           # tried lately: not again for GEO_RETRY seconds
    monkeypatch.setitem(visitors._geo, 'tried', 0.0)
    (tmp_path / 'geo').mkdir()
    (tmp_path / 'geo' / visitors.GEO_FILE).write_bytes(b'x')
    assert not visitors.ensure_geo() and started == [1]        # a fresh list is not fetched again


def test_the_settings_switch(app, client, admin_user):
    login(client, admin_user.email)
    r = client.post('/admin/crm/integrations/livechat/save', data={'on': '1', 'title': 'NRI Parent Service',
                                                             'greeting': 'Hi', 'away': 'Away', 'color': '#0F1F3D'})
    assert r.status_code in (200, 302)
    assert livechat.config()['visitors'] is False
    client.post('/admin/crm/integrations/livechat/save', data={'on': '1', 'visitors': '1', 'title': 'NRI Parent Service',
                                                         'greeting': 'Hi', 'away': 'Away', 'color': '#0F1F3D'})
    assert livechat.config()['visitors'] is True
    assert 'name="visitors"' in page(client, '/admin/crm/integrations/livechat?tab=settings')
