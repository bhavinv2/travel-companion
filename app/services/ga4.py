"""Google Analytics 4, read back: the numbers the site's own tag (services/analytics, G-...) sends to Google, asked
for again through the Analytics Data API so the Promotion dashboard can show them (2026-10-29).

    connected()                       is a property id and a service-account key set (here or on the server)
    report(start, end, metrics, dims, limit, order, filters)   {'rows': [(dims..., metrics...)], 'totals': [...]}
    realtime(metrics, dims, limit)    the last 30 minutes, the same shape
    status()                          what the connection page shows: property, the key's e-mail, where it is set
    save(property_id, key_json, by)   the connection page's Save; the key is sealed (services/secretbox)
    test()                            a small real report, for the page's "Test the connection"

HOW IT SIGNS IN. A Google Cloud service account (its JSON key) that the GA4 property has as a Viewer. The key signs
a JWT (RS256, `cryptography`), Google answers an access token for an hour, and every call carries it. Read-only
scope: nothing here can change the property.

WHERE THE SETTINGS LIVE. The connection page saves them in app settings (`mkt.ga4`, the key sealed). The server's
GA4_PROPERTY_ID / GA4_SERVICE_ACCOUNT (the key's JSON) are used when nothing is saved, so a deploy can set them
too. The measurement id the tag uses (G-...) is not the property id (a number): Admin > Property details shows it.

Answers are kept for a few minutes (REPORT_TTL; REALTIME_TTL for the last 30 minutes) per worker: a dashboard of
twelve boxes opened by five people is not sixty calls to Google, and the property's daily quota stays far away.
"""
import base64
import json
import os
import threading
import time
from datetime import date

import requests

# one read-only token for both: Analytics, and Search Console (services/gsc)
SCOPE = 'https://www.googleapis.com/auth/analytics.readonly https://www.googleapis.com/auth/webmasters.readonly'
API = 'https://analyticsdata.googleapis.com/v1beta/properties/%s:%s'
TOKEN_URI = 'https://oauth2.googleapis.com/token'
SETTING = 'mkt.ga4'
REPORT_TTL = 600
REALTIME_TTL = 30
TIMEOUT = 20

_cache = {}
_lock = threading.Lock()
_token = {'value': None, 'until': 0.0, 'who': None}


class GAError(Exception):
    """Something Google said no to, in words a person can act on."""


# ================================================================================================ settings

def _saved():
    from app.services import settings
    raw = settings.get_setting(SETTING) or {}
    return raw if isinstance(raw, dict) else {}


def _key_from_text(text):
    try:
        key = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(key, dict) or not key.get('client_email') or not key.get('private_key'):
        return None
    return key


def key():
    """(the service-account key as a dict, where it came from): the saved one, else the server's -- or (None, None)."""
    from app.services import secretbox
    saved = _saved()
    if saved.get('key'):
        opened = secretbox.open(saved['key'])
        if opened and opened.get('key'):
            return opened['key'], 'saved'
    env_key = _key_from_text(os.environ.get('GA4_SERVICE_ACCOUNT') or '')
    return (env_key, 'server') if env_key else (None, None)


def _config():
    """(property id, the key as a dict, where the key came from) -- or (None, None, None)."""
    k, where = key()
    pid = str(_saved().get('property_id') or '').strip() or (os.environ.get('GA4_PROPERTY_ID') or '').strip()
    if pid and k:
        return pid, k, where
    return None, None, None


def search_site():
    """The Search Console property the search boxes read ('sc-domain:example.com' or 'https://example.com/')."""
    return str(_saved().get('sc_site') or '').strip() or (os.environ.get('GSC_SITE_URL') or '').strip() or None


def connected():
    pid, k, _ = _config()
    return bool(pid and k)


def search_connected():
    return bool(search_site() and key()[0])


def status():
    pid, k, where = _config()
    saved = _saved()
    from app.services import secretbox
    unreadable = bool(saved.get('key')) and secretbox.open(saved['key']) is None
    k = k or key()[0]
    return {'connected': bool(pid and k), 'property_id': pid or str(saved.get('property_id') or ''),
            'email': (k or {}).get('client_email') or saved.get('email') or '', 'where': where or key()[1],
            'has_key': bool(k), 'search_connected': search_connected(), 'sc_site': search_site() or '',
            'unreadable': unreadable, 'saved_at': saved.get('saved_at'), 'saved_by': saved.get('saved_by'),
            'server_set': bool((os.environ.get('GA4_PROPERTY_ID') or '').strip())}


