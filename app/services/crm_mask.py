"""Hidden contact details (Staff Console 2.0, 2026-10-26): least privilege for phone numbers and e-mails.

A role can say "hide other people's phone numbers and e-mails" (services/role_rights, `mask`). For somebody with such
a role, the Sales CRM's screens show the number and e-mail of a person none of whose leads they look after as
+91 98•••••210 and r•••@gmail.com, with a Show button; Call and E-mail buttons wait behind it too. Show is logged
(ActivityEvent 'contact_shown', Set-up › Security › Audit log) and lasts for the rest of their sign-in, so the page
can simply be drawn again. Taking the lead (looking after it) shows them for good.

    hidden(person)       are this person's details hidden from whoever is signed in?
    phone(e164) / email(address)   the masked words
    show(person)         Show: logged, and remembered for this sign-in
    SHOW_CAP             how many people one sign-in remembers (the oldest are forgotten)
"""
from flask import has_request_context, session
from flask_login import current_user

from app import db
from app.models import ActivityEvent, CrmLead, request_cache

SESSION_KEY = 'crm_shown'
SHOW_CAP = 300
DOT = '•'


def _mine(user):
    """The ids of the people whose leads `user` looks after (once a request)."""
    c = request_cache('crm_mask')
    if 'mine' not in c:
        rows = (db.session.query(CrmLead.person_id).filter(CrmLead.owner_id == user.id, CrmLead.deleted_at.is_(None))
                .distinct().all())
        c['mine'] = {pid for (pid,) in rows}
    return c['mine']


def hidden(person):
    """Are `person`'s phone and e-mail hidden from whoever is signed in? Never outside a request, never for a role
    that does not hide them, never for somebody whose lead they look after or whom they chose to Show."""
    if person is None or getattr(person, 'id', None) is None or not has_request_context():
        return False
    if not getattr(current_user, 'is_authenticated', False):
        return False
    from app.services import role_rights
    if not role_rights.masks(current_user):
        return False
    if person.id in set(session.get(SESSION_KEY) or ()):
        return False
    return person.id not in _mine(current_user)


def phone(e164):
    """'+91 98•••••210': the country code, the first two digits and the last three."""
    from app.services import phone as phone_svc
    text = phone_svc.pretty(e164) if e164 else ''
    if not text:
        return ''
    cc, _sp, rest = text.partition(' ') if text.startswith('+') else ('', '', text)
    digits = ''.join(ch for ch in rest if ch.isdigit())
    masked = digits[:2] + DOT * max(len(digits) - 5, 0) + digits[-3:] if len(digits) > 5 else DOT * len(digits)
    return ('%s %s' % (cc, masked)) if cc else masked


def email(address):
    """'r•••@gmail.com'."""
    if not address or '@' not in address:
        return address or ''
    name, _at, domain = address.partition('@')
    return '%s%s@%s' % (name[:1], DOT * 3, domain)


def show(person, where=''):
    """Show: the person's details for the rest of this sign-in, and the audit log says who looked at whose."""
    shown = [i for i in (session.get(SESSION_KEY) or ()) if i != person.id] + [person.id]
    session[SESSION_KEY] = shown[-SHOW_CAP:]
    ActivityEvent.log('contact_shown', actor=current_user, person=person.display_name, person_id=person.id,
                      where=where or None)
    db.session.commit()
