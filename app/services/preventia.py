"""The Preventia360 External API (v1): the Sahayak catalogue, its pricing, and its gig forms.

Read-only, and deliberately so at their end -- "bookings themselves still go through the regular
app/backoffice flow". So this fetches what a visitor is shown and what it costs; the booking they
make is still stored by us, in sahayak_bookings, and worked in the CS console. Nothing here
writes to Preventia.

Three things the page needs, in the order it needs them:

    service-categories  the catalogue, with each category's pricing embedded
    pricing             one category's rule again, for a zone-specific refresh
    gig-forms           the PRE/DURING/POST field schema, if we ever render their forms

Operational shape:

  * The key is an environment variable and never leaves the server. The bundle asks Flask, Flask
    asks Preventia -- putting the key in window.__SAHAYAK__ would publish it to every visitor.
  * Everything is cached for CACHE_SECONDS. Their own responses sit behind a 5-minute cache, so
    asking more often than that buys nothing and makes our page wait on their network.
  * Every call degrades to None rather than raising. A catalogue that cannot be fetched must not
    take down a page whose job is letting somebody arrange care for a parent -- the caller falls
    back to the catalogue in services/sahayak.
  * A bare 403 with no JSON body means the credential was not accepted; a 403 WITH a body is a
    business rejection like ROLE_OUT_OF_SCOPE. The two need different people to fix them, so
    they are logged differently.
"""
import logging
import os
import time

import requests

log = logging.getLogger(__name__)

ROLE = 'SAHAYAK'
CACHE_SECONDS = 300          # their side caches for five minutes; asking faster buys nothing
TIMEOUT = (3.05, 8)          # (connect, read) -- a page render is waiting on this

_cache = {}


def base_url():
    """e.g. https://api.preventia360.com/api/v1 -- the backend context path is part of it."""
    return (os.environ.get('PREVENTIA_API_URL') or '').strip().rstrip('/')


def api_key():
    return (os.environ.get('PREVENTIA_API_KEY') or '').strip()


def enabled():
    """Both halves set. Unset on a developer's machine and in the tests, which is what keeps
    the suite from reaching the network."""
    return bool(base_url() and api_key())


def _get(path, params=None):
    """One GET, cached, unwrapped from the success envelope. None on any failure.

    Never raises: see the module docstring. The key is sent as a header and is not included in
    the cache key beyond its own identity -- nothing here is logged with it in.
    """
    if not enabled():
        return None
    key = (path, tuple(sorted((params or {}).items())))
    hit = _cache.get(key)
    now = time.monotonic()
    if hit and hit[0] > now:
        return hit[1]

    url = '%s/external/v1/%s' % (base_url(), path.lstrip('/'))
    try:
        r = requests.get(url, params=params, timeout=TIMEOUT,
                         headers={'X-API-Key': api_key(), 'Accept': 'application/json'})
    except requests.RequestException as exc:
        log.warning('preventia %s unreachable: %s', path, exc)
        return None

    if r.status_code == 403 and not (r.text or '').strip():
        # rejected at their security filter, before any controller ran
        log.error('preventia %s: the API key was not accepted (403, empty body)', path)
        return None
    try:
        body = r.json()
    except ValueError:
        log.error('preventia %s: %s with a non-JSON body', path, r.status_code)
        return None
    if not body.get('success'):
        log.error('preventia %s: %s %s', path, body.get('errorCode'), body.get('message'))
        return None

    data = body.get('data')
    _cache[key] = (now + CACHE_SECONDS, data)
    return data


def clear_cache():
    _cache.clear()


def roles():
    """Every provider role this key may query. [] when the API is off or unreachable."""
    return _get('roles') or []


def service_categories(role=ROLE):
    """The catalogue, each category carrying its own pricing. None when unavailable.

    None rather than [], because the two mean different things to a caller: an empty catalogue
    is an answer ("they have published nothing"), and None is "we could not ask".
    """
    return _get('service-categories', {'role': role})


def pricing(service_category_id, role=ROLE, zone=None):
    """One category's pricing rule, optionally for a zone. None when unavailable."""
    params = {'role': role, 'serviceCategoryId': service_category_id}
    if zone:
        params['zone'] = zone
    return _get('pricing', params)


# A visit runs in this order. The API gives each section a stage rather than a position, and
# sortOrder only orders within one, so the stages have to be put in sequence here.
STAGE_ORDER = {'PRE': 0, 'PRE_DURING': 1, 'DURING': 2, 'POST_DURING': 3, 'POST': 4}


