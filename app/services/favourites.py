"""Favourites (2026-10-27): each staff member's own shortcuts -- a screen with the filters it had when they starred it,
or a saved view they can open (theirs or their team's) -- in the order they like, under the names they like.

They are starred from the header ("This page", the star beside "+"), or with the star beside a view in a Views menu.
They show at the top of the menu rail (★ Favourites) and are kept on "Favourites & views" (/my/favourites, the one
place to rename, reorder and remove them). Nobody else sees them.

What is kept is the screen as words (services/page_address): opening one builds the address again for its owner,
in their console. A favourite whose screen their role no longer opens, or whose view is no longer shared with them,
is left out of the list until it comes back -- it is not deleted. Deleting a view removes the stars on it.

    add(user, endpoint, args, params, label=None, view=None)   once per address (the same one twice is the same one)
    remove(user, fav_id) / rename(user, fav_id, label) / move(user, fav_id, up)
    star_view(user, view)        on and off, for a view they can open
    for_user(user)               [{'id', 'label', 'url', 'icon', 'page', 'filters', 'view', 'team', 'here'}]
    find(user, endpoint, args, params) / of_view(user, view_id)
"""
from datetime import datetime

from app import db
from app.models import StaffFavourite
from app.services import access, page_address, team_share

MAX = 40
LABEL_MAX = 80


class FavouriteError(ValueError):
    """Something the person can fix, said for them."""


def _label(text):
    return ' '.join(str(text or '').split())[:LABEL_MAX] or None


def _rows(user):
    c = access._cache()
    key = ('favs', user.id)
    if key not in c:
        c[key] = (StaffFavourite.query.filter_by(user_id=user.id)
                  .order_by(StaffFavourite.position, StaffFavourite.id).all())
    return c[key]


def _forget(user):
    c = access._cache()
    c.pop(('favs', user.id), None)
    c.pop(('fav_list', user.id), None)


def find(user, endpoint, args, params):
    k = page_address.key(endpoint, args, params)
    return next((f for f in _rows(user) if f.key == k and f.view_id is None), None)


def of_view(user, view_id):
    return next((f for f in _rows(user) if f.view_id == view_id), None)


def add(user, endpoint, args, params, label=None, view=None):
    """Star a screen (or a view). Returns the favourite; starring what is already a favourite returns that one."""
    if view is not None:
        from app.services import crm_views
        if not team_share.sees(user, view):
            raise FavouriteError('That view is not shared with you.')
        got = of_view(user, view.id)
        if got is not None:
            return got
        endpoint = view.endpoint or ('crm.board' if view.scope == crm_views.LEADS else 'crm.contacts')
        args, params = view.args or {}, view.params or {}
    elif not page_address.is_screen(endpoint):
        raise FavouriteError('This screen cannot be a favourite.')
    elif not (access.ENDPOINT_PAGES.get(endpoint, set()) & access.pages_for(user)):
        raise FavouriteError('Your role does not open this screen.')
    else:
        got = find(user, endpoint, args, params)
        if got is not None:
            return got
    if len(_rows(user)) >= MAX:
        raise FavouriteError('You already have %d favourites. Remove one to make room.' % MAX)
    last = max((f.position for f in _rows(user)), default=0)
    k = page_address.key(endpoint, args, params) if view is None else 'view:%d' % view.id
    f = StaffFavourite(user_id=user.id, key=k, label=None if view is not None else _label(label),
                       endpoint=endpoint, args=args or None, params=params or None,
                       view_id=view.id if view is not None else None, position=last + 1,
                       created_at=datetime.utcnow())
    db.session.add(f)
    db.session.commit()
    _forget(user)
    return f


def _own(user, fav_id):
    f = db.session.get(StaffFavourite, fav_id)
    if f is None or f.user_id != user.id:
        raise FavouriteError('That favourite is not yours.')
    return f


def remove(user, fav_id):
    db.session.delete(_own(user, fav_id))
    db.session.commit()
    _forget(user)


def rename(user, fav_id, label):
    f = _own(user, fav_id)
    f.label = _label(label)
    db.session.commit()
    _forget(user)
    return f


def move(user, fav_id, up):
    """One place up or down among their favourites."""
    rows = list(_rows(user))
    ids = [f.id for f in rows]
    if fav_id not in ids:
        raise FavouriteError('That favourite is not yours.')
    i = ids.index(fav_id)
    j = i - 1 if up else i + 1
    if 0 <= j < len(rows):
        rows[i], rows[j] = rows[j], rows[i]
    for n, f in enumerate(rows, start=1):
        f.position = n
    db.session.commit()
    _forget(user)


def star_view(user, view):
    """On and off for a view: returns True when it is a favourite now."""
    got = of_view(user, view.id)
    if got is not None:
        remove(user, got.id)
        return False
    add(user, None, None, None, view=view)
    return True


def _page_bits(endpoint):
    key = page_address.page_of(endpoint)
    p = access.PAGES.get(key) if key else None
    icon = (p['icon'] if p else 'fa-star')
    return key, (p['label'] if p else ''), icon if ' ' in icon else 'fa-solid ' + icon


def for_user(user):
    """What the rail and "Favourites & views" show, in their order: only what they may open now."""
    c = access._cache()
    key = ('fav_list', user.id)
    if key in c:
        return c[key]
    from app.services import crm_views
    mine = access.pages_for(user)
    here = page_address.here()
    here_key = page_address.key(*here) if here else None
    out = []
    for f in _rows(user):
        page, page_label, icon = _page_bits(f.endpoint)
        if not (access.ENDPOINT_PAGES.get(f.endpoint, set()) & mine):
            continue
        view = f.view if f.view_id else None
        if f.view_id and (view is None or not team_share.sees(user, view)):
            continue
        url = crm_views.url_of(view, user) if view is not None else \
            page_address.url(f.endpoint, f.args, f.params, user)
        if not url:
            continue
        label = f.label or (view.name if view is not None else '') or page_label or 'A page'
        out.append({'id': f.id, 'label': label, 'url': url, 'icon': icon, 'page': page_label,
                    'filters': len(f.params or {}), 'view': view is not None,
                    'team': team_share.team_name(view) if view is not None else None,
                    'shared_by': (view.owner.first_name or view.owner.username)
                    if view is not None and view.owner_id != user.id and view.owner else None,
                    'here': here_key is not None and view is None and f.key == here_key})
    c[key] = out
    return out
