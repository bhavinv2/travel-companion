from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from app import db, mail
from app.models import CompanionRequest, User, Notification, ChatRoom, ConnectionRequest
from flask_mail import Message as MailMessage
from datetime import datetime, date

trips_bp = Blueprint('trips', __name__)


def notify_connected_users(trip, notification_type, title, body):
    rooms = ChatRoom.query.filter(
        (ChatRoom.trip_id == trip.id) |
        (ChatRoom.user1_id == trip.user_id) |
        (ChatRoom.user2_id == trip.user_id)
    ).all()
    notified = set()
    for room in rooms:
        other_id = room.user2_id if room.user1_id == trip.user_id else room.user1_id
        if other_id not in notified:
            notif = Notification(
                user_id=other_id,
                type=notification_type,
                title=title,
                body=body,
                link=f"/",
            )
            db.session.add(notif)
            notified.add(other_id)
    db.session.commit()


@trips_bp.route('/post-trip', methods=['POST'])
@login_required
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
        return v

    def parse_date(s):
        if not s:
            return None
        try:
            return datetime.strptime(s, '%Y-%m-%d').date()
        except Exception:
            return None

    trip_type = get('trip_type')

    # Multi-destination: legs come as JSON array in 'legs' key
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
                'from': leg.get('from', ''),
                'to': leg.get('to', ''),
                'date': leg.get('date', ''),
                'airline': leg.get('airline', ''),
                'flight_number': leg.get('flight_number', ''),
            }
            for leg in raw_legs if leg.get('from') or leg.get('to')
        ]
        # Derive summary fields from first/last leg for search/display
        flying_from = legs[0]['from'] if legs else None
        destination = legs[-1]['to'] if legs else None
        from_date = parse_date(legs[0]['date']) if legs else None
        to_date = parse_date(legs[-1]['date']) if legs else None
    else:
        flying_from = get('flying_from')
        destination = get('destination')
        from_date = parse_date(get('from_date'))
        # one_way has no return date
        to_date = parse_date(get('to_date')) if trip_type == 'round_trip' else None

    trip = CompanionRequest(
        user_id=current_user.id,
        travel_type=get('travel_type', 'air'),
        trip_type=trip_type,
        on_behalf_of=get('on_behalf_of'),
        connect_me_to=get_list('connect_me_to'),
        traveller_needs=get_list('traveller_needs'),
        special_needs_notes=get('special_needs_notes'),
        flying_from=flying_from,
        flying_from_flexible=get('flying_from_flexible') in ('true', 'on', True),
        destination=destination,
        destination_flexible=get('destination_flexible') in ('true', 'on', True),
        from_date=from_date,
        from_date_flexible=get('from_date_flexible') in ('true', 'on', True),
        to_date=to_date,
        to_date_flexible=get('to_date_flexible') in ('true', 'on', True),
        airline=get('airline') if trip_type != 'multi_destination' else None,
        flight_number=get('flight_number') if trip_type != 'multi_destination' else None,
        legs=legs,
        preferred_languages=get_list('preferred_languages'),
        additional_comments=get('additional_comments'),
        ticket_booked=get('ticket_booked') in ('true', 'on', True),
        category=get('category'),
        is_anonymous=get('is_anonymous') in ('true', 'on', True),
        expires_at=to_date or from_date,
    )

    try:
        db.session.add(trip)
        db.session.commit()
        return jsonify({'success': True, 'trip': trip.to_dict()}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@trips_bp.route('/trip/<int:trip_id>', methods=['PUT'])
@login_required
def modify_trip(trip_id):
    trip = CompanionRequest.query.get_or_404(trip_id)
    if trip.user_id != current_user.id and not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403

    data = request.get_json() or {}
    fields = ['flying_from', 'destination', 'airline', 'flight_number', 'category',
              'on_behalf_of', 'ticket_booked', 'is_anonymous', 'special_needs_notes',
              'road_from', 'road_to', 'travelling_by']
    for field in fields:
        if field in data:
            setattr(trip, field, data[field])

    trip.updated_at = datetime.utcnow()

    try:
        db.session.commit()
        notify_connected_users(
            trip,
            'trip_modified',
            'Trip Updated',
            f'A trip you connected on has been modified by {current_user.username}.'
        )
        return jsonify({'success': True, 'trip': trip.to_dict()})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@trips_bp.route('/trip/<int:trip_id>', methods=['DELETE'])
@login_required
def disable_trip(trip_id):
    trip = CompanionRequest.query.get_or_404(trip_id)
    if trip.user_id != current_user.id and not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403

    trip.is_active = False
    try:
        db.session.commit()
        notify_connected_users(
            trip,
            'trip_cancelled',
            'Trip Cancelled',
            f'A trip posted by {current_user.username} has been cancelled.'
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
    return jsonify({'trips': [t.to_dict() for t in trips]})


@trips_bp.route('/connect/<int:trip_id>', methods=['POST'])
@login_required
def send_connection(trip_id):
    trip = CompanionRequest.query.get_or_404(trip_id)
    if trip.user_id == current_user.id:
        return jsonify({'error': 'Cannot connect to your own trip'}), 400

    existing = ConnectionRequest.query.filter_by(
        requester_id=current_user.id, trip_id=trip_id
    ).filter(ConnectionRequest.status.in_(['pending', 'accepted'])).first()
    if existing:
        return jsonify({'error': 'already_requested'}), 409

    data = request.get_json() or {}
    conn = ConnectionRequest(
        requester_id=current_user.id,
        trip_id=trip_id,
        requester_anonymous=data.get('anonymous', False),
    )
    db.session.add(conn)
    db.session.flush()

    requester_name = 'Someone' if conn.requester_anonymous else current_user.username
    notif = Notification(
        user_id=trip.user_id,
        type='connection_request',
        title='New Connection Request',
        body=f'{requester_name} wants to connect on your trip from {trip.flying_from or trip.road_from} to {trip.destination or trip.road_to}.',
        connection_id=conn.id,
    )
    db.session.add(notif)
    db.session.commit()
    return jsonify({'success': True, 'connection_id': conn.id})


@trips_bp.route('/connect/<int:connection_id>/respond', methods=['POST'])
@login_required
def respond_connection(connection_id):
    conn = ConnectionRequest.query.get_or_404(connection_id)
    trip = CompanionRequest.query.get(conn.trip_id)
    if trip.user_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403
    if conn.status != 'pending':
        return jsonify({'error': 'Already responded'}), 400

    data = request.get_json() or {}
    action = data.get('action')  # 'accept' or 'deny'
    if action not in ('accept', 'deny'):
        return jsonify({'error': 'Invalid action'}), 400

    conn.status = 'accepted' if action == 'accept' else 'denied'
    conn.recipient_anonymous = data.get('anonymous', False)

    recipient_name = 'Someone' if conn.recipient_anonymous else current_user.username
    if action == 'accept':
        notif_title = 'Connection Accepted!'
        notif_body = f'{recipient_name} accepted your connection request.'
        notif_type = 'connection_accepted'
        if not conn.requester_anonymous and not conn.recipient_anonymous:
            ChatRoom.get_or_create(conn.requester_id, trip.user_id, trip.id)
    else:
        notif_title = 'Connection Declined'
        notif_body = f'Your connection request was not accepted this time.'
        notif_type = 'connection_denied'

    notif = Notification(
        user_id=conn.requester_id,
        type=notif_type,
        title=notif_title,
        body=notif_body,
        connection_id=conn.id,
    )
    db.session.add(notif)
    db.session.commit()
    return jsonify({'success': True})
