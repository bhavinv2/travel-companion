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
    """kind: count | sum (of a field) | avg (of a field) | ratio (sum of `field` / sum of `of`)."""

    def __init__(self, key, label, kind='count', field=None, of=None, unit='count', additive=True, lower_better=False):
        self.key, self.label, self.kind, self.field, self.of, self.unit = key, label, kind, field, of, unit
        self.additive = additive and kind in ('count', 'sum')
        # a smaller number is the good news (an average position, a bounce rate): the change is coloured the other way
        self.lower_better = lower_better

    def value(self, rows):
        if self.kind == 'count':
            return len(rows)
        if self.kind == 'sum':
            return sum((r.get(self.field) or 0) for r in rows)
        if self.kind == 'avg':
            vals = [r[self.field] for r in rows if r.get(self.field) is not None]
            return round(sum(vals) / len(vals), 2) if vals else None
        num = sum((r.get(self.field) or 0) for r in rows)
        den = sum((r.get(self.of) or 0) for r in rows)
        return round(num / den, 4) if den else None


class Dim:
    """fn(row) -> (sort key, label); `multi`: fn returns a list (a trip with two needs counts under each);
    `ordered`: the groups keep their natural order instead of biggest first."""

    def __init__(self, key, label, fn, multi=False, ordered=False):
        self.key, self.label, self.fn, self.multi, self.ordered = key, label, fn, multi, ordered

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
        """Rows with '_when' (the India day of `date_field`) inside the period."""
        return self._fetch(period, date_field)


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


# ------------------------------------------------------------------------------------------------ the website

class GASource(Source):
    """Google Analytics 4. Measures are GA metrics, dimensions GA dimensions; the time grains are GA's own
    (`date`, `isoYearIsoWeek`, `yearMonth`, `year`) so a month's visitors are counted once, not summed per day."""
    kind = 'ga'
    grains = ('auto', 'day', 'week', 'month', 'year')

    def __init__(self, key, label, group, icon, says, metrics, dims, live=False):
        super().__init__(key, label, group, icon, says, metrics, [], [('visit', 'Visited')], None)
        self.ga_dims = OrderedDict(dims)
        self.dims = OrderedDict((k, Dim(k, v[0], None)) for k, v in dims.items())
        self.live = live
        if live:
            self.grains = ()
            self.dates = OrderedDict([('now', 'The last 30 minutes')])


GA_GRAIN = {'day': 'date', 'week': 'isoYearIsoWeek', 'month': 'yearMonth', 'year': 'year'}

GA_METRICS = [
    Measure('activeUsers', 'Visitors', additive=False), Measure('newUsers', 'New visitors'),
    Measure('sessions', 'Visits'), Measure('screenPageViews', 'Page views'),
    Measure('engagedSessions', 'Engaged visits'),
    Measure('engagementRate', 'Engagement rate', kind='avg', unit='pct', additive=False),
    Measure('averageSessionDuration', 'Average visit length', kind='avg', unit='seconds', additive=False),
    Measure('bounceRate', 'Bounce rate', kind='avg', unit='pct', additive=False, lower_better=True),
    Measure('keyEvents', 'Key events (conversions)'), Measure('eventCount', 'Events'),
]
GA_DIMS = OrderedDict([
    ('country', ('Country', 'country')), ('city', ('City', 'city')), ('region', ('State or region', 'region')),
    ('device', ('Device', 'deviceCategory')), ('channel', ('Channel', 'sessionDefaultChannelGroup')),
    ('source', ('Source', 'sessionSource')), ('medium', ('Medium', 'sessionMedium')),
    ('source_medium', ('Source / medium', 'sessionSourceMedium')), ('campaign', ('Campaign', 'sessionCampaignName')),
    ('landing', ('Landing page', 'landingPage')), ('page', ('Page', 'pagePath')), ('title', ('Page title', 'pageTitle')),
    ('site', ('Website (host name)', 'hostName')), ('returning', ('New or returning', 'newVsReturning')),
    ('browser', ('Browser', 'browser')), ('os', ('Operating system', 'operatingSystem')),
    ('language', ('Language', 'language')), ('first_channel', ("First visit's channel", 'firstUserDefaultChannelGroup')),
])
GA_LIVE_METRICS = [Measure('activeUsers', 'People on the site', additive=False), Measure('screenPageViews', 'Page views'),
                   Measure('eventCount', 'Events'), Measure('keyEvents', 'Key events (conversions)')]
