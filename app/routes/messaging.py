"""WhatsApp, inside the portal: the WhatsApp CRM's own screens in the portal's frame.

The WhatsApp CRM is a separate app at WACRM_URL -- studio.preventia360.com/crm, another site (see
services/wacrm_team.py and deploy/WHATSAPP_CRM.md). Each screen here is the portal's menu and header around that app's
page, so WhatsApp chats, templates, broadcasts, tags, reply rules, the chatbot and AI replies are
used where everything else is, with one sign-in: the frame opens through a signed hand-off that signs
the person into the CRM as the role their workspace pages give them.

Which of these screens somebody gets is their roles' business (services/access.py, the
"WhatsApp messaging" area); what they can do once inside follows from the CRM role the hand-off
gives them ('admin' for templates / tags / AI / the number, otherwise 'agent'), and the hand-off
also names the screens their pages give them (contract 14, PATH_PAGES below).

Screens that moved into the portal (contacts, pipelines, the dashboard...) are retired inside the
WhatsApp CRM: it tells the frame, and the frame moves the whole window to sso?go=<key> (contract
15), which opens the portal's own page.
"""
from urllib.parse import parse_qs, urlsplit

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app import db
from app.services import access, urls, wacrm_team

messaging_bp = Blueprint('messaging', __name__, url_prefix='/admin/messaging')

# endpoint -> the page key that opens it, the CRM path it opens, and the bar above the frame: its
# heading, helper line and "(?) How this works". The order matters: the first screen a person's
# pages give them is where the hand-off lands when nothing else is asked for, and the frame's
# heading follows the path inside the CRM by matching these paths (`tabs`: the /settings tabs that
# are this screen).
SCREENS = {
    'inbox': {'page': 'wa_inbox', 'path': '/inbox?mine=1', 'heading': 'WhatsApp chats',
              'helper': 'Every WhatsApp conversation. Click a chat; its lead shows on the right.',
              'help': ["These are the WhatsApp CRM's own chats, opened with your portal sign-in.",
                       'Within 24 hours of their last message you can write freely. After that only an approved '
                       'WhatsApp template can go.',
                       'A chat with a lead shows the lead on the right: the next follow-up, the stage and who looks '
                       'after it.']},
    # off the menu until U7 (access.py crm_people): the WhatsApp CRM retires /contacts inside the portal, so an old link lands on Leads
    'contacts': {'page': 'crm_people', 'path': '/contacts', 'heading': 'Contacts',
                 'helper': 'Everyone in WhatsApp, one row per person. Enquiries are worked on Leads.',
                 'help': ["The WhatsApp CRM's contact list.", 'Enquiries, stages and follow-ups are on Leads.']},
    'broadcasts': {'page': 'wa_broadcasts', 'path': '/broadcasts', 'heading': 'Broadcasts',
                   'helper': 'Send one approved message to many people at once, for example everyone in a stage.',
                   'help': ['Only an approved WhatsApp template can go to many people.',
                            'Pick the people by their tags, for example everyone in one stage.',
                            'People who opted out are skipped.']},
    'automations': {'page': 'wa_automations', 'path': '/automations', 'heading': 'Reply rules',
                    'helper': 'When something happens in a WhatsApp chat, like a keyword, a first message or out of '
                              'hours, reply by itself. Follow-ups for leads are set in Pipelines.',
                    'help': ['Each rule starts on something in a chat and replies by itself.',
                             'Follow-ups for leads are planned in Pipelines, not here.',
                             'A rule that sends when a tag is added can repeat our follow-ups. Check before you '
                             'switch one on.']},
    'flows': {'page': 'wa_flows', 'path': '/flows', 'heading': 'Chatbot',
              'helper': "A menu of buttons that answers customers step by step. If the chatbot answers a message, "
                        "reply rules don't.",
              'help': ['A chatbot asks with buttons and answers step by step.',
                       "If the chatbot answers a message, reply rules don't."]},
    'ai': {'page': 'wa_ai', 'path': '/agents', 'heading': 'AI replies',
           'helper': 'AI drafts or sends answers from the documents you add here. It stops as soon as a person '
                     'takes the chat.',
           'help': ['AI replies use only the documents you add here.', 'It stops as soon as a person takes the chat.']},
    'templates': {'page': 'wa_templates', 'path': '/settings?tab=templates', 'heading': 'WhatsApp templates',
                  'helper': 'Messages WhatsApp has approved, for first messages and for writing after 24 hours. '
                            'Follow-ups use these.',
                  'help': ['WhatsApp only lets us write first, or after 24 hours of silence, with a template it has '
                           'approved.',
                           'Follow-ups that go by themselves use these.', 'Approval usually takes minutes to a day.']},
    'tags': {'page': 'wa_tags', 'path': '/settings?tab=fields', 'tabs': ('fields', 'tags'), 'heading': 'Tags',
             'helper': 'Labels on contacts, used to choose who gets a broadcast or a reply rule.',
             'help': ['Tags pick who gets a broadcast or a reply rule.',
                      "The Sales CRM adds tags for each lead's stage and source by itself.",
                      "Don't rename or delete the stage, product or source tags here: the Sales CRM writes them and puts them back."]},
    'settings': {'page': 'wa_settings', 'path': '/settings?tab=whatsapp', 'tabs': ('whatsapp', 'api'),
                 'heading': 'WhatsApp number',
                 'helper': 'The number customers write to, and its Meta account details. Messages not reaching leads? '
                           'Check WhatsApp connection.',
                 'help': ['This is the number customers write to, connected to Meta.',
                          'If messages are not reaching leads, check WhatsApp connection in Set-up.']},
}
INBOX_HELPER_ALONE = 'Every WhatsApp conversation.'      # nobody draws the lead panel for them
EXTRA_HEADINGS = {'/settings?tab=quick-replies': 'Quick replies'}   # framed only by a link inside the CRM

