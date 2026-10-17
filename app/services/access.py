"""Who may open what: workspaces, modules, pages, roles and teams.

    workspace  ->  modules it has switched on  ->  the pages in them
    role       ->  a set of pages (made and edited on Workspace -> Roles)
    person     ->  their own role in a workspace + the roles of the teams they are in

What a page IS lives here, because a page is a screen in the code: its label, its icon, the
endpoints it is made of and where its menu link goes. Everything about WHO opens it lives in the
database (models.Workspace*), so giving somebody the insurance desk is a tick on a screen rather
than a change to a decorator.

Two consoles grew up separately -- /admin and /cs -- and a few screens exist in both (the voices
inbox, insurance leads, the Sahayak queue, the Sales CRM). A page owns both copies, so granting
"Quote leads" opens it wherever the link happens to point; the menu link stays in whichever
console the person is already in.

Before any workspace exists, and for staff nobody has added to one yet, the old rules still hold:
an admin opens everything and a CS agent opens the console screens (narrowed by the cs_access
list if an admin set one). That is also what ensure_defaults() writes down as roles, so the first
workspace starts out exactly as the site already behaved.

The menu groups pages by SECTIONS; MODULES stay the areas a workspace switches on.
"""
import re

from flask import has_request_context, request, session, url_for

from app import db


# ------------------------------------------------------------------------------- the pages

def _page(key, label, icon, endpoints=(), admin=None, cs=None, args=None, nav=True, desc='', lit=(), deny=None,
          tip=''):
    """`admin` / `cs`: the endpoint the menu opens in that console (None: not in that console).
    `args`: the query string both links carry -- several menu lines are one screen filtered.
    `lit`: endpoints other pages share that should light THIS line (the lead page is "Leads",
    though My day opens it too). `tip`: the menu line's tooltip; `desc` is what the Roles screen
    says about the page."""
    return {'key': key, 'label': label, 'icon': icon, 'endpoints': tuple(endpoints),
            'links': {'admin': admin, 'cs': cs}, 'args': dict(args or {}), 'nav': nav, 'desc': desc,
            'lit': frozenset(lit), 'deny': deny, 'tip': tip}


def _both(*names):
    """A Sales CRM endpoint: the same view is mounted in both consoles."""
    return tuple('crm.' + n for n in names) + tuple('admin_crm.' + n for n in names)


# one inbox seen through different filters: every voices line owns the whole of it
VOICES = ('cs.voices', 'cs.contact_messages', 'cs.contact_status', 'cs.voice_read', 'cs.contact_reply',
          'admin.voices', 'admin.voice_status', 'admin.contact_messages')

# what a salesperson does to a lead, from My day or from the lead itself
CRM_DAILY = _both('lead', 'move', 'route_lead', 'task_action', 'send', 'call', 'note', 'update',
                  'suggest', 'answer_used', 'event', 'undo', 'reopen', 'remove', 'message', 'live', 'opt_in',
                  'wa_retry', 'snooze_lead', 'bulk', 'find', 'contact', 'contact_edit', 'contact_tags')

MATCHES = ('matches.cs_match_queue', 'matches.cs_matches', 'matches.cs_notify', 'matches.cs_dismiss',
           'matches.cs_connected', 'matches.cs_mark_sent', 'matches.cs_intro_text', 'matches.trip_matches',
           'matches.api_notify', 'matches.api_dismiss', 'matches.cs_read_post')

SCRAPER = tuple('scraper.' + n for n in (
    'recipes', 'new_recipe', 'new_recipe_detect', 'use_source', 'start_teach', 'recipe_form', 'preview_recipe',
    'mapping', 'mapping_preview', 'recipe_runs', 'start_run', 'toggle_recipe', 'delete_recipe', 'run_detail',
    'run_status', 'cancel_run', 'create_posts', 'skip_rows', 'row_detail', 'row_edit', 'export_run',
    'export_recipe'))

