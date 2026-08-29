"""Customer-service console: post intake, queues, claim links, lifecycle actions."""
from functools import wraps
from datetime import datetime, date, timedelta

from flask import (Blueprint, render_template, request, redirect, url_for, flash, jsonify,
                   current_app, abort)
from flask_login import login_required, current_user
from sqlalchemy import func, or_

from app import db
from app.models import (
    CompanionRequest, ContactPoint, ClaimToken, ActivityEvent, Notification, User,
    TRIP_STATUSES, TRIP_SOURCES, TRIP_ROLES, TRIP_ROLE_LABELS, CLOSED_REASONS, CLOSED_REASON_LABELS,
    AGE_GROUPS, AGE_GROUP_LABELS, GENDERS, PREF_GENDERS, CONTACT_TYPES, CONTACT_TYPE_LABELS,
)
from app import options
from app.services.locations import apply_route
from app.services.contacts import parse_contact_rows
from app.services.storage import save_private_document, delete_private
from app.services import matching

cs_bp = Blueprint('cs', __name__)

PAGE_SIZE = 30


def cs_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login', next=request.path))
        if not current_user.is_cs:
            flash('The CS console is for customer-service staff only.', 'danger')
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated


def _choices():
    return dict(
        TRIP_STATUSES=TRIP_STATUSES, TRIP_SOURCES=TRIP_SOURCES, TRIP_ROLES=TRIP_ROLES,
        TRIP_ROLE_LABELS=TRIP_ROLE_LABELS, CLOSED_REASONS=CLOSED_REASONS,
        CLOSED_REASON_LABELS=CLOSED_REASON_LABELS, AGE_GROUPS=AGE_GROUPS, AGE_GROUP_LABELS=AGE_GROUP_LABELS,
        GENDERS=GENDERS, PREF_GENDERS=PREF_GENDERS, CONTACT_TYPES=CONTACT_TYPES,
        CONTACT_TYPE_LABELS=CONTACT_TYPE_LABELS,
        ON_BEHALF_OF=options.ON_BEHALF_OF, CONNECT_ME_TO=options.CONNECT_ME_TO,
        TRAVELLER_NEEDS=options.TRAVELLER_NEEDS, LANGUAGES=options.LANGUAGES,
    )


def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, '%Y-%m-%d').date()
    except ValueError:
        return None


def _int_or_none(s):
    try:
        return int(s) if s not in (None, '') else None
    except (TypeError, ValueError):
        return None


def claim_url_for(token):
    return url_for('claim.claim_page', token=token.token, _external=True)


def dm_text_for(trip, url):
    """Suggested message CS pastes into the person's DM along with the claim link (action A)."""
    name = (trip.poster_name or '').split(' ')[0]
    greeting = f"Hi {name}," if name else "Hi,"
    route = trip.route_display if current_app.config.get('CLAIM_SHOW_ROUTE') else 'upcoming'
    return (
        f"{greeting} this is the Connecting Desis team. We help Desi travellers find companions on the "
        f"same route. We'd like to help with your {route} trip. Please add your preferred contact details "
        f"here so we can introduce you to matching travellers: {url}\n\n"
        f"We only share your details with a matched companion, and only with your consent."
    )


# ---------------------------------------------------------------------------
# Home / queues
# ---------------------------------------------------------------------------

