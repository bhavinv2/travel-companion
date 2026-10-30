"""Visitors (2026-10-30): who is on our websites -- tawk.to's Visitors list, kept by us. Recorded by our own chat bubble,
placed on the map by our own copy of a free IP list: nothing per visit is asked of Cloudflare, or of anybody.

The bubble (static/js/live-chat.js) keeps a random id in the browser and tells the app, at the app's own address
(ping_url(): no proxy in between to stand in for the visitor, so the address that reaches us is theirs):
    'view'   a page opened: which page, where it was linked from (referrer, utm_*), the browser's language, time zone
    'beat'   still here: every 30 seconds while the tab shows, every 90 while it is in the background
    'leave'  the page closed
ping() keeps one CrmVisitor per browser and a CrmVisitorPage per page; a visit is pages less than VISIT_GAP apart.
A chat started from the bubble links the browser to the chat and so to the person (link_chat, from livechat.start).

Where they are: DB-IP's "IP to City Lite" list (CC BY 4.0, a new one each month), downloaded by the app itself into
instance/geo (refresh_geo, by itself when the file is missing or old, or from the Visitors screen). Without the file a
visitor still has their address, browser and their browser's own time zone.

The screen is Inbox › Visitors (routes/messaging.py visitors_page): on the site now, the last day and week, where they
are from, how they found us, each one's pages. Addresses are kept KEEP_DAYS after the last visit (purge); a role that
masks contact details sees them masked (show_ip).
"""
import ipaddress
import logging
import os
import re
import threading
import time
import zlib
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlsplit

from flask import current_app, has_request_context, request
from sqlalchemy import func, or_, select

from app import db
from app.models import CrmLiveChat, CrmPerson, CrmVisitor, CrmVisitorPage
from app.services import settings

log = logging.getLogger(__name__)

HERE_FOR = timedelta(seconds=150)        # its browser speaks every 30-90 seconds: quiet longer, it left
VISIT_GAP = timedelta(minutes=30)        # pages further apart than this are another visit
BEAT_WRITE = timedelta(seconds=20)       # a "still here" is written at most this often
KEEP_DAYS = 90                           # addresses and pages are let go this long after the last visit
PAGES_SHOWN = 60
PER_PAGE = 50
VID_RE = re.compile(r'^[A-Za-z0-9_-]{16,40}$')
# browsers that run our script but are not people (search engines render pages; test and monitoring tools)
BOT_RE = re.compile(r'bot\b|bot/|crawl|spider|slurp|headless|lighthouse|pingdom|uptime|monitor|preview|phantom|'
                    r'selenium|puppeteer|playwright', re.I)

BROWSERS = ((r'FBAN|FBAV|FB_IAB', 'Facebook app'), (r'Instagram', 'Instagram app'), (r'Edg[A-Za-z]*/', 'Edge'),
            (r'OPR/|Opera', 'Opera'), (r'SamsungBrowser', 'Samsung Internet'), (r'UCBrowser', 'UC Browser'),
            (r'YaBrowser', 'Yandex'), (r'Firefox/|FxiOS', 'Firefox'), (r'CriOS|Chrome/|Chromium', 'Chrome'),
            (r'Safari/', 'Safari'))
SYSTEMS = ((r'Windows', 'Windows'), (r'iPhone|iPad|iPod', 'iOS'), (r'Android', 'Android'), (r'CrOS', 'ChromeOS'),
           (r'Mac OS X|Macintosh', 'macOS'), (r'Linux', 'Linux'))
DEVICES = (('phone', 'Phone', 'fa-mobile-screen'), ('tablet', 'Tablet', 'fa-tablet-screen-button'),
           ('computer', 'Computer', 'fa-desktop'))
DEVICE_WORD = {k: w for k, w, _i in DEVICES}
DEVICE_ICON = {k: i for k, _w, i in DEVICES}

