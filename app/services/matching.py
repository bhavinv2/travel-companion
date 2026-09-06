"""Matching engine: candidate selection, explainable scoring, persistence of Match rows.

Matching runs **leg against leg**, not post against post. Every post is flattened into
TripLeg rows by services.legs, so a round trip offers its outbound and its return
separately and a multi-destination post offers each hop. Any leg can pair with any other
leg whatever trip type it came from, which is what lets a one-way traveller be the
companion for the second hop of somebody's multi-stop itinerary.

Route, date and flight are scored from the two legs; role, language and preferences come
from the posts behind them. Weights and sub-scores follow doc/PHASE2_PLAN_ANALYSIS.md §6.
Every criterion returns a 0-100 sub-score and a human-readable detail so the UI can show
"why" next to the percentage.
"""
import re
from datetime import date, timedelta

from app import db
from app.models import CompanionRequest, Match, TripLeg, ActivityEvent
from app.services import legs

WEIGHTS = {
    'route': 35,
    'date': 25,
    'flight': 15,
    'role': 10,
    'language': 8,
    'prefs': 7,
}
LABELS = {
    'route': 'Route', 'date': 'Dates', 'flight': 'Flight / airline', 'role': 'Roles',
    'language': 'Language', 'prefs': 'Preferences',
}
MIN_SCORE = 40           # below this a pair is not stored as a match
DATE_WINDOW_DAYS = 7     # candidate pre-filter; scoring narrows further
AGE_MIDPOINT = {'under_18': 15, '18_30': 24, '31_45': 38, '46_60': 53, '60_plus': 68}


def _norm_flight(s):
    return re.sub(r'[^A-Z0-9]', '', (s or '').upper())


def _norm_airline(s):
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


# ---------------------------------------------------------------------------
# Sub-scores
# ---------------------------------------------------------------------------

def score_route(a, b):
    if a.origin_iata and b.origin_iata and a.dest_iata and b.dest_iata:
        if a.origin_iata == b.origin_iata and a.dest_iata == b.dest_iata:
            return 100, f'Same airports {a.origin_iata} → {a.dest_iata}'
        if a.origin_metro == b.origin_metro and a.dest_metro == b.dest_metro:
            return 80, f'Same cities ({a.origin_metro} → {a.dest_metro}), different airports'
        return 0, 'Different route'
    if a.origin_metro and b.origin_metro and a.origin_metro == b.origin_metro and a.dest_metro == b.dest_metro:
        return 80, f'Same cities ({a.origin_metro} → {a.dest_metro})'
    return 0, 'Route not recognised'


def score_date(a, b):
    if not a.from_date or not b.from_date:
        return 30, 'A date is missing'
    diff = abs((a.from_date - b.from_date).days)
    if diff == 0:
        return 100, 'Same day'
    if diff == 1:
        return 80, '1 day apart'
    if diff <= 3:
        return 50, f'{diff} days apart'
    if diff <= DATE_WINDOW_DAYS and (a.from_date_flexible or b.from_date_flexible):
        return 60, f'{diff} days apart, but dates are flexible'
    return 0, f'{diff} days apart'


def score_flight(a, b):
    fa, fb = _norm_flight(a.flight_number), _norm_flight(b.flight_number)
    aa, ab = _norm_airline(a.airline), _norm_airline(b.airline)
    if fa and fb and fa == fb and (not aa or not ab or aa == ab):
        return 100, f'Same flight {a.flight_number or b.flight_number}'
    if aa and ab and aa == ab:
        return 60, f'Same airline ({a.airline})'
    if not aa or not ab:
        return 30, 'Airline unknown on one side'
    return 0, 'Different airlines'


def _post(x):
    """The post behind a leg -- or x itself, so the scorers work on either.

    Route, date and flight read attribute names a TripLeg also provides, so score_pair()
    can be handed two legs (what the matcher does) or two whole posts (handy in tests and
    for CS tools that just want to compare two listings).
    """
    return getattr(x, 'trip', None) or x


def score_role(a, b):
    a, b = _post(a), _post(b)
    ra, rb = a.role or 'seeking_help', b.role or 'seeking_help'
    pair = {ra, rb}
    if pair == {'seeking_help', 'offering_help'}:
        return 100, 'One needs help, one offers help'
    if 'open' in pair:
        return 70, 'One side is open to either role'
    if pair == {'seeking_help'}:
        return 50, 'Both are seeking help (could still travel together)'
    return 20, 'Both are offering help'


def score_language(a, b):
    a, b = _post(a), _post(b)
    la = {x.strip().lower() for x in (a.preferred_languages or []) if x}
    lb = {x.strip().lower() for x in (b.preferred_languages or []) if x}
    if not la or not lb:
        return 50, 'Language not specified on one side'
    shared = la & lb
    if shared:
        return 100, 'Shared: ' + ', '.join(sorted(s.title() for s in shared))
    return 0, 'No shared language'


