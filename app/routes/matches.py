"""Matching & communication bridge: user API, public contact page, CS match view."""
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, abort
from flask_login import login_required, current_user

from app import db
from app.models import (Match, MatchParty, CompanionRequest, ActivityEvent, User, DISMISS_REASONS,
                        CHANNEL_LABELS, CONTACT_TYPE_LABELS, CONTACT_TYPE_ICONS, PARTY_CHANNELS)
from app.services import matching, bridge
from app.services.ratelimit import rate_limit
from app.routes.cs import cs_required, _choices

matches_bp = Blueprint('matches', __name__)


def _can_manage(match):
    return current_user.is_authenticated and (current_user.is_cs or match.involves_user(current_user.id))


def _trip_for_user(match):
    """Which side of the match the current (non-CS) user is."""
    if match.trip_a.user_id == current_user.id:
        return match.trip_a
    if match.trip_b.user_id == current_user.id:
        return match.trip_b
    return None


# ---------------------------------------------------------------------------
# User-facing JSON API
# ---------------------------------------------------------------------------

@matches_bp.route('/api/trip/<int:trip_id>/matches', methods=['GET'])
@login_required
def trip_matches(trip_id):
    trip = CompanionRequest.query.get_or_404(trip_id)
    if trip.user_id != current_user.id and not current_user.is_cs:
        return jsonify({'error': 'Unauthorized'}), 403
    if request.args.get('recompute') == '1' or not matching.live_matches_for(trip):
        matching.compute_matches_for(trip, actor=current_user)
    ms = matching.ranked_matches_for(trip)
    return jsonify({'matches': [m.to_dict(for_trip_id=trip.id, viewer_id=current_user.id) for m in ms],
                    'count': len(ms)})


@matches_bp.route('/api/matches/<int:match_id>/notify', methods=['POST'])
@login_required
@rate_limit(30, 3600)
def api_notify(match_id):
    match = Match.query.get_or_404(match_id)
    if not _can_manage(match):
        return jsonify({'error': 'Unauthorized'}), 403
    if not match.is_open:
        return jsonify({'error': 'This match is no longer open.'}), 400
    # Who pressed the button. notify_match records what was *sent* to each side; this
    # records the decision itself, on the post of the person who made it, so CS can see
    # "this traveller agreed to share" without inferring it from a delivery log.
    mine = match.trip_a if match.trip_a.user_id == current_user.id else match.trip_b
    theirs = match.other_trip(mine.id)
    ActivityEvent.log('contact_shared', mine, actor=current_user, match_id=match.id,
                      other_trip_id=theirs.id)
    # ...and on the other post, so the traveller who received the details has the same
    # record on their own timeline rather than only on the sharer's.
    ActivityEvent.log('contact_shared_by_match', theirs, actor=current_user, match_id=match.id,
                      other_trip_id=mine.id)
    parties, problems = bridge.notify_match(match, actor=current_user)
    return jsonify({'success': True, 'status': match.status,
                    'parties': [p.to_dict() for p in parties], 'problems': problems})


@matches_bp.route('/api/matches/<int:match_id>/dismiss', methods=['POST'])
@login_required
def api_dismiss(match_id):
    match = Match.query.get_or_404(match_id)
    if not _can_manage(match):
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.get_json(silent=True) or {}
    reason = data.get('reason') if data.get('reason') in DISMISS_REASONS else 'not_suitable'
    match.status = 'dismissed'
    match.dismissed_reason = reason
    match.needs_cs_attention = False
    mine = _trip_for_user(match) if not current_user.is_cs else None
    ActivityEvent.log('match_dismissed', mine or match.trip_a, actor=current_user, match_id=match.id, reason=reason)
    db.session.commit()
    return jsonify({'success': True})


# ---------------------------------------------------------------------------
# Public contact page (token is the credential)
# ---------------------------------------------------------------------------

@matches_bp.route('/match/<token>', methods=['GET'])
def contact_page(token):
    party = MatchParty.query.filter_by(token=token).first()
    if party is None:
        return render_template('match/invalid.html', reason='not_found'), 404
    match = party.match
    me = party.trip
    other = match.other_trip(me.id)
    if match.status == 'dismissed':
        return render_template('match/invalid.html', reason='dismissed'), 410
    if not other.is_public or me.status == 'closed':
        return render_template('match/invalid.html', reason='closed'), 410

    bridge.record_opened(party)
    consented = [cp for cp in other.contact_points if cp.consent_to_share and cp.type != 'inapp_chat']
    can_chat = bool(other.user_id) and any(cp.type == 'inapp_chat' and cp.consent_to_share for cp in other.contact_points)
    if consented or can_chat:
        bridge.record_contact_viewed(party)
    db.session.commit()

    other_matches = [m for m in matching.ranked_matches_for(me) if m.id != match.id]
    my_consented = me.consented_contact_types
    return render_template('match/contact.html', party=party, match=match, me=me, other=other,
                           consented=consented, can_chat=can_chat, other_matches_count=len(other_matches),
                           my_consented=my_consented, CHANNEL_LABELS=CHANNEL_LABELS)