MODULES = [
    {'key': 'console', 'label': 'Overview', 'icon': 'fa-gauge',
     'desc': 'Service to-do, notifications and the site dashboard.',
     'pages': [
         _page('dashboard', 'Site dashboard', 'fa-gauge', ['admin.dashboard'], admin='admin.dashboard',
               desc='Numbers across every product on the site.', tip='Numbers across every product on the site.'),
         _page('home', 'Service to-do', 'fa-inbox', ['cs.home'], cs='cs.home',
               desc='What is waiting for customer service.'),
         _page('notifications', 'Notifications', 'fa-bell',
               ['cs.notifications', 'cs.notifications_read', 'cs.notifications_send'], cs='cs.notifications'),
     ]},
    {'key': 'crm', 'label': 'Sales', 'icon': 'fa-filter-circle-dollar',
     'desc': 'Leads, follow-ups, contacts, quick replies, the half-hourly check, reports and set-up.',
     'pages': [
         _page('crm_today', 'My day', 'fa-sun', _both('today', 'log_work', 'signoff') + CRM_DAILY,
               admin='admin_crm.today', cs='crm.today',
               tip="Today's follow-ups and customers waiting, in order."),
         _page('crm_board', 'Leads', 'fa-table-columns', _both('board') + CRM_DAILY,
               admin='admin_crm.board', cs='crm.board', lit=_both('lead'),
               tip='Every enquiry, by stage, for each product.'),
         _page('crm_people', 'Contacts', 'fa-address-book',
               _both('contacts', 'contact', 'contact_edit', 'contact_tags', 'find') + ('messaging.contacts',),
               admin='admin_crm.contacts', cs='crm.contacts', lit=_both('contact', 'contact_edit'),
               desc='Everyone we can reach, one row per person, and each contact page.',
               tip='Everyone we can reach, one row per person.'),
         _page('crm_add', 'Add a lead', 'fa-user-plus', _both('add', 'add_from_record'),
               admin='admin_crm.add', cs='crm.add', nav=False, desc='The Add a lead button on Leads and My day.'),
         _page('crm_checks', 'Half-hourly check', 'fa-clipboard-check', _both('checks', 'check_tick'),
               admin='admin_crm.checks', cs='crm.checks',
               tip='Tick each inbox every half hour; connected ones tick themselves.'),
         _page('crm_process', 'How we sell', 'fa-route', _both('process'),
               admin='admin_crm.process', cs='crm.process',
               tip="Our sales path per product, with today's numbers."),
         _page('crm_quick', 'Quick replies', 'fa-bolt',
               _both('quick_replies', 'save_answer', 'setup') + ('messaging.quick_replies',),
               admin='admin_crm.quick_replies', cs='crm.quick_replies',
               tip='Ready-made answers for every chat; edit them only here.'),
         _page('crm_tracker', 'Team today', 'fa-people-line', _both('tracker'), admin='admin_crm.tracker',
               desc="Each person's checklist and timeline, day by day.", tip="How each person's day is going."),
         _page('crm_insights', 'Results', 'fa-chart-line', _both('insights') + ('messaging.overview',),
               admin='admin_crm.insights',
               tip='New leads, replies and customers won, by product, source and person.'),
         _page('crm_auto', 'What goes out by itself', 'fa-list-check', _both('automatic'), admin='admin_crm.automatic',
               desc='Every automatic message in one list, with where to change it.',
               tip='Every automatic message in one list, with where to change it.'),
         _page('crm_pipelines', 'Pipelines', 'fa-diagram-project',
               _both('pipelines', 'pipeline_new', 'pipeline_edit', 'pipeline_save', 'pipeline_active',
                     'pipeline_tag_check', 'pipeline_tag', 'tag_check', 'save_product', 'product_offered',
                     'template_draft', 'save_pipeline', 'save_step', 'setup_templates', 'setup'),
               admin='admin_crm.pipelines', tip='Stages and follow-ups for each product.'),
         _page('crm_sources', 'Where leads come from', 'fa-door-open',
               _both('sources', 'save_source', 'save_process', 'setup', 'save_inboxes', 'save_activities',
                     'source_tag_check'),
               admin='admin_crm.sources', tip='Forms and channels, who gets their leads, the inboxes to check.'),
         _page('crm_connection', 'WhatsApp connection', 'fa-plug',
               _both('connection', 'save_whatsapp', 'setup', 'connection_checks', 'connection_team',
                     'connection_retry', 'connection_settle', 'quick_replies_push', 'quick_replies_import'),
               admin='admin_crm.connection', tip='Is WhatsApp linked, and what to fix if not.'),
         _page('crm_data', 'Bring in & download', 'fa-file-arrow-up',
               _both('data', 'backfill', 'import_sheet', 'import_confirm', 'setup', 'import_csv',
                     'import_csv_confirm', 'wa_contacts_import', 'wa_notes_import'),
               admin='admin_crm.data', tip='Import lists and old enquiries; download lists.'),
         _page('crm_export', 'Download lists of leads and contacts', 'fa-file-arrow-down', _both('insights_csv', 'export_leads', 'export_contacts'),
               admin='admin_crm.insights', nav=False,
               desc='Download this list on Leads and Contacts, and the downloads on Bring in & download.'),
     ]},
    {'key': 'companion', 'label': 'Travel Companion', 'icon': 'fa-plane-departure',
     'desc': 'Trip posts, matches and everything on the companion site.',
     'pages': [
         _page('posts', 'All posts', 'fa-list',
               ['cs.posts', 'cs.post_detail', 'cs.post_tree', 'cs.edit_post', 'cs.publish_post', 'cs.close_post',
                'cs.reopen_post', 'cs.issue_claim_link', 'cs.log_manual_event', 'cs.check_duplicates'],
               cs='cs.posts'),
         _page('matches', 'Match queue', 'fa-handshake', MATCHES, cs='matches.cs_match_queue'),
         _page('metrics', 'Match quality', 'fa-chart-simple', ['cs.metrics'], cs='cs.metrics',
               desc='How matches turn out, and hints for the match weights.'),
         _page('new', 'New post', 'fa-plus', ['cs.new_post'], cs='cs.new_post'),
         _page('import', 'Import', 'fa-file-import', ['imports.import_page', 'imports.import_template'],
               cs='imports.import_page'),
         _page('scraper', 'Scraper', 'fa-spider', SCRAPER, cs='scraper.recipes',
               desc='Bring posts in from other sites.'),
         _page('listings', 'Listings', 'fa-rectangle-list', ['admin.listings', 'admin.disable_listing'],
               admin='admin.listings'),
         _page('voices_contact', 'Contact us', 'fa-envelope', VOICES, admin='admin.voices', cs='cs.voices',
               args={'tab': 'contact', 'topic': 'companion'}),
         _page('voices_feedback', 'Feedback', 'fa-star',
               VOICES + ('cs.feedback_action', 'admin.feedback', 'admin.approve_feedback',
                         'admin.feature_feedback', 'admin.reject_feedback'),
               admin='admin.voices', cs='cs.voices', args={'tab': 'feedback'}),
         _page('voices_report', 'Reports', 'fa-flag-checkered', VOICES + ('cs.report_action',),
               admin='admin.voices', cs='cs.voices', args={'tab': 'report'}),
         _page('landing', 'Landing page', 'fa-flag', ['admin.landing_page'], admin='admin.landing_page',
               desc='Contact numbers, support addresses and colours.'),
         _page('blog_list', 'Blog posts', 'fa-newspaper', ['admin.blog_list'], admin='admin.blog_list'),
         _page('blog', 'New blog post', 'fa-pen', ['admin.new_blog'], admin='admin.new_blog'),
         _page('help', 'Help & FAQ', 'fa-circle-question', ['admin.help_center_page'],
               admin='admin.help_center_page'),
     ]},
    {'key': 'insurance', 'label': 'Travel Insurance', 'icon': 'fa-shield-heart',
     'desc': 'Quote leads, enquiries and the insurance page.',
     'pages': [
         _page('insurance', 'Quote leads', 'fa-shield-heart', ['admin.insurance_quotes', 'cs.insurance_quotes'],
               admin='admin.insurance_quotes', cs='cs.insurance_quotes'),
         _page('voices_insurance', 'Enquiries', 'fa-envelope', VOICES, admin='admin.voices', cs='cs.voices',
               args={'tab': 'contact', 'topic': 'insurance'}),
         _page('insurance_page', 'Page content', 'fa-quote-left', ['admin.insurance_page_content'],
               admin='admin.insurance_page_content'),
         _page('help_insurance', 'Help & FAQ', 'fa-circle-question', ['admin.help_center_page'],
               admin='admin.help_center_page', args={'site': 'insurance'}),
     ]},
    {'key': 'sahayak', 'label': 'Sahayak', 'icon': 'fa-house-medical',
     'desc': 'Home-care bookings, nurse applications and the service list.',
     'pages': [
         _page('sahayak', 'Bookings', 'fa-house-medical',
               ['admin.sahayak_bookings', 'cs.sahayak_bookings', 'cs.sahayak_update'],
               admin='admin.sahayak_bookings', cs='cs.sahayak_bookings'),
         _page('voices_sahayak', 'Applications & enquiries', 'fa-user-plus', VOICES, admin='admin.voices',
               cs='cs.voices', args={'tab': 'contact', 'topic': 'sahayak'}),
         _page('sahayak_services', 'Services & prices', 'fa-list-check', ['admin.sahayak_services'],
               admin='admin.sahayak_services'),
         _page('help_sahayak', 'Help & FAQ', 'fa-circle-question', ['admin.help_center_page'],
               admin='admin.help_center_page', args={'site': 'sahayak'}),
     ]},
    {'key': 'whatsapp', 'label': 'WhatsApp messaging', 'icon': 'fa-brands fa-whatsapp',
     'desc': 'The WhatsApp screens inside the portal: chats, templates, broadcasts, tags, reply rules, chatbot, '
             'AI replies and the number.',
     'pages': [
         _page('wa_inbox', 'WhatsApp chats', 'fa-brands fa-whatsapp',
               ['messaging.inbox', 'messaging.lead_panel', 'messaging.lead_panel_make'], admin='messaging.inbox',
               cs='messaging.inbox', desc='Every WhatsApp conversation.',
               tip='Every WhatsApp conversation; the lead shows beside the open chat.'),
         _page('wa_templates', 'WhatsApp templates', 'fa-file-lines', ['messaging.templates'],
               admin='messaging.templates', cs='messaging.templates',
               desc='Messages WhatsApp has approved. Makes somebody a WhatsApp admin.',
               tip='Messages WhatsApp has approved, for first messages and after 24 hours.'),
         _page('wa_broadcasts', 'Broadcasts', 'fa-bullhorn', ['messaging.broadcasts'],
               admin='messaging.broadcasts', cs='messaging.broadcasts', desc='One approved template to many.',
               tip='One approved message to many people.'),
         _page('wa_tags', 'Tags', 'fa-tags', ['messaging.tags'], admin='messaging.tags', cs='messaging.tags',
               desc='Makes somebody a WhatsApp admin.',
               tip='Labels on contacts, used to pick who gets a broadcast or a reply rule.'),
         _page('wa_automations', 'Reply rules', 'fa-reply-all', ['messaging.automations'],
               admin='messaging.automations', cs='messaging.automations',
               desc='Welcome messages, keywords, out-of-hours and follow-ups.',
               tip='Replies to keywords, first messages and out-of-hours.'),
         _page('wa_flows', 'Chatbot', 'fa-sitemap', ['messaging.flows'], admin='messaging.flows',
               cs='messaging.flows', tip='A menu of buttons that answers step by step.'),
         _page('wa_ai', 'AI replies', 'fa-robot', ['messaging.ai'], admin='messaging.ai', cs='messaging.ai',
               desc='Makes somebody a WhatsApp admin.', tip='AI answers from the documents you add here.'),
         _page('wa_settings', 'WhatsApp number', 'fa-sim-card', ['messaging.settings'], admin='messaging.settings',
               cs='messaging.settings', desc='Makes somebody a WhatsApp admin. Also opens Tags.',
               tip='The number customers write to, and its Meta details.'),
     ]},
    {'key': 'site', 'label': 'Site settings', 'icon': 'fa-gear',
     'desc': 'Accounts, wording, dropdowns, notifications and colours for the whole site.',
     'pages': [
         _page('voices_general', 'Contact us (all services)', 'fa-inbox', VOICES, admin='admin.voices',
               cs='cs.voices', args={'tab': 'contact', 'topic': 'general'}),
         _page('users', 'Users', 'fa-users',
               ['admin.users', 'admin.toggle_user', 'admin.set_user_role', 'admin.set_user_roles', 'admin.new_user'],
               admin='admin.users'),
         _page('options', 'Options & dropdowns', 'fa-sliders',
               ['admin.options_page', 'admin.translations_list', 'admin.translations_save', 'admin.save_options',
                'admin.reset_options', 'admin.airports_search', 'admin.airports_add', 'admin.airports_delete',
                'admin.airlines_search', 'admin.airlines_add', 'admin.airlines_delete'],
               admin='admin.options_page'),
         _page('messages', 'Trip post texts & e-mails', 'fa-envelope-open-text',
               ['admin.messages_page', 'admin.test_email', 'admin.save_message', 'admin.reset_message',
                'admin.save_custom_snippets', 'admin.preview_message'],
               admin='admin.messages_page'),
         _page('notiflog', 'Notification log', 'fa-bell',
               ['admin.notification_log', 'admin.notification_log_send', 'admin.notification_log_read',
                'admin.notification_log_delete', 'admin.notification_log_delete_matching', 'admin.broadcast'],
               admin='admin.notification_log'),
         _page('notify_switches', 'Notification switches', 'fa-bell-slash', ['admin.notification_switches'],
               admin='admin.notification_switches'),
         _page('themes', 'Colour themes', 'fa-palette', ['admin.themes_page'], admin='admin.themes_page'),
         _page('delete_records', 'Delete records permanently', 'fa-trash-can',
               ['admin.hard_delete', 'admin.hard_delete_bulk', 'admin.delete_user', 'admin.bulk_delete_users',
                'admin.delete_listing', 'admin.bulk_delete_listings', 'crm.contact_erase', 'admin_crm.contact_erase'],
               nav=False, desc=('The bin buttons on every list, and Erase this person on a contact page. '
                                'Nothing deleted this way can be brought back.'),
               deny='Only an admin can delete this.'),
     ]},
    {'key': 'workspace', 'label': 'Team', 'icon': 'fa-people-group', 'required': True,
     'desc': 'Team members, teams, roles and the areas this workspace uses.',
     'pages': [
         _page('ws_settings', 'Workspace', 'fa-building',
               ['workspace.overview', 'workspace.save_settings', 'workspace.whatsapp'],
               admin='workspace.overview', tip='Business name and the areas you use.'),
         _page('ws_members', 'Team members', 'fa-user-gear',
               ['workspace.members', 'workspace.add_member', 'workspace.member', 'workspace.save_member',
                'workspace.remove_member', 'admin.cs_agents', 'admin.cs_screen_access'],
               admin='workspace.members', tip='Who works here, their role and teams.'),
         _page('ws_teams', 'Teams', 'fa-people-group',
               ['workspace.teams', 'workspace.team', 'workspace.save_team', 'workspace.delete_team'],
               admin='workspace.teams', tip='Groups of people who share a role.'),
         _page('ws_roles', 'Roles', 'fa-user-lock',
               ['workspace.roles', 'workspace.role', 'workspace.save_role', 'workspace.delete_role'],
               admin='workspace.roles', tip='What each kind of job can open.'),
         _page('ws_all', 'All workspaces', 'fa-layer-group',
               ['workspace.all_workspaces', 'workspace.create_workspace'], admin='workspace.all_workspaces',
               nav=False, desc='Make new workspaces (a tab on Workspace).'),
     ]},
]