@cs_bp.route('/')
@login_required
@cs_required
def home():
    today = date.today()
    now = datetime.utcnow()
    public = CompanionRequest.query.filter(CompanionRequest.status.in_(['open', 'matched']))

    departing_soon = (public.filter(CompanionRequest.from_date >= today,
                                    CompanionRequest.from_date <= today + timedelta(days=7))
                      .order_by(CompanionRequest.from_date.asc()).limit(40).all())

    new_posts = (CompanionRequest.query
                 .filter(CompanionRequest.created_at >= now - timedelta(hours=48),
                         CompanionRequest.status != 'closed')
                 .order_by(CompanionRequest.created_at.desc()).limit(40).all())

    awaiting_claim = (CompanionRequest.query.filter_by(status='unconfirmed')
                      .order_by(CompanionRequest.created_at.asc()).all())

    # Needs action: claim link sent > 3 days ago with no response; departing ≤ 3 days with nothing consented.
    needs_action = []
    for t in awaiting_claim:
        tok = t.claim_tokens.order_by(ClaimToken.created_at.desc()).first()
        if tok and tok.used_at is None and tok.created_at < now - timedelta(days=3):
            needs_action.append(('No response to claim link for %d days' % (now - tok.created_at).days, t))
        elif tok is None and t.created_at < now - timedelta(days=2):
            needs_action.append(('No claim link sent yet', t))
    for t in public.filter(CompanionRequest.from_date >= today,
                           CompanionRequest.from_date <= today + timedelta(days=3)).all():
        if not t.consented_contact_types:
            needs_action.append(('Departing soon with no consented contact', t))

    # Repeats: same contact value on several posts; same route + date on several posts.
    dup_contacts = (db.session.query(ContactPoint.value, ContactPoint.type,
                                     func.count(func.distinct(ContactPoint.trip_id)).label('n'))
                    .filter(ContactPoint.trip_id.isnot(None))
                    .group_by(ContactPoint.value, ContactPoint.type)
                    .having(func.count(func.distinct(ContactPoint.trip_id)) > 1).all())
    dup_contact_groups = []
    for value, ctype, n in dup_contacts:
        trips = (CompanionRequest.query.join(ContactPoint, ContactPoint.trip_id == CompanionRequest.id)
                 .filter(ContactPoint.value == value, ContactPoint.type == ctype).all())
        dup_contact_groups.append({'type': ctype, 'value': value, 'trips': trips})

    dup_routes = (db.session.query(CompanionRequest.origin_iata, CompanionRequest.dest_iata,
                                   CompanionRequest.from_date, func.count(CompanionRequest.id).label('n'))
                  .filter(CompanionRequest.status != 'closed', CompanionRequest.origin_iata.isnot(None),
                          CompanionRequest.dest_iata.isnot(None), CompanionRequest.from_date.isnot(None))
                  .group_by(CompanionRequest.origin_iata, CompanionRequest.dest_iata, CompanionRequest.from_date)
                  .having(func.count(CompanionRequest.id) > 1).all())
    dup_route_groups = []
    for o, d, fd, n in dup_routes:
        trips = CompanionRequest.query.filter_by(origin_iata=o, dest_iata=d, from_date=fd).all()
        dup_route_groups.append({'origin': o, 'dest': d, 'date': fd, 'trips': trips})

    closed = (CompanionRequest.query.filter_by(status='closed')
              .order_by(CompanionRequest.closed_at.desc()).limit(20).all())

    from app.models import Match
    match_tasks = (Match.query.filter(Match.needs_cs_attention.is_(True), Match.status != 'dismissed')
                   .order_by(Match.updated_at.desc()).limit(20).all())

    counts = {
        'open': public.count(),
        'unconfirmed': len(awaiting_claim),
        'closed': CompanionRequest.query.filter_by(status='closed').count(),
        'needs_action': len(needs_action) + len(match_tasks),
    }
    return render_template('cs/home.html', counts=counts, needs_action=needs_action, match_tasks=match_tasks,
                           departing_soon=departing_soon, new_posts=new_posts,
                           awaiting_claim=awaiting_claim, dup_contact_groups=dup_contact_groups,
                           dup_route_groups=dup_route_groups, closed=closed, today=today, **_choices())


# ---------------------------------------------------------------------------
# Metrics (plan §13 2D: time-to-match, % manual, claim rate, connected rate, tuning hints)
# ---------------------------------------------------------------------------

