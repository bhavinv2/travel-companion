"""The marketing data engine (2026-10-29): every number a Promotion dashboard box can show, from every place we keep
one -- the website (Google Analytics), trips, flights, insurance quotes, Sahayak bookings, enquiries, reviews,
sign-ups, blog posts and (staff only) leads -- in one catalogue that any box can combine.

A BOX asks for:
    metrics   one or more (source, measure, filters, date field): "trips", "Travellers", only India -> abroad, by
              travel date. Several metrics side by side make several lines or bars (sign-ups AND enquiries a month)
    group     what to split the numbers by: a time grain (day, week, month, quarter, year) or one of the source's
              dimensions (direction, destination country, channel ...); empty = one total
    split     a second dimension, one series per value (trips a month by direction)
    range     the dates: the dashboard's own (the page's date picker) or a fixed one (last 7 days, this year ...)
    chart     how it is drawn (CHARTS); top = how many groups are kept, the rest summed as "Everything else"

    catalogue()                  everything a designer can choose, for the designer's script
    clean_box(raw)               a box with every choice checked against the catalogue (EngineError otherwise)
    run(box, period, viewer)     the numbers: labels, series, total, the previous period's total and the change
    period_for(key, from, to)    a Period (dates in India time, both ends included) and its .previous()
    options(source, dim)         the values a filter can pick, most common first

SAFETY, the rule services/promo.py was written for and every source here keeps: aggregates only. A dimension is a
place, a product, a month, a status -- never a name, an e-mail, a phone number or an address -- and every number is
a count, a sum or an average of a group. Nothing a person types reaches a query: sources, measures, dimensions,
dates and charts are keys of the fixed lists below and filter values are compared in Python with the labels the
dimensions produce. Lead numbers are company-wide counts (no money), shown to staff only (`staff_only`).
"""
from collections import OrderedDict, defaultdict
from datetime import date, datetime, timedelta

from app import db

IST = timedelta(hours=5, minutes=30)
ROW_LIMIT = 200000
MAX_METRICS = 6
MAX_SPLITS = 8
MAX_TOP = 50
TEXT_MAX = 2000
EVER = date(2020, 1, 1)
OTHERS = 'Everything else'
NOT_KNOWN = 'Not known'


class EngineError(ValueError):
    """A choice the engine does not offer, phrased for the person."""


# ================================================================================================ dates

def today():
    return (datetime.utcnow() + IST).date()


RANGES = OrderedDict([
    ('page', "The dashboard's dates"), ('today', 'Today'), ('yesterday', 'Yesterday'), ('last_7', 'Last 7 days'),
    ('last_30', 'Last 30 days'), ('last_90', 'Last 90 days'), ('last_365', 'Last 12 months'),
    ('this_month', 'This month'), ('last_month', 'Last month'), ('this_year', 'This year'),
    ('last_year', 'Last year'), ('all', 'All time'),
    # ahead of today: for travel dates ("who flies in the next three months")
    ('next_30', 'Next 30 days'), ('next_90', 'Next 90 days'), ('next_365', 'Next 12 months')])
PAGE_RANGES = OrderedDict((k, v) for k, v in RANGES.items() if k != 'page' and not k.startswith('next_'))
PAGE_RANGES['custom'] = 'Choose dates'
BOX_RANGES = tuple(RANGES)


class Period:
    """[start, end], both included, India dates."""

    def __init__(self, start, end, key='custom'):
        if end < start:
            start, end = end, start
        self.start, self.end, self.key = start, end, key

    @property
    def days(self):
        return (self.end - self.start).days + 1

    def previous(self):
        """The same number of days just before -- what "change" is measured against."""
        end = self.start - timedelta(days=1)
        return Period(end - timedelta(days=self.days - 1), end, 'previous')

    @property
    def label(self):
        if self.key in RANGES and self.key not in ('page', 'custom'):
            return RANGES[self.key]
        return day_range(self.start, self.end)

    @property
    def dates(self):
        return day_range(self.start, self.end)

    def utc(self):
        """The UTC datetimes that hold these India days: [start, end)."""
        return (datetime.combine(self.start, datetime.min.time()) - IST,
                datetime.combine(self.end + timedelta(days=1), datetime.min.time()) - IST)

    def as_dict(self):
        return {'key': self.key, 'from': self.start.isoformat(), 'to': self.end.isoformat(), 'label': self.label,
                'dates': self.dates, 'days': self.days}


def day_range(a, b):
    if a == b:
        return a.strftime('%d %b %Y').lstrip('0')
    if a.year == b.year:
        return '%s – %s' % (a.strftime('%d %b').lstrip('0'), b.strftime('%d %b %Y').lstrip('0'))
    return '%s – %s' % (a.strftime('%d %b %Y').lstrip('0'), b.strftime('%d %b %Y').lstrip('0'))


def _parse_day(v):
    try:
        return datetime.strptime(str(v or '').strip(), '%Y-%m-%d').date()
    except ValueError:
        return None


def period_for(key, start=None, end=None):
    """The dates a range key stands for. 'custom' takes `start` / `end` (YYYY-MM-DD, or dates)."""
    t = today()
    key = key if (key in PAGE_RANGES or key in RANGES) and key != 'page' else 'last_30'
    if key.startswith('next_'):
        return Period(t, t + timedelta(days=int(key[5:]) - 1), key)
    if key == 'today':
        return Period(t, t, key)
    if key == 'yesterday':
        y = t - timedelta(days=1)
        return Period(y, y, key)
    if key.startswith('last_') and key[5:].isdigit():
        n = int(key[5:])
        return Period(t - timedelta(days=n - 1), t, key)
    if key == 'this_month':
        return Period(t.replace(day=1), t, key)
    if key == 'last_month':
        end_ = t.replace(day=1) - timedelta(days=1)
        return Period(end_.replace(day=1), end_, key)
    if key == 'this_year':
        return Period(date(t.year, 1, 1), t, key)
    if key == 'last_year':
        return Period(date(t.year - 1, 1, 1), date(t.year - 1, 12, 31), key)
    if key == 'all':
        return Period(EVER, t, key)
    a = start if isinstance(start, date) else _parse_day(start)
    b = end if isinstance(end, date) else _parse_day(end)
    if a is None and b is None:
        return period_for('last_30')
    a, b = a or (b - timedelta(days=29)), b or t
    a, b = max(EVER, min(a, t)), max(EVER, min(b, t))
    return Period(a, b, 'custom')


# ------------------------------------------------------------------------------------------------ time grains

GRAINS = OrderedDict([('auto', 'Time (days, weeks or months, to fit the dates)'), ('day', 'Day'), ('week', 'Week'),
                      ('month', 'Month'), ('quarter', 'Quarter'), ('year', 'Year')])
MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')
MAX_POINTS = 400


def auto_grain(period):
    """What "time" means for these dates: a month of days, a quarter of weeks, a year of months."""
    if period.days <= 62:
        return 'day'
    if period.days <= 190:
        return 'week'
    if period.days <= 365 * 4:
        return 'month'
    return 'year'


