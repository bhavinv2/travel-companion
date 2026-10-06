"""Which CS console screens an agent may open.

The console covers three separate products plus its own tools, and not every agent works on all
of them. This lets an admin narrow one agent to the screens they actually use -- the insurance
desk does not need the scraper, and whoever answers Sahayak bookings does not need the match
queue.

Two decisions shape everything here:

  * An agent is UNRESTRICTED until somebody says otherwise. `user.cs_access` is null for everyone
    today and for every new hire, and null means "all of it". Nothing changes for anybody when
    this ships, and a new agent can start work before an admin has got round to them.
  * This grants SCREENS, not rows. An agent without insurance cannot open the insurance screens,
    by menu or by typing the URL. The shared inboxes still show everything they always did.
    Filtering the data too would mean auditing every shared query, and a half-filtered list is
    worse than an honest one.

Admins are never restricted. Scoping an admin is a different conversation and a different set of
mistakes; `applies_to` says so in one place rather than at every call site.

Sub-routes matter as much as the menu entry. "All posts" is not one endpoint -- it is the list,
the detail page, the editor, publish, close, reopen and the rest -- so a screen owns a set of
endpoints and the guard checks membership. An endpoint nobody claimed is allowed: a new route
should not silently disappear for restricted agents before anyone notices.
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
]

SITES = [
    ('console', 'Console', 'fa-gauge'),
    ('companion', 'Travel Companion', 'fa-plane-departure'),
    ('insurance', 'Travel Insurance', 'fa-shield-heart'),
    ('sahayak', 'Sahayak', 'fa-house-medical'),
]

ALL_KEYS = [s['key'] for s in SCREENS]

# endpoint -> screen key, built once
_OWNER = {ep: s['key'] for s in SCREENS for ep in s['endpoints']}


def applies_to(user):
    """Whether these limits mean anything for this person.

    Only signed-in CS agents who are not admins. An admin sees everything, and saying that here
    keeps the rule in one place instead of at every call site.
    """
    return bool(user and getattr(user, 'is_authenticated', False)
                and getattr(user, 'is_cs', False) and not getattr(user, 'is_admin', False))


def allowed_keys(user):
    """The screens this agent may open. None means unrestricted, which is the default."""
    if not applies_to(user):
        return None
    raw = getattr(user, 'cs_access', None)
    if raw is None:
        return None
    return [k for k in raw if k in set(ALL_KEYS)]


def can_open(user, screen_key):
    screen = next((s for s in SCREENS if s['key'] == screen_key), None)
    keys = allowed_keys(user)
    if screen and screen.get('admin_only'):
        # it was admin-only before this feature and stays that way by default; only an explicit
        # grant opens it to an agent
        if not (user and getattr(user, 'is_admin', False)):
            return bool(keys is not None and screen_key in keys)
    return True if keys is None else screen_key in keys


def can_open_endpoint(user, endpoint):
    """An endpoint nobody has claimed is allowed. A route added tomorrow should not vanish for
    restricted agents before anyone has decided where it belongs."""
    owner = _OWNER.get(endpoint or '')
    return True if owner is None else can_open(user, owner)


def site_for_endpoint(endpoint):
    """Which product an endpoint belongs to, for the header switcher -- which renders before the
    sidebar has said where it is."""
    key = _OWNER.get(endpoint or '')
    if not key:
        return None
    return next((s['site'] for s in SCREENS if s['key'] == key), None)


def screens_for(user):
    """The menu this agent should see, in declaration order."""
    keys = allowed_keys(user)
    is_admin = bool(user and getattr(user, 'is_admin', False))
    out = []
    for s in SCREENS:
        if s.get('admin_only') and not is_admin:
            # unless an admin has granted it explicitly
            if keys is None or s['key'] not in keys:
                continue
        if keys is None or s['key'] in keys:
            out.append(s)
    return out


def sites_for(user):
    """(key, label, icon, screens) for each site this agent has anything in."""
    visible = screens_for(user)
    out = []
    for key, label, icon in SITES:
        items = [s for s in visible if s['site'] == key]
        if items:
            out.append({'key': key, 'label': label, 'icon': icon, 'items': items})
    return out


def summary_for(user):
    """Per-site counts for the admin list: what this agent can actually open, out of what could
    be granted to them.

    The numerator is screens_for(), not the stored list, because the two disagree: the scraper is
    closed unless an admin ticks it, so an agent with no limits set reaches four of Travel
    Companion's five screens, not five. Counting the stored list would print 5/5 and describe a
    door that is shut.
    """
    reachable = {s['key'] for s in screens_for(user)}
    out = []
    for key, label, icon in SITES:
        owned = [s for s in SCREENS if s['site'] == key]
        got = [s for s in owned if s['key'] in reachable]
        out.append({'key': key, 'label': label, 'icon': icon,
                    'got': len(got), 'total': len(owned),
                    'names': ', '.join(s['label'] for s in got) or 'nothing'})
    return out


def recipients(*screen_keys, limit=20):
    """Active staff who should hear about something on one of `screen_keys`.

    This grants screens, so it has to gate the notifications about them as well. A notification
    is an instruction to go and look: sending "New contact message" to an agent whose console
    has no User voices screen is an instruction they cannot follow -- the link 403s -- and every
    one of them buries the ones they can act on. The restriction was invisible here, so an agent
    narrowed to the Sahayak queue was still told about every insurance lead and every report.

    Admins are never restricted, so they always appear. An agent with no limits set is
    unrestricted too, which is still the default and still everybody today.
    """
    from app.models import User
    staff = (User.query
             .filter(User.role.in_(['cs', 'admin']), User.is_active.is_(True))
             .order_by(User.id).all())
    out = [u for u in staff if any(can_open(u, k) for k in screen_keys)]
    return out[:limit] if limit else out


def clean(keys):
    """What to store from a form: known keys only, in declaration order so the column reads the
    way the screen does."""
    chosen = set(keys or [])
    return [k for k in ALL_KEYS if k in chosen]
