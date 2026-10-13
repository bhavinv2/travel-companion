"""The CS console's screen keys, read through workspace roles (services/access.py).

This used to be the access list itself: a per-agent `cs_access` column naming the console screens
an admin had left them. Who opens what now comes from workspace roles, which cover every page on
the site rather than the console's twelve, and `cs_access` survives only as history -- the first
workspace turned each distinct list into a role (access.ensure_defaults), and an agent nobody has
put in a workspace yet is still read by it.

The screen keys stay because a lot of the site asks in their terms ("who can open the voices
inbox?" for a notification, "may this agent see the Import link?" in the navbar). Each key maps
onto the pages that replaced it (access.LEGACY_SCREEN_PAGES), so those questions now get the
roles' answer.
"""

# key, label, site, and every endpoint that screen owns.
SCREENS = [
    # --- the console itself; everybody needs a way in and a way to see their own work
    {'key': 'home', 'label': 'Queues', 'icon': 'fa-inbox', 'site': 'console',
     'endpoints': ['cs.home']},
    {'key': 'notifications', 'label': 'Notifications', 'icon': 'fa-bell', 'site': 'console',
     'endpoints': ['cs.notifications', 'cs.notifications_read', 'cs.notifications_send']},
    {'key': 'metrics', 'label': 'Metrics', 'icon': 'fa-chart-simple', 'site': 'console',
     'endpoints': ['cs.metrics']},
    {'key': 'voices', 'label': 'User voices', 'icon': 'fa-comment-dots', 'site': 'console',
     'endpoints': ['cs.voices', 'cs.contact_messages', 'cs.contact_status',
                   'cs.feedback_action', 'cs.report_action', 'cs.voice_read']},

    # --- travel companion
    {'key': 'posts', 'label': 'All posts', 'icon': 'fa-list', 'site': 'companion',
     'endpoints': ['cs.posts', 'cs.post_detail', 'cs.post_tree', 'cs.edit_post',
                   'cs.publish_post', 'cs.close_post', 'cs.reopen_post',
                   'cs.issue_claim_link', 'cs.log_manual_event']},
    {'key': 'matches', 'label': 'Match queue', 'icon': 'fa-handshake', 'site': 'companion',
     'endpoints': ['matches.cs_match_queue', 'matches.cs_matches', 'matches.cs_notify',
                   'matches.cs_dismiss', 'matches.cs_connected', 'matches.cs_mark_sent',
                   'matches.cs_intro_text', 'matches.trip_matches', 'matches.api_notify',
                   'matches.api_dismiss', 'matches.cs_read_post']},
    {'key': 'new', 'label': 'New post', 'icon': 'fa-plus', 'site': 'companion',
     'endpoints': ['cs.new_post']},
    {'key': 'import', 'label': 'Import', 'icon': 'fa-file-import', 'site': 'companion',
     'endpoints': ['imports.import_page', 'imports.import_template']},
    # Admin-only before this feature existed, and still is: granting it by default would hand
    # every CS agent a tool they have never had. An admin can tick it on for someone who needs it.
    {'key': 'scraper', 'label': 'Scraper', 'icon': 'fa-spider', 'site': 'companion',
     'admin_only': True,
     'endpoints': ['scraper.recipes', 'scraper.recipe_form', 'scraper.new_recipe',
                   'scraper.new_recipe_detect', 'scraper.preview_recipe', 'scraper.delete_recipe',
                   'scraper.toggle_recipe', 'scraper.export_recipe', 'scraper.use_source',
                   'scraper.mapping', 'scraper.mapping_preview', 'scraper.recipe_runs',
                   'scraper.run_detail', 'scraper.run_status', 'scraper.start_run',
                   'scraper.cancel_run', 'scraper.export_run', 'scraper.row_detail',
                   'scraper.row_edit', 'scraper.skip_rows', 'scraper.create_posts',
                   'scraper.start_teach', 'jobs.run_jobs']},

    # --- travel insurance
    {'key': 'insurance', 'label': 'Insurance leads', 'icon': 'fa-shield-heart', 'site': 'insurance',
     'endpoints': ['cs.insurance_quotes']},

    # --- sahayak
    {'key': 'sahayak', 'label': 'Sahayak queue', 'icon': 'fa-house-medical', 'site': 'sahayak',
     'endpoints': ['cs.sahayak_bookings', 'cs.sahayak_update']},

    # --- sales CRM: the day's work. The set-up, imports, dashboard and daily tracker are the
    # admin's and live in the admin portal (routes/crm.py MANAGE), so they are not offered here.
    {'key': 'crm_board', 'label': 'My sales day', 'icon': 'fa-filter-circle-dollar', 'site': 'crm',
     'endpoints': ['crm.today', 'crm.board', 'crm.lead', 'crm.move', 'crm.route_lead',
                   'crm.task_action', 'crm.send', 'crm.call', 'crm.note', 'crm.update',
                   'crm.suggest', 'crm.answer_used', 'crm.add', 'crm.checks', 'crm.check_tick', 'crm.event',
                   'crm.whatsapp_thread', 'crm.process', 'crm.add_from_record', 'crm.undo', 'crm.reopen',
                   'crm.remove', 'crm.log_work']},
]

