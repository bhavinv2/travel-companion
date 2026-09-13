"""Helpers for the admin/CS "Notifications" management screen — a searchable, filterable,
paginated view of every in-app notification, plus a targeted send-to-user(s) action.

Kept out of the route modules so admin.py and cs.py share exactly one implementation (the two
screens differ only in whether delete is offered).
"""
from datetime import datetime, timedelta
from sqlalchemy import or_, false
from app import db
from app.models import Notification, User
from app.services.notify import CATEGORY_FOR_TYPE

# The categories offered in the filter dropdown (short labels; the switches page has the long ones).
CATEGORY_ORDER = ['match_alerts', 'match_intro', 'connection', 'chat', 'announcements', 'cs', 'other']
CATEGORY_LABELS = {
    'match_alerts': 'Match alerts', 'match_intro': 'Match intros', 'connection': 'Connections',
    'chat': 'Chat messages', 'announcements': 'Announcements', 'cs': 'CS alerts', 'other': 'Other',
}
SEND_GROUPS = [('all', 'All active users'), ('verified', 'Verified users only'),
               ('unverified', 'Unverified users only')]


def _types_in_category(cat):
    return [t for t, c in CATEGORY_FOR_TYPE.items() if c == cat]


def _parse_date(s):
    try:
        return datetime.strptime((s or '').strip(), '%Y-%m-%d')
    except (ValueError, TypeError):
        return None


def build_query(args):
    """A Notification query filtered by the request args: q (title/body/user), category, status
    (read/unread), user (username or e-mail), user_id, from/to (created_at date range)."""
    q = Notification.query.join(User, Notification.user_id == User.id)

    search = (args.get('q') or '').strip()
    if search:
        pat = f"%{search}%"
        q = q.filter(or_(Notification.title.ilike(pat), Notification.body.ilike(pat),
                         User.username.ilike(pat), User.email.ilike(pat)))

    category = (args.get('category') or '').strip()
    if category == 'other':
        known = list(CATEGORY_FOR_TYPE.keys())
        q = q.filter(or_(Notification.type.is_(None), Notification.type.notin_(known)))
    elif category:
        types = _types_in_category(category)
        q = q.filter(Notification.type.in_(types)) if types else q.filter(false())

    status = (args.get('status') or '').strip()
    if status == 'read':
        q = q.filter(Notification.is_read.is_(True))
    elif status == 'unread':
        q = q.filter(Notification.is_read.is_(False))

    user_id = (args.get('user_id') or '').strip()
    if user_id.isdigit():
        q = q.filter(Notification.user_id == int(user_id))
    user = (args.get('user') or '').strip()
    if user:
        pat = f"%{user}%"
        q = q.filter(or_(User.username.ilike(pat), User.email.ilike(pat)))

    d_from = _parse_date(args.get('from'))
    if d_from:
        q = q.filter(Notification.created_at >= d_from)
    d_to = _parse_date(args.get('to'))
    if d_to:
        q = q.filter(Notification.created_at < d_to + timedelta(days=1))   # inclusive end-of-day

    return q.order_by(Notification.created_at.desc())


def category_of(ntype):
    return CATEGORY_FOR_TYPE.get(ntype, 'other')


def resolve_user(text):
    """Look up a user by exact username or e-mail. Returns (user_or_None, was_searched) so a
    caller can tell "no text given" (group send) from "text given but no match" (an error)."""
    from sqlalchemy import func
    text = (text or '').strip()
    if not text:
        return None, False
    u = User.query.filter(or_(func.lower(User.username) == text.lower(),
                              func.lower(User.email) == text.lower())).first()
    return u, True


def send(title, body, link, group, user_id):
    """Push an admin/CS 'broadcast' notification to one user (user_id) or a group. Respects the
    notification switches and each recipient's preferences (via notify.push). Returns (sent, total)."""
    from app.services import notify
    title = (title or '').strip()[:255]
    body = (body or '').strip()
    link = (link or '').strip()[:500] or '/'
    if not title or not body:
        return None  # caller treats None as a validation error

    recipients = []
    if user_id and str(user_id).strip().isdigit():
        u = db.session.get(User, int(user_id))
        if u and u.is_active:
            recipients = [u]
    else:
        uq = User.query.filter_by(is_active=True)
        if group == 'verified':
            uq = uq.filter_by(is_verified=True)
        elif group == 'unverified':
            uq = uq.filter_by(is_verified=False)
        recipients = uq.all()

    sent = 0
    for u in recipients:
        if notify.push(u.id, 'broadcast', title=title, body=body, link=link) is not None:
            sent += 1
    db.session.commit()
    return sent, len(recipients)