# Contract 14, in its order -- the same table is in the WhatsApp CRM (src/lib/portal/page-grants.ts):
# (path, rule, page key). rule None: that path exactly; '*': it and everything under it; a tuple:
# /settings with one of those tabs.
PATH_PAGES = (
    ('/inbox', None, 'wa_inbox'), ('/broadcasts', '*', 'wa_broadcasts'), ('/automations', '*', 'wa_automations'),
    ('/flows', '*', 'wa_flows'), ('/agents', '*', 'wa_ai'), ('/settings', ('templates',), 'wa_templates'),
    ('/settings', ('fields', 'tags'), 'wa_tags'), ('/settings', ('quick-replies',), 'wa_quick'),
    ('/settings', ('whatsapp', 'api'), 'wa_settings'))


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


def page_for_path(path):
    """The page key a path inside the WhatsApp CRM needs (contract 14), or None for one no grant
    covers (the CRM decides those itself)."""
    parts = urlsplit(path or '')
    base = parts.path.rstrip('/') or '/'
    tab = (parse_qs(parts.query).get('tab') or [None])[0]
    for prefix, rule, key in PATH_PAGES:
        if (rule is None and base == prefix) or (rule == '*' and (base == prefix or base.startswith(prefix + '/'))) \
                or (isinstance(rule, tuple) and base == prefix and tab in rule):
            return key
    return None


def _inside(path, granted=None):
    """A path inside the CRM, from a query string: None for anything that is not a plain path, or for
    a screen the person's pages do not give them (`granted`; the caller then opens its own)."""
    if not isinstance(path, str) or not path.startswith('/') or path.startswith('//') or '\\' in path:
        return None
    path = path[:500]
    key = page_for_path(path)
    if granted is not None and key and key not in granted:
        return None
    return path


def _with_panel(path):
    """The inbox beside the portal's lead panel: the CRM leaves its own contact sidebar out (contract 24)."""
    parts = urlsplit(path)
    if parts.path != '/inbox' or 'panel=' in parts.query:
        return path
    return path + ('&' if parts.query else '?') + 'panel=portal'


def _first_screen_path(granted):
    """Where the hand-off lands when nothing else is asked for: the first screen their pages give them."""
    return next((s['path'] for s in SCREENS.values() if s['page'] in granted and s['page'].startswith('wa_')),
                '/inbox')


def _screens_js(panel):
    """The screens for the frame's script, which keeps the bar's heading in step with the path inside
    the CRM: {base, tabs, heading, helper, help} each."""
    out = []
    for name, s in SCREENS.items():
        parts = urlsplit(s['path'])
        tab = parse_qs(parts.query).get('tab')
        alone = name == 'inbox' and not panel
        out.append({'base': parts.path, 'tabs': list(s.get('tabs') or tab or []) or None, 'heading': s['heading'],
                    'helper': INBOX_HELPER_ALONE if alone else s['helper'],
                    'help': s['help'][:2] if alone else s['help']})
    for path, heading in EXTRA_HEADINGS.items():
        parts = urlsplit(path)
        out.append({'base': parts.path, 'tabs': parse_qs(parts.query).get('tab'), 'heading': heading,
                    'helper': '', 'help': None})
    return out