@cs_bp.route('/metrics')
@login_required
@cs_required
def metrics():
    from collections import Counter
    from statistics import median
    from app.models import Match, MatchParty
    from app.services.matching import get_weights, LABELS

    days = _int_or_none(request.args.get('days')) or 30
    since = datetime.utcnow() - timedelta(days=days)

    posts = CompanionRequest.query.filter(CompanionRequest.created_at >= since).all()
    by_source = Counter(p.source or 'organic' for p in posts)
    by_status = Counter(p.status for p in posts)
    cs_posts = [p for p in posts if (p.source or 'organic') != 'organic']
    claimed = [p for p in cs_posts if p.claimed_at]
    claim_rate = (len(claimed) / len(cs_posts)) if cs_posts else None

    matches = Match.query.filter(Match.created_at >= since).all()
    m_by_status = Counter(m.status for m in matches)
    bands = Counter('75+' if m.score >= 75 else '55-74' if m.score >= 55 else '40-54' for m in matches)
    parties = [p for m in matches for p in m.parties]
    sent_parties = [p for p in parties if p.sent_at]
    channels = Counter(p.channel for p in parties)
    manual = sum(v for k, v in channels.items() if k.startswith('manual_'))
    auto = channels.get('email', 0) + channels.get('inapp', 0)
    pct_manual = (manual / (manual + auto)) if (manual + auto) else None
    notified_matches = [m for m in matches if any(p.sent_at for p in m.parties)]
    connected_rate = (m_by_status.get('connected', 0) / len(notified_matches)) if notified_matches else None
    escalated = sum(1 for p in sent_parties if p.escalated_at)
    escalation_rate = (escalated / len(sent_parties)) if sent_parties else None
    opened = sum(1 for p in sent_parties if p.opened_at)
    open_rate = (opened / len(sent_parties)) if sent_parties else None

    # Time from post creation to its first suggested match
    first_seen = {}
    for e in ActivityEvent.query.filter(ActivityEvent.event == 'match_suggested',
                                        ActivityEvent.created_at >= since).all():
        if e.trip_id and (e.trip_id not in first_seen or e.created_at < first_seen[e.trip_id]):
            first_seen[e.trip_id] = e.created_at
    post_created = {p.id: p.created_at for p in posts}
    hours = [(t - post_created[tid]).total_seconds() / 3600 for tid, t in first_seen.items()
             if tid in post_created and t >= post_created[tid]]
    ttm = {'n': len(hours), 'avg': (sum(hours) / len(hours)) if hours else None,
           'median': median(hours) if hours else None}

    dismiss_reasons = Counter((m.dismissed_reason or 'unspecified') for m in matches if m.status == 'dismissed')

    # Tuning hints: which criteria separate connected matches from ones people rejected
    good = [m for m in matches if m.status == 'connected']
    bad = [m for m in matches if m.status == 'dismissed'
           and m.dismissed_reason in ('not_suitable', 'not_suitable_by_party', 'wrong_direction')]

    def ok_rate(ms, key):
        vals = [c['ok'] for m in ms for c in (m.criteria or []) if c.get('key') == key]
        return (sum(vals) / len(vals)) if vals else None

    weights = get_weights()
    tuning = []
    for key, w in weights.items():
        g, b = ok_rate(good, key), ok_rate(bad, key)
        hint = '—'
        if g is not None and b is not None:
            if g - b >= 0.25:
                hint = 'strong signal — consider raising'
            elif b - g >= 0.10:
                hint = 'weak / misleading — consider lowering'
            else:
                hint = 'neutral'
        tuning.append({'key': key, 'label': LABELS[key], 'weight': w, 'ok_connected': g, 'ok_dismissed': b, 'hint': hint})

    return render_template('cs/metrics.html', days=days, posts_n=len(posts), by_source=by_source, by_status=by_status,
                           cs_posts_n=len(cs_posts), claimed_n=len(claimed), claim_rate=claim_rate,
                           matches_n=len(matches), m_by_status=m_by_status, bands=bands, channels=channels,
                           pct_manual=pct_manual, manual=manual, auto=auto, connected_rate=connected_rate,
                           notified_n=len(notified_matches), escalation_rate=escalation_rate, escalated=escalated,
                           open_rate=open_rate, sent_n=len(sent_parties), ttm=ttm, dismiss_reasons=dismiss_reasons,
                           tuning=tuning, good_n=len(good), bad_n=len(bad), **_choices())


