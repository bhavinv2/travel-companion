from flask import Blueprint, render_template, request, jsonify
from flask_login import current_user, login_required
from app.models import CompanionRequest, Feedback, ConnectionRequest, TRIP_ROLES
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


def _viewer_id():
    return current_user.id if current_user.is_authenticated else None


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
    data = request.get_json(silent=True) or request.form
    sort = data.get('sort', 'newest')
    q = (data.get('q') or '').strip()
    try:
        limit = int(data.get('limit', 50))
    except (TypeError, ValueError):
        limit = 50
    limit = max(1, min(limit, 200))

    query = CompanionRequest.query.filter(
        CompanionRequest.status.in_(['open', 'matched']),
        CompanionRequest.travel_type == 'air',
    )

    # Hide departed trips
    today = date.today()
    query = query.filter(
        (CompanionRequest.from_date == None) | (CompanionRequest.from_date >= today)  # noqa: E711
    )

    # Optional field filters
    if data.get('flying_from'):
        pat = f"%{data['flying_from']}%"
        query = query.filter(CompanionRequest.flying_from.ilike(pat) | CompanionRequest.origin_iata.ilike(pat))
    if data.get('destination'):
        pat = f"%{data['destination']}%"
        query = query.filter(CompanionRequest.destination.ilike(pat) | CompanionRequest.dest_iata.ilike(pat))
    if data.get('role') in TRIP_ROLES:
        query = query.filter(CompanionRequest.role == data['role'])
    if data.get('language'):
        from sqlalchemy import cast, String
        query = query.filter(cast(CompanionRequest.preferred_languages, String).ilike(f"%{data['language']}%"))
    if data.get('days'):
        try:
            from datetime import timedelta as _td2
            query = query.filter(CompanionRequest.from_date <= today + _td2(days=int(data['days'])))
        except (TypeError, ValueError):
            pass
    if data.get('from_date'):
        try:
            from datetime import datetime as _dt, timedelta as _td
            d = _dt.strptime(data['from_date'], '%Y-%m-%d').date()
            window = 7 if data.get('from_date_flexible') in ('on', 'true', True) else 3
            query = query.filter(CompanionRequest.from_date >= d - _td(days=window),
                                 CompanionRequest.from_date <= d + _td(days=window))
        except ValueError:
            pass

    # Free-text search across route fields
    if q:
        pattern = f"%{q}%"
        query = query.filter(
            CompanionRequest.flying_from.ilike(pattern) |
            CompanionRequest.destination.ilike(pattern) |
            CompanionRequest.origin_iata.ilike(pattern) |
            CompanionRequest.dest_iata.ilike(pattern) |
            CompanionRequest.airline.ilike(pattern) |
            CompanionRequest.flight_number.ilike(pattern)
        )

    if sort == 'date':
        query = query.order_by(CompanionRequest.from_date.asc())
    elif sort == 'destination':
        query = query.order_by(CompanionRequest.destination.asc())
    else:
        query = query.order_by(CompanionRequest.created_at.desc())

    results = query.limit(limit).all()
    vid = _viewer_id()
    return jsonify({'results': [r.to_dict(viewer_id=vid) for r in results], 'count': len(results)})


@main_bp.route('/dashboard')
@login_required
def dashboard():
    from app.services import matching
    my_posts = (CompanionRequest.query.filter_by(user_id=current_user.id)
                .order_by(CompanionRequest.created_at.desc()).all())
    match_rows = []
    for t in my_posts:
        if not t.is_public:
            continue
        for m in matching.ranked_matches_for(t):
            other = m.other_trip(t.id)
            match_rows.append({'trip': t, 'match': m, 'other': other,
                               'mine': m.party_for(t.id), 'theirs': m.party_for(other.id)})
    match_rows.sort(key=lambda r: (r['match'].status == 'connected', -r['match'].score))
    return render_template('dashboard.html', my_posts=my_posts, match_rows=match_rows)


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
        travel_date = (trip.from_date or trip.road_from_date)
        if role == 'sent':
            if not conn.recipient_anonymous and trip.author:
                other_user = {'username': trip.author.username,
                              'photo_url': trip.author.photo_url if trip.author.show_photo else None}
            elif not conn.recipient_anonymous and not trip.author:
                other_user = {'username': trip.display_name, 'photo_url': None}
            else:
                other_user = {'username': 'Anonymous', 'photo_url': None}
        else:
            if not conn.requester_anonymous and conn.requester:
                other_user = {'username': conn.requester.username,
                              'photo_url': conn.requester.photo_url if conn.requester.show_photo else None}
            else:
                other_user = {'username': 'Anonymous', 'photo_url': None}

        return {
            'id': conn.id,
            'trip_id': trip.id,
            'route': trip.route_display,
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
