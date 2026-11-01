"""Google Search Console, read back (2026-10-29): how the site does in Google search -- the words people searched,
the pages Google showed, how often, how often people clicked and how high we came -- for the Promotion dashboard.

    connected()                                 a Search Console property and a service-account key are set
    query(start, end, dims, filters, limit, kind)   [(keys..., clicks, impressions, position)] for [start, end];
                                                `kind` the kind of search: web (the default), image, video, news,
                                                discover or googleNews
    sitemaps()                                  the sitemaps Google has of the site, and what it made of each
    indexing(top)                               whether Google has our most-shown pages in its index (URL Inspection)
    test()                                      a small real query, for the connection page

The same read-only service account as Analytics (services/ga4: its key, its token, both scopes), added in Search
Console as a user of the property (Settings > Users and permissions; Restricted is enough). Google keeps 16 months
and its newest two or three days are still filling in. Answers are kept for half an hour: the numbers change daily.
"""
import json
from datetime import timedelta
from urllib.parse import quote

import requests

from app.services import ga4

API = 'https://searchconsole.googleapis.com/webmasters/v3/sites/%s/searchAnalytics/query'
SITEMAPS_API = 'https://searchconsole.googleapis.com/webmasters/v3/sites/%s/sitemaps'
INSPECT_API = 'https://searchconsole.googleapis.com/v1/urlInspection/index:inspect'
TTL = 1800
INSPECT_TTL = 12 * 3600   # Google allows 2,000 inspections a day; a page's place in the index changes slowly
KINDS = ('web', 'image', 'video', 'news', 'discover', 'googleNews')
KEEPS_DAYS = 486          # 16 months
MAX_ROWS = 25000
_RE2_SPECIAL = set('\\.^$|?*+()[]{}')


def connected():
    return ga4.search_connected()


def _re2(value):
    return ''.join('\\' + c if c in _RE2_SPECIAL else c for c in value)


def _filters(filters):
    """{'device': ['MOBILE'], 'country': ['ind', 'usa']} -> dimensionFilterGroups: each dimension one of its values
    (one value: equals; several: an anchored regular expression), all the dimensions together."""
    out = []
    for dim, values in sorted((filters or {}).items()):
        values = [str(v) for v in values if str(v)][:50]
        if not values:
            continue
        if len(values) == 1:
            out.append({'dimension': dim, 'operator': 'equals', 'expression': values[0]})
        else:
            out.append({'dimension': dim, 'operator': 'includingRegex',
                        'expression': '^(?:%s)$' % '|'.join(_re2(v) for v in values)})
    return [{'groupType': 'and', 'filters': out}] if out else []


def _post(site, body, key):
    """One search question to the Search Console API (the seam the tests replace)."""
    return _call('POST', API % quote(site, safe=''), site, key, body)


def _call(method, url, site, key, body=None, token=None):
    """`requests.post` or `requests.get` by name, so a test that replaces one replaces every call of that kind."""
    send = requests.post if method == 'POST' else requests.get
    try:
        r = send(url, json=body, timeout=ga4.TIMEOUT,
                 headers={'Authorization': 'Bearer ' + (token or ga4._access_token(key))})
    except requests.RequestException as e:
        raise ga4.GAError('Google Search Console could not be reached. Try again in a minute.') from e
    data = ga4._json(r)
    if r.status_code != 200:
        msg = (data.get('error') or {}).get('message') or 'HTTP %s' % r.status_code
        if r.status_code == 403:
            msg = ('The service account %s is not a user of the Search Console property %s. In Search Console open '
                   'Settings > Users and permissions > Add user (Restricted is enough).' % (key.get('client_email'), site))
        elif r.status_code == 404:
            msg = ('Search Console has no property called %s. Copy its name exactly as the property list shows it '
                   '(sc-domain:... or https://.../).' % site)
        elif r.status_code == 429:
            msg = 'Search Console says too many requests for now. The numbers come back in a few minutes.'
        raise ga4.GAError(msg)
    return data


def _site_key():
    site, (key, _) = ga4.search_site(), ga4.key()
    if not site or not key:
        raise ga4.GAError('Google Search Console is not connected yet.')
    return site, key


def query(start, end, dims=(), filters=None, limit=1000, kind='web'):
    site, key = _site_key()
    body = {'startDate': start.isoformat(), 'endDate': end.isoformat(), 'dimensions': list(dims),
            'rowLimit': min(int(limit), MAX_ROWS), 'dataState': 'all', 'type': kind if kind in KINDS else 'web'}
    groups = _filters(filters)
    if groups:
        body['dimensionFilterGroups'] = groups
    ck = ('gsc', site, json.dumps(body, sort_keys=True))

    def make():
        data = _post(site, body, key)
        return [tuple(row.get('keys') or ()) + (row.get('clicks', 0), row.get('impressions', 0),
                                                 row.get('position', 0)) for row in data.get('rows') or []]
    return ga4._cached(ck, TTL, make)


