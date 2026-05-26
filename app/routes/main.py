from flask import Blueprint, render_template, request, jsonify
from flask_login import current_user, login_required
from app.models import CompanionRequest, Feedback, ConnectionRequest
from datetime import date
import json, os

main_bp = Blueprint('main', __name__)

# Load airports once at startup
_airports = []
_airports_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'js', 'airports.json')
try:
    with open(_airports_path, encoding='utf-8') as _f:
        _airports = json.load(_f)
except Exception:
    pass

_airlines = []
_airlines_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'js', 'airlines.json')
try:
    with open(_airlines_path, encoding='utf-8') as _f:
        _airlines = json.load(_f)
except Exception:
    pass


@main_bp.route('/')
def index():
    approved_feedback = Feedback.query.filter_by(is_approved=True).order_by(Feedback.created_at.desc()).limit(6).all()
    return render_template('index.html', feedbacks=approved_feedback)


@main_bp.route('/about')
def about():
    return render_template('pages/about.html')


@main_bp.route('/terms')
def terms():
    return render_template('pages/terms.html')


@main_bp.route('/privacy')
def privacy():
    return render_template('pages/privacy.html')


@main_bp.route('/help')
def help_page():
    return render_template('pages/help.html')


@main_bp.route('/app')
def app_page():
    return render_template('pages/app_download.html')


@main_bp.route('/api/airports')
def airport_search():
    q = request.args.get('q', '').strip().lower()
    if len(q) < 2:
        return jsonify([])
    results = []
    for a in _airports:
        iata = a['iata'].lower()
        city = a['city'].lower()
        name = a['name'].lower()
        if iata.startswith(q) or city.startswith(q) or name.startswith(q) or q in city or q in iata:
            results.append(a)
            if len(results) == 8:
                break
    return jsonify(results)


@main_bp.route('/api/airlines')
def airline_search():
    q = request.args.get('q', '').strip().lower()
    if len(q) < 2:
        return jsonify([])
    results = []
    for a in _airlines:
        name = a['name'].lower()
        iata = a['iata'].lower()
        if name.startswith(q) or iata.startswith(q) or q in name:
            results.append(a)
            if len(results) == 8:
                break
    return jsonify(results)


@main_bp.route('/trips')
def all_trips():
    return render_template('trips/all_trips.html')


@main_bp.route('/api/search', methods=['POST'])
def search():
    data = request.get_json() or request.form
    sort = data.get('sort', 'newest')
    q = (data.get('q') or '').strip()
    limit = int(data.get('limit', 50))

    query = CompanionRequest.query.filter_by(is_active=True, travel_type='air')

    # Filter out expired
    today = date.today()
    query = query.filter(
        (CompanionRequest.from_date == None) | (CompanionRequest.from_date >= today)
    )

    # Optional field filters
    if data.get('flying_from'):
        query = query.filter(CompanionRequest.flying_from.ilike(f"%{data['flying_from']}%"))
    if data.get('destination'):
        query = query.filter(CompanionRequest.destination.ilike(f"%{data['destination']}%"))

    # Free-text search across route fields
    if q:
        pattern = f"%{q}%"
        query = query.filter(
            CompanionRequest.flying_from.ilike(pattern) |
            CompanionRequest.destination.ilike(pattern) |
            CompanionRequest.road_from.ilike(pattern) |
            CompanionRequest.road_to.ilike(pattern) |
            CompanionRequest.airline.ilike(pattern) |
            CompanionRequest.flight_number.ilike(pattern)
        )

    if sort == 'newest':
        query = query.order_by(CompanionRequest.created_at.desc())
    elif sort == 'date':
        query = query.order_by(CompanionRequest.from_date.asc())
    elif sort == 'destination':
        query = query.order_by(CompanionRequest.destination.asc())

    results = query.limit(limit).all()
    return jsonify({'results': [r.to_dict() for r in results], 'count': len(results)})


@main_bp.route('/connections')
@login_required
def connections_page():
    return render_template('connections.html')


@main_bp.route('/api/my-connections')
@login_required
def my_connections():
    # Requests I sent
    sent = ConnectionRequest.query.filter_by(requester_id=current_user.id).order_by(
        ConnectionRequest.created_at.desc()
    ).all()

    # Requests I received (on my trips)
    my_trip_ids = [t.id for t in CompanionRequest.query.filter_by(user_id=current_user.id).all()]
    received = ConnectionRequest.query.filter(
        ConnectionRequest.trip_id.in_(my_trip_ids)
    ).order_by(ConnectionRequest.created_at.desc()).all() if my_trip_ids else []

    def serialize(conn, role):
        trip = conn.trip
        from_loc = trip.flying_from or trip.road_from or '?'
        to_loc = trip.destination or trip.road_to or '?'
        travel_date = (trip.from_date or trip.road_from_date)
        other_user = None
        if role == 'sent':
            # I sent it — other person is the trip owner
            if not conn.recipient_anonymous and trip.author:
                other_user = {'username': trip.author.username, 'photo_url': trip.author.photo_url if trip.author.show_photo else None}
            else:
                other_user = {'username': 'Anonymous', 'photo_url': None}
        else:
            # I received it — other person is the requester
            if not conn.requester_anonymous and conn.requester:
                other_user = {'username': conn.requester.username, 'photo_url': conn.requester.photo_url if conn.requester.show_photo else None}
            else:
                other_user = {'username': 'Anonymous', 'photo_url': None}

        return {
            'id': conn.id,
            'trip_id': trip.id,
            'route': f"{from_loc} → {to_loc}",
            'travel_type': trip.travel_type,
            'travel_date': travel_date.isoformat() if travel_date else None,
            'status': conn.status,
            'role': role,
            'other_user': other_user,
            'created_at': conn.created_at.isoformat() if conn.created_at else None,
        }

    return jsonify({
        'sent': [serialize(c, 'sent') for c in sent],
        'received': [serialize(c, 'received') for c in received],
    })