SITES = [
    ('console', 'Console', 'fa-gauge'),
    ('companion', 'Travel Companion', 'fa-plane-departure'),
    ('insurance', 'Travel Insurance', 'fa-shield-heart'),
    ('sahayak', 'Sahayak', 'fa-house-medical'),
    ('crm', 'Sales CRM', 'fa-filter-circle-dollar'),
]

ALL_KEYS = [s['key'] for s in SCREENS]

# endpoint -> screen key, built once
_OWNER = {ep: s['key'] for s in SCREENS for ep in s['endpoints']}


def applies_to(user):
    """Whether limits mean anything for this person: signed-in staff who are not site admins."""
    from app.services import access
    return bool(access.is_staff(user) and not getattr(user, 'is_admin', False))


def allowed_keys(user):
    """The screens this agent may open; None when nobody has narrowed them -- every screen but
    the admin-only ones (the scraper), which is what an agent has always had by default."""
    if not applies_to(user):
        return None
    keys = [s['key'] for s in SCREENS if can_open(user, s['key'])]
    usual = [s['key'] for s in SCREENS if not s.get('admin_only')]
    return None if set(usual) <= set(keys) else keys


def can_open(user, screen_key):
    from app.services import access
    pages = access.LEGACY_SCREEN_PAGES.get(screen_key, ())
    mine = access.pages_for(user)
    return any(p in mine for p in pages)


def can_open_endpoint(user, endpoint):
    from app.services import access
    return access.allowed(user, endpoint)


def site_for_endpoint(endpoint):
    """Which product an endpoint belongs to."""
    key = _OWNER.get(endpoint or '')
    if not key:
        return None
    return next((s['site'] for s in SCREENS if s['key'] == key), None)


def screens_for(user):
    """The console screens this person may open, in declaration order."""
    return [s for s in SCREENS if can_open(user, s['key'])]


def sites_for(user):
    """(key, label, icon, screens) for each site this person has anything in."""
    visible = screens_for(user)
    out = []
    for key, label, icon in SITES:
        items = [s for s in visible if s['site'] == key]
        if items:
            out.append({'key': key, 'label': label, 'icon': icon, 'items': items})
    return out


def recipients(*screen_keys, limit=20):
    """Active staff who should hear about something on one of `screen_keys`: whoever's roles, in
    any of their workspaces, open one of the pages that replaced those screens. A notification is
    an instruction to go and look; sending it to somebody whose roles cannot open the page is an
    instruction they cannot follow, and it buries the ones they can act on."""
    from app.services import access
    pages = [p for k in screen_keys for p in access.LEGACY_SCREEN_PAGES.get(k, (k,))]
    return access.recipients(*pages, limit=limit)


def clean(keys):
    """What to store from a form: known keys only, in declaration order so the column reads the
    way the screen does."""
    chosen = set(keys or [])
    return [k for k in ALL_KEYS if k in chosen]
