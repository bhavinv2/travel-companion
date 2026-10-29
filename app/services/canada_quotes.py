"""Canada cover -- super visa and visitors to Canada -- priced from Secure Travel's own calculators.

Secure Travel (secure-travel.ca) sells RIMI's "Visitors to Canada" plan. Each of its two pages carries a
"Calculated Fields Form": the whole calculator, rate table included, sits in the page as JSON (the
form_structure_1 variable), and the browser does the arithmetic. Nothing is priced on a server there, so
nothing here asks one either:

    price for one traveller = rate per day x days x deductible factor
      rate per day   one entry of a table keyed age band + pre-existing (y/n) + plan (s/e) + policy limit
      days           365 on the super visa page (a fixed field); the trip's days on the visitors page
      factor         1 for a $0 deductible, less for a bigger one (the bands 80+ get fewer discounts)

NOTHING OF THEIRS IS KEPT. The rates are read from their live pages every time they are needed, and a
read is reused for READ_SECONDS only, so their site is not asked on every click. Each fresh read is
compared with the one before it (by fingerprint: AppSetting CHECK_KEY holds the fingerprints and times,
never a rate), and the two pages are compared with each other -- they are meant to share one table, and
one price differed between them when this was written. The quotes page and the admin page both say what
the last check found.

When their page cannot be read, a read up to STALE_SECONDS old is still used and says so; with nothing to
use, Unavailable is raised and the quotes page falls back to "our agent will call you with prices".

The parser reads the calculator's own structure (field titles, the price code's order, the plan field's
show/hide rules) rather than assuming it, so a changed limit, band or deductible list comes through as
long as the calculator keeps its shape. When the shape itself changes, parse() raises Unavailable and
the admin page says the page could not be understood.
"""
import hashlib
import html as _html
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

log = logging.getLogger(__name__)

PRODUCTS = {
    'super_visa': {'label': 'Super visa', 'url': 'https://www.secure-travel.ca/super-visa-insurance/'},
    'visitors': {'label': 'Visitors to Canada', 'url': 'https://www.secure-travel.ca/visitors-insurance/'},
}
# Where staff buy the policy for somebody who asked for a call back, with our own tracking code so the
# sale is credited to us. The customer is never sent here: step 2 is a call from our team.
CHECKOUT_URL = 'https://rimi-forms.policy-dashboard.com/en/rimivisitorstocanada'
TRACKING_CODE = '30NJMC'

READ_SECONDS = 15 * 60          # a read is reused this long: their site is not asked on every page view
STALE_SECONDS = 6 * 3600        # their site is down: a read this old is still shown, marked as such
TIMEOUT = 15
CHECK_KEY = 'canada_quotes.rate_check'
MAX_DAYS = 365                  # a visitor policy is one year at most; longer is a conversation
MAX_TRAVELLERS = 8


