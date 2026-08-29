"""Communication bridge: decide how each side of a match can be reached, notify them, and log it.

Per doc/PHASE2_PLAN_ANALYSIS.md §5 the action depends on each party's consented contact points, not on where
the post came from:  consented e-mail → automatic e-mail · account → in-app notification ·
other consented contact → manual CS task · nothing consented → blocked (send the claim link first).
"""
from datetime import datetime, timedelta

from flask import current_app, url_for

from app import db
from app.models import Match, MatchParty, Notification, ActivityEvent, CONTACT_TYPE_LABELS
from app.services import mailer

MANUAL_PRIORITY = ('whatsapp', 'mobile', 'facebook', 'instagram', 'other')


def channel_for(trip):
    """Best available channel for a post: ('email'|'inapp'|'manual_<type>'|'none', ContactPoint|None)."""
    consented = [cp for cp in trip.contact_points if cp.consent_to_share]
    email = next((cp for cp in consented if cp.type == 'email'), None)
    if email:
        return 'email', email
    if trip.user_id:
        return 'inapp', None
    for t in MANUAL_PRIORITY:
        cp = next((cp for cp in consented if cp.type == t), None)
        if cp:
            return f'manual_{t}', cp
    return 'none', None


def contact_page_url(party):
    return url_for('matches.contact_page', token=party.token, _external=True)


def _email_subject(other):
    return f"[Connecting Desis] Possible travel companion for your {other.route_display} trip"


def notify_party(match, trip, actor=None):
    """Notify one side of a match. Returns the MatchParty."""
    other = match.other_trip(trip.id)
    channel, cp = channel_for(trip)
    party = MatchParty.get_or_create(match, trip.id, channel=channel)
    party.channel = channel
    db.session.flush()
    now = datetime.utcnow()

    if channel == 'email':
        ok = mailer.send_template(
            _email_subject(trip), [cp.value], 'email/match_found.txt',
            trip=trip, other=other, match=match, link=contact_page_url(party),
            site_url=current_app.config['SITE_URL'], support_email=current_app.config['SUPPORT_EMAIL'],
        )
        if ok:
            party.status, party.sent_at, party.sent_by_id = 'sent', now, (actor.id if actor else None)
            party.touch()
            ActivityEvent.log('email_sent', trip, actor=actor, match_id=match.id, to=cp.value)
        else:
            match.needs_cs_attention = True
            ActivityEvent.log('email_not_sent', trip, actor=actor, match_id=match.id, to=cp.value)
    elif channel == 'inapp':
        db.session.add(Notification(
            user_id=trip.user_id, type='match_found',
            title=f'Possible travel companion: {other.route_display}',
            body=f'{other.display_name} is travelling {other.route_display} on {other.from_date or "a similar date"} '
                 f'({match.score}% match). Open to see how to get in touch.',
            link=f'/match/{party.token}',
        ))
        party.status, party.sent_at, party.sent_by_id = 'sent', now, (actor.id if actor else None)
        party.touch()
        ActivityEvent.log('inapp_notified', trip, actor=actor, match_id=match.id)
    elif channel.startswith('manual_'):
        party.status = 'pending'
        match.needs_cs_attention = True
        ActivityEvent.log('manual_task_created', trip, actor=actor, match_id=match.id, channel=channel)
    else:
        party.status = 'pending'
        match.needs_cs_attention = True
        ActivityEvent.log('notify_blocked', trip, actor=actor, match_id=match.id,
                          reason='no consented contact and no account')
    return party


def notify_match(match, actor=None):
    """Notify both sides. Returns (parties, problems) where problems lists sides that could not be reached."""
    problems = []
    for trip in (match.trip_a, match.trip_b):
        ch, _ = channel_for(trip)
        if ch == 'none':
            problems.append(f"#{trip.id} ({trip.display_name}) has no consented contact and no account — send the claim link first.")
    parties = [notify_party(match, match.trip_a, actor), notify_party(match, match.trip_b, actor)]
    if any(p.status == 'sent' for p in parties) and match.status == 'suggested':
        match.status = 'notified'
    for t in (match.trip_a, match.trip_b):
        if t.status == 'open':
            t.status = 'matched'
    db.session.commit()
    return parties, problems


def intro_text(match, for_trip, contact_point_ids=None):
    """Formatted text CS pastes into a manual DM to `for_trip`'s person (plan §8.3 B).

    Includes only the OTHER party's consented contact points, optionally restricted to `contact_point_ids`.
    """
    other = match.other_trip(for_trip.id)
    party = MatchParty.get_or_create(match, for_trip.id)
    db.session.flush()
    consented = [cp for cp in other.contact_points if cp.consent_to_share and cp.type != 'inapp_chat']
    if contact_point_ids is not None:
        consented = [cp for cp in consented if cp.id in set(contact_point_ids)]
    from app.services.matching import ranked_matches_for
    n_matches = len(ranked_matches_for(for_trip))
    name = (for_trip.poster_name or for_trip.display_name or '').split(' ')[0]
    lines = [f"Hi {name}," if name else "Hi,", "",
             f"Good news from Connecting Desis: we found a traveller on the same route as your "
             f"{for_trip.route_display} trip ({match.score}% match"
             f"{', the closest of ' + str(n_matches) + ' possible matches' if n_matches > 1 else ''}).", "",
             f"• {other.display_name} — {other.route_display} on {other.from_date or 'a similar date'}"
             + (f", {other.airline} {other.flight_number or ''}".rstrip() if other.airline else "")
             + (f" ({(other.preferred_languages or [])[0]} speaker)" if other.preferred_languages else "")]
    if consented:
        lines.append("")
        lines.append("They agreed we may share these details with you:")
        for cp in consented:
            lines.append(f"  - {CONTACT_TYPE_LABELS.get(cp.type, cp.type)}: {cp.value}" + (f" ({cp.label})" if cp.label else ""))
    elif other.user_id:
        lines += ["", "They prefer to be contacted through Connecting Desis chat — use the link below."]
    lines += ["", f"See their request, other matches and how to get in touch: {contact_page_url(party)}", "",
              "Safe travels,", "The Connecting Desis team",
              "(We share contact details only with the other person's consent. Please use them respectfully.)"]
    return "\n".join(lines)