@matches_bp.route('/match/<token>/<action>', methods=['POST'])
@rate_limit(20, 600)
def contact_page_action(token, action):
    party = MatchParty.query.filter_by(token=token).first_or_404()
    actor = current_user if current_user.is_authenticated else None
    if action == 'contacted':
        bridge.record_contacted(party, actor=actor)
        flash('Great — we have marked this as connected. Safe travels!', 'success')
    elif action == 'not-suitable':
        bridge.record_not_suitable(party, actor=actor)
        flash('Thanks for letting us know. We will keep looking for a better match.', 'info')
        db.session.commit()
        return redirect(url_for('main.index'))
    elif action == 'report':
        reason = (request.form.get('reason') or '').strip()
        if not reason:
            flash('Please tell us what the problem is.', 'danger')
            return redirect(url_for('matches.contact_page', token=token))
        bridge.record_report(party, reason, actor=actor)
        flash('Thank you — our team will look into it.', 'info')
    else:
        abort(404)
    db.session.commit()
    return redirect(url_for('matches.contact_page', token=token))


@matches_bp.route('/api/matches/<int:match_id>/request-contact', methods=['POST'])
@login_required
def request_contact(match_id):
    """Ask the matched traveller to share their contact details - lands in their inbox like a connect request."""
    from datetime import datetime, timedelta
    from app.models import ActivityEvent
    from app.services import notify
    match = Match.query.get_or_404(match_id)
    if match.status == 'dismissed':
        return jsonify({'error': 'This match was dismissed.'}), 400
    mine = next((t for t in (match.trip_a, match.trip_b) if t.user_id == current_user.id), None)
    if mine is None:
        return jsonify({'error': 'This match does not involve one of your posts.'}), 403
    other = match.other_trip(mine.id)
    if not other.user_id:
        return jsonify({'error': 'This traveller is assisted by our team - use "Share my contact & notify" and we will bridge the introduction.'}), 400
    since = datetime.utcnow() - timedelta(hours=24)
    already = (ActivityEvent.query.filter_by(event='contact_requested', actor_id=current_user.id, match_id=match.id)
               .filter(ActivityEvent.created_at >= since).count())
    if already:
        return jsonify({'error': 'You already asked in the last 24 hours - give them a little time to reply.'}), 429
    n = notify.push(
        other.user_id, 'contact_request',
        title=f'{current_user.username} would like to exchange contact details',
        body=(f'For your {other.route_display} trip on {other.from_date or "a similar date"} '
              f'({match.score}% match). Open your matches to view the request and share yours if you want to.'),
        link='/#my-trips', category='match_intro',
    )
    ActivityEvent.log('contact_requested', mine, actor=current_user, match_id=match.id, other_trip_id=other.id)
    ActivityEvent.log('contact_requested_by_match', other, actor=current_user, match_id=match.id,
                      other_trip_id=mine.id)
    db.session.commit()
    return jsonify({'success': True, 'delivered': n is not None,
                    'message': 'Request sent - it will appear in their notifications and inbox.'})


# ---------------------------------------------------------------------------
# CS match view & actions
# ---------------------------------------------------------------------------

def _match_rows(trip, ms):
    rows = []
    for m in ms:
        other = m.other_trip(trip.id)
        ch_me, _ = bridge.channel_for(trip)
        ch_other, _ = bridge.channel_for(other)
        my_leg = m.leg_for(trip.id)
        rows.append({
            'match': m, 'other': other,
            # which trip of this post the match is on -- the chips filter by it
            'my_leg': my_leg, 'leg_id': my_leg.id if my_leg else 0,
            'their_leg': m.other_leg(trip.id),
            'party_me': m.party_for(trip.id), 'party_other': m.party_for(other.id),
            'channel_me': ch_me, 'channel_other': ch_other,
            'can_notify': m.is_open and ch_me != 'none' and ch_other != 'none' and other.is_public and trip.is_public,
            'other_consented': [cp for cp in other.contact_points if cp.consent_to_share and cp.type != 'inapp_chat'],
            'me_consented': [cp for cp in trip.contact_points if cp.consent_to_share and cp.type != 'inapp_chat'],
        })
    return rows