def clean_search_site(text):
    """A Search Console property as Search Console names it: a domain property ('sc-domain:example.com') or a URL
    prefix ('https://example.com/', its slash kept)."""
    text = str(text or '').strip()
    if not text:
        return ''
    low = text.lower()
    if low.startswith('sc-domain:'):
        host = low.split(':', 1)[1].strip().strip('/')
        if host and '.' in host and ' ' not in host and '/' not in host:
            return 'sc-domain:' + host
    elif low.startswith(('https://', 'http://')) and ' ' not in text and '.' in text:
        return text if text.endswith('/') else text + '/'
    raise GAError('The Search Console property is written as Search Console shows it: sc-domain:nriparentservice.com '
                  '(a domain property) or https://nriparentservice.com/ (a URL-prefix property).')


def clean_property_id(text):
    text = str(text or '').strip()
    if text.lower().startswith('properties/'):
        text = text.split('/', 1)[1]
    if not text.isdigit() or not 4 <= len(text) <= 15:
        raise GAError('The property id is a number, like 412345678 (Admin > Property details). It is not the '
                      'G-... measurement id.')
    return text


def save(property_id, key_text, by=None, sc_site=None):
    """Keep the connection: the Analytics property, the Search Console property, or both. An empty key keeps the one
    saved before (a page never shows it again)."""
    from app.services import secretbox, settings
    saved = _saved()
    site = clean_search_site(sc_site if sc_site is not None else saved.get('sc_site'))
    pid = clean_property_id(property_id) if str(property_id or '').strip() or not site else ''
    out = {'property_id': pid, 'sc_site': site, 'key': saved.get('key'), 'email': saved.get('email')}
    if str(key_text or '').strip():
        key = _key_from_text(key_text)
        if key is None:
            raise GAError('That is not a service-account key. Paste the whole JSON file Google Cloud downloaded '
                          '(it has "client_email" and "private_key" in it).')
        out['key'] = secretbox.seal({'key': key})
        out['email'] = key['client_email']
    elif not out['key']:
        raise GAError('Paste the service account key (the JSON file) as well.')
    out['saved_at'] = time.strftime('%Y-%m-%d %H:%M')
    out['saved_by'] = getattr(by, 'full_name', None) or getattr(by, 'username', None)
    settings.set_setting(SETTING, out, actor=by)
    forget()
    return out


def disconnect(by=None):
    from app.services import settings
    settings.set_setting(SETTING, {}, actor=by)
    forget()


def forget():
    with _lock:
        _cache.clear()
        _token.update(value=None, until=0.0, who=None)


# ================================================================================================ signing in

def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def _jwt(key, now):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    head = _b64(json.dumps({'alg': 'RS256', 'typ': 'JWT'}).encode())
    claims = _b64(json.dumps({'iss': key['client_email'], 'scope': SCOPE, 'aud': key.get('token_uri') or TOKEN_URI,
                              'iat': int(now), 'exp': int(now) + 3600}).encode())
    try:
        pk = serialization.load_pem_private_key(key['private_key'].encode(), password=None)
    except (ValueError, TypeError) as e:
        raise GAError('The key file\'s private key cannot be read. Download a new key for the service account.') from e
    sig = pk.sign(('%s.%s' % (head, claims)).encode(), padding.PKCS1v15(), hashes.SHA256())
    return '%s.%s.%s' % (head, claims, _b64(sig))


def _access_token(key):
    now = time.time()
    with _lock:
        if _token['value'] and _token['until'] > now + 60 and _token['who'] == key['client_email']:
            return _token['value']
    try:
        r = requests.post(key.get('token_uri') or TOKEN_URI, timeout=TIMEOUT, data={
            'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer', 'assertion': _jwt(key, now)})
    except requests.RequestException as e:
        raise GAError('Google could not be reached to sign in. Try again in a minute.') from e
    body = _json(r)
    if r.status_code != 200 or not body.get('access_token'):
        raise GAError('Google did not accept the service account key (%s). Download a new key, or check the '
                      'account was not deleted.' % (body.get('error_description') or body.get('error') or r.status_code))
    with _lock:
        _token.update(value=body['access_token'], until=now + int(body.get('expires_in') or 3600),
                      who=key['client_email'])
    return body['access_token']


def _json(r):
    try:
        out = r.json()
    except ValueError:
        return {}
    return out if isinstance(out, dict) else {}


