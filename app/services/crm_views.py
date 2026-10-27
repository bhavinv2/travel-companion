"""Saved views: a staff page's filters under a name. Leads and Contacts since Sales CRM 2.0 (run 4b), with the Views
menu of their own toolbars; every other staff page since 2026-10-27, from the star in the header (base.html, "This
page"). One table and one set of rules for all of them:

  * Leads and Contacts keep their whitelists below (clean); any other page keeps plain filter words
    (services/page_address.clean_params) and its endpoint and path words (`endpoint`, `args`), and only a screen a
    menu line opens may have views (page_address.menu_endpoints) -- not one lead, not a download.
  * Shared with ONE team, the owner's, and only with them (services/team_share). `shared` is true while it is.
  * Anybody who can open a view can star it (services/favourites); deleting the view takes the stars with it.

WHY A TABLE OF ITS OWN (crm_views) AND NOT SavedFilter + a `scope` column. SavedFilter (services/saved_filters.py,
routes/saved_views.py) is built around the post listings' filter engine: its params are cleaned against
post_filters.FIELDS, its chips come from post_filters.chips(), "Open" redirects onto cs.posts / admin.listings, its
dates are the engine's presets, and the manage screen and its drawer are that engine's. Sharing the table would have
meant a second code path through every one of those, and a `scope` column every posts query would have to
remember to filter on. A views table is five columns; the CRM's filters are plain query-string words.

A view stores only filter words from a whitelist (never ids of rows, never SQL). Opening one is a link to the
page with those words, so everything the page does -- record visibility, the recycle bin, the downloads -- applies to
it exactly as to a hand-made filter.
"""
from datetime import datetime, timedelta

from sqlalchemy import or_

from app import db
from app.models import CRM_FORECASTS, CRM_LIKELIHOOD, CrmView
from app.services import crm, crm_money, team_share

LEADS, CONTACTS = 'crm_leads', 'crm_contacts'
SCOPES = (LEADS, CONTACTS)
MAX_PER_USER = 60
NAME_MAX = 60
OWNER_WORDS = ('mine', 'all', 'none')
IST = timedelta(hours=5, minutes=30)


class ViewError(ValueError):
    """Something the person can fix, phrased for them."""


def _owner(v):
    return v if (v in OWNER_WORDS or (v.isdigit() and len(v) < 10)) else None


def _word(allowed):
    allowed = tuple(allowed)
    return lambda v: v if v in allowed else None


def _digits(v):
    return v if v.isdigit() and len(v) < 10 else None


def _text(n):
    return lambda v: v[:n] or None


def _closes(v):
    return v if crm_money.closes_bounds(v) else None


def _day(v):
    return v if crm._iso_day(v) and len(v) == 10 else None


def _leads_checks():
    from app.routes.crm import CHAT_FILTERS
    ranges = {k for f, _ in crm.LEAD_DATES for k, _l in crm.date_ranges(f)} | {'custom'}
    return {'p': lambda v: v if v == 'all' or (v.replace('-', '').replace('_', '').isalnum() and len(v) <= 40) else None,
            'view': _word(('board', 'list')), 'owner': _owner, 'chat': _word([k for k, _ in CHAT_FILTERS]),
            'win': _word(('30', 'all')), 'stage': _digits, 'q': _text(80), 'closes': _closes,
            'forecast': _word(tuple(CRM_FORECASTS)), 'no_value': _word(('1',)), 'no_close': _word(('1',)),
            'status': _word(('open', 'won', 'lost')), 'follow': _word([k for k, _ in crm.FOLLOW_FILTERS]),
            'quoted': _word(('week',)),
            # the filter panel's: which date and its range (a ready-made range stays rolling), source, how likely
            'dt': _word([k for k, _ in crm.LEAD_DATES]), 'dr': _word(sorted(ranges)), 'd1': _day, 'd2': _day,
            'src': _source, 'lk': _word(tuple(CRM_LIKELIHOOD)),
            'how': _word(('organic', 'manual', 'imported'))}


def _source(v):
    """A lead source id, a group of the lead sources' list ('g:calls'), or 'none'."""
    from app.services import crm_sources
    return v if v == 'none' or (v.startswith('g:') and v[2:] in crm_sources.GROUP_NAMES) else _digits(v)


