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
          tip='', with_=(), grant=False):
    """`admin` / `cs`: the endpoint the menu opens in that console (None: not in that console).
    `args`: the query string both links carry -- several menu lines are one screen filtered.
    `lit`: endpoints other pages share that should light THIS line (the lead page is "Leads",
    though My day opens it too). `tip`: the menu line's tooltip; `desc` is what the Roles screen
    says about the page. `with_`: a page nobody grants on its own -- whoever may open any of these
    may open it too (_implied), so it is not on the Roles screen and no stored role needs it --
    unless `grant`: then it comes with them AND can still be given on its own (a menu line that
    gathers tabs: whoever has any tab has the line, and the line was grantable before)."""
    return {'key': key, 'label': label, 'icon': icon, 'endpoints': tuple(endpoints),
            'links': {'admin': admin, 'cs': cs}, 'args': dict(args or {}), 'nav': nav, 'desc': desc,
            'lit': frozenset(lit), 'deny': deny, 'tip': tip, 'with': frozenset(with_), 'grant': bool(grant)}


def _both(*names):
    """A Sales CRM endpoint: the same view is mounted in both consoles."""
    return tuple('crm.' + n for n in names) + tuple('admin_crm.' + n for n in names)


# one inbox seen through different filters: every voices line owns the whole of it
VOICES = ('cs.voices', 'cs.contact_messages', 'cs.contact_status', 'cs.voice_read', 'cs.contact_reply',
          'admin.voices', 'admin.voice_status', 'admin.contact_messages')

# what a salesperson does to a lead, from My day or from the lead itself
CRM_DAILY = _both('lead', 'move', 'route_lead', 'task_action', 'send', 'call', 'note', 'update',
                  'suggest', 'answer_used', 'event', 'lead_money', 'undo', 'reopen', 'remove', 'message', 'live', 'opt_in',
                  'wa_retry', 'snooze_lead', 'bulk', 'find', 'contact', 'contact_edit', 'contact_tags',
                  'task_add', 'task_edit', 'task_delete', 'lead_email', 'lead_email_send',
                  'file_upload', 'file_download', 'file_delete', 'contact_family_add', 'contact_family_role',
                  'contact_family_remove', 'contact_family_rename', 'contact_merge', 'contact_merge_do',
                  'quote_add', 'quote_edit', 'quote_status', 'quote_approve', 'quote_delete', 'payment_add',
                  'payment_status', 'payment_delete', 'view_save', 'view_rename', 'view_delete', 'ai_summary')

MATCHES = ('matches.cs_match_queue', 'matches.cs_matches', 'matches.cs_notify', 'matches.cs_dismiss',
           'matches.cs_connected', 'matches.cs_mark_sent', 'matches.cs_intro_text', 'matches.trip_matches',
           'matches.api_notify', 'matches.api_dismiss', 'matches.cs_read_post')

SCRAPER = tuple('scraper.' + n for n in (
    'recipes', 'new_recipe', 'new_recipe_detect', 'use_source', 'start_teach', 'recipe_form', 'preview_recipe',
    'mapping', 'mapping_preview', 'recipe_runs', 'start_run', 'toggle_recipe', 'run_detail',
    'run_status', 'cancel_run', 'create_posts', 'skip_rows', 'row_detail', 'row_edit', 'export_run',
    'export_recipe'))

# the reports gathered under Overview's one Reports line, as tabs, in this order (TAB_GROUPS['reports'])
REPORT_TABS = (('crm_insights', 'Sales results'), ('crm_forecast', 'Forecast'), ('crm_report_builder', 'Report builder'),
               ('crm_tracker', 'Team today'), ('dashboard', 'Site dashboard'), ('metrics', 'Match quality'))
REPORT_PAGES = tuple(k for k, _ in REPORT_TABS)