# The menu, in order: each section is a heading in the staff menu with its pages in this order.
# A page's area (its module above) still decides whether the workspace has it switched on; the
# section only decides where its line sits. The one place the menu's order lives.
SECTIONS = [
    {'key': 'overview', 'label': 'Overview', 'icon': 'fa-gauge', 'pages': ('dashboard', 'home', 'notifications')},
    {'key': 'sales', 'label': 'Sales', 'icon': 'fa-filter-circle-dollar',
     'pages': ('crm_today', 'wa_inbox', 'crm_board', 'crm_people', 'crm_checks', 'crm_process', 'crm_add')},
    {'key': 'messaging', 'label': 'Messaging', 'icon': 'fa-comments',
     'pages': ('crm_quick', 'wa_templates', 'wa_broadcasts', 'wa_tags')},
    {'key': 'automatic', 'label': 'Automatic messages', 'icon': 'fa-wand-magic-sparkles',
     'pages': ('crm_auto', 'wa_automations', 'wa_flows', 'wa_ai')},
    {'key': 'reports', 'label': 'Reports', 'icon': 'fa-chart-column', 'pages': ('crm_tracker', 'crm_insights')},
    {'key': 'setup', 'label': 'Set-up', 'icon': 'fa-sliders',
     'pages': ('crm_pipelines', 'crm_sources', 'crm_connection', 'wa_settings', 'crm_data', 'crm_export')},
    {'key': 'team', 'label': 'Team', 'icon': 'fa-users',
     'pages': ('ws_members', 'ws_teams', 'ws_roles', 'ws_settings', 'ws_all')},
    {'key': 'companion', 'label': 'Travel Companion', 'icon': 'fa-plane-departure',
     'pages': ('posts', 'matches', 'metrics', 'new', 'import', 'scraper', 'listings', 'voices_contact', 'voices_feedback',
               'voices_report', 'landing', 'blog_list', 'blog', 'help')},
    {'key': 'insurance', 'label': 'Travel Insurance', 'icon': 'fa-shield-heart',
     'pages': ('insurance', 'voices_insurance', 'insurance_page', 'help_insurance')},
    {'key': 'sahayak', 'label': 'Sahayak', 'icon': 'fa-house-medical',
     'pages': ('sahayak', 'voices_sahayak', 'sahayak_services', 'help_sahayak')},
    {'key': 'site', 'label': 'Site settings', 'icon': 'fa-gear',
     'pages': ('voices_general', 'users', 'options', 'messages', 'notiflog', 'notify_switches', 'themes',
               'delete_records')},
]