# ---------------------------------------------------------------------------
# Posts list
# ---------------------------------------------------------------------------

@cs_bp.route('/posts')
@login_required
@cs_required
def posts():
    q = (request.args.get('q') or '').strip()
    status = request.args.get('status') or ''
    source = request.args.get('source') or ''
    role = request.args.get('role') or ''
    contact_type = request.args.get('contact_type') or ''
    days = _int_or_none(request.args.get('days'))
    sort = request.args.get('sort') or 'departure'
    page = max(_int_or_none(request.args.get('page')) or 1, 1)

    query = CompanionRequest.query
    if status:
        query = query.filter(CompanionRequest.status == status)
    else:
        query = query.filter(CompanionRequest.status != 'closed')
    if source:
        query = query.filter(CompanionRequest.source == source)
    if role:
        query = query.filter(CompanionRequest.role == role)
    if contact_type:
        query = query.filter(CompanionRequest.contact_points.any(ContactPoint.type == contact_type))
    if days is not None:
        query = query.filter(CompanionRequest.from_date >= date.today(),
                             CompanionRequest.from_date <= date.today() + timedelta(days=days))
    if q:
        pat = f"%{q}%"
        query = query.filter(or_(
            CompanionRequest.flying_from.ilike(pat), CompanionRequest.destination.ilike(pat),
            CompanionRequest.origin_iata.ilike(pat), CompanionRequest.dest_iata.ilike(pat),
            CompanionRequest.poster_name.ilike(pat), CompanionRequest.traveler_name.ilike(pat),
            CompanionRequest.airline.ilike(pat), CompanionRequest.flight_number.ilike(pat),
            CompanionRequest.additional_comments.ilike(pat),
            CompanionRequest.contact_points.any(ContactPoint.value.ilike(pat)),
        ))
    if sort == 'newest':
        query = query.order_by(CompanionRequest.created_at.desc())
    elif sort == 'updated':
        query = query.order_by(CompanionRequest.updated_at.desc())
    else:
        query = query.order_by(CompanionRequest.from_date.asc().nulls_last(), CompanionRequest.created_at.desc())

    total = query.count()
    items = query.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE).all()
    pages = max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1)
    return render_template('cs/posts.html', posts=items, total=total, page=page, pages=pages,
                           filters=dict(q=q, status=status, source=source, role=role,
                                        contact_type=contact_type, days=days, sort=sort),
                           today=date.today(), **_choices())


# ---------------------------------------------------------------------------
# Create / edit
# ---------------------------------------------------------------------------