# where a link came from, by the linking page's host
SOURCES = ((r'(^|\.)mail\.google\.|(^|\.)outlook\.|(^|\.)mail\.yahoo\.', 'E-mail'),
           (r'(^|\.)google\.|(^|\.)googleadservices\.', 'Google'), (r'(^|\.)bing\.com$', 'Bing'),
           (r'(^|\.)yahoo\.', 'Yahoo'), (r'(^|\.)duckduckgo\.com$', 'DuckDuckGo'),
           (r'(^|\.)facebook\.com$|(^|\.)fb\.com$|(^|\.)fb\.me$', 'Facebook'), (r'(^|\.)instagram\.com$', 'Instagram'),
           (r'(^|\.)whatsapp\.(com|net)$|^wa\.me$', 'WhatsApp'), (r'^t\.co$|(^|\.)twitter\.com$|(^|\.)x\.com$', 'X'),
           (r'(^|\.)linkedin\.com$|^lnkd\.in$', 'LinkedIn'), (r'(^|\.)youtube\.com$|^youtu\.be$', 'YouTube'),
           (r'(^|\.)chatgpt\.com$|(^|\.)openai\.com$', 'ChatGPT'), (r'(^|\.)perplexity\.ai$', 'Perplexity'),
           (r'(^|\.)reddit\.com$', 'Reddit'), (r'(^|\.)quora\.com$', 'Quora'))
# utm_source words people type, in our words
UTM_WORDS = {'google': 'Google', 'facebook': 'Facebook', 'fb': 'Facebook', 'instagram': 'Instagram', 'ig': 'Instagram',
             'whatsapp': 'WhatsApp', 'wa': 'WhatsApp', 'linkedin': 'LinkedIn', 'youtube': 'YouTube', 'email': 'E-mail',
             'newsletter': 'E-mail', 'twitter': 'X', 'x': 'X', 'bing': 'Bing'}
DIRECT = 'Direct'

PERIODS = (('now', 'On the site now', None), ('day', 'Last 24 hours', timedelta(days=1)),
           ('week', 'Last 7 days', timedelta(days=7)), ('month', 'Last 30 days', timedelta(days=30)),
           ('all', 'Last %d days' % KEEP_DAYS, timedelta(days=KEEP_DAYS)))
PERIOD_SPAN = {k: span for k, _w, span in PERIODS}

# ------------------------------------------------------------------------------------------------ the IP list
GEO_FILE = 'dbip-city-lite.mmdb'
GEO_URL = 'https://download.db-ip.com/free/dbip-city-lite-{month}.mmdb.gz'
GEO_SETTING = 'visitors.geo'
GEO_OLD = timedelta(days=35)             # DB-IP publishes a new list each month
GEO_RETRY = 6 * 3600                     # seconds between tries by itself after one failed
GEO_MAX = 400 * 1024 * 1024              # the unpacked file; this month's is about 130 MB
GEO_CREDIT = ('IP Geolocation by DB-IP', 'https://db-ip.com')     # the list's licence (CC BY 4.0) asks for this line

_geo = {'reader': None, 'mtime': None, 'path': None, 'tried': 0.0}
_geo_lock = threading.Lock()
_purged = {'at': 0.0}
PURGE_EVERY = 6 * 3600


def geo_path():
    return os.path.join(current_app.instance_path, 'geo', GEO_FILE)


def _reader():
    """The list, opened once per process (memory-mapped: two workers share one copy) and again when a new one lands."""
    path = geo_path()
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    if _geo['reader'] is not None and _geo['mtime'] == mtime and _geo['path'] == path:
        return _geo['reader']
    with _geo_lock:
        try:
            import maxminddb
            reader = maxminddb.open_database(path, maxminddb.MODE_MMAP)
        except Exception:                                # noqa: BLE001 -- a broken file places nobody, it breaks nothing
            log.exception('visitors: could not open %s', path)
            return None
        _geo.update(reader=reader, mtime=mtime, path=path)
        return reader


def _close_reader():
    with _geo_lock:
        reader, _geo['reader'], _geo['mtime'] = _geo['reader'], None, None
        if reader is not None:
            try:
                reader.close()
            except Exception:                            # noqa: BLE001
                pass