def _screen_view(name):
    screen = SCREENS[name]

    @login_required
    def view():
        if not access.allowed(current_user, request.endpoint):
            flash('Your role does not include that page.', 'warning')
            return redirect(access.home_url(current_user))
        from app.services import crm
        role = crm_role(current_user)
        # the inbox gets the open conversation's sales lead beside it, for whoever works leads
        panel = bool(name == 'inbox' and wacrm_team.enabled() and role
                     and (access.can(current_user, 'crm_board') or access.can(current_user, 'crm_today')))
        src = None
        if wacrm_team.enabled() and role:
            granted = wacrm_team.wa_pages(wacrm_team.user_pages(current_user))
            # ?p= is where they were inside the CRM (the frame reports it), so a reload stays put --
            # unless their pages do not give them that screen: then this screen's own
            path = _inside(request.args.get('p'), set(granted)) or screen['path']
            if panel:
                path = _with_panel(path)
            src = wacrm_team.sso_url(current_user, role, path, pages=granted)
        alone = name == 'inbox' and not panel
        return render_template('messaging/frame.html', heading=screen['heading'],
                               helper=INBOX_HELPER_ALONE if alone else screen['helper'],
                               help=screen['help'][:2] if alone else screen['help'],
                               page_key=screen['page'], src=src, panel=panel, wa_ready=crm.wa_can_send(),
                               configured=wacrm_team.enabled(), role=role, screen=name,
                               crm_origin=wacrm_team.browser_origin(), go_url=url_for('messaging.sso'),
                               screens=_screens_js(panel))
    view.__name__ = name
    return view


for _name in SCREENS:
    messaging_bp.add_url_rule('/' + _name.replace('_', '-'), endpoint=_name, view_func=_screen_view(_name))


@messaging_bp.route('/quick-replies')
@login_required
def quick_replies():
    """Moved: quick replies are the Sales CRM's own page (button replies stay in WhatsApp)."""
    return redirect(access.page_url(access.PAGES['crm_quick']) or access.home_url(current_user))


@messaging_bp.route('/overview')
@login_required
def overview():
    """Moved: the WhatsApp dashboard's numbers are in Results."""
    return redirect(access.page_url(access.PAGES['crm_insights']) or access.home_url(current_user))


# contract 15: a screen retired inside the WhatsApp CRM -> the portal page that took its place
GO_PAGES = {'contacts': 'crm_board',          # U7: 'crm_people', once Contacts is the portal's own page
            'leads': 'crm_board', 'results': 'crm_insights', 'notifications': 'notifications',
            'members': 'ws_members', 'quick_replies': 'crm_quick', 'pipelines': 'crm_pipelines'}


def _go_url(key, template=''):
    """Where a WhatsApp screen that moved to the portal sends somebody (contract 15): that page when
    their roles give it, their start page otherwise. pipelines + template: the pipeline whose
    follow-up uses that WhatsApp template."""
    page = GO_PAGES.get(key)
    if page is None or not access.can(current_user, page):
        return access.home_url(current_user)
    if page == 'crm_pipelines' and template:
        from app.models import CrmPlaybookStep
        step = CrmPlaybookStep.query.filter_by(wa_template=template).order_by(CrmPlaybookStep.id).first()
        if step is not None and step.stage is not None and step.stage.pipeline is not None:
            return url_for('admin_crm.pipelines', p=step.stage.pipeline.key) + '#st-%d' % step.stage_id
    return access.page_url(access.PAGES[page]) or access.home_url(current_user)


@messaging_bp.route('/sso')
@login_required
def sso():
    """Where the CRM sends somebody whose session there has run out (its PORTAL_URL): straight
    back with a fresh hand-off, as the role they have today, to a screen their pages give them.
    With ?go=<key>: a screen that moved into the portal -- its page here (contract 15)."""
    if request.args.get('go'):
        if not access.is_staff(current_user):
            return redirect(url_for('main.index'))
        return redirect(_go_url(request.args['go'].strip()[:32], (request.args.get('template') or '').strip()[:80]))
    role = crm_role(current_user)
    if not (wacrm_team.enabled() and role):
        flash('Your role does not include WhatsApp.', 'warning')
        return redirect(access.home_url(current_user) if access.is_staff(current_user) else url_for('main.index'))
    granted = wacrm_team.wa_pages(wacrm_team.user_pages(current_user))
    return redirect(wacrm_team.sso_url(current_user, role,
                                       _inside(request.args.get('next'), set(granted)) or _first_screen_path(granted),
                                       pages=granted))


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
    """The lead's own WhatsApp thread, for the lead page's full-chat drawer: photos, documents,
    voice notes. Their chat is ensured first and must be theirs (crm.wa_ensure_chat); with sending
    off it is only looked up, never made. A WhatsApp user without a number opens the chat we hold."""
    from app.services import crm
    lead = _lead(lead_id)
    role = crm_role(current_user)
    person = lead.person
    if not (wacrm_team.enabled() and role):
        return render_template('messaging/lead_chat.html', lead=lead, state='off', role=role)
    if person.phone:
        writes = crm.wa_writes_on()
        try:
            r = crm.wa_ensure_chat(person, create=writes,
                                   assign_email=(lead.owner.email if writes and lead.owner else None))
        except crm.WaChatRefused as exc:
            db.session.rollback()
            return render_template('messaging/lead_chat.html', lead=lead, state='error', error=str(exc), role=role)
        db.session.commit()
        conv = r.get('conversation_id')
    else:
        conv = person.wacrm_conversation_id          # a WhatsApp user without a number: that thread
    if conv:
        return redirect(wacrm_team.sso_url(current_user, role, '/inbox?c=%s&view=thread' % conv))
    return render_template('messaging/lead_chat.html', lead=lead, state='none', role=role,
                           no_phone=not person.phone, off=not crm.wa_writes_on())


