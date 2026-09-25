"""One filter engine for every post listing — the CS console and the Admin listings page.

The post form has dozens of fields, and staff need to slice by any combination of them: posts
created this week departing next month, round trips to Hyderabad needing wheelchair help, posts
from Facebook with no match yet. Rather than grow two filter bars in two templates that drift
apart, the whole set is declared once here:

* `GROUPS` describes every filter (key, label, widget, choices) so the drawer renders itself and
  both pages always offer exactly the same options. Adding a filter is one entry here and nothing
  else -- no template edit, no route edit.
* A date range is ONE entry (`kind='daterange'`) that owns its two URL params. Six separate date
  boxes for three ideas is what made the old panel unreadable.
* `apply()` turns request args into SQL, ignoring anything unparseable so a hand-edited URL can
  never 500 the page.
* `chips()` names what is currently applied, so the listing can show it and offer a one-click
  removal.

Every filter ANDs with the others: each one narrows what the previous left. The free-text search
box (`q`) is deliberately not part of this -- it stays owned by the listing, because the two
consoles search different columns.
"""
from datetime import date, datetime, timedelta

from sqlalchemy import and_, or_

from app import db, options
from app.models import (AGE_GROUP_LABELS, AGE_GROUPS, CONTACT_TYPE_LABELS, CONTACT_TYPES,
                        CompanionRequest, ContactPoint, GENDERS, Match, PREF_GENDERS,
                        TRIP_ROLE_LABELS, TRIP_ROLES, TRIP_SOURCE_LABELS, TRIP_SOURCES,
                        TRIP_STATUSES)

# Journey shape lives here rather than in the CS route, so both consoles and this engine share
# one definition (app.routes.cs re-exports it for its own templates).
TRIP_TYPES = ('one_way', 'round_trip', 'multi_destination')
TRIP_TYPE_LABELS = {'one_way': 'One-way', 'round_trip': 'Round trip',
                    'multi_destination': 'Multi-trip'}

YES_NO = (('yes', 'Yes'), ('no', 'No'))
DEPARTURE_WINDOWS = ((3, 'Departing within 3 days'), (7, 'Departing within 7 days'),
                     (14, 'Departing within 14 days'), (30, 'Departing within 30 days'),
                     (60, 'Departing within 60 days'))
SORTS = (('departure', 'Soonest departure'), ('newest', 'Newest first'),
         ('updated', 'Recently updated'), ('oldest', 'Oldest first'))


# ---------------------------------------------------------------------------
# Value helpers
# ---------------------------------------------------------------------------

def _pairs(seq, labels=None):
    """Normalise a choice source into [(value, label), ...]."""
    out = []
    for item in seq:
        if isinstance(item, (tuple, list)):
            out.append((str(item[0]), str(item[1])))
        else:
            out.append((str(item), (labels or {}).get(item) or str(item).replace('_', ' ').capitalize()))
    return out