def locate(ip):
    """{'country_code', 'country', 'region', 'city'} for an address, from our copy of the list; {} when it cannot say
    (no list yet, a local or private address, an address it does not know)."""
    try:
        if not ip or not ipaddress.ip_address(ip).is_global:
            return {}
    except ValueError:
        return {}
    reader = _reader()
    if reader is None:
        return {}
    try:
        rec = reader.get(ip) or {}
    except Exception:                                    # noqa: BLE001
        return {}

    def en(part):
        return ((part or {}).get('names') or {}).get('en')
    subs = rec.get('subdivisions') or []
    out = {'country_code': ((rec.get('country') or {}).get('iso_code') or '')[:2].upper() or None,
           'country': (en(rec.get('country')) or '')[:80] or None,
           'region': (en(subs[0]) or '')[:80] or None if subs else None,
           'city': (en(rec.get('city')) or '')[:80] or None}
    return out if out['country_code'] or out['city'] else {}


def geo_status():
    """What the Visitors screen says about the list: {'has', 'month', 'at', 'mb', 'old', 'error', 'tried_at'}."""
    saved = settings.get_setting(GEO_SETTING) or {}
    saved = saved if isinstance(saved, dict) else {}
    path = geo_path()
    has = os.path.exists(path)
    at = datetime.utcfromtimestamp(os.path.getmtime(path)) if has else None
    return {'has': has, 'month': saved.get('month') if has else None, 'at': at,
            'mb': round(os.path.getsize(path) / 1048576) if has else 0,
            'old': bool(has and datetime.utcnow() - at > GEO_OLD),
            'error': saved.get('error'), 'tried_at': saved.get('tried_at'), 'credit': GEO_CREDIT}


def _auto_geo():
    if current_app.config.get('VISITOR_GEO_AUTO') is not None:
        return bool(current_app.config['VISITOR_GEO_AUTO'])
    if (os.environ.get('VISITOR_GEO') or '').strip().lower() in ('off', '0', 'no', 'false'):
        return False
    return not current_app.testing


def ensure_geo():
    """Fetch the list in the background when it is missing or a month old -- at most every GEO_RETRY seconds per
    process, so a site that cannot reach DB-IP does not try on every visit."""
    if not _auto_geo() or time.time() - _geo['tried'] < GEO_RETRY:
        return False
    path = geo_path()
    if os.path.exists(path) and datetime.utcnow() - datetime.utcfromtimestamp(os.path.getmtime(path)) < GEO_OLD:
        return False
    _geo['tried'] = time.time()
    refresh_geo_soon()
    return True


def refresh_geo_soon():
    """refresh_geo in the background: the download takes a minute or two."""
    app = current_app._get_current_object()

    def run():
        with app.app_context():
            try:
                refresh_geo()
            except Exception:                            # noqa: BLE001 -- logged; the next try is GEO_RETRY away
                log.exception('visitors: the IP list download failed')
                db.session.rollback()
    threading.Thread(target=run, name='visitors-geo', daemon=True).start()


def _months(now):
    first = now.replace(day=1)
    return [now.strftime('%Y-%m'), (first - timedelta(days=1)).strftime('%Y-%m')]


