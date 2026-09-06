from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, flash
from app import options
from flask_login import current_user, login_required
from app.models import CompanionRequest, Feedback, ConnectionRequest, TripLeg, TRIP_ROLES
from datetime import date
from app.services.ratelimit import rate_limit
import json, os, re

main_bp = Blueprint('main', __name__)


def _viewer_id():
    return current_user.id if current_user.is_authenticated else None


# Staff (CS / admin) work in their consoles only: the traveller screens redirect them there.
STAFF_REDIRECT_ENDPOINTS = {'main.index', 'main.all_trips', 'main.dashboard', 'main.connections_page', 'chat.inbox'}


def staff_home(user):
    """Where a staff account lands: admins on the admin panel, CS agents on the CS console."""
    from flask import url_for
    if user.is_admin:
        return url_for('admin.dashboard')
    if user.is_cs:
        return url_for('cs.home')
    return url_for('main.index')


def staff_view_active(user=None):
    """True while a CS/admin account uses the staff console (the default); multi-role accounts can switch.

    Safe outside a request (CLI jobs render e-mail templates, which runs the context processors)."""
    from flask import has_request_context
    if user is None:
        if not has_request_context():
            return False
        user = current_user
    if not getattr(user, 'is_authenticated', False):
        return False
    return bool(user.is_cs and session.get('view') != 'traveller')


@main_bp.before_app_request
def _staff_to_console():
    if request.endpoint in STAFF_REDIRECT_ENDPOINTS and staff_view_active():
        return redirect(staff_home(current_user))


@main_bp.app_context_processor
def _inject_staff_home():
    staff = staff_view_active()
    return {'staff_home': staff_home, 'is_staff': staff,
            'can_switch_view': bool(staff and current_user.is_traveller)}


@main_bp.route('/switch-view/<view>')
@login_required
def switch_view(view):
    """Accounts holding both a traveller role and a staff role flip between the two experiences."""
    if view == 'traveller':
        if not (current_user.is_cs and current_user.is_traveller):
            flash('This account has no traveller role.', 'danger')
            return redirect(staff_home(current_user))
        session['view'] = 'traveller'
        return redirect(url_for('main.dashboard'))
    session.pop('view', None)
    if view == 'cs' and current_user.is_cs:
        return redirect(url_for('cs.home'))
    if view == 'admin' and current_user.is_admin:
        return redirect(url_for('admin.dashboard'))
    return redirect(staff_home(current_user))


@main_bp.route('/')
def index():
    approved_feedback = (Feedback.query.filter_by(is_approved=True, is_featured=True)
                         .order_by(Feedback.created_at.desc()).limit(6).all())
    if not approved_feedback:   # nothing hand-picked yet: the newest approved keep the section alive
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


def _validate_contact(form):
    """Shared by the /contact page and the home-page widget. Returns a list of errors."""
    from app.routes.auth import EMAIL_RE
    errors = []
    if not form['name']:
        errors.append('Please tell us your name.')
    if not EMAIL_RE.match(form['email'] or ''):
        errors.append('Please enter an e-mail address we can reply to.')
    if form['phone'] and not re.fullmatch(r'[\d\s()+-]{7,20}', form['phone']):
        errors.append('That phone number does not look right - digits, spaces, + and - only.')
    if len(form['message']) < 10:
        errors.append('Please write a little more so we can help (at least 10 characters).')
    return errors


def _save_contact(form):
    """Store the enquiry and let the CS team know. Returns the ContactMessage."""
    from app import db
    from app.models import ContactMessage, ActivityEvent, User
    from app.services import notify
    msg = ContactMessage(
        name=form['name'][:120], email=form['email'].lower()[:255],
        phone=form['phone'][:30] or None, message=form['message'][:4000],
        user_id=current_user.id if current_user.is_authenticated else None)
    db.session.add(msg)
    db.session.flush()
    ActivityEvent.log('contact_message_received',
                      actor=(current_user if current_user.is_authenticated else None),
                      contact_id=msg.id, email=msg.email)
    for agent in User.query.filter(User.role.in_(['cs', 'admin']), User.is_active.is_(True)).limit(20).all():
        notify.push(agent.id, 'cs_escalation', title='New contact message',
                    body=f'{msg.name} <{msg.email}>: {msg.message[:90]}', link='/cs/contact')
    db.session.commit()
    return msg


def _contact_fields(src):
    return {k: (src.get(k) or '').strip() for k in ('name', 'email', 'phone', 'message')}


@main_bp.route('/contact', methods=['GET', 'POST'])
@rate_limit(6, 3600)
def contact():
    """Contact us. Works signed-out on purpose - someone who cannot log in most needs it."""
    form = {}
    if request.method == 'POST':
        form = _contact_fields(request.form)
        errors = _validate_contact(form)
        if not errors:
            msg = _save_contact(form)
            flash('Thanks - we have your message and will reply to ' + msg.email + '.', 'success')
            return redirect(url_for('main.contact'))
        for e in errors:
            flash(e, 'danger')
    return render_template('pages/contact.html', form=form)


