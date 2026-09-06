"""Scheduled housekeeping: escalate silent matches to CS, close departed posts.

Triggered by `POST /internal/jobs/run` (header X-Jobs-Secret) from an external scheduler (Railway cron,
Cloud Scheduler, GitHub Actions…) or by `flask run-jobs`. Idempotent — safe to run every 15 minutes.
"""
from datetime import datetime, date, timedelta

from app import db
from app.models import MatchParty, CompanionRequest, Notification, ActivityEvent

# (max days to departure, hours of silence before escalating) — plan §9: tiered, not a flat 2-3 h.
ESCALATION_TIERS = [(2, 2), (7, 12), (None, 24)]


def escalation_hours(trip):
    d = trip.days_to_departure
    for max_days, hours in ESCALATION_TIERS:
        if max_days is None or (d is not None and d <= max_days):
            return hours
    return ESCALATION_TIERS[-1][1]


def run_escalation(now=None):
    """Flag matches where a notified side has not opened its link within the tiered window."""
    now = now or datetime.utcnow()
    escalated = 0
    parties = (MatchParty.query
               .filter(MatchParty.status == 'sent', MatchParty.escalated_at.is_(None),
                       MatchParty.sent_at.isnot(None))
               .all())
    for p in parties:
        m = p.match
        if m.status in ('dismissed', 'connected') or not p.trip.is_public:
            continue
        hours = escalation_hours(p.trip)
        if now - p.sent_at < timedelta(hours=hours):
            continue
        p.escalated_at = now
        p.touch()
        m.needs_cs_attention = True
        ActivityEvent.log('escalated', p.trip, match_id=m.id, hours=hours, channel=p.channel)
        # Tell the CS agent who created either post (if any); the match queue catches the rest.
        other = m.other_trip(p.trip_id)
        from app.services import notify
        for cs_id in {p.trip.created_by_id, other.created_by_id, m.cs_owner_id} - {None}:
            notify.push(
                cs_id, 'cs_escalation',
                title=f'No response on match #{m.id}',
                body=f'{p.trip.display_name} ({p.trip.route_display}) has not opened the link sent '
                     f'{hours}h ago via {p.channel}. Please follow up.',
                link=f'/cs/posts/{p.trip_id}/matches',
            )
        escalated += 1
    db.session.commit()
    return escalated


def close_departed_posts(today=None):
    """Posts whose departure date has passed are closed as 'travelled' and their matches dismissed."""
    from app.services.matching import dismiss_matches_for_closed_trip
    today = today or date.today()
    closed = 0
    posts = (CompanionRequest.query
             .filter(CompanionRequest.status.in_(['open', 'matched', 'unconfirmed']),
                     CompanionRequest.from_date.isnot(None),
                     CompanionRequest.from_date < today - timedelta(days=1))
             .all())
    for t in posts:
        t.set_status('closed', reason='travelled')
        dismiss_matches_for_closed_trip(t)
        ActivityEvent.log('post_auto_closed', t, reason='travelled')
        closed += 1
    db.session.commit()
    return closed


def run_retention(today=None):
    """Apply the retention rules promised in the Privacy Policy.

    - Ticket attachments are deleted RETENTION_DAYS (default 30) after the departure date.
    - CS-created posts that were never confirmed by the person are deleted (with their contact details)
      once the departure date has passed — we said we would not keep unconfirmed requests.
    - Expired, unused claim tokens older than 60 days are purged.
    """
    from flask import current_app
    from app.models import ClaimToken, Match, ConnectionRequest
    from app.services.storage import delete_private
    today = today or date.today()
    days = int(current_app.config.get('RETENTION_DAYS', 30))
    result = {'attachments_deleted': 0, 'unconfirmed_deleted': 0, 'tokens_purged': 0}

    for t in (CompanionRequest.query
              .filter(CompanionRequest.ticket_attachment.isnot(None),
                      CompanionRequest.from_date.isnot(None),
                      CompanionRequest.from_date < today - timedelta(days=days)).all()):
        delete_private(t.ticket_attachment)
        t.ticket_attachment = None
        ActivityEvent.log('attachment_deleted', t, reason='retention')
        result['attachments_deleted'] += 1

    stale = (CompanionRequest.query
             .filter(CompanionRequest.source != 'organic', CompanionRequest.claimed_at.is_(None),
                     CompanionRequest.user_id.is_(None), CompanionRequest.from_date.isnot(None),
                     CompanionRequest.from_date < today - timedelta(days=1)).all())
    for t in stale:
        if t.ticket_attachment:
            delete_private(t.ticket_attachment)
        Match.query.filter((Match.trip_a_id == t.id) | (Match.trip_b_id == t.id)).delete(synchronize_session=False)
        for c in ConnectionRequest.query.filter_by(trip_id=t.id).all():
            Notification.query.filter_by(connection_id=c.id).update({'connection_id': None})
            db.session.delete(c)
        ActivityEvent.query.filter_by(trip_id=t.id).delete(synchronize_session=False)
        db.session.delete(t)   # contact points and claim tokens cascade
        result['unconfirmed_deleted'] += 1

    cutoff = datetime.utcnow() - timedelta(days=60)
    result['tokens_purged'] = ClaimToken.query.filter(ClaimToken.used_at.is_(None),
                                                      ClaimToken.expires_at < cutoff).delete(synchronize_session=False)

    # Scraped rows are third-party personal data: keep only those that became posts.
    from app.models import ScrapeRow, ScrapeRun
    scrape_days = int(current_app.config.get('SCRAPER_ROWS_RETENTION_DAYS', 30))
    scrape_cutoff = datetime.utcnow() - timedelta(days=scrape_days)
    result['scrape_rows_purged'] = (ScrapeRow.query
                                    .filter(ScrapeRow.status != 'imported', ScrapeRow.created_at < scrape_cutoff)
                                    .delete(synchronize_session=False))
    for run in ScrapeRun.query.filter(ScrapeRun.created_at < scrape_cutoff, ScrapeRun.result.isnot(None)).all():
        run.result = None   # detect/preview payloads carry sample rows
    db.session.commit()
    return result


def run_all():
    from app.services import scraper_worker
    out = {
        'escalated': run_escalation(),
        'closed_departed': close_departed_posts(),
    }
    out.update(run_retention())
    out['scrape_stale_recovered'] = scraper_worker.recover_stale_runs()
    out['scrape_runs_started'] = scraper_worker.enqueue_scheduled()
    return out
