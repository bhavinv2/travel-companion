"""Matching engine: candidate selection, explainable scoring, persistence of Match rows.

Weights and sub-scores follow doc/PHASE2_PLAN_ANALYSIS.md §6. Every criterion returns a 0-100 sub-score and a
human-readable detail so the UI can show "why" next to the percentage.
"""
import re
from datetime import date, timedelta

from app import db
from app.models import CompanionRequest, Match, ActivityEvent

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


def score_role(a, b):
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
    """Return (total 0-100, criteria list)."""
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

def candidates_for(trip, include_unconfirmed=False):
    if not trip.from_date:
        return []
    statuses = ['open', 'matched'] + (['unconfirmed'] if include_unconfirmed else [])
    q = CompanionRequest.query.filter(
        CompanionRequest.id != trip.id,
        CompanionRequest.travel_type == 'air',
        CompanionRequest.status.in_(statuses),
        CompanionRequest.from_date >= trip.from_date - timedelta(days=DATE_WINDOW_DAYS),
        CompanionRequest.from_date <= trip.from_date + timedelta(days=DATE_WINDOW_DAYS),
        CompanionRequest.from_date >= date.today() - timedelta(days=1),
    )
    if trip.origin_metro and trip.dest_metro:
        q = q.filter(CompanionRequest.origin_metro == trip.origin_metro,
                     CompanionRequest.dest_metro == trip.dest_metro)
    elif trip.origin_iata and trip.dest_iata:
        q = q.filter(CompanionRequest.origin_iata == trip.origin_iata,
                     CompanionRequest.dest_iata == trip.dest_iata)
    else:
        return []
    if trip.user_id:
        q = q.filter((CompanionRequest.user_id != trip.user_id) | (CompanionRequest.user_id.is_(None)))
    return q.all()


def _same_person(a, b):
    """Two posts by the same account or sharing a contact value are never matched to each other."""
    if a.user_id and a.user_id == b.user_id:
        return True
    va = {(cp.type, cp.value) for cp in a.contact_points if cp.type != 'inapp_chat'}
    vb = {(cp.type, cp.value) for cp in b.contact_points if cp.type != 'inapp_chat'}
    return bool(va & vb)


def compute_matches_for(trip, include_unconfirmed=False, actor=None, commit=True):
    """(Re)compute and persist matches for one post. Returns the list of live Match rows for it."""
    seen_pairs = set()
    results = []
    new_matches = []
    for cand in candidates_for(trip, include_unconfirmed=include_unconfirmed):
        if _same_person(trip, cand):
            continue
        score, criteria = score_pair(trip, cand)
        a_id, b_id = Match.ordered_ids(trip.id, cand.id)
        existing = Match.query.filter_by(trip_a_id=a_id, trip_b_id=b_id).first()
        if score < MIN_SCORE:
            if existing and existing.status == 'suggested':
                existing.status = 'dismissed'
                existing.dismissed_reason = 'post_changed'
            continue
        seen_pairs.add((a_id, b_id))
        if existing:
            if existing.status == 'dismissed' and existing.dismissed_reason == 'post_changed':
                existing.status = 'suggested'
                existing.dismissed_reason = None
            existing.score, existing.criteria = score, criteria
            results.append(existing)
        else:
            m = Match(trip_a_id=a_id, trip_b_id=b_id, score=score, criteria=criteria)
            db.session.add(m)
            results.append(m)
            new_matches.append(m)
            ActivityEvent.log('match_suggested', trip, actor=actor, other_trip_id=cand.id, score=score)
    # Pairs that used to match but no longer pass the candidate filter
    for m in live_matches_for(trip):
        pair = Match.ordered_ids(m.trip_a_id, m.trip_b_id)
        if pair not in seen_pairs and m.status == 'suggested':
            m.status = 'dismissed'
            m.dismissed_reason = 'post_changed'
    if commit:
        db.session.commit()
        if new_matches:
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


def dismiss_matches_for_closed_trip(trip):
    for m in live_matches_for(trip):
        m.status = 'dismissed'
        m.dismissed_reason = 'post_closed'