def _when(v):
    """'2026-10-30T04:12:55.123Z' as an India date and time; '' when Google gave none."""
    from datetime import datetime
    from app.services import mkt_engine as eng
    try:
        t = datetime.strptime(str(v or '')[:19], '%Y-%m-%dT%H:%M:%S')
    except ValueError:
        return ''
    return (t + eng.IST).strftime('%d %b %Y, %H:%M').lstrip('0')


def sitemaps():
    """[{'path', 'kind', 'submitted', 'read', 'pending', 'errors', 'warnings', 'urls'}]: each sitemap Google has of the
    site (Search Console > Sitemaps), when it was sent and last read, and how many addresses it lists."""
    site, key = _site_key()

    def make():
        data = _call('GET', SITEMAPS_API % quote(site, safe=''), site, key)
        out = []
        for sm in data.get('sitemap') or []:
            urls = sum(int(c.get('submitted') or 0) for c in sm.get('contents') or [])
            out.append({'path': sm.get('path') or '',
                        'kind': 'Sitemap index' if sm.get('isSitemapsIndex') else 'Sitemap',
                        'submitted': _when(sm.get('lastSubmitted')), 'read': _when(sm.get('lastDownloaded')),
                        'pending': bool(sm.get('isPending')), 'errors': int(sm.get('errors') or 0),
                        'warnings': int(sm.get('warnings') or 0), 'urls': urls})
        return sorted(out, key=lambda r: r['path'])
    return ga4._cached(('gsc-sitemaps', site), TTL, make)


VERDICTS = {'PASS': 'In Google', 'PARTIAL': 'In Google, with problems', 'FAIL': 'Not in Google',
            'NEUTRAL': 'Not in Google'}


def _words(v):
    return str(v or '').replace('_', ' ').capitalize()


def _inspect(site, key, token, url):
    def make():
        data = _call('POST', INSPECT_API, site, key,
                     {'inspectionUrl': url, 'siteUrl': site, 'languageCode': 'en-GB'}, token=token)
        res = data.get('inspectionResult') or {}
        ix = res.get('indexStatusResult') or {}
        rich = res.get('richResultsResult') or {}
        return {'url': url, 'verdict': ix.get('verdict') or 'VERDICT_UNSPECIFIED',
                'state': VERDICTS.get(ix.get('verdict'), 'Not known yet'),
                'coverage': ix.get('coverageState') or '', 'crawled': _when(ix.get('lastCrawlTime')),
                'crawled_as': {'MOBILE': 'phone', 'DESKTOP': 'computer'}.get(ix.get('crawledAs'), ''),
                'fetch': _words(ix.get('pageFetchState')), 'robots': _words(ix.get('robotsTxtState')),
                'canonical': ix.get('googleCanonical') or '', 'our_canonical': ix.get('userCanonical') or '',
                'rich': sorted({i.get('richResultType') for i in rich.get('detectedItems') or []
                                if i.get('richResultType')}),
                'link': res.get('inspectionResultLink') or ''}
    return ga4._cached(('gsc-inspect', site, url), INSPECT_TTL, make)


def indexing(top=12):
    """Whether Google has our pages in its index -- the pages Google showed most in the last 28 days, the home page
    first -- by Search Console's URL Inspection, one page a question, five at a time:
    {'rows', 'indexed', 'not', 'checked', 'note'}."""
    from concurrent.futures import ThreadPoolExecutor
    from app.services import mkt_engine as eng
    site, key = _site_key()
    t = eng.today()
    pages = [r[0] for r in sorted(query(t - timedelta(days=27), t, ['page'], limit=max(top, 1) * 2),
                                  key=lambda r: -r[2])]
    if site.startswith('http'):
        pages.insert(0, site)
    pages = list(dict.fromkeys(pages))[:top]
    token = ga4._access_token(key)
    errors = []

    def one(url):
        try:
            return _inspect(site, key, token, url)
        except ga4.GAError as e:
            errors.append(str(e))
            return None
    with ThreadPoolExecutor(max_workers=5) as pool:
        rows = [r for r in pool.map(one, pages) if r]
    if not rows and errors:
        raise ga4.GAError(errors[0])
    return {'rows': rows, 'indexed': sum(1 for r in rows if r['verdict'] == 'PASS'),
            'not': sum(1 for r in rows if r['verdict'] != 'PASS'), 'checked': len(rows),
            'note': ('%d page%s could not be checked: %s' % (len(errors), 's' if len(errors) != 1 else '', errors[0]))
            if errors else ''}


def test():
    """Clicks and times shown in the last 28 days. Raises ga4.GAError with what to fix."""
    from app.services import mkt_engine as eng
    t = eng.today()
    rows = query(t - timedelta(days=27), t)
    clicks, shown = (rows[0][0], rows[0][1]) if rows else (0, 0)
    return {'clicks': int(clicks), 'impressions': int(shown)}