# Endpoints anybody on the staff side may open, whatever their role: the plumbing behind
# screens rather than screens (saved filters, the "what's new" button, switching workspace).
STAFF_ANY = {
    'cs.whats_new_api', 'workspace.switch', 'messaging.sso', 'messaging.lead_chat',
    'saved.manage', 'saved.open_filter', 'saved.save', 'saved.rename', 'saved.share', 'saved.delete', 'saved.move',
}

PAGES = {}
for _m in MODULES:
    for _p in _m['pages']:
        _p['module'] = _m['key']
        PAGES[_p['key']] = _p
ALL_PAGES = frozenset(PAGES)
SECTION_BY_KEY = {s['key']: s for s in SECTIONS}
for _s in SECTIONS:
    for _k in _s['pages']:
        PAGES[_k]['section'] = _s['key']
MENU_ORDER = tuple(k for s in SECTIONS for k in s['pages'])
# every page sits in exactly one section, and no section names a page that does not exist
assert sorted(MENU_ORDER) == sorted(PAGES), 'SECTIONS and MODULES disagree about the pages'
MODULE_KEYS = [m['key'] for m in MODULES]
REQUIRED_MODULES = {m['key'] for m in MODULES if m.get('required')}
MODULE_BY_KEY = {m['key']: m for m in MODULES}

ENDPOINT_PAGES = {}
for _p in PAGES.values():
    for _ep in _p['endpoints']:
        ENDPOINT_PAGES.setdefault(_ep, set()).add(_p['key'])

# The consoles' blueprints, for "which console am I in" when choosing a menu link.
ADMIN_SIDE = {'admin', 'admin_crm', 'workspace', 'messaging'}


# ------------------------------------------------------------------------- the old rules

# cs_access screen keys -> pages. The CS console's per-agent list predates roles; a stored list
# still means what it meant, and ensure_defaults() turns each distinct one into a role.
VOICE_PAGES = ('voices_contact', 'voices_feedback', 'voices_report', 'voices_insurance', 'voices_sahayak',
               'voices_general')
