"""Which console a page is in, and the workspace switcher in its header.

The admin panel (/admin) and the CS console (/cs) grew up separately and still have separate
addresses. What somebody may open no longer depends on which one they are in -- workspace roles
decide that (services/access.py) -- so the header offers workspaces, not consoles: the menu under
it is that workspace's modules, narrowed to the person's pages.
"""
from flask import request, url_for

from app.services import urls

# Which blueprints belong to which console.
ADMIN_BLUEPRINTS = {'admin', 'admin_crm', 'workspace', 'messaging'}
CS_BLUEPRINTS = {'cs', 'matches', 'imports', 'scraper', 'jobs', 'saved', 'crm'}


def which():
    """'admin', 'cs', or None when this is not a console page."""
    bp = (request.blueprint or '').split('.')[0]
    if bp in ADMIN_BLUEPRINTS:
        return 'admin'
    if bp in CS_BLUEPRINTS:
        return 'cs'
    return None


def switcher():
    """The workspace switcher in the staff header: the workspace this request works in and the
    others this person can move to. None on a traveller page, and for somebody with only one
    workspace and nothing to manage -- a menu with one item is noise."""
    from flask_login import current_user
    from app.services import access
    if which() is None or not access.is_staff(current_user):
        return None
    from app.services import wacrm_team
    current = access.current_workspace(current_user)
    spaces = access.workspaces_for(current_user)
    manage = access.can(current_user, 'ws_settings')
    create = access.can(current_user, 'ws_all')
    if current is None or (len(spaces) < 2 and not manage and not create):
        return None
    # each workspace with the business WhatsApp number it runs (wacrm_team.number_of: stored, never asked live)
    sites = [dict({'key': w.id, 'label': w.name, 'icon': 'fa-building',
                   'url': url_for('workspace.switch', ws_id=w.id, next=urls.here())}, wa=wacrm_team.number_of(w))
             for w in spaces]
    tools = []
    if create:
        tools.append({'key': 'new', 'label': 'New workspace', 'icon': 'fa-plus', 'url': url_for('workspace.new_workspace')})
    if manage:
        tools.append({'key': 'settings', 'label': 'Workspace settings', 'icon': 'fa-gear',
                      'url': url_for('workspace.overview')})
    return {'label': current.name, 'current': current.id, 'wa': wacrm_team.number_of(current), 'sites': sites,
            'tools': tools}