@matches_bp.route('/cs/posts/<int:trip_id>/matches')
@login_required
@cs_required
def cs_matches(trip_id):
    trip = CompanionRequest.query.get_or_404(trip_id)
    matching.compute_matches_for(trip, include_unconfirmed=True, actor=current_user)
    ms = matching.ranked_matches_for(trip, include_unconfirmed=True)
    dismissed = Match.query.filter(((Match.trip_a_id == trip.id) | (Match.trip_b_id == trip.id)),
                                   Match.status == 'dismissed').order_by(Match.updated_at.desc()).limit(10).all()
    from app.routes.cs import _leg_data
    return render_template('cs/matches.html', trip=trip, rows=_match_rows(trip, ms), dismissed=dismissed,
                           leg_data=_leg_data(trip),
                           channel_me=bridge.channel_for(trip)[0], CHANNEL_LABELS=CHANNEL_LABELS,
                           DISMISS_REASONS=DISMISS_REASONS, PARTY_CHANNELS=PARTY_CHANNELS, **_choices())


@matches_bp.route('/cs/matches')
@login_required
@cs_required
def cs_match_queue():
    """Matches a person has to move along, grouped by the post that is waiting.

    One traveller asking ten people to connect produces ten rows that are really one piece
    of work. Grouping by the waiting post turns that back into one item with ten matches
    under it, so the queue reflects how many people need attention rather than how many
    pairings exist.
    """
    from sqlalchemy import or_ as _or
    from app.routes.cs import TRIP_TYPES, TRIP_TYPE_LABELS

    try:
        page = max(int(request.args.get('page') or 1), 1)
    except ValueError:
        page = 1
    per_page = 20

    q = (request.args.get('q') or '').strip()
    status = request.args.get('status') or ''
    trip_type = request.args.get('trip_type') or ''
    channel = request.args.get('channel') or ''

    query = Match.query.filter(Match.needs_cs_attention.is_(True), Match.status != 'dismissed')
    if status:
        query = query.filter(Match.status == status)
    if trip_type in TRIP_TYPES:
        query = query.filter(_or(
            Match.trip_a.has(CompanionRequest.trip_type == trip_type),
            Match.trip_b.has(CompanionRequest.trip_type == trip_type)))
    if q:
        pat = f'%{q}%'
        def _side(rel):
            return rel.has(_or(
                CompanionRequest.flying_from.ilike(pat), CompanionRequest.destination.ilike(pat),
                CompanionRequest.origin_iata.ilike(pat), CompanionRequest.dest_iata.ilike(pat),
                CompanionRequest.poster_name.ilike(pat),
                CompanionRequest.author.has(_or(User.username.ilike(pat), User.email.ilike(pat))),
            ))
        query = query.filter(_or(_side(Match.trip_a), _side(Match.trip_b)))

    ms = query.order_by(Match.updated_at.desc()).all()

    # A match is in this queue because one side is stuck. Group under that side; if both
    # are stuck the match appears under each, because both need a person to act.
    groups = {}
    for m in ms:
        waiting = [t for t in (m.trip_a, m.trip_b)
                   if (m.party_for(t.id) is None or m.party_for(t.id).status == 'pending')]
        for t in (waiting or [m.trip_a]):
            party = m.party_for(t.id)
            if channel and (party.channel if party else 'none') != channel:
                continue
            g = groups.setdefault(t.id, {'trip': t, 'rows': []})
            g['rows'].append({'match': m, 'other': m.other_trip(t.id),
                              'party': party, 'other_party': m.party_for(m.other_trip(t.id).id)})
    if channel:
        groups = {k: g for k, g in groups.items() if g['rows']}

    ordered = sorted(groups.values(), key=lambda g: (-len(g['rows']), g['trip'].id))
    total_groups, total_matches = len(ordered), sum(len(g['rows']) for g in ordered)
    pages = max((total_groups + per_page - 1) // per_page, 1)
    page = min(page, pages)
    shown = ordered[(page - 1) * per_page: page * per_page]

    template = 'cs/_queue_results.html' if request.args.get('partial') else 'cs/match_queue.html'
    return render_template(template, groups=shown, page=page, pages=pages,
                           total=total_groups, total_matches=total_matches,
                           filters=dict(q=q, status=status, trip_type=trip_type, channel=channel),
                           MATCH_STATUSES=['suggested', 'notified', 'viewed', 'connected'],
                           CHANNEL_LABELS=CHANNEL_LABELS, **_choices())


def _back(default):
    return request.form.get('next') or default


@matches_bp.route('/cs/matches/<int:match_id>/notify', methods=['POST'])
@login_required
@cs_required
def cs_notify(match_id):
    match = Match.query.get_or_404(match_id)
    if not match.is_open:
        flash('This match is no longer open.', 'danger')
        return redirect(_back(url_for('cs.home')))
    parties, problems = bridge.notify_match(match, actor=current_user)
    sent = [p for p in parties if p.status == 'sent']
    flash(f'Notified {len(sent)} of 2 sides automatically.' if sent else 'No side could be notified automatically.',
          'success' if sent else 'info')
    for p in problems:
        flash(p, 'danger')
    if any(p.status == 'pending' and p.channel.startswith('manual_') for p in parties):
        flash('One side needs a manual message — use "Intro text" below and mark it sent.', 'info')
    return redirect(_back(url_for('matches.cs_matches', trip_id=match.trip_a_id)))


@matches_bp.route('/cs/matches/<int:match_id>/dismiss', methods=['POST'])
@login_required
@cs_required
def cs_dismiss(match_id):
    match = Match.query.get_or_404(match_id)
    reason = request.form.get('reason') if request.form.get('reason') in DISMISS_REASONS else 'not_suitable'
    match.status = 'dismissed'
    match.dismissed_reason = reason
    match.needs_cs_attention = False
    ActivityEvent.log('match_dismissed', match.trip_a, actor=current_user, match_id=match.id, reason=reason)
    db.session.commit()
    flash('Match dismissed.', 'success')
    return redirect(_back(url_for('matches.cs_matches', trip_id=match.trip_a_id)))


@matches_bp.route('/cs/matches/<int:match_id>/connected', methods=['POST'])
@login_required
@cs_required
def cs_connected(match_id):
    match = Match.query.get_or_404(match_id)
    for t in (match.trip_a, match.trip_b):
        p = MatchParty.get_or_create(match, t.id)
        p.status = 'connected'
        p.touch()
    match.status = 'connected'
    match.needs_cs_attention = False
    ActivityEvent.log('marked_contacted', match.trip_a, actor=current_user, match_id=match.id, by='cs')
    db.session.commit()
    flash('Marked as connected.', 'success')
    return redirect(_back(url_for('matches.cs_matches', trip_id=match.trip_a_id)))


@matches_bp.route('/cs/matches/<int:match_id>/intro-text', methods=['POST'])
@login_required
@cs_required
def cs_intro_text(match_id):
    """Formatted text for a manual DM to one side (plan §8.3 B). Only consented contact points are allowed."""
    match = Match.query.get_or_404(match_id)
    data = request.get_json(silent=True) or {}
    for_trip_id = int(data.get('for_trip_id') or 0)
    if for_trip_id not in (match.trip_a_id, match.trip_b_id):
        return jsonify({'error': 'for_trip_id must be one side of the match'}), 400
    for_trip = match.trip_a if for_trip_id == match.trip_a_id else match.trip_b
    other = match.other_trip(for_trip_id)
    ids = data.get('contact_point_ids')
    if ids is not None:
        allowed = {cp.id for cp in other.contact_points if cp.consent_to_share}
        bad = [i for i in ids if i not in allowed]
        if bad:
            return jsonify({'error': 'Only contact points the person consented to share can be included.'}), 400
    text = bridge.intro_text(match, for_trip, contact_point_ids=ids)
    party = match.party_for(for_trip_id)
    ActivityEvent.log('intro_text_generated', for_trip, actor=current_user, match_id=match.id,
                      contact_point_ids=ids)
    db.session.commit()
    return jsonify({'text': text, 'party_id': party.id if party else None})


@matches_bp.route('/cs/match-parties/<int:party_id>/mark-sent', methods=['POST'])
@login_required
@cs_required
def cs_mark_sent(party_id):
    party = MatchParty.query.get_or_404(party_id)
    data = request.get_json(silent=True) or request.form
    channel = data.get('channel') if data.get('channel') in PARTY_CHANNELS else None
    bridge.mark_manual_sent(party, current_user, channel=channel, note=(data.get('note') or '').strip()[:500])
    if request.is_json:
        return jsonify({'success': True, 'party': party.to_dict()})
    flash('Marked as sent.', 'success')
    return redirect(_back(url_for('matches.cs_matches', trip_id=party.trip_id)))