def _apply_form(trip, form, files, is_new):
    """Populate a CompanionRequest from the CS form. Returns list of error strings."""
    errors = []
    trip.travel_type = 'air'
    trip.trip_type = form.get('trip_type') or 'one_way'
    trip.source = form.get('source') if form.get('source') in TRIP_SOURCES else 'website'
    trip.source_url = (form.get('source_url') or '').strip()[:500] or None
    trip.poster_name = (form.get('poster_name') or '').strip()[:120] or None
    trip.traveler_name = (form.get('traveler_name') or '').strip()[:120] or None
    trip.on_behalf_of = form.get('on_behalf_of') or None
    trip.role = form.get('role') if form.get('role') in TRIP_ROLES else 'seeking_help'

    trip.flying_from = (form.get('flying_from') or '').strip()[:200] or None
    trip.destination = (form.get('destination') or '').strip()[:200] or None
    trip.flying_from_flexible = form.get('flying_from_flexible') == 'on'
    trip.destination_flexible = form.get('destination_flexible') == 'on'
    trip.from_date = _parse_date(form.get('from_date'))
    trip.from_date_flexible = form.get('from_date_flexible') == 'on'
    trip.to_date = _parse_date(form.get('to_date')) if trip.trip_type == 'round_trip' else None
    trip.to_date_flexible = form.get('to_date_flexible') == 'on'
    trip.airline = (form.get('airline') or '').strip()[:200] or None
    trip.flight_number = (form.get('flight_number') or '').strip()[:30] or None
    trip.ticket_booked = form.get('ticket_booked') == 'on'

    trip.traveller_needs = form.getlist('traveller_needs')
    trip.special_needs_notes = (form.get('special_needs_notes') or '').strip() or None
    trip.connect_me_to = form.getlist('connect_me_to')
    trip.preferred_languages = form.getlist('preferred_languages')
    trip.traveler_age_group = form.get('traveler_age_group') if form.get('traveler_age_group') in AGE_GROUPS else None
    trip.traveler_gender = form.get('traveler_gender') if form.get('traveler_gender') in GENDERS else None
    trip.pref_gender = form.get('pref_gender') if form.get('pref_gender') in PREF_GENDERS else 'any'
    trip.pref_age_min = _int_or_none(form.get('pref_age_min'))
    trip.pref_age_max = _int_or_none(form.get('pref_age_max'))
    trip.additional_comments = (form.get('additional_comments') or '').strip() or None
    trip.cs_notes = (form.get('cs_notes') or '').strip() or None
    trip.is_anonymous = form.get('is_anonymous') == 'on'
    trip.expires_at = trip.to_date or trip.from_date

    if not trip.flying_from or not trip.destination:
        errors.append('Origin and destination are required.')
    if not trip.from_date:
        errors.append('Departure date is required.')
    if trip.pref_age_min and trip.pref_age_max and trip.pref_age_min > trip.pref_age_max:
        errors.append('Preferred age range is inverted.')

    o, d = apply_route(trip)
    if trip.flying_from and not o:
        errors.append('Origin was not recognised — pick an airport from the suggestions.')
    if trip.destination and not d:
        errors.append('Destination was not recognised — pick an airport from the suggestions.')

    # Ticket attachment (private)
    if form.get('remove_ticket') == 'on' and trip.ticket_attachment:
        delete_private(trip.ticket_attachment)
        trip.ticket_attachment = None
    f = files.get('ticket_file')
    if f and f.filename:
        key = save_private_document(f, prefix=f"ticket_{trip.id or 'new'}")
        if key:
            if trip.ticket_attachment:
                delete_private(trip.ticket_attachment)
            trip.ticket_attachment = key
        else:
            errors.append('Ticket attachment must be a PDF or an image (jpg/png/webp).')

    return errors


def _replace_contact_points(trip, rows):
    existing = {cp.id: cp for cp in trip.contact_points}
    keep_ids = set()
    ids = request.form.getlist('contact_id')
    for i, r in enumerate(rows):
        cp_id = _int_or_none(ids[i]) if i < len(ids) else None
        cp = existing.get(cp_id) if cp_id else None
        if cp is None:
            cp = ContactPoint(trip=trip, added_by='cs')
            db.session.add(cp)
        cp.type, cp.value, cp.label = r['type'], r['value'], r['label'] or None
        cp.consent_to_share = r['consent']
        if cp.id:
            keep_ids.add(cp.id)
        else:
            keep_ids.add(id(cp))
    for cp in list(trip.contact_points):
        if cp.id and cp.id not in keep_ids and id(cp) not in keep_ids:
            db.session.delete(cp)


def _duplicate_warnings(trip, rows):
    warnings = []
    for r in rows:
        others = (CompanionRequest.query.join(ContactPoint, ContactPoint.trip_id == CompanionRequest.id)
                  .filter(ContactPoint.value == r['value'], CompanionRequest.id != trip.id)
                  .limit(5).all())
        for o in others:
            warnings.append(f"Contact {r['value']} also appears on post #{o.id} ({o.route_display}).")
    if trip.origin_iata and trip.dest_iata and trip.from_date:
        q = CompanionRequest.query.filter_by(origin_iata=trip.origin_iata, dest_iata=trip.dest_iata,
                                             from_date=trip.from_date).filter(CompanionRequest.id != trip.id)
        if trip.poster_name:
            q = q.filter(CompanionRequest.poster_name.ilike(trip.poster_name))
        for o in q.limit(5).all():
            warnings.append(f"Post #{o.id} has the same route/date{' and name' if trip.poster_name else ''}.")
    return warnings


