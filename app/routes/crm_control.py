"""Control (Sales CRM 2.0, run 3b): the Recycle bin, being away, and the "what a stage needs" form.

The rules are on crm_bp (routes/crm.py), so they exist under /cs/crm and /admin/crm. The work is in
services/crm_bin.py, crm_assign.py and crm_stage_rules.py.
"""
from datetime import datetime

from flask import abort, flash, jsonify, redirect, render_template, request
from flask_login import current_user

from app import db
from app.routes.crm import _common, admin_only, crm_bp, crm_url
from app.routes.cs import cs_required
from app.services import access, clock, crm_bin



# ============================================================================================ Recycle bin

@crm_bp.route('/bin')
@cs_required
@admin_only
def bin():
    """Leads removed in the last 30 days: put them back, or (Super admin) delete them now."""
    leads = crm_bin.removed_query().all()
    users = {}
    from app.models import User
    ids = {l.deleted_by_id for l in leads if l.deleted_by_id}
    if ids:
        users = {u.id: u.full_name for u in User.query.filter(User.id.in_(ids))}
    rows = []
    for l in leads:
        left = crm_bin.KEEP_DAYS - (datetime.utcnow() - l.deleted_at).days
        rows.append({'lead': l, 'person': l.person, 'who': users.get(l.deleted_by_id, 'Someone who left'),
                     'when': clock.local(l.deleted_at), 'days_left': max(0, left)})
    return render_template('cs/crm/bin.html', rows=rows, keep=crm_bin.KEEP_DAYS,
                           can_purge=access.can(current_user, 'delete_records'), **_common())


@crm_bp.route('/bin/<int:lead_id>/restore', methods=['POST'])
@cs_required
@admin_only
def bin_restore(lead_id):
    lead = crm_bin.get_removed(lead_id)
    if lead is None:
        abort(404)
    crm_bin.restore(lead, user=current_user)
    flash('Put %s back in the Sales CRM.' % lead.person.display_name, 'success')
    return redirect(crm_url('bin'))


@crm_bp.route('/bin/<int:lead_id>/purge', methods=['POST'])
@cs_required
@admin_only
def bin_purge(lead_id):
    if not access.can(current_user, 'delete_records'):
        flash('Only a Super admin can delete for good.', 'danger')
        return redirect(crm_url('bin'))
    lead = crm_bin.get_removed(lead_id)
    if lead is None:
        abort(404)
    crm_bin.purge(lead, user=current_user)
    flash('Deleted for good.', 'success')
    return redirect(crm_url('bin'))
