"""Favourites, saved views of any staff page, and the tour guide (2026-10-27). The work is in services/favourites.py,
services/crm_views.py (the one table of saved views), services/team_share.py and services/tours.py.

Every staff member has these, whatever their role, so the endpoints are access.STAFF_ANY: personal shortcuts, not
pages a role grants. What a favourite or a view OPENS is still a screen the page guard checks as always.

The forms post back to the page they came from (`next`, checked by urls.safe_next) with a message; the tour guide
talks JSON to static/js/tour.js.
"""
from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user

from app import db
from app.routes.cs import cs_required
from app.services import access, crm_views, favourites, page_address, team_share, tours, urls

my_bp = Blueprint('my', __name__, url_prefix='/my')

ENDPOINTS = ('my.favourites', 'my.fav_add', 'my.fav_remove', 'my.fav_rename', 'my.fav_move', 'my.view_star',
             'my.view_save', 'my.view_edit', 'my.view_delete', 'my.tours', 'my.tour_answer', 'my.tour_done')


def _back():
    return urls.safe_next(request.form.get('next')) or url_for('my.favourites')


# ------------------------------------------------------------------------------------------------ the templates

@my_bp.app_template_global('FAVOURITES')
def _favourites():
    """The rail's ★ Favourites: what this person may open, in their order."""
    if not getattr(current_user, 'is_authenticated', False):
        return []
    return favourites.for_user(current_user)


@my_bp.app_template_global('HERE_URL')
def _here_url():
    """This page's address, for a form's `next` (a global: some screens pass a variable called `here`)."""
    return urls.here()


@my_bp.app_template_global('SHARE_TEAMS')
def _share_teams():
    return team_share.teams(current_user)


@my_bp.app_template_global('FAV_OF_VIEW')
def _fav_of_view(view_id):
    return favourites.of_view(current_user, view_id)


@my_bp.app_template_global('FAV_HERE')
def fav_here():
    """The header's "This page": is it a favourite, may its filters be saved as a view, the views of it."""
    got = page_address.here()
    if got is None or not getattr(current_user, 'is_authenticated', False):
        return None
    endpoint, args, params = got
    page = page_address.page_of(endpoint)
    fav = favourites.find(current_user, endpoint, args, params)
    out = {'fav': fav, 'params': params, 'page': access.PAGES[page]['label'] if page else '',
           'own_menu': crm_views.OWN_MENUS.get(endpoint), 'views': None, 'can_save': False, 'next': urls.here()}
    if crm_views.may_have_views(endpoint) and not args:
        out['views'] = crm_views.for_user(current_user, page, endpoint)
        out['can_save'] = bool(params)
        out['url_of'] = lambda v: crm_views.url_of(v, current_user)
        out['active'] = lambda v: crm_views.is_active(v.params, params) and len(v.params) == len(params)
    return out


@my_bp.app_template_global('TOUR_ASK')
def _tour_ask():
    return bool(getattr(current_user, 'is_authenticated', False)) and tours.should_ask(current_user)


# ------------------------------------------------------------------------------------------------ favourites

@my_bp.route('/favourites', endpoint='favourites')
@cs_required
def favourites_page():
    views = crm_views.everything_for(current_user)
    return render_template('my_favourites.html', favs=favourites.for_user(current_user), views=views,
                           url_of=lambda v: crm_views.url_of(v, current_user), page_label=crm_views.page_label,
                           max_favs=favourites.MAX, max_views=crm_views.MAX_PER_USER)



@my_bp.route('/favourites/add', methods=['POST'])
@cs_required
def fav_add():
    got = page_address.parse(request.form.get('next') or '')
    if got is None:
        flash('This screen cannot be a favourite.', 'warning')
        return redirect(_back())
    try:
        f = favourites.add(current_user, *got, label=request.form.get('label'))
        flash('Added “%s” to your favourites. It is at the top of the menu.' % (f.label or 'this page'), 'success')
    except favourites.FavouriteError as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
    return redirect(_back())