MODULES = [
    {'key': 'console', 'label': 'Overview', 'icon': 'fa-gauge',
     'desc': 'Service to-do, notifications and the site dashboard.',
     'pages': [
         # one menu line for every report, All reports (TAB_GROUPS['reports']): whoever may open any of them has
         # it; it opens the first one they may open, and the reports are its tabs
         _page('reports', 'All reports', 'fa-chart-pie', ['admin.reports', 'cs.reports'], admin='admin.reports',
               cs='cs.reports', with_=REPORT_PAGES,
               tip='Every report in one place: sales results, forecast, your own reports, team today, the site '
                   'numbers and match quality.'),
         _page('dashboard', 'Site dashboard', 'fa-gauge', ['admin.dashboard'], admin='admin.dashboard', nav=False,
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
         _page('crm_calendar', 'Calendar', 'fa-calendar-days', _both('calendar'),
               admin='admin_crm.calendar', cs='crm.calendar', with_=('crm_today',),
               desc='Tasks, calls, meetings and follow-ups by day, and a list of what is open.',
               tip='Tasks, calls, meetings, follow-ups and trips, by month or week.'),
         _page('crm_people', 'Contacts', 'fa-address-book',
               _both('contacts', 'contact', 'contact_edit', 'contact_tags', 'find', 'contact_family_add',
                     'contact_family_role', 'contact_family_remove', 'contact_family_rename', 'contact_merge',
                     'contact_merge_do', 'file_upload', 'file_download', 'file_delete', 'view_save', 'view_rename',
                     'view_delete', 'contact_offers') + ('messaging.contacts',),
               admin='admin_crm.contacts', cs='crm.contacts', lit=_both('contact', 'contact_edit'),
               desc='Everyone we can reach, one row per person, and each contact page.',
               tip='Everyone we can reach, one row per person.'),
         _page('crm_flow', 'Visual flow', 'fa-diagram-project', _both('flow', 'flow_find'),
               admin='admin_crm.flow', cs='crm.flow', nav=False, with_=('crm_today', 'crm_board', 'crm_people'),
               tip="Every step from first message to won or lost, where each customer is, and what to do next."),
         _page('crm_add', 'Add a lead', 'fa-user-plus', _both('add', 'add_from_record'),
               admin='admin_crm.add', cs='crm.add', nav=False, desc='The Add a lead button on Leads and My day.'),
         _page('crm_checks', 'Half-hourly check', 'fa-clipboard-check', _both('checks', 'check_tick'),
               admin='admin_crm.checks', cs='crm.checks', nav=False, with_=('crm_today',), grant=True,
               tip='Tick each inbox every half hour; connected ones tick themselves.'),
         _page('crm_process', 'How we sell', 'fa-route', _both('process'),
               admin='admin_crm.process', cs='crm.process', nav=False,
               with_=('crm_today', 'crm_board', 'crm_people'), grant=True,
               tip="Our sales path per product, with today's numbers."),
         _page('crm_quick', 'Messages', 'fa-bolt',
               _both('quick_replies', 'save_answer', 'setup') + ('messaging.quick_replies',),
               admin='admin_crm.quick_replies', cs='crm.quick_replies',
               with_=('wa_templates', 'wa_broadcasts', 'wa_tags'), grant=True,
               tip='Quick replies, WhatsApp templates, broadcasts and tags.'),
         _page('crm_tracker', 'Team today', 'fa-people-line', _both('tracker'), admin='admin_crm.tracker', nav=False,
               desc="Each person's checklist and timeline, day by day.", tip="How each person's day is going."),
         _page('crm_insights', 'Sales results', 'fa-chart-line', _both('insights', 'insights_recalculate') + ('messaging.overview',),
               admin='admin_crm.insights', nav=False,
               tip='New leads, replies and customers won, by product, source and person.'),
         _page('crm_forecast', 'Forecast', 'fa-bullseye', _both('forecast', 'forecast_csv'),
               admin='admin_crm.forecast', cs='crm.forecast', nav=False, with_=('crm_insights',), grant=True,
               desc='Money won against target, and what is committed, for the month.',
               tip='Money won against target, and what is committed, for the month or quarter.'),
         _page('crm_report_builder', 'Report builder', 'fa-chart-column',
               _both('report_builder', 'report_builder_csv', 'report_save', 'report_pin', 'report_move', 'report_delete'),
               admin='admin_crm.report_builder', cs='crm.report_builder', nav=False, with_=('crm_insights',), grant=True,
               desc='Build your own report: what to count, how to group it, a chart and a table to download.',
               tip='Build your own report, save it, and pin it to Sales results.'),
         _page('crm_auto', 'Automation', 'fa-list-check', _both('automatic', 'ai_switch'), admin='admin_crm.automatic',
               with_=('wa_automations', 'wa_flows', 'wa_ai'), grant=True,
               desc='Everything that goes out by itself, in one list, with where to change it.',
               tip='What goes out by itself, reply rules, the chatbot and AI replies.'),
         _page('crm_rules', 'Rules', 'fa-code-branch',
               _both('rules', 'rule_save', 'rule_test', 'rule_toggle', 'rule_delete'), admin='admin_crm.rules',
               nav=False, with_=('crm_auto',),
               desc='Automation rules: when something happens to a lead, do these things (a tab of Automation).',
               tip='When something happens to a lead, do these things by themselves.'),
         _page('crm_pipelines', 'Pipelines & products', 'fa-diagram-project',
               _both('pipelines', 'pipeline_new', 'pipeline_edit', 'pipeline_save', 'pipeline_active',
                     'pipeline_tag_check', 'pipeline_tag', 'tag_check', 'save_product', 'product_offered',
                     'template_draft', 'save_pipeline', 'save_step', 'setup_templates', 'setup', 'save_rates',
                     'scoring_switch', 'scoring_save', 'score_rule_save', 'score_rule_delete'),
               admin='admin_crm.pipelines', tip='Stages and follow-ups for each product.'),
         _page('crm_sources', 'Lead sources', 'fa-door-open',
               _both('sources', 'save_source', 'save_process', 'setup', 'save_inboxes', 'save_activities',
                     'source_tag_check'),
               admin='admin_crm.sources', tip='Forms and channels, who gets their leads, the inboxes to check.'),
         _page('crm_targets', 'Targets', 'fa-bullseye', _both('targets', 'targets_save', 'targets_copy'),
               admin='admin_crm.targets', with_=('crm_tracker',), grant=True,
               desc='What each person and team aims for each month. Comes with Team today: a team lead sets the targets of their teams.',
               tip='What each person and team aims for each month.'),
         _page('crm_connection', 'WhatsApp', 'fa-plug',
               _both('connection', 'save_whatsapp', 'setup', 'connection_checks', 'connection_team',
                     'connection_retry', 'connection_settle', 'quick_replies_push', 'quick_replies_import',
                     'email_sender_save'),
               admin='admin_crm.connection', with_=('wa_settings',), grant=True,
               tip='Is WhatsApp linked, what to fix if not, and the number.'),
         _page('crm_data', 'Import & export', 'fa-file-arrow-up',
               _both('data', 'backfill', 'import_sheet', 'import_confirm', 'setup', 'import_csv',
                     'import_csv_confirm', 'wa_contacts_import', 'wa_notes_import'),
               admin='admin_crm.data', tip='Import lists and old enquiries; download lists.'),
         _page('crm_export', 'Download lists of leads and contacts', 'fa-file-arrow-down', _both('insights_csv', 'insights_people_csv', 'export_leads', 'export_contacts'),
               admin='admin_crm.insights', nav=False,
               desc='Download this list on Leads and Contacts, and the downloads on Import & export.'),
         _page('crm_bin', 'Recycle bin', 'fa-trash-can-arrow-up', _both('bin', 'bin_restore', 'bin_purge'),
               admin='admin_crm.bin', nav=False, with_=('crm_data',),
               desc='Leads that were removed in the last 30 days: put them back, or delete them for good.'),
     ]},
    {'key': 'companion', 'label': 'Travel Companion', 'icon': 'fa-plane-departure',
     'desc': 'Trip posts, matches and everything on the companion site.',
     'pages': [
         _page('posts', 'All posts', 'fa-list',
               ['cs.posts', 'cs.post_detail', 'cs.post_tree', 'cs.edit_post', 'cs.publish_post', 'cs.close_post',
                'cs.reopen_post', 'cs.issue_claim_link', 'cs.log_manual_event', 'cs.check_duplicates'],
               cs='cs.posts'),
         _page('matches', 'Match queue', 'fa-handshake', MATCHES, cs='matches.cs_match_queue'),
         _page('metrics', 'Match quality', 'fa-chart-simple', ['cs.metrics'], cs='cs.metrics', nav=False,
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
         _page('blog', 'New blog post', 'fa-pen', ['admin.new_blog', 'admin.blog_edit', 'admin.blog_check',
                                                  'admin.blog_preview', 'admin.blog_image'],
               admin='admin.new_blog'),
         # Word documents in, draft posts out (services/blog_engine.py): whoever may write a post may
         # import one, so it comes with "New blog post" rather than being granted on its own
         _page('blog_import', 'Import blog posts', 'fa-file-import', ['admin.blog_import', 'admin.blog_template'],
               admin='admin.blog_import', with_=('blog',)),
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
               ['messaging.inbox', 'messaging.lead_panel', 'messaging.lead_panel_make', 'messaging.start_chat_panel',
                'messaging.start_chat'], admin='messaging.inbox',
               cs='messaging.inbox', desc='Every WhatsApp conversation.',
               tip='Every WhatsApp conversation; the lead shows beside the open chat.'),
         _page('wa_templates', 'WhatsApp templates', 'fa-file-lines', ['messaging.templates'],
               nav=False, admin='messaging.templates', cs='messaging.templates',
               desc='Messages WhatsApp has approved. Makes somebody a WhatsApp admin.',
               tip='Messages WhatsApp has approved, for first messages and after 24 hours.'),
         _page('wa_broadcasts', 'Broadcasts', 'fa-bullhorn', ['messaging.broadcasts'],
               nav=False, admin='messaging.broadcasts', cs='messaging.broadcasts', desc='One approved template to many.',
               tip='One approved message to many people.'),
         _page('wa_tags', 'Tags', 'fa-tags', ['messaging.tags'], nav=False, admin='messaging.tags', cs='messaging.tags',
               desc='Makes somebody a WhatsApp admin.',
               tip='Labels on contacts, used to pick who gets a broadcast or a reply rule.'),
         _page('wa_automations', 'Reply rules', 'fa-reply-all', ['messaging.automations'],
               nav=False, admin='messaging.automations', cs='messaging.automations',
               desc='Welcome messages, keywords, out-of-hours and follow-ups.',
               tip='Replies to keywords, first messages and out-of-hours.'),
         _page('wa_flows', 'Chatbot', 'fa-sitemap', ['messaging.flows'], nav=False, admin='messaging.flows',
               cs='messaging.flows', tip='A menu of buttons that answers step by step.'),
         _page('wa_ai', 'AI replies', 'fa-robot', ['messaging.ai'], nav=False, admin='messaging.ai', cs='messaging.ai',
               desc='Makes somebody a WhatsApp admin.', tip='AI answers from the documents you add here.'),
         _page('wa_settings', 'WhatsApp number', 'fa-sim-card', ['messaging.settings'], nav=False, admin='messaging.settings',
               cs='messaging.settings', desc='Makes somebody a WhatsApp admin. Also opens Tags.',
               tip='The number customers write to, and its Meta details.'),
     ]},
    {'key': 'site', 'label': 'Site settings', 'icon': 'fa-gear',
     'desc': 'Accounts, wording, dropdowns, notifications and colours for the whole site.',
     'pages': [
         _page('voices_general', 'Contact us (all services)', 'fa-inbox', VOICES, admin='admin.voices',
               cs='cs.voices', args={'tab': 'contact', 'topic': 'general'}),
         _page('users', 'Users', 'fa-users',
               ['admin.users', 'admin.toggle_user', 'admin.set_user_role', 'admin.set_user_roles', 'admin.new_user',
                'admin.user_panel', 'admin.user_send_reset', 'admin.user_away'],
               admin='admin.users'),
         _page('options', 'Options & dropdowns', 'fa-sliders',
               ['admin.options_page', 'admin.translations_list', 'admin.translations_save', 'admin.save_options',
                'admin.reset_options', 'admin.airports_search', 'admin.airports_add',
                'admin.airlines_search', 'admin.airlines_add'],
               admin='admin.options_page'),
         _page('messages', 'Trip post texts & e-mails', 'fa-envelope-open-text',
               ['admin.messages_page', 'admin.test_email', 'admin.save_message', 'admin.reset_message',
                'admin.save_custom_snippets', 'admin.preview_message'],
               admin='admin.messages_page'),
         _page('notiflog', 'Notification log', 'fa-bell',
               ['admin.notification_log', 'admin.notification_log_send', 'admin.notification_log_read',
                'admin.broadcast'],
               admin='admin.notification_log'),
         _page('notify_switches', 'Notification switches', 'fa-bell-slash', ['admin.notification_switches'],
               admin='admin.notification_switches'),
         _page('themes', 'Colour themes', 'fa-palette', ['admin.themes_page'], admin='admin.themes_page'),
         _page('delete_records', 'Delete records permanently', 'fa-trash-can',
               ['admin.hard_delete', 'admin.hard_delete_bulk', 'admin.delete_user', 'admin.bulk_delete_users',
                'admin.delete_listing', 'admin.bulk_delete_listings', 'crm.contact_erase', 'admin_crm.contact_erase',
                'admin.notification_log_delete', 'admin.notification_log_delete_matching', 'admin.airports_delete',
                'admin.airlines_delete', 'scraper.delete_recipe'],
               nav=False, desc=('The bin buttons on every list, and Erase this person on a contact page. '
                                'Nothing deleted this way can be brought back. Super admins only.'),
               deny='Only a Super admin can delete this.'),
     ]},
    {'key': 'workspace', 'label': 'Team', 'icon': 'fa-people-group', 'required': True,
     'desc': 'Team members, teams, roles and the areas this workspace uses.',
     'pages': [
         _page('ws_settings', 'Workspace', 'fa-building',
               ['workspace.overview', 'workspace.save_settings', 'workspace.whatsapp'],
               admin='workspace.overview', tip='Business name and the areas you use.'),
         _page('ws_members', 'Team members', 'fa-user-gear',
               ['workspace.members', 'workspace.add_member', 'workspace.member_search', 'workspace.member',
                'workspace.save_member', 'workspace.remove_member', 'admin.cs_agents', 'admin.cs_screen_access'],
               admin='workspace.members', tip='Who works here, their role and teams.'),
         _page('ws_teams', 'Teams', 'fa-people-group',
               ['workspace.teams', 'workspace.team', 'workspace.save_team', 'workspace.delete_team'],
               admin='workspace.teams', tip='Groups of people who share a role.'),
         _page('ws_roles', 'Roles', 'fa-user-lock',
               ['workspace.roles', 'workspace.role', 'workspace.save_role', 'workspace.delete_role'],
               admin='workspace.roles', tip='What each kind of job can open.'),
         _page('ws_menu', 'Menu builder', 'fa-bars-staggered',
               ['workspace.menu', 'workspace.save_menu', 'workspace.reset_menu', 'workspace.menu_preview'],
               admin='workspace.menu', desc='Arrange the staff menu: sections, sub-menus, order and names.',
               tip='Arrange the menu: sections, sub-menus, order and names. Roles decide who sees each line.'),
         _page('ws_all', 'All workspaces', 'fa-layer-group',
               ['workspace.all_workspaces', 'workspace.create_workspace', 'workspace.new_workspace'],
               admin='workspace.all_workspaces',
               nav=False, desc='Make new workspaces (a tab on Workspace).'),
     ]},
]

# The menu, in order: one heading per area, each with its pages in this order -- or, for a big area,
# `subs`: sub-menus that fold again, each with its pages. Every dashboard and report sits in Overview,
# whatever it is about, so the numbers are in one place. A page's area (its module above) still decides
# whether the workspace has it switched on; the section only decides where its line sits. The one place
# the menu's order lives.
SECTIONS = [
    {'key': 'overview', 'label': 'Overview', 'icon': 'fa-gauge',
     'pages': ('reports', 'dashboard', 'crm_insights', 'crm_forecast', 'crm_report_builder', 'crm_tracker', 'metrics', 'home',
               'notifications', 'voices_general')},
    {'key': 'sales', 'label': 'Sales CRM', 'icon': 'fa-filter-circle-dollar', 'subs': (
        # pages with no line of their own (nav=False) are tabs of a line next to them: TAB_GROUPS
        {'key': 'daily', 'label': 'Daily work', 'icon': 'fa-sun',
         'pages': ('crm_today', 'wa_inbox', 'crm_board', 'crm_calendar', 'crm_people', 'crm_add', 'crm_checks', 'crm_flow',
                   'crm_process')},
        {'key': 'setup', 'label': 'Set-up', 'icon': 'fa-sliders',
         'pages': ('crm_pipelines', 'crm_auto', 'crm_rules', 'crm_quick', 'crm_sources', 'crm_targets', 'crm_connection', 'crm_data',
                   'crm_export', 'crm_bin', 'wa_templates', 'wa_broadcasts', 'wa_tags', 'wa_automations', 'wa_flows',
                   'wa_ai', 'wa_settings')},
    )},
    {'key': 'companion', 'label': 'Travel Companion', 'icon': 'fa-plane-departure', 'subs': (
        {'key': 'posts', 'label': 'Posts & matches', 'icon': 'fa-list',
         'pages': ('posts', 'matches', 'new', 'import', 'scraper', 'listings')},
        {'key': 'voices', 'label': 'Inbox', 'icon': 'fa-envelope',
         'pages': ('voices_contact', 'voices_feedback', 'voices_report')},
        {'key': 'website', 'label': 'Website', 'icon': 'fa-globe', 'pages': ('landing', 'blog_list', 'blog', 'blog_import', 'help')},
    )},
    {'key': 'insurance', 'label': 'Travel Insurance', 'icon': 'fa-shield-heart',
     'pages': ('insurance', 'voices_insurance', 'insurance_page', 'help_insurance')},
    {'key': 'sahayak', 'label': 'Sahayak', 'icon': 'fa-house-medical',
     'pages': ('sahayak', 'voices_sahayak', 'sahayak_services', 'help_sahayak')},
    {'key': 'team', 'label': 'Team', 'icon': 'fa-users',
     'pages': ('ws_members', 'ws_teams', 'ws_roles', 'ws_menu', 'ws_settings', 'ws_all')},
    {'key': 'site', 'label': 'Site settings', 'icon': 'fa-gear',
     'pages': ('users', 'options', 'messages', 'notiflog', 'notify_switches', 'themes', 'delete_records')},
]
for _s in SECTIONS:
    if 'subs' in _s:
        _s['pages'] = tuple(k for sub in _s['subs'] for k in sub['pages'])

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
    for _sub in _s.get('subs', ()):
        for _k in _sub['pages']:
            PAGES[_k]['sub'] = _sub['key']
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

# Menu lines that gather other screens as TABS: the line's page first, then the pages that have no line of
# their own (nav=False). Each tab is (page key, tab name); the strip (templates/cs/crm/_tabs.html) shows the
# ones this person may open. Leads is not here: its Board / List / Flow / How we sell are a view switch.
TAB_GROUPS = {
    'crm_quick': (('crm_quick', 'Quick replies'), ('wa_templates', 'WhatsApp templates'),
                  ('wa_broadcasts', 'Broadcasts'), ('wa_tags', 'Tags')),
    'crm_auto': (('crm_auto', 'Overview'), ('crm_rules', 'Rules'), ('wa_automations', 'Reply rules'),
                 ('wa_flows', 'Chatbot'), ('wa_ai', 'AI replies')),
    'crm_connection': (('crm_connection', 'Connection'), ('wa_settings', 'Number')),
    # every report is a tab of Overview's Reports line (the line itself has no screen: it opens the first tab)
    'reports': REPORT_TABS,
}
# the menu line a nav=False page lives under (the line that lights up while it is open)
TAB_HOST = {k: host for host, tabs in TAB_GROUPS.items() for k, _ in tabs if k != host}
TAB_HOST.update({'crm_flow': 'crm_board', 'crm_process': 'crm_board', 'crm_checks': 'crm_today', 'crm_bin': 'crm_data'})
# Pages that can be given on their own AND lost their menu line: somebody who has only that page still sees the
# line it moved under, opening that page (nothing is taken away from a role that held it).
LINE_VIA = {'crm_board': ('crm_process',), 'crm_today': ('crm_checks',),
            'crm_quick': ('wa_templates', 'wa_broadcasts', 'wa_tags'),
            'crm_auto': ('wa_automations', 'wa_flows', 'wa_ai'), 'crm_connection': ('wa_settings',)}


def tabs_for(page_key, user=None):
    """The tab strip for the page `page_key` (the line's own page or one of its tabs) for this person:
    [{'key', 'label', 'url', 'active'}] -- only the pages they may open, and [] when it would be a strip of one."""
    from flask_login import current_user
    user = user or current_user
    host = TAB_HOST.get(page_key, page_key)
    out = []
    for key, label, url in _open_tabs(host, user):
        links = PAGES[key]['links']
        out.append({'key': key, 'label': label, 'url': url,
                    'active': request.endpoint in (links['admin'], links['cs'])})
    return out if len(out) > 1 else []


def _open_tabs(host, user):
    """(key, tab name, address) of each tab of `host` this person may open, whose area is switched on in the
    workspace (as the menu hides a line whose area is off)."""
    on = set(enabled_modules(current_workspace(user)))
    for key, label in TAB_GROUPS.get(host, ()):
        if PAGES[key]['module'] not in on or not can(user, key):
            continue
        url = page_url(PAGES[key])
        if url:
            yield key, label, url


def first_tab_url(host, user=None):
    """Where a line that gathers tabs and has no screen of its own (Reports) opens: its first tab this person
    may open, or None."""
    from flask_login import current_user
    return next((url for _k, _l, url in _open_tabs(host, user or current_user)), None)


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
TEAM_LEAD_EXTRA = frozenset({'crm_tracker', 'crm_insights', 'crm_forecast', 'crm_report_builder', 'crm_targets', 'crm_auto', 'wa_broadcasts'})
# Deleting for good belongs to the Super admin account role (Users screen), whatever any workspace role says:
# these pages are taken out of every role -- Administrator too -- and given to Super admins alone.
SUPER_ROLE = 'superadmin'
SUPER_ONLY = frozenset({'delete_records'})
# the role somebody chose to work as (header menu), by id; none = everything they have
ACT_KEY = 'act_role'


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


IMPLIED_PAGES = {k: p['with'] for k, p in PAGES.items() if p['with']}


def _implied(pages):
    """`pages` plus every page that comes with one of them (_page's `with_`)."""
    extra = {k for k, needs in IMPLIED_PAGES.items() if pages & needs}
    return frozenset(pages | extra) if extra - pages else pages


def _legacy_pages(user):
    if user.is_admin:
        return ALL_PAGES
    if not user.is_cs:
        return frozenset()
    keys = getattr(user, 'cs_access', None)
    if keys is None:
        return _implied(CS_DEFAULT_PAGES)
    return _implied(frozenset(p for k in keys for p in LEGACY_SCREEN_PAGES.get(k, ())))


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
        return within - SUPER_ONLY
    pages = set(role_pages(member.role))
    for t in _teams(member):
        pages |= role_pages(t.role)
    return _implied(frozenset(pages) & within) - SUPER_ONLY


def _teams(member):
    """The teams of the member's workspace they are in (one query)."""
    from app.models import WorkspaceTeam, workspace_team_members
    return (WorkspaceTeam.query.join(workspace_team_members, workspace_team_members.c.team_id == WorkspaceTeam.id)
            .filter(WorkspaceTeam.workspace_id == member.workspace_id,
                    workspace_team_members.c.user_id == member.user_id).all())


def is_super(user):
    """A Super admin: the only people who delete for good."""
    return _authed(user) and SUPER_ROLE in (user.role_keys or ())


def _super(user, pages):
    return (pages | SUPER_ONLY) if is_super(user) else (pages - SUPER_ONLY)


def _role_only(role):
    """Exactly one role's pages in its workspace (somebody working as it): never a Super admin's."""
    return _implied(role_pages(role) & module_pages(enabled_modules(role.workspace))) - SUPER_ONLY


def pages_for(user, ws=None):
    """The page keys this person may open in `ws` (default: the current workspace). Somebody working as one
    of their roles (acting_role) gets just that role's pages."""
    if not _authed(user):
        return frozenset()
    act = acting_role(user)
    if act is not None and (ws is None or ws.id == act.workspace_id):
        return _role_only(act)
    if user.is_admin:
        return _super(user, ALL_PAGES)
    mems = memberships(user)
    if not mems:
        return _super(user, _legacy_pages(user))
    ws = ws or current_workspace(user)
    if ws is None:
        return frozenset()
    c = _cache()
    key = ('p', user.id, ws.id)
    if key not in c:
        m = next((m for m in mems if m.workspace_id == ws.id), None)
        c[key] = _member_pages(m) if m else frozenset()
    return _super(user, c[key])


def pages_anywhere(user):
    """Everything this person may open in any of their workspaces -- for "who should hear about
    this", where the answer cannot depend on which workspace they happen to have open (nor on the
    role they are working as just now)."""
    if not _authed(user):
        return frozenset()
    if user.is_admin:
        return _super(user, ALL_PAGES)
    mems = memberships(user)
    if not mems:
        return _super(user, _legacy_pages(user))
    out = set()
    for m in mems:
        out |= _member_pages(m)
    return _super(user, frozenset(out))


def roles_to_act(user):
    """The roles somebody can work as in their current workspace: a site admin or the owner any of them,
    anybody else their own role and their teams' roles -- only when that is more than one, since with one
    there is nothing to switch to."""
    if not _authed(user):
        return []
    c = _cache()
    key = ('can_act', user.id)
    if key in c:
        return c[key]
    ws = current_workspace(user)
    m = next((m for m in memberships(user) if m.workspace_id == ws.id), None) if ws is not None else None
    if ws is None:
        roles = []
    elif user.is_admin or (m is not None and m.is_owner):
        roles = list(ws.roles)
    elif m is None:
        roles = []
    else:
        roles = [m.role] if m.role else []
        for t in _teams(m):
            if t.role is not None and t.role not in roles:
                roles.append(t.role)
        roles = roles if len(roles) > 1 else []
    c[key] = roles
    return roles


def acting_role(user):
    """The role this person chose to work as (header menu), or None for everything they have. A choice that
    no longer fits -- another workspace, a role taken away -- is simply not used."""
    if not has_request_context() or not _authed(user):
        return None
    rid = session.get(ACT_KEY)
    if not rid:
        return None
    c = _cache()
    key = ('act', user.id)
    if key not in c:
        c[key] = next((r for r in roles_to_act(user) if r.id == rid), None)
    return c[key]


def act_as(role):
    """Work as `role` from the next page on; None goes back to everything."""
    if has_request_context():
        if role is None:
            session.pop(ACT_KEY, None)
        else:
            session[ACT_KEY] = role.id
        _cache().clear()


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
    if acting_role(user) is not None:          # working as one role: nothing else of theirs counts
        return False
    for m in memberships(user):
        if owners & _super(user, _member_pages(m)):
            set_current_workspace(m.workspace)
            return True
    return False


# --------------------------------------------------------------------------- the menu

def current_console(user=None):
    """Which console's copy a menu link should open. Only site admins live in /admin; everybody
    else stays in /cs and reaches an admin-only screen there when their role gives them one -- a
    site admin working as another role too, so they see that role's screens as its people do."""
    if user is not None and _authed(user):
        act = acting_role(user)
        if not user.is_admin or (act is not None and act.system_key != 'admin'):
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
    owners = {TAB_HOST.get(k, k) for k in owners} | owners          # a tab lights its menu line
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


# The menu's layout: SECTIONS is the default; a workspace's Menu builder may save its own (Workspace.menu) --
# other sections, another order, lines moved, renamed or hidden. Only where a line SITS changes: whether
# somebody sees it is still their roles (pages_for), and where a refused person lands still follows the
# order in code (denied_url, _first_url), so tidying the menu cannot change anybody's way in.
MENU_PAGES = tuple(k for k in MENU_ORDER if PAGES[k]['nav'])
MENU_ICON = re.compile(r'^fa-[a-z0-9-]{1,40}$')
MENU_LABEL_MAX = 40
# what the builder offers for a section or a sub-menu
MENU_ICONS = ('fa-gauge', 'fa-filter-circle-dollar', 'fa-sun', 'fa-comments', 'fa-wand-magic-sparkles', 'fa-sliders',
              'fa-plane-departure', 'fa-shield-heart', 'fa-house-medical', 'fa-users', 'fa-gear', 'fa-circle-question',
              'fa-chart-line', 'fa-list', 'fa-envelope', 'fa-globe', 'fa-inbox', 'fa-star', 'fa-bolt', 'fa-briefcase',
              'fa-folder', 'fa-folder-open', 'fa-layer-group', 'fa-bullhorn', 'fa-diagram-project', 'fa-book-open')


def default_layout():
    """The menu in code, in the shape the builder saves (lines that are buttons, not menu lines, left out)."""
    sections = []
    for s in SECTIONS:
        sec = {'key': s['key'], 'label': s['label'], 'icon': s['icon']}
        if 'subs' in s:
            sec['subs'] = [{'key': b['key'], 'label': b['label'], 'icon': b['icon'],
                            'pages': [k for k in b['pages'] if PAGES[k]['nav']]} for b in s['subs']]
        else:
            sec['pages'] = [k for k in s['pages'] if PAGES[k]['nav']]
        sections.append(sec)
    return {'sections': sections, 'labels': {}, 'hidden': []}


def _had_lines(section):
    """Did this saved section list any menu line at all (in itself or in a sub-menu)?"""
    lists = [section.get('pages')] + [b.get('pages') for b in section.get('subs') or () if isinstance(b, dict)]
    return any(isinstance(v, list) and v for v in lists)


def clean_layout(raw):
    """A layout from the builder (or the database) made safe and whole: every menu line exactly once -- one it
    does not place (a screen added since it was saved) goes back to its section in code -- names and icons
    within bounds, unknown pages dropped. None when there is nothing to read."""
    if not isinstance(raw, dict) or not isinstance(raw.get('sections'), list):
        return None
    seen, sections, taken = set(), [], set()

    def text(v, default):
        return ' '.join(str(v or '').split())[:MENU_LABEL_MAX] or default

    def icon(v, default):
        v = str(v or '').strip()
        return v if MENU_ICON.match(v) else default

    def key_of(v, keys):
        base = re.sub(r'[^a-z0-9_]', '', str(v or '').lower())[:30] or 'section'
        k, n = base, 2
        while k in keys:
            k, n = '%s%d' % (base, n), n + 1
        keys.add(k)
        return k

    def lines(v):
        out = []
        for k in v if isinstance(v, list) else ():
            if isinstance(k, str) and k in PAGES and PAGES[k]['nav'] and k not in seen:
                seen.add(k)
                out.append(k)
        return out

    for s in raw['sections'][:40]:
        if not isinstance(s, dict):
            continue
        before = len(seen)
        sec = {'key': key_of(s.get('key'), taken), 'label': text(s.get('label'), 'Menu'),
               'icon': icon(s.get('icon'), 'fa-folder')}
        subs = [b for b in s.get('subs') or () if isinstance(b, dict)] if isinstance(s.get('subs'), list) else []
        if subs:
            sub_keys = set()
            sec['subs'] = [{'key': key_of(b.get('key'), sub_keys), 'label': text(b.get('label'), 'Sub-menu'),
                            'icon': icon(b.get('icon'), 'fa-folder-open'), 'pages': lines(b.get('pages'))}
                           for b in subs[:20]]
        else:
            sec['pages'] = lines(s.get('pages'))
        # a section whose lines have all gone since it was saved (the old Help section: its screens became
        # tabs) goes with them; one the builder made empty on purpose has nothing listed and stays
        if len(seen) == before and _had_lines(s):
            taken.discard(sec['key'])
            continue
        sections.append(sec)
    restored = []
    for k in MENU_PAGES:
        if k in seen:
            continue
        home = PAGES[k]['section']
        sec = next((s for s in sections if s['key'] == home), None)
        if sec is None:           # its whole section is missing: back as it is in code, sub-menus and all
            d = SECTION_BY_KEY[home]
            sec = {'key': key_of(home, taken), 'label': d['label'], 'icon': d['icon']}
            if 'subs' in d:
                sec['subs'] = [{'key': b['key'], 'label': b['label'], 'icon': b['icon'], 'pages': []} for b in d['subs']]
            else:
                sec['pages'] = []
            sections.append(sec)
            restored.append(sec)
        if 'subs' in sec:
            sub = next((b for b in sec['subs'] if b['key'] == PAGES[k].get('sub')), sec['subs'][-1])
            sub['pages'].append(k)
        else:
            sec['pages'].append(k)
        seen.add(k)
    for sec in restored:
        if 'subs' in sec:
            sec['subs'] = [b for b in sec['subs'] if b['pages']]
    names = raw.get('labels') if isinstance(raw.get('labels'), dict) else {}
    labels = {k: text(v, '') for k, v in names.items()
              if k in seen and text(v, '') and text(v, '') != PAGES[k]['label']}
    hidden = sorted({k for k in raw.get('hidden') or () if isinstance(k, str) and k in seen}) \
        if isinstance(raw.get('hidden'), list) else []
    return {'sections': sections, 'labels': labels, 'hidden': hidden}


def menu_layout(ws):
    """The menu `ws` uses: what its Menu builder saved (made whole), else the menu in code."""
    if ws is None or not ws.menu:
        return default_layout()
    c = _cache()
    key = ('menu', ws.id)
    if key not in c:
        c[key] = clean_layout(ws.menu) or default_layout()
    return c[key]


def _menu(layout, allowed_pages, on, here, console):
    from app.services.nav_badges import MARKS
    names, hidden = layout['labels'], set(layout['hidden'])

    def line(key):
        p = PAGES[key]
        if not p['nav'] or key in hidden or p['module'] not in on:
            return None
        if key in allowed_pages:
            url = page_url(p, console)
        else:          # only a page that moved under this line: the line opens that page
            via = next((v for v in LINE_VIA.get(key, ()) if v in allowed_pages), None)
            if via is None:
                return None
            url = page_url(PAGES[via], console)
        if not url:
            return None
        return {'key': key, 'label': names.get(key, p['label']), 'icon': p['icon'], 'tip': p['tip'] or p['label'],
                'url': url, 'active': key == here, 'badge': key, 'mark': key in MARKS, 'sum': key not in MARKS}

    groups = []
    for sec in layout['sections']:
        subs = []
        for sub in sec.get('subs') or ():
            got = [i for i in map(line, sub['pages']) if i]
            if got:
                subs.append({'key': '%s.%s' % (sec['key'], sub['key']), 'label': sub['label'], 'icon': sub['icon'],
                             'items': got, 'open': any(i['active'] for i in got)})
        items = [i for s in subs for i in s['items']] if 'subs' in sec else \
            [i for i in map(line, sec['pages']) if i]
        if not items:
            continue
        # the customers waiting are in My day's number too: the section's total counts them once
        if any(i['key'] == 'crm_today' for i in items):
            for i in items:
                if i['key'] == 'wa_inbox':
                    i['sum'] = False
        groups.append({'key': sec['key'], 'label': sec['label'], 'icon': sec['icon'], 'items': items,
                       'subs': subs if len(subs) > 1 else [], 'open': any(i['active'] for i in items)})
    # a short menu is shown whole; a long one opens only the section being worked in (the rest are
    # one click away, and the menu remembers what was opened)
    if sum(len(gr['items']) for gr in groups) <= 12:
        for gr in groups:
            gr['open'] = True
            for s in gr['subs']:
                s['open'] = True
    return groups


def nav(user, fallback_active=None):
    """The staff menu: the workspace's layout (menu_layout) in order, each section with the pages this
    person may open whose area is switched on in this workspace, the one being looked at marked. A
    section with nothing in it for them is left out. `mark`: the line's badge is a "!"
    (services/nav_badges.MARKS); `sum`: its number counts in the section's total. `subs`: a section's
    sub-menus that have lines for them -- none when only one would (a sub-heading over everything they
    have is one click too many); `items` always lists every line of the section."""
    ws = current_workspace(user)
    return _menu(menu_layout(ws), pages_for(user, ws), set(enabled_modules(ws)), active_page(fallback_active),
                 current_console(user))


def menu_for_role(ws, role, layout):
    """The menu somebody whose only role is `role` would see with `layout` (the Menu builder's preview)."""
    on = set(enabled_modules(ws))
    admin = role is not None and role.system_key == 'admin'
    pages = _role_only(role) if role is not None else frozenset()
    return _menu(layout, pages, on, None, 'admin' if admin else 'cs')


def home_url(user):
    """Where a staff account lands: site owners on Results (the site dashboard when Sales is off),
    people who work leads on My day, customer service on Service to-do, anybody else on the first
    page in the menu their roles give them."""
    act = acting_role(user)
    if user.is_admin and (act is None or act.system_key == 'admin'):          # a site owner
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
    from app.services import crm_scope
    crm_scope.forget()             # the CRM's list of workspaces (per request) has one more
    db.session.add(WorkspaceRole(workspace_id=ws.id, name='Administrator', system_key='admin', pages=[],
                                 description='Every page, including team members, teams and roles.'))
    db.session.add(WorkspaceRole(workspace_id=ws.id, name='Sales & service', system_key='cs',
                                 pages=sorted(CS_ROLE_PAGES),
                                 description='The daily work: My day, leads, contacts, WhatsApp chats, quick '
                                             'replies, queues and posts.'))
    db.session.add(WorkspaceRole(workspace_id=ws.id, name='Team lead', system_key=None,
                                 pages=sorted(CS_ROLE_PAGES | TEAM_LEAD_EXTRA),
                                 description='Sales & service, plus Team today, Results, Automation and Broadcasts.'))
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
            if owner and not any(s.is_super for s in staff):     # somebody must be able to delete for good
                u.set_roles(u.role_keys + [SUPER_ROLE])
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
    out = [p['key'] for m in MODULES for p in m['pages']
           if p['key'] in wanted and (not p['with'] or p['grant']) and p['key'] not in SUPER_ONLY]
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

