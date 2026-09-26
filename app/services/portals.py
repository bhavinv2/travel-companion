"""The header's site switcher, for both consoles.

The admin panel and the CS console each cover three products plus their own shared screens, and
an agent working a Sahayak queue has no use for insurance testimonials sitting next to it. The
switcher picks one product; the sidebar under it shows only that product's screens.

One control, two catalogues. Admin screens are declared in admin_nav, CS screens in cs_access --
they are different lists with different rules (cs_access also decides what an agent may open at
all) and merging them would mean one list pretending to be two. This module only answers "which
console am I in, and what can I switch to".

It is a view of the same screens, not a second set of permissions. Switching changes what the
menu offers; what somebody is allowed to open is cs_access's job and is enforced on the request,
not here.
"""
from flask import request, url_for
from flask_login import current_user

from app.services import admin_nav, cs_access

# Which blueprints belong to which console.
ADMIN_BLUEPRINTS = {'admin'}
CS_BLUEPRINTS = {'cs', 'matches', 'imports', 'scraper', 'jobs', 'saved'}


def which():
    """'admin', 'cs', or None when this is not a console page."""
    bp = (request.blueprint or '').split('.')[0]
    if bp in ADMIN_BLUEPRINTS:
        return 'admin'
    if bp in CS_BLUEPRINTS:
        return 'cs'
    return None


def switcher():
    """What the header dropdown should show, or None to render nothing.

    Where we are comes from the ENDPOINT, not from the sidebar's `active` key: the header renders
    before the sidebar does, so `active` is not in scope yet. Off a console page, or for somebody
    with only one product to see, there is nothing worth switching.
    """
    console = which()
    if not console:
        return None

    if console == 'admin':
        if not getattr(current_user, 'is_admin', False):
            return None
        current = admin_nav.section_for_endpoint(request.endpoint, request.args)
        sites = [{'key': s['key'], 'label': s['label'], 'icon': s['icon'],
                  'url': url_for(s['items'][0]['endpoint'], **s['items'][0]['args'])}
                 for s in admin_nav.SECTIONS]
        on_dashboard = request.endpoint == admin_nav.DASHBOARD['endpoint']
        return {'console': 'admin', 'sites': sites,
                'current': None if on_dashboard else current,
                'label': 'Dashboard' if on_dashboard else _label(sites, current)}

    groups = cs_access.sites_for(current_user)
    if len(groups) < 2:
        # nothing to switch between; the sidebar already says everything there is to say
        return None
    current = cs_access.site_for_endpoint(request.endpoint) or groups[0]['key']
    sites = [{'key': g['key'], 'label': g['label'], 'icon': g['icon'],
              'url': url_for(g['items'][0]['endpoints'][0])} for g in groups]
    return {'console': 'cs', 'sites': sites, 'current': current,
            'label': _label(sites, current)}


def _label(sites, current):
    for s in sites:
        if s['key'] == current:
            return s['label']
    return 'All screens'