def _pref_side(pref_trip, other):
    """How well `other`'s traveller matches `pref_trip`'s companion preferences (0-100)."""
    parts, notes = [], []
    pg = pref_trip.pref_gender or 'any'
    if pg == 'any':
        parts.append(100)
    elif not other.traveler_gender or other.traveler_gender in ('other', 'unspecified'):
        parts.append(50); notes.append('gender unknown')
    elif other.traveler_gender == pg:
        parts.append(100)
    else:
        parts.append(0); notes.append(f'wants {pg}')
    if pref_trip.pref_age_min is None and pref_trip.pref_age_max is None:
        parts.append(100)
    elif not other.traveler_age_group:
        parts.append(50); notes.append('age unknown')
    else:
        mid = AGE_MIDPOINT.get(other.traveler_age_group, 40)
        lo = pref_trip.pref_age_min if pref_trip.pref_age_min is not None else 0
        hi = pref_trip.pref_age_max if pref_trip.pref_age_max is not None else 200
        if lo <= mid <= hi:
            parts.append(100)
        else:
            parts.append(0); notes.append(f'wants age {lo}–{hi if hi < 200 else "+"}')
    return sum(parts) / len(parts), notes


def score_prefs(a, b):
    a, b = _post(a), _post(b)
    sa, na = _pref_side(a, b)
    sb, nb = _pref_side(b, a)
    s = (sa + sb) / 2
    notes = na + nb
    return round(s), ('Preferences fit' if s >= 75 else ('; '.join(notes) or 'Partial fit'))


SCORERS = {
    'route': score_route, 'date': score_date, 'flight': score_flight,
    'role': score_role, 'language': score_language, 'prefs': score_prefs,
}


def get_weights():
    """Default weights, optionally overridden per key via MATCH_WEIGHTS (JSON env var / app config)."""
    try:
        from flask import current_app
        override = current_app.config.get('MATCH_WEIGHTS') or {}
    except RuntimeError:  # outside an app context
        override = {}
    weights = dict(WEIGHTS)
    for k, v in override.items():
        if k in weights:
            try:
                weights[k] = max(0, float(v))
            except (TypeError, ValueError):
                pass
    return weights


def score_pair(a, b):
    """Score one leg against another. Returns (total 0-100, criteria list)."""
    total = 0.0
    criteria = []
    weights = get_weights()
    scale = 100.0 / sum(weights.values()) if sum(weights.values()) else 0
    for key, weight in weights.items():
        weight = weight * scale
        sub, detail = SCORERS[key](a, b)
        points = weight * sub / 100.0
        total += points
        criteria.append({
            'key': key, 'label': LABELS[key], 'ok': sub >= 60, 'sub': sub,
            'points': round(points, 1), 'weight': round(weight, 1), 'detail': detail,
        })
    return int(round(total)), criteria


# ---------------------------------------------------------------------------
# Candidates & persistence
# ---------------------------------------------------------------------------

def leg_candidates(leg, include_unconfirmed=False):
    """Legs on other people's posts that could pair with this one.

    A cheap pre-filter only — same metro pair (or same airports when a metro is unknown)
    and departing within DATE_WINDOW_DAYS. score_pair() decides what actually counts.
    """
    if not leg.depart_date:
        return []
    statuses = ['open', 'matched'] + (['unconfirmed'] if include_unconfirmed else [])
    q = TripLeg.query.join(CompanionRequest, TripLeg.trip_id == CompanionRequest.id).filter(
        TripLeg.trip_id != leg.trip_id,
        CompanionRequest.travel_type == 'air',
        CompanionRequest.status.in_(statuses),
        TripLeg.depart_date >= leg.depart_date - timedelta(days=DATE_WINDOW_DAYS),
        TripLeg.depart_date <= leg.depart_date + timedelta(days=DATE_WINDOW_DAYS),
        TripLeg.depart_date >= date.today() - timedelta(days=1),
    )
    if leg.origin_metro and leg.dest_metro:
        q = q.filter(TripLeg.origin_metro == leg.origin_metro,
                     TripLeg.dest_metro == leg.dest_metro)
    elif leg.origin_iata and leg.dest_iata:
        q = q.filter(TripLeg.origin_iata == leg.origin_iata,
                     TripLeg.dest_iata == leg.dest_iata)
    else:
        return []
    owner = leg.trip.user_id
    if owner:
        q = q.filter((CompanionRequest.user_id != owner) | (CompanionRequest.user_id.is_(None)))
    return q.all()


def candidates_for(trip, include_unconfirmed=False):
    """Posts with at least one leg that could pair with one of this post's legs.

    Kept for callers that only want "who might suit this post"; the matcher itself works
    in leg pairs and uses leg_candidates() directly.
    """
    seen, out = set(), []
    for leg in legs.legs_of(trip):
        for cand in leg_candidates(leg, include_unconfirmed=include_unconfirmed):
            if cand.trip_id not in seen:
                seen.add(cand.trip_id)
                out.append(cand.trip)
    return out


def _same_person(a, b):
    """Two posts by the same account or sharing a contact value are never matched to each other."""
    if a.user_id and a.user_id == b.user_id:
        return True
    va = {(cp.type, cp.value) for cp in a.contact_points if cp.type != 'inapp_chat'}
    vb = {(cp.type, cp.value) for cp in b.contact_points if cp.type != 'inapp_chat'}
    return bool(va & vb)