LEGACY_SCREEN_PAGES = {
    'home': ('home',), 'notifications': ('notifications',), 'metrics': ('metrics',), 'voices': VOICE_PAGES,
    'posts': ('posts',), 'matches': ('matches',), 'new': ('new',), 'import': ('import',),
    'scraper': ('scraper',), 'insurance': ('insurance',), 'sahayak': ('sahayak',),
    'crm_board': ('crm_today', 'crm_board', 'crm_add', 'crm_checks', 'crm_process'),
}
# an agent nobody has narrowed: every console screen except the scraper, which was admin-only
CS_DEFAULT_PAGES = frozenset(p for k, pages in LEGACY_SCREEN_PAGES.items() if k != 'scraper' for p in pages)
# what a new workspace's Sales & service role starts with: the console, plus WhatsApp chats,
# Contacts and Quick replies, which an agent works in every day
CS_ROLE_PAGES = CS_DEFAULT_PAGES | {'wa_inbox', 'crm_people', 'crm_quick'}

# page keys before the one menu (U2) -> what they became; read wherever role pages are read
OLD_PAGE_KEYS = {'wa_contacts': ('crm_people',), 'wa_quick': ('crm_quick',),
                 'crm_setup': ('crm_pipelines', 'crm_sources', 'crm_connection', 'crm_data', 'crm_export'),
                 'wa_overview': ()}
NEW_IN_ONE_MENU = frozenset({'crm_people', 'crm_quick', 'crm_pipelines', 'crm_sources', 'crm_connection',
                             'crm_data', 'crm_export', 'wa_tags'})
# keys a later step adds: kept in stored roles (a role save does not drop them), never shown
RESERVED_PAGES = frozenset()
# the Team lead role: Sales & service plus these
TEAM_LEAD_EXTRA = frozenset({'crm_tracker', 'crm_insights', 'crm_auto', 'wa_broadcasts'})


def expand_page_keys(keys):
    """A stored list of page keys as today's pages: old keys become their new ones, and a list written
    before Tags had its own line gets Tags with WhatsApp number. Unknown keys are dropped."""
    keys = list(keys or [])
    out = set()
    for k in keys:
        out.update(OLD_PAGE_KEYS.get(k, (k,)))
    if 'wa_settings' in out and not set(keys) & NEW_IN_ONE_MENU:
        out.add('wa_tags')
    return frozenset(k for k in out if k in PAGES)


def _legacy_pages(user):
    if user.is_admin:
        return ALL_PAGES
    if not user.is_cs:
        return frozenset()
    keys = getattr(user, 'cs_access', None)
    if keys is None:
        return CS_DEFAULT_PAGES
    return frozenset(p for k in keys for p in LEGACY_SCREEN_PAGES.get(k, ()))


# ------------------------------------------------------------------------------ lookups

def _cache():
    """Answers already worked out for this request. Kept on the request itself (its WSGI
    environ), not on `g`: an application context can outlive one request -- a worker's CLI
    job, a test run -- and roles changed in between must not be read from a stale copy."""
    if not has_request_context():
        return {}
    return request.environ.setdefault('app.access', {})


def _authed(user):
    return bool(user is not None and getattr(user, 'is_authenticated', False))


def memberships(user):
    """Every workspace this person is in, oldest workspace first."""
    from app.models import WorkspaceMember, Workspace
    if not _authed(user):
        return []
    c = _cache()
    key = ('m', user.id)
    if key not in c:
        c[key] = (WorkspaceMember.query.join(Workspace).filter(WorkspaceMember.user_id == user.id)
                  .order_by(Workspace.id).all())
    return c[key]


def workspaces_for(user):
    """The workspaces this person can switch between. A site admin sees them all."""
    from app.models import Workspace
    if not _authed(user):
        return []
    if user.is_admin:
        return Workspace.query.order_by(Workspace.id).all()
    return [m.workspace for m in memberships(user)]


def default_workspace():
    from app.models import Workspace
    return Workspace.query.order_by(Workspace.id).first()


def current_workspace(user):
    """The workspace this request works in: the one chosen in the switcher, else their first."""
    if not _authed(user):
        return None
    c = _cache()
    key = ('ws', user.id)
    if key in c:
        return c[key]
    choices = workspaces_for(user)
    chosen = None
    wanted = session.get('ws_id') if has_request_context() else None
    if wanted:
        chosen = next((w for w in choices if w.id == wanted), None)
    if chosen is None and choices:
        chosen = choices[0]
    c[key] = chosen
    return chosen


def set_current_workspace(ws):
    if has_request_context():
        session['ws_id'] = ws.id
        _cache().clear()


def enabled_modules(ws):
    if ws is None or ws.modules is None:
        return list(MODULE_KEYS)
    on = set(ws.modules) | REQUIRED_MODULES
    return [k for k in MODULE_KEYS if k in on]


def module_pages(module_keys):
    return frozenset(p['key'] for k in module_keys for p in MODULE_BY_KEY[k]['pages'])


def role_pages(role):
    """A role's pages. The administrator's are every page there is, computed rather than stored,
    so a screen added next month is not missing from the one role that must have everything.
    Keys stored before the one menu are read as the pages they became (expand_page_keys)."""
    if role is None:
        return frozenset()
    if role.system_key == 'admin':
        return ALL_PAGES
    return expand_page_keys(role.pages)


def _member_pages(member):
    from app.models import WorkspaceTeam, workspace_team_members
    ws = member.workspace
    within = module_pages(enabled_modules(ws))
    if member.is_owner:
        return within
    pages = set(role_pages(member.role))
    teams = (WorkspaceTeam.query.join(workspace_team_members, workspace_team_members.c.team_id == WorkspaceTeam.id)
             .filter(WorkspaceTeam.workspace_id == ws.id, workspace_team_members.c.user_id == member.user_id).all())
    for t in teams:
        pages |= role_pages(t.role)
    return frozenset(pages) & within


