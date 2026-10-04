"""How many rows on each staff screen are still waiting for somebody.

The menu named the screens but never said which of them had work in it, so the only way to find
out that three enquiries had come in was to open the inbox and look -- and the enquiry inbox is
four menu lines now, split by product, so "look" meant opening four. A number on the line is the
whole point of grouping them in the first place.

What counts as waiting is per screen, and it is always the state a human has not acted on yet:

    contact enquiries   status 'new'      -- nobody has opened it
    feedback            not approved      -- nobody has decided whether it may be published
    match reports       status 'open'     -- nobody has resolved it
    notifications       not read          -- this agent's own, which is the one count here
                                             that is personal rather than a shared queue

Keyed by the sidebar keys in services/admin_nav, plus 'voices' for the CS console, whose menu has
one line for the whole screen rather than one per slice.

Counted in four aggregate queries rather than one per line, and only when a sidebar actually
renders -- the context processor hands templates the function, not the result, so a public page
never pays for it. Within one request the answer is cached, because both sidebars and the header
can each ask.
"""
from flask import g

from app import db


def _by(column, model, *filters):
    """{value: count} for one column, in a single grouped query."""
    rows = db.session.query(column, db.func.count(model.id)).filter(*filters).group_by(column).all()
    return {value: count for value, count in rows}


def _compute():
    from flask_login import current_user

    from app.models import ContactMessage, Feedback, MatchReport, Notification

    # topic -> how many nobody has opened. The keys are the sidebar's, not the model's, because
    # that is what the template looks them up by.
    by_topic = _by(ContactMessage.topic, ContactMessage, ContactMessage.status == 'new')
    out = {
        'voices_contact': by_topic.get('companion', 0),
        'voices_insurance': by_topic.get('insurance', 0),
        'voices_sahayak': by_topic.get('sahayak', 0),
        'voices_general': by_topic.get('general', 0),
        'voices_feedback': Feedback.query.filter_by(is_approved=False).count(),
        'voices_report': MatchReport.query.filter_by(status='open').count(),
    }
    # The CS console has one "User voices" line covering all three tabs, so it carries the lot.
    # A topic with no line of its own still has to be in this total, or an enquiry filed under
    # something the menu does not split by would go uncounted everywhere.
    out['voices'] = (sum(by_topic.values())
                     + out['voices_feedback'] + out['voices_report'])

    # The one personal count: a shared queue is the same number for everybody looking at it,
    # but "notifications" means the ones addressed to whoever is signed in. Same figure as the
    # bell in the header, so the two cannot disagree about whether there is anything to read.
    if getattr(current_user, 'is_authenticated', False):
        out['notifications'] = Notification.query.filter_by(
            user_id=current_user.id, is_read=False).count()
    return out


def unread():
    """{sidebar key: how many rows are waiting}. Empty if anything goes wrong.

    Never raises: this decorates a menu. A badge that cannot be counted must not take down every
    staff screen that draws one -- an install mid-migration would lose the whole console over a
    number nobody needs to see.
    """
    if 'nav_badges' not in g:
        try:
            g.nav_badges = _compute()
        except Exception:                        # noqa: BLE001 -- see the docstring
            g.nav_badges = {}
    return g.nav_badges