@cs_bp.route('/posts/new', methods=['GET', 'POST'])
@login_required
@cs_required
def new_post():
    if request.method == 'POST':
        trip = CompanionRequest(created_by_id=current_user.id, user_id=None)
        errors = _apply_form(trip, request.form, request.files, is_new=True)
        rows, contact_errors = parse_contact_rows(request.form)
        errors += contact_errors
        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('cs/post_form.html', trip=trip, form=request.form,
                                   contact_rows=rows, is_new=True, **_choices())
        publish_now = request.form.get('publish_now') == 'on'
        trip.set_status('open' if publish_now else 'unconfirmed')
        if publish_now:
            trip.claimed_at = datetime.utcnow()
        db.session.add(trip)
        db.session.flush()
        _replace_contact_points(trip, rows)
        ActivityEvent.log('post_created', trip, actor=current_user, source=trip.source, status=trip.status)
        db.session.commit()
        found = matching.compute_matches_for(trip, include_unconfirmed=True, actor=current_user)
        for w in _duplicate_warnings(trip, rows):
            flash(w, 'info')
        flash('Post created.' + (f' {len(found)} possible match(es) found.' if found else ''), 'success')
        return redirect(url_for('cs.post_detail', trip_id=trip.id))
    return render_template('cs/post_form.html', trip=None, form={}, contact_rows=[], is_new=True, **_choices())


@cs_bp.route('/posts/<int:trip_id>/edit', methods=['GET', 'POST'])
@login_required
@cs_required
def edit_post(trip_id):
    trip = CompanionRequest.query.get_or_404(trip_id)
    if request.method == 'POST':
        errors = _apply_form(trip, request.form, request.files, is_new=False)
        rows, contact_errors = parse_contact_rows(request.form)
        errors += contact_errors
        if errors:
            db.session.rollback()
            for e in errors:
                flash(e, 'danger')
            return render_template('cs/post_form.html', trip=trip, form=request.form,
                                   contact_rows=rows, is_new=False, **_choices())
        _replace_contact_points(trip, rows)
        ActivityEvent.log('post_updated', trip, actor=current_user)
        db.session.commit()
        matching.compute_matches_for(trip, include_unconfirmed=True, actor=current_user)
        flash('Post updated.', 'success')
        return redirect(url_for('cs.post_detail', trip_id=trip.id))
    contact_rows = [{'id': cp.id, 'type': cp.type, 'value': cp.value, 'label': cp.label or '',
                     'consent': cp.consent_to_share} for cp in trip.contact_points]
    return render_template('cs/post_form.html', trip=trip, form=None, contact_rows=contact_rows,
                           is_new=False, **_choices())


# ---------------------------------------------------------------------------
# Detail + actions
# ---------------------------------------------------------------------------

@cs_bp.route('/posts/<int:trip_id>')
@login_required
@cs_required
def post_detail(trip_id):
    trip = CompanionRequest.query.get_or_404(trip_id)
    tokens = trip.claim_tokens.order_by(ClaimToken.created_at.desc()).all()
    events = trip.events.limit(50).all()
    if trip.contact_points:
        ActivityEvent.log('contact_values_viewed', trip, actor=current_user)
        db.session.commit()
    latest_token = next((t for t in tokens if t.is_valid), None)
    latest_url = claim_url_for(latest_token) if latest_token else None
    return render_template('cs/post_detail.html', trip=trip, tokens=tokens, events=events,
                           latest_token=latest_token, latest_url=latest_url,
                           dm_text=dm_text_for(trip, latest_url) if latest_url else None,
                           today=date.today(), **_choices())


