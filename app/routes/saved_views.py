"""Saved filters: the manage screen and the actions behind the chips.

Both post listings read one filter engine, so a saved filter is not tied to either of them --
these routes serve the CS console and the admin listings alike, and `is_cs` is true for admins,
so one guard covers both.

Nothing here renders a listing. Opening a saved filter is a redirect onto whichever listing the
person came from, carrying the filter's params; the listing does what it always did. That keeps
this feature out of the query path entirely, so it cannot slow down or break the lists it
decorates.
"""
from flask import (Blueprint, flash, redirect, render_template, request, url_for)
from flask_login import current_user

from app.routes.cs import cs_required
from app.services import post_filters, saved_filters

saved_bp = Blueprint('saved', __name__, url_prefix='/saved-filters')

# Where a filter may be opened. Anything else is ignored rather than followed, so a crafted
# `next` cannot turn a saved filter into an open redirect.
LISTINGS = {'cs': 'cs.posts', 'admin': 'admin.listings'}


def _listing(name):
    return LISTINGS.get(name) or 'cs.posts'


def _back(name, **args):
    return url_for(_listing(name), **args)


@saved_bp.route('/')
@cs_required
def manage():
    """Create, rename, reorder and delete. Deliberately a page of its own: the filter drawer is
    for building a query, and building is a different job from keeping house."""
    mine = [f for f in saved_filters.for_user(current_user) if f.owner_id == current_user.id]
    shared = [f for f in saved_filters.for_user(current_user) if f.owner_id != current_user.id]
    listing = request.args.get('from') or 'cs'
    return render_template(
        'saved_filters.html',
        mine=mine, shared=shared, listing=listing,
        describe=saved_filters.describe, is_relative=saved_filters.is_relative,
        query_string=saved_filters.query_string,
        max_per_user=saved_filters.MAX_PER_USER,
        filter_groups=post_filters.GROUPS, SORTS=post_filters.SORTS)


@saved_bp.route('/open/<int:filter_id>')
@cs_required
def open_filter(filter_id):
    """Apply a saved filter to a listing."""
    f = saved_filters.get_for(current_user, filter_id)
    listing = request.args.get('from') or 'cs'
    if not f:
        # Somebody's muscle memory outliving the filter is not an error worth a 404 page.
        flash('That saved filter is no longer available.', 'warning')
        return redirect(_back(listing))
    saved_filters.mark_used(f)
    args = dict(f.params or {})
    if f.sort:
        args['sort'] = f.sort
    args['view'] = f.id                     # so the listing can show which one is open
    return redirect(_back(listing, **args))


@saved_bp.route('/save', methods=['POST'])
@cs_required
def save():
    """Keep the filters currently applied to a listing, under a name."""
    listing = request.form.get('from') or 'cs'
    keep = {k: v for k, v in request.form.items() if k not in ('name', 'from', 'shared', 'csrf_token')}
    try:
        f = saved_filters.create(current_user, request.form.get('name'), keep,
                                 sort=request.form.get('sort'),
                                 shared=request.form.get('shared') == 'on')
    except saved_filters.FilterError as e:
        flash(str(e), 'danger')
        return redirect(_back(listing, **keep))
    flash('Saved as "%s". It will be here tomorrow too.' % f.name, 'success')
    return redirect(_back(listing, view=f.id, **keep))


@saved_bp.route('/<int:filter_id>/rename', methods=['POST'])
@cs_required
def rename(filter_id):
    try:
        saved_filters.update(current_user, filter_id, name=request.form.get('name'))
        flash('Renamed.', 'success')
    except saved_filters.FilterError as e:
        flash(str(e), 'danger')
    return redirect(url_for('saved.manage', **{'from': request.form.get('from') or 'cs'}))


@saved_bp.route('/<int:filter_id>/share', methods=['POST'])
@cs_required
def share(filter_id):
    want = request.form.get('shared') == 'on'
    try:
        saved_filters.update(current_user, filter_id, shared=want)
        flash('Shared with the team.' if want else 'This filter is private again.', 'success')
    except saved_filters.FilterError as e:
        flash(str(e), 'danger')
    return redirect(url_for('saved.manage', **{'from': request.form.get('from') or 'cs'}))


@saved_bp.route('/<int:filter_id>/delete', methods=['POST'])
@cs_required
def delete(filter_id):
    try:
        saved_filters.delete(current_user, filter_id)
        flash('Deleted.', 'success')
    except saved_filters.FilterError as e:
        flash(str(e), 'danger')
    return redirect(url_for('saved.manage', **{'from': request.form.get('from') or 'cs'}))


@saved_bp.route('/<int:filter_id>/move', methods=['POST'])
@cs_required
def move(filter_id):
    """Nudge one filter up or down. Buttons rather than drag-and-drop: this has to work on a
    tablet, with a mouse, and for somebody who has never dragged a list item in their life."""
    listing = request.form.get('from') or 'cs'
    direction = request.form.get('dir')
    mine = [f for f in saved_filters.for_user(current_user) if f.owner_id == current_user.id]
    ids = [f.id for f in mine]
    if filter_id in ids:
        i = ids.index(filter_id)
        j = i - 1 if direction == 'up' else i + 1
        if 0 <= j < len(ids):
            ids[i], ids[j] = ids[j], ids[i]
            saved_filters.reorder(current_user, ids)
    return redirect(url_for('saved.manage', **{'from': listing}))
