"""Single gate for every notification the app produces.

A notification goes out only if (1) the global master switch is on, (2) its channel (e-mail / in-app) is on,
(3) its category is on, and (4) the recipient — when they have an account — has not muted that category or
channel in their own preferences. Admins manage (1)-(3) at /admin/notifications; users manage (4) at
/settings/notifications.
"""
from app import db
from app.models import Notification, User, NOTIFY_CATEGORIES, USER_PREF_CATEGORIES
from app.services import settings

CATEGORY_FOR_TYPE = {
    'connection_request': 'connection', 'connection_accepted': 'connection', 'connection_denied': 'connection',
    'trip_modified': 'connection', 'trip_cancelled': 'connection',
    'message': 'chat',
    'blog': 'announcements', 'broadcast': 'announcements',
    'cs_escalation': 'cs', 'post_claimed': 'cs',
    'match_found': 'match_alerts', 'contact_shared': 'match_intro', 'contact_request': 'match_intro',
}

# Counts per category for the current process (cheap observability for the admin page)
SUPPRESSED = []


def category_of(ntype, category=None):
    return category or CATEGORY_FOR_TYPE.get(ntype, 'other')


def allowed(category, channel, user=None) -> bool:
    """Global switches first, then the recipient's own preferences (for account holders)."""
    sw = settings.notification_switches()
    if not sw['enabled']:
        return False
    if not sw['channels'].get(channel, True):
        return False
    if category in NOTIFY_CATEGORIES and not sw['categories'].get(category, True):
        return False
    if user is not None and category in USER_PREF_CATEGORIES:
        prefs = user.notify_prefs or {}
        if prefs.get('muted'):
            return False
        if channel == 'email' and prefs.get('email') is False:
            return False
        if prefs.get(category) is False:
            return False
    return True


def push(user_id, ntype, title, body=None, link=None, connection_id=None, category=None):
    """Create an in-app Notification if the switches allow it. Returns the Notification or None."""
    cat = category_of(ntype, category)
    user = db.session.get(User, user_id) if user_id else None
    if user is None or not allowed(cat, 'inapp', user):
        SUPPRESSED.append({'channel': 'inapp', 'category': cat, 'type': ntype, 'user_id': user_id})
        return None
    n = Notification(user_id=user_id, type=ntype, title=title, body=body, link=link, connection_id=connection_id)
    db.session.add(n)
    return n


def email_allowed(category, recipient_email) -> bool:
    user = None
    if recipient_email:
        user = User.query.filter_by(email=str(recipient_email).strip().lower()).first()
    ok = allowed(category, 'email', user)
    if not ok:
        SUPPRESSED.append({'channel': 'email', 'category': category, 'to': recipient_email})
    return ok


def user_prefs(user) -> dict:
    """Effective per-user preferences with defaults (everything on)."""
    prefs = dict(user.notify_prefs or {})
    out = {'muted': bool(prefs.get('muted', False)), 'email': prefs.get('email', True) is not False}
    for c in USER_PREF_CATEGORIES:
        out[c] = prefs.get(c, True) is not False
    return out
