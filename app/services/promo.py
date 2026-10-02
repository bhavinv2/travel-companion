"""The numbers an influencer needs, and nothing else.

Somebody promoting this service wants to know how much interest there is and what people are
saying, per product, so they can say something true in a video. They do not need -- and should
not have -- the enquirers themselves: names, e-mail addresses and phone numbers belong to the
people who wrote in, and a promotion dashboard is no reason to hand them out.

So: counts, averages, and the text of reviews that are already public because somebody approved
them. Read-only, and nothing here can change anything.
"""
from datetime import datetime, timedelta

from sqlalchemy import func

from app import db
from app.models import (CompanionRequest, ContactMessage, Feedback, InsuranceQuote,
                        REVIEW_SITE_LABELS, REVIEW_SITES)

# The three products, as this dashboard groups them. The contact inbox calls the companion app's
# enquiries 'companion' and the group page's 'general', so both are shown against their site.
SITES = [
    {'key': 'companion', 'label': 'Travel Companion', 'topics': ['companion']},
    {'key': 'insurance', 'label': 'Travel Insurance', 'topics': ['insurance']},
    {'key': 'sahayak', 'label': 'Sahayak', 'topics': []},
]
WINDOW_DAYS = 30


def _since():
    return datetime.utcnow() - timedelta(days=WINDOW_DAYS)


def _counts(column, model, extra=None):
    """{value: count} for one column, so a single query answers a whole row of the table."""
    q = db.session.query(column, func.count(model.id))
    if extra is not None:
        q = q.filter(extra)
    return {k: n for k, n in q.group_by(column).all()}


def enquiries():
    """Contact messages per kind, all time and in the last month."""
    from app.models import CONTACT_TOPICS, CONTACT_TOPIC_LABELS
    total = _counts(ContactMessage.topic, ContactMessage)
    recent = _counts(ContactMessage.topic, ContactMessage,
                     ContactMessage.created_at >= _since())
    rows = [{'key': t, 'label': CONTACT_TOPIC_LABELS.get(t, t),
             'total': total.get(t, 0), 'recent': recent.get(t, 0)} for t in CONTACT_TOPICS]
    return {'rows': rows,
            'total': sum(r['total'] for r in rows),
            'recent': sum(r['recent'] for r in rows)}


def reviews():
    """Approved reviews per product, with the average somebody could quote.

    Only approved ones are counted: an average that included reviews nobody has read yet would
    move when they are moderated, and the number is going into a video.
    """
    approved = Feedback.is_approved.is_(True)
    counts = _counts(Feedback.site, Feedback, approved)
    pending = _counts(Feedback.site, Feedback, Feedback.is_approved.is_(False))
    avgs = dict(db.session.query(Feedback.site, func.avg(Feedback.rating))
                .filter(approved).group_by(Feedback.site).all())
    rows = []
    for key in REVIEW_SITES:
        n = counts.get(key, 0)
        avg = avgs.get(key)
        rows.append({'key': key, 'label': REVIEW_SITE_LABELS[key], 'count': n,
                     'pending': pending.get(key, 0),
                     # below a handful, a specific average reads as invented
                     'avg': round(float(avg), 1) if avg is not None and n >= 3 else None})
    return {'rows': rows, 'total': sum(r['count'] for r in rows)}


def quotable(limit=8):
    """Approved reviews with words in them, newest first -- the ones worth quoting."""
    rows = (Feedback.query.filter(Feedback.is_approved.is_(True), Feedback.comment.isnot(None))
            .order_by(Feedback.created_at.desc()).limit(limit * 2).all())
    out = []
    for fb in rows:
        text = (fb.comment or '').strip()
        if not text:
            continue
        out.append({'text': text, 'rating': fb.rating,
                    'site': REVIEW_SITE_LABELS.get(fb.site or 'companion', fb.site),
                    'who': fb.user.username if fb.user else 'A traveller',
                    'when': fb.created_at})
        if len(out) >= limit:
            break
    return out


def demand():
    """What each product has actually produced, for the headline tiles."""
    from app.models import SahayakBooking
    since = _since()
    return [
        {'label': 'Trips posted', 'site': 'Travel Companion',
         'total': CompanionRequest.query.count(),
         'recent': CompanionRequest.query.filter(CompanionRequest.created_at >= since).count()},
        {'label': 'Insurance quote requests', 'site': 'Travel Insurance',
         'total': InsuranceQuote.query.count(),
         'recent': InsuranceQuote.query.filter(InsuranceQuote.created_at >= since).count()},
        {'label': 'Sahayak bookings', 'site': 'Sahayak',
         'total': SahayakBooking.query.count(),
         'recent': SahayakBooking.query.filter(SahayakBooking.created_at >= since).count()},
    ]


def snapshot():
    return {'window_days': WINDOW_DAYS, 'enquiries': enquiries(), 'reviews': reviews(),
            'demand': demand(), 'quotable': quotable()}