def pages_for(user, ws=None):
    """The page keys this person may open in `ws` (default: the current workspace)."""
    if not _authed(user):
        return frozenset()
    if user.is_admin:
        return ALL_PAGES
    mems = memberships(user)
    if not mems:
        return _legacy_pages(user)
    ws = ws or current_workspace(user)
    if ws is None:
        return frozenset()
    c = _cache()
    key = ('p', user.id, ws.id)
    if key not in c:
        m = next((m for m in mems if m.workspace_id == ws.id), None)
        c[key] = _member_pages(m) if m else frozenset()
    return c[key]


def pages_anywhere(user):
    """Everything this person may open in any of their workspaces -- for "who should hear about
    this", where the answer cannot depend on which workspace they happen to have open."""
    if not _authed(user):
        return frozenset()
    if user.is_admin:
        return ALL_PAGES
    mems = memberships(user)
    if not mems:
        return _legacy_pages(user)
    out = set()
    for m in mems:
        out |= _member_pages(m)
    return frozenset(out)


def is_staff(user):
    if not _authed(user):
        return False
    return bool(user.is_admin or user.is_cs or memberships(user))


def can(user, page_key):
    return page_key in pages_for(user)


def claims(endpoint):
    return bool(endpoint) and (endpoint in ENDPOINT_PAGES or endpoint in STAFF_ANY)


def allowed(user, endpoint, fallback=None):
    """May `user` open `endpoint`?

    An endpoint no page claims is not this module's to decide: `fallback(user)` decides (the
    route's old rule), or it is allowed. When the current workspace says no but another of theirs
    says yes -- a link from a notification about the other one -- that workspace becomes current.
    """
    if not _authed(user):
        return False
    if endpoint in STAFF_ANY:
        return is_staff(user)
    owners = ENDPOINT_PAGES.get(endpoint or '')
    if not owners:
        return bool(fallback(user)) if fallback else True
    if owners & pages_for(user):
        return True
    for m in memberships(user):
        if owners & _member_pages(m):
            set_current_workspace(m.workspace)
            return True
    return False


# --------------------------------------------------------------------------- the menu

def current_console(user=None):
    """Which console's copy a menu link should open. Only site admins live in /admin; everybody
    else stays in /cs and reaches an admin-only screen there when their role gives them one."""
    if user is not None and _authed(user) and not user.is_admin:
        return 'cs'
    if has_request_context() and request.blueprint in ADMIN_SIDE:
        return 'admin'
    return 'cs'


def page_url(page, console=None):
    if console is None:
        from flask_login import current_user
        console = current_console(current_user)
    other = 'cs' if console == 'admin' else 'admin'
    endpoint = page['links'].get(console) or page['links'].get(other)
    if not endpoint:
        return None
    try:
        return url_for(endpoint, **page['args'])
    except Exception:          # noqa: BLE001 -- an endpoint switched off (the scraper flag)
        return None


def active_page(fallback=None):
    """Which menu line is this request? Several lines are one screen with a filter, so the
    query string decides between them: a line whose filter disagrees with the request is out."""
    if not has_request_context():
        return fallback
    owners = ENDPOINT_PAGES.get(request.endpoint or '')
    if not owners:
        return fallback if fallback in PAGES else None
    best, best_score = None, -1
    for key in (k for m in MODULES for k in (p['key'] for p in m['pages']) if k in owners):
        page = PAGES[key]
        if not page['nav']:
            continue
        args = page['args']
        if any(k in request.args and request.args.get(k) != v for k, v in args.items()):
            continue
        # a line that names the screen it is on beats one that merely owns it
        on_link = request.endpoint in (page['links']['admin'], page['links']['cs']) or request.endpoint in page['lit']
        score = sum(1 for k, v in args.items() if request.args.get(k) == v) + (10 if on_link else 0)
        if score > best_score:
            best, best_score = key, score
    return best or (fallback if fallback in PAGES else None)


def nav(user, fallback_active=None):
    """The staff menu: SECTIONS in order, each with the pages this person may open whose area is
    switched on in this workspace, the one being looked at marked. A section with nothing in it for
    them is left out. `mark`: the line's badge is a "!" (services/nav_badges.MARKS); `sum`: its
    number counts in the section's total."""
    from app.services.nav_badges import MARKS
    ws = current_workspace(user)
    on = set(enabled_modules(ws))
    allowed_pages = pages_for(user, ws)
    here = active_page(fallback_active)
    console = current_console(user)
    groups = []
    for sec in SECTIONS:
        items = []
        for key in sec['pages']:
            p = PAGES[key]
            if not p['nav'] or p['module'] not in on or key not in allowed_pages:
                continue
            url = page_url(p, console)
            if url:
                items.append({'key': key, 'label': p['label'], 'icon': p['icon'], 'tip': p['tip'] or p['label'],
                              'url': url, 'active': key == here, 'badge': key,
                              'mark': key in MARKS, 'sum': key not in MARKS})
        # the customers waiting are in My day's number too: the section's total counts them once
        if any(i['key'] == 'crm_today' for i in items):
            for i in items:
                if i['key'] == 'wa_inbox':
                    i['sum'] = False
        if items:
            groups.append({'key': sec['key'], 'label': sec['label'], 'icon': sec['icon'], 'items': items,
                           'open': any(i['active'] for i in items)})
    # a short menu is shown whole; a long one opens only the section being worked in (the rest are
    # one click away, and the menu remembers what was opened)
    if sum(len(gr['items']) for gr in groups) <= 12:
        for gr in groups:
            gr['open'] = True
    return groups


def home_url(user):
    """Where a staff account lands: site owners on Results (the site dashboard when Sales is off),
    people who work leads on My day, customer service on Service to-do, anybody else on the first
    page in the menu their roles give them."""
    if user.is_admin:                                          # a site owner
        return url_for('admin_crm.insights' if 'crm' in enabled_modules(current_workspace(user))
                       else 'admin.dashboard')
    pages = pages_for(user)
    if 'crm_today' in pages:
        return url_for('crm.today')
    if 'home' in pages:
        return url_for('cs.home')
    return _first_url(user, pages, MODULE_KEYS) or url_for('main.index')


def _first_url(user, pages, module_keys):
    """The first line in the menu, of a page in one of `module_keys`, that this person may open."""
    console = current_console(user)
    for key in MENU_ORDER:
        p = PAGES[key]
        if p['module'] in module_keys and p['nav'] and key in pages:
            url = page_url(p, console)
            if url:
                return url
    return None