@cs_bp.route('/posts/<int:trip_id>/close', methods=['POST'])
@login_required
@cs_required
def close_post(trip_id):
    trip = CompanionRequest.query.get_or_404(trip_id)
    reason = request.form.get('reason') or (request.get_json(silent=True) or {}).get('reason')
    if reason not in CLOSED_REASONS:
        flash('Pick a close reason.', 'danger')
        return redirect(url_for('cs.post_detail', trip_id=trip.id))
    trip.set_status('closed', reason=reason, by=current_user)
    ActivityEvent.log('post_closed', trip, actor=current_user, reason=reason)
    matching.dismiss_matches_for_closed_trip(trip)
    db.session.commit()
    flash(f'Post closed ({CLOSED_REASON_LABELS[reason]}).', 'success')
    return redirect(request.form.get('next') or url_for('cs.post_detail', trip_id=trip.id))


@cs_bp.route('/posts/<int:trip_id>/reopen', methods=['POST'])
@login_required
@cs_required
def reopen_post(trip_id):
    trip = CompanionRequest.query.get_or_404(trip_id)
    trip.set_status('open' if trip.is_claimed else 'unconfirmed')
    ActivityEvent.log('post_reopened', trip, actor=current_user, status=trip.status)
    db.session.commit()
    matching.compute_matches_for(trip, include_unconfirmed=True, actor=current_user)
    flash('Post reopened.', 'success')
    return redirect(request.form.get('next') or url_for('cs.post_detail', trip_id=trip.id))


@cs_bp.route('/posts/<int:trip_id>/publish', methods=['POST'])
@login_required
@cs_required
def publish_post(trip_id):
    """CS confirms the person agreed (e.g. in DM) — publish without waiting for the claim link."""
    trip = CompanionRequest.query.get_or_404(trip_id)
    if trip.status != 'unconfirmed':
        flash('Only unconfirmed posts can be published this way.', 'info')
        return redirect(url_for('cs.post_detail', trip_id=trip.id))
    trip.set_status('open')
    trip.claimed_at = datetime.utcnow()
    ActivityEvent.log('post_published_by_cs', trip, actor=current_user)
    db.session.commit()
    matching.compute_matches_for(trip, include_unconfirmed=True, actor=current_user)
    flash('Post published.', 'success')
    return redirect(url_for('cs.post_detail', trip_id=trip.id))


@cs_bp.route('/posts/<int:trip_id>/claim-link', methods=['POST'])
@login_required
@cs_required
def issue_claim_link(trip_id):
    trip = CompanionRequest.query.get_or_404(trip_id)
    tok = ClaimToken.issue(trip, days=current_app.config['CLAIM_TOKEN_DAYS'], created_by=current_user)
    db.session.flush()
    url = claim_url_for(tok)
    ActivityEvent.log('claim_link_issued', trip, actor=current_user, token_id=tok.id)
    db.session.commit()
    return jsonify({'success': True, 'url': url, 'dm_text': dm_text_for(trip, url),
                    'expires_at': tok.expires_at.isoformat()})


@cs_bp.route('/posts/<int:trip_id>/events', methods=['POST'])
@login_required
@cs_required
def log_manual_event(trip_id):
    """Record a manual CS action (e.g. DM sent on Facebook) so the trail is complete."""
    trip = CompanionRequest.query.get_or_404(trip_id)
    data = request.get_json(silent=True) or request.form
    event = (data.get('event') or '').strip()
    allowed = {'claim_link_sent_manual', 'dm_sent', 'called', 'note'}
    if event not in allowed:
        return jsonify({'error': 'Unknown event'}), 400
    note = (data.get('note') or '').strip()[:500]
    channel = (data.get('channel') or '').strip()[:30]
    ActivityEvent.log(event, trip, actor=current_user, note=note or None, channel=channel or None)
    db.session.commit()
    if request.is_json:
        return jsonify({'success': True})
    flash('Logged.', 'success')
    return redirect(url_for('cs.post_detail', trip_id=trip.id))