def _contacts_checks():
    from app.services import crm_people
    return {'tag': lambda v: v.lower()[:40] or None, 'wa': _word([k for k, _ in crm_people.WA_FILTERS]),
            'enq': _word([k for k, _ in crm_people.ENQ_FILTERS]), 'owner': _owner, 'q': _text(80)}


def keys(scope):
    return tuple(_leads_checks() if scope == LEADS else _contacts_checks())


def clean(scope, raw):
    """Only whitelisted filter words, each checked; anything else is dropped."""
    if scope not in SCOPES:
        raise ViewError('Unknown page.')
    checks = _leads_checks() if scope == LEADS else _contacts_checks()
    out = {}
    for k, check in checks.items():
        v = raw.get(k) if hasattr(raw, 'get') else None
        if v in (None, ''):
            continue
        v = check(' '.join(str(v).split()))
        if v:
            out[k] = v
    return out


def builtins(scope, today=None):
    """[(key, label, params)] the views everybody has. Dates are worked out when the menu is drawn."""
    if scope == LEADS:
        today = today or (datetime.utcnow() + IST).date()
        month = '%04d-%02d' % (today.year, today.month)
        return [('mine-open', 'My open leads', {'owner': 'mine', 'status': 'open'}),
                ('due-today', 'Due today', {'owner': 'mine', 'follow': 'today'}),
                ('late', 'Late', {'owner': 'mine', 'follow': 'late'}),
                ('quoted-week', 'Quoted this week', {'owner': 'all', 'quoted': 'week'}),
                ('new-week', 'Came in the last 7 days', {'owner': 'all', 'dr': '7d'}),
                ('travel-soon', 'Travelling in the next 30 days', {'owner': 'all', 'status': 'open', 'dt': 'travel',
                                                                  'dr': 'next30'}),
                ('won-month', 'Won this month', {'owner': 'all', 'status': 'won', 'forecast': 'won',
                                                 'closes': month}),
                ('no-value', 'No value yet', {'owner': 'all', 'status': 'open', 'no_value': '1'})]
    return [('mine', 'My contacts', {'owner': 'mine'}), ('no-enquiry', 'No enquiry yet', {'enq': 'no'}),
            ('opted-out', 'Opted out', {'wa': 'optout'}), ('waiting', 'Waiting on us', {'wa': 'waiting'})]


def _visible(user, query):
    """{'mine': [CrmView], 'shared': [CrmView]} of a query: this person's, and the ones shared with their team."""
    rows = (query.filter(or_(CrmView.owner_id == user.id, CrmView.team_id.in_(sorted(team_share.team_ids(user)) or [0])))
            .order_by(CrmView.name, CrmView.id).all())
    return {'mine': [v for v in rows if v.owner_id == user.id], 'shared': team_share.shared_with(user, rows)}


def for_user(user, scope, endpoint=None):
    """{'mine': [CrmView], 'shared': [CrmView]}: the views of a page this person made, and the ones their team shared
    with them. `endpoint`: of the page's screen (any page but Leads and Contacts)."""
    q = CrmView.query.filter(CrmView.scope == scope)
    if scope not in SCOPES and endpoint:
        q = q.filter(CrmView.endpoint.in_(_console_twins(endpoint)))
    return _visible(user, q)


def everything_for(user):
    """Every view this person can open, for "Favourites & views": {'mine': [...], 'shared': [...]}."""
    return _visible(user, CrmView.query)


def _console_twins(endpoint):
    """The Sales CRM's screens are mounted twice: a view saved in one console is the same view in the other."""
    if endpoint.startswith('admin_crm.'):
        return (endpoint, 'crm.' + endpoint[len('admin_crm.'):])
    if endpoint.startswith('crm.'):
        return (endpoint, 'admin_crm.' + endpoint[len('crm.'):])
    return (endpoint,)


def get_for(user, view_id):
    """A view this person may open (theirs, or shared with their team), or None."""
    v = db.session.get(CrmView, view_id)
    return v if team_share.sees(user, v) else None


def url_of(v, user):
    """Where a view opens, for `user` (their console), or None when its screen is gone."""
    from app.services import page_address
    if v.scope in SCOPES:
        return page_address.url('crm.board' if v.scope == LEADS else 'crm.contacts', {}, v.params, user)
    return page_address.url(v.endpoint, v.args, v.params, user) if v.endpoint else None