def _post(pid, method, body, key):
    """One call to the Data API (the seam the tests replace)."""
    try:
        r = requests.post(API % (pid, method), json=body, timeout=TIMEOUT,
                          headers={'Authorization': 'Bearer ' + _access_token(key)})
    except requests.RequestException as e:
        raise GAError('Google Analytics could not be reached. Try again in a minute.') from e
    data = _json(r)
    if r.status_code != 200:
        err = data.get('error') or {}
        msg = err.get('message') or 'HTTP %s' % r.status_code
        if r.status_code == 403:
            msg = ('The service account %s may not read property %s. In Google Analytics open Admin > Property '
                   'access management and add it as a Viewer.' % (key.get('client_email'), pid))
        elif r.status_code == 429:
            msg = 'Google Analytics says too many requests for now. The numbers come back in a few minutes.'
        raise GAError(msg)
    return data


# ================================================================================================ the reports

def _rows(data, n_dims):
    out = []
    for row in data.get('rows') or []:
        dims = [d.get('value', '') for d in row.get('dimensionValues') or []]
        mets = [_num(m.get('value')) for m in row.get('metricValues') or []]
        out.append(tuple(dims[:n_dims]) + tuple(mets))
    totals = []
    for t in (data.get('totals') or [])[:1]:
        totals = [_num(m.get('value')) for m in t.get('metricValues') or []]
    return {'rows': out, 'totals': totals}


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0
    return int(f) if f.is_integer() else f


def _filter(filters):
    """{'country': ['India', 'United States']} -> a dimensionFilter: each dimension one of its values, all of them."""
    exprs = [{'filter': {'fieldName': name, 'inListFilter': {'values': [str(v) for v in values][:50]}}}
             for name, values in sorted((filters or {}).items()) if values]
    if not exprs:
        return None
    return exprs[0] if len(exprs) == 1 else {'andGroup': {'expressions': exprs}}


def _cached(key, ttl, make):
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
    value = make()
    with _lock:
        if len(_cache) > 500:
            _cache.clear()
        _cache[key] = (now + ttl, value)
    return value


def report(start, end, metrics, dims=(), limit=1000, order=None, filters=None):
    """GA4's runReport for [start, end] (dates, the property's own time zone). `order`: ('metric'|'dim', name, desc)."""
    pid, key, _ = _config()
    if not pid:
        raise GAError('Google Analytics is not connected yet.')
    body = {'dateRanges': [{'startDate': _iso(start), 'endDate': _iso(end)}],
            'metrics': [{'name': m} for m in metrics], 'dimensions': [{'name': d} for d in dims],
            'limit': int(limit), 'metricAggregations': ['TOTAL'], 'keepEmptyRows': False}
    flt = _filter(filters)
    if flt:
        body['dimensionFilter'] = flt
    if order:
        kind, name, desc = order
        body['orderBys'] = [{'metric': {'metricName': name}, 'desc': bool(desc)} if kind == 'metric'
                            else {'dimension': {'dimensionName': name}, 'desc': bool(desc)}]
    ck = ('r', pid, json.dumps(body, sort_keys=True))
    return _cached(ck, REPORT_TTL, lambda: _rows(_post(pid, 'runReport', body, key), len(dims)))


def realtime(metrics=('activeUsers',), dims=(), limit=50, filters=None):
    pid, key, _ = _config()
    if not pid:
        raise GAError('Google Analytics is not connected yet.')
    body = {'metrics': [{'name': m} for m in metrics], 'dimensions': [{'name': d} for d in dims],
            'limit': int(limit), 'metricAggregations': ['TOTAL']}
    flt = _filter(filters)
    if flt:
        body['dimensionFilter'] = flt
    ck = ('rt', pid, json.dumps(body, sort_keys=True))
    return _cached(ck, REALTIME_TTL, lambda: _rows(_post(pid, 'runRealtimeReport', body, key), len(dims)))


def _iso(d):
    return d.isoformat() if isinstance(d, date) else str(d)


def test():
    """A real, small report: visitors in the last 7 days and right now. Raises GAError with what to fix."""
    forget()
    week = report('7daysAgo', 'today', ['activeUsers', 'sessions'])
    now = realtime()
    return {'users': (week['totals'] or [0, 0])[0], 'sessions': (week['totals'] or [0, 0])[1],
            'now': (now['totals'] or [0])[0]}