def _date(raw):
    try:
        return datetime.strptime((raw or '').strip(), '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


def _int(raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _json_has(column, value):
    """Membership test for a JSON array column, portable across Postgres json and SQLite.

    The columns are `json`, not `jsonb`, so Postgres offers no containment operator and
    `.contains()` fails with "operator does not exist: json ~~ text". Casting to text and
    matching the quoted element is what the admin role filter already does.
    """
    return db.cast(column, db.Text).like('%"{}"%'.format(value.replace('%', '')))


def _matched(query, wanted):
    """Posts that do (or do not) have at least one live match."""
    live = Match.status != 'dismissed'
    as_a = db.session.query(Match.trip_a_id).filter(live)
    as_b = db.session.query(Match.trip_b_id).filter(live)
    if wanted == 'yes':
        return query.filter(or_(CompanionRequest.id.in_(as_a), CompanionRequest.id.in_(as_b)))
    return query.filter(and_(CompanionRequest.id.notin_(as_a), CompanionRequest.id.notin_(as_b)))


def _text_any(query, value, columns):
    pat = '%{}%'.format(value)
    return query.filter(or_(*[c.ilike(pat) for c in columns]))


def _bool(query, value, column):
    return query.filter(column.is_(True) if value == 'yes' else or_(column.is_(False), column.is_(None)))


# ---------------------------------------------------------------------------
# The filters
# ---------------------------------------------------------------------------
# kind:   date | text | select | bool  (bool is a yes/no select)
# sql:    (query, value) -> query.  Only called with a value that passed `parse`.
# parse:  raw string -> usable value or None to skip the filter entirely.

# Presets are client-side sugar: picking one fills the two date boxes, so the server still sees a
# plain from/to range and a shared URL means exactly one thing. Offsets are in days from today,
# `None` meaning open-ended.
DEPARTURE_PRESETS = (
    ('next7', 'In the next 7 days', 0, 7),
    ('next30', 'In the next 30 days', 0, 30),
    ('next90', 'In the next 3 months', 0, 90),
    ('past', 'Already departed', None, -1),
)
POSTED_PRESETS = (
    ('today', 'Today', 0, 0),
    ('last7', 'In the last 7 days', -7, 0),
    ('last30', 'In the last 30 days', -30, 0),
    ('last90', 'In the last 3 months', -90, 0),
)
RETURN_PRESETS = (
    ('next30', 'In the next 30 days', 0, 30),
    ('next90', 'In the next 3 months', 0, 90),
)


def _daterange(key, label, column, from_key, to_key, presets, is_datetime=False, hint=None):
    """One filter covering a from/to pair on a single column.

    A timestamp column (created_at) is stored and displayed in UTC -- the listings print
    "posted 2026-09-24" straight from it -- so the range is compared in UTC too. Filtering in
    local time would disagree with the date printed next to the row, which is worse than the
    few hours of skew it would fix.

    The two URL params are kept (`dep_from`/`dep_to` and friends) so existing links and bookmarks
    still work -- what changes is that the UI, the chips and this spec treat them as one thing.
    """
    return {'key': key, 'label': label, 'kind': 'daterange', 'column': column,
            'from_key': from_key, 'to_key': to_key, 'presets': presets,
            'is_datetime': is_datetime, 'hint': hint,
            # not 'wide': a range is one dropdown like any other, and the exact-date boxes
            # stack underneath it when they are asked for
            'choices': None, 'parse': None, 'placeholder': None, 'wide': False, 'sql': None,
            'widget': None}


def _field(key, label, kind, sql, choices=None, parse=None, placeholder=None, wide=False,
           widget=None):
    # A yes/no filter is just a two-option select; filling in its choices here means the popup
    # template has one code path for every dropdown.
    if kind == 'bool' and choices is None:
        choices = _pairs(YES_NO)
    return {'key': key, 'label': label, 'kind': kind, 'sql': sql, 'choices': choices,
            'parse': parse, 'placeholder': placeholder, 'wide': wide,
            # 'airport' / 'airline' ask the template for the same autocomplete the post form uses,
            # so nobody has to know how a city is spelled in our data
            'widget': widget}


GROUPS = [
    {
        'title': 'When',
        'hint': 'Departure and return read the trip; posted reads when it reached us.',
        'fields': [
            _daterange('dep', 'Departure', CompanionRequest.from_date, 'dep_from', 'dep_to',
                       DEPARTURE_PRESETS),
            _daterange('ret', 'Return', CompanionRequest.to_date, 'ret_from', 'ret_to',
                       RETURN_PRESETS, hint='Round trips only — one-way posts have no return date.'),
            _daterange('posted', 'Posted to us', CompanionRequest.created_at, 'posted_from',
                       'posted_to', POSTED_PRESETS, is_datetime=True),
            _field('flex', 'Dates flexible', 'bool',
                   sql=lambda q, v: q.filter(or_(CompanionRequest.from_date_flexible.is_(True),
                                                 CompanionRequest.to_date_flexible.is_(True))
                                             if v == 'yes' else
                                             and_(or_(CompanionRequest.from_date_flexible.is_(False),
                                                      CompanionRequest.from_date_flexible.is_(None)),
                                                  or_(CompanionRequest.to_date_flexible.is_(False),
                                                      CompanionRequest.to_date_flexible.is_(None))))),
        ],
    },
    {
        'title': 'Route and flight',
        'hint': 'City, airport name or IATA code — all four route columns are searched.',
        'fields': [
            _field('origin', 'Departing from', 'text', widget='airport',
                   placeholder='City or code…',
                   sql=lambda q, v: _text_any(q, v, [CompanionRequest.flying_from, CompanionRequest.origin_iata,
                                                     CompanionRequest.origin_city, CompanionRequest.origin_metro])),
            _field('dest', 'Arriving at', 'text', widget='airport',
                   placeholder='City or code…',
                   sql=lambda q, v: _text_any(q, v, [CompanionRequest.destination, CompanionRequest.dest_iata,
                                                     CompanionRequest.dest_city, CompanionRequest.dest_metro])),
            _field('airline', 'Airline', 'text', widget='airline',
                   placeholder='Airline name…',
                   sql=lambda q, v: _text_any(q, v, [CompanionRequest.airline, CompanionRequest.return_airline])),
            _field('flight', 'Flight number', 'text', placeholder='e.g. QR573',
                   sql=lambda q, v: _text_any(q, v, [CompanionRequest.flight_number,
                                                     CompanionRequest.return_flight_number])),
            _field('trip_type', 'Journey', 'select', choices=_pairs(TRIP_TYPES, TRIP_TYPE_LABELS),
                   parse=lambda r: r if r in TRIP_TYPES else None,
                   sql=lambda q, v: q.filter(CompanionRequest.trip_type == v)),
            _field('ticket', 'Ticket already booked', 'bool',
                   sql=lambda q, v: _bool(q, v, CompanionRequest.ticket_booked)),
        ],
    },
    {
        'title': 'The post',
        'fields': [
            _field('status', 'Status', 'select', choices=_pairs(TRIP_STATUSES),
                   parse=lambda r: r if r in TRIP_STATUSES else None,
                   sql=lambda q, v: q.filter(CompanionRequest.status == v)),
            _field('source', 'Came from', 'select', choices=_pairs(TRIP_SOURCES, TRIP_SOURCE_LABELS),
                   parse=lambda r: r if r in TRIP_SOURCES else None,
                   sql=lambda q, v: q.filter(CompanionRequest.source == v)),
            _field('role', 'Role', 'select', choices=_pairs(TRIP_ROLES, TRIP_ROLE_LABELS),
                   parse=lambda r: r if r in TRIP_ROLES else None,
                   sql=lambda q, v: q.filter(CompanionRequest.role == v)),
            _field('category', 'Reason for travel', 'select', choices=_pairs(options.CATEGORIES),
                   sql=lambda q, v: q.filter(CompanionRequest.category == v)),
            _field('matched', 'Has a live match', 'bool', sql=_matched),
            _field('claimed', 'Claimed by the traveller', 'bool',
                   sql=lambda q, v: q.filter(CompanionRequest.claimed_at.isnot(None) if v == 'yes'
                                             else CompanionRequest.claimed_at.is_(None))),
            _field('anon', 'Posted anonymously', 'bool',
                   sql=lambda q, v: _bool(q, v, CompanionRequest.is_anonymous)),
        ],
    },
    {
        'title': 'Travellers',
        'fields': [
            _field('age', 'Age group', 'select', choices=_pairs(AGE_GROUPS, AGE_GROUP_LABELS),
                   parse=lambda r: r if r in AGE_GROUPS else None,
                   sql=lambda q, v: q.filter(CompanionRequest.traveler_age_group == v)),
            _field('gender', 'Gender', 'select', choices=_pairs(GENDERS),
                   parse=lambda r: r if r in GENDERS else None,
                   sql=lambda q, v: q.filter(CompanionRequest.traveler_gender == v)),
            _field('pref_gender', 'Companion preference', 'select', choices=_pairs(PREF_GENDERS),
                   parse=lambda r: r if r in PREF_GENDERS else None,
                   sql=lambda q, v: q.filter(CompanionRequest.pref_gender == v)),
            _field('need', 'Assistance needed', 'select', choices=_pairs(options.TRAVELLER_NEEDS),
                   sql=lambda q, v: q.filter(_json_has(CompanionRequest.traveller_needs, v))),
            _field('language', 'Language', 'select', choices=_pairs(options.LANGUAGES),
                   sql=lambda q, v: q.filter(_json_has(CompanionRequest.preferred_languages, v))),
            _field('on_behalf', 'Travelling for', 'select', choices=_pairs(options.ON_BEHALF_OF),
                   sql=lambda q, v: q.filter(CompanionRequest.on_behalf_of.ilike('%{}%'.format(v)))),
        ],
    },
    {
        'title': 'Contact',
        'fields': [
            _field('contact_type', 'Has contact of type', 'select',
                   choices=_pairs(CONTACT_TYPES, CONTACT_TYPE_LABELS),
                   parse=lambda r: r if r in CONTACT_TYPES else None,
                   sql=lambda q, v: q.filter(CompanionRequest.contact_points.any(ContactPoint.type == v))),
            _field('consent', 'Contact shareable', 'bool',
                   sql=lambda q, v: q.filter(CompanionRequest.contact_points.any(
                       ContactPoint.consent_to_share.is_(True)) if v == 'yes'
                       else ~CompanionRequest.contact_points.any(ContactPoint.consent_to_share.is_(True)))),
        ],
    },
]

FIELDS = {f['key']: f for g in GROUPS for f in g['fields']}


def _parse_range(field, args):
    """{'from': date|None, 'to': date|None} or None when neither end is usable."""
    lo, hi = _date(args.get(field['from_key'])), _date(args.get(field['to_key']))
    if lo and hi and lo > hi:
        lo, hi = hi, lo                       # a backwards range is a slip, not an empty result
    return {'from': lo, 'to': hi} if (lo or hi) else None


def _range_sql(field, query, value):
    col = field['column']
    if value['from']:
        lo = datetime.combine(value['from'], datetime.min.time()) if field['is_datetime'] else value['from']
        query = query.filter(col >= lo)
    if value['to']:
        if field['is_datetime']:
            # "posted on or before the 5th" has to include everything that happened during the 5th
            query = query.filter(col < datetime.combine(value['to'] + timedelta(days=1), datetime.min.time()))
        else:
            query = query.filter(col <= value['to'])
    return query


def _parse(field, raw):
    raw = (raw or '').strip()
    if not raw:
        return None
    if field['parse']:
        return field['parse'](raw)
    if field['kind'] == 'bool':
        return raw if raw in ('yes', 'no') else None
    if field['kind'] == 'select':
        allowed = {v for v, _ in (field['choices'] or [])}
        return raw if raw in allowed else None
    return raw[:120]


def values(args):
    """Every filter that is set and valid, as {key: parsed value}."""
    out = {}
    for key, field in FIELDS.items():
        v = _parse_range(field, args) if field['kind'] == 'daterange' else _parse(field, args.get(key))
        if v is not None:
            out[key] = v
    return out


def apply(query, args, vals=None):
    """AND every valid filter in `args` onto `query`. Returns (query, values)."""
    vals = values(args) if vals is None else vals
    for key, value in vals.items():
        field = FIELDS[key]
        query = _range_sql(field, query, value) if field['kind'] == 'daterange' \
            else field['sql'](query, value)
    return query, vals


def sort_query(query, sort):
    if sort == 'newest':
        return query.order_by(CompanionRequest.created_at.desc())
    if sort == 'updated':
        return query.order_by(CompanionRequest.updated_at.desc())
    if sort == 'oldest':
        return query.order_by(CompanionRequest.created_at.asc())
    return query.order_by(CompanionRequest.from_date.asc().nulls_last(),
                          CompanionRequest.created_at.desc())


def _label_for(field, value):
    if field['kind'] == 'daterange':
        lo, hi = value['from'], value['to']
        if lo and hi:
            return '%s to %s' % (lo.strftime('%d %b %Y'), hi.strftime('%d %b %Y'))
        return ('from %s' % lo.strftime('%d %b %Y')) if lo else ('until %s' % hi.strftime('%d %b %Y'))
    if field['kind'] == 'bool':
        return 'Yes' if value == 'yes' else 'No'
    for v, label in (field['choices'] or []):
        if v == str(value):
            return label
    return str(value)


def chips(vals):
    """What is applied, in drawer order, ready to render as removable chips.

    `params` is what a chip's X has to blank out -- a date range owns two of them, so the chip
    cannot just clear an input named after its own key.
    """
    out = []
    for key in FIELDS:
        if key in vals:
            field = FIELDS[key]
            params = [field['from_key'], field['to_key']] if field['kind'] == 'daterange' else [key]
            out.append({'key': key, 'label': field['label'],
                        'value': _label_for(field, vals[key]), 'params': params})
    return out