def journey(service_category_id, role=ROLE):
    """What the visit covers, step by step, as Preventia defines it for that category.

    The same list the GIG sheet draws by hand, read from the source instead: each section is
    one step, `required` is the sheet's MAD/OPT, and the booking step is dropped because it is
    the form the family has already filled in by the time they are reading this.

    None when the API could not be asked -- the caller keeps whatever it was showing.

    Costs a request per category and the responses are large (a hundred and fifty fields for a
    wellness screen), so this is never called while a page is being rendered: nine of them cold
    is eleven seconds. It answers one service at a time, when somebody asks to see it.
    """
    data = gig_forms(service_category_id, role=role)
    if not data:
        return None
    out = []
    for s in data.get('sections') or []:
        code = s.get('gigTypeCode') or ''
        if code == 'BOOKING':
            continue
        out.append({
            'key': code,
            'title': s.get('gigTypeName') or code.replace('_', ' ').title(),
            'text': s.get('displaySection') or '',
            'optional': not s.get('required'),
            'stage': s.get('stage') or '',
        })
    out.sort(key=lambda x: (STAGE_ORDER.get(x['stage'], 9), x['title']))
    return out


def gig_forms(service_category_id, role=ROLE, stage=None, locale='en'):
    """The dynamic PRE/DURING/POST field schema for a category.

    Not rendered on the public page today -- those are the forms the Sahayak fills in during a
    visit, not the ones a family fills in to ask for one. Here because the catalogue and the
    pricing come from the same place and splitting the client would be worse.
    """
    params = {'role': role, 'serviceCategoryId': service_category_id, 'locale': locale}
    if stage:
        params['stage'] = stage
    return _get('gig-forms', params)


# ---------------------------------------------------------------------------
# What a visit costs
# ---------------------------------------------------------------------------

WORKING_DAYS_PER_MONTH = 30      # the guide's definition of a working month


def quote(rule, usage):
    """The provider subtotal ("fair") for `usage` minutes (or km, for a distance gig).

    Straight from the guide:

        billable = max(0, min(usage - freeTier, billingCap))
        fair     = baseFare + (billable, tiered) + submissionFee

    DYNAMIC peels off whole working months and whole working days first, at perMonthRate and
    perDayRate, and bills the remainder hourly. STANDARD is flatter: everything past the free
    tier at a single overageRate.

    Returns None when there is no configured rule -- a page must then say nothing rather than
    print a zero, because "free" and "we have not set a price yet" are not the same claim. The
    patient's total is NOT this: a platform fee and GST are added at checkout, in a currency
    this API does not decide, so callers must not present this as the final price.
    """
    if not rule or not rule.get('configured'):
        return None

    def num(key, default=0.0):
        v = rule.get(key)
        return float(v) if v is not None else float(default)

    usage = max(0.0, float(usage or 0))
    free = num('freeTier')
    cap = rule.get('billingCap')
    billable = max(0.0, usage - free)
    if cap is not None:
        billable = min(billable, float(cap))

    if (rule.get('pricingType') or '').upper() == 'STANDARD':
        variable = billable * num('overageRate')
    else:
        per_day_minutes = num('workingHoursPerDay', 9) * 60
        variable = 0.0
        left = billable
        per_month = rule.get('perMonthRate')
        if per_month and per_day_minutes > 0:
            month = per_day_minutes * WORKING_DAYS_PER_MONTH
            whole, left = divmod(left, month)
            variable += whole * float(per_month)
        per_day = rule.get('perDayRate')
        if per_day and per_day_minutes > 0:
            whole, left = divmod(left, per_day_minutes)
            variable += whole * float(per_day)
        variable += (left / 60.0) * num('hourlyRate')

    fair = (num('baseFare') + variable) * num('surchargeMultiplier', 1) + num('submissionFee')
    return round(fair, 2)


def as_catalogue(categories):
    """Their service-categories response in the shape services/sahayak uses.

    `price` is the base fare, as a string, because that is what the page prints beside a service
    and what a booking records; '' where no rule is configured, so the page prints nothing
    rather than a made-up number.
    """
    out = []
    for c in categories or []:
        rule = c.get('pricing') or {}
        base = rule.get('baseFare') if rule.get('configured') else None
        out.append({
            'key': (c.get('code') or '').lower()[:40],
            'name': (c.get('name') or c.get('code') or '')[:80],
            'blurb': (c.get('description') or '')[:240],
            'price': ('%g' % float(base)) if base is not None else '',
            'duration': '',
            'icon': 'fa-user-nurse',
            # their code, unchanged -- `key` is lowercased and truncated for our own use, so it
            # is no good for matching anything back to their catalogue
            'code': c.get('code') or '',
            # kept so a booking can be tied back to their catalogue, and so a zone-specific
            # pricing refresh has something to ask about
            'remote_id': c.get('id'),
            'pricing': rule or None,
        })
    return out