def denied_url(user, endpoint):
    """Where somebody turned away from `endpoint` goes: the first thing they may open in the same
    module (a salesperson refused Results lands on My day), else their home."""
    owners = ENDPOINT_PAGES.get(endpoint or '') or ()
    modules = [PAGES[k]['module'] for k in owners]
    return (_first_url(user, pages_for(user), [m for m in MODULE_KEYS if m in modules])
            or home_url(user))


def recipients(*page_keys, limit=20):
    """Active staff who may open any of `page_keys` in any workspace: who should be told about
    something on those screens. Telling somebody about a screen they cannot open is an
    instruction they cannot follow."""
    from sqlalchemy import or_
    from app.models import User, WorkspaceMember
    wanted = set(page_keys)
    member_ids = db.session.query(WorkspaceMember.user_id)
    staff = (User.query.filter(User.is_active.is_(True),
                               or_(User.is_admin.is_(True), User.role.in_(['cs', 'admin']), User.id.in_(member_ids)))
             .order_by(User.id).all())
    out = [u for u in staff if wanted & pages_anywhere(u)]
    return out[:limit] if limit else out


# ---------------------------------------------------------------------- the guard

def guard():
    """before_request: a staff member opening a page their roles do not give them is turned
    back. Travellers are left to each route's own check -- the decorators on the staff blueprints
    refuse them, and the shared routes (a traveller's own matches) have their own rules."""
    from flask import flash, jsonify, redirect
    from flask_login import current_user
    endpoint = request.endpoint
    if not claims(endpoint) or not is_staff(current_user):
        return None
    if allowed(current_user, endpoint):
        return None
    # a page's own fetch() calls get an answer they can show; a form or a link gets the menu back
    if (request.is_json or request.accept_mimetypes.best == 'application/json'
            or request.headers.get('X-Requested-With') == 'XMLHttpRequest'):
        said = [PAGES[k]['deny'] for k in sorted(ENDPOINT_PAGES.get(endpoint, ())) if PAGES[k]['deny']]
        return jsonify({'error': said[0] if said else 'Your role does not include this page.'}), 403
    flash('That part of the console has not been enabled for your account.', 'warning')
    return redirect(denied_url(current_user, endpoint))


# ---------------------------------------------------------------------- changing it

def _slug(name):
    from app.models import Workspace
    base = re.sub(r'[^a-z0-9]+', '-', (name or '').lower()).strip('-')[:50] or 'workspace'
    slug, n = base, 2
    while Workspace.query.filter_by(slug=slug).first():
        slug, n = '%s-%d' % (base, n), n + 1
    return slug


def create_workspace(name, by=None, modules=None, description=None):
    """A workspace with the three roles every one starts with (Administrator, Sales & service and
    Team lead), and its maker as the owner."""
    from app.models import Workspace, WorkspaceRole
    ws = Workspace(name=name.strip()[:120], slug=_slug(name), modules=modules,
                   description=(description or '').strip()[:255] or None,
                   created_by_id=by.id if by else None)
    db.session.add(ws)
    db.session.flush()
    db.session.add(WorkspaceRole(workspace_id=ws.id, name='Administrator', system_key='admin', pages=[],
                                 description='Every page, including team members, teams and roles.'))
    db.session.add(WorkspaceRole(workspace_id=ws.id, name='Sales & service', system_key='cs',
                                 pages=sorted(CS_ROLE_PAGES),
                                 description='The daily work: My day, leads, contacts, WhatsApp chats, quick '
                                             'replies, queues and posts.'))
    db.session.add(WorkspaceRole(workspace_id=ws.id, name='Team lead', system_key=None,
                                 pages=sorted(CS_ROLE_PAGES | TEAM_LEAD_EXTRA),
                                 description='Sales & service, plus Team today, Results, What goes out by itself and Broadcasts.'))
    db.session.flush()
    if by is not None:
        add_member(ws, by, role=system_role(ws, 'admin'), owner=True, by=by, commit=False)
    return ws


def system_role(ws, key):
    return next((r for r in ws.roles if r.system_key == key), None)


def ensure_defaults():
    """The first workspace, written down from how the site already behaves: every admin an
    Administrator (the first one its owner), every CS agent Sales & service -- or a role made
    from the screens an admin had narrowed them to. Safe to call any number of times."""
    from sqlalchemy import or_
    from app.models import User, Workspace, WorkspaceRole, WorkspaceMember
    ws = default_workspace()
    if ws is not None:
        return ws
    try:
        ws = create_workspace('NRI Parent Service')
        staff = (User.query.filter(User.is_active.is_(True),
                                   or_(User.is_admin.is_(True), User.role.in_(['cs', 'admin'])))
                 .order_by(User.id).all())
        owner_given = False
        for u in staff:
            if u.is_admin:
                role = system_role(ws, 'admin')
                owner, owner_given = (not owner_given), True
            elif u.is_cs:
                owner = False
                if u.cs_access is None:
                    role = system_role(ws, 'cs')
                else:
                    pages = sorted(_legacy_pages(u))
                    role = next((r for r in ws.roles if not r.system_key and sorted(r.pages or []) == pages), None)
                    if role is None:
                        labels = [LEGACY_LABELS.get(k, k) for k in u.cs_access if k in LEGACY_SCREEN_PAGES]
                        name = ('Customer service: ' + ', '.join(labels))[:80] if labels else 'No screens'
                        while WorkspaceRole.query.filter_by(workspace_id=ws.id, name=name).first():
                            name = name[:76] + ' +'
                        role = WorkspaceRole(workspace_id=ws.id, name=name, pages=pages,
                                             description='Made from the screens this agent was limited to.')
                        db.session.add(role)
                        db.session.flush()
                        ws.roles.append(role)
            else:
                continue
            db.session.add(WorkspaceMember(workspace_id=ws.id, user_id=u.id, role_id=role.id, is_owner=owner))
        db.session.commit()
    except Exception:          # noqa: BLE001 -- two workers racing to make it: the other one won
        db.session.rollback()
        ws = default_workspace()
    _cache().clear()
    return ws