GA_LIVE_DIMS = OrderedDict([
    ('country', ('Country', 'country')), ('city', ('City', 'city')), ('device', ('Device', 'deviceCategory')),
    ('page', ('Page', 'unifiedScreenName')), ('minutes', ('Minutes ago', 'minutesAgo')),
    ('audience', ('Audience', 'audienceName')),
])


class GSCSource(Source):
    """Google Search Console: Google search results that showed one of our pages. Its only time is the day, so weeks,
    months and the rest are added up here (clicks and times shown add up; the click rate and the position are worked
    out again from them, the position weighted by how often each page was shown)."""
    kind = 'gsc'

    def __init__(self, key, label, group, icon, says, metrics, dims):
        super().__init__(key, label, group, icon, says, metrics, [], [('search', 'Searched on')], None)
        self.gsc_dims = OrderedDict(dims)
        self.dims = OrderedDict((k, Dim(k, v[0], None)) for k, v in dims.items())


GSC_METRICS = [
    Measure('clicks', 'Clicks from Google'), Measure('impressions', 'Times shown in Google'),
    Measure('ctr', 'Click rate', kind='avg', unit='pct', additive=False),
    Measure('position', 'Average position', kind='avg', unit='position', additive=False, lower_better=True),
]
GSC_DIMS = OrderedDict([
    ('query', ('Words people searched', 'query')), ('page', ('Page Google showed', 'page')),
    ('country', ('Country', 'country')), ('device', ('Device', 'device')),
])


# ------------------------------------------------------------------------------------------------ the catalogue

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
])
NO_DATA_CHARTS = ('text', 'quotes', 'links')
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
        parts = [{'ga': _run_ga, 'gsc': _run_gsc}.get(s.kind, _run_db)(s, m, box, p, grain, want_prev and not s.live)
                 for s, m in zip(srcs, box['metrics'])]
    except ga4.GAError as e:
        return {'ok': False, 'message': str(e), 'ga': True}
    first = srcs[0].measures[box['metrics'][0]['measure']]
    out = {'ok': True, 'kind': 'data', 'unit': first.unit, 'time': bool(grain), 'grain': grain,
           'period': p.as_dict(), 'live': srcs[0].live, 'lower_better': first.lower_better, 'notes': []}
    for part in parts:
        out['notes'] += [n for n in part.get('notes', ()) if n not in out['notes']]
    if grain and box['group'] not in ('auto', grain):
        out['notes'].append('Shown by %s: %d %ss would not fit.' % (grain, len(buckets(p, box['group'])), box['group']))
    if len(parts) == 1:
        part = parts[0]
        out.update(labels=part['labels'], series=part['series'], total=part['total'], prev=part['prev'],
                   change=_change(part['total'], part['prev']))
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
    out['empty'] = not any(any(v for v in (s['data'] or []) if v) for s in out['series']) and not out['total']
    out['rows'] = _table_rows(out)
    return out


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
    span = Period(p.previous().start, p.end) if want_prev else p
    rows = [r for r in src.fetch(span, metric['date']) if _keep(src, r, metric['filters'])]
    cur = [r for r in rows if p.start <= r['_when'] <= p.end]
    m = src.measures[metric['measure']]
    prev = None
    if want_prev:
        pp = p.previous()
        prev = m.value([r for r in rows if pp.start <= r['_when'] <= pp.end])
    total = m.value(cur)
    group = box['group']
    groups, order, name = _group_rows(src, cur, group if not grain else None, grain, p)
    d = src.dims.get(group) if group and not grain else None
    if order is None:
        if d is not None and d.ordered:
            order = sorted(groups)
        else:
            order = sorted(groups, key=lambda k: (-(m.value(groups[k]) or 0), k[1]))
        top = box.get('top') or 0
        if top and len(order) > top:
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
    return {'labels': labels, 'series': series, 'total': total, 'prev': prev}