def to_fixed2(x):
    """What their calculator's `total.toFixed(2)` gives: the exact value of the float, halves rounded up.

    Not round(): 5.05 x 365 x 0.7 is 1290.2749999... as a float, which toFixed calls 1290.27, and a nudge
    towards the half would have said 1290.28 -- a cent away from the price on their own page."""
    return float(Decimal(x).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


class Unavailable(Exception):
    """Their page could not be read or understood, and there is no recent read to fall back on."""


@dataclass
class Band:
    code: str
    label: str
    lo: int
    hi: int


@dataclass
class Table:
    """One page's calculator, as read. Rates only live as long as the read does."""
    product: str
    url: str
    bands: list
    plans: list                   # [(code, label)]
    limits: dict                  # plan code -> [(code, label, amount)]
    deductibles: list             # [(value, label)]
    rates: dict                   # price code -> rate per day
    discounts: list               # [(band codes, plan codes, {deductible: factor}, default factor)]
    order: list                   # the price code's parts in order: 'age', 'pre', 'plan', ('limit', plan)
    fixed_days: int = None
    monthly: dict = field(default_factory=dict)
    benefits: list = field(default_factory=list)   # [(benefit, standard, enhanced)]
    fingerprint: str = ''

    def band(self, age):
        for b in self.bands:
            if b.lo <= age <= b.hi:
                return b
        return None

    def plan_label(self, code):
        return dict(self.plans).get(code, code)

    def limit_label(self, plan, code):
        return next((lab for c, lab, _ in self.limits.get(plan, ()) if c == code), code)

    def factor(self, band_code, plan, deductible):
        """The deductible's factor, or None where their calculator has no rule (it would show $0)."""
        for bands, plans, by_ded, default in self.discounts:
            if band_code in bands and plan in plans:
                return by_ded.get(deductible, default)
        return None

    def code(self, band_code, pre, plan, limit):
        parts = []
        for part in self.order:
            if part == 'age':
                parts.append(band_code)
            elif part == 'pre':
                parts.append(pre)
            elif part == 'plan':
                parts.append(plan)
            else:
                # the limit box of the other plan is hidden, and a hidden box counts as 0 there
                parts.append(limit if part[1] == plan else '0')
        return ''.join(parts)

    def price(self, age, pre, plan, limit, deductible, days):
        """One traveller's price, or None when this page offers no price for them."""
        band = self.band(age)
        if band is None:
            return None
        rate = self.rates.get(self.code(band.code, pre, plan, limit))
        factor = self.factor(band.code, plan, deductible)
        if rate is None or not factor:
            return None
        return to_fixed2(rate * days * factor)

    def monthly_ok(self, days, limit):
        """Their monthly option: the super visa page always; the visitors page only for a year at $100k+."""
        if not self.monthly:
            return False
        if self.monthly.get('min_days') and days != self.monthly['min_days']:
            return False
        if self.monthly.get('min_limit') and int(limit) < self.monthly['min_limit']:
            return False
        return True


# ---------------------------------------------------------------------------------------------- parsing

def _json_after(text, marker_re):
    """The JSON value that follows the first match of `marker_re` (bracket matched, strings respected)."""
    m = re.search(marker_re, text)
    if not m:
        raise Unavailable('the calculator is not on the page')
    start = m.end()
    depth, i, in_str, esc = 0, start, False, False
    while i < len(text):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == '\\':
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c in '[{':
            depth += 1
        elif c in ']}':
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
        i += 1
    raise Unavailable('the calculator could not be read')


def _money(label):
    digits = re.sub(r'[^\d]', '', label or '')
    return int(digits) if digits else 0


def _find(fields, ftype, pattern):
    rx = re.compile(pattern, re.I)
    return [f for f in fields if f.get('ftype') == ftype and rx.search(f.get('title') or '')]


def _benefits(page):
    """The Standard / Enhanced benefits table, where the page has one."""
    for tbl in re.findall(r'<table.*?</table>', page, re.S | re.I):
        if 'Standard Plan' not in tbl or 'Enhanced Plan' not in tbl:
            continue
        rows = []
        for tr in re.findall(r'<tr.*?</tr>', tbl, re.S | re.I):
            cells = [re.sub(r'\s+', ' ', _html.unescape(re.sub(r'<[^>]+>', ' ', c))).strip()
                     for c in re.findall(r'<t[hd][^>]*>(.*?)</t[hd]>', tr, re.S | re.I)]
            if len(cells) >= 3 and cells[0] and 'Plan' not in cells[1]:
                rows.append((cells[0], cells[1], cells[2]))
        if rows:
            return rows
    return []


def parse(page, product, url=''):
    """A Table from one of their pages. Raises Unavailable when the calculator is missing or changed shape."""
    data = _json_after(page, r'form_structure_\d+\s*=\s*')
    fields = data[0] if isinstance(data, list) and data else []
    try:
        age_f = _find(fields, 'fdropdown', r'^\s*age')[0]
        pre_f = (_find(fields, 'fradio', r'pre-?existing') or _find(fields, 'fdropdown', r'pre-?existing'))[0]
        plan_f = _find(fields, 'fdropdown', r'^\s*plan\s*$')[0]
        ded_f = _find(fields, 'fdropdown', r'deductible')[0]
        limit_fs = _find(fields, 'fdropdown', r'policy limit')
        days_f = _find(fields, 'fnumber', r'days')[0]
        calcs = [f for f in fields if f.get('ftype') == 'fCalculated']
        price_f = next(f for f in calcs if 'priceCode' in (f.get('eq') or ''))
    except (IndexError, StopIteration):
        raise Unavailable('the calculator changed shape')
    eq = price_f['eq']
    monthly_f = next((f for f in calcs if f is not price_f and 'monthly' in (f.get('title') or '').lower()), None)

    bands = []
    for label, code in zip(age_f.get('choices') or [], age_f.get('choicesVal') or []):
        m = re.search(r'(\d+)\s*(?:to|-|–)\s*(\d+)', label)
        if m:
            bands.append(Band(str(code), label, int(m.group(1)), int(m.group(2))))
    plans = list(zip([str(v) for v in plan_f.get('choicesVal') or []], plan_f.get('choices') or []))
    # which limit box each plan shows: the plan field's own show/hide rules
    shown = {}
    for (code, _), dep in zip(plans, plan_f.get('choicesDep') or []):
        for name in dep or []:
            shown[name] = code
    limits, limit_field = {}, {}
    for f in limit_fs:
        plan = shown.get(f['name'])
        if plan is None:
            continue
        limit_field[f['name']] = plan
        limits[plan] = [(str(v), lab, _money(lab)) for lab, v in zip(f.get('choices') or [], f.get('choicesVal') or [])]
    deductibles = [(int(v), lab) for lab, v in zip(ded_f.get('choices') or [], ded_f.get('choicesVal') or [])
                   if str(v).isdigit()]
    fixed_days = int(days_f['predefined']) if days_f.get('readonly') and str(days_f.get('predefined', '')).isdigit() else None

    m = re.search(r'priceCode\s*=\s*([\w\s+]+);', eq)
    if not m or not bands or not plans or not limits or not deductibles:
        raise Unavailable('the calculator changed shape')
    roles = {age_f['name']: 'age', pre_f['name']: 'pre', plan_f['name']: 'plan'}
    order = []
    for name in [p.strip() for p in m.group(1).split('+') if p.strip()]:
        if name in roles:
            order.append(roles[name])
        elif name in limit_field:
            order.append(('limit', limit_field[name]))
        else:
            raise Unavailable('the price code uses a box this reader does not know')
    rates = {c: float(v) for c, v in re.findall(r'priceCode\s*==\s*"(\w+)"\s*\)\s*\{\s*perDay\s*=\s*([\d.]+)\s*;', eq)}
    if not rates:
        raise Unavailable('no rates on the page')

    # the deductible rules: `if ([bands].indexOf(age) > -1 && [plans].indexOf(plan) > -1) { if (ded == 0) ...`
    cond = re.compile(r'\[([^\]]*)\]\.indexOf\((\w+)\)\s*>\s*-1\s*&&\s*(?:\[([^\]]*)\]\.indexOf\((\w+)\)\s*>\s*-1'
                      r'|(\w+)\s*==\s*"(\w+)")')
    tail = eq[eq.find('subTotal'):] if 'subTotal' in eq else eq
    hits = list(cond.finditer(tail))
    discounts = []
    for i, h in enumerate(hits):
        if h.group(2) != age_f['name']:
            continue
        seg = tail[h.end(): hits[i + 1].start() if i + 1 < len(hits) else len(tail)]
        seg = seg.split('var total')[0]
        bands_in = frozenset(re.findall(r'"(\w+)"', h.group(1)))
        plans_in = frozenset(re.findall(r'"(\w+)"', h.group(3))) if h.group(3) is not None else frozenset([h.group(6)])
        by_ded = {int(d): float(x) for d, x in
                  re.findall(r'==\s*(\d+)\s*\)\s*\{\s*discount\s*=\s*([\d.]+)\s*;', seg)}
        dm = re.search(r'else\s*\{\s*discount\s*=\s*([\d.]+)\s*;', seg)
        discounts.append((bands_in, plans_in, by_ded, float(dm.group(1)) if dm else 1.0))
    if not discounts:
        raise Unavailable('the deductible rules could not be read')

    monthly = {}
    if monthly_f is not None:
        meq = monthly_f.get('eq') or ''
        fee = re.search(r'\$\s*([\d,]+)', monthly_f.get('userhelp') or '')
        div = re.search(r'/\s*(\d+)\s*\)', meq)
        monthly = {'months': int(div.group(1)) if div else 12, 'fee': _money(fee.group(1)) if fee else 0}
        md = re.search(r'%s\s*==\s*(\d+)' % re.escape(days_f['name']), meq)
        ml = re.search(r'(?:%s)\s*>=\s*(\d+)' % '|'.join(map(re.escape, limit_field)), meq) if limit_field else None
        if md:
            monthly['min_days'] = int(md.group(1))
        if ml:
            monthly['min_limit'] = int(ml.group(1))

    t = Table(product=product, url=url, bands=bands, plans=plans, limits=limits, deductibles=deductibles,
              rates=rates, discounts=discounts, order=order, fixed_days=fixed_days, monthly=monthly,
              benefits=_benefits(page))
    t.fingerprint = hashlib.sha256(json.dumps({
        'bands': [(b.code, b.lo, b.hi) for b in bands], 'plans': plans, 'limits': limits,
        'deductibles': deductibles, 'rates': sorted(rates.items()), 'order': [str(o) for o in order],
        'discounts': [(sorted(b), sorted(p), sorted(d.items()), x) for b, p, d, x in discounts],
        'days': fixed_days, 'monthly': sorted(monthly.items()),
    }, sort_keys=True, default=str).encode()).hexdigest()[:16]
    return t


# ---------------------------------------------------------------------------------------------- reading

_reads = {}            # product -> (monotonic time, utc time, Table, same as the read before it)
_lock = threading.Lock()


def forget():
    """Drop every read (tests; the admin's "Check now")."""
    with _lock:
        _reads.clear()


def fetch(product):
    """Their page, now. Separate so tests can stand in for the network."""
    req = urllib.request.Request(PRODUCTS[product]['url'], headers={
        'User-Agent': 'Mozilla/5.0 (compatible; NRIParentService/1.0; +https://nriparentservice.com)',
        'Accept': 'text/html'})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read().decode('utf-8', 'ignore')


def _record(product, table, previous):
    """Note this read against the last one: same, or changed (and when). Never stores a rate."""
    from app.services import settings
    now = datetime.utcnow()
    state = dict(settings.get_setting(CHECK_KEY) or {})
    mine = dict(state.get(product) or {})
    same = None
    if mine.get('fingerprint'):
        same = mine['fingerprint'] == table.fingerprint
    if same is False:
        mine['changed_at'] = now.isoformat()
        mine['previous'] = mine.get('fingerprint')
        mine['codes_changed'] = (sum(1 for c, r in table.rates.items() if previous.rates.get(c) != r)
                                 + sum(1 for c in previous.rates if c not in table.rates)) if previous else None
    mine.setdefault('first_seen', now.isoformat())
    mine.update({'fingerprint': table.fingerprint, 'checked_at': now.isoformat(), 'same': same,
                 'rates': len(table.rates), 'error': None})
    state[product] = mine
    try:
        settings.set_setting(CHECK_KEY, state)
    except Exception:          # noqa: BLE001 -- a check we cannot note must never cost a customer their quote
        from app import db
        db.session.rollback()
        log.warning('Could not note the Canada rate check', exc_info=True)
    if same is False:
        _tell_admins(product, mine)
    return same


def _note_failure(product, why):
    from app.services import settings
    try:
        state = dict(settings.get_setting(CHECK_KEY) or {})
        mine = dict(state.get(product) or {})
        mine.update({'error': str(why)[:200], 'failed_at': datetime.utcnow().isoformat()})
        state[product] = mine
        settings.set_setting(CHECK_KEY, state)
    except Exception:          # noqa: BLE001
        from app import db
        db.session.rollback()


def _tell_admins(product, mine):
    """A bell for the admins when Secure Travel's prices change. Best effort."""
    from app import db
    from app.models import User
    from app.services import notify
    try:
        n = mine.get('codes_changed')
        body = ('%d prices on their %s page are different from the last check.' % (n, PRODUCTS[product]['label'])
                if n else 'Their %s page is different from the last check.' % PRODUCTS[product]['label'])
        try:
            from flask import url_for
            link = url_for('admin.canada_quotes_admin')
        except Exception:          # noqa: BLE001 -- outside a request
            link = '/admin/insurance/canada-quotes'
        for u in User.query.filter(User.is_admin.is_(True), User.is_active.is_(True)).all():
            notify.push(u.id, 'canada_rates', title='Secure Travel changed their prices', body=body, link=link)
        db.session.commit()
    except Exception:          # noqa: BLE001
        db.session.rollback()
        log.warning('Could not tell the admins about a Canada rate change', exc_info=True)


def live(product, force=False):
    """(Table, check) for `product`: a read at most READ_SECONDS old, else a fresh one.

    `check` = {'checked_at': utc datetime of the read, 'fresh': read now, 'same': True/False/None against
    the read before it, 'stale': their page failed and an older read is standing in}."""
    if product not in PRODUCTS:
        raise KeyError(product)
    now = time.monotonic()
    with _lock:
        hit = _reads.get(product)
        if hit and not force and now - hit[0] < READ_SECONDS:
            return hit[2], {'checked_at': hit[1], 'fresh': False, 'same': hit[3], 'stale': False}
    try:
        table = parse(fetch(product), product, PRODUCTS[product]['url'])
    except (urllib.error.URLError, OSError, ValueError, Unavailable) as e:
        log.warning('Secure Travel %s page could not be read: %s', product, e)
        _note_failure(product, e)
        if hit and now - hit[0] < STALE_SECONDS:
            return hit[2], {'checked_at': hit[1], 'fresh': False, 'same': hit[3], 'stale': True}
        raise Unavailable(str(e)) from e
    previous = hit[2] if hit else None
    same = _record(product, table, previous)
    at = datetime.utcnow()
    with _lock:
        _reads[product] = (time.monotonic(), at, table, same)
    return table, {'checked_at': at, 'fresh': True, 'same': same, 'stale': False}


def state():
    """What the checks have found so far, per product (AppSetting CHECK_KEY): for the admin page."""
    from app.services import settings
    return dict(settings.get_setting(CHECK_KEY) or {})


def compare_pages(sv, vi):
    """Prices the two pages disagree on, for the options the super visa page offers."""
    out = []
    offered = {p: {c for c, _, _ in ls} for p, ls in sv.limits.items()}
    for code, rate in sorted(sv.rates.items()):
        other = vi.rates.get(code)
        if other is None or other == rate:
            continue
        what = _describe(sv, code)
        if what and what['limit'] in offered.get(what['plan'], ()):
            out.append({**what, 'super_visa': rate, 'visitors': other})
    return out


def _describe(t, code):
    """A price code back into words, for the admin page."""
    for b in t.bands:
        for pre in ('n', 'y'):
            for plan, _ in t.plans:
                for lim, lab, _ in t.limits.get(plan, ()):
                    if t.code(b.code, pre, plan, lim) == code:
                        return {'plan': plan, 'limit': lim,
                                'text': '%s · %s · %s · %s' % (b.label, 'pre-existing' if pre == 'y' else 'no pre-existing',
                                                              t.plan_label(plan), lab)}
    return None


# ---------------------------------------------------------------------------------------------- quoting

def cover_days(product, start, end, table=None):
    """Days of cover: a super visa is always the page's fixed year; a visit counts both its first and last day."""
    if product == 'super_visa':
        return (table.fixed_days if table and table.fixed_days else 365)
    return (end - start).days + 1


def book(product, travellers, days):
    """Every price the page offers these travellers, as the quotes page reads it (JSON-able).

    travellers: [{'age': 66, 'pre': 'n'}, ...]. Each person is priced for BOTH answers to the
    pre-existing question, so the page can change one person's answer without asking the server."""
    table, check = live(product)
    people = []
    for t in travellers:
        age = int(t['age'])
        band = table.band(age)
        prices = {}
        for pre in ('n', 'y'):
            prices[pre] = {plan: {lim: {str(ded): table.price(age, pre, plan, lim, ded, days)
                                        for ded, _ in table.deductibles}
                                  for lim, _, _ in table.limits.get(plan, ())}
                           for plan, _ in table.plans}
        people.append({'age': age, 'pre': t.get('pre') or 'n', 'band': band.label if band else None,
                       'prices': prices})
    return {
        'product': product, 'label': PRODUCTS[product]['label'], 'days': days,
        'plans': [{'code': c, 'label': lab} for c, lab in table.plans],
        'limits': {p: [{'code': c, 'label': lab, 'amount': amt} for c, lab, amt in ls] for p, ls in table.limits.items()},
        'deductibles': [{'value': v, 'label': lab} for v, lab in table.deductibles],
        'monthly': ({'months': table.monthly.get('months', 12), 'fee': table.monthly.get('fee', 0),
                     'limits': [c for p in table.limits for c, _, _ in table.limits[p] if table.monthly_ok(days, c)]}
                    if table.monthly else None),
        'people': people,
        'benefits': table.benefits,
        'checked_at': check['checked_at'].isoformat() + 'Z', 'stale': check['stale'], 'same': check['same'],
        'fingerprint': table.fingerprint,
    }


def price_pick(product, travellers, days, plan, limit, deductible):
    """One option for these travellers, priced now: (total, [per person], fingerprint) or None if not offered."""
    table, _ = live(product)
    each = [table.price(int(t['age']), t.get('pre') or 'n', plan, str(limit), int(deductible), days)
            for t in travellers]
    if any(p is None for p in each):
        return None
    return round(sum(each), 2), each, table


def money(x):
    return '${:,.2f}'.format(x) if x is not None else '—'


def checkout_url():
    """Their checkout with our tracking code: for staff completing a purchase after the call."""
    return '%s?&sales_channel=online&tracking_code=%s' % (CHECKOUT_URL, TRACKING_CODE)