@my_bp.route('/favourites/<int:fav_id>/remove', methods=['POST'])
@cs_required
def fav_remove(fav_id):
    try:
        favourites.remove(current_user, fav_id)
        flash('Removed from your favourites.', 'success')
    except favourites.FavouriteError as exc:
        flash(str(exc), 'danger')
    return redirect(_back())


@my_bp.route('/favourites/<int:fav_id>/rename', methods=['POST'])
@cs_required
def fav_rename(fav_id):
    try:
        favourites.rename(current_user, fav_id, request.form.get('label'))
        flash('Saved.', 'success')
    except favourites.FavouriteError as exc:
        flash(str(exc), 'danger')
    return redirect(_back())


@my_bp.route('/favourites/<int:fav_id>/move', methods=['POST'])
@cs_required
def fav_move(fav_id):
    """One place up or down: buttons rather than dragging, so it works with a keyboard and on a tablet."""
    try:
        favourites.move(current_user, fav_id, request.form.get('dir') == 'up')
    except favourites.FavouriteError as exc:
        flash(str(exc), 'danger')
    return redirect(_back())


# ------------------------------------------------------------------------------------------------ views

@my_bp.route('/views/<int:view_id>/star', methods=['POST'])
@cs_required
def view_star(view_id):
    v = crm_views.get_for(current_user, view_id)
    if v is None:
        flash('That view is not shared with you.', 'warning')
        return redirect(_back())
    try:
        on = favourites.star_view(current_user, v)
        flash(('Added “%s” to your favourites.' if on else 'Removed “%s” from your favourites.') % v.name, 'success')
    except favourites.FavouriteError as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
    return redirect(_back())


@my_bp.route('/views/save', methods=['POST'])
@cs_required
def view_save():
    """Save the filters of the page in `next` as a view (any page but Leads and Contacts: their own menu does)."""
    got = page_address.parse(request.form.get('next') or '')
    if got is None or got[1]:
        flash('This screen cannot be saved as a view.', 'warning')
        return redirect(_back())
    endpoint, args, params = got
    try:
        v = crm_views.create(current_user, page_address.page_of(endpoint), request.form.get('name'), params,
                             team=team_share.pick(current_user, request.form.get('team')), endpoint=endpoint, args=args)
        if request.form.get('star') == 'on':
            favourites.star_view(current_user, v)
        flash('Saved the view “%s”%s.' % (v.name, ' for you and %s' % v.team.name if v.team_id else ''), 'success')
    except (crm_views.ViewError, favourites.FavouriteError) as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
    return redirect(_back())


@my_bp.route('/views/<int:view_id>/edit', methods=['POST'])
@cs_required
def view_edit(view_id):
    try:
        crm_views.rename(current_user, view_id, request.form.get('name'),
                         team=team_share.pick(current_user, request.form.get('team')))
        flash('Saved.', 'success')
    except crm_views.ViewError as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
    return redirect(_back())


@my_bp.route('/views/<int:view_id>/delete', methods=['POST'])
@cs_required
def view_delete(view_id):
    try:
        crm_views.delete(current_user, view_id)
        flash('View deleted.', 'success')
    except crm_views.ViewError as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
    return redirect(_back())


# ------------------------------------------------------------------------------------------------ the tour guide

@my_bp.route('/tours', endpoint='tours')
@cs_required
def tours_json():
    return jsonify(tours.for_user(current_user))


@my_bp.route('/tours/answer', methods=['POST'])
@cs_required
def tour_answer():
    what = (request.get_json(silent=True) or {}).get('answer') or request.form.get('answer')
    return jsonify({'ok': tours.answer(current_user, what)})


@my_bp.route('/tours/done', methods=['POST'])
@cs_required
def tour_done():
    key = str((request.get_json(silent=True) or {}).get('key') or request.form.get('key') or '')[:80]
    return jsonify({'ok': tours.finished(current_user, key)})
