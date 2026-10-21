"""People 360 (Sales CRM 2.0, run 4a): families, merging two people, and files.

The rules are on crm_bp (routes/crm.py), so they exist under /cs/crm and /admin/crm. The work is in
services/crm_household.py, crm_merge.py and crm_files.py; this file reads the request and draws.

Record visibility (crm_access): every route that loads a person goes through `_person_or_404`, every lead
through `_lead_or_404`; every list a POST draws applies crm_access.person_filter itself.
"""
from flask import abort, flash, redirect, render_template, request, send_file
from flask_login import current_user

from app import db
from app.models import ActivityEvent, CrmFile, CrmPerson, HOUSEHOLD_ROLES
from app.routes.crm import _common, _lead_or_404, crm_bp, crm_url
from app.routes.cs import cs_required
from app.services import access, crm_access, crm_files, crm_household, crm_merge, crm_scope


def _person_or_404(person_id):
    person = db.session.get(CrmPerson, person_id)
    if person is None or not crm_access.can_see_person(current_user, person) or not crm_scope.visible(person):
        abort(404)
    return person


def _safe_next(default):
    nxt = request.values.get('next') or ''
    return nxt if nxt.startswith('/') and not nxt.startswith('//') else default


def can_merge(user):
    """Admins, and anyone who can open the workspace's Team members page."""
    return bool(user.is_authenticated and (user.is_admin or access.can(user, 'ws_members')))


@crm_bp.app_template_global('CAN_MERGE')
def can_merge_global():
    return can_merge(current_user)


@crm_bp.app_template_global('HOUSEHOLD_ROLES')
def household_roles():
    return HOUSEHOLD_ROLES


@crm_bp.app_template_global('FILE_SIZE')
def file_size(n):
    return crm_files.size_text(n)


@crm_bp.app_template_global('CAN_DELETE_FILE')
def can_delete_file(f):
    return bool(current_user.is_authenticated and (current_user.is_admin or f.uploaded_by_id == current_user.id))


@crm_bp.app_template_global('FILE_TYPES')
def file_types():
    return ', '.join(sorted(crm_files.TYPES))


# ============================================================================================ families

def _back(person):
    return crm_url('contact', person_id=person.id) + '#family'


@crm_bp.route('/contact/<int:person_id>/family/add', methods=['POST'])
@cs_required
def contact_family_add(person_id):
    """Add an existing person (other_id) or a new one (name + phone) to this person's family."""
    person = _person_or_404(person_id)
    role = request.form.get('role') or 'other'
    other_id = request.form.get('other_id', type=int)
    if other_id:
        other = _person_or_404(other_id)
        err = crm_household.link(person, other, role, current_user)
        added = other
    else:
        added, err = crm_household.create_member(person, request.form.get('name'), request.form.get('phone'), role,
                                                 current_user, cc=request.form.get('phone_cc'))
    if err:
        db.session.rollback()
        flash(err, 'danger')
        return redirect(_back(person))
    ActivityEvent.log('crm_family_added', actor=current_user, person_id=person.id, other_id=added.id)
    db.session.commit()
    flash('%s is in the family now.' % added.display_name, 'success')
    return redirect(_back(person))


@crm_bp.route('/contact/<int:person_id>/family/role', methods=['POST'])
@cs_required
def contact_family_role(person_id):
    person = _person_or_404(person_id)
    member = _person_or_404(request.form.get('member_id', type=int) or 0)
    if person.household_id is None or member.household_id != person.household_id:
        abort(404)
    crm_household.set_role(member, request.form.get('role'))
    db.session.commit()
    flash('Saved.', 'success')
    return redirect(_back(person))


@crm_bp.route('/contact/<int:person_id>/family/remove', methods=['POST'])
@cs_required
def contact_family_remove(person_id):
    person = _person_or_404(person_id)
    member = _person_or_404(request.form.get('member_id', type=int) or 0)
    if person.household_id is None or member.household_id != person.household_id:
        abort(404)
    crm_household.leave(member)
    db.session.commit()
    flash('%s is not in the family any more.' % member.display_name, 'success')
    return redirect(_back(person))


@crm_bp.route('/contact/<int:person_id>/family/rename', methods=['POST'])
@cs_required
def contact_family_rename(person_id):
    person = _person_or_404(person_id)
    if person.household is None:
        abort(404)
    if crm_household.rename(person.household, request.form.get('name')):
        db.session.commit()
        flash('Saved.', 'success')
    return redirect(_back(person))


