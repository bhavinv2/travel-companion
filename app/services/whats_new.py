"""What has come in that nobody has dealt with -- the floating "what's new" button on staff pages.

The sidebar badges answer "is there anything on this screen"; they only help on a screen whose
menu you are already looking at, and the menu shows one product at a time. Somebody working the
Sahayak queue could not see that three insurance quote requests had arrived without switching
tabs to go and look. This is the one place that answers across all of them at once.

Five lists, and the definition of "new" is different for each because the data is:

  insurance  quote requests     no staff-facing status at all -- `status` only records whether
                                 the partner priced it -- so new means "since you last opened the
                                 quotes list", per person
  posts      companion posts    no "somebody looked at this" state either; same rule, and a post
                                 you created yourself is never new to you
  matches    matches waiting    the match queue's own definition -- needs_cs_attention, not
                                 dismissed -- narrowed to 'suggested', the ones nobody has acted on
  sahayak    Sahayak bookings   status 'new', i.e. not yet assigned
  contact    contact enquiries  status 'new', every topic -- Sahayak applications included, since
                                 that is the list the link opens and the count must match it

Where a status says "unhandled", that status is the answer, and it is the same number for every
member of staff: it is a shared queue. Where nothing does, the answer is personal, kept in
User.seen_marks and moved on whenever that person opens the list (see SEEN_BY_ENDPOINT).

Every item is filtered through cs_access, so an agent narrowed to the Sahayak queue is shown the
Sahayak count and nothing they would be turned away from. Admins see everything.
"""
from datetime import datetime, timedelta

from flask import url_for

# A member of staff who has never opened a list is shown the last two days of it rather than its
# entire history -- the CS console's own definition of a new post (cs.home, `new_posts`).
FIRST_LOOK = timedelta(hours=48)

ITEMS = [
    {'key': 'insurance', 'label': 'Insurance quote requests', 'icon': 'fa-shield-heart',
     'screen': 'insurance', 'seen': True,
     'admin': ('admin.insurance_quotes', {}), 'cs': ('cs.insurance_quotes', {})},
    {'key': 'posts', 'label': 'Companion posts', 'icon': 'fa-plane-departure',
     'screen': 'posts', 'seen': True,
     'admin': ('admin.listings', {}), 'cs': ('cs.posts', {})},
    {'key': 'matches', 'label': 'Matches waiting', 'icon': 'fa-handshake',
     'screen': 'matches',
     # there is no admin match screen; admins use the console's, which they can always open
     'admin': ('matches.cs_match_queue', {'status': 'suggested'}),
     'cs': ('matches.cs_match_queue', {'status': 'suggested'})},
    {'key': 'sahayak', 'label': 'Sahayak bookings', 'icon': 'fa-house-medical',
     'screen': 'sahayak',
     'admin': ('admin.sahayak_bookings', {'status': 'new'}),
     'cs': ('cs.sahayak_bookings', {'status': 'new'})},
    {'key': 'contact', 'label': 'Contact-us enquiries', 'icon': 'fa-envelope',
     'screen': 'voices',
     'admin': ('admin.voices', {'tab': 'contact', 'status': 'new'}),
     'cs': ('cs.voices', {'tab': 'contact', 'status': 'new'})},
]
_BY_KEY = {i['key']: i for i in ITEMS}

# Opening one of these lists is what "I have looked" means for the two personal counts. Both
# consoles, because an admin may work from either.
SEEN_BY_ENDPOINT = {
    'admin.insurance_quotes': 'insurance',
    'cs.insurance_quotes': 'insurance',
    'admin.listings': 'posts',
    'cs.posts': 'posts',
}


def _since(user, key, now):
    """When this person last opened list `key`, or the first-look window if they never have."""
    raw = ((getattr(user, 'seen_marks', None) or {}).get(key)) if user else None
    if raw:
        try:
            return datetime.fromisoformat(raw)
        except (TypeError, ValueError):
            pass                                  # a mark we cannot read counts as never
    return now - FIRST_LOOK


def _count(item, user, now):
    from app.models import CompanionRequest, ContactMessage, InsuranceQuote, Match, SahayakBooking

    key = item['key']
    if key == 'insurance':
        return InsuranceQuote.query.filter(
            InsuranceQuote.created_at > _since(user, key, now)).count()
    if key == 'posts':
        q = CompanionRequest.query.filter(CompanionRequest.created_at > _since(user, key, now),
                                          CompanionRequest.status != 'closed')
        if user is not None and getattr(user, 'id', None):
            # what you typed in yourself is not news to you -- an import of forty posts would
            # otherwise light the button up for the person who ran it
            q = q.filter((CompanionRequest.created_by_id.is_(None))
                         | (CompanionRequest.created_by_id != user.id))
        return q.count()
    if key == 'matches':
        return Match.query.filter(Match.needs_cs_attention.is_(True),
                                  Match.status == 'suggested').count()
    if key == 'sahayak':
        return SahayakBooking.query.filter_by(status='new').count()
    if key == 'contact':
        return ContactMessage.query.filter_by(status='new').count()
    return 0


def _hint(item, n):
    """The words beside the icon on hover. Says what the number means, because two of the five
    are "since you last looked" and three are "nobody has dealt with it", and a reader cannot
    tell which from a bare figure."""
    if not n:
        return 'nothing new' if item.get('seen') else 'nothing waiting'
    if item.get('seen'):
        return '%d new since you last looked' % n
    return '%d waiting' % n if item['key'] != 'contact' else '%d not opened yet' % n


def snapshot(user, console='cs'):
    """{'items': [...], 'total': n} for the widget. Never raises -- see below.

    `console` picks which screen each icon opens: an admin on the admin panel goes to the admin
    list, anybody on the CS console stays in the console.
    """
    from app.services import cs_access

    now = datetime.utcnow()
    out = []
    for item in ITEMS:
        if not cs_access.can_open(user, item['screen']):
            continue
        try:
            n = _count(item, user, now)
        except Exception:                         # noqa: BLE001
            # One list that cannot be counted -- a migration not yet run, a table locked -- must
            # not take the other four with it, and must never break the page it floats over.
            n = 0
        is_admin = bool(getattr(user, 'is_admin', False))
        endpoint, args = item['admin'] if (console == 'admin' and is_admin) else item['cs']
        out.append({'key': item['key'], 'label': item['label'], 'icon': item['icon'],
                    'count': n, 'hint': _hint(item, n), 'url': url_for(endpoint, **args)})
    return {'items': out, 'total': sum(i['count'] for i in out)}


def safe_snapshot(user, console='cs'):
    """snapshot(), or an empty widget. For the template, where an exception would cost the page."""
    try:
        return snapshot(user, console)
    except Exception:                             # noqa: BLE001
        return {'items': [], 'total': 0}


def mark_seen(user, key, when=None):
    """Record that `user` has just looked at list `key`. Only the personal lists keep a mark."""
    if key not in _BY_KEY or not _BY_KEY[key].get('seen') or user is None:
        return
    marks = dict(getattr(user, 'seen_marks', None) or {})
    marks[key] = (when or datetime.utcnow()).isoformat()
    # a fresh dict, not an in-place edit: a mutated JSON value is not seen as a change and would
    # never be written
    user.seen_marks = marks