# ------------------------------------------------- the sales lead beside the WhatsApp inbox

def _person_for(conversation_id, phone, name=''):
    """(person or None, phone digits, name). The inbox usually says the phone; a page that opens
    straight on a conversation (?p=/inbox?c=...) only knows its id, so ask the CRM."""
    from app.models import CrmPerson
    from app.services import crm, wacrm_team
    person = None
    if conversation_id:
        person = CrmPerson.query.filter_by(wacrm_conversation_id=str(conversation_id)).first()
    digits = ''.join(ch for ch in str(phone or '') if ch.isdigit())
    if person is None and len(digits) < 8 and conversation_id and wacrm_team.enabled():
        contact = (wacrm_team.conversation_info(conversation_id) or {}).get('contact') or {}
        digits = ''.join(ch for ch in str(contact.get('phone') or '') if ch.isdigit())
        name = name or (contact.get('name') or '')
    if person is None and len(digits) >= 8:
        person = crm.find_person(crm.normalise_phone('+' + digits), None)
        if person is not None and conversation_id:
            person.wacrm_conversation_id = str(conversation_id)
            db.session.commit()
    return person, digits, name


@messaging_bp.route('/lead-panel')
@login_required
def lead_panel():
    """The sales lead of the conversation open in the WhatsApp inbox, as the lead card -- loaded
    beside the inbox each time the agent opens a conversation (the inbox says which: the
    wacrm:conversation message). Work the lead without leaving the chat."""
    from app.routes.crm import _common, lead_card_context
    if not access.allowed(current_user, request.endpoint):
        abort(403)
    if not (access.can(current_user, 'crm_board') or access.can(current_user, 'crm_today')):
        return render_template('messaging/lead_panel.html', state='no_crm')
    conversation_id = (request.args.get('conversation') or '').strip()[:64]
    person, digits, name = _person_for(conversation_id, request.args.get('phone'),
                                       (request.args.get('name') or '').strip())
    lead = None
    if person is not None:
        from app.services import crm
        lead = crm.wa_lead_for(person) or (person.leads[0] if person.leads else None)
    if lead is None:
        return render_template('messaging/lead_panel.html', state='none', phone=digits,
                               name=name[:120], conversation=conversation_id)
    from app.services import crm
    belongs = sum(1 for l in person.leads if l.status == 'open') > 1
    return render_template('messaging/lead_panel.html', state='lead', belongs=belongs,
                           suggested=crm.suggested_reply(lead, current_user) if crm.WA_COMPOSE else None, conversation=conversation_id,
                           **lead_card_context(lead, compact=True), **_common())


@messaging_bp.route('/lead-panel/make', methods=['POST'])
@login_required
def lead_panel_make():
    """Somebody wrote on WhatsApp who is not a lead yet: make them one, from the inbox."""
    from flask import current_app
    from app.services import crm
    if not access.allowed(current_user, request.endpoint) or not access.can(current_user, 'crm_add'):
        abort(403)
    digits = ''.join(ch for ch in (request.form.get('wa_phone') or '') if ch.isdigit())
    if len(digits) < 8:
        abort(400)
    key = current_app.config.get('WACRM_SOURCE_KEY') or 'wa-india'
    lead = crm.capture(key, name=(request.form.get('name') or '').strip()[:120] or None, phone='+' + digits,
                       channel='whatsapp', utm={}, created_by_id=current_user.id, note=crm.MADE_FROM_CHAT)
    if lead is not None and request.form.get('conversation'):
        lead.person.wacrm_conversation_id = request.form.get('conversation')[:64]
        took_it = lead.owner_id is None
        if took_it:
            lead.owner_id = current_user.id
        # the chat goes to whoever looks after the lead: to me when I took it here; to an owner the
        # source routed it to only if nobody in WhatsApp has it (the agent chatting keeps it)
        crm.mark_wa_due(lead.person, assign=took_it, assign_if_free=not took_it)
        db.session.commit()
    return redirect(url_for('messaging.lead_panel', conversation=request.form.get('conversation'), phone=digits))