def refresh_geo(now=None):
    """Download this month's list (last month's while this month's is not out yet) into instance/geo, check that it
    places a well-known address, and swap it in. Returns (ok, words); the try is kept in GEO_SETTING."""
    import requests
    import maxminddb
    now = now or datetime.utcnow()
    path = geo_path()
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    lock = os.path.join(folder, 'download.lock')
    try:                                             # one download at a time, across the server's workers
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        if time.time() - os.path.getmtime(lock) < 1800:
            return False, 'A download is already running. Look again in a few minutes.'
        os.remove(lock)
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)
    template = (current_app.config.get('VISITOR_GEO_URL') or os.environ.get('VISITOR_GEO_URL') or GEO_URL).strip()
    tmp = path + '.part'
    said = 'The list could not be downloaded.'
    try:
        for month in _months(now):
            url = template.format(month=month)
            try:
                size = 0
                with requests.get(url, stream=True, timeout=(10, 120)) as r:
                    if r.status_code == 404:
                        said = 'DB-IP has no list for %s yet.' % month
                        continue
                    r.raise_for_status()
                    unzip = zlib.decompressobj(16 + zlib.MAX_WBITS) if url.endswith('.gz') else None
                    with open(tmp, 'wb') as fh:
                        for chunk in r.iter_content(1 << 20):
                            part = unzip.decompress(chunk) if unzip else chunk
                            size += len(part)
                            if size > GEO_MAX:
                                raise ValueError('the file is larger than expected')
                            fh.write(part)
                        if unzip:
                            fh.write(unzip.flush())
                check = maxminddb.open_database(tmp, maxminddb.MODE_FILE)
                try:
                    placed = ((check.get('8.8.8.8') or {}).get('country') or {}).get('iso_code')
                finally:
                    check.close()
                if placed != 'US':
                    raise ValueError('the file does not read as an IP list')
                _close_reader()
                os.replace(tmp, path)
                settings.set_setting(GEO_SETTING, {'month': month, 'error': None,
                                                   'tried_at': now.isoformat(timespec='seconds')})
                return True, 'The IP list is up to date: DB-IP, %s (%d MB).' % (month, size // 1048576)
            except Exception as exc:                     # noqa: BLE001 -- said on the screen, and the old file stays
                log.warning('visitors: %s: %s', url, exc)
                said = 'The list could not be downloaded (%s).' % (str(exc)[:160] or exc.__class__.__name__)
        settings.set_setting(GEO_SETTING, {'month': (settings.get_setting(GEO_SETTING) or {}).get('month'),
                                           'error': said, 'tried_at': now.isoformat(timespec='seconds')})
        return False, said
    finally:
        for p in (tmp, lock):
            try:
                os.remove(p)
            except OSError:
                pass


# ------------------------------------------------------------------------------------------------ the visitor

def ping_url():
    """Where the bubble reports a visit: the app's own address, so the visitor's own address is the one that reaches
    us (a proxy in front -- the Cloudflare forwarder on nriparentservice.com -- would put its own there).
    VISITOR_PING_URL names it; on Railway the service's own domain is the default. '' while neither is known (on a
    laptop): the bubble then reports where it was loaded from."""
    base = (current_app.config.get('VISITOR_PING_URL') or os.environ.get('VISITOR_PING_URL') or '').strip()
    if not base:
        dom = (os.environ.get('RAILWAY_PUBLIC_DOMAIN') or '').strip().strip('/')
        base = 'https://' + dom if dom else ''
    return base.rstrip('/') + '/api/live-chat/here' if base else ''


def address():
    """The visitor's address, as the host's own proxy saw it (ProxyFix took it from there). None for a ping that came
    through our forwarder (it alone sends X-Forwarded-Prefix): that address is the forwarder's, not theirs."""
    if not has_request_context() or request.headers.get('X-Forwarded-Prefix'):
        return None
    try:
        return str(ipaddress.ip_address((request.remote_addr or '').strip()))
    except ValueError:
        return None


def is_bot(ua):
    return not ua or bool(BOT_RE.search(ua))


def device_of(ua, touch=False):
    """(browser, system, 'phone' / 'tablet' / 'computer') from a browser's User-Agent."""
    ua = ua or ''
    browser = next((name for rx, name in BROWSERS if re.search(rx, ua)), 'Other')
    system = next((name for rx, name in SYSTEMS if re.search(rx, ua)), 'Other')
    if re.search(r'iPad|Tablet|PlayBook|Silk', ua) or (system == 'Android' and 'Mobile' not in ua):
        device = 'tablet'
    elif re.search(r'Mobi|iPhone|iPod|Android', ua):
        device = 'phone'
    elif system == 'macOS' and touch:             # an iPad asks for the desktop pages and says it is a Mac
        device, system = 'tablet', 'iOS'
    else:
        device = 'computer'
    return browser, system, device


def _host(url):
    try:
        host = (urlsplit(url or '').hostname or '').lower()
    except ValueError:
        return ''
    return host[4:] if host.startswith('www.') else host


def source_of(page_url, referrer):
    """(how they came, the campaign words) for a page opened from outside: the page's utm_* words first, then an ad
    click's id, then the linking page's host; (None, campaign) when the link was from our own site; DIRECT without any."""
    try:
        q = parse_qs(urlsplit(page_url or '').query)
    except ValueError:
        q = {}
    utm = [(q.get(k) or [''])[0].strip()[:60] for k in ('utm_source', 'utm_medium', 'utm_campaign')]
    campaign = ' / '.join(u for u in utm if u)[:200] or None
    if utm[0]:
        return UTM_WORDS.get(utm[0].lower(), utm[0][:60]), campaign
    if q.get('gclid') or q.get('gbraid') or q.get('wbraid'):
        return 'Google Ads', campaign
    if q.get('fbclid'):
        return 'Facebook', campaign
    ref = _host(referrer)
    if not ref:
        return DIRECT, campaign
    if ref == _host(page_url):
        return None, campaign
    return next((name for rx, name in SOURCES if re.search(rx, ref)), ref[:60]), campaign


def _page(url):
    url = str(url or '').strip().split('#', 1)[0][:500]
    return url if url.startswith(('https://', 'http://')) else None


def _words(text, n):
    return ' '.join(str(text or '').split())[:n] or None


def _place(v, ip):
    """Their address, and where it is, when it is new to us (or the list has come since)."""
    if ip and (ip != v.ip or not v.country_code):
        where = locate(ip)
        if ip != v.ip or where:
            v.ip = ip
            v.country_code, v.country = where.get('country_code'), where.get('country')
            v.region, v.city = where.get('region'), where.get('city')


def ping(data, ua, ip, now=None):
    """One word from the bubble: a page opened ('view'), it still shows ('beat'), it closed ('leave'). Returns the
    CrmVisitor, or None when there is nothing to keep (a robot, a malformed id, a word from a browser we let go of).
    Commits when something changed."""
    data = data if isinstance(data, dict) else {}
    vid = str(data.get('vid') or '')
    if not VID_RE.match(vid) or is_bot(ua):
        return None
    kind = data.get('kind') if data.get('kind') in ('view', 'beat', 'leave') else 'beat'
    now = now or datetime.utcnow()
    v = CrmVisitor.query.filter_by(vid=vid).first()
    if v is None and kind != 'view':
        return None
    if kind == 'view':
        page = _page(data.get('page'))
        if page is None:
            return None
        came, campaign = source_of(page, data.get('ref'))
        if v is None:
            v = CrmVisitor(vid=vid, first_at=now, visit_at=now, visits=1, pages=0, site=_host(page)[:120] or None,
                           landing_url=page, source=came or DIRECT, campaign=campaign,
                           referrer=_page(data.get('ref')) if came not in (None, DIRECT) else None)
            db.session.add(v)
            new_visit = True
        else:
            new_visit = v.last_at is None or now - v.last_at > VISIT_GAP
            if new_visit:
                v.visits = (v.visits or 0) + 1
                v.visit_at = now
            _close_page(v, now)
        v.browser, v.os, v.device = device_of(ua, touch=bool(data.get('touch')))
        v.lang = _words(data.get('lang'), 20)
        v.tz = _words(data.get('tz'), 64)
        _place(v, ip)
        v.page_url, v.page_title = page, _words(data.get('title'), 200)
        v.pages = (v.pages or 0) + 1
        v.last_at, v.gone_at = now, None
        db.session.flush()
        db.session.add(CrmVisitorPage(visitor_id=v.id, at=now, url=page, title=v.page_title, visit=v.visits, secs=0,
                                      came_from=(came if new_visit and came else None)))
    elif kind == 'beat':
        if v.gone_at is None and v.last_at is not None and now - v.last_at < BEAT_WRITE:
            return v
        if v.last_at is not None and now - v.last_at > VISIT_GAP:
            # the computer slept with our page open, and they are reading it again: a new visit, on that page
            v.visits = (v.visits or 0) + 1
            v.visit_at, v.pages = now, (v.pages or 0) + 1
            db.session.add(CrmVisitorPage(visitor_id=v.id, at=now, url=v.page_url, title=v.page_title, visit=v.visits,
                                          secs=0))
        _place(v, ip)
        v.last_at, v.gone_at = now, None
        _close_page(v, now)
    else:
        _close_page(v, now)
        v.gone_at = now
    db.session.commit()
    _purge_now_and_then(now)
    return v


def _close_page(v, now):
    """How long the page they are on has shown so far."""
    last = (CrmVisitorPage.query.filter_by(visitor_id=v.id).order_by(CrmVisitorPage.at.desc(), CrmVisitorPage.id.desc())
            .first())
    if last is not None and last.visit == v.visits:
        last.secs = max(int((now - last.at).total_seconds()), last.secs or 0)


def link_chat(chat, vid):
    """A chat started from this browser: the chat knows where they are, the browser knows who they are. No commit."""
    if not chat or not VID_RE.match(str(vid or '')):
        return None
    v = CrmVisitor.query.filter_by(vid=str(vid)).first()
    if v is None:
        return None
    chat.visitor_id = v.id
    if chat.person_id:
        v.person_id = chat.person_id
    return v


def purge(now=None):
    """Let go of browsers not seen for KEEP_DAYS, and of older pages. Their chats stay (with their own page).
    Returns how many browsers went. Commits."""
    cut = (now or datetime.utcnow()) - timedelta(days=KEEP_DAYS)
    CrmVisitorPage.query.filter(CrmVisitorPage.at < cut).delete(synchronize_session=False)
    old = [i for (i,) in db.session.query(CrmVisitor.id).filter(CrmVisitor.last_at < cut)]
    if old:
        CrmLiveChat.query.filter(CrmLiveChat.visitor_id.in_(old)).update({'visitor_id': None},
                                                                         synchronize_session=False)
        CrmVisitorPage.query.filter(CrmVisitorPage.visitor_id.in_(old)).delete(synchronize_session=False)
        CrmVisitor.query.filter(CrmVisitor.id.in_(old)).delete(synchronize_session=False)
    db.session.commit()
    return len(old)


def _purge_now_and_then(now):
    if time.time() - _purged['at'] < PURGE_EVERY:
        return
    _purged['at'] = time.time()
    try:
        purge(now)
    except Exception:                                    # noqa: BLE001 -- tried again in PURGE_EVERY
        db.session.rollback()
        log.exception('visitors: purge failed')


# ------------------------------------------------------------------------------------------------ the screen

def here(v, now=None):
    return bool(v is not None and v.gone_at is None and v.last_at is not None
                and (now or datetime.utcnow()) - v.last_at < HERE_FOR)


def show_ip(ip, masked=False):
    """The address as the screen shows it: 49.207.•.• to a role that masks contact details."""
    if not ip:
        return ''
    if not masked:
        return ip
    if ':' in ip:
        return ':'.join(ip.split(':')[:2]) + ':…'
    parts = ip.split('.')
    return '.'.join(parts[:2] + ['•', '•']) if len(parts) == 4 else '•••'


def place(v):
    """'Bengaluru, Karnataka, India' -- or the browser's own time zone when the list cannot say."""
    bits = [b for b in (v.city, v.region, v.country) if b]
    if v.city and v.region and v.city.startswith(v.region):
        bits.remove(v.region)
    if bits:
        return ', '.join(dict.fromkeys(bits))
    if v.ip and not _global(v.ip):
        return 'Local network'
    return ('Time zone %s' % v.tz) if v.tz else 'Not known yet'


def _global(ip):
    try:
        return ipaddress.ip_address(ip).is_global
    except ValueError:
        return False


def filters(args):
    f = {'when': args.get('when') if args.get('when') in PERIOD_SPAN else 'week',
         'country': (args.get('country') or '').strip().upper()[:2],
         'source': (args.get('source') or '').strip()[:60],
         'device': args.get('device') if args.get('device') in DEVICE_WORD else '',
         'chat': args.get('chat') if args.get('chat') in ('yes', 'no') else '',
         'q': ' '.join((args.get('q') or '').split())[:80]}
    f['active'] = any(f[k] for k in ('country', 'source', 'device', 'chat', 'q'))
    return f


def _since(when, now):
    return now - (PERIOD_SPAN.get(when) or HERE_FOR)


def _chatted_ids(ids):
    if not ids:
        return set()
    return {i for (i,) in db.session.query(CrmLiveChat.visitor_id).filter(CrmLiveChat.visitor_id.in_(ids)).distinct()}


def find(f, n=1, now=None):
    """The visitors the filters pick, last seen first: {'rows', 'total', 'n', 'pages'}."""
    now = now or datetime.utcnow()
    q = CrmVisitor.query.filter(CrmVisitor.last_at >= _since(f['when'], now))
    if f['when'] == 'now':
        q = q.filter(CrmVisitor.gone_at.is_(None))
    if f['country']:
        q = q.filter(CrmVisitor.country_code == f['country'])
    if f['source']:
        q = q.filter(CrmVisitor.source == f['source'])
    if f['device']:
        q = q.filter(CrmVisitor.device == f['device'])
    chatted = select(CrmLiveChat.visitor_id).where(CrmLiveChat.visitor_id.isnot(None))
    if f['chat'] == 'yes':
        q = q.filter(or_(CrmVisitor.person_id.isnot(None), CrmVisitor.id.in_(chatted)))
    elif f['chat'] == 'no':
        q = q.filter(CrmVisitor.person_id.is_(None), ~CrmVisitor.id.in_(chatted))
    if f['q']:
        like = '%' + f['q'].replace('%', '').replace('_', '') + '%'
        named = select(CrmPerson.id).where(CrmPerson.name.ilike(like))
        q = q.filter(or_(CrmVisitor.ip.ilike(like), CrmVisitor.city.ilike(like), CrmVisitor.region.ilike(like),
                         CrmVisitor.country.ilike(like), CrmVisitor.page_url.ilike(like),
                         CrmVisitor.page_title.ilike(like), CrmVisitor.landing_url.ilike(like),
                         CrmVisitor.person_id.in_(named)))
    total = q.count()
    pages = max(1, -(-total // PER_PAGE))
    n = min(max(1, n), pages)
    rows = q.order_by(CrmVisitor.last_at.desc(), CrmVisitor.id.desc()).offset((n - 1) * PER_PAGE).limit(PER_PAGE).all()
    return {'rows': _rows(rows, now), 'total': total, 'n': n, 'pages': pages}


def _rows(visitors, now):
    chatted = _chatted_ids([v.id for v in visitors])
    return [{'v': v, 'here': here(v, now), 'place': place(v), 'chatted': v.id in chatted or bool(v.person_id),
             'on_for': int((now - (v.visit_at or v.first_at)).total_seconds()) if here(v, now) else None}
            for v in visitors]


def now_list(now=None, limit=200):
    """Who is on the site now, the longest here first."""
    now = now or datetime.utcnow()
    rows = (CrmVisitor.query.filter(CrmVisitor.last_at >= now - HERE_FOR, CrmVisitor.gone_at.is_(None))
            .order_by(CrmVisitor.visit_at.asc(), CrmVisitor.id.asc()).limit(limit).all())
    return _rows(rows, now)


def _top(column, since, n=6):
    return (db.session.query(column, func.count(CrmVisitor.id)).filter(CrmVisitor.last_at >= since)
            .group_by(column).order_by(func.count(CrmVisitor.id).desc()).limit(n).all())


def summary(now=None):
    """The figures at the top of the screen and the three lists beside the visitors (last 7 days)."""
    now = now or datetime.utcnow()
    week = now - timedelta(days=7)

    def count(since):
        return CrmVisitor.query.filter(CrmVisitor.last_at >= since).count()
    chats = (db.session.query(func.count(func.distinct(CrmLiveChat.visitor_id)))
             .filter(CrmLiveChat.visitor_id.isnot(None), CrmLiveChat.started_at >= week).scalar() or 0)
    countries = [{'code': c or '', 'name': name or ('Not known' if not c else c), 'n': k}
                 for c, name, k in (db.session.query(CrmVisitor.country_code, func.max(CrmVisitor.country),
                                                     func.count(CrmVisitor.id))
                                    .filter(CrmVisitor.last_at >= week).group_by(CrmVisitor.country_code)
                                    .order_by(func.count(CrmVisitor.id).desc()).limit(6))]
    sources = [{'name': s or DIRECT, 'n': k} for s, k in _top(CrmVisitor.source, week)]
    devices = {d: k for d, k in _top(CrmVisitor.device, week)}
    pages = [{'url': u, 'title': t or u, 'n': k} for u, t, k in
             (db.session.query(CrmVisitorPage.url, func.max(CrmVisitorPage.title), func.count(CrmVisitorPage.id))
              .filter(CrmVisitorPage.at >= week).group_by(CrmVisitorPage.url)
              .order_by(func.count(CrmVisitorPage.id).desc()).limit(6))]
    unplaced = (CrmVisitor.query.filter(CrmVisitor.last_at >= now - timedelta(days=1), CrmVisitor.ip.is_(None))
                .count())
    return {'now': len(now_list(now)), 'day': count(now - timedelta(days=1)), 'week': count(week), 'chats': chats,
            'countries': countries, 'sources': sources, 'pages': pages,
            'devices': [(k, DEVICE_WORD[k], DEVICE_ICON[k], devices.get(k, 0)) for k, _w, _i in DEVICES],
            'no_address_day': unplaced}


def choices(now=None):
    """The countries and the ways in that the last KEEP_DAYS saw, for the filters."""
    since = (now or datetime.utcnow()) - timedelta(days=KEEP_DAYS)
    countries = [(c, name or c) for c, name in
                 db.session.query(CrmVisitor.country_code, func.max(CrmVisitor.country))
                 .filter(CrmVisitor.last_at >= since, CrmVisitor.country_code.isnot(None))
                 .group_by(CrmVisitor.country_code).order_by(func.max(CrmVisitor.country))]
    sources = [s for (s,) in db.session.query(CrmVisitor.source).filter(CrmVisitor.last_at >= since,
                                                                          CrmVisitor.source.isnot(None))
               .distinct().order_by(CrmVisitor.source)]
    return {'countries': countries, 'sources': sources}


def detail(v, now=None):
    """One visitor: their pages (newest first, grouped by visit) and their chats."""
    now = now or datetime.utcnow()
    pages = (CrmVisitorPage.query.filter_by(visitor_id=v.id).order_by(CrmVisitorPage.at.desc(), CrmVisitorPage.id.desc())
             .limit(PAGES_SHOWN).all())
    visits = []
    for p in pages:
        if not visits or visits[-1]['visit'] != p.visit:
            visits.append({'visit': p.visit, 'pages': []})
        visits[-1]['pages'].append(p)
    for g in visits:
        g['began'] = g['pages'][-1].at
        g['from'] = g['pages'][-1].came_from
        g['secs'] = sum(p.secs or 0 for p in g['pages'])
    chats = CrmLiveChat.query.filter_by(visitor_id=v.id).order_by(CrmLiveChat.started_at.desc()).all()
    return {'v': v, 'here': here(v, now), 'place': place(v), 'visits': visits, 'chats': chats,
            'more': (v.pages or 0) > len(pages)}


def secs_words(secs):
    """'45 s', '3 min', '1 h 20 min'."""
    secs = int(secs or 0)
    if secs < 60:
        return '%d s' % secs
    mins = secs // 60
    if mins < 60:
        return '%d min' % mins
    return '%d h %d min' % (mins // 60, mins % 60) if mins % 60 else '%d h' % (mins // 60)
