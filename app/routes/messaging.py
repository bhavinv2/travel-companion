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
from datetime import datetime
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
                       'after it. Click a quick reply there to put it in the chat.',
                       'New chat lists new leads with no chat yet, and finds any lead: Message opens their chat on '
                       'the left, where the first message is an approved template.']},
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
                      "Tags set by the Sales CRM (stage, product, source, opted-out) are locked here; change the stage or source instead."]},
    'settings': {'page': 'wa_settings', 'path': '/settings?tab=whatsapp', 'tabs': ('whatsapp', 'api'),
                 'heading': 'WhatsApp number',
                 'helper': 'The number customers write to, and its Meta account details. Messages not reaching leads? '
                           'Check WhatsApp in Set-up.',
                 'help': ['This is the number customers write to, connected to Meta.',
                          'If messages are not reaching leads, check WhatsApp in Set-up.']},
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


def frame_link(path):
    """The portal address that opens `path` inside the WhatsApp frame, on the first framed screen this person may
    open (SCREENS order), or None when WhatsApp is not connected here or no framed screen is theirs."""
    if not wacrm_team.enabled():
        return None
    name = next((n for n, s in SCREENS.items() if access.can(current_user, s['page'])), None)
    return url_for('messaging.' + name, p=path) if name else None


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
        rules, rules_at = [], None
        if name == 'automations':                  # the strip is what was last seen: no call to the WhatsApp CRM
            rules, seen = crm.known_rule_conflicts()
            from app.services import clock
            rules_at = clock.fmt(seen, '%d %b, %H:%M') if seen else None
        # the inbox holds ONE number of ours (the WhatsApp CRM's): the banner names it, and where the others' chats are;
        # beside the lead panel the rail lists every number and draws a Meta-direct number's chats here (_rail)
        inbox_num = inbox_others = rail = None
        if name == 'inbox' and src:
            from app.services import channels
            inbox_num = channels.badge(None)
            inbox_others = [channels.badge(l) for l in channels.lines()]
            if panel:
                rail = _rail(request.args.get('num'), request.args.get('chat', type=int))
        return render_template('messaging/frame.html', rules=rules, rules_line=crm.rule_strip(rules),
                               inbox_num=inbox_num, inbox_others=inbox_others, rail=rail,
                               rules_at=rules_at, heading=screen['heading'],
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


def _rail(num, chat):
    """The rail beside WhatsApp chats (Messaging Hub, 2026-10-29): each WhatsApp number of ours, the WhatsApp CRM's
    first, with how many people on it wait on us, and the website's WhatsApp numbers nothing of ours hears. `num` is the
    number to open on: the WhatsApp CRM's (its inbox in the frame) unless it names a Meta-direct number, whose chats
    are drawn here (number_chats) -- with `chat`, that person's chat open. 'web' is Live chat (the website's own
    bubble): `live` its people waiting on us, None for somebody without the page."""
    from app.services import channels, crm_inbox
    waiting = crm_inbox.waiting_by_number(current_user)
    live = crm_inbox.live_waiting(current_user) if access.can(current_user, 'web_chat') else None
    nums = []
    for line in [None] + channels.lines():
        b = channels.badge(line)
        b.update(waiting=waiting.get(b['key'], 0),
                 state=None if line is None or line.status == 'live'
                 else channels.STATUS_WORDS.get(line.status, line.status))
        nums.append(b)
    keys = {b['key'] for b in nums} | ({'web'} if live is not None else set())
    on = num if num != 'crm' and num in keys else 'crm'
    return {'nums': nums, 'unheard': channels.unheard(), 'on': on, 'chat': chat if on != 'crm' else None, 'live': live}


@messaging_bp.route('/contacts')
@login_required
def contacts():
    """Moved: Contacts is the Sales CRM's own page."""
    return redirect(access.page_url(access.PAGES['crm_people']) or access.home_url(current_user))


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
GO_PAGES = {'contacts': 'crm_people',
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
        from app.services import wa_templates
        step = CrmPlaybookStep.query.filter_by(wa_template=template).order_by(CrmPlaybookStep.id).first()
        if step is None:
            step = next((s for s in CrmPlaybookStep.query.filter_by(channel='whatsapp', wa_template=None)
                         .order_by(CrmPlaybookStep.id) if wa_templates.slug_name(s.code) == template), None)
        if step is not None and step.stage is not None and step.stage.pipeline_id is not None:
            return url_for('admin_crm.pipeline_edit', pid=step.stage.pipeline_id, step=step.id)
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
    from app.services import crm_access, crm_scope
    lead = db.session.get(CrmLead, lead_id)
    if lead is None or lead.deleted_at is not None or not crm_access.can_see_lead(current_user, lead) \
            or not crm_scope.visible(lead):
        abort(404)
    if not (access.can(current_user, 'crm_board') or access.can(current_user, 'crm_today')):
        abort(403)
    return lead


def _lead_conversation(lead):
    """The lead's chat in the WhatsApp CRM, ensured and certainly theirs (crm.wa_ensure_chat): made when missing
    while the portal may write there, and then given to the lead's owner if nobody has it; with writes off only
    looked up. A WhatsApp user without a number has the chat we hold. The conversation id or None; raises
    crm.WaChatRefused (rolled back). Commits."""
    return _person_conversation(lead.person, lead.owner)


def _person_conversation(person, owner=None):
    """_lead_conversation for a person: a chat made here is given to `owner` if nobody has it."""
    from app.services import crm
    if not person.phone:
        return person.wacrm_conversation_id
    writes = crm.wa_writes_on()
    try:
        r = crm.wa_ensure_chat(person, create=writes,
                               assign_email=(owner.email if writes and owner else None))
    except crm.WaChatRefused:
        db.session.rollback()
        raise
    db.session.commit()
    return r.get('conversation_id')


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
    try:
        conv = _lead_conversation(lead)
    except crm.WaChatRefused as exc:
        return render_template('messaging/lead_chat.html', lead=lead, state='error', error=str(exc), role=role)
    if conv:
        return redirect(wacrm_team.sso_url(current_user, role, '/inbox?c=%s&view=thread' % conv))
    return render_template('messaging/lead_chat.html', lead=lead, state='none', role=role,
                           no_phone=not person.phone, off=not crm.wa_writes_on())


# ------------------------------------------------- starting a chat from WhatsApp chats

START_WHO = (('mine', 'Mine'), ('none', 'Not given to anyone'), ('all', 'Everyone'))


def _start_who(raw):
    if raw in dict(START_WHO):
        return raw
    return 'all' if access.can(current_user, 'crm_insights') else 'mine'


@messaging_bp.route('/start-chat')
@login_required
def start_chat_panel():
    """The panel beside WhatsApp chats when no chat is open, or after "New chat": leads to message. With no search,
    open leads with a phone and no WhatsApp chat yet, newest first (whose: mine / not given to anyone / everyone);
    with a search, any lead it finds, open first, each with "Message" or "Open chat". A fragment.
    `num`: a Meta-direct number picked in the rail -- "no chat yet" is then no message on that number, the list keeps
    to phones that number serves (its prefixes), and it says when the number cannot send a first message."""
    from sqlalchemy import case, exists, or_
    from app.models import CrmLead, CrmPerson, CrmTouchpoint
    from app.services import channels, crm, crm_people, crm_products
    if not access.allowed(current_user, request.endpoint):
        abort(403)
    if not (access.can(current_user, 'crm_board') or access.can(current_user, 'crm_today')):
        return render_template('messaging/start_chat.html', state='no_crm')
    line = channels.get(request.args.get('num', type=int))
    q = ' '.join((request.args.get('q') or '').split())[:80]
    who = _start_who(request.args.get('who'))
    query = CrmLead.query.join(CrmPerson, CrmPerson.id == CrmLead.person_id).options(*crm.lead_load())
    if q:
        query = (query.filter(crm_people.person_match(q))
                 .order_by(case((CrmLead.status == 'open', 0), else_=1), CrmLead.last_activity_at.desc()))
    else:
        query = query.filter(CrmLead.status == 'open', CrmPerson.phone.isnot(None))
        if line is None:
            query = query.filter(CrmPerson.wacrm_conversation_id.is_(None))
        else:
            query = query.filter(~exists().where(CrmTouchpoint.person_id == CrmLead.person_id,
                                                 CrmTouchpoint.channel == 'whatsapp', CrmTouchpoint.line_id == line.id))
            if line.prefixes:
                query = query.filter(or_(*[CrmPerson.phone.startswith(p) for p in line.prefixes]))
        if who == 'mine':
            query = query.filter(CrmLead.owner_id == current_user.id)
        elif who == 'none':
            query = query.filter(CrmLead.owner_id.is_(None))
        query = query.order_by(CrmLead.created_at.desc(), CrmLead.id.desc())
    total = query.count()
    leads = query.limit(30).all()
    here = chatting = None
    if line is not None:
        here = channels.badge(line)
        here.update(live=line.status == 'live', templates=len(channels.templates(line).approved_list()),
                    prefixes=', '.join(line.prefixes or ()), line_id=line.id)
        ids = [l.person_id for l in leads]
        chatting = {pid for (pid,) in db.session.query(CrmTouchpoint.person_id).distinct().filter(
            CrmTouchpoint.person_id.in_(ids), CrmTouchpoint.channel == 'whatsapp',
            CrmTouchpoint.line_id == line.id)} if ids else set()
    return render_template('messaging/start_chat.html', state='list', leads=leads, total=total, q=q, who=who,
                           WHO=START_WHO, writes=crm.wa_writes_on(), utcnow=datetime.utcnow(),
                           PRODUCTS=crm_products.labels(), here=here, chatting=chatting,
                           back=(request.args.get('back') or '').strip()[:120])


@messaging_bp.route('/start-chat', methods=['POST'])
@login_required
def start_chat():
    """"Message" beside WhatsApp chats: the lead's chat, made in the WhatsApp CRM when it has none (never sends
    anything), and the address that opens it in the frame. {ok, conversation, src, name} or {ok: false, error}.
    `person` instead of `lead`: "Find a contact" in the rail opening somebody's chat on the WhatsApp CRM's number.
    `num`: a Meta-direct number picked in the rail -- their chat is put on that number (start_on_number)."""
    from app.services import crm
    if not access.allowed(current_user, request.endpoint):
        abort(403)
    if request.form.get('num'):
        return start_on_number()
    if request.form.get('person'):
        _for_leads()
        person = _visible_person(request.form.get('person', type=int) or 0)
        lead = crm.wa_lead_for(person)
    else:
        lead = _lead(request.form.get('lead', type=int) or 0)
        person = lead.person
    role = crm_role(current_user)
    if not (wacrm_team.enabled() and role):
        return jsonify(ok=False, error='WhatsApp is not connected for you here.')
    if not person.phone and not person.wacrm_conversation_id:
        return jsonify(ok=False, error='%s has no phone number. Add one on the lead page first.'
                       % person.display_name)
    try:
        conv = _person_conversation(person, lead.owner if lead is not None else None)
    except crm.WaChatRefused as exc:
        return jsonify(ok=False, error=str(exc))
    if not conv:
        return jsonify(ok=False, error=START_OFF)
    granted = wacrm_team.wa_pages(wacrm_team.user_pages(current_user))
    path = _with_panel('/inbox?mine=1&c=%s' % conv)
    return jsonify(ok=True, conversation=str(conv), name=person.display_name,
                   src=wacrm_team.sso_url(current_user, role, path, pages=granted))


def start_on_number():
    """"Message" beside a Meta-direct number's chats: their chat is put on that number -- what goes to them next goes
    from it, as when they last wrote to it (channels.line_for) -- and nothing is sent; the first message is an
    approved template in the chat's box. {ok, person, num, name} or {ok: false, error}."""
    from app.services import channels
    _for_leads()
    line = channels.get(request.form.get('num', type=int))
    if line is None:
        abort(404)
    lead = _lead(request.form.get('lead', type=int) or 0)
    person = lead.person
    if line.status != 'live':
        return jsonify(ok=False, error='Our %s number is not connected (%s), so nothing can go from it.'
                       % (line.label, channels.STATUS_WORDS.get(line.status, line.status).lower()))
    if not person.phone:
        return jsonify(ok=False, error='%s has no phone number. Add one on the lead page first.' % person.display_name)
    person.wa_line_id = line.id
    db.session.commit()
    return jsonify(ok=True, person=person.id, num=str(line.id), name=person.display_name)


START_OFF = ("They have no WhatsApp chat yet, and WhatsApp is on “Not yet” in Set-up → WhatsApp, so a new chat "
             "can't be started from here.")


# ------------------------------------------------- starting a chat from a contact

def can_start_chats(user):
    """Whether contacts offer this person "WhatsApp chat": WhatsApp is connected for the CRM being worked on, their
    role includes it, and WhatsApp chats is one of their pages (the chat opens there)."""
    from app.services import crm
    return bool(crm.wa_team_on() and crm_role(user) and access.can(user, 'wa_inbox'))


@messaging_bp.route('/contact/<int:person_id>/chat', methods=['POST'])
@login_required
def contact_chat(person_id):
    """"Start WhatsApp chat" on a contact page and in Contacts: their chat, made in the WhatsApp CRM when they have
    none (never sends anything) and given to the owner of their open lead if nobody has it, opened in WhatsApp chats
    with their lead beside it. What stops it is said on the page it came from (`next`)."""
    from app.services import crm
    if not access.allowed(current_user, request.endpoint):
        abort(403)
    person = _visible_person(person_id)
    back = request.form.get('next') or ''
    if not back.startswith('/') or back.startswith('//') or '\\' in back:
        back = access.page_url(access.PAGES['crm_people']) or access.home_url(current_user)
    if not can_start_chats(current_user):
        flash('WhatsApp is not connected for you here.', 'warning')
        return redirect(back)
    if not person.phone and not person.wacrm_conversation_id:
        flash('%s has no phone number. Add one with Edit details first.' % person.display_name, 'warning')
        return redirect(back)
    lead = crm.wa_lead_for(person)
    try:
        conv = _person_conversation(person, lead.owner if lead is not None else None)
    except crm.WaChatRefused as exc:
        flash(str(exc), 'warning')
        return redirect(back)
    if not conv:
        flash(START_OFF, 'warning')
        return redirect(back)
    return redirect(url_for('messaging.inbox', p='/inbox?mine=1&c=%s' % conv))


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
    from app.services import channels
    conversation_id = (request.args.get('conversation') or '').strip()[:64]
    line = None
    live = request.args.get('num') == 'web'          # beside a website live chat (Live chat on the rail)
    if request.args.get('person', type=int):
        # a chat on a Meta-direct number, opened in the rail's chats (number_chat): that number's 24 hours
        person = _visible_person(request.args.get('person', type=int))
        line = channels.get(request.args.get('num', type=int))
        digits, name = (person.phone or '').lstrip('+'), person.display_name
    else:
        person, digits, name = _person_for(conversation_id, request.args.get('phone'),
                                           (request.args.get('name') or '').strip())
    lead = None
    if person is not None:
        from app.services import crm
        lead = crm.wa_lead_for(person) or (person.leads[0] if person.leads else None)
    if lead is None:
        from app.services import crm_products
        return render_template('messaging/lead_panel.html', state='none', phone=digits,
                               name=name[:120], conversation=conversation_id, tiles=crm_products.tiles())
    from app.models import CrmTouchpoint
    from app.services import crm, crm_metrics
    belongs = sum(1 for l in person.leads if l.status == 'open') > 1
    # what WhatsApp allows now, from what we hold: free text inside 24 hours of their last message ON THE CHAT'S
    # NUMBER (the WhatsApp CRM's beside its inbox) -- a message to another number of ours opens that number's 24 hours
    on = CrmTouchpoint.line_id.is_(None) if line is None else CrmTouchpoint.line_id == line.id
    last = (crm._real_whatsapp_in(person.id).filter(on)
            .with_entities(CrmTouchpoint.created_at).order_by(CrmTouchpoint.created_at.desc()).first())
    return render_template('messaging/lead_panel.html', state='lead', belongs=belongs,
                           suggested=crm.suggested_reply(lead, current_user), conversation=conversation_id,
                           window_left=crm_metrics.window_left_hours(last[0] if last else None), live=live,
                           us=None if live else channels.badge(line), **lead_card_context(lead, compact=True),
                           **_common())


@messaging_bp.route('/lead-panel/make', methods=['POST'])
@login_required
def lead_panel_make():
    """Somebody wrote on WhatsApp who is not a lead yet: make them one, from the inbox."""
    from flask import current_app
    from app.services import crm, crm_products
    if not access.allowed(current_user, request.endpoint) or not access.can(current_user, 'crm_add'):
        abort(403)
    chosen = crm_products.by_code(request.form.get('product'))
    product = chosen.code if chosen is not None and chosen.offered else None
    digits = ''.join(ch for ch in (request.form.get('wa_phone') or '') if ch.isdigit())
    if len(digits) < 8:
        abort(400)
    key = current_app.config.get('WACRM_SOURCE_KEY') or 'wa-india'
    lead = crm.capture(key, name=(request.form.get('name') or '').strip()[:120] or None, phone='+' + digits,
                       channel='whatsapp', utm={}, created_by_id=current_user.id, note=crm.MADE_FROM_CHAT,
                       product=product)
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


# ------------------------------------------------- the website's live chat: our own bubble, answered here

@messaging_bp.route('/live-chat')
@login_required
def live_chat_page():
    """Live chat (2026-10-30): visitors on our websites, answered here -- the chats on the left (live_chats), one chat
    with the lead page's own box in the middle (live_chat). The same pane opens from the rail beside WhatsApp chats.
    The bubble itself is services/livechat.py; nothing of tawk.to's is framed."""
    from app.routes.crm import _common
    from app.services import livechat
    if not access.allowed(current_user, request.endpoint):
        flash('Your role does not include that page.', 'warning')
        return redirect(access.home_url(current_user))
    leads = access.can(current_user, 'crm_board') or access.can(current_user, 'crm_today')
    return render_template('messaging/live_chat_page.html', cfg=livechat.config(), leads=leads,
                           online=livechat.online(now=datetime.utcnow()), chat=request.args.get('chat', type=int),
                           **_common())


@messaging_bp.route('/live-chat/chats')
@login_required
def live_chats():
    """The website's live chats, newest first (crm_inbox, channel 'webchat'): who is still on the site, the page they
    are on, its search and "whose" tabs. A fragment; ?n=2 and on bring only the next rows."""
    from app.services import crm_inbox, livechat
    _for_leads()
    f = crm_inbox.live_filters(request.args)
    n = request.args.get('n', type=int) or 1
    data = crm_inbox.page(f, current_user, n)
    now = datetime.utcnow()
    chats = livechat.chats_of([r['person'].id for r in data['rows']])
    for r in data['rows']:
        c = chats.get(r['person'].id)
        r['live'] = livechat.here(c, now)
        r['where'] = livechat.status_line(c, now)
    return render_template('messaging/number_chats.html', f=f, here=LIVE_BADGE, WHO=crm_inbox.WHO, live=True,
                           more=n > 1, utcnow=now, **data)


@messaging_bp.route('/live-chat/<int:person_id>')
@login_required
def live_chat(person_id):
    """One visitor's live chat in the middle: their messages (livechat.thread), where they are, and the lead page's
    own box sending on "Live chat" (livechat.reply). A fragment, fetched again to stay fresh (crm.js CRM_applyLive)."""
    from app.routes.crm import _common
    from app.services import crm, livechat
    _for_leads()
    person = _visible_person(person_id)
    chat = livechat.chat_of(person)
    lead = (chat.lead if chat is not None and chat.lead is not None and chat.lead.deleted_at is None else None)         or crm.wa_lead_for(person) or next((l for l in person.leads if l.deleted_at is None), None)
    now = datetime.utcnow()
    from app.services import visitors
    seen = chat.visitor if chat is not None else None           # the browser it came from: where, which device
    ctx = dict(person=person, lead=lead, here=LIVE_BADGE, chat=chat, live=livechat.here(chat, now),
               where=livechat.status_line(chat, now), seen=seen, seen_place=visitors.place(seen) if seen else None)
    if lead is None or chat is None:
        return render_template('messaging/live_chat.html', **ctx)
    return render_template('messaging/live_chat.html', wa={'state': 'live', 'num': None}, stream=livechat.thread(lead),
                           box_note='', social_notes={}, social=[], chat_url=None, via0=livechat.CHANNEL,
                           quick=crm.quick_replies_for(lead, current_user), **ctx, **_common())


@messaging_bp.route('/live-chat/<int:person_id>/typing', methods=['POST'])
@login_required
def live_typing(person_id):
    """One of us is typing in this chat: the visitor sees it for a few seconds."""
    from app.services import livechat
    _for_leads()
    return jsonify(ok=livechat.typing(_visible_person(person_id), current_user))


# ------------------------------------------------- who is on our websites: the chat bubble's visitors

def _visitors_ctx(now):
    from app.services import role_rights, visitors
    return {'V': visitors, 'masked': role_rights.masks(current_user), 'utcnow': now,
            'chat_page': access.can(current_user, 'web_chat'),
            'leads': access.can(current_user, 'crm_board') or access.can(current_user, 'crm_today')}


@messaging_bp.route('/visitors')
@login_required
def visitors_page():
    """Visitors (2026-10-30): who is on our websites now and lately -- where they are, their device, how they found
    us and the pages they read -- recorded by our own chat bubble and placed by our own copy of a free IP list
    (services/visitors.py), as tawk.to's Visitors list showed them. "On the site now" fetches itself again every
    10 seconds (visitors_now); a visitor opens beside the list (visitor)."""
    from app.services import livechat, visitors
    if not access.allowed(current_user, request.endpoint):
        flash('Your role does not include that page.', 'warning')
        return redirect(access.home_url(current_user))
    now = datetime.utcnow()
    f = visitors.filters(request.args)
    return render_template('messaging/visitors.html', f=f, found=visitors.find(f, request.args.get('n', type=int) or 1, now),
                           now_rows=visitors.now_list(now), sums=visitors.summary(now), opts=visitors.choices(now),
                           geo=visitors.geo_status(), cfg=livechat.config(), ping=visitors.ping_url(),
                           open_id=request.args.get('v', type=int), **_visitors_ctx(now))


@messaging_bp.route('/visitors/now')
@login_required
def visitors_now():
    """"On the site now" again, for the screen to swap in (every 10 seconds while it shows)."""
    from app.services import visitors
    if not access.allowed(current_user, request.endpoint):
        abort(403)
    now = datetime.utcnow()
    return render_template('messaging/_visitors_now.html', now_rows=visitors.now_list(now), **_visitors_ctx(now))


@messaging_bp.route('/visitors/<int:visitor_id>')
@login_required
def visitor(visitor_id):
    """One visitor: where they are, their device, how they found us, each visit's pages and their chats. A fragment."""
    from app.models import CrmVisitor
    from app.services import visitors
    if not access.allowed(current_user, request.endpoint):
        abort(403)
    v = db.session.get(CrmVisitor, visitor_id) or abort(404)
    now = datetime.utcnow()
    return render_template('messaging/_visitor.html', d=visitors.detail(v, now), **_visitors_ctx(now))


@messaging_bp.route('/visitors/ip-list', methods=['POST'])
@login_required
def visitors_geo():
    """An admin fetches DB-IP's list now (it comes by itself once a month): in the background, a minute or two."""
    from app.services import visitors
    if not access.allowed(current_user, request.endpoint) or not current_user.is_admin:
        abort(403)
    visitors.refresh_geo_soon()
    flash('Downloading the IP list (about 60 MB). It takes a minute or two: look again shortly.', 'info')
    return redirect(url_for('messaging.visitors_page'))


# ------------------------------------------------- our other numbers, beside WhatsApp chats (the rail)

FIND_SHOWN = 12
# the live chat in the rail and its screens, drawn as a number of ours is (channels.badge's keys)
LIVE_BADGE = {'key': 'web', 'code': 'LIVE', 'name': 'Live chat', 'tone': 'live', 'phone': None, 'last4': None,
              'engine': 'Our websites', 'live': True}


def _for_leads():
    """The rail's chats and its "Find a contact" are for whoever works leads, as the lead panel beside them is."""
    if not access.allowed(current_user, request.endpoint):
        abort(403)
    if not (access.can(current_user, 'crm_board') or access.can(current_user, 'crm_today')):
        abort(403)


def _visible_person(person_id):
    """The contact, if this person may see them (crm_access, and the workspace being worked in); 404 otherwise."""
    from app.models import CrmPerson
    from app.services import crm_access, crm_scope
    person = db.session.get(CrmPerson, person_id) if person_id else None
    if person is None or not crm_access.can_see_person(current_user, person) or not crm_scope.visible(person):
        abort(404)
    return person


def _line(line_id):
    from app.services import channels
    line = channels.get(line_id)
    if line is None:
        abort(404)
    return line


@messaging_bp.route('/number/<int:line_id>/chats')
@login_required
def number_chats(line_id):
    """The chats on one Meta-direct number of ours, newest first, in the middle of WhatsApp chats when the rail picks
    it: All conversations' rows for that number (crm_inbox), its search and its "whose" tabs. A fragment; ?n=2 and on
    bring only the next rows."""
    from app.services import channels, crm_inbox
    _for_leads()
    line = _line(line_id)
    f = crm_inbox.filters({'num': str(line.id), 'who': request.args.get('who'), 'q': request.args.get('q')})
    f['started'] = True                  # a chat we started there is a chat on the number too
    n = request.args.get('n', type=int) or 1
    return render_template('messaging/number_chats.html', f=f, here=channels.badge(line), WHO=crm_inbox.WHO,
                           more=n > 1, utcnow=datetime.utcnow(), **crm_inbox.page(f, current_user, n))


@messaging_bp.route('/number/<int:line_id>/chat/<int:person_id>')
@login_required
def number_chat(line_id, person_id):
    """One person's chat on one Meta-direct number of ours, in the middle of WhatsApp chats: their messages with that
    number (crm_timeline.number_thread) and the lead page's own message box -- which sends from the number WhatsApp
    allows (channels.line_for) and says which. A fragment, fetched again to stay fresh (crm.js CRM_applyLive)."""
    from app.routes.crm import _common
    from app.services import channels, crm, crm_timeline, wacrm
    _for_leads()
    line = _line(line_id)
    person = _visible_person(person_id)
    lead = crm.wa_lead_for(person) or next((l for l in person.leads if l.deleted_at is None), None)
    here = channels.badge(line)
    if lead is None:
        return render_template('messaging/number_chat.html', person=person, lead=None, here=here)
    with wacrm.short_timeouts():
        wa = crm.wa_chat_state(lead)
        tpl = crm.box_templates(lead, current_user)
    return render_template('messaging/number_chat.html', person=person, lead=lead, here=here, wa=wa, tpl=tpl,
                           stream=crm_timeline.number_thread(lead, line), box_note=crm.box_note(wa), social_notes={},
                           social=[], chat_url=None, via0='whatsapp', quick=crm.quick_replies_for(lead, current_user),
                           **_common())


@messaging_bp.route('/find')
@login_required
def find_chat():
    """"Find a contact" in the rail beside WhatsApp chats: people with a WhatsApp chat on any number of ours whose
    name, phone or e-mail has the words, newest chat first, each with the numbers they talk to us on -- one click opens
    that chat. A fragment."""
    from app.services import crm_inbox
    _for_leads()
    q = ' '.join((request.args.get('q') or '').split())[:80]
    if len(q) < 2:
        return ''
    data = crm_inbox.page(crm_inbox.filters({'ch': 'whatsapp', 'q': q}), current_user)
    return render_template('messaging/find_chat.html', q=q, rows=data['rows'][:FIND_SHOWN], total=data['total'],
                           utcnow=datetime.utcnow())
