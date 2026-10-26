"""What a role may DO on the pages it opens (Staff Console 2.0, 2026-10-26): least privilege by action, and the six
ready-made profiles.

A role's pages say what somebody may open (services/access.py). On top of them each role says (WorkspaceRole.rights):
    view      page keys opened only to look: every request that changes something on those pages' addresses is
              turned back by the page guard (access.guard), except the harmless ones in LOOKING (marking read,
              previews, one's own saved filters)
    remove    may send leads to the Recycle bin (those they created or look after, as before)
    mask      phone numbers and e-mails of people whose leads they do not look after are hidden on the Sales CRM's
              screens until "Show", which is logged (services/crm_mask)
A role with no rights stored behaves as every role did before them: nothing look-only, removing allowed, nothing
hidden. Somebody with several roles (their own and their teams') gets the most generous answer, as with the lead
scope; somebody "Working as" one role gets just that role's. Site admins and the workspace owner are never limited.

    PROFILES          the six profiles: five fill the role form ("Start from a profile"), Owner is the workspace owner
    rights_of(user)   {'view': frozenset, 'remove': bool, 'mask': bool} in the current workspace
    may_change(user, endpoint)  False when every page of theirs that owns `endpoint` is look-only
    look_only_here()  the same for the screen open now (the notice under its heading)
    may_remove(user)  /  masks(user)
    from_form(form, pages) / form_values(role)   the role form's part
"""
from app.services import access

FULL = {'view': frozenset(), 'remove': True, 'mask': False}
LOOK_ONLY = 'Your role can look at this page but not change anything on it.'

# POSTs that change nothing anybody else sees: reading marks, previews, a person's own saved filters
LOOKING = frozenset({
    'cs.voice_read', 'cs.notifications_read', 'admin.notification_log_read', 'matches.cs_read_post',
    'admin.blog_check', 'admin.blog_preview', 'admin.preview_message', 'cs.check_duplicates',
    'scraper.mapping_preview', 'scraper.preview_recipe', 'workspace.menu_preview',
    'crm.view_save', 'crm.view_rename', 'crm.view_delete', 'admin_crm.view_save', 'admin_crm.view_rename',
    'admin_crm.view_delete', 'crm.contact_show', 'admin_crm.contact_show', 'admin.checklist_hide'})

_SALES = ('crm_today', 'crm_checks', 'crm_inbox', 'wa_inbox', 'crm_board', 'crm_add', 'crm_calendar', 'crm_people',
          'crm_process', 'notifications', 'guide')
_FORMS = ('voices_general', 'voices_contact', 'voices_feedback', 'voices_report', 'voices_insurance', 'voices_sahayak')

# The six profiles (Staff Console 2.0's matrix). `pages` go through access.clean_pages, so a page that cannot be
# given on its own is simply left out; `admin` means every page the role form offers.
PROFILES = (
    {'key': 'sales_agent', 'label': 'Sales agent', 'icon': 'fa-headset',
     'says': 'Works their own leads: My day, the Inbox, Leads, Contacts and Tasks. Sees only their own leads and new '
             'ones; other people\'s numbers are hidden.',
     'pages': _SALES, 'scope': 'own', 'remove': True, 'mask': True, 'view': ()},
    {'key': 'service_agent', 'label': 'Service agent', 'icon': 'fa-handshake-angle',
     'says': 'Service to-do, the website forms, WhatsApp chats, posts and matches, insurance quotes and Sahayak '
             'bookings, with their own leads and contacts.',
     'pages': ('home', 'notifications', 'guide', 'wa_inbox', 'crm_inbox', 'crm_board', 'crm_people', 'crm_calendar',
               'posts', 'matches', 'new', 'insurance', 'sahayak') + _FORMS,
     'scope': 'own', 'remove': True, 'mask': True, 'view': ()},
    {'key': 'team_lead', 'label': 'Team lead', 'icon': 'fa-user-tie',
     'says': "Everything an agent does for their team's leads, plus Team today, Results, Report builder, Targets and "
             'Broadcasts. Automation is look-only.',
     'pages': tuple(sorted(access.CS_ROLE_PAGES | access.TEAM_LEAD_EXTRA)) + ('crm_inbox', 'crm_calendar', 'guide'),
     'scope': 'team', 'remove': True, 'mask': False, 'view': ('crm_auto',)},
    {'key': 'content_editor', 'label': 'Content editor', 'icon': 'fa-pen-nib',
     'says': 'The blog, the landing page, the insurance page and the Help & FAQ pages. No leads, no set-up.',
     'pages': ('blog_list', 'blog', 'landing', 'insurance_page', 'help', 'help_insurance', 'help_sahayak',
               'notifications', 'guide'),
     'scope': 'own', 'remove': False, 'mask': True, 'view': ()},
    {'key': 'admin', 'label': 'Admin', 'icon': 'fa-user-gear',
     'says': 'Every page and every set-up screen; sees all leads. Deleting for good stays with the Super admin.',
     'pages': 'admin', 'scope': 'all', 'remove': True, 'mask': False, 'view': ()},
    {'key': 'owner', 'label': 'Owner', 'icon': 'fa-crown', 'fills': False,
     'says': "The workspace's owner, chosen on Team members: everything, always. Emptying the Recycle bin and "
             'deleting for good belong to the Super admin account.',
     'pages': (), 'scope': 'all', 'remove': True, 'mask': False, 'view': ()},
)
PROFILE_BY_KEY = {p['key']: p for p in PROFILES}


