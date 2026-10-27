"""Saved views on Leads and Contacts (Sales CRM 2.0, run 4b). Rules on crm_bp; the work is in services/crm_views.py.

A view is only filter words, opened as a link to the page itself (so record visibility and the downloads apply as
for any filter). Saving, renaming and deleting are plain form posts that come back to the page.
"""
from flask import flash, redirect, request
from flask_login import current_user

from app import db
from app.routes.crm import crm_bp, crm_url
from app.routes.cs import cs_required
from app.services import crm_views, team_share

PAGE = {crm_views.LEADS: 'board', crm_views.CONTACTS: 'contacts'}


@crm_bp.app_template_global('VIEWS_FOR')
def views_for(scope):
    return crm_views.for_user(current_user, scope)


@crm_bp.app_template_global('VIEWS_BUILTIN')
def views_builtin(scope):
    return crm_views.builtins(scope)


@crm_bp.app_template_global('VIEW_ACTIVE')
def view_active(params, current):
    return crm_views.is_active(params, current)


def _scope():
    s = request.form.get('scope')
    return s if s in crm_views.SCOPES else crm_views.LEADS


def _back(scope, args=None):
    return crm_url(PAGE[scope], **{k: v for k, v in (args or {}).items() if v})


@crm_bp.route('/views/save', methods=['POST'])
@cs_required
def view_save():
    scope = _scope()
    raw = {k[2:]: v for k, v in request.form.items() if k.startswith('f_')}
    try:
        v = crm_views.create(current_user, scope, request.form.get('name'), raw, request.form.get('shared') == 'on',
                             team=team_share.pick(current_user, request.form.get('team')))
    except crm_views.ViewError as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
        return redirect(_back(scope, raw))
    flash('Saved the view "%s"%s. It is in the Views menu.' % (
        v.name, ' and shared it with %s' % v.team.name if v.team_id else ''), 'success')
    return redirect(_back(scope, v.params))


@crm_bp.route('/views/<int:view_id>/rename', methods=['POST'])
@cs_required
def view_rename(view_id):
    scope = _scope()
    try:
        if 'team' in request.form:              # "Who sees it": only me, or one of my teams
            crm_views.rename(current_user, view_id, request.form.get('name'),
                             team=team_share.pick(current_user, request.form.get('team')))
        else:
            crm_views.rename(current_user, view_id, request.form.get('name'),
                             shared=(request.form.get('shared') == 'on') if 'shared_present' in request.form else None)
        flash('Saved.', 'success')
    except crm_views.ViewError as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
    return redirect(_back(scope))


@crm_bp.route('/views/<int:view_id>/delete', methods=['POST'])
@cs_required
def view_delete(view_id):
    scope = _scope()
    try:
        crm_views.delete(current_user, view_id)
        flash('View deleted.', 'success')
    except crm_views.ViewError as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
    return redirect(_back(scope))