def compute_matches_for(trip, include_unconfirmed=False, actor=None, commit=True, notify=True):
    """(Re)compute and persist matches for one post, leg by leg.

    Returns the live Match rows for it. A post pairs with another once per pair of legs
    that fit, so two multi-stop itineraries sharing two hops produce two matches.
    """
    legs.sync_legs(trip)
    db.session.flush()                      # new legs need ids before a Match can point at them

    seen_pairs = set()
    results = []
    new_matches = []
    blocked = {}                            # trip_id -> same person? (asked once per post)

    for leg in legs.legs_of(trip):
        for cand_leg in leg_candidates(leg, include_unconfirmed=include_unconfirmed):
            cand = cand_leg.trip
            if cand.id not in blocked:
                blocked[cand.id] = _same_person(trip, cand)
            if blocked[cand.id]:
                continue
            score, criteria = score_pair(leg, cand_leg)
            a_id, b_id = Match.ordered_ids(trip.id, cand.id)
            leg_a, leg_b = (leg, cand_leg) if a_id == trip.id else (cand_leg, leg)
            existing = Match.query.filter_by(trip_a_id=a_id, trip_b_id=b_id,
                                             leg_a_id=leg_a.id, leg_b_id=leg_b.id).first()
            if score < MIN_SCORE:
                if existing and existing.status == 'suggested':
                    existing.status = 'dismissed'
                    existing.dismissed_reason = 'post_changed'
                continue
            seen_pairs.add((a_id, b_id, leg_a.id, leg_b.id))
            if existing:
                if existing.status == 'dismissed' and existing.dismissed_reason == 'post_changed':
                    existing.status = 'suggested'
                    existing.dismissed_reason = None
                existing.score, existing.criteria = score, criteria
                results.append(existing)
            else:
                m = Match(trip_a_id=a_id, trip_b_id=b_id,
                          leg_a_id=leg_a.id, leg_b_id=leg_b.id, score=score, criteria=criteria)
                db.session.add(m)
                results.append(m)
                new_matches.append(m)
                ActivityEvent.log('match_suggested', trip, actor=actor, other_trip_id=cand.id,
                                  score=score, leg=leg.label, their_leg=cand_leg.label)

    # Leg pairs that used to match but no longer pass the candidate filter
    for m in live_matches_for(trip):
        key = (m.trip_a_id, m.trip_b_id, m.leg_a_id, m.leg_b_id)
        if key not in seen_pairs and m.status == 'suggested':
            m.status = 'dismissed'
            m.dismissed_reason = 'post_changed'
    if commit:
        db.session.commit()
        if new_matches and notify:
            from app.services.bridge import alert_new_matches  # local import: bridge imports matching
            alert_new_matches(trip, new_matches, actor=actor)
    return results


def live_matches_for(trip):
    return Match.query.filter(
        ((Match.trip_a_id == trip.id) | (Match.trip_b_id == trip.id)),
        Match.status != 'dismissed',
    ).all()


def urgency_factor(trip):
    d = trip.days_to_departure
    if d is None:
        return 0.9
    if d <= 2:
        return 1.5
    if d <= 7:
        return 1.25
    if d <= 30:
        return 1.0
    return 0.85


def ranked_matches_for(trip, include_unconfirmed=False):
    """Live matches for a post, best first (score × urgency of the other side)."""
    ms = live_matches_for(trip)
    if not include_unconfirmed:
        ms = [m for m in ms if m.other_trip(trip.id).is_public]
    ms.sort(key=lambda m: (m.score * urgency_factor(m.other_trip(trip.id)), m.score), reverse=True)
    return ms


def _short_route(trip):
    o = trip.origin_iata or (trip.flying_from or '?')[:3].upper()
    d = trip.dest_iata or (trip.destination or '?')[:3].upper()
    return f"{o} → {d}"


def matches_for_user(user):
    """{other_trip_id: {'score', 'my_trip_id', 'my_route'}} for every live match between one of
    `user`'s posts and someone else's — best score per other post. Used to flag, while a user
    browses everyone's trips, the ones that already match something they posted."""
    my_posts = CompanionRequest.query.filter_by(user_id=user.id).all()
    my_ids = {t.id for t in my_posts}
    if not my_ids:
        return {}
    my_route = {t.id: _short_route(t) for t in my_posts}
    rows = Match.query.filter(
        Match.status != 'dismissed',
        (Match.trip_a_id.in_(my_ids)) | (Match.trip_b_id.in_(my_ids)),
    ).all()
    out = {}
    for m in rows:
        mine, other = (m.trip_a_id, m.trip_b_id) if m.trip_a_id in my_ids else (m.trip_b_id, m.trip_a_id)
        if other in my_ids:                 # a pair of the user's own posts: never a "match to me"
            continue
        cur = out.get(other)
        if cur is None or m.score > cur['score']:
            out[other] = {'score': m.score, 'my_trip_id': mine, 'my_route': my_route[mine]}
    return out


def dismiss_matches_for_closed_trip(trip):
    for m in live_matches_for(trip):
        m.status = 'dismissed'
        m.dismissed_reason = 'post_closed'
