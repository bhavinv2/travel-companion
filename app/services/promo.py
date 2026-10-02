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
    return {'window_days': WINDOW_DAYS, 'months': MONTHS,
            'enquiries': enquiries(), 'reviews': reviews(),
            'demand': demand(), 'quotable': quotable(),
            'trend': trend(), 'routes': top_routes(), 'destinations': top_destinations(),
            'ratings': rating_spread(), 'reach': reach(), 'links': links()}


# ---------------------------------------------------------------------------
# The detail: what is actually being asked for, and where
#
# All of it aggregate. Every query below groups or counts -- none of them select a name, an
# e-mail or a phone number, which is the whole rule this module exists to keep.
# ---------------------------------------------------------------------------

MONTHS = 6


def _month_key(dt):
    return (dt.year, dt.month)


def _month_labels(n=MONTHS):
    """The last n months, oldest first, as (key, 'Mon YY')."""
    today = datetime.utcnow()
    out = []
    y, m = today.year, today.month
    for _ in range(n):
        out.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    out.reverse()
    names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
             'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    return [((y, m), '%s %02d' % (names[m - 1], y % 100)) for y, m in out]


def _by_month(column, model, keys):
    """Counts per month for one model, bucketed in Python.

    Not in SQL: date_trunc is Postgres and strftime is SQLite, and a dashboard is no place to
    maintain two. Only the timestamp column is selected, and only for the window shown.
    """
    first = datetime(keys[0][0], keys[0][1], 1)
    rows = db.session.query(column).filter(column >= first).all()
    counts = {}
    for (dt,) in rows:
        if dt:
            counts[_month_key(dt)] = counts.get(_month_key(dt), 0) + 1
    return [counts.get(k, 0) for k in keys]


def trend(months=MONTHS):
    """Month by month, so the page shows a direction and not just a total.

    `max` rides along because the bars are drawn as percentages of it and working that out in
    the template means three passes over the same list.
    """
    labelled = _month_labels(months)
    keys = [k for k, _ in labelled]
    # 'counts', not 'values': dot access in Jinja prefers an attribute, and every dict has a
    # .values method, so {{ s.values }} hands the template the method instead of the list.
    series = [
        {'label': 'Trips posted', 'key': 'companion',
         'counts': _by_month(CompanionRequest.created_at, CompanionRequest, keys)},
        {'label': 'Insurance quotes', 'key': 'insurance',
         'counts': _by_month(InsuranceQuote.created_at, InsuranceQuote, keys)},
        {'label': 'Enquiries', 'key': 'contact',
         'counts': _by_month(ContactMessage.created_at, ContactMessage, keys)},
    ]
    for s in series:
        s['total'] = sum(s['counts'])
    peak = max([max(s['counts']) for s in series] + [1])
    return {'months': [lbl for _, lbl in labelled], 'series': series, 'max': peak}


def top_routes(limit=6):
    """Where people are actually flying, by city pair. A route is not a person."""
    rows = (db.session.query(CompanionRequest.origin_city, CompanionRequest.dest_city,
                             func.count(CompanionRequest.id))
            .filter(CompanionRequest.origin_city.isnot(None),
                    CompanionRequest.dest_city.isnot(None))
            .group_by(CompanionRequest.origin_city, CompanionRequest.dest_city)
            .order_by(func.count(CompanionRequest.id).desc())
            .limit(limit).all())
    return [{'route': '%s to %s' % (a, b), 'count': n} for a, b, n in rows if a and b]


def top_destinations(limit=6):
    """Which countries the insurance questions are about, by name rather than ISO-3."""
    from app.services import insurance_countries
    names = {code: name for code, name in insurance_countries.ALL}
    rows = (db.session.query(InsuranceQuote.destination, func.count(InsuranceQuote.id))
            .filter(InsuranceQuote.destination.isnot(None))
            .group_by(InsuranceQuote.destination)
            .order_by(func.count(InsuranceQuote.id).desc())
            .limit(limit).all())
    return [{'label': names.get(code, code), 'count': n} for code, n in rows if code]


def rating_spread():
    """Five down to one, with the share each takes. The shape of the praise, not just its mean."""
    counts = _counts(Feedback.rating, Feedback, Feedback.is_approved.is_(True))
    total = sum(counts.values()) or 0
    return {'total': total,
            'rows': [{'stars': s, 'count': counts.get(s, 0),
                      'pct': round(100.0 * counts.get(s, 0) / total) if total else 0}
                     for s in (5, 4, 3, 2, 1)]}


def reach():
    """Facts about the business that are true and quotable, read from where they are defined."""
    from app import options
    from app.services import offices
    return [
        {'label': 'Countries we have an office in', 'value': len(offices.countries())},
        {'label': 'Support lines published', 'value': len(offices.numbers())},
        {'label': 'Languages the site runs in', 'value': len(options.SITE_LANGUAGES)},
        {'label': 'Products', 'value': len(SITES)},
    ]


def links():
    """The public addresses, so whoever is promoting them does not have to remember which is
    which. urls.public_url, because insurance and the contact page answer beside the app's
    prefix rather than inside it."""
    from app.services import urls
    return [
        {'label': 'Travel Companion', 'url': urls.public_url('main.index')},
        {'label': 'Travel Insurance', 'url': urls.public_url('insurance.landing')},
        {'label': 'Sahayak', 'url': urls.public_url('sahayak.landing')},
        {'label': 'Contact us', 'url': urls.public_url('main.contact_us')},
        {'label': 'Reviews', 'url': urls.public_url('main.reviews')},
    ]
