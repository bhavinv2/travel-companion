"""How many rows on each staff screen are still waiting for somebody.

The menu named the screens but never said which of them had work in it, so the only way to find
out that three enquiries had come in was to open the inbox and look -- and the enquiry inbox is
four menu lines now, split by product, so "look" meant opening four. A number on the line is the
whole point of grouping them in the first place.

What counts as waiting is per screen. On User voices and the match queue it is "you have not
opened it" (models.ReadMark), not "nobody has finished it", so the number falls as you read the list
rather than only when each item is closed -- and it is personal: what a colleague opened is still
new to you.

    contact enquiries   not opened by you
    feedback            not opened by you
    match reports       not opened by you
    match queue         posts with a queued match you have not opened -- opening the post's
                                             matches page reads them all; counted per post, as
                                             the queue is grouped
    notifications       not read          -- this agent's own, which is the one count here
                                             that is personal rather than a shared queue

Keyed by the sidebar keys in services/admin_nav, plus 'voices' for the CS console, whose menu has
one line for the whole screen rather than one per slice.

Counted in four aggregate queries rather than one per line, and only when a sidebar actually
renders -- the context processor hands templates the function, not the result, so a public page
never pays for it. Within one request the answer is cached, because both sidebars and the header
can each ask.
"""

from app import db


def _by(column, model, *filters):
    """{value: count} for one column, in a single grouped query."""
    rows = db.session.query(column, db.func.count(model.id)).filter(*filters).group_by(column).all()
    return {value: count for value, count in rows}


def _unread_match_posts(user):
    """Posts in the CS match queue with at least one match `user` has not opened.

    Posts, not matches, because the queue is grouped by post and opening one post reads all of
    its matches: one click, one fewer. Which post a match is filed under depends on whose side is
    stuck, which is not a column, so it is worked out the same way the queue does it.
    """
    from sqlalchemy.orm import selectinload

    from app.models import Match

    ms = (Match.query.options(selectinload(Match.parties), selectinload(Match.trip_a),
                              selectinload(Match.trip_b))
          .filter(Match.needs_cs_attention.is_(True), Match.status != 'dismissed',
                  Match.unread_by(user)).all())
    return len({t.id for m in ms for t in m.waiting_trips()})


def _compute(user):

    from app.models import ContactMessage, Feedback, MatchReport, Notification

    # topic -> how many nobody has opened. The keys are the sidebar's, not the model's, because
    # that is what the template looks them up by.
    by_topic = _by(ContactMessage.topic, ContactMessage, ContactMessage.unread_by(user))
    out = {
        'voices_contact': by_topic.get('companion', 0),
        'voices_insurance': by_topic.get('insurance', 0),
        'voices_sahayak': by_topic.get('sahayak', 0),
        'voices_general': by_topic.get('general', 0),
        'voices_feedback': Feedback.query.filter(Feedback.unread_by(user)).count(),
        'voices_report': MatchReport.query.filter(MatchReport.unread_by(user)).count(),
    }
    # Every topic, for the "Contact us" tab on the voices screen, which is not split by topic.
    # A topic with no line of its own still has to be in this total, or an enquiry filed under
    # something the menu does not split by would go uncounted everywhere.
    out['voices_inbox'] = sum(by_topic.values())
    # The CS console has one "User voices" line covering all three tabs, so it carries the lot.
    out['voices'] = out['voices_inbox'] + out['voices_feedback'] + out['voices_report']
    out['matches'] = _unread_match_posts(user)

    # The one personal count: a shared queue is the same number for everybody looking at it,
    # but "notifications" means the ones addressed to whoever is signed in. Same figure as the
    # bell in the header, so the two cannot disagree about whether there is anything to read.
    if getattr(user, 'is_authenticated', False):
        out['notifications'] = Notification.query.filter_by(
            user_id=user.id, is_read=False).count()
    return out


def unread(user=None):
    """{sidebar key: how many rows are waiting} for `user` (default: whoever is signed in).
    Empty if anything goes wrong.

    Never raises: this decorates a menu. A badge that cannot be counted must not take down every
    staff screen that draws one -- an install mid-migration would lose the whole console over a
    number nobody needs to see.
    """
    if user is None:
        from flask_login import current_user
        user = current_user
    from app.models import request_cache
    cache = request_cache('nav_badges')
    key = getattr(user, 'id', None) if getattr(user, 'is_authenticated', False) else None
    if key not in cache:
        try:
            cache[key] = _compute(user)
        except Exception:                        # noqa: BLE001 -- see the docstring
            cache[key] = {}
    return cache[key]


def forget():
    """Drop this request's counts -- after a write that changes them."""
    from app.models import request_cache
    request_cache('nav_badges').clear()
