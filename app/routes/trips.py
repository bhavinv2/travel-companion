from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from app import db
from app.models import (CompanionRequest, Notification, ChatRoom, ConnectionRequest, ContactPoint,
                        ActivityEvent, TRIP_ROLES, AGE_GROUPS, GENDERS, PREF_GENDERS)
from app.services.locations import apply_route
from app.services.contacts import parse_contact_rows
from app.services import matching
from app.services.ratelimit import rate_limit
from datetime import datetime

trips_bp = Blueprint('trips', __name__)


def notify_connected_users(trip, notification_type, title, body):
    """Notify everyone who requested a connection on THIS trip (pending or accepted)."""
    conns = ConnectionRequest.query.filter(ConnectionRequest.trip_id == trip.id,
                                           ConnectionRequest.status.in_(['pending', 'accepted'])).all()
    from app.services import notify
    notified = set()
    for c in conns:
        if c.requester_id in notified or c.requester_id == trip.user_id:
            continue
        notify.push(c.requester_id, notification_type, title=title, body=body, link='/connections',
                    connection_id=c.id)
        notified.add(c.requester_id)
    db.session.commit()


def _truthy(v):
    return v in ('true', 'on', True, 1, '1')


def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, '%Y-%m-%d').date()
    except Exception:
        return None


def _parse_travellers(raw):
    """Normalise the per-person travellers list from the post form.

    Accepts a JSON string or an already-decoded list. Returns a clean list of
    {who, age_group, gender, needs:[...]} dicts, dropping empty rows.
    """
    if isinstance(raw, str):
        import json as _json
        try:
            raw = _json.loads(raw)
        except Exception:
            raw = []
    if not isinstance(raw, list):
        return []
    out = []
    for t in raw:
        if not isinstance(t, dict):
            continue
        who = (t.get('who') or '').strip()[:50]
        if not who:
            continue
        age = t.get('age_group')
        gender = t.get('gender')
        needs = t.get('needs') or []
        if not isinstance(needs, list):
            needs = []
        out.append({
            'who': who,
            'age_group': age if age in AGE_GROUPS else None,
            'gender': gender if gender in GENDERS else None,
            'needs': [str(n)[:60] for n in needs if n][:12],
        })
    return out[:20]


