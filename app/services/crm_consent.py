""""OK to send offers" (Sales CRM 2.0, run 5b): CrmPerson.consent_marketing, with when and how it was given or taken
back (consent_marketing_at / _how / _by_id).

It is NOT the WhatsApp tick ("Send my quote and updates on WhatsApp", consent_whatsapp): that one lets us answer and
follow up on WhatsApp; this one is permission to send offers (broadcasts, promotions). A public form sets it only
when the form has its own offers tick (`offers_consent`); the contact page's switch sets or clears it by hand.
Shown on the contact page, in the downloads and as a Report builder filter. Never sends anything.
"""
from datetime import datetime, timedelta

from app import db

LABEL = 'OK to send offers'
IST = timedelta(hours=5, minutes=30)
HOW_FORM = 'form: '
HOW_PAGE = 'contact page'
HOW_MERGE = 'merge'
BROADCAST_NOTE = "Only send offers to people with 'OK to send offers'."


def set_offers(person, on, how, by=None, at=None):
    """Give (on) or take back (off) the permission. Returns True when it changed. No commit."""
    on = bool(on)
    if bool(person.consent_marketing) == on:
        return False
    person.consent_marketing = on
    person.consent_marketing_at = at or datetime.utcnow()
    person.consent_marketing_how = (how or '')[:120] or None
    person.consent_marketing_by_id = getattr(by, 'id', None) if by is not None and not isinstance(by, int) else by
    return True


def from_form(person, form_name, at=None):
    """A public form's own offers tick was ticked: given (unless it already was). Never taken back by a form."""
    if person is None or person.consent_marketing:
        return False
    return set_offers(person, True, HOW_FORM + (form_name or 'a form'), by=None, at=at)


def _day(dt):
    from app.services import clock
    d = clock.local(dt)
    return '%d %s %d' % (d.day, d.strftime('%b'), d.year)


def how_words(person):
    """'ticked on the form “Diwali offer”' / 'on the contact page, by Ann' / 'when two contacts were merged'."""
    how = person.consent_marketing_how or ''
    if how.startswith(HOW_FORM):
        return 'ticked on the form “%s”' % how[len(HOW_FORM):]
    by = None
    if person.consent_marketing_by_id:
        from app.models import User
        u = db.session.get(User, person.consent_marketing_by_id)
        by = (u.first_name or u.username) if u is not None else None
    if how == HOW_PAGE:
        return 'on the contact page' + (', by %s' % by if by else '')
    if how == HOW_MERGE:
        return 'when two contacts were merged'
    return how or ''


def line(person):
    """The contact page's sentence: 'Given 21 Oct 2026 · ticked on the form “Diwali offer”' or 'Not given'."""
    at = person.consent_marketing_at
    if person.consent_marketing:
        if at is None:
            return 'Given'
        words = how_words(person)
        return 'Given %s' % _day(at) + (' · %s' % words if words else '')
    if at is not None:
        words = how_words(person)
        return 'Not given · taken back %s' % _day(at) + (' · %s' % words if words else '')
    return 'Not given'


def withdrawn(person):
    """They (or we, for them) took the permission back: an opt-out that a merge must keep."""
    return (not person.consent_marketing) and person.consent_marketing_at is not None


def cell(person):
    return 'Yes' if person is not None and person.consent_marketing else 'No'
