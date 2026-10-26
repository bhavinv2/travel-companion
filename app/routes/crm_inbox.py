"""Inbox › All conversations (Staff Console 2.0, 2026-10-26): one row per person who wrote to us, on any channel.
Rules on crm_bp (both consoles); the logic is in services/crm_inbox.py."""
from flask import render_template, request, url_for
from flask_login import current_user

from app.routes.crm import _common, crm_bp, crm_url
from app.routes.cs import cs_required
from app.services import crm_inbox


@crm_bp.route('/inbox')
@cs_required
def inbox():
    """Everybody who wrote to us -- WhatsApp, e-mail, Instagram, Facebook, the website's forms and chat -- newest
    first, 40 a page; whose (all / mine / not given to anyone / waiting on us), the channel and a search narrow it.
    Each row opens where it is answered (crm_inbox's module note)."""
    from app.routes.messaging import can_start_chats
    f = crm_inbox.filters(request.args)
    got = crm_inbox.page(f, current_user, request.args.get('page', type=int) or 1)
    chats = can_start_chats(current_user)
    for row in got['rows']:
        row['open'], row['open_label'] = _where(row, chats)
    return render_template('cs/crm/inbox.html', f=f, crm_inbox=crm_inbox, **got, **_common())


def _where(row, chats):
    """(address, button words) a row opens: their WhatsApp chat beside the lead when the last word was on WhatsApp,
    else the lead page, else the contact."""
    person, lead = row['person'], row['lead']
    if chats and row['channel'] == 'whatsapp' and person.wacrm_conversation_id:
        return url_for('messaging.inbox', p='/inbox?mine=1&c=%s' % person.wacrm_conversation_id), 'Open chat'
    if lead is not None:
        return crm_url('lead', lead_id=lead.id), 'Open lead'
    return crm_url('contact', person_id=person.id), 'Open contact'