@main_bp.route('/api/contact', methods=['POST'])
@rate_limit(6, 3600)
def api_contact():
    """Same thing from the home-page widget, without leaving the page."""
    form = _contact_fields(request.get_json(silent=True) or request.form)
    errors = _validate_contact(form)
    if errors:
        return jsonify({'success': False, 'error': ' '.join(errors)}), 400
    msg = _save_contact(form)
    return jsonify({'success': True,
                    'message': f'Thanks — we have your message and will reply to {msg.email}.'})


@main_bp.route('/help')
def help_page():
    """Topic index. Each category links to its own page rather than filtering in place."""
    from app.services import help_center
    grouped = help_center.grouped()
    # flat index so the topic page can search every answer and link straight to its page
    index = [{'q': f['question'], 'a': f['answer'], 'id': f['id'], 'cat': cat['title'],
              'url': url_for('main.help_category', category=cat['key'])}
             for cat, items in grouped for f in items]
    return render_template('pages/help.html', grouped=grouped, faq_index=index,
                           faq_total=len(index))


@main_bp.route('/help/<category>')
def help_category(category):
    """One category's questions, with a way back to the index."""
    from flask import abort
    from app.services import help_center
    grouped = help_center.grouped()
    match = next(((c, items) for c, items in grouped if c['key'] == category), None)
    if match is None:
        abort(404)
    cat, items = match
    keys = [c['key'] for c, _ in grouped]
    i = keys.index(category)
    return render_template('pages/help_category.html', cat=cat, items=items,
                           prev_cat=(grouped[i - 1][0] if i > 0 else None),
                           next_cat=(grouped[i + 1][0] if i + 1 < len(grouped) else None),
                           total_cats=len(grouped))


@main_bp.route('/api/airports')
def airport_search():
    q = request.args.get('q', '').strip().lower()
    if len(q) < 2:
        return jsonify([])
    from app.services import locations
    # Rank by how well each airport matches, so "del" surfaces Delhi (DEL) before Adelaide
    # or "Ciudad del Este". Lower score = better; we sort then take the top 8. Without this
    # the list was in file order and cut off at 8, hiding the airport people actually meant.
    scored = []
    for a in locations.all_airports():
        iata = (a.get('iata') or '').lower()
        city = (a.get('city') or '').lower()
        name = (a.get('name') or '').lower()
        if iata == q:
            rank = 0
        elif iata.startswith(q):
            rank = 1
        elif city.startswith(q):
            rank = 2
        elif name.startswith(q):
            rank = 3
        elif q in city or q in iata:
            rank = 4
        elif q in name:
            rank = 5
        else:
            continue
        scored.append((rank, len(city), city, a))
    scored.sort(key=lambda t: (t[0], t[1], t[2]))
    results = [{'iata': a.get('iata'), 'name': a.get('name'), 'city': a.get('city'), 'country': a.get('country')}
               for _, _, _, a in scored[:8]]
    return jsonify(results)


