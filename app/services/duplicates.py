"""Same-request detection: the guard that stops one trip being posted twice.

A duplicate is not a good companion candidate. Matching handles those, and two different
people on one flight are the whole point of this site. A duplicate is a signal that this is
the SAME request entered twice -- a double submit, a re-import, or CS typing up a post the
traveller already made themselves.

These are the rules the CS posts tree has always listed under "possible duplicates", lifted
out of the route so they can also run *before* a post is stored. Submit time is the only
moment anybody can still decide not to create the post, which is why the check belongs there
and not only in the console afterwards.

Nothing here blocks a post. find() reports, the caller shows what it found, and a confirmed
submit goes straight in -- CS especially always gets to say "yes, post it anyway".
"""
from app import db
from app.models import CompanionRequest, ContactPoint, TRIP_ROLE_LABELS
from app.services.matching import DATE_WINDOW_DAYS

# A closed post is finished business: re-posting the same route later is not a double entry.
LIVE_STATUSES = ('unconfirmed', 'open', 'matched')


def _others(trip):
    """Live posts other than this one. `trip` may be unsaved, in which case there is no id yet."""
    q = CompanionRequest.query.filter(CompanionRequest.status.in_(LIVE_STATUSES))
    if trip.id:
        q = q.filter(CompanionRequest.id != trip.id)
    return q


def _near(a, b):
    """Close enough in time that the two posts could match at all.

    Outside the matcher's candidate window the posts can never pair up, so calling them the
    same request would be wrong however alike the rest of the details look.
    """
    if not a or not b:
        return True
    return abs((a - b).days) <= DATE_WINDOW_DAYS


def _name(trip):
    return (trip.traveler_name or trip.poster_name or '').strip().lower()


def describe(trip, reasons):
    """The other post as a popup needs to show it -- enough to recognise one's own trip."""
    person = trip.poster_name or (trip.author.username if trip.author else None) or 'Not named'
    return {
        'id': trip.id,
        'owner_id': trip.user_id,
        'person': person,
        'route': trip.route_display,
        'departs': trip.from_date.isoformat() if trip.from_date else None,
        'returns': trip.to_date.isoformat() if trip.to_date else None,
        'airline': trip.airline,
        'flight': trip.flight_number,
        'role': TRIP_ROLE_LABELS.get(trip.role or 'seeking_help', 'Seeking help'),
        'status': trip.status,
        'status_label': (trip.status or '').replace('_', ' ').title(),
        'source': trip.source,
        'reasons': reasons,
    }


def find(trip, contact_values=(), owner_id=None, limit=6):
    """Posts that look like `trip` posted twice, worst first.

    `trip` can be an unsaved CompanionRequest -- route fields and dates are all that is read,
    so callers build the candidate, check, and only then store it.

    `contact_values` are the phone/e-mail rows submitted with this post (they are not attached
    to an unsaved trip yet). `owner_id` restricts the answer to that account's own posts, which
    is what the traveller-facing form wants: it must never describe a stranger's post back to
    the person filling in the form. CS passes no owner and sees every signal.
    """
    found = {}

    def add(other, reason):
        if other.id == trip.id:
            return
        if owner_id is not None and other.user_id != owner_id:
            return
        found.setdefault(other.id, []).append(reason)

    # 1. The same account posting the same route again, around the same time.
    if trip.user_id:
        for t in _others(trip).filter(CompanionRequest.user_id == trip.user_id,
                                      CompanionRequest.flying_from == trip.flying_from,
                                      CompanionRequest.destination == trip.destination).all():
            if _near(t.from_date, trip.from_date):
                add(t, 'same account and route')

    # 2. The same named traveller, route and date -- how a CS double-entry usually looks.
    if trip.poster_name:
        pname = trip.poster_name.strip().lower()
        for t in _others(trip).filter(db.func.lower(CompanionRequest.poster_name) == pname,
                                      CompanionRequest.flying_from == trip.flying_from,
                                      CompanionRequest.destination == trip.destination,
                                      CompanionRequest.from_date == trip.from_date).all():
            add(t, 'same traveller, route and date')

    # 3. Same flight, same day, same role. Two *different* people here are companions, not a
    #    double entry, so anything that identifies them as different people rules it out.
    if trip.flight_number and trip.from_date:
        mine = _name(trip)
        for t in _others(trip).filter(CompanionRequest.flight_number == trip.flight_number,
                                      CompanionRequest.from_date == trip.from_date,
                                      CompanionRequest.role == trip.role).all():
            if trip.user_id and t.user_id and t.user_id != trip.user_id:
                continue
            theirs = _name(t)
            if mine and theirs and mine != theirs:
                continue
            add(t, 'same flight, date and role')

    # 4. Re-imported or re-typed from the very same page.
    if trip.source_url:
        for t in _others(trip).filter(CompanionRequest.source_url == trip.source_url).all():
            add(t, 'same source page')

    # 5. A contact point that already sits on another live post around the same dates.
    values = [v for v in contact_values if v]
    values += [cp.value for cp in trip.contact_points if cp.value and cp.type != 'inapp_chat']
    if values:
        ids = {cp.trip_id for cp in ContactPoint.query.filter(
            ContactPoint.value.in_(values), ContactPoint.trip_id.isnot(None)).all() if cp.trip_id}
        ids.discard(trip.id)
        if ids:
            for t in _others(trip).filter(CompanionRequest.id.in_(ids)).all():
                if _near(t.from_date, trip.from_date):
                    add(t, 'shared contact detail')

    if not found:
        return []
    rows = CompanionRequest.query.filter(CompanionRequest.id.in_(found)).all()
    out = [describe(t, found[t.id]) for t in rows]
    out.sort(key=lambda d: (-len(d['reasons']), d['id']))
    return out[:limit]


def summary(dups):
    """One line for a flash message or a toast."""
    if not dups:
        return ''
    ids = ', '.join('#%s' % d['id'] for d in dups)
    if len(dups) == 1:
        return 'This looks like post %s, which is already live.' % ids
    return 'This looks like posts that are already live: %s.' % ids