def _ga_label(dim, value):
    if value in ('(not set)', '(other)', ''):
        return NOT_KNOWN
    if dim in ('deviceCategory',):
        return value.capitalize()
    if dim == 'newVsReturning':
        return {'new': 'New visitors', 'returning': 'Returning visitors'}.get(value, value.capitalize())
    return value


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


def _run_ga(src, metric, box, p, grain, want_prev):
    from app.services import ga4
    m = src.measures[metric['measure']]
    filters = {src.ga_dims[k][1]: v for k, v in metric['filters'].items()}
    group, split = box['group'], box.get('split')
    if src.live:
        dims = [src.ga_dims[group][1]] if group and group not in GRAINS else []
        if split:
            dims.append(src.ga_dims[split][1])
        data = ga4.realtime([m.key], dims, limit=250, filters=filters)
        return _ga_shape(src, m, box, data, dims, None, None, None)
    dims = []
    if grain:
        dims.append(GA_GRAIN[grain])
    elif group:
        dims.append(src.ga_dims[group][1])
    if split:
        dims.append(src.ga_dims[split][1])
    top = box.get('top') or 0
    limit = 10000 if (grain or split) else (max(top, 1) if top else 1000)
    order = None if grain else ('metric', m.key, True)
    data = ga4.report(p.start, p.end, [m.key], dims, limit=limit, order=order, filters=filters)
    prev = None
    if want_prev:
        pp = p.previous()
        old = ga4.report(pp.start, pp.end, [m.key], [], limit=1, filters=filters)
        prev = (old['totals'] or [r[-1] for r in old['rows']][:1] or [0])[0]
    return _ga_shape(src, m, box, data, dims, grain, p, prev)


def _ga_shape(src, m, box, data, dims, grain, p, prev):
    total = (data['totals'] or [None])[0]
    if total is None:
        total = sum(r[-1] for r in data['rows']) if m.additive else (data['rows'][0][-1] if data['rows'] else 0)
    split = box.get('split')
    gdim = dims[0] if dims and (grain or (box['group'] and box['group'] not in GRAINS)) else None
    sdim = dims[-1] if split else None
    cells = defaultdict(float)
    gkeys, skeys, stot, gtot = [], [], defaultdict(float), defaultdict(float)
    for row in data['rows']:
        val = row[-1]
        if gdim:
            gk = _ga_bucket(grain, row[0]) if grain else _ga_label(gdim, row[0])
            if gk is None:
                continue
        else:
            gk = 'All'
        sk = _ga_label(sdim, row[len(dims) - 1]) if sdim else None
        if gk not in gtot:
            gkeys.append(gk)
        gtot[gk] += val
        if sk is not None:
            if sk not in stot:
                skeys.append(sk)
            stot[sk] += val
        cells[(gk, sk)] += val
    if grain:
        order = buckets(p, grain)
        labels = [bucket_label(k, grain) for k in order]
    else:
        order = sorted(gkeys, key=lambda k: -gtot[k]) if gkeys else (['All'] if not gdim else [])
        top = box.get('top') or 0
        if top and len(order) > top:
            order = order[:top]
        labels = list(order)
    if split:
        skeys = sorted(skeys, key=lambda k: -stot[k])[:MAX_SPLITS]
        series = [{'name': sk, 'data': [_round(cells.get((gk, sk), 0)) for gk in order]} for sk in skeys]
    else:
        series = [{'name': m.label, 'data': [_round(cells.get((gk, None), 0)) for gk in order]}]
    return {'labels': labels, 'series': series, 'total': _round(total), 'prev': _round(prev)}


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