def page_label(v):
    from app.services import access
    p = access.PAGES.get(v.scope)
    return 'Leads' if v.scope == LEADS else ('Contacts' if v.scope == CONTACTS else (p['label'] if p else v.scope))


def may_have_views(endpoint):
    """May a screen have saved views of the kind "This page" saves? Leads and Contacts keep theirs in their own Views
    menu, the trip lists as saved filters (saved_filters); one record's page, a download, a JSON answer have none."""
    from app.services import page_address
    return bool(endpoint) and endpoint in page_address.menu_endpoints() and endpoint not in OWN_MENUS


# screens whose views live in a menu of their own (the one home for them): the header points there
OWN_MENUS = {'crm.board': 'views', 'admin_crm.board': 'views', 'crm.contacts': 'views', 'admin_crm.contacts': 'views',
             'cs.posts': 'filters', 'admin.listings': 'filters'}


def _name(name):
    name = ' '.join(str(name or '').split())[:NAME_MAX]
    if not name:
        raise ViewError('Give the view a name so you can find it again.')
    return name


def _team(user, team, shared):
    """The team a view is shared with: the one given (one of theirs), else for the older "shared" tick their first
    team, else nobody."""
    if team is not None:
        return team if team in team_share.teams(user) else None
    if shared:
        mine = team_share.teams(user)
        return mine[0] if mine else None
    return None


def create(user, scope, name, raw, shared=False, team=None, endpoint=None, args=None):
    """A view of Leads / Contacts (scope LEADS / CONTACTS, `raw` checked against their whitelists), or of any other
    page: `scope` its page key, `endpoint` its screen, `raw` its filter words. `team`: shared with that team of the
    person's (shared=True: their first team)."""
    from app.services import page_address
    name = _name(name)
    if scope in SCOPES:
        params, endpoint, args = clean(scope, raw), None, None
    else:
        if not may_have_views(endpoint) or page_address.page_of(endpoint) != scope:
            raise ViewError('This screen cannot be saved as a view.')
        params, args = page_address.clean_params(raw), {k: v for k, v in (args or {}).items() if isinstance(v, (int, str))}
    if not params:
        raise ViewError('Choose at least one filter before saving a view.')
    if CrmView.query.filter_by(owner_id=user.id).count() >= MAX_PER_USER:
        raise ViewError('You already have %d saved views. Delete one to make room.' % MAX_PER_USER)
    if CrmView.query.filter_by(owner_id=user.id, scope=scope, name=name).first():
        raise ViewError('You already have a view called "%s".' % name)
    team = _team(user, team, shared)
    v = CrmView(owner_id=user.id, scope=scope, name=name, params=params, endpoint=endpoint, args=args or None,
                team_id=team.id if team else None, shared=team is not None, created_at=datetime.utcnow())
    db.session.add(v)
    db.session.commit()
    return v


def own(user, view_id):
    v = db.session.get(CrmView, view_id)
    return v if v is not None and v.owner_id == user.id else None


_KEEP = object()


def rename(user, view_id, name=None, shared=None, team=_KEEP):
    """Rename and / or share: `team` a team of theirs (None: only them); the older `shared` tick: their first team."""
    v = own(user, view_id)
    if v is None:
        raise ViewError('That view is not yours to change.')
    if name is not None:
        name = _name(name)
        clash = CrmView.query.filter_by(owner_id=user.id, scope=v.scope, name=name).first()
        if clash is not None and clash.id != v.id:
            raise ViewError('You already have a view called "%s".' % name)
        v.name = name
    if team is not _KEEP or shared is not None:
        t = _team(user, None if team is _KEEP else team, bool(shared) if team is _KEEP else False)
        v.team_id, v.shared = (t.id if t else None), t is not None
    db.session.commit()
    return v


def delete(user, view_id):
    v = own(user, view_id)
    if v is None:
        raise ViewError('That view is not yours to delete.')
    db.session.delete(v)
    db.session.commit()


def is_active(params, current):
    """A view is the open one when the page's filters carry all its words."""
    return bool(params) and all(str(current.get(k)) == str(v) for k, v in params.items())