@main_bp.route('/api/airlines')
def airline_search():
    q = request.args.get('q', '').strip().lower()
    if len(q) < 2:
        return jsonify([])
    results = []
    from app.services import airlines as airlines_svc
    for a in airlines_svc.all_airlines():
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

    # Optional field filters. Route terms are checked against every leg as well as the
    # post's overall origin and destination, so a search for Dubai finds an itinerary that
    # merely passes through it -- the same legs the matcher pairs on.
    if data.get('flying_from'):
        pat = f"%{data['flying_from']}%"
        query = query.filter(
            CompanionRequest.flying_from.ilike(pat) | CompanionRequest.origin_iata.ilike(pat)
            | CompanionRequest.leg_rows.any(
                TripLeg.origin_text.ilike(pat) | TripLeg.origin_iata.ilike(pat)))
    if data.get('destination'):
        pat = f"%{data['destination']}%"
        query = query.filter(
            CompanionRequest.destination.ilike(pat) | CompanionRequest.dest_iata.ilike(pat)
            | CompanionRequest.leg_rows.any(
                TripLeg.dest_text.ilike(pat) | TripLeg.dest_iata.ilike(pat)))
    if data.get('role') in TRIP_ROLES:
        # An explicit browse filter: "show me posts with this role" (the dashboard's
        # Seeking / Offering dropdown).
        query = query.filter(CompanionRequest.role == data['role'])
    elif data.get('for_role') in TRIP_ROLES:
        # ...and this is the other question: "I am this role -- who suits me?" The home
        # page sends the role from the post form, and someone who needs a companion needs
        # to see people offering help, not the other 30 people who also need one.
        want = {'seeking_help': ['offering_help', 'open'],
                'offering_help': ['seeking_help', 'open']}.get(data['for_role'])
        if want:
            query = query.filter(CompanionRequest.role.in_(want))
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
            # The filter panel sends an explicit +/- window (0 = that day only); without
            # one, keep the historical default of 3 days, or 7 when marked flexible.
            try:
                window = max(0, min(int(data.get('flex_days')), 30))
            except (TypeError, ValueError):
                window = 7 if data.get('from_date_flexible') in ('on', 'true', True) else 3
            query = query.filter(CompanionRequest.from_date >= d - _td(days=window),
                                 CompanionRequest.from_date <= d + _td(days=window))
        except ValueError:
            pass

    # Filter-panel fields (all optional; absent means "don't filter on this")
    truthy = (True, 'true', 'on', '1', 1)
    if data.get('booking') in ('booked', 'planned'):
        if data['booking'] == 'booked':
            query = query.filter(CompanionRequest.ticket_booked.is_(True))
        else:
            query = query.filter((CompanionRequest.ticket_booked.is_(False))
                                 | (CompanionRequest.ticket_booked.is_(None)))
    trip_types = data.get('trip_types')
    if isinstance(trip_types, str):
        trip_types = [t.strip() for t in trip_types.split(',') if t.strip()]
    trip_types = [t for t in (trip_types or []) if t in ('one_way', 'round_trip', 'multi_destination')]
    if trip_types:
        clause = CompanionRequest.trip_type.in_(trip_types)
        if 'one_way' in trip_types:   # legacy/blank trip_type counts as a one-way
            clause = clause | (CompanionRequest.trip_type.is_(None))
        query = query.filter(clause)
    genders = data.get('genders')
    if isinstance(genders, str):
        genders = [g.strip() for g in genders.split(',') if g.strip()]
    if genders:
        query = query.filter(CompanionRequest.traveler_gender.in_(genders))
    if data.get('verified_only') in truthy:
        from app.models import User
        query = query.join(User, CompanionRequest.user_id == User.id).filter(User.is_verified.is_(True))

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

    try:
        offset = max(int(data.get('offset', 0)), 0)
    except (TypeError, ValueError):
        offset = 0
    total = query.count()
    results = query.offset(offset).limit(limit).all()
    vid = _viewer_id()
    # Flag the posts that already match something the viewer posted, so they stand out while
    # browsing everyone's trips.
    mine_map = {}
    if current_user.is_authenticated:
        from app.services import matching
        mine_map = matching.matches_for_user(current_user)
    out = []
    for r in results:
        d = r.to_dict(viewer_id=vid)
        mm = mine_map.get(r.id)
        if mm and not d['is_own']:
            d['match_to_me'] = mm
        out.append(d)
    return jsonify({'results': out, 'count': len(out), 'total': total, 'offset': offset})


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
                               'my_leg': m.leg_for(t.id), 'their_leg': m.other_leg(t.id),
                               'mine': m.party_for(t.id), 'theirs': m.party_for(other.id)})
    match_rows.sort(key=lambda r: (r['match'].status == 'connected', -r['match'].score))
    return render_template('dashboard.html', my_posts=my_posts, match_rows=match_rows)


@main_bp.route('/settings/notifications', methods=['GET', 'POST'])
@login_required
def notification_settings():
    """Per-user notification preferences: mute all, no e-mail, or mute individual kinds."""
    from flask import redirect, url_for, flash
    from app import db
    from app.models import USER_PREF_CATEGORIES, NOTIFY_CATEGORY_LABELS
    from app.services import notify, settings as app_settings
    if request.method == 'POST':
        prefs = {'muted': request.form.get('muted') == 'on', 'email': request.form.get('email') == 'on'}
        for c in USER_PREF_CATEGORIES:
            prefs[c] = request.form.get(f'cat_{c}') == 'on'
        current_user.notify_prefs = prefs
        db.session.commit()
        flash('Notification settings saved.', 'success')
        return redirect(url_for('main.notification_settings'))
    return render_template('settings_notifications.html', prefs=notify.user_prefs(current_user),
                           categories=USER_PREF_CATEGORIES, labels=NOTIFY_CATEGORY_LABELS,
                           global_sw=app_settings.notification_switches())


@main_bp.route('/api/language', methods=['POST'])
def set_language():
    """Persist the visitor's language choice: a cookie for everyone, the profile column when signed in."""
    data = request.get_json(silent=True) or {}
    lang = str(data.get('lang') or 'en').split('-')[0].lower()[:8]
    if not lang.isalpha() or not 2 <= len(lang) <= 3:
        lang = 'en'
    if current_user.is_authenticated:
        from app import db
        current_user.language_preference = lang
        db.session.commit()
    resp = jsonify({'success': True, 'lang': lang})
    if lang == 'en':
        resp.delete_cookie('lang')
    else:
        resp.set_cookie('lang', lang, max_age=31536000, samesite='Lax')
    return resp


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