def bucket(d, grain):
    if grain == 'day':
        return d
    if grain == 'week':
        return d - timedelta(days=d.weekday())
    if grain == 'month':
        return (d.year, d.month)
    if grain == 'quarter':
        return (d.year, (d.month - 1) // 3 + 1)
    return d.year


def bucket_label(k, grain):
    if grain == 'day':
        return '%d %s' % (k.day, MONTHS[k.month - 1])
    if grain == 'week':
        return 'Week of %d %s' % (k.day, MONTHS[k.month - 1])
    if grain == 'month':
        return '%s %d' % (MONTHS[k[1] - 1], k[0])
    if grain == 'quarter':
        return 'Q%d %d' % (k[1], k[0])
    return str(k)


def buckets(period, grain):
    """Every bucket the period touches, in order, so a line has its zeros too."""
    out = []
    if grain in ('day', 'week'):
        d, step = bucket(period.start, grain), timedelta(days=1 if grain == 'day' else 7)
        while d <= period.end:
            out.append(d)
            d += step
        return out
    if grain == 'year':
        return list(range(period.start.year, period.end.year + 1))
    k, last = bucket(period.start, grain), bucket(period.end, grain)
    per_year = 12 if grain == 'month' else 4
    while k <= last:
        out.append(k)
        k = (k[0] + 1, 1) if k[1] == per_year else (k[0], k[1] + 1)
    return out


def fit_grain(period, grain):
    """A grain the period can draw: a year of days is fine, ten years of days is not."""
    if grain == 'auto':
        return auto_grain(period)
    order = [g for g in GRAINS if g != 'auto']
    i = order.index(grain)
    while i < len(order) - 1 and len(buckets(period, order[i])) > MAX_POINTS:
        i += 1
    return order[i]


# ================================================================================================ the sources

def _first(*vals):
    for v in vals:
        if v not in (None, ''):
            return v
    return None


def _yes(v, yes='Yes', no='No'):
    return (0, yes) if v else (1, no)


def _cat(label, order=0):
    label = str(label).strip() if label not in (None, '') else ''
    return (order, label) if label else (10 ** 6, NOT_KNOWN)


def _band(n, edges, unit=''):
    """(sort, label) of the band a number falls in: edges [7, 15, 30] -> 'Up to 7', '8–15', '16–30', 'More than 30'."""
    if n is None:
        return (10 ** 6, NOT_KNOWN)
    lo = None
    for i, e in enumerate(edges):
        if n <= e:
            if lo is None:
                return (i, 'Up to %d%s' % (e, unit))
            return (i, '%d–%d%s' % (lo + 1, e, unit))
        lo = e
    return (len(edges), 'More than %d%s' % (edges[-1], unit))


def _age_band(age):
    try:
        a = int(str(age).strip())
    except (TypeError, ValueError):
        return (10 ** 6, NOT_KNOWN)
    for i, (hi, label) in enumerate(((17, 'Under 18'), (39, '18–39'), (59, '40–59'), (69, '60–69'), (79, '70–79'))):
        if a <= hi:
            return (i, label)
    return (9, '80 and over')


class Measure:
    """kind: count | sum (of a field) | avg (of a field) | ratio (sum of `field` / sum of `of`) | distinct (how many
    different `field`s there are: visitors, not the pages they opened). `ga`: a Google Analytics number GA's screens
    show but its API does not give, worked out of two it does -- the first divided by the second."""

    def __init__(self, key, label, kind='count', field=None, of=None, unit='count', additive=True, lower_better=False,
                 ga=None):
        self.key, self.label, self.kind, self.field, self.of, self.unit = key, label, kind, field, of, unit
        self.additive = additive and kind in ('count', 'sum')
        # a smaller number is the good news (an average position, a bounce rate): the change is coloured the other way
        self.lower_better = lower_better
        self.ga = tuple(ga) if ga else None

    def value(self, rows):
        if self.kind == 'count':
            return len(rows)
        if self.kind == 'sum':
            return sum((r.get(self.field) or 0) for r in rows)
        if self.kind == 'distinct':
            return len({r[self.field] for r in rows if r.get(self.field) is not None})
        if self.kind == 'avg':
            vals = [r[self.field] for r in rows if r.get(self.field) is not None]
            return round(sum(vals) / len(vals), 2) if vals else None
        num = sum((r.get(self.field) or 0) for r in rows)
        den = sum((r.get(self.of) or 0) for r in rows)
        return round(num / den, 4) if den else None


class Dim:
    """fn(row) -> (sort key, label); `multi`: fn returns a list (a trip with two needs counts under each);
    `ordered`: the groups keep their natural order instead of biggest first; `fill`: the (sort, label)s always shown,
    nought or not (every hour of the day)."""

    def __init__(self, key, label, fn, multi=False, ordered=False, fill=None):
        self.key, self.label, self.fn, self.multi, self.ordered = key, label, fn, multi, ordered
        self.fill = list(fill or ())

    def keys(self, row):
        out = self.fn(row)
        if self.multi:
            return out or [(10 ** 6, NOT_KNOWN)]
        return [out]


class Source:
    kind = 'db'
    grains = tuple(GRAINS)
    live = False

    def __init__(self, key, label, group, icon, says, measures, dims, dates, fetch, staff_only=False):
        self.key, self.label, self.group, self.icon, self.says = key, label, group, icon, says
        self.measures = OrderedDict((m.key, m) for m in measures)
        self.dims = OrderedDict((d.key, d) for d in dims)
        self.dates = OrderedDict(dates)
        self._fetch = fetch
        self.staff_only = staff_only

    def fetch(self, period, date_field):
        """Rows with '_when' (the India day of `date_field`) inside the period. While a whole dashboard is drawn
        (mkt_dashboards.render) its boxes share what they read: thirty boxes of visitors are one question."""
        from flask import g, has_app_context
        shared = g.get('_mkt_rows') if has_app_context() else None
        if shared is None:
            return self._fetch(period, date_field)
        k = (self.key, period.start, period.end, date_field)
        if k not in shared:
            shared[k] = self._fetch(period, date_field)
        return shared[k]


def _when(v):
    """The India day of a stored value: a UTC datetime is moved to India time, a date is already a day."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return (v + IST).date()
    return v


def _by_date(rows, period, field_of):
    out = []
    for r in rows:
        w = _when(field_of(r))
        if w is not None and period.start <= w <= period.end:
            r['_when'] = w
            out.append(r)
    return out


def _created_filter(q, col, period):
    a, b = period.utc()
    return q.filter(col >= a, col < b)


# ------------------------------------------------------------------------------------------------ places

DIRECTIONS = ('India → abroad', 'Abroad → India', 'Within India', 'Between other countries', 'Route not known')


def _country_of_iata(iata):
    """The country's name for an airport: the list keeps ISO codes ("IN"); one an admin added may hold a name."""
    if not iata:
        return None
    from app.services import locations, phone
    c = str((locations.airport(iata) or {}).get('country') or '').strip()
    if len(c) == 2:
        return (phone.BY_ISO.get(c.upper()) or {}).get('name') or c.upper()
    return c or None


def _direction(o, d):
    if not o or not d:
        return DIRECTIONS[4]
    o_in, d_in = o == 'India', d == 'India'
    if o_in and not d_in:
        return DIRECTIONS[0]
    if d_in and not o_in:
        return DIRECTIONS[1]
    if o_in and d_in:
        return DIRECTIONS[2]
    return DIRECTIONS[3]


def _dir_key(label):
    return (DIRECTIONS.index(label) if label in DIRECTIONS else 9, label)


def _route(a, b):
    if not a and not b:
        return (10 ** 6, NOT_KNOWN)
    return (0, '%s → %s' % (a or '?', b or '?'))


def _place_dims(prefix=''):
    """The route dimensions trips and flights share, so a box can switch between the two."""
    return [
        Dim('direction', 'Direction (India ↔ abroad)', lambda r: _dir_key(r['direction']), ordered=True),
        Dim('origin_country', 'Flying from (country)', lambda r: _cat(r['o_country'])),
        Dim('dest_country', 'Flying to (country)', lambda r: _cat(r['d_country'])),
        Dim('country_route', 'Country to country', lambda r: _route(r['o_country'], r['d_country'])
            if (r['o_country'] or r['d_country']) else (10 ** 6, NOT_KNOWN)),
        Dim('origin_city', 'Flying from (city)', lambda r: _cat(r['o_city'])),
        Dim('dest_city', 'Flying to (city)', lambda r: _cat(r['d_city'])),
        Dim('route', 'City to city', lambda r: _route(r['o_city'], r['d_city'])
            if (r['o_city'] and r['d_city']) else (10 ** 6, NOT_KNOWN)),
        Dim('airline', 'Airline', lambda r: _cat(r['airline'])),
    ]


def _with_places(r, o_iata, d_iata, o_city, d_city):
    r['o_country'] = _country_of_iata(o_iata)
    r['d_country'] = _country_of_iata(d_iata)
    r['o_city'] = o_city
    r['d_city'] = d_city
    r['direction'] = _direction(r['o_country'], r['d_country'])
    return r


# ------------------------------------------------------------------------------------------------ trips and flights

def _labels(name):
    from app import options
    try:
        return dict(options.labels(name))
    except Exception:          # noqa: BLE001 -- an option list nobody set up yet
        return {}


def _fetch_trips(period, date_field):
    from app.models import CompanionRequest as T
    cols = (T.id, T.created_at, T.from_date, T.origin_iata, T.dest_iata, T.origin_city, T.dest_city, T.airline,
            T.role, T.status, T.source, T.trip_type, T.traveler_age_group, T.traveler_gender, T.traveller_needs,
            T.preferred_languages, T.travellers, T.ticket_booked, T.on_behalf_of, T.category)
    q = db.session.query(*cols)
    if date_field == 'travel':
        q = q.filter(T.from_date >= period.start, T.from_date <= period.end)
    else:
        q = _created_filter(q, T.created_at, period)
    out = []
    for row in q.limit(ROW_LIMIT).all():
        r = dict(zip(('id', 'created', 'travel', 'o_iata', 'd_iata', 'o_city', 'd_city', 'airline', 'role', 'status',
                      'intake', 'trip_type', 'age', 'gender', 'needs', 'langs', 'travellers', 'ticket', 'behalf',
                      'category'), row))
        _with_places(r, r['o_iata'], r['d_iata'], r['o_city'], r['d_city'])
        r['n_travellers'] = len(r['travellers']) if isinstance(r['travellers'], list) and r['travellers'] else 1
        out.append(r)
    return _by_date(out, period, lambda r: r['travel'] if date_field == 'travel' else r['created'])


def _trip_dims():
    from app.models import AGE_GROUP_LABELS, TRIP_ROLE_LABELS, TRIP_SOURCE_LABELS
    needs = _labels('traveller_needs')
    return _place_dims() + [
        Dim('role', 'Looking for or offering help', lambda r: _cat(TRIP_ROLE_LABELS.get(r['role'], r['role']))),
        Dim('status', 'Status', lambda r: _cat((r['status'] or '').capitalize())),
        Dim('intake', 'How it came in', lambda r: _cat(TRIP_SOURCE_LABELS.get(r['intake'], r['intake']))),
        Dim('trip_type', 'One way or round trip',
            lambda r: _cat((r['trip_type'] or '').replace('_', ' ').capitalize())),
        Dim('age', 'Age of the traveller', lambda r: _cat(AGE_GROUP_LABELS.get(r['age'], r['age'])), ordered=True),
        Dim('gender', 'Traveller is', lambda r: _cat((r['gender'] or '').capitalize())),
        Dim('needs', 'Help they need', lambda r: [_cat(needs.get(n, str(n).replace('_', ' ').capitalize()))
                                                 for n in (r['needs'] or []) if n], multi=True),
        Dim('languages', 'Languages they speak', lambda r: [_cat(x) for x in (r['langs'] or []) if x], multi=True),
        Dim('ticket', 'Ticket booked', lambda r: _yes(r['ticket'], 'Ticket booked', 'Not booked yet'), ordered=True),
        Dim('behalf', 'Who is travelling', lambda r: _cat(str(r['behalf'] or '').replace('_', ' ').capitalize())),
        Dim('category', 'Reason for travel', lambda r: _cat(r['category'])),
    ]


def _fetch_flights(period, date_field):
    from app.models import CompanionRequest as T, TripLeg as L
    q = (db.session.query(L.kind, L.origin_iata, L.dest_iata, L.origin_city, L.dest_city, L.depart_date, L.airline,
                          T.created_at, T.role, T.status)
         .join(T, T.id == L.trip_id))
    if date_field == 'created':
        q = _created_filter(q, T.created_at, period)
    else:
        q = q.filter(L.depart_date >= period.start, L.depart_date <= period.end)
    out = []
    for row in q.limit(ROW_LIMIT).all():
        r = dict(zip(('kind', 'o_iata', 'd_iata', 'o_city', 'd_city', 'travel', 'airline', 'created', 'role',
                      'status'), row))
        out.append(_with_places(r, r['o_iata'], r['d_iata'], r['o_city'], r['d_city']))
    return _by_date(out, period, lambda r: r['created'] if date_field == 'created' else r['travel'])


def _flight_dims():
    from app.models import TRIP_ROLE_LABELS
    return _place_dims() + [
        Dim('kind', 'Outbound or return', lambda r: _cat({'outbound': 'Outbound', 'return': 'Return'}.get(
            r['kind'], 'A leg of a longer trip'))),
        Dim('role', 'Looking for or offering help', lambda r: _cat(TRIP_ROLE_LABELS.get(r['role'], r['role']))),
        Dim('status', 'Status of the trip', lambda r: _cat((r['status'] or '').capitalize())),
    ]


# ------------------------------------------------------------------------------------------------ insurance

PLAN_LABELS = {'visitors': 'Visitors Medical (to the USA)', 'health': 'Travel Medical', 'schengen': 'Schengen'}


def _iso3_names():
    from app.services import insurance_countries
    return dict(insurance_countries.ALL)


def _fetch_insurance(period, date_field):
    from app.models import InsuranceQuote as Q
    q = db.session.query(Q.created_at, Q.start_date, Q.end_date, Q.insurance_type, Q.citizenship, Q.destination,
                         Q.travellers, Q.status)
    if date_field == 'travel':
        q = q.filter(Q.start_date >= period.start, Q.start_date <= period.end)
    else:
        q = _created_filter(q, Q.created_at, period)
    names = _iso3_names()
    out = []
    for row in q.limit(ROW_LIMIT).all():
        r = dict(zip(('created', 'travel', 'end', 'plan', 'citizen', 'dest', 'travellers', 'status'), row))
        r['citizen_name'] = names.get((r['citizen'] or '').upper()) or None
        if r['plan'] == 'visitors':
            r['dest_name'] = 'United States'
        elif r['plan'] == 'schengen':
            r['dest_name'] = 'Schengen area'
        else:
            r['dest_name'] = names.get((r['dest'] or '').upper()) or None
        r['direction'] = _direction(r['citizen_name'], r['dest_name']) if r['citizen_name'] and r['dest_name'] \
            else DIRECTIONS[4]
        r['days'] = (r['end'] - r['travel']).days + 1 if r['end'] and r['travel'] else None
        r['ages'] = [t.get('age') for t in (r['travellers'] or []) if isinstance(t, dict)]
        r['n_travellers'] = len(r['ages']) or 1
        out.append(r)
    return _by_date(out, period, lambda r: r['travel'] if date_field == 'travel' else r['created'])


def _insurance_dims():
    return [
        Dim('direction', 'Direction (India ↔ abroad)', lambda r: _dir_key(r['direction']), ordered=True),
        Dim('plan', 'Plan asked for', lambda r: _cat(PLAN_LABELS.get(r['plan'], (r['plan'] or '').capitalize()))),
        Dim('citizen', 'Citizen of', lambda r: _cat(r['citizen_name'])),
        Dim('dest', 'Travelling to', lambda r: _cat(r['dest_name'])),
        Dim('length', 'Length of the trip', lambda r: _band(r['days'], [7, 15, 30, 90, 180], ' days'), ordered=True),
        Dim('party', 'Travellers in the quote', lambda r: _band(r['n_travellers'], [1, 2, 3]), ordered=True),
        Dim('ages', 'Age of each traveller', lambda r: [_age_band(a) for a in r['ages']], multi=True, ordered=True),
        Dim('status', 'Status', lambda r: _cat((r['status'] or '').capitalize())),
    ]


# ------------------------------------------------------------------------------------------------ the rest

def _fetch_sahayak(period, date_field):
    from app.models import SahayakBooking as B
    q = db.session.query(B.created_at, B.scheduled_for, B.service_name, B.status, B.when_type, B.patient_age)
    if date_field != 'visit':
        q = _created_filter(q, B.created_at, period)
    out = [dict(zip(('created', 'visit', 'service', 'status', 'when', 'age'), row)) for row in q.limit(ROW_LIMIT)]

    def day(r):
        if date_field != 'visit':
            return r['created']
        # the time chosen for a visit is India time already; one "as soon as possible" is the day it was booked
        return r['visit'].date() if r['visit'] else r['created']
    return _by_date(out, period, day)


def _sahayak_dims():
    from app.models import SAHAYAK_STATUS_LABELS, SAHAYAK_WHEN_LABELS
    return [
        Dim('service', 'Service', lambda r: _cat(r['service'])),
        Dim('status', 'Status', lambda r: _cat(SAHAYAK_STATUS_LABELS.get(r['status'], r['status']))),
        Dim('when', 'When they asked for it', lambda r: _cat(SAHAYAK_WHEN_LABELS.get(r['when'], r['when']))),
        Dim('age', 'Age of the person cared for', lambda r: _age_band(r['age']), ordered=True),
    ]


def _fetch_enquiries(period, date_field):
    from app.models import ContactMessage as C
    q = _created_filter(db.session.query(C.created_at, C.topic, C.status), C.created_at, period)
    out = [dict(zip(('created', 'topic', 'status'), row)) for row in q.limit(ROW_LIMIT).all()]
    return _by_date(out, period, lambda r: r['created'])


def _enquiry_dims():
    from app.models import CONTACT_STATUS_LABELS, CONTACT_TOPIC_LABELS, CONTACT_TOPICS
    return [
        Dim('topic', 'About', lambda r: ((CONTACT_TOPICS.index(r['topic']) if r['topic'] in CONTACT_TOPICS else 9),
                                         CONTACT_TOPIC_LABELS.get(r['topic'], r['topic'] or NOT_KNOWN))),
        Dim('status', 'Answered yet', lambda r: _cat(CONTACT_STATUS_LABELS.get(r['status'], r['status']))),
    ]


def _fetch_reviews(period, date_field):
    from app.models import Feedback as F
    q = _created_filter(db.session.query(F.created_at, F.site, F.rating).filter(F.is_approved.is_(True)),
                        F.created_at, period)
    out = [dict(zip(('created', 'site', 'rating'), row)) for row in q.limit(ROW_LIMIT).all()]
    return _by_date(out, period, lambda r: r['created'])


def _review_dims():
    from app.models import REVIEW_SITE_LABELS
    return [
        Dim('product', 'Service', lambda r: _cat(REVIEW_SITE_LABELS.get(r['site'], r['site']))),
        Dim('stars', 'Stars', lambda r: (5 - int(r['rating'] or 0), '%d ★' % int(r['rating'] or 0)), ordered=True),
    ]


def _fetch_signups(period, date_field):
    from app.models import User as U
    q = _created_filter(db.session.query(U.created_at, U.signed_up, U.oauth_provider, U.is_verified,
                                         U.language_preference, U.marketing_consent)
                        .filter(U.is_admin.isnot(True), db.func.coalesce(U.role, 'user') == 'user'),
                        U.created_at, period)
    out = [dict(zip(('created', 'self', 'oauth', 'verified', 'lang', 'offers'), row)) for row in q.limit(ROW_LIMIT)]
    return _by_date(out, period, lambda r: r['created'])


def _signup_dims():
    def how(r):
        if r['oauth']:
            return (0, 'With %s' % str(r['oauth']).capitalize())
        if r['self']:
            return (1, 'On the sign-up page')
        return (2, 'Made by our team or by claiming a trip')
    return [
        Dim('how', 'How the account was made', how, ordered=True),
        Dim('verified', 'E-mail confirmed', lambda r: _yes(r['verified'], 'Confirmed', 'Not confirmed'), ordered=True),
        Dim('offers', 'OK to send offers', lambda r: _yes(r['offers'], 'OK to send offers', 'No offers'), ordered=True),
        Dim('lang', 'Site language', lambda r: _cat((r['lang'] or 'en').upper())),
    ]


def _fetch_blog(period, date_field):
    from app.models import Blog as B
    q = (db.session.query(B.published_at, B.is_featured)
         .filter(B.is_published.is_(True), B.trashed_at.is_(None), B.published_at.isnot(None)))
    q = _created_filter(q, B.published_at, period)
    out = [dict(zip(('published', 'featured'), row)) for row in q.limit(ROW_LIMIT).all()]
    return _by_date(out, period, lambda r: r['published'])


def _fetch_leads(period, date_field):
    from app.models import CrmLead as L, CrmPerson as P
    q = (db.session.query(L.created_at, L.closed_at, L.status, L.product, L.source_id, L.pipeline_id, L.utm,
                          P.country)
         .outerjoin(P, P.id == L.person_id).filter(L.deleted_at.is_(None))
         # company-wide COUNTS: the per-person visibility (crm_access) is for working leads, not for counting them
         .execution_options(include_hidden=True))
    q = _created_filter(q, L.closed_at if date_field == 'closed' else L.created_at, period)
    out = []
    for row in q.limit(ROW_LIMIT).all():
        r = dict(zip(('created', 'closed', 'status', 'product', 'source', 'pipeline', 'utm', 'country'), row))
        r['won'] = 1 if r['status'] == 'won' else 0
        r['lost'] = 1 if r['status'] == 'lost' else 0
        r['decided'] = r['won'] + r['lost']
        out.append(r)
    return _by_date(out, period, lambda r: r['closed'] if date_field == 'closed' else r['created'])


class _LeadNames:
    """The names the lead dimensions show, read once per run."""

    def __init__(self):
        from app.models import CrmPipeline, CrmSource
        from app.services import crm_products
        self.products = crm_products.labels()
        self.sources = {s.id: s.name for s in CrmSource.query.all()}
        self.pipes = {p.id: p.name for p in CrmPipeline.query.all()}
        self._camps = None

    def campaign(self, r):
        from app.services import crm_campaigns
        if self._camps is None:
            self._camps = [c for c in crm_campaigns.rows() if crm_campaigns.is_campaign(c)]
        for n, c in enumerate(self._camps):
            if crm_campaigns.owns(c, r['utm'], r['source'], r['created']):
                return (n, crm_campaigns.label(c))
        return (10 ** 5, 'No campaign')


def _ln():
    from flask import g, has_app_context
    if has_app_context():
        if not hasattr(g, '_mkt_lead_names'):
            g._mkt_lead_names = _LeadNames()
        return g._mkt_lead_names
    return _LeadNames()


def _utm(r, key):
    u = r['utm'] if isinstance(r['utm'], dict) else {}
    return _cat(str(u.get(key) or '').strip().lower() or None)


def _lead_dims():
    from app.services.crm_report_builder import _country
    return [
        Dim('product', 'Product', lambda r: _cat(_ln().products.get(r['product'], r['product']))),
        Dim('source', 'Where it came from', lambda r: _cat(_ln().sources.get(r['source']))),
        Dim('campaign', 'Campaign', lambda r: _ln().campaign(r)),
        Dim('country', 'Country of the person', lambda r: _cat(_country(r['country']))),
        Dim('status', 'Open, won or lost', lambda r: {'won': (1, 'Won'), 'lost': (2, 'Lost')}.get(
            r['status'], (0, 'Still open')), ordered=True),
        Dim('pipeline', 'Pipeline', lambda r: _cat(_ln().pipes.get(r['pipeline']))),
        Dim('utm_source', 'Ad source (utm_source)', lambda r: _utm(r, 'utm_source')),
        Dim('utm_medium', 'Ad medium (utm_medium)', lambda r: _utm(r, 'utm_medium')),
        Dim('utm_campaign', 'Ad campaign (utm_campaign)', lambda r: _utm(r, 'utm_campaign')),
    ]


# ------------------------------------------------------------------------------------------------ our own visitors
# What our chat bubble records of every browser on our websites (services/visitors.py, 2026-10-30): one row a page
# opened, with the visitor's place, device and way in. The visitor's internet address is not a dimension here --
# it is shown one visitor at a time, to staff, by the "Visitors one by one" box and Inbox › Visitors.

HOURS = [(h, '%02d:00' % h) for h in range(24)]
WEEKDAYS = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')
WEEKDAY_FILL = list(enumerate(WEEKDAYS))


def _path(url):
    """'/travel-insurance' of 'https://nriparentservice.com/travel-insurance?x=1'."""
    from urllib.parse import urlparse
    try:
        p = urlparse(str(url or ''))
    except ValueError:
        return None
    return (p.path or '/') if p.netloc else None


def _host(url):
    from urllib.parse import urlparse
    try:
        host = (urlparse(str(url or '')).hostname or '').lower()
    except ValueError:
        return None
    return host[4:] if host.startswith('www.') else (host or None)


def _fetch_visitors(period, date_field):
    from app.models import CrmLiveChat, CrmVisitor as V, CrmVisitorPage as P
    a, b = period.utc()
    q = (db.session.query(P.visitor_id, P.at, P.url, P.title, P.visit, P.secs, P.came_from, V.country, V.region,
                          V.city, V.device, V.browser, V.os, V.source, V.campaign, V.site, V.lang, V.tz, V.person_id)
         .join(V, V.id == P.visitor_id).filter(P.at >= a, P.at < b).order_by(P.at, P.id).limit(ROW_LIMIT))
    names = ('vid', 'at', 'url', 'title', 'visit', 'secs', 'came_from', 'country', 'region', 'city', 'device',
             'browser', 'os', 'source', 'campaign', 'site', 'lang', 'tz', 'person')
    rows = [dict(zip(names, r)) for r in q.all()]
    ids = {r['vid'] for r in rows}
    chatted = {i for (i,) in db.session.query(CrmLiveChat.visitor_id).filter(CrmLiveChat.visitor_id.in_(ids))
               .distinct()} if ids else set()
    landing, way_in = {}, {}
    for r in rows:
        k = (r['vid'], r['visit'])
        # the first page of a visit says where the visit came from; a visit begun before these dates keeps its first
        # page seen in them
        if k not in landing or (r['came_from'] and not way_in.get(k)):
            landing[k] = _path(r['url'])
            way_in[k] = r['came_from']
        local = r['at'] + IST
        chat = r['person'] is not None or r['vid'] in chatted
        r.update(_when=local.date(), visit_key=k, hour=local.hour, weekday=local.weekday(), path=_path(r['url']),
                 host=_host(r['url']) or r['site'], first=r['visit'] == 1,
                 new_vid=r['vid'] if r['visit'] == 1 else None, chat_vid=r['vid'] if chat else None, chat=chat)
    for r in rows:
        k = r['visit_key']
        r['landing'] = landing.get(k)
        r['way_in'] = way_in.get(k) or r['source']
    return rows


DEVICE_WORDS = {'phone': (0, 'Phone'), 'tablet': (1, 'Tablet'), 'computer': (2, 'Computer')}


def _visitor_dims(live=False):
    from app.services import visitors
    out = [
        Dim('country', 'Country', lambda r: _cat(r['country'])),
        Dim('region', 'State or region', lambda r: _cat(r['region'])),
        Dim('city', 'City', lambda r: _cat(r['city'])),
        Dim('device', 'Device', lambda r: DEVICE_WORDS.get(r['device'], (10 ** 6, NOT_KNOWN)), ordered=True),
        Dim('browser', 'Browser', lambda r: _cat(r['browser'])),
        Dim('os', 'Operating system', lambda r: _cat(r['os'])),
        Dim('page', 'Page', lambda r: _cat(r['path'])),
        Dim('title', 'Page title', lambda r: _cat(r['title'])),
        Dim('site', 'Website', lambda r: _cat(r['host'])),
    ]
    if live:
        return out + [Dim('source', 'How they found us', lambda r: _cat(r['source'] or visitors.DIRECT))]
    return out + [
        Dim('source', 'How they found us (this visit)', lambda r: _cat(r['way_in'] or visitors.DIRECT)),
        Dim('first_source', 'How they first found us', lambda r: _cat(r['source'] or visitors.DIRECT)),
        Dim('campaign', 'Campaign (utm)', lambda r: _cat(r['campaign'])),
        Dim('landing', 'Landing page (first page of the visit)', lambda r: _cat(r['landing'])),
        Dim('returning', 'First visit or came back', lambda r: (0, 'First visit') if r['first'] else (1, 'Came back'),
            ordered=True),
        Dim('chat', 'Started a chat', lambda r: _yes(r['chat'], 'Started a chat', 'Did not chat'), ordered=True),
        Dim('hour', 'Hour of the day (India time)', lambda r: HOURS[r['hour']], ordered=True, fill=HOURS),
        Dim('weekday', 'Day of the week', lambda r: (r['weekday'], WEEKDAYS[r['weekday']]), ordered=True,
            fill=WEEKDAY_FILL),
        Dim('lang', 'Browser language', lambda r: _cat((r['lang'] or '').split('-')[0].lower() or None)),
        Dim('tz', 'Time zone', lambda r: _cat(r['tz'])),
    ]


def _fetch_visitors_now(period, date_field):
    from app.services import visitors
    out = []
    for row in visitors.now_list():
        v = row['v']
        out.append({'_when': today(), 'vid': v.id, 'country': v.country, 'region': v.region, 'city': v.city,
                    'device': v.device, 'browser': v.browser, 'os': v.os, 'path': _path(v.page_url),
                    'title': v.page_title, 'host': _host(v.page_url) or v.site, 'source': v.source})
    return out


# ------------------------------------------------------------------------------------------------ the website

class GASource(Source):
    """Google Analytics 4. Measures are GA metrics, dimensions GA dimensions; the time grains are GA's own
    (`date`, `isoYearIsoWeek`, `yearMonth`, `year`) so a month's visitors are counted once, not summed per day."""
    kind = 'ga'
    grains = ('auto', 'day', 'week', 'month', 'year')

    def __init__(self, key, label, group, icon, says, metrics, dims, live=False):
        super().__init__(key, label, group, icon, says, metrics, [], [('visit', 'Visited')], None)
        self.ga_dims = OrderedDict(dims)
        self.dims = OrderedDict((k, Dim(k, v[0], None, ordered=k in GA_ORDERED)) for k, v in dims.items())
        self.live = live
        if live:
            self.grains = ()
            self.dates = OrderedDict([('now', 'The last 30 minutes')])


GA_GRAIN = {'day': 'date', 'week': 'isoYearIsoWeek', 'month': 'yearMonth', 'year': 'year'}

# Everything Google Analytics' own screens show about a website (Reports: realtime, acquisition, engagement, user
# attributes, tech, retention), in our words. `unit` 'decimal' is a number with a fraction (pages per visit).
GA_METRICS = [
    Measure('activeUsers', 'Visitors', additive=False), Measure('newUsers', 'New visitors'),
    Measure('totalUsers', 'Everybody who came (total users)', additive=False),
    Measure('sessions', 'Visits'), Measure('screenPageViews', 'Page views'),
    Measure('engagedSessions', 'Engaged visits'),
    Measure('engagementRate', 'Engagement rate', kind='avg', unit='pct', additive=False),
    Measure('avgEngagement', 'Average time engaged per visitor', kind='avg', unit='seconds', additive=False,
            ga=('userEngagementDuration', 'activeUsers')),
    Measure('userEngagementDuration', 'Time engaged (all visitors together)', unit='seconds'),
    Measure('averageSessionDuration', 'Average visit length', kind='avg', unit='seconds', additive=False),
    Measure('bounceRate', 'Bounce rate', kind='avg', unit='pct', additive=False, lower_better=True),
    Measure('screenPageViewsPerSession', 'Pages per visit', kind='avg', unit='decimal', additive=False),
    Measure('screenPageViewsPerUser', 'Pages per visitor', kind='avg', unit='decimal', additive=False),
    Measure('sessionsPerUser', 'Visits per visitor', kind='avg', unit='decimal', additive=False),
    Measure('keyEvents', 'Key events (conversions)'), Measure('eventCount', 'Events'),
    Measure('eventsPerSession', 'Events per visit', kind='avg', unit='decimal', additive=False),
    Measure('sessionKeyEventRate', 'Visits with a key event', kind='avg', unit='pct', additive=False),
    Measure('userKeyEventRate', 'Visitors with a key event', kind='avg', unit='pct', additive=False),
    Measure('scrolledUsers', 'Visitors who scrolled to the end', additive=False),
    Measure('active1DayUsers', 'Daily active visitors', additive=False),
    Measure('active7DayUsers', 'Weekly active visitors (7 days)', additive=False),
    Measure('active28DayUsers', 'Monthly active visitors (28 days)', additive=False),
    Measure('dauPerMau', 'Stickiness: daily ÷ monthly visitors', kind='avg', unit='pct', additive=False),
    Measure('wauPerMau', 'Stickiness: weekly ÷ monthly visitors', kind='avg', unit='pct', additive=False),
]
GA_DIMS = OrderedDict([
    # where they are
    ('country', ('Country', 'country')), ('city', ('City', 'city')), ('region', ('State or region', 'region')),
    ('continent', ('Continent', 'continent')), ('subcontinent', ('Part of the world', 'subContinent')),
    ('language', ('Language', 'language')),
    # how they found us: this visit, and their very first
    ('channel', ('Channel', 'sessionDefaultChannelGroup')),
    ('source', ('Source', 'sessionSource')), ('medium', ('Medium', 'sessionMedium')),
    ('source_medium', ('Source / medium', 'sessionSourceMedium')), ('campaign', ('Campaign', 'sessionCampaignName')),
    ('term', ('Ad keyword (utm_term)', 'sessionManualTerm')),
    ('ad_content', ('Ad content (utm_content)', 'sessionManualAdContent')),
    ('referrer', ('Page they came from', 'pageReferrer')),
    ('first_channel', ("First visit's channel", 'firstUserDefaultChannelGroup')),
    ('first_source', ("First visit's source", 'firstUserSource')),
    ('first_medium', ("First visit's medium", 'firstUserMedium')),
    ('first_campaign', ("First visit's campaign", 'firstUserCampaignName')),
    # what they read and did
    ('landing', ('Landing page', 'landingPage')), ('page', ('Page', 'pagePath')), ('title', ('Page title', 'pageTitle')),
    ('full_page', ('Page with its query (?…)', 'pagePathPlusQueryString')),
    ('site', ('Website (host name)', 'hostName')), ('event', ('Event', 'eventName')),
    ('link', ('Link clicked to another site', 'linkUrl')), ('link_site', ('Site linked to', 'linkDomain')),
    ('file', ('File downloaded', 'fileName')), ('search_term', ('Searched for on our site', 'searchTerm')),
    ('video', ('Video watched', 'videoTitle')), ('scrolled', ('How far down they scrolled (%)', 'percentScrolled')),
    # who they are (Google signals: shown only once enough people came)
    ('returning', ('New or returning', 'newVsReturning')), ('age', ('Age', 'userAgeBracket')),
    ('gender', ('Gender', 'userGender')), ('interests', ('Interests', 'brandingInterest')),
    # their device
    ('device', ('Device', 'deviceCategory')), ('platform', ('Platform', 'platform')),
    ('browser', ('Browser', 'browser')), ('os', ('Operating system', 'operatingSystem')),
    ('os_version', ('Operating system and version', 'operatingSystemWithVersion')),
    ('screen', ('Screen size', 'screenResolution')), ('brand', ('Phone or computer make', 'mobileDeviceBranding')),
    ('model', ('Device model', 'mobileDeviceModel')),
    # when they come (the property's own time zone)
    ('hour', ('Hour of the day', 'hour')), ('weekday', ('Day of the week', 'dayOfWeekName')),
])
GA_ORDERED = ('hour', 'weekday', 'age', 'scrolled')
GA_LIVE_METRICS = [Measure('activeUsers', 'People on the site', additive=False), Measure('screenPageViews', 'Page views'),
                   Measure('eventCount', 'Events'), Measure('keyEvents', 'Key events (conversions)')]
GA_LIVE_DIMS = OrderedDict([
    ('country', ('Country', 'country')), ('city', ('City', 'city')), ('device', ('Device', 'deviceCategory')),
    ('page', ('Page', 'unifiedScreenName')), ('event', ('Event', 'eventName')), ('platform', ('Platform', 'platform')),
    ('minutes', ('Minutes ago', 'minutesAgo')), ('audience', ('Audience', 'audienceName')),
])


class GSCSource(Source):
    """Google Search Console: Google search results that showed one of our pages. Its only time is the day, so weeks,
    months and the rest are added up here (clicks and times shown add up; the click rate and the position are worked
    out again from them, the position weighted by how often each page was shown)."""
    kind = 'gsc'

    def __init__(self, key, label, group, icon, says, metrics, dims):
        super().__init__(key, label, group, icon, says, metrics, [], [('search', 'Searched on')], None)
        self.gsc_dims = OrderedDict(dims)
        self.dims = OrderedDict((k, Dim(k, v[0], None, ordered=k == 'band')) for k, v in dims.items())


GSC_METRICS = [
    Measure('clicks', 'Clicks from Google'), Measure('impressions', 'Times shown in Google'),
    Measure('ctr', 'Click rate', kind='avg', unit='pct', additive=False),
    Measure('position', 'Average position', kind='avg', unit='position', additive=False, lower_better=True),
]
# 'type' and 'band' are ours: Search Console answers one kind of search per question (we ask for each and add them
# up), and where we came is worked out from each search's (or page's) own average position.
GSC_DIMS = OrderedDict([
    ('query', ('Words people searched', 'query')), ('page', ('Page Google showed', 'page')),
    ('country', ('Country', 'country')), ('device', ('Device', 'device')),
    ('appearance', ('How Google showed it (search appearance)', 'searchAppearance')),
    ('type', ('Kind of search (web, images, videos, news, Discover)', 'type')),
    ('band', ('Where we came in the results', 'band')),
])
GSC_TYPES = OrderedDict([('web', 'Web'), ('image', 'Images'), ('video', 'Videos'), ('news', 'News tab'),
                         ('discover', 'Discover'), ('googleNews', 'Google News')])
GSC_BANDS = ((3, 'Top 3'), (10, '4th to 10th (first page)'), (20, '11th to 20th (second page)'),
             (50, '21st to 50th'), (None, 'Below 50th'))
GSC_APPEARANCE = {'AMP_BLUE_LINK': 'AMP page', 'AMP_TOP_STORIES': 'Top stories (AMP)', 'TRANSLATED_RESULT':
                  'Translated result', 'VIDEO': 'Video', 'RICHCARD': 'Rich result', 'REVIEW_SNIPPET': 'Review stars',
                  'FAQ_RICH_RESULT': 'FAQ', 'PRODUCT_SNIPPETS': 'Product snippet', 'MERCHANT_LISTINGS':
                  'Merchant listing', 'BREADCRUMB': 'Breadcrumb', 'SITELINKS': 'Sitelinks', 'WEBLITE': 'Web Light'}


# ------------------------------------------------------------------------------------------------ the catalogue

def _keep_days():
    from app.services import visitors
    return visitors.KEEP_DAYS


def _live(src):
    """A source of ours that tells what is so this minute: no dates and no time grains, like GA's realtime."""
    src.live = True
    src.grains = ()
    src.dates = OrderedDict([('now', 'Now')])
    return src


def _sources():
    out = [
        GASource('website', 'Website visitors (Google Analytics)', 'Website', 'fa-globe',
                 'Visitors, visits, page views and engagement on the website, from Google Analytics.',
                 GA_METRICS, GA_DIMS),
        GASource('website_now', 'Website right now (last 30 minutes)', 'Website', 'fa-signal',
                 'Who is on the website now, from Google Analytics in real time.', GA_LIVE_METRICS, GA_LIVE_DIMS,
                 live=True),
        GSCSource('search', 'Google search (Search Console)', 'Website', 'fa-magnifying-glass',
                  'How we do in Google search: the words people searched, the pages Google showed, how often they '
                  'clicked and how high we came. Two or three days behind; 16 months back.', GSC_METRICS, GSC_DIMS),
        Source('visitors', 'Our visitors (our own record)', 'Website', 'fa-eye',
               'Every page opened on our websites, as our chat bubble records it: where the visitor is, their '
               'device, how they found us and how long they read. To the minute; kept %d days.' % _keep_days(),
               [Measure('visitors', 'Visitors', kind='distinct', field='vid', additive=False),
                Measure('visits', 'Visits', kind='distinct', field='visit_key', additive=False),
                Measure('count', 'Pages opened'),
                Measure('new', 'First-time visitors', kind='distinct', field='new_vid', additive=False),
                Measure('secs', 'Average time on a page', kind='avg', field='secs', unit='seconds', additive=False),
                Measure('time', 'Time spent reading (all together)', kind='sum', field='secs', unit='seconds'),
                Measure('chatters', 'Visitors who started a chat', kind='distinct', field='chat_vid',
                        additive=False)],
               _visitor_dims(), [('visit', 'Visited')], _fetch_visitors),
        _live(Source('visitors_now', 'Our visitors right now (our own record)', 'Website', 'fa-signal',
                     'Who is on our websites this minute, as our chat bubble sees them.',
                     [Measure('count', 'People on our websites')], _visitor_dims(live=True), [('now', 'Now')],
                     _fetch_visitors_now)),
        Source('trips', 'Trips posted (Travel Companion)', 'Travel', 'fa-plane-departure',
               'Every trip posted: where from and to, India ↔ abroad, when, the airline, who and what help.',
               [Measure('count', 'Trips'), Measure('travellers', 'Travellers', kind='sum', field='n_travellers')],
               _trip_dims(), [('created', 'Posted'), ('travel', 'Travel date')], _fetch_trips),
        Source('flights', 'Flights (each leg of a trip)', 'Travel', 'fa-route',
               'Each flown leg on its own: a round trip is one flight out and one back.',
               [Measure('count', 'Flights')], _flight_dims(), [('travel', 'Flight date'), ('created', 'Trip posted')],
               _fetch_flights),
        Source('insurance', 'Travel insurance quote requests', 'Travel', 'fa-shield-heart',
               'Quote requests: the plan, citizenship, destination, trip length and travellers\' ages.',
               [Measure('count', 'Quote requests'), Measure('travellers', 'Travellers', kind='sum', field='n_travellers')],
               _insurance_dims(), [('created', 'Asked on'), ('travel', 'Travel starts')], _fetch_insurance),
        Source('sahayak', 'Sahayak bookings', 'Care', 'fa-house-medical',
               'Home-care bookings by service, status and age of the person cared for.',
               [Measure('count', 'Bookings')], _sahayak_dims(), [('created', 'Booked on'), ('visit', 'Visit date')],
               _fetch_sahayak),
        Source('enquiries', 'Website enquiries (contact forms)', 'Interest', 'fa-envelope-open-text',
               'Messages sent through the contact forms, by what they are about.',
               [Measure('count', 'Enquiries')], _enquiry_dims(), [('created', 'Sent on')], _fetch_enquiries),
        Source('reviews', 'Published reviews', 'Interest', 'fa-star',
               'Reviews somebody approved for the site, by service and stars.',
               [Measure('count', 'Reviews'), Measure('rating', 'Average rating', kind='avg', field='rating',
                                                      unit='rating', additive=False)],
               _review_dims(), [('created', 'Written on')], _fetch_reviews),
        Source('signups', 'Sign-ups (new accounts)', 'Interest', 'fa-user-plus',
               'Traveller accounts made, by how they were made.',
               [Measure('count', 'Sign-ups')], _signup_dims(), [('created', 'Made on')], _fetch_signups),
        Source('blog', 'Blog posts published', 'Interest', 'fa-pen-nib', 'Posts that went live on the blog.',
               [Measure('count', 'Posts')], [Dim('featured', 'Featured', lambda r: _yes(r['featured'], 'Featured',
                                                                                         'Not featured'), ordered=True)],
               [('published', 'Published on')], _fetch_blog),
        Source('leads', 'Leads (Sales CRM) – staff only', 'Sales', 'fa-filter-circle-dollar',
               'Leads that came in and how many were won, by product, source, campaign and country. Counts only, '
               'and only staff see them.',
               [Measure('count', 'Leads'), Measure('won', 'Won', kind='sum', field='won'),
                Measure('lost', 'Lost', kind='sum', field='lost'),
                Measure('win_rate', 'Win rate', kind='ratio', field='won', of='decided', unit='pct', additive=False)],
               _lead_dims(), [('created', 'Came in'), ('closed', 'Won or lost')], _fetch_leads, staff_only=True),
    ]
    return OrderedDict((s.key, s) for s in out)


def sources():
    """The catalogue, built once a request: the option lists it names (traveller needs) can be renamed any time."""
    from flask import g, has_app_context
    if not has_app_context():
        return _sources()
    if not hasattr(g, '_mkt_sources'):
        g._mkt_sources = _sources()
    return g._mkt_sources


def source(key):
    s = sources().get(key)
    if s is None:
        raise EngineError('Choose where the numbers come from.')
    return s


CHARTS = OrderedDict([
    ('number', ('Big number', 'fa-hashtag')), ('line', ('Line', 'fa-chart-line')), ('area', ('Area', 'fa-chart-area')),
    ('bar', ('Columns', 'fa-chart-column')), ('hbar', ('Bars (ranking)', 'fa-chart-bar')),
    ('stacked', ('Stacked columns', 'fa-layer-group')), ('pie', ('Pie', 'fa-chart-pie')),
    ('donut', ('Donut', 'fa-circle-notch')), ('table', ('Table', 'fa-table')), ('live', ('Live counter', 'fa-signal')),
    ('text', ('Words (a heading or a note)', 'fa-font')), ('quotes', ('Published reviews to quote', 'fa-quote-left')),
    ('links', ('Pages to send people to', 'fa-link')),
    ('people', ('Visitors one by one (staff only)', 'fa-users')),
    ('sitemaps', ('Our sitemaps in Google', 'fa-sitemap')),
    ('indexing', ("Our pages in Google's index", 'fa-list-check')),
    ('retention', ('Who came back, week by week', 'fa-arrows-rotate')),
])
# boxes that are not numbers of a source: words, reviews, links -- and four made their own way (SPECIAL_CHARTS)
NO_DATA_CHARTS = ('text', 'quotes', 'links', 'people', 'sitemaps', 'indexing', 'retention')
SPECIAL_CHARTS = ('people', 'sitemaps', 'indexing', 'retention')
# 'top' of a special box: visitors, pages, sitemaps -- and for 'retention' the weeks (each a row and a column)
SPECIAL_TOP = {'people': (1, 50, 12), 'indexing': (1, 30, 12), 'sitemaps': (1, 50, 20), 'retention': (2, 12, 6)}
RETENTION_OF = OrderedDict([('website', 'Google Analytics'), ('visitors', 'Our visitors')])
TIME_CHARTS = ('line', 'area', 'bar', 'stacked', 'table', 'number')
CAT_CHARTS = ('hbar', 'bar', 'stacked', 'pie', 'donut', 'table', 'number')
COLOURS = ('brand', 'ocean', 'sunset', 'forest', 'berry', 'mono')


def catalogue():
    """What the designer offers, as plain data for its script."""
    from app.services import ga4
    out = []
    for s in sources().values():
        out.append({'key': s.key, 'label': s.label, 'group': s.group, 'icon': s.icon, 'says': s.says,
                    'kind': s.kind, 'live': s.live, 'staff_only': s.staff_only,
                    'measures': [{'key': m.key, 'label': m.label, 'unit': m.unit} for m in s.measures.values()],
                    'dims': [{'key': d.key, 'label': d.label, 'multi': d.multi} for d in s.dims.values()],
                    'dates': [{'key': k, 'label': v} for k, v in s.dates.items()],
                    'grains': [{'key': g, 'label': GRAINS[g]} for g in s.grains]})
    return {'sources': out, 'charts': [{'key': k, 'label': v[0], 'icon': v[1]} for k, v in CHARTS.items()],
            'time_charts': TIME_CHARTS, 'cat_charts': CAT_CHARTS, 'no_data': NO_DATA_CHARTS,
            'ranges': [{'key': k, 'label': v} for k, v in RANGES.items()], 'colours': COLOURS,
            'ga_connected': ga4.connected(), 'search_connected': ga4.search_connected(), 'max_metrics': MAX_METRICS}


# ================================================================================================ a box, cleaned

def _str(v, n):
    return ' '.join(str(v or '').split())[:n]


def _clean_metric(raw):
    raw = raw if isinstance(raw, dict) else {}
    s = source(str(raw.get('source') or ''))
    measure = str(raw.get('measure') or '') or next(iter(s.measures))
    if measure not in s.measures:
        raise EngineError('"%s" does not have that measure. Choose one from the list.' % s.label)
    date_field = str(raw.get('date') or '') or next(iter(s.dates))
    if date_field not in s.dates:
        date_field = next(iter(s.dates))
    filters = {}
    for k, vals in (raw.get('filters') or {}).items() if isinstance(raw.get('filters'), dict) else ():
        if k not in s.dims:
            raise EngineError('"%s" cannot be narrowed by that.' % s.label)
        vals = [_str(v, 200) for v in (vals if isinstance(vals, (list, tuple)) else [vals]) if _str(v, 200)]
        if vals:
            filters[k] = vals[:50]
    return {'source': s.key, 'measure': measure, 'date': date_field, 'filters': filters,
            'label': _str(raw.get('label'), 60)}


def _int(v, lo, hi, default):
    try:
        n = int(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def clean_box(raw):
    raw = raw if isinstance(raw, dict) else {}
    chart = str(raw.get('chart') or 'number')
    if chart not in CHARTS:
        raise EngineError('Choose how the box is drawn.')
    box = {'id': _str(raw.get('id'), 20) or 'b', 'title': _str(raw.get('title'), 90), 'chart': chart,
           'note': _str(raw.get('note'), 200),
           'x': _int(raw.get('x'), 0, 11, 0), 'y': _int(raw.get('y'), 0, 400, 0),
           'w': _int(raw.get('w'), 1, 12, 4), 'h': _int(raw.get('h'), 1, 10, 3),
           'colour': raw.get('colour') if raw.get('colour') in COLOURS else 'brand'}
    box['w'] = min(box['w'], 12 - box['x'])
    if chart == 'text':
        box['body'] = str(raw.get('body') or '').strip()[:TEXT_MAX]
        return box
    if chart in ('quotes', 'links'):
        box['top'] = _int(raw.get('top'), 1, 20, 6)
        return box
    if chart in SPECIAL_CHARTS:
        lo, hi, default = SPECIAL_TOP[chart]
        box['top'] = _int(raw.get('top'), lo, hi, default)
        if chart == 'retention':
            box['of'] = raw.get('of') if raw.get('of') in RETENTION_OF else 'website'
        return box
    metrics = raw.get('metrics')
    if not isinstance(metrics, list) or not metrics:
        metrics = [{'source': raw.get('source'), 'measure': raw.get('measure'), 'filters': raw.get('filters'),
                    'date': raw.get('date')}]
    metrics = [_clean_metric(m) for m in metrics[:MAX_METRICS]]
    srcs = [source(m['source']) for m in metrics]
    first = srcs[0]
    group = str(raw.get('group') or '')
    split = str(raw.get('split') or '')
    if group:
        if group in GRAINS:
            for s in srcs:
                if group not in s.grains:
                    raise EngineError('"%s" cannot be shown by %s.' % (s.label, GRAINS[group].lower()) if s.grains
                                      else '"%s" is the last 30 minutes only: it has no days or months.' % s.label)
        elif group not in first.dims or any(group not in s.dims for s in srcs):
            raise EngineError('Every line in a box must be grouped by something they all have.')
    if split:
        if len(metrics) > 1:
            raise EngineError('A box with several numbers cannot be split again. Remove the split or the extra numbers.')
        if split not in first.dims or split == group:
            raise EngineError('Choose a different "split by", or none.')
    if len(srcs) > 1 and any(s.live for s in srcs):
        raise EngineError('The live numbers go in a box of their own.')
    if group and group not in GRAINS and len({s.kind for s in srcs}) > 1:
        raise EngineError('Website numbers and our own can share a box only when grouped by time.')
    rng = str(raw.get('range') or 'page')
    box.update(metrics=metrics, group=group, split=split, range=rng if rng in BOX_RANGES else 'page',
               top=_int(raw.get('top'), 0, MAX_TOP, 10), compare=bool(raw.get('compare', True)),
               empty=_str(raw.get('empty'), 120))
    if first.live:
        box['range'] = 'page'
    if chart == 'live' and not first.live:
        box['chart'] = 'number'
    return box


def describe(box):
    """A box's title when it was given none: "Trips by direction"."""
    if box.get('title'):
        return box['title']
    if box['chart'] in NO_DATA_CHARTS:
        return CHARTS[box['chart']][0]
    parts = []
    for m in box['metrics']:
        s = source(m['source'])
        parts.append(m['label'] or s.measures[m['measure']].label)
    text = ' and '.join(parts)
    if box['group']:
        if box['group'] == 'auto':
            text += ' over time'
        elif box['group'] in GRAINS:
            text += ' by ' + GRAINS[box['group']].lower()
        else:
            text += ' by ' + source(box['metrics'][0]['source']).dims[box['group']].label.lower()
    if box.get('split'):
        text += ', split by ' + source(box['metrics'][0]['source']).dims[box['split']].label.lower()
    return text


# ================================================================================================ running a box

def _keep(src, row, filters):
    for k, allowed in filters.items():
        d = src.dims[k]
        labels = {lbl for _, lbl in d.keys(row)}
        if not labels & set(allowed):
            return False
    return True


def _change(now, before):
    if before in (None, 0) or now is None:
        return None
    try:
        return round((float(now) - float(before)) * 100.0 / float(before), 1)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def run(box, period, viewer=None, compare=None):
    """The numbers of a cleaned box for `period` (the dashboard's dates, used when the box's range is 'page')."""
    from app.services import ga4
    if box['chart'] in SPECIAL_CHARTS:
        try:
            return _run_special(box, viewer)
        except ga4.GAError as e:
            return {'ok': False, 'message': str(e), 'ga': True}
    if box['chart'] in NO_DATA_CHARTS:
        return {'ok': True, 'kind': box['chart']}
    p = period if box['range'] == 'page' else period_for(box['range'])
    srcs = [source(m['source']) for m in box['metrics']]
    if any(s.staff_only for s in srcs) and not _staff(viewer):
        return {'ok': False, 'hidden': True, 'message': 'Only staff see the numbers in this box.'}
    want_prev = box.get('compare', True) if compare is None else compare
    grain = box['group'] if box['group'] in GRAINS else None
    if grain:
        grain = fit_grain(p, grain)
    try:
        parts = _parts(srcs, box, p, grain, want_prev)
    except ga4.GAError as e:
        return {'ok': False, 'message': str(e), 'ga': True}
    first = srcs[0].measures[box['metrics'][0]['measure']]
    out = {'ok': True, 'kind': 'data', 'unit': first.unit, 'time': bool(grain), 'grain': grain,
           'period': p.as_dict(), 'live': srcs[0].live, 'lower_better': first.lower_better, 'notes': []}
    if srcs[0].live and srcs[0].kind == 'db':
        from app.services import visitors
        out['live_words'] = 'right now'
        if box['chart'] == 'live':
            out['minutes'] = visitors.minutes()
    for part in parts:
        out['notes'] += [n for n in part.get('notes', ()) if n not in out['notes']]
    if grain and box['group'] not in ('auto', grain):
        out['notes'].append('Shown by %s: %d %ss would not fit.' % (grain, len(buckets(p, box['group'])), box['group']))
    if len(parts) == 1:
        part = parts[0]
        out.update(labels=part['labels'], series=part['series'], total=part['total'], prev=part['prev'],
                   change=_change(part['total'], part['prev']))
        _row_change(out, part)
    else:
        labels = parts[0]['labels']
        if not grain:
            seen = list(labels)
            for part in parts[1:]:
                seen += [lb for lb in part['labels'] if lb not in seen]
            labels = seen
        series = []
        for m, s, part in zip(box['metrics'], srcs, parts):
            by = dict(zip(part['labels'], part['series'][0]['data'])) if part['series'] else {}
            series.append({'name': m['label'] or s.measures[m['measure']].label,
                           'data': [by.get(lb, 0) for lb in labels], 'total': part['total'],
                           'prev': part['prev'], 'change': _change(part['total'], part['prev']),
                           'unit': s.measures[m['measure']].unit})
        out.update(labels=labels, series=series, total=parts[0]['total'], prev=parts[0]['prev'],
                   change=_change(parts[0]['total'], parts[0]['prev']), multi=True)
        if labels == parts[0]['labels']:
            _row_change(out, parts[0])
    out['empty'] = not any(any(v for v in (s['data'] or []) if v) for s in out['series']) and not out['total']
    out['rows'] = _table_rows(out)
    return out


def _parts(srcs, box, p, grain, want_prev):
    """One part a number. Several numbers of one Google source with the same filters are one question to Google, so a
    table's columns describe the same rows: the top pages by views, and those same pages' visitors."""
    metrics, s0 = box['metrics'], srcs[0]
    if (len(metrics) > 1 and s0.kind in _GOOGLE and all(s.key == s0.key for s in srcs)
            and all(m['filters'] == metrics[0]['filters'] for m in metrics)):
        return _GOOGLE[s0.kind](s0, metrics, box, p, grain, want_prev and not s0.live)
    out = []
    for s, m in zip(srcs, metrics):
        if s.kind in _GOOGLE:
            out += _GOOGLE[s.kind](s, [m], box, p, grain, want_prev and not s.live)
        else:
            out.append(_run_db(s, m, box, p, grain, want_prev and not s.live))
    return out


def _row_change(out, part):
    """Each group's own change on the days before (the first number's): which pages, searches or countries grew."""
    before = part.get('row_prev')
    if before is None or not part['series']:
        return
    out['row_prev'] = before
    out['row_change'] = [_change(v, b) for v, b in zip(part['series'][0]['data'], before)]


def _staff(viewer):
    from app.services import access
    return viewer is not None and access.is_staff(viewer)


def _table_rows(out):
    rows = []
    for i, lb in enumerate(out['labels']):
        vals = [s['data'][i] if i < len(s['data']) else 0 for s in out['series']]
        rows.append({'label': lb, 'values': vals})
    return rows


def _group_rows(src, rows, key, grain, p):
    """{(sort, label): [rows]} by the group (a dimension or a time grain), and the ordered keys."""
    groups = defaultdict(list)
    if grain:
        for r in rows:
            groups[bucket(r['_when'], grain)].append(r)
        return groups, buckets(p, grain), lambda k: bucket_label(k, grain)
    if not key:
        groups[(0, 'All')] = rows
        return groups, [(0, 'All')], lambda k: k[1]
    d = src.dims[key]
    for r in rows:
        for k in d.keys(r):
            groups[k].append(r)
    return groups, None, lambda k: k[1]


def _run_db(src, metric, box, p, grain, want_prev):
    if src.live:
        p = Period(today(), today(), 'now')          # what is so this minute, whatever the dashboard's dates
    span = Period(p.previous().start, p.end) if want_prev else p
    rows = [r for r in src.fetch(span, metric['date']) if _keep(src, r, metric['filters'])]
    cur = [r for r in rows if p.start <= r['_when'] <= p.end]
    m = src.measures[metric['measure']]
    prev = old = None
    if want_prev:
        pp = p.previous()
        old = [r for r in rows if pp.start <= r['_when'] <= pp.end]
        prev = m.value(old)
    total = m.value(cur)
    group = box['group']
    groups, order, name = _group_rows(src, cur, group if not grain else None, grain, p)
    d = src.dims.get(group) if group and not grain else None
    if order is None:
        if d is not None and d.ordered:
            order = sorted(set(groups) | set(d.fill))
        else:
            order = sorted(groups, key=lambda k: (-(m.value(groups[k]) or 0), k[1]))
        top = box.get('top') or 0
        if top and len(order) > top and not (d is not None and d.fill):
            rest = [r for k in order[top:] for r in groups[k]]
            order = order[:top]
            if m.additive and box['chart'] in ('pie', 'donut', 'stacked') and rest:
                groups[(10 ** 7, OTHERS)] = rest
                order.append((10 ** 7, OTHERS))
    labels = [name(k) for k in order]
    split = box.get('split')
    if split:
        sd = src.dims[split]
        tot = defaultdict(list)
        for r in cur:
            for k in sd.keys(r):
                tot[k].append(r)
        keys = sorted(tot) if sd.ordered else sorted(tot, key=lambda k: (-(m.value(tot[k]) or 0), k[1]))
        keys, extra = keys[:MAX_SPLITS], keys[MAX_SPLITS:]
        series = []
        for sk in keys:
            data = []
            for k in order:
                data.append(m.value([r for r in groups.get(k, []) if sk in sd.keys(r)]) or 0)
            series.append({'name': sk[1], 'data': data})
        if extra and m.additive:
            data = [m.value([r for r in groups.get(k, []) if any(e in sd.keys(r) for e in extra)]) or 0 for k in order]
            series.append({'name': OTHERS, 'data': data})
    else:
        series = [{'name': metric['label'] or m.label, 'data': [m.value(groups.get(k, [])) or 0 for k in order]}]
    out = {'labels': labels, 'series': series, 'total': total, 'prev': prev}
    if old is not None and d is not None and not split:
        before = defaultdict(list)
        for r in old:
            for k in d.keys(r):
                before[k].append(r)
        out['row_prev'] = [None if k[1] == OTHERS else (m.value(before.get(k, [])) or 0) for k in order]
    return out


_NOT_SET = ('(not set)', '(other)', '', 'unknown', '(data not available)')


def _ga_label(dim, value):
    if value in _NOT_SET or value is None:
        return NOT_KNOWN
    if dim in ('deviceCategory', 'userGender', 'platform'):
        return value.capitalize() if dim != 'platform' else value
    if dim == 'newVsReturning':
        return {'new': 'New visitors', 'returning': 'Returning visitors'}.get(value, value.capitalize())
    if dim == 'hour':
        try:
            return HOURS[int(value)][1]
        except (ValueError, IndexError):
            return NOT_KNOWN
    if dim == 'percentScrolled':
        return '%s%%' % value
    return value


def _ga_natural(group, keys):
    """The groups of a dimension with an order of its own: every hour, every day of the week, ages youngest first."""
    if group == 'hour':
        return [lb for _, lb in HOURS]
    if group == 'weekday':
        return list(WEEKDAYS)
    return sorted(keys, key=lambda k: (k == NOT_KNOWN, len(k) if group == 'scrolled' else 0, k))


def _ga_bucket(grain, value):
    try:
        if grain == 'day':
            return datetime.strptime(value, '%Y%m%d').date()
        if grain == 'week':
            return datetime.strptime(value + '-1', '%G%V-%u').date()
        if grain == 'month':
            return (int(value[:4]), int(value[4:6]))
        return int(value)
    except (TypeError, ValueError):
        return None


def _ga_names(ms):
    """The GA numbers to ask for: each measure's own, or the two a worked-out one is made of."""
    return list(OrderedDict.fromkeys(n for m in ms for n in (m.ga or (m.key,))))


def _ga_val(m, vals):
    if not vals:
        return 0
    if m.ga:
        num, den = vals.get(m.ga[0]) or 0, vals.get(m.ga[1]) or 0
        return round(num / den, 4) if den else 0
    return vals.get(m.key) or 0


def _run_ga(src, metrics, box, p, grain, want_prev):
    """Google Analytics: every number of the box in one report, so its columns describe the same rows."""
    from app.services import ga4
    ms = [src.measures[x['measure']] for x in metrics]
    names = _ga_names(ms)
    filters = {src.ga_dims[k][1]: v for k, v in metrics[0]['filters'].items()}
    group, split = box['group'], box.get('split')
    cat = bool(group) and group not in GRAINS
    if src.live:
        dims = ([src.ga_dims[group][1]] if cat else []) + ([src.ga_dims[split][1]] if split else [])
        data = ga4.realtime(names, dims, limit=250, filters=filters)
        return _ga_shape(src, ms, metrics, box, data, dims, names, None, None, None, False)
    dims = []
    if grain:
        dims.append(GA_GRAIN[grain])
    elif group:
        dims.append(src.ga_dims[group][1])
    if split:
        dims.append(src.ga_dims[split][1])
    top = box.get('top') or 0
    natural = cat and src.dims[group].ordered
    limit = 10000 if (grain or split or natural) else (max(top, 1) if top else 1000)
    order = None if (grain or natural) else ('metric', names[0], True)
    data = ga4.report(p.start, p.end, names, dims, limit=limit, order=order, filters=filters)
    old, by_row = None, cat and not split
    if want_prev:
        pp = p.previous()
        if by_row:
            # the days before, by the same groups: each row's own change
            old = ga4.report(pp.start, pp.end, names, dims, limit=max(limit, 250), order=order, filters=filters)
        else:
            old = ga4.report(pp.start, pp.end, names, [], limit=1, filters=filters)
    return _ga_shape(src, ms, metrics, box, data, dims, names, grain, p, old, by_row)


def _ga_shape(src, ms, metrics, box, data, dims, names, grain, p, old, by_row):
    group, split = box['group'], box.get('split')
    nd = len(dims)
    gdim = dims[0] if dims and (grain or (group and group not in GRAINS)) else None
    sdim = dims[-1] if split else None
    # what adds up when two of GA's rows land in one group of ours ("(not set)" and "" are both "Not known")
    adds = {n for m in ms for n in (m.ga or ((m.key,) if m.additive else ()))}

    def put(acc, vals, first):
        for n, v in zip(names, vals):
            if first or n in adds:
                acc[n] = (0 if first else acc.get(n, 0)) + (v or 0)

    cells, gsum, ssum = {}, {}, {}
    gkeys, skeys = [], []
    for row in data['rows']:
        if gdim:
            gk = _ga_bucket(grain, row[0]) if grain else _ga_label(gdim, row[0])
            if gk is None:
                continue
        else:
            gk = 'All'
        sk = _ga_label(sdim, row[nd - 1]) if sdim else None
        vals = row[nd:]
        if gk not in gsum:
            gkeys.append(gk)
        if sk is not None and sk not in ssum:
            skeys.append(sk)
        for store, k in ((cells, (gk, sk)), (gsum, gk)) + (((ssum, sk),) if sk is not None else ()):
            first = k not in store
            put(store.setdefault(k, {}), vals, first)

    def whole(d):
        if d and d.get('totals'):
            return dict(zip(names, d['totals']))
        acc = {}
        for i, row in enumerate((d or {}).get('rows') or []):
            put(acc, row[len(row) - len(names):], i == 0)
        return acc
    totals = [_ga_val(m, whole(data)) for m in ms]
    prevs = [_ga_val(m, whole(old)) for m in ms] if old is not None else [None] * len(ms)
    if grain:
        order = buckets(p, grain)
        labels = [bucket_label(k, grain) for k in order]
    else:
        if gdim and src.dims[group].ordered:
            order = _ga_natural(group, gkeys)
        else:
            order = sorted(gkeys, key=lambda k: -(_ga_val(ms[0], gsum[k]) or 0)) if gkeys else ([] if gdim else ['All'])
            top = box.get('top') or 0
            if top and len(order) > top:
                order = order[:top]
        labels = list(order)
    if split:
        m = ms[0]
        skeys = sorted(skeys, key=lambda k: -(_ga_val(m, ssum[k]) or 0))[:MAX_SPLITS]
        series = [{'name': sk, 'data': [_round(_ga_val(m, cells.get((gk, sk)))) for gk in order]} for sk in skeys]
        return [{'labels': labels, 'series': series, 'total': _round(totals[0]), 'prev': _round(prevs[0])}]
    before = None
    if by_row and old is not None:
        before = {}
        for row in old['rows']:
            k = _ga_label(gdim, row[0])
            first = k not in before
            put(before.setdefault(k, {}), row[nd:], first)
    parts = []
    for i, (m, x) in enumerate(zip(ms, metrics)):
        part = {'labels': labels, 'total': _round(totals[i]), 'prev': _round(prevs[i]),
                'series': [{'name': x['label'] or m.label,
                            'data': [_round(_ga_val(m, cells.get((gk, None)))) for gk in order]}]}
        if before is not None:
            part['row_prev'] = [_round(_ga_val(m, before.get(gk))) for gk in order]
        parts.append(part)
    return parts


class _Acc:
    """Search Console numbers of a group: clicks and times shown add up; the position is weighted by times shown."""
    __slots__ = ('clicks', 'shown', 'pos_w')

    def __init__(self):
        self.clicks = self.shown = self.pos_w = 0.0

    def add(self, clicks, shown, position):
        self.clicks += clicks or 0
        self.shown += shown or 0
        self.pos_w += (position or 0) * (shown or 0)

    def value(self, mk):
        if mk == 'clicks':
            return int(self.clicks)
        if mk == 'impressions':
            return int(self.shown)
        if not self.shown:
            return None
        if mk == 'ctr':
            return round(self.clicks / self.shown, 4)
        return round(self.pos_w / self.shown, 1)


GSC_BAND_ORDER = {label: i for i, (_, label) in enumerate(GSC_BANDS)}


def _gsc_band(position):
    for edge, label in GSC_BANDS:
        if edge is None or (position or 0) <= edge:
            return label
    return GSC_BANDS[-1][1]


def _gsc_label(dim, value):
    if dim == 'country':
        code = str(value or '').upper()
        return _iso3_names().get(code) or code or NOT_KNOWN
    if dim == 'device':
        return str(value or '').capitalize() or NOT_KNOWN
    if dim == 'searchAppearance':
        v = str(value or '')
        return GSC_APPEARANCE.get(v) or v.replace('_', ' ').capitalize() or NOT_KNOWN
    return value or NOT_KNOWN


def _gsc_values(dim, values):
    """The labels a filter chose, as Search Console spells them: a country's ISO-3 code, a device in capitals."""
    if dim == 'country':
        codes = {name.lower(): code.lower() for code, name in _iso3_names().items()}
        return [codes.get(v.lower(), v.lower()) for v in values]
    if dim == 'device':
        return [v.upper() for v in values]
    if dim == 'searchAppearance':
        codes = {label.lower(): code for code, label in GSC_APPEARANCE.items()}
        return [codes.get(v.lower(), v.upper().replace(' ', '_')) for v in values]
    return list(values)


def _gsc_ask(src, raw, group, split, grain):
    """What to ask Search Console: the request's dimensions and filters, the kinds of search, the position bands."""
    ours = ('type', 'band')
    filters = {src.gsc_dims[k][1]: _gsc_values(src.gsc_dims[k][1], v) for k, v in raw.items() if k not in ours}
    chosen = raw.get('type') or ()
    if chosen:
        types = [k for k, lb in GSC_TYPES.items() if lb in chosen] or ['web']
    elif 'type' in (group, split):
        types = list(GSC_TYPES)
    else:
        types = ['web']
    bands = set(raw.get('band') or ())
    keys = []
    if grain:
        keys.append('date')
    elif group and group not in ours:
        keys.append(src.gsc_dims[group][1])
    if split and split not in ours:
        keys.append(src.gsc_dims[split][1])
    want_band = 'band' in (group, split) or bool(bands)
    if want_band and not {'query', 'page'} & set(keys):
        keys.append('query')          # a band is where one search came; days or countries have no place of their own
    return {'keys': keys, 'filters': filters, 'types': types, 'bands': bands, 'band': want_band}


def _gsc_collect(src, q, ask, group, split, grain, rows=True):
    """Search Console's answers for one period, added up by the box's groups: {'cells', 'g', 's', 'whole', 'notes'}."""
    from app.services import ga4, gsc
    keys, bands = ask['keys'], ask['bands']
    cells, gacc, sacc, whole = defaultdict(_Acc), defaultdict(_Acc), defaultdict(_Acc), _Acc()
    missing = []
    need_rows = bool(keys) and (rows or bands)
    for kind in ask['types']:
        try:
            got = gsc.query(q.start, q.end, keys, ask['filters'], limit=gsc.MAX_ROWS, kind=kind) if need_rows else []
            tot = [] if bands else gsc.query(q.start, q.end, [], ask['filters'], limit=1, kind=kind)
        except ga4.GAError:
            if len(ask['types']) == 1:
                raise
            missing.append(GSC_TYPES[kind])
            continue
        for r in tot:
            whole.add(*r[-3:])
        if not rows and not bands:
            continue
        kind_label = GSC_TYPES[kind]
        for row in (got if keys else tot):
            vals = dict(zip(keys, row[:len(keys)]))
            band = _gsc_band(row[-1]) if ask['band'] else None
            if bands and band not in bands:
                continue

            def key_of(k):
                if k == 'type':
                    return kind_label
                if k == 'band':
                    return band
                name = src.gsc_dims[k][1]
                return _gsc_label(name, vals.get(name))
            if grain:
                try:
                    gk = bucket(datetime.strptime(vals['date'], '%Y-%m-%d').date(), grain)
                except (ValueError, KeyError):
                    continue
            else:
                gk = key_of(group) if group else 'All'
            sk = key_of(split) if split else None
            accs = [cells[(gk, sk)], gacc[gk]] + ([sacc[sk]] if split else []) + ([whole] if bands else [])
            for acc in accs:
                acc.add(*row[-3:])
    notes = ['Google has no numbers for: %s.' % ', '.join(missing)] if missing else []
    return {'cells': cells, 'g': gacc, 's': sacc, 'whole': whole, 'notes': notes}


def _run_gsc(src, metrics, box, p, grain, want_prev):
    """Google Search Console: every number of the box from the same answers (clicks, times shown and position come
    together), added up here by day, week or month, kind of search and where we came."""
    from app.services import gsc
    t = today()
    oldest = t - timedelta(days=gsc.KEEPS_DAYS - 1)
    notes = []
    q = Period(max(p.start, oldest), max(min(p.end, t), oldest), p.key)
    if p.start < oldest:
        notes.append('Google keeps 16 months of search numbers: these start on %s.' % day_range(q.start, q.start))
    ms = [src.measures[x['measure']] for x in metrics]
    mk0 = ms[0].key
    group, split = box['group'], box.get('split')
    ask = _gsc_ask(src, metrics[0]['filters'], group, split, grain)
    now = _gsc_collect(src, q, ask, group, split, grain)
    notes += now['notes']
    by_row = bool(group) and group not in GRAINS and not split
    before = None
    if want_prev:
        pp = q.previous()
        if pp.end >= oldest:
            before = _gsc_collect(src, Period(max(pp.start, oldest), pp.end), ask, group, split, grain, rows=by_row)

    # biggest first; a rate or a position is ranked by how often Google showed the group
    def rank(accs):
        return lambda k: (-(accs[k].value(mk0) or 0) if ms[0].additive else -accs[k].shown, str(k))
    gacc, cells = now['g'], now['cells']
    if grain:
        order = buckets(p, grain)
        labels = [bucket_label(k, grain) for k in order]
    elif group:
        if group == 'band':
            order = sorted(gacc, key=lambda k: GSC_BAND_ORDER.get(k, 99))
        else:
            order = sorted(gacc, key=rank(gacc))
            top = box.get('top') or 0
            order = order[:top] if top else order
        labels = list(order)
    else:
        order, labels = ['All'], ['All']
    if q.end >= t - timedelta(days=2):
        notes.append("Google's newest two or three days are still coming in.")
    if split:
        skeys = sorted(now['s'], key=rank(now['s']))[:MAX_SPLITS]
        series = [{'name': sk, 'data': [cells[(gk, sk)].value(mk0) or 0 for gk in order]} for sk in skeys]
        return [{'labels': labels, 'series': series, 'total': now['whole'].value(mk0),
                 'prev': before['whole'].value(mk0) if before else None, 'notes': notes}]
    parts = []
    for m, x in zip(ms, metrics):
        part = {'labels': labels, 'notes': notes, 'total': now['whole'].value(m.key),
                'prev': before['whole'].value(m.key) if before else None,
                'series': [{'name': x['label'] or m.label,
                            'data': [cells[(gk, None)].value(m.key) or 0 for gk in order]}]}
        if before is not None and by_row:
            part['row_prev'] = [before['g'][gk].value(m.key) if gk in before['g'] else 0 for gk in order]
        parts.append(part)
    return parts


_GOOGLE = {'ga': _run_ga, 'gsc': _run_gsc}


# ================================================================================================ the lists

def _ist_text(dt):
    return (dt + IST).strftime('%d %b, %H:%M').lstrip('0') if dt else ''


def _run_special(box, viewer):
    from app.services import gsc
    if box['chart'] == 'people':
        return _run_people(box, viewer)
    if box['chart'] == 'sitemaps':
        return {'ok': True, 'kind': 'sitemaps', 'rows': gsc.sitemaps()[:box.get('top') or 20]}
    if box['chart'] == 'retention':
        return _run_retention(box)
    return dict(gsc.indexing(box.get('top') or 12), ok=True, kind='indexing')


def _run_retention(box):
    """Google Analytics' Retention report: of the people who first came in each of the last weeks, how many came
    again in each week after. Of the website (Google's weeks begin on Sunday, as its own report's) or of our own
    visitors (Monday, as the rest of the dashboard's weeks)."""
    weeks, of, t = box.get('top') or 6, box.get('of') or 'website', today()
    back = (t.weekday() + 1) % 7 if of == 'website' else t.weekday()
    starts = [t - timedelta(days=back) - timedelta(weeks=n) for n in range(weeks - 1, -1, -1)]
    if of == 'visitors':
        found = _visitor_cohorts(starts)
    else:
        from app.services import ga4
        found = ga4.cohorts(starts, weeks)
    rows, kept, came = [], [0] * (weeks - 1), [0] * (weeks - 1)
    for s in starts:
        size, active = found.get(s, (0, {}))
        cells = []
        for n in range(1, weeks):
            if s + timedelta(weeks=n) > t:             # that week has not begun
                cells.append(None)
                continue
            a = active.get(n, 0)
            cells.append({'n': a, 'pct': round(a * 100.0 / size, 1) if size else None})
            if size:
                kept[n - 1] += size
                came[n - 1] += a
        rows.append({'label': '%d %s' % (s.day, s.strftime('%b')), 'start': s.isoformat(), 'size': size,
                     'cells': cells})
    while len(rows) > 1 and not rows[0]['size']:      # weeks before anybody was recorded (our own began 2026-10)
        rows.pop(0)
    average = [round(c * 100.0 / k, 1) if k else None for c, k in zip(came, kept)]
    return {'ok': True, 'kind': 'retention', 'of': of, 'weeks': weeks, 'rows': rows, 'average': average,
            'size': sum(r['size'] for r in rows), 'starts_on': 'Sunday' if of == 'website' else 'Monday',
            'empty': not any(r['size'] for r in rows)}


def _visitor_cohorts(starts):
    """{week's Monday: (visitors first seen that week, {n: of them, those who opened a page n weeks later})}, our
    own visitors (India time). A browser is a visitor, as everywhere on the dashboard."""
    from app.models import CrmVisitor as V, CrmVisitorPage as P
    since = datetime.combine(starts[0], datetime.min.time()) - IST
    first = {vid: bucket((at + IST).date(), 'week') for vid, at in
             db.session.query(V.id, V.first_at).filter(V.first_at >= since).limit(ROW_LIMIT)}
    sizes, active = defaultdict(int), defaultdict(lambda: defaultdict(set))
    for c in first.values():
        sizes[c] += 1
    q = (db.session.query(P.visitor_id, P.at).join(V, V.id == P.visitor_id)
         .filter(V.first_at >= since, P.at >= since).limit(ROW_LIMIT))
    for vid, at in q:
        c = first.get(vid)
        if c is not None:
            active[c][((at + IST).date() - c).days // 7].add(vid)
    return {c: (sizes[c], {n: len(v) for n, v in active[c].items()}) for c in starts}


def _run_people(box, viewer):
    """Visitors one by one -- those on the site now, then the latest -- for staff: where they are, their device, how
    they found us, the page they are on. Their internet address is shown in part to a role that masks contact
    details; never a name, even of a visitor who chatted."""
    from flask import url_for
    from app.services import access, role_rights, visitors
    if not _staff(viewer):
        return {'ok': False, 'hidden': True, 'message': 'Only staff see visitors one by one.'}
    now = datetime.utcnow()
    masked = role_rights.masks(viewer)
    top = box.get('top') or 12
    here = visitors.now_list(now)
    rows = here[:top] + visitors.latest(top - len(here[:top]), [r['v'].id for r in here], now)
    page = url_for('messaging.visitors_page') if access.can(viewer, 'web_visitors') else None
    out = []
    for r in rows:
        v = r['v']
        out.append({'id': v.id, 'ip': visitors.show_ip(v.ip, masked), 'code': v.country_code or '',
                    'place': r['place'], 'device': visitors.DEVICE_WORD.get(v.device, 'Computer'),
                    'icon': visitors.DEVICE_ICON.get(v.device, 'fa-desktop'), 'browser': v.browser or '',
                    'os': v.os or '', 'source': v.source or visitors.DIRECT, 'campaign': v.campaign or '',
                    'page': v.page_title or _path(v.page_url) or '', 'url': v.page_url or '', 'visits': v.visits,
                    'pages': v.pages, 'here': r['here'], 'chatted': r['chatted'],
                    'on_for': visitors.secs_words(r['on_for']) if r['on_for'] is not None else '',
                    'seen': _ist_text(v.last_at), 'open': ('%s?v=%d' % (page, v.id)) if page else None})
    return {'ok': True, 'kind': 'people', 'rows': out, 'now': len(here), 'masked': masked, 'all_url': page,
            'live': True}


def _round(v):
    if v is None:
        return None
    if isinstance(v, float):
        return int(v) if v.is_integer() else round(v, 4)
    return v


# ================================================================================================ filter values

def options(source_key, dim_key, limit=100):
    """The values a filter can choose, most common first (the last year's)."""
    from app.services import ga4
    s = source(source_key)
    if dim_key not in s.dims:
        raise EngineError('That cannot be used to narrow "%s".' % s.label)
    p = period_for('last_365')
    if s.kind == 'gsc':
        from app.services import gsc
        if dim_key == 'type':
            return list(GSC_TYPES.values())
        if dim_key == 'band':
            return [label for _, label in GSC_BANDS]
        name = s.gsc_dims[dim_key][1]
        rows = gsc.query(today() - timedelta(days=89), today(), [name], limit=limit)
        return [_gsc_label(name, r[0]) for r in sorted(rows, key=lambda r: -r[1])]
    if s.kind == 'ga':
        name = s.ga_dims[dim_key][1]
        if s.live:
            data = ga4.realtime(['activeUsers'], [name], limit=limit)
        else:
            data = ga4.report(p.start, p.end, ['activeUsers'], [name], limit=limit,
                              order=('metric', 'activeUsers', True))
        return [row[0] for row in data['rows'] if row[0] not in ('(not set)', '')]
    d = s.dims[dim_key]
    counts = defaultdict(int)
    for r in s.fetch(period_for('all'), next(iter(s.dates))):
        for _, lb in d.keys(r):
            counts[lb] += 1
    if dim_key == 'direction':
        return [x for x in DIRECTIONS if x in counts] + [x for x in DIRECTIONS if x not in counts]
    return [k for k, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))][:limit]
