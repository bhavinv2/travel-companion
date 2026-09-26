"""Named filter sets that keep working tomorrow.

An agent who wants "everyone flying out of Delhi today" sets eight fields, reads the list, and
then does the same eight fields again the next morning. This lets them do it once, name it, and
click the name from then on.

The thing that makes it worth building rather than bookmarking a URL is that the dates are stored
as INTENT. `dep=today` is saved, not `dep_from=2026-09-26`, and post_filters resolves it against
the day the filter is opened. Save it in September, open it in December, and it is December's
departures. A bookmarked URL cannot do that, which is why people stopped using bookmarks for this.

What is stored is exactly the filter engine's params, so a filter added to post_filters.GROUPS is
immediately saveable with no change here and no migration.

Ownership: a filter belongs to whoever made it. Sharing is opt-in and read-only for everybody
else -- a colleague can use a shared filter but cannot rename, change or delete it, so nobody's
morning shortcut vanishes because somebody tidied up.
"""
from datetime import datetime

from sqlalchemy import or_

from app import db
from app.models import SavedFilter
from app.services import post_filters

NAME_MAX = 60
# Enough to be useful, few enough that the chip row stays a row. Somebody with forty daily views
# does not have daily views, they have a search box.
MAX_PER_USER = 20


class FilterError(ValueError):
    """Something the person can fix, phrased for them rather than for a log."""


def _clean_params(raw):
    """Keep only what the filter engine recognises, in its own vocabulary.

    Anything else is dropped rather than stored: a saved filter is replayed straight into the
    query builder, so letting unknown keys through would mean saving today's typo forever.
    """
    out = {}
    for key, field in post_filters.FIELDS.items():
        if field['kind'] == 'daterange':
            # the relative form first -- it is the reason this feature exists
            preset = (raw.get(key) or '').strip()
            if post_filters.preset_range(field, preset):
                out[key] = preset
                continue
            for param in (field['from_key'], field['to_key']):
                v = (raw.get(param) or '').strip()
                if v:
                    out[param] = v
        else:
            v = (raw.get(key) or '').strip()
            if v:
                out[key] = v
    return out


def describe(params):
    """What this filter does, in words, for somebody who did not build it.

    Reuses the chips the listing already shows, so the description on the manage screen and the
    chips above the results can never disagree about what is applied.
    """
    vals = post_filters.values(params or {})
    return [('%s: %s' % (c['label'], c['value'])) for c in post_filters.chips(vals)]


def is_relative(params):
    """True when this filter rolls forward on its own -- worth saying out loud in the UI."""
    for key, field in post_filters.FIELDS.items():
        if field['kind'] == 'daterange' and post_filters.preset_range(field, (params or {}).get(key)):
            return True
    return False


def decorate(rows):
    """Attach what the templates show but the table does not store.

    Computed once here rather than in each template so the chip's tooltip, the manage screen's
    summary and the listing's chips can never describe the same filter differently.
    """
    for f in rows:
        f.reads_as = ' · '.join(describe(f.params)) or 'No filters'
        f.rolls_forward = is_relative(f.params)
    return rows


def for_user(user):
    """The filters this person can open: their own first, then what colleagues shared.

    Own filters lead because they are the ones somebody made for their own morning; a shared one
    is useful but it is somebody else's idea of the day.
    """
    rows = (SavedFilter.query
            .filter(or_(SavedFilter.owner_id == user.id, SavedFilter.shared.is_(True)))
            .order_by(SavedFilter.position.asc(), SavedFilter.name.asc())
            .all())
    mine = [f for f in rows if f.owner_id == user.id]
    theirs = [f for f in rows if f.owner_id != user.id]
    return decorate(mine + theirs)


def get_for(user, filter_id):
    """A filter this person is allowed to open. None rather than an error: a deleted shortcut in
    somebody's muscle memory should land on the plain listing, not on a 404."""
    f = SavedFilter.query.get(filter_id)
    if not f:
        return None
    return f if (f.owner_id == user.id or f.shared) else None


def owned_by(user, filter_id):
    """A filter this person may CHANGE. Sharing grants use, never edit."""
    f = SavedFilter.query.get(filter_id)
    return f if (f and f.owner_id == user.id) else None


def create(user, name, raw_params, sort=None, shared=False):
    name = (name or '').strip()[:NAME_MAX]
    if not name:
        raise FilterError('Give the filter a name so you can find it again.')

    params = _clean_params(raw_params)
    if not params:
        raise FilterError('Choose at least one filter before saving.')

    if SavedFilter.query.filter_by(owner_id=user.id).count() >= MAX_PER_USER:
        raise FilterError('You already have %d saved filters. Delete one to make room.' % MAX_PER_USER)
    if SavedFilter.query.filter_by(owner_id=user.id, name=name).first():
        raise FilterError('You already have a filter called "%s".' % name)

    last = (db.session.query(db.func.max(SavedFilter.position))
            .filter_by(owner_id=user.id).scalar()) or 0
    f = SavedFilter(owner_id=user.id, name=name, params=params, sort=(sort or None),
                    shared=bool(shared), position=last + 1)
    db.session.add(f)
    db.session.commit()
    return f


def update(user, filter_id, name=None, raw_params=None, sort=None, shared=None):
    f = owned_by(user, filter_id)
    if not f:
        raise FilterError('That filter is not yours to change.')

    if name is not None:
        name = name.strip()[:NAME_MAX]
        if not name:
            raise FilterError('Give the filter a name so you can find it again.')
        clash = SavedFilter.query.filter_by(owner_id=user.id, name=name).first()
        if clash and clash.id != f.id:
            raise FilterError('You already have a filter called "%s".' % name)
        f.name = name

    if raw_params is not None:
        params = _clean_params(raw_params)
        if not params:
            raise FilterError('Choose at least one filter before saving.')
        f.params = params

    if sort is not None:
        f.sort = sort or None
    if shared is not None:
        f.shared = bool(shared)

    db.session.commit()
    return f


def delete(user, filter_id):
    f = owned_by(user, filter_id)
    if not f:
        raise FilterError('That filter is not yours to delete.')
    db.session.delete(f)
    db.session.commit()


def reorder(user, ids):
    """Put the owner's filters in the given order; anything left out keeps its place at the end."""
    mine = {f.id: f for f in SavedFilter.query.filter_by(owner_id=user.id).all()}
    for i, fid in enumerate(ids, start=1):
        f = mine.get(int(fid))
        if f:
            f.position = i
    db.session.commit()


def mark_used(f):
    """Cheap usage record, so an unused shortcut can be spotted rather than guessed at."""
    f.last_used_at = datetime.utcnow()
    f.use_count = (f.use_count or 0) + 1
    db.session.commit()


def query_string(f):
    """The filter as URL params, ready to hang off a listing link."""
    from urllib.parse import urlencode
    args = dict(f.params or {})
    if f.sort:
        args['sort'] = f.sort
    return urlencode(args)