ALERT_THROTTLE = timedelta(hours=1)


def alert_new_matches(trip, new_matches, actor=None):
    """Heads-up (no contact sharing) to the OTHER side of each brand-new match, at most once per hour per post."""
    now = datetime.utcnow()
    by_other = {}
    for m in new_matches:
        if m.score < 60 or not trip.is_public:
            continue
        other = m.other_trip(trip.id)
        if not other.is_public:
            continue
        by_other.setdefault(other.id, [other, []])[1].append(m)
    alerted = 0
    for other, ms in by_other.values():
        if other.last_match_alert_at and now - other.last_match_alert_at < ALERT_THROTTLE:
            continue
        best = max(ms, key=lambda x: x.score)
        sent_via = []
        if other.user_id:
            db.session.add(Notification(
                user_id=other.user_id, type='match_found',
                title=f'New possible companion for {other.route_display}',
                body=f'{trip.display_name} is travelling {trip.route_display} on {trip.from_date or "a similar date"} '
                     f'({best.score}% match). Review it and choose whether to share your contact.',
                link='/dashboard',
            ))
            sent_via.append('inapp')
        ch, cp = channel_for(other)
        if ch == 'email' and mailer.send_template(
                f"[Connecting Desis] New possible companion for your {other.route_display} trip", [cp.value],
                'email/new_match_alert.txt', trip=other, other=trip, best=best, count=len(ms),
                site_url=current_app.config['SITE_URL'], support_email=current_app.config['SUPPORT_EMAIL']):
            sent_via.append('email')
        if sent_via:
            other.last_match_alert_at = now
            ActivityEvent.log('match_alert_sent', other, actor=actor, match_id=best.id, via=sent_via, count=len(ms))
            alerted += 1
    if alerted:
        db.session.commit()
    return alerted


def mark_manual_sent(party, actor, channel=None, note=None):
    party.channel = channel or party.channel
    party.status = 'sent'
    party.sent_at = datetime.utcnow()
    party.sent_by_id = actor.id if actor else None
    party.touch()
    match = party.match
    if match.status == 'suggested':
        match.status = 'notified'
    _recompute_attention(match)
    ActivityEvent.log('manual_dm_sent', party.trip, actor=actor, match_id=match.id,
                      channel=party.channel, note=note or None)
    db.session.commit()


def _recompute_attention(match):
    match.needs_cs_attention = any(p.status == 'pending' for p in match.parties)


def record_opened(party):
    now = datetime.utcnow()
    if not party.opened_at:
        party.opened_at = now
        ActivityEvent.log('link_opened', party.trip, match_id=party.match_id)
    if party.status in ('pending', 'sent'):
        party.status = 'opened'
    if party.match.status in ('suggested', 'notified'):
        party.match.status = 'viewed'
    party.touch()


def record_contact_viewed(party):
    now = datetime.utcnow()
    if not party.viewed_at:
        party.viewed_at = now
        ActivityEvent.log('contact_viewed', party.trip, match_id=party.match_id)
    if party.status in ('pending', 'sent', 'opened'):
        party.status = 'contact_viewed'
    party.touch()


def record_contacted(party, actor=None):
    party.status = 'connected'
    party.touch()
    party.match.status = 'connected'
    _recompute_attention(party.match)
    ActivityEvent.log('marked_contacted', party.trip, actor=actor, match_id=party.match_id)


def record_not_suitable(party, actor=None):
    party.status = 'not_suitable'
    party.touch()
    m = party.match
    m.status = 'dismissed'
    m.dismissed_reason = 'not_suitable_by_party'
    m.needs_cs_attention = False
    ActivityEvent.log('not_suitable', party.trip, actor=actor, match_id=m.id)


def record_report(party, reason, actor=None):
    m = party.match
    m.needs_cs_attention = True
    ActivityEvent.log('reported', party.trip, actor=actor, match_id=m.id, reason=(reason or '')[:500])
    # tell whoever created the other post (a CS agent) or fall back to any CS via the queue flag
    other = m.other_trip(party.trip_id)
    if other.created_by_id:
        db.session.add(Notification(user_id=other.created_by_id, type='cs_escalation',
                                    title='Match reported', body=f'Match #{m.id} was reported: {reason[:120]}',
                                    link=f'/cs/posts/{other.id}/matches'))
