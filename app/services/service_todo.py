"""Service to-do (cs.home): the trip posts customer service has to chase. Health (services/health.py) counts
the same list, so the two screens cannot disagree about how many there are."""
from datetime import date, datetime, timedelta

from app.models import ClaimToken, CompanionRequest


def needs_action(today=None, now=None):
    """[(why, post)]: a claim link sent more than 3 days ago with no answer, no claim link two days after the post
    came in, and a post leaving within 3 days that nobody may be contacted about."""
    today = today or date.today()
    now = now or datetime.utcnow()
    out = []
    for t in CompanionRequest.query.filter_by(status='unconfirmed').order_by(CompanionRequest.created_at.asc()).all():
        tok = t.claim_tokens.order_by(ClaimToken.created_at.desc()).first()
        # created_at has a Python-side default, not a DB-enforced one, so a row written outside
        # the normal ORM path (a data fix, a bulk import) can legitimately have it as NULL —
        # guard the comparison rather than letting one such row 500 the whole CS home page.
        if tok and tok.used_at is None and tok.created_at and tok.created_at < now - timedelta(days=3):
            out.append(('No response to claim link for %d days' % (now - tok.created_at).days, t))
        elif tok is None and t.created_at and t.created_at < now - timedelta(days=2):
            out.append(('No claim link sent yet', t))
    leaving = CompanionRequest.query.filter(CompanionRequest.status.in_(['open', 'matched']),
                                            CompanionRequest.from_date >= today,
                                            CompanionRequest.from_date <= today + timedelta(days=3))
    for t in leaving.all():
        if not t.consented_contact_types:
            out.append(('Departing soon with no consented contact', t))
    return out