# ============================================================================================ merge

@crm_bp.route('/contact/<int:person_id>/merge')
@cs_required
def contact_merge(person_id):
    """Merge with another person: search, see what would move, press Merge. This contact is the one kept."""
    person = _person_or_404(person_id)
    if not can_merge(current_user):
        flash('Only an admin, or someone who manages team members, can merge two people.', 'warning')
        return redirect(crm_url('contact', person_id=person.id))
    q = ' '.join((request.args.get('q') or '').split())[:80]
    other = None
    preview = None
    other_id = request.args.get('with', type=int)
    if other_id:
        other = _person_or_404(other_id)
        if other.id == person.id:
            other = None
        else:
            preview = crm_merge.plan(person, other)
    results = crm_merge.search(person, q, current_user) if q and other is None else []
    return render_template('cs/crm/merge.html', person=person, other=other, preview=preview, q=q, results=results,
                           **_common())


@crm_bp.route('/contact/<int:person_id>/merge', methods=['POST'])
@cs_required
def contact_merge_do(person_id):
    person = _person_or_404(person_id)
    if not can_merge(current_user):
        abort(403)
    other = _person_or_404(request.form.get('other_id', type=int) or 0)
    if other.id == person.id:
        flash(crm_merge.SAME, 'danger')
        return redirect(crm_url('contact_merge', person_id=person.id))
    crm_merge.merge(person, other, actor=current_user)
    flash('Merged. Everything of the other contact is on this page now.', 'success')
    return redirect(crm_url('contact', person_id=person_id))


# ============================================================================================ files

def _after(person, lead):
    fallback = crm_url('lead', lead_id=lead.id) if lead is not None else crm_url('contact', person_id=person.id)
    return _safe_next(fallback) + '#files'


@crm_bp.route('/file/upload', methods=['POST'])
@cs_required
def file_upload():
    """Upload one or more files to a person (person_id) or to one of their enquiries (lead_id)."""
    lead = _lead_or_404(request.form.get('lead_id', type=int)) if request.form.get('lead_id') else None
    person = lead.person if lead is not None else _person_or_404(request.form.get('person_id', type=int) or 0)
    if lead is not None and not crm_access.can_see_person(current_user, person):
        abort(404)
    sent = [f for f in request.files.getlist('file') if f and f.filename]
    if not sent:
        flash(crm_files.NOTHING, 'danger')
        return redirect(_after(person, lead))
    done, problems = 0, []
    for storage in sent:
        row, err = crm_files.save_upload(storage, person, lead, current_user)
        if err:
            problems.append('%s: %s' % (crm_files.clean_name(storage.filename), err))
        else:
            done += 1
    if done:
        db.session.commit()
        flash('%d file%s saved.' % (done, '' if done == 1 else 's'), 'success')
    for p in problems:
        flash(p, 'danger')
    return redirect(_after(person, lead))


def _file_or_404(file_id):
    row = db.session.get(CrmFile, file_id)
    if row is None:
        abort(404)
    person = db.session.get(CrmPerson, row.person_id)
    if person is None or not crm_access.can_see_person(current_user, person) or not crm_scope.visible(person):
        abort(404)
    if row.lead_id:
        _lead_or_404(row.lead_id)        # an enquiry the viewer may not see, or one in the bin, hides its files
    return row, person


@crm_bp.route('/file/<int:file_id>/download')
@cs_required
def file_download(file_id):
    row, _person = _file_or_404(file_id)
    path = crm_files.path_of(row)
    try:
        resp = send_file(path, as_attachment=True, download_name=row.filename,
                         mimetype=row.content_type or 'application/octet-stream', max_age=0)
    except (FileNotFoundError, OSError):
        abort(404)
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['Cache-Control'] = 'private, no-store'
    return resp


@crm_bp.route('/file/<int:file_id>/delete', methods=['POST'])
@cs_required
def file_delete(file_id):
    row, person = _file_or_404(file_id)
    if not can_delete_file(row):
        abort(403)
    path = crm_files.delete(row)
    db.session.commit()
    crm_files.remove_from_disk([path])
    flash('File deleted.', 'success')
    return redirect(_safe_next(crm_url('contact', person_id=person.id)) + '#files')
