"""WhatsApp, inside the portal: the WhatsApp CRM's own screens in the portal's frame.

The WhatsApp CRM is a separate app at WACRM_URL -- studio.preventia360.com/crm, another site (see
services/wacrm_team.py and deploy/WHATSAPP_CRM.md). Each screen here is the portal's menu and header around that app's
page, so the inbox, templates, broadcasts, auto-replies, chatbot flows and AI assistant are used
where everything else is, with one sign-in: the frame opens through a signed hand-off that signs
the person into the CRM as the role their workspace pages give them.

Which of these screens somebody gets is their roles' business (services/access.py, the
"WhatsApp" module); what they can do once inside follows from the CRM role the hand-off gives
them ('admin' for templates / AI / settings, otherwise 'agent').
"""
from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app import db
from app.services import access, urls, wacrm_team

messaging_bp = Blueprint('messaging', __name__, url_prefix='/admin/messaging')

# endpoint -> (page key, the CRM path it opens, heading)
SCREENS = {
    'inbox': ('wa_inbox', '/inbox', 'Inbox'),
    'contacts': ('wa_contacts', '/contacts', 'Contacts'),
    'quick_replies': ('wa_quick', '/settings?tab=quick-replies', 'Quick replies'),
    'broadcasts': ('wa_broadcasts', '/broadcasts', 'Broadcasts'),
    'automations': ('wa_automations', '/automations', 'Auto-replies'),
    'flows': ('wa_flows', '/flows', 'Chatbot flows'),
    'templates': ('wa_templates', '/settings?tab=templates', 'Templates'),
    'ai': ('wa_ai', '/agents', 'AI assistant'),
    'overview': ('wa_overview', '/dashboard', 'WhatsApp dashboard'),
    'settings': ('wa_settings', '/settings?tab=whatsapp', 'WhatsApp settings'),
}


def crm_role(user):
    """The CRM role a hand-off gives this person, or None when no WhatsApp page is theirs."""
    from app.models import WorkspaceMember
    if user.is_admin:
        return 'admin'
    ws = wacrm_team.linked_workspace() or access.current_workspace(user)
    m = (WorkspaceMember.query.filter_by(workspace_id=ws.id, user_id=user.id).first() if ws else None)
    if m is None:
        return None
    return wacrm_team.role_for(m)


def _inside(path):
    """A path inside the CRM, from a query string: anything else becomes its inbox."""
    if not isinstance(path, str) or not path.startswith('/') or path.startswith('//') or '\\' in path:
        return None
    return path[:500]


def _screen_view(name):
    page_key, crm_path, heading = SCREENS[name]

    @login_required
    def view():
        if not access.allowed(current_user, request.endpoint):
            flash('Your role does not include that page.', 'warning')
            return redirect(access.home_url(current_user))
        role = crm_role(current_user)
        src = None
        if wacrm_team.enabled() and role:
            # ?p= is where they were inside the CRM (the frame reports it), so a reload stays put
            src = wacrm_team.sso_url(current_user, role, _inside(request.args.get('p')) or crm_path)
        return render_template('messaging/frame.html', heading=heading, page_key=page_key, src=src,
                               configured=wacrm_team.enabled(), role=role, screen=name,
                               direct=wacrm_team.browser_base() + crm_path,
                               crm_origin=wacrm_team.browser_origin())
    view.__name__ = name
    return view


for _name in SCREENS:
    messaging_bp.add_url_rule('/' + _name.replace('_', '-'), endpoint=_name, view_func=_screen_view(_name))


@messaging_bp.route('/sso')
@login_required
def sso():
    """Where the CRM sends somebody whose session there has run out (its PORTAL_URL): straight
    back with a fresh hand-off, as the role they have today."""
    role = crm_role(current_user)
    if not (wacrm_team.enabled() and role):
        flash('Your role does not include WhatsApp.', 'warning')
        return redirect(access.home_url(current_user) if access.is_staff(current_user) else url_for('main.index'))
    return redirect(wacrm_team.sso_url(current_user, role, _inside(request.args.get('next')) or '/inbox'))


# ------------------------------------------------------------------ the lead page's chat

def _lead(lead_id):
    from app.models import CrmLead
    lead = db.session.get(CrmLead, lead_id)
    if lead is None:
        abort(404)
    if not (access.can(current_user, 'crm_board') or access.can(current_user, 'crm_today')):
        abort(403)
    return lead


@messaging_bp.route('/lead/<int:lead_id>/chat')
@login_required
def lead_chat(lead_id):
    """The lead's WhatsApp conversation, as the CRM shows it, for the frame on the lead page.
    No conversation yet: a way to start one with an approved template."""
    from app.services import wacrm
    lead = _lead(lead_id)
    role = crm_role(current_user)
    person = lead.person
    if not (wacrm_team.enabled() and wacrm.enabled() and role):
        return render_template('messaging/lead_chat.html', lead=lead, state='off', role=role)
    try:
        if not person.wacrm_contact_id and person.phone:
            person.wacrm_contact_id = wacrm.find_contact(person.phone)
        if not person.wacrm_conversation_id and person.wacrm_contact_id:
            person.wacrm_conversation_id = wacrm.conversation_for(person.wacrm_contact_id)
        db.session.commit()
    except wacrm.WacrmError as exc:
        db.session.rollback()
        return render_template('messaging/lead_chat.html', lead=lead, state='error', error=str(exc), role=role)
    if person.wacrm_conversation_id:
        return redirect(wacrm_team.sso_url(current_user, role,
                                           '/inbox?c=%s&view=thread' % person.wacrm_conversation_id))
    try:
        rows = wacrm_team.templates()
    except wacrm_team.TeamError as exc:
        rows, error = [], str(exc)
    else:
        error = None
    return render_template('messaging/lead_chat.html', lead=lead, state='new', templates=rows, error=error,
                           role=role, can_send=bool(person.phone))


@messaging_bp.route('/lead/<int:lead_id>/template', methods=['POST'])
@login_required
def lead_template(lead_id):
    """Start the conversation: an approved template is the only thing WhatsApp lets a business
    send first. Recorded on the lead like any other message."""
    from app.services import crm, wacrm
    lead = _lead(lead_id)
    if not crm_role(current_user):
        abort(403)
    name = (request.form.get('name') or '').strip()
    language = (request.form.get('language') or '').strip() or None
    params = [v.strip() for v in request.form.getlist('params')]
    if not name or not lead.person.phone:
        flash('Pick a template; the lead needs a phone number.', 'warning')
        return redirect(url_for('messaging.lead_chat', lead_id=lead.id))
    try:
        wacrm.send_template(lead.person.phone, name, language=language, params=params)
    except wacrm.WacrmError as exc:
        flash('WhatsApp did not send it: %s' % exc, 'danger')
        return redirect(url_for('messaging.lead_chat', lead_id=lead.id))
    crm.log_touch(lead, 'whatsapp', body='Template: %s' % name, user=current_user)
    db.session.commit()
    flash('Template sent. The conversation opens as soon as WhatsApp has it.', 'success')
    return redirect(url_for('messaging.lead_chat', lead_id=lead.id))


@messaging_bp.route('/templates.json')
@login_required
def templates_json():
    """The approved templates, for the lead page's template picker."""
    if not crm_role(current_user):
        return jsonify({'error': 'Your role does not include WhatsApp.'}), 403
    try:
        return jsonify({'templates': wacrm_team.templates()})
    except wacrm_team.TeamError as exc:
        return jsonify({'error': str(exc)}), 502