def profile_pages(profile):
    """The page keys a profile ticks on the role form."""
    if profile['pages'] == 'admin':
        return access.clean_pages([p['key'] for m in access.MODULES for p in m['pages']])
    return access.clean_pages(profile['pages'])


def presets():
    """The profiles for the role form's "Start from a profile": [{'key', 'label', 'icon', 'says', 'fills', 'pages',
    'scope', 'view', 'remove', 'mask'}] -- what the page's script ticks."""
    return [{'key': p['key'], 'label': p['label'], 'icon': p['icon'], 'says': p['says'], 'fills': p.get('fills', True),
             'pages': profile_pages(p), 'scope': p['scope'], 'view': list(p['view']), 'remove': p['remove'],
             'mask': p['mask']} for p in PROFILES]


def _stored(role):
    """A role's rights as stored, with the defaults of a role that has none."""
    r = role.rights if role is not None and isinstance(role.rights, dict) else {}
    pages = access.role_pages(role)
    return {'view': frozenset(k for k in r.get('view') or () if k in pages),
            'remove': bool(r.get('remove', True)), 'mask': bool(r.get('mask', False)),
            'profile': r.get('profile') if r.get('profile') in PROFILE_BY_KEY else None}


def form_values(role):
    """What the role form shows for `role` (None: a new role -- nothing look-only, removing allowed, nothing
    hidden)."""
    if role is None:
        return {'view': frozenset(), 'remove': True, 'mask': False, 'profile': None}
    return _stored(role)


def from_form(form, pages):
    """The rights a role form sends, for a role with `pages`: look-only only on pages it has."""
    profile = form.get('profile') if form.get('profile') in PROFILE_BY_KEY else None
    return {'profile': profile, 'view': [k for k in pages if k in set(form.getlist('view'))],
            'remove': form.get('right_remove') == 'on', 'mask': form.get('right_mask') == 'on'}


def _roles(user):
    """The roles that apply to `user` now, or None when nothing limits them (a site admin, the owner, an
    Administrator, an account from before workspaces)."""
    act = access.acting_role(user)
    if act is not None:
        return None if act.system_key == 'admin' else [act]
    if user.is_admin:
        return None
    ws = access.current_workspace(user)
    m = next((m for m in access.memberships(user) if ws is not None and m.workspace_id == ws.id), None)
    if m is None or m.is_owner:
        return None
    roles = [m.role] if m.role is not None else []
    roles += [t.role for t in access._teams(m) if t.role is not None and t.role not in roles]
    if not roles or any(r.system_key == 'admin' for r in roles):
        return None
    return roles


def rights_of(user):
    """{'view': frozenset of look-only page keys, 'remove': bool, 'mask': bool} for `user` in the current workspace,
    the most generous across their roles (module note). Once a request."""
    if not getattr(user, 'is_authenticated', False):
        return FULL
    c = access._cache()
    key = ('rights', user.id)
    if key in c:
        return c[key]
    roles = _roles(user)
    if roles is None:
        out = FULL
    else:
        got = [(_stored(r), access.role_pages(r)) for r in roles]
        changes = set()
        for r, pages in got:
            changes |= pages - r['view']
        view = frozenset(k for r, _p in got for k in r['view']) - changes
        out = {'view': view, 'remove': any(r['remove'] for r, _p in got),
               'mask': all(r['mask'] for r, _p in got)}
    c[key] = out
    return out


def may_change(user, endpoint):
    """May `user` send a request that changes something to `endpoint`? No only when every page of theirs that owns it
    is look-only (another page of theirs that may change it wins)."""
    if endpoint in LOOKING:
        return True
    view = rights_of(user)['view']
    if not view:
        return True
    owners = access.ENDPOINT_PAGES.get(endpoint or '') or set()
    mine = owners & access.pages_for(user)
    return not mine or bool(mine - view)


def look_only(user, page_key):
    """Is `page_key` look-only for `user`?"""
    return page_key in rights_of(user)['view']


def look_only_here():
    """Is the screen open now look-only for whoever is signed in -- every page of theirs that owns it is? The notice
    under the page's heading (_page_head.html)."""
    from flask import has_request_context, request
    from flask_login import current_user
    if not has_request_context() or not getattr(current_user, 'is_authenticated', False):
        return False
    view = rights_of(current_user)['view']
    if not view:
        return False
    mine = (access.ENDPOINT_PAGES.get(request.endpoint or '') or set()) & access.pages_for(current_user)
    return bool(mine) and mine <= view


def may_remove(user):
    return rights_of(user)['remove']


def masks(user):
    return rights_of(user)['mask']