LEGACY_LABELS = {'home': 'Service to-do', 'notifications': 'Notifications', 'metrics': 'Match quality', 'voices': 'User voices',
                 'posts': 'Posts', 'matches': 'Matches', 'new': 'New post', 'import': 'Import', 'scraper': 'Scraper',
                 'insurance': 'Insurance', 'sahayak': 'Sahayak', 'crm_board': 'Sales'}


def _mark_staff(user, staff):
    """Keep the account-level flag the rest of the site reads (`is_cs`) in step with membership:
    somebody in a workspace is staff wherever the site asks "staff or traveller?"."""
    from app import options
    keys = list(user.role_keys)
    levels = {options.role_level(k) for k in keys}
    if staff and not (levels & {'cs', 'admin'}):
        user.set_roles(keys + ['cs'])
    elif not staff and not user.is_admin:
        kept = [k for k in keys if options.role_level(k) not in ('cs', 'admin')]
        if kept != keys:
            user.set_roles(kept or ['user'])


def add_member(ws, user, role=None, teams=(), owner=False, by=None, commit=True):
    from app.models import WorkspaceMember
    m = WorkspaceMember.query.filter_by(workspace_id=ws.id, user_id=user.id).first()
    if m is None:
        m = WorkspaceMember(workspace_id=ws.id, user_id=user.id, added_by_id=by.id if by else None)
        db.session.add(m)
    m.role_id = role.id if role else None
    m.is_owner = bool(owner or m.is_owner)
    m.user = user
    m.workspace = ws
    set_teams(m, teams)
    _mark_staff(user, True)
    if commit:
        db.session.commit()
    _cache().clear()
    _changed(m)
    return m


def set_teams(member, teams):
    """Exactly these teams of the member's workspace."""
    from app.models import WorkspaceTeam
    wanted = {t.id for t in teams or ()}
    for t in WorkspaceTeam.query.filter_by(workspace_id=member.workspace_id).all():
        inside = member.user in t.users
        if t.id in wanted and not inside:
            t.users.append(member.user)
        elif t.id not in wanted and inside:
            t.users.remove(member.user)


def teams_of(member):
    from app.models import WorkspaceTeam
    return [t for t in WorkspaceTeam.query.filter_by(workspace_id=member.workspace_id).order_by(WorkspaceTeam.name)
            if member.user in t.users]


def remove_member(member, commit=True, hand_over=None, by=None):
    """Out of the workspace and its teams. Never the owner: a workspace without one cannot be
    run. Somebody left in no workspace at all stops being staff. `hand_over` ({'to', 'team'}):
    their open leads and follow-ups go first (crm.hand_over); returns (leads, follow-ups) moved, or
    None without it. A ValueError from the hand-over (nobody to take them) stops the removal."""
    if member.is_owner:
        raise ValueError('The owner cannot be removed from the workspace.')
    user, ws = member.user, member.workspace
    moved = None
    if hand_over is not None:
        from app.services import crm
        moved = crm.hand_over(user, to=hand_over.get('to'), team=hand_over.get('team'), by=by)
    set_teams(member, ())
    _removed(member)
    db.session.delete(member)
    db.session.flush()
    from app.models import WorkspaceMember
    if not WorkspaceMember.query.filter_by(user_id=user.id).count():
        _mark_staff(user, False)
    if commit:
        db.session.commit()
    _cache().clear()
    return moved


def sync_account(user, by=None):
    """After an account's roles change on the Users screen: staff with no workspace join the first
    one (as an Administrator or Sales & service, by their level); somebody who is no longer staff
    leaves every workspace they were in."""
    from app.models import WorkspaceMember
    ws = default_workspace()
    mems = WorkspaceMember.query.filter_by(user_id=user.id).all()
    staff = user.is_admin or user.is_cs
    if staff and not mems and ws is not None:
        add_member(ws, user, role=system_role(ws, 'admin' if user.is_admin else 'cs'), by=by)
    elif not staff:
        for m in mems:
            if not m.is_owner:
                remove_member(m, commit=False)
        db.session.commit()
    _cache().clear()


def clean_pages(keys, keep=()):
    """What to store from the role form: known pages only, in menu order, plus the keys of `keep`
    (what the role held) that a later step reserves -- the form cannot show them, so a save must
    not drop them."""
    wanted = set(keys or [])
    out = [p['key'] for m in MODULES for p in m['pages'] if p['key'] in wanted]
    return out + [k for k in (keep or ()) if k in RESERVED_PAGES and k not in out]


def who_has(ws):
    """{role id: number of members using it directly or through a team}."""
    counts = {}
    for m in ws.members:
        if m.role_id:
            counts[m.role_id] = counts.get(m.role_id, 0) + 1
    for t in ws.teams:
        if t.role_id:
            counts[t.role_id] = counts.get(t.role_id, 0) + len(t.users)
    return counts


# the order "Can open" names pages in: the menu's, with the day's work first and Overview last
_SUMMARY_ORDER = tuple(k for s in SECTIONS if s['key'] != 'overview' for k in s['pages']) + SECTIONS[0]['pages']


def can_open_summary(member, limit=3):
    """"My day, WhatsApp chats, Leads +4": what a member can open, the day's work first. "Every page"
    when that is everything the workspace has on; "Nothing yet" for nobody's pages."""
    within = module_pages(enabled_modules(member.workspace))
    pages = within if (member.user is not None and member.user.is_admin) else _member_pages(member)
    labels = [PAGES[k]['label'] for k in _SUMMARY_ORDER if PAGES[k]['nav'] and k in pages]
    if not labels:
        return 'Nothing yet'
    if pages >= {k for k in within if PAGES[k]['nav']}:
        return 'Every page'
    more = len(labels) - limit
    return ', '.join(labels[:limit]) + (' +%d' % more if more > 0 else '')


# The WhatsApp CRM keeps its own team; these tell it (services/wacrm_team.py, when linked).

def _changed(member):
    try:
        from app.services import wacrm_team
        wacrm_team.member_changed(member)
    except ImportError:
        pass


def _removed(member):
    try:
        from app.services import wacrm_team
        wacrm_team.member_removed(member)
    except ImportError:
        pass

