"""Derive a post's flown segments and keep the trip_legs rows in step with them.

A post describes its route in three different shapes depending on trip_type:

    one_way            flying_from -> destination on from_date
    round_trip         the same, plus the mirror image back on to_date
    multi_destination  the `legs` JSON blob, one hop per entry

Matching needs all of those to look the same, so this module flattens them into TripLeg
rows. Everything that changes a route calls sync_legs(); nothing else writes trip_legs.
"""
from datetime import date, datetime

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app import db
from app.models import CompanionRequest, TripLeg
from app.services.locations import normalize_location


def _as_date(value):
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], '%Y-%m-%d').date()
    except ValueError:
        return None


def _endpoint(text):
    """(display text, iata, city, metro) for one end of a leg."""
    loc = normalize_location(text)
    if not loc:
        return (text or None), None, None, None
    return (text or loc['display']), loc['iata'], loc['city'], loc['metro']


def derive(trip):
    """The legs this post implies, as plain dicts in travel order.

    Pure: reads the post, touches no rows. sync_legs() turns the result into TripLeg rows,
    and the tests use it directly to check the shape of each trip type.
    """
    out = []

    def add(kind, o_text, d_text, when, flexible, airline, flight,
            o_norm=None, d_norm=None):
        o_text, o_iata, o_city, o_metro = o_norm or _endpoint(o_text)
        d_text, d_iata, d_city, d_metro = d_norm or _endpoint(d_text)
        out.append({
            'seq': len(out), 'kind': kind,
            'origin_text': o_text, 'origin_iata': o_iata,
            'origin_city': o_city, 'origin_metro': o_metro,
            'dest_text': d_text, 'dest_iata': d_iata,
            'dest_city': d_city, 'dest_metro': d_metro,
            'depart_date': _as_date(when), 'date_flexible': bool(flexible),
            'airline': airline or None, 'flight_number': flight or None,
        })

    if trip.travel_type != 'air':
        return out

    if trip.trip_type == 'multi_destination' and trip.legs:
        for leg in trip.legs:
            if not (leg.get('from') or leg.get('to')):
                continue
            add('leg', leg.get('from'), leg.get('to'), leg.get('date'),
                trip.from_date_flexible, leg.get('airline'), leg.get('flight_number'))
        return out

    # The post already carries normalised columns for its own origin and destination, so
    # reuse them rather than re-resolving the text and risking a different answer.
    origin = (trip.flying_from, trip.origin_iata, trip.origin_city, trip.origin_metro)
    dest = (trip.destination, trip.dest_iata, trip.dest_city, trip.dest_metro)

    add('outbound' if trip.trip_type == 'round_trip' else 'leg',
        None, None, trip.from_date, trip.from_date_flexible,
        trip.airline, trip.flight_number, o_norm=origin, d_norm=dest)

    if trip.trip_type == 'round_trip' and trip.to_date:
        # the way home is the same two airports the other way round
        add('return', None, None, trip.to_date, trip.to_date_flexible,
            trip.airline, trip.flight_number, o_norm=dest, d_norm=origin)
    return out


_FIELDS = ('kind', 'origin_text', 'origin_iata', 'origin_city', 'origin_metro',
           'dest_text', 'dest_iata', 'dest_city', 'dest_metro',
           'depart_date', 'date_flexible', 'airline', 'flight_number')


def sync_legs(trip):
    """Rebuild trip.leg_rows from the post. Returns the legs, in order.

    Existing rows are updated in place where they can be, so a leg keeps its id — matches
    point at leg ids, and replacing every row on each save would drop every match the post
    already had.
    """
    wanted = derive(trip)
    have = sorted(trip.leg_rows, key=lambda r: r.seq)

    for i, spec in enumerate(wanted):
        row = have[i] if i < len(have) else None
        if row is None:
            # Append to the post's collection rather than setting TripLeg(trip=...): since
            # SQLAlchemy 2.0 the save-update cascade only runs parent -> child, so the
            # child-side assignment leaves the leg out of the session entirely (it warns,
            # then drops it). Going through the collection also means a post the caller is
            # about to reject never gets pulled into the session by its legs.
            row = TripLeg(seq=i)
            trip.leg_rows.append(row)
        row.seq = i
        for f in _FIELDS:
            setattr(row, f, spec[f])

    for extra in have[len(wanted):]:          # trip got shorter (round trip -> one way)
        trip.leg_rows.remove(extra)           # delete-orphan turns this into a DELETE
        if extra in db.session:
            db.session.delete(extra)

    return sorted([r for r in trip.leg_rows if r not in have[len(wanted):]],
                  key=lambda r: r.seq)


def legs_of(trip):
    """The post's legs, falling back to a synthetic one for posts not yet synced."""
    if trip.leg_rows:
        return sorted(trip.leg_rows, key=lambda r: r.seq)
    return []


# Fields a leg is derived from. Touching any of them makes the existing legs wrong.
_ROUTE_FIELDS = (
    'travel_type', 'trip_type', 'legs',
    'flying_from', 'destination', 'from_date', 'to_date',
    'from_date_flexible', 'to_date_flexible', 'airline', 'flight_number',
    'origin_iata', 'origin_city', 'origin_metro',
    'dest_iata', 'dest_city', 'dest_metro',
)


def _route_changed(trip):
    state = inspect(trip)
    return any(state.attrs[f].history.has_changes() for f in _ROUTE_FIELDS)


@event.listens_for(Session, 'before_flush')
def _resync_legs_on_flush(session, flush_context, instances):
    """Rebuild a post's legs whenever its route changes, however it was changed.

    apply_route() covers the normal paths, but a post's date can also be set straight onto
    the column -- and a post whose legs lag behind its route quietly stops matching, which
    is close to impossible to spot from the outside. Doing it at flush time means there is
    no way to write a route without its legs following.
    """
    for obj in list(session.new) + list(session.dirty):
        if not isinstance(obj, CompanionRequest):
            continue
        if obj in session.deleted:
            continue
        try:
            if obj in session.new or _route_changed(obj):
                sync_legs(obj)
        except Exception:                    # never let leg upkeep block a save
            from flask import current_app
            current_app.logger.exception('Could not rebuild legs for post %s', obj.id)
