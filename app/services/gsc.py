"""Google Search Console, read back (2026-10-29): how the site does in Google search -- the words people searched,
the pages Google showed, how often, how often people clicked and how high we came -- for the Promotion dashboard.

    connected()                                 a Search Console property and a service-account key are set
    query(start, end, dims, filters, limit)     [(keys..., clicks, impressions, position)] for [start, end]
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
TTL = 1800
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
    """One call to the Search Console API (the seam the tests replace)."""
    try:
        r = requests.post(API % quote(site, safe=''), json=body, timeout=ga4.TIMEOUT,
                          headers={'Authorization': 'Bearer ' + ga4._access_token(key)})
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


def query(start, end, dims=(), filters=None, limit=1000):
    site, (key, _) = ga4.search_site(), ga4.key()
    if not site or not key:
        raise ga4.GAError('Google Search Console is not connected yet.')
    body = {'startDate': start.isoformat(), 'endDate': end.isoformat(), 'dimensions': list(dims),
            'rowLimit': min(int(limit), MAX_ROWS), 'dataState': 'all', 'type': 'web'}
    groups = _filters(filters)
    if groups:
        body['dimensionFilterGroups'] = groups
    ck = ('gsc', site, json.dumps(body, sort_keys=True))

    def make():
        data = _post(site, body, key)
        return [tuple(row.get('keys') or ()) + (row.get('clicks', 0), row.get('impressions', 0),
                                                 row.get('position', 0)) for row in data.get('rows') or []]
    return ga4._cached(ck, TTL, make)


def test():
    """Clicks and times shown in the last 28 days. Raises ga4.GAError with what to fix."""
    from app.services import mkt_engine as eng
    t = eng.today()
    rows = query(t - timedelta(days=27), t)
    clicks, shown = (rows[0][0], rows[0][1]) if rows else (0, 0)
    return {'clicks': int(clicks), 'impressions': int(shown)}