@trips_bp.route('/post-trip', methods=['POST'])
@login_required
@rate_limit(10, 3600)
def post_trip():
    data = request.get_json() or request.form.to_dict(flat=False)

    def get(key, default=None):
        v = data.get(key, default)
        if isinstance(v, list):
            return v[0] if v else default
        return v

    def get_list(key):
        v = data.get(key, [])
        if isinstance(v, str):
            return [v]
        return v or []

    trip_type = get('trip_type') or 'one_way'
    errors = []

    legs = None
    if trip_type == 'multi_destination':
        raw_legs = data.get('legs', [])
        if isinstance(raw_legs, str):
            import json as _json
            try:
                raw_legs = _json.loads(raw_legs)
            except Exception:
                raw_legs = []
        legs = [
            {
                'from': (leg.get('from') or '')[:200],
                'to': (leg.get('to') or '')[:200],
                'date': leg.get('date', ''),
                'airline': (leg.get('airline') or '')[:200],
                'flight_number': (leg.get('flight_number') or '')[:30],
            }
            for leg in raw_legs if leg.get('from') or leg.get('to')
        ]
        flying_from = legs[0]['from'] if legs else None
        destination = legs[-1]['to'] if legs else None
        from_date = _parse_date(legs[0]['date']) if legs else None
        to_date = _parse_date(legs[-1]['date']) if legs else None
        if len(legs) < 2:
            errors.append('Add at least two stops for a multi-destination trip.')
    else:
        flying_from = (get('flying_from') or '').strip()[:200] or None
        destination = (get('destination') or '').strip()[:200] or None
        from_date = _parse_date(get('from_date'))
        to_date = _parse_date(get('to_date')) if trip_type == 'round_trip' else None

    if not flying_from or not destination:
        errors.append('Please enter where you are flying from and to.')
    if not from_date:
        errors.append('Please pick a departure date.')

    role = get('role') if get('role') in TRIP_ROLES else 'seeking_help'
    pref_gender = get('pref_gender') if get('pref_gender') in PREF_GENDERS else 'any'

    def _int(v):
        try:
            return int(v) if v not in (None, '') else None
        except (TypeError, ValueError):
            return None

    # Contact points (Phase 2): rows + one global consent checkbox
    contact_rows, contact_errors = parse_contact_rows(data.get('contact_points') or [])
    errors += contact_errors
    consent = _truthy(get('contact_consent'))

    travellers = _parse_travellers(data.get('travellers'))
    # One companion is matched for the whole group, so the trip-level fields the matcher and
    # cards read collapse the group: who = every tag, needs = the union, age/gender = the
    # first traveller's. Derived here so it holds no matter what the client sent.
    if travellers:
        summary_on_behalf = ','.join(t['who'] for t in travellers if t['who'])[:50] or None
        summary_needs = list(dict.fromkeys(n for t in travellers for n in t['needs']))
        summary_age = travellers[0]['age_group']
        summary_gender = travellers[0]['gender']
    else:
        summary_on_behalf = ','.join(x for x in get_list('on_behalf_of') if x)[:50] or None
        summary_needs = get_list('traveller_needs')
        summary_age = get('traveler_age_group') if get('traveler_age_group') in AGE_GROUPS else None
        summary_gender = get('traveler_gender') if get('traveler_gender') in GENDERS else None

    if errors:
        return jsonify({'success': False, 'error': ' '.join(errors)}), 400

    trip = CompanionRequest(
        user_id=current_user.id,
        source='organic',
        poster_name=current_user.full_name,
        travel_type=get('travel_type', 'air') or 'air',
        trip_type=trip_type,
        role=role,
        on_behalf_of=summary_on_behalf,
        connect_me_to=get_list('connect_me_to'),
        traveller_needs=summary_needs,
        travellers=travellers or None,
        special_needs_notes=(get('special_needs_notes') or '').strip() or None,
        flying_from=flying_from,
        flying_from_flexible=_truthy(get('flying_from_flexible')),
        destination=destination,
        destination_flexible=_truthy(get('destination_flexible')),
        from_date=from_date,
        from_date_flexible=_truthy(get('from_date_flexible')),
        to_date=to_date,
        to_date_flexible=_truthy(get('to_date_flexible')),
        airline=((get('airline') or '').strip()[:200] or None) if trip_type != 'multi_destination' else None,
        flight_number=((get('flight_number') or '').strip()[:30] or None) if trip_type != 'multi_destination' else None,
        return_airline=((get('return_airline') or '').strip()[:200] or None) if trip_type == 'round_trip' else None,
        return_flight_number=((get('return_flight_number') or '').strip()[:30] or None) if trip_type == 'round_trip' else None,
        legs=legs,
        preferred_languages=get_list('preferred_languages'),
        traveler_age_group=summary_age,
        traveler_gender=summary_gender,
        pref_gender=pref_gender,
        pref_age_min=_int(get('pref_age_min')),
        pref_age_max=_int(get('pref_age_max')),
        additional_comments=(get('additional_comments') or '').strip() or None,
        ticket_booked=_truthy(get('ticket_booked')),
        category=get('category'),
        is_anonymous=_truthy(get('is_anonymous')),
        expires_at=to_date or from_date,
        claimed_at=datetime.utcnow(),
    )
    trip.set_status('open')
    apply_route(trip)

    try:
        db.session.add(trip)
        db.session.flush()
        # Every account holder can always be reached through in-app chat.
        db.session.add(ContactPoint(trip=trip, user_id=current_user.id, type='inapp_chat', value='inapp',
                                    consent_to_share=True, added_by='owner'))
        for r in contact_rows:
            db.session.add(ContactPoint(trip=trip, user_id=current_user.id, type=r['type'], value=r['value'],
                                        label=r['label'] or None, consent_to_share=consent, added_by='owner'))
        ActivityEvent.log('post_created', trip, actor=current_user, source='organic',
                          contact_types=sorted({r['type'] for r in contact_rows}), consent=consent)
        db.session.commit()
        # Instant matching (plan §9): compute now so the UI can show "N possible matches" immediately.
        found = matching.compute_matches_for(trip, actor=current_user)
        d = trip.to_dict(viewer_id=current_user.id)
        d['matches_count'] = len(found)
        return jsonify({'success': True, 'trip': d, 'matches_count': len(found)}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@trips_bp.route('/parse-ticket', methods=['POST'])
@login_required
@rate_limit(20, 3600)
def parse_ticket():
    """Read an uploaded e-ticket and return suggested form values. Nothing is stored here —
    the file is attached to the post later, through the normal private-upload path."""
    from app.services import ticket_parser
    f = request.files.get('ticket')
    if not f or not f.filename:
        return jsonify({'ok': False, 'fields': {}, 'found': [],
                        'message': 'Choose your e-ticket file first.'}), 400
    result = ticket_parser.parse_upload(f.stream, f.filename)
    return jsonify(result)


@trips_bp.route('/trip/<int:trip_id>', methods=['GET'])
@login_required
def get_trip(trip_id):
    trip = CompanionRequest.query.get_or_404(trip_id)
    if trip.user_id != current_user.id and not current_user.is_cs:
        return jsonify({'error': 'Unauthorized'}), 403
    d = trip.to_dict(viewer_id=current_user.id)
    d['contact_points'] = [cp.to_dict(reveal_value=True) for cp in trip.contact_points]
    return jsonify({'trip': d})


@trips_bp.route('/trip/<int:trip_id>', methods=['PUT'])
@login_required
def modify_trip(trip_id):
    trip = CompanionRequest.query.get_or_404(trip_id)
    if trip.user_id != current_user.id and not current_user.is_cs:
        return jsonify({'error': 'Unauthorized'}), 403

    data = request.get_json() or {}
    fields = ['flying_from', 'destination', 'airline', 'flight_number', 'category',
              'return_airline', 'return_flight_number',
              'on_behalf_of', 'ticket_booked', 'is_anonymous', 'special_needs_notes',
              'road_from', 'road_to', 'travelling_by', 'additional_comments', 'role',
              'traveler_age_group', 'traveler_gender', 'pref_gender', 'pref_age_min', 'pref_age_max',
              'flying_from_flexible', 'destination_flexible', 'from_date_flexible', 'to_date_flexible']
    for field in fields:
        if field in data:
            v = data[field]
            if isinstance(v, str):
                v = v.strip()[:500] or None
            setattr(trip, field, v)
    for dfield in ('from_date', 'to_date'):
        if dfield in data:
            setattr(trip, dfield, _parse_date(data[dfield]))
    # A post can change shape here, not only its values: one-way <-> round trip <-> a
    # multi-stop itinerary. The legs are rebuilt from whatever shape arrives, so matching
    # follows immediately -- that is the whole reason editing these was blocked before.
    new_type = data.get('trip_type')
    if new_type in ('one_way', 'round_trip', 'multi_destination'):
        trip.trip_type = new_type

    if trip.trip_type == 'multi_destination':
        legs = []
        for leg in (data.get('legs') or []):
            frm = (leg.get('from') or '').strip()[:200]
            to = (leg.get('to') or '').strip()[:200]
            if not (frm or to):
                continue
            legs.append({'from': frm, 'to': to, 'date': (leg.get('date') or '')[:10],
                         'airline': (leg.get('airline') or '').strip()[:200] or None,
                         'flight_number': (leg.get('flight_number') or '').strip()[:30] or None})
        if len(legs) < 2:
            db.session.rollback()
            return jsonify({'error': 'A multi-stop trip needs at least two stops.'}), 400
        if any(not (l['from'] and l['to'] and l['date']) for l in legs):
            db.session.rollback()
            return jsonify({'error': 'Every stop needs a from, a to and a date.'}), 400
        trip.legs = legs
        # the post's own columns describe the whole journey: first origin, last destination
        trip.flying_from = legs[0]['from']
        trip.destination = legs[-1]['to']
        trip.from_date = _parse_date(legs[0]['date'])
        trip.to_date = _parse_date(legs[-1]['date'])
        trip.airline = None
        trip.flight_number = None
    else:
        trip.legs = None
        if trip.trip_type == 'one_way':
            trip.to_date = None
    if trip.trip_type != 'round_trip':
        trip.return_airline = None
        trip.return_flight_number = None

    if not trip.flying_from or not trip.destination or not trip.from_date:
        db.session.rollback()
        return jsonify({'error': 'Route and departure date are required.'}), 400
    if trip.trip_type == 'round_trip' and not trip.to_date:
        db.session.rollback()
        return jsonify({'error': 'A round trip needs a return date.'}), 400
    for lfield in ('connect_me_to', 'traveller_needs', 'preferred_languages'):
        if lfield in data and isinstance(data[lfield], list):
            setattr(trip, lfield, data[lfield])
    if 'travellers' in data:
        travellers = _parse_travellers(data.get('travellers'))
        trip.travellers = travellers or None
        # Keep the trip-level summary fields in step with the group: one companion is
        # matched for everyone, so age/gender collapse to the first traveller and needs
        # are the union across the group.
        if travellers:
            trip.on_behalf_of = (','.join(t['who'] for t in travellers if t['who'])[:50] or None)
            trip.traveller_needs = list(dict.fromkeys(n for t in travellers for n in t['needs']))
            trip.traveler_age_group = travellers[0]['age_group']
            trip.traveler_gender = travellers[0]['gender']
    if trip.role not in TRIP_ROLES:
        trip.role = 'seeking_help'
    apply_route(trip)
    trip.expires_at = trip.to_date or trip.from_date
    trip.updated_at = datetime.utcnow()

    try:
        ActivityEvent.log('post_updated', trip, actor=current_user)
        db.session.commit()
        matching.compute_matches_for(trip, actor=current_user)
        notify_connected_users(
            trip,
            'trip_modified',
            'Trip Updated',
            f'A trip you connected on ({trip.route_display}) has been modified.'
        )
        return jsonify({'success': True, 'trip': trip.to_dict(viewer_id=current_user.id)})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@trips_bp.route('/trip/<int:trip_id>', methods=['DELETE'])
@login_required
def disable_trip(trip_id):
    trip = CompanionRequest.query.get_or_404(trip_id)
    if trip.user_id != current_user.id and not current_user.is_cs:
        return jsonify({'error': 'Unauthorized'}), 403

    data = request.get_json(silent=True) or {}
    reason = data.get('reason') if data.get('reason') in ('information_shared', 'no_longer_required', 'travelled') else 'no_longer_required'
    trip.set_status('closed', reason=reason, by=current_user)
    try:
        ActivityEvent.log('post_closed', trip, actor=current_user, reason=reason)
        matching.dismiss_matches_for_closed_trip(trip)
        db.session.commit()
        notify_connected_users(
            trip,
            'trip_cancelled',
            'Trip Cancelled',
            f'A trip you connected on ({trip.route_display}) has been cancelled.'
        )
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@trips_bp.route('/my-trips', methods=['GET'])
@login_required
def my_trips():
    trips = CompanionRequest.query.filter_by(user_id=current_user.id).order_by(
        CompanionRequest.created_at.desc()
    ).all()
    out = []
    for t in trips:
        d = t.to_dict(viewer_id=current_user.id)
        ms = matching.ranked_matches_for(t) if t.is_public else []
        d['matches_count'] = len(ms)
        # Per-leg tallies, so a multi-leg post can offer "which leg?" before opening the
        # matches panel. Always sent (a one-way post simply has one entry) and always in
        # travel order, including legs with nothing on them yet.
        per_leg = {}
        for m in ms:
            leg = m.leg_for(t.id)
            if leg is not None:
                per_leg[leg.id] = per_leg.get(leg.id, 0) + 1
        d['legs_summary'] = [{**leg.to_dict(), 'matches': per_leg.get(leg.id, 0)}
                             for leg in sorted(t.leg_rows, key=lambda r: r.seq)]
        out.append(d)
    return jsonify({'trips': out})


@trips_bp.route('/connect/<int:trip_id>', methods=['POST'])
@login_required
@rate_limit(30, 3600)
def send_connection(trip_id):
    trip = CompanionRequest.query.get_or_404(trip_id)
    if trip.user_id == current_user.id:
        return jsonify({'error': 'Cannot connect to your own trip'}), 400
    if not trip.is_public:
        return jsonify({'error': 'This trip is no longer open.'}), 400

    existing = ConnectionRequest.query.filter_by(
        requester_id=current_user.id, trip_id=trip_id
    ).filter(ConnectionRequest.status.in_(['pending', 'accepted'])).first()
    if existing:
        return jsonify({'error': 'already_requested'}), 409

    data = request.get_json() or {}
    conn = ConnectionRequest(
        requester_id=current_user.id,
        trip_id=trip_id,
        requester_anonymous=bool(data.get('anonymous', False)),
    )
    db.session.add(conn)
    db.session.flush()

    requester_name = 'Someone' if conn.requester_anonymous else current_user.username
    # Owner-less (CS-created) posts route the request to the CS agent who created them.
    recipient_id = trip.user_id or trip.created_by_id
    if recipient_id:
        from app.services import notify
        notify.push(recipient_id, 'connection_request', title='New Connection Request',
                    body=f'{requester_name} wants to connect on the trip {trip.route_display}.',
                    link='/connections' if trip.user_id else f'/cs/posts/{trip.id}', connection_id=conn.id)
    ActivityEvent.log('connection_requested', trip, actor=current_user, connection_id=conn.id)
    db.session.commit()
    return jsonify({'success': True, 'connection_id': conn.id})


@trips_bp.route('/connect/<int:connection_id>/respond', methods=['POST'])
@login_required
def respond_connection(connection_id):
    conn = ConnectionRequest.query.get_or_404(connection_id)
    trip = db.session.get(CompanionRequest, conn.trip_id)
    is_owner = trip.user_id == current_user.id
    is_cs_for_ownerless = trip.user_id is None and current_user.is_cs
    if not (is_owner or is_cs_for_ownerless):
        return jsonify({'error': 'Unauthorized'}), 403
    if conn.status != 'pending':
        return jsonify({'error': 'Already responded'}), 400

    data = request.get_json() or {}
    action = data.get('action')  # 'accept' or 'deny'
    if action not in ('accept', 'deny'):
        return jsonify({'error': 'Invalid action'}), 400

    conn.status = 'accepted' if action == 'accept' else 'denied'
    conn.recipient_anonymous = bool(data.get('anonymous', False))

    recipient_name = 'Someone' if conn.recipient_anonymous else (trip.display_name if is_owner else 'The Connecting Desis team')
    if action == 'accept':
        notif_title = 'Connection Accepted!'
        notif_body = f'{recipient_name} accepted your connection request.'
        notif_type = 'connection_accepted'
        if trip.user_id and not conn.requester_anonymous and not conn.recipient_anonymous:
            ChatRoom.get_or_create(conn.requester_id, trip.user_id, trip.id)
    else:
        notif_title = 'Connection Declined'
        notif_body = 'Your connection request was not accepted this time.'
        notif_type = 'connection_denied'

    from app.services import notify
    notify.push(conn.requester_id, notif_type, title=notif_title, body=notif_body, link='/connections',
                connection_id=conn.id)
    ActivityEvent.log(f'connection_{conn.status}', trip, actor=current_user, connection_id=conn.id)
    db.session.commit()
    return jsonify({'success': True})
