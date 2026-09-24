"""One filter engine for every post listing — the CS console and the Admin listings page.

The post form has dozens of fields, and staff need to slice by any combination of them: posts
created this week departing next month, round trips to Hyderabad needing wheelchair help, posts
from Facebook with no match yet. Rather than grow two filter bars in two templates that drift
apart, the whole set is declared once here:

* `GROUPS` describes every filter (key, label, widget, choices) so the popup renders itself and
  both pages always offer exactly the same options.
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

def _field(key, label, kind, sql, choices=None, parse=None, placeholder=None, wide=False):
    # A yes/no filter is just a two-option select; filling in its choices here means the popup
    # template has one code path for every dropdown.
    if kind == 'bool' and choices is None:
        choices = _pairs(YES_NO)
    return {'key': key, 'label': label, 'kind': kind, 'sql': sql, 'choices': choices,
            'parse': parse, 'placeholder': placeholder, 'wide': wide}


GROUPS = [
    {
        'title': 'When',
        'hint': 'Departure and return read the trip; posted reads when it reached us.',
        'fields': [
            _field('dep_from', 'Departs on or after', 'date', parse=_date,
                   sql=lambda q, v: q.filter(CompanionRequest.from_date >= v)),
            _field('dep_to', 'Departs on or before', 'date', parse=_date,
                   sql=lambda q, v: q.filter(CompanionRequest.from_date <= v)),
            _field('ret_from', 'Returns on or after', 'date', parse=_date,
                   sql=lambda q, v: q.filter(CompanionRequest.to_date >= v)),
            _field('ret_to', 'Returns on or before', 'date', parse=_date,
                   sql=lambda q, v: q.filter(CompanionRequest.to_date <= v)),
            _field('posted_from', 'Posted on or after', 'date', parse=_date,
                   sql=lambda q, v: q.filter(CompanionRequest.created_at >= datetime.combine(v, datetime.min.time()))),
            _field('posted_to', 'Posted on or before', 'date', parse=_date,
                   sql=lambda q, v: q.filter(CompanionRequest.created_at < datetime.combine(v + timedelta(days=1), datetime.min.time()))),
            _field('days', 'Quick departure window', 'select', choices=_pairs(DEPARTURE_WINDOWS),
                   parse=lambda r: _int(r) if (_int(r) or 0) > 0 else None,
                   sql=lambda q, v: q.filter(CompanionRequest.from_date >= date.today(),
                                             CompanionRequest.from_date <= date.today() + timedelta(days=v))),
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
            _field('origin', 'Departure city / airport', 'text', placeholder='Hyderabad, HYD…',
                   sql=lambda q, v: _text_any(q, v, [CompanionRequest.flying_from, CompanionRequest.origin_iata,
                                                     CompanionRequest.origin_city, CompanionRequest.origin_metro])),
            _field('dest', 'Arrival city / airport', 'text', placeholder='Dallas, DFW…',
                   sql=lambda q, v: _text_any(q, v, [CompanionRequest.destination, CompanionRequest.dest_iata,
                                                     CompanionRequest.dest_city, CompanionRequest.dest_metro])),
            _field('airline', 'Airline', 'text', placeholder='Qatar Airways…',
                   sql=lambda q, v: _text_any(q, v, [CompanionRequest.airline, CompanionRequest.return_airline])),
            _field('flight', 'Flight number', 'text', placeholder='QR573',
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
        v = _parse(field, args.get(key))
        if v is not None:
            out[key] = v
    return out


def apply(query, args, vals=None):
    """AND every valid filter in `args` onto `query`. Returns (query, values)."""
    vals = values(args) if vals is None else vals
    for key, value in vals.items():
        query = FIELDS[key]['sql'](query, value)
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
    if field['kind'] == 'bool':
        return 'Yes' if value == 'yes' else 'No'
    for v, label in (field['choices'] or []):
        if v == str(value):
            return label
    return str(value)


def chips(vals):
    """What is applied, in popup order, ready to render as removable chips."""
    out = []
    for key in FIELDS:
        if key in vals:
            out.append({'key': key, 'label': FIELDS[key]['label'],
                        'value': _label_for(FIELDS[key], vals[key])})
    return out