def _gsc_label(dim, value):
    if dim == 'country':
        code = str(value or '').upper()
        return _iso3_names().get(code) or code or NOT_KNOWN
    if dim == 'device':
        return str(value or '').capitalize() or NOT_KNOWN
    return value or NOT_KNOWN


def _gsc_values(dim, values):
    """The labels a filter chose, as Search Console spells them: a country's ISO-3 code, a device in capitals."""
    if dim == 'country':
        codes = {name.lower(): code.lower() for code, name in _iso3_names().items()}
        return [codes.get(v.lower(), v.lower()) for v in values]
    if dim == 'device':
        return [v.upper() for v in values]
    return list(values)


def _run_gsc(src, metric, box, p, grain, want_prev):
    from app.services import gsc
    t = today()
    oldest = t - timedelta(days=gsc.KEEPS_DAYS - 1)
    notes = []
    q = Period(max(p.start, oldest), max(min(p.end, t), oldest), p.key)
    if p.start < oldest:
        notes.append('Google keeps 16 months of search numbers: these start on %s.' % day_range(q.start, q.start))
    mk = metric['measure']
    m = src.measures[mk]
    filters = {src.gsc_dims[k][1]: _gsc_values(src.gsc_dims[k][1], v) for k, v in metric['filters'].items()}
    group, split = box['group'], box.get('split')
    dims = ['date'] if grain else ([src.gsc_dims[group][1]] if group else [])
    if split:
        dims.append(src.gsc_dims[split][1])
    totals = gsc.query(q.start, q.end, [], filters, limit=1)
    rows = gsc.query(q.start, q.end, dims, filters, limit=gsc.MAX_ROWS) if dims else totals
    whole = _Acc()
    for r in totals:
        whole.add(*r[-3:])
    prev = None
    if want_prev:
        pp = q.previous()
        if pp.end >= oldest:
            before = _Acc()
            for r in gsc.query(max(pp.start, oldest), pp.end, [], filters, limit=1):
                before.add(*r[-3:])
            prev = before.value(mk)
    cells, gacc, sacc = defaultdict(_Acc), defaultdict(_Acc), defaultdict(_Acc)
    for row in rows:
        keys = row[:len(dims)]
        if grain:
            try:
                gk = bucket(datetime.strptime(keys[0], '%Y-%m-%d').date(), grain)
            except (ValueError, IndexError):
                continue
        else:
            gk = _gsc_label(dims[0], keys[0]) if group else 'All'
        sk = _gsc_label(dims[-1], keys[-1]) if split else None
        for acc in (cells[(gk, sk)], gacc[gk]) + ((sacc[sk],) if split else ()):
            acc.add(*row[-3:])

    # biggest first; a rate or a position is ranked by how often Google showed the group
    def rank(accs):
        return lambda k: (-(accs[k].value(mk) or 0) if m.additive else -accs[k].shown, str(k))
    if grain:
        order = buckets(p, grain)
        labels = [bucket_label(k, grain) for k in order]
    elif group:
        order = sorted(gacc, key=rank(gacc))
        top = box.get('top') or 0
        order = order[:top] if top else order
        labels = list(order)
    else:
        order, labels = ['All'], ['All']
    if split:
        skeys = sorted(sacc, key=rank(sacc))[:MAX_SPLITS]
        series = [{'name': sk, 'data': [cells[(gk, sk)].value(mk) or 0 for gk in order]} for sk in skeys]
    else:
        series = [{'name': metric['label'] or m.label, 'data': [cells[(gk, None)].value(mk) or 0 for gk in order]}]
    if q.end >= t - timedelta(days=2):
        notes.append("Google's newest two or three days are still coming in.")
    return {'labels': labels, 'series': series, 'total': whole.value(mk), 'prev': prev, 'notes': notes}


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
