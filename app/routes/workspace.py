"""Workspace settings: modules, members, teams and roles (services/access.py does the deciding).

Everything here works on the workspace chosen in the header. Who may open each screen is itself a
page in the registry (ws_settings, ws_members, ws_teams, ws_roles, ws_all), so running a
workspace can be handed to somebody without making them a site admin.

Two guard rails, because these are the screens that can lock people out:
  * the owner cannot be removed or demoted, and nobody can change their own membership here --
    the classic way to lose a workspace is somebody tidying up their own role;
  * the Administrator role's pages cannot be edited: it is always every page.
"""
import secrets
from functools import wraps

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app import db
from app.models import ActivityEvent, User, WorkspaceMember, WorkspaceRole, WorkspaceTeam
from app.services import access, urls

workspace_bp = Blueprint('workspace', __name__, url_prefix='/admin/workspace')


def staff_page(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login', next=urls.here()))
        if not access.allowed(current_user, request.endpoint, fallback=lambda u: u.is_admin):
            flash('Your role does not include that page.', 'warning')
            return redirect(access.home_url(current_user) if access.is_staff(current_user) else url_for('main.index'))
        return f(*args, **kwargs)
    return decorated


def _ws():
    """The workspace these screens work on. The very first visit makes it (from today's admins
    and agents), so there is never an empty screen to start from."""
    ws = access.current_workspace(current_user)
    if ws is None:
        ws = access.ensure_defaults()
    if ws is None:
        abort(404)
    return ws


def _member_or_404(ws, member_id):
    m = db.session.get(WorkspaceMember, member_id)
    if m is None or m.workspace_id != ws.id:
        abort(404)
    return m


def _role_or_none(ws, role_id):
    try:
        rid = int(role_id or 0)
    except (TypeError, ValueError):
        return None
    return next((r for r in ws.roles if r.id == rid), None)


def _teams_from(ws, ids):
    wanted = {int(i) for i in ids if str(i).isdigit()}
    return [t for t in ws.teams if t.id in wanted]


def _log(kind, **data):
    ActivityEvent.log(kind, actor=current_user, **data)


# ----------------------------------------------------------------------------- overview

@workspace_bp.route('')
@staff_page
def overview():
    ws = _ws()
    on = set(access.enabled_modules(ws))
    modules = [{'key': m['key'], 'label': m['label'], 'icon': m['icon'], 'desc': m.get('desc', ''),
                'required': m.get('required', False), 'on': m['key'] in on,
                'pages': [p for p in m['pages'] if p['nav']]} for m in access.MODULES]
    from app.services import wacrm_team
    return render_template('workspace/overview.html', ws=ws, modules=modules,
                           counts={'members': len(ws.members), 'teams': len(ws.teams), 'roles': len(ws.roles)},
                           whatsapp=wacrm_team.status(ws))


@workspace_bp.route('/settings', methods=['POST'])
@staff_page
def save_settings():
    ws = _ws()
    name = (request.form.get('name') or '').strip()
    if not name:
        flash('The workspace needs a name.', 'warning')
        return redirect(url_for('workspace.overview'))
    ws.name = name[:120]
    ws.description = (request.form.get('description') or '').strip()[:255] or None
    if request.form.get('modules_sent'):
        chosen = set(request.form.getlist('modules')) | access.REQUIRED_MODULES
        picked = [k for k in access.MODULE_KEYS if k in chosen]
        ws.modules = None if len(picked) == len(access.MODULE_KEYS) else picked
    _log('workspace_saved', workspace=ws.id, modules=ws.modules)
    db.session.commit()
    from app.services import wacrm_team
    wacrm_team.workspace_changed(ws)
    flash('Workspace saved.', 'success')
    return redirect(url_for('workspace.overview'))


# ------------------------------------------------------------------------------ members

@workspace_bp.route('/members')
@staff_page
def members():
    """Team members. ?add=1 opens the add form; ?email= (or an address in ?add=) fills it in -- Users
    sends somebody here to add a member of staff."""
    ws = _ws()
    rows = sorted(ws.members, key=lambda m: (not m.is_owner, (m.user.full_name or m.user.email or '').lower()))
    teams = {m.id: access.teams_of(m) for m in rows}
    add = request.args.get('add', '')
    prefill = (request.args.get('email') or (add if '@' in add else '')).strip()[:254]
    return render_template('workspace/members.html', ws=ws, rows=rows, teams=teams, prefill=prefill,
                           open_add=bool(add or prefill), can_open={m.id: access.can_open_summary(m) for m in rows})


@workspace_bp.route('/members/add', methods=['POST'])
@staff_page
def add_member():
    """Add somebody by e-mail. An existing account joins; a new address gets a staff account
    and, if asked, the set-password e-mail."""
    from app.routes.auth import EMAIL_RE
    from app.services import mailer, tokens
    ws = _ws()
    email = (request.form.get('email') or '').strip().lower()
    if not EMAIL_RE.match(email):
        flash('Enter the e-mail address of the person to add.', 'warning')
        return redirect(url_for('workspace.members'))
    role = _role_or_none(ws, request.form.get('role_id'))
    teams = _teams_from(ws, request.form.getlist('team_ids'))
    user = User.query.filter(db.func.lower(User.email) == email).first()
    created = user is None
    if created:
        first = (request.form.get('first_name') or '').strip()[:60] or None
        base = ''.join(ch for ch in email.split('@')[0] if ch.isalnum() or ch in '._')[:24] or 'staff'
        username, n = base, 2
        while User.query.filter(db.func.lower(User.username) == username.lower()).first():
            username, n = '%s%d' % (base[:22], n), n + 1
        user = User(email=email, username=username, first_name=first, is_verified=True)
        user.set_password(secrets.token_urlsafe(18))
        user.set_roles(['cs'])
        db.session.add(user)
        db.session.flush()
    elif WorkspaceMember.query.filter_by(workspace_id=ws.id, user_id=user.id).first():
        flash('%s is already a member.' % email, 'info')
        return redirect(url_for('workspace.members'))
    access.add_member(ws, user, role=role, teams=teams, by=current_user)
    _log('workspace_member_added', workspace=ws.id, user_id=user.id, role=role.name if role else None)
    db.session.commit()
    sent = False
    if created and request.form.get('send_link'):
        link = url_for('auth.reset_password', token=tokens.make_reset_token(user), _external=True)
        sent = mailer.send('[NRI Parent Service] You have been added to %s' % ws.name, [email],
                           'Hello %s,\n\n%s added you to the %s workspace on NRI Parent Service.\n'
                           'Set your password here: %s\n\nSign in: %s'
                           % (user.first_name or user.username, current_user.full_name or 'An admin', ws.name,
                              link, url_for('auth.login', _external=True)),
                           category='account', account=True)
    flash('%s added%s.' % (email, ' and sent a set-password e-mail' if sent else ''), 'success')
    return redirect(url_for('workspace.members'))


@workspace_bp.route('/members/<int:member_id>')
@staff_page
def member(member_id):
    ws = _ws()
    m = _member_or_404(ws, member_id)
    pages = access._member_pages(m)
    by_module = [{'label': mod['label'], 'icon': mod['icon'],
                  'pages': [p['label'] for p in mod['pages'] if p['key'] in pages]}
                 for mod in access.MODULES if mod['key'] in access.enabled_modules(ws)]
    from app.models import CrmLead, CrmTask
    from app.services import cs_access
    return render_template('workspace/member.html', ws=ws, m=m, teams=access.teams_of(m),
                           by_module=[b for b in by_module if b['pages']],
                           open_leads=CrmLead.query.filter_by(owner_id=m.user_id, status='open').count(),
                           open_tasks=CrmTask.query.filter_by(owner_id=m.user_id, status='open').count(),
                           takers=[u for u in cs_access.recipients('crm_board', limit=None) if u.id != m.user_id],
                           is_self=(m.user_id == current_user.id and not current_user.is_admin))


@workspace_bp.route('/members/<int:member_id>', methods=['POST'])
@staff_page
def save_member(member_id):
    ws = _ws()
    m = _member_or_404(ws, member_id)
    if m.user_id == current_user.id and not current_user.is_admin:
        flash('Ask another admin to change your own access.', 'warning')
        return redirect(url_for('workspace.member', member_id=m.id))
    role = _role_or_none(ws, request.form.get('role_id'))
    teams = _teams_from(ws, request.form.getlist('team_ids'))
    access.add_member(ws, m.user, role=role, teams=teams, owner=m.is_owner, by=current_user)
    _log('workspace_member_saved', workspace=ws.id, user_id=m.user_id, role=role.name if role else None,
         teams=[t.name for t in teams])
    db.session.commit()
    flash('Saved %s.' % (m.user.full_name or m.user.email), 'success')
    return redirect(url_for('workspace.members'))


@workspace_bp.route('/members/<int:member_id>/remove', methods=['POST'])
@staff_page
def remove_member(member_id):
    ws = _ws()
    m = _member_or_404(ws, member_id)
    if m.user_id == current_user.id and not current_user.is_admin:
        flash('You cannot remove yourself.', 'warning')
        return redirect(url_for('workspace.members'))
    who = m.user.full_name or m.user.email
    from app.services import cs_access
    # their open leads and follow-ups go first: to a person, or to whoever is least busy (in a team)
    hand = request.form.get('hand') or 'least'
    to = team = None
    if hand == 'person':
        to = db.session.get(User, request.form.get('to_id', type=int) or 0)
        if to is None or to.id == m.user_id or to not in cs_access.recipients('crm_board', limit=None):
            flash('Choose who gets their leads.', 'warning')
            return redirect(url_for('workspace.member', member_id=m.id))
    else:
        tid = request.form.get('team_id', type=int)
        team = next((t for t in ws.teams if t.id == tid), None)
    try:
        moved = access.remove_member(m, hand_over={'to': to, 'team': team}, by=current_user)
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'warning')
        return redirect(url_for('workspace.member', member_id=m.id) if not m.is_owner
                        else url_for('workspace.members'))
    _log('workspace_member_removed', workspace=ws.id, user=who)
    db.session.commit()
    said = '%s is no longer in %s.' % (who, ws.name)
    if moved and (moved[0] or moved[1]):
        said += ' %d lead%s and %d follow-up%s were handed over.' % (
            moved[0], '' if moved[0] == 1 else 's', moved[1], '' if moved[1] == 1 else 's')
    flash(said, 'success')
    return redirect(url_for('workspace.members'))


# -------------------------------------------------------------------------------- teams

@workspace_bp.route('/teams')
@staff_page
def teams():
    ws = _ws()
    return render_template('workspace/teams.html', ws=ws)


@workspace_bp.route('/teams/<int:team_id>')
@staff_page
def team(team_id):
    ws = _ws()
    t = next((t for t in ws.teams if t.id == team_id), None) if team_id else None
    if team_id and t is None:
        abort(404)
    people = sorted(ws.members, key=lambda m: (m.user.full_name or m.user.email or '').lower())
    return render_template('workspace/team.html', ws=ws, t=t, people=people,
                           inside={u.id for u in t.users} if t else set())


@workspace_bp.route('/teams/save', methods=['POST'])
@staff_page
def save_team():
    ws = _ws()
    tid = request.form.get('team_id', type=int)
    t = next((t for t in ws.teams if t.id == tid), None) if tid else None
    name = (request.form.get('name') or '').strip()[:80]
    if not name:
        flash('The team needs a name.', 'warning')
        return redirect(url_for('workspace.team', team_id=tid or 0))
    clash = WorkspaceTeam.query.filter(WorkspaceTeam.workspace_id == ws.id, db.func.lower(WorkspaceTeam.name) == name.lower(),
                                       WorkspaceTeam.id != (t.id if t else 0)).first()
    if clash:
        flash('There is already a team called %s.' % name, 'warning')
        return redirect(url_for('workspace.team', team_id=tid or 0))
    if t is None:
        t = WorkspaceTeam(workspace_id=ws.id, name=name)
        db.session.add(t)
    t.name = name
    t.description = (request.form.get('description') or '').strip()[:255] or None
    role = _role_or_none(ws, request.form.get('role_id'))
    t.role_id = role.id if role else None
    wanted = {int(i) for i in request.form.getlist('user_ids') if i.isdigit()}
    member_ids = {m.user_id for m in ws.members}
    t.users = [m.user for m in ws.members if m.user_id in wanted & member_ids]
    db.session.flush()
    _log('workspace_team_saved', workspace=ws.id, team=t.name, people=len(t.users))
    db.session.commit()
    from app.services import wacrm_team
    for m in ws.members:
        if m.user_id in wanted or m.user_id in {u.id for u in t.users}:
            wacrm_team.member_changed(m)
    flash('Team %s saved.' % t.name, 'success')
    return redirect(url_for('workspace.teams'))


@workspace_bp.route('/teams/<int:team_id>/delete', methods=['POST'])
@staff_page
def delete_team(team_id):
    ws = _ws()
    t = next((t for t in ws.teams if t.id == team_id), None)
    if t is None:
        abort(404)
    affected = [m for m in ws.members if m.user in t.users]
    name = t.name
    t.users = []
    db.session.delete(t)
    _log('workspace_team_deleted', workspace=ws.id, team=name)
    db.session.commit()
    from app.services import wacrm_team
    for m in affected:
        wacrm_team.member_changed(m)
    flash('Team %s deleted.' % name, 'success')
    return redirect(url_for('workspace.teams'))


# -------------------------------------------------------------------------------- roles

@workspace_bp.route('/roles')
@staff_page
def roles():
    ws = _ws()
    return render_template('workspace/roles.html', ws=ws, used=access.who_has(ws),
                           pages_of={r.id: access.role_pages(r) for r in ws.roles})


@workspace_bp.route('/roles/<int:role_id>')
@staff_page
def role(role_id):
    ws = _ws()
    r = next((r for r in ws.roles if r.id == role_id), None) if role_id else None
    if role_id and r is None:
        abort(404)
    copy_of = _role_or_none(ws, request.args.get('copy'))
    chosen = access.role_pages(r) if r else (access.role_pages(copy_of) if copy_of else frozenset())
    on = set(access.enabled_modules(ws))
    modules = [{'key': m['key'], 'label': m['label'], 'icon': m['icon'], 'desc': m.get('desc', ''), 'on': m['key'] in on,
                'pages': [p for p in m['pages'] if not p['with']]} for m in access.MODULES]
    return render_template('workspace/role.html', ws=ws, r=r, modules=modules, chosen=chosen,
                           copy_of=copy_of, locked=bool(r and r.system_key == 'admin'))


@workspace_bp.route('/roles/save', methods=['POST'])
@staff_page
def save_role():
    ws = _ws()
    rid = request.form.get('role_id', type=int)
    r = next((r for r in ws.roles if r.id == rid), None) if rid else None
    name = (request.form.get('name') or '').strip()[:80]
    if not name:
        flash('The role needs a name.', 'warning')
        return redirect(url_for('workspace.role', role_id=rid or 0))
    clash = WorkspaceRole.query.filter(WorkspaceRole.workspace_id == ws.id, db.func.lower(WorkspaceRole.name) == name.lower(),
                                       WorkspaceRole.id != (r.id if r else 0)).first()
    if clash:
        flash('There is already a role called %s.' % name, 'warning')
        return redirect(url_for('workspace.role', role_id=rid or 0))
    if r is None:
        r = WorkspaceRole(workspace_id=ws.id, name=name)
        db.session.add(r)
        ws.roles.append(r)
    r.name = name
    r.description = (request.form.get('description') or '').strip()[:255] or None
    if r.system_key != 'admin':
        r.pages = access.clean_pages(request.form.getlist('pages'), keep=r.pages or [])
    db.session.flush()
    _log('workspace_role_saved', workspace=ws.id, role=r.name, pages=len(access.role_pages(r)))
    db.session.commit()
    from app.services import wacrm_team
    for m in ws.members:
        wacrm_team.member_changed(m)
    flash('Role %s saved.' % r.name, 'success')
    return redirect(url_for('workspace.roles'))


@workspace_bp.route('/roles/<int:role_id>/delete', methods=['POST'])
@staff_page
def delete_role(role_id):
    ws = _ws()
    r = next((r for r in ws.roles if r.id == role_id), None)
    if r is None:
        abort(404)
    if r.system_key:
        flash('%s comes with every workspace and cannot be deleted.' % r.name, 'warning')
        return redirect(url_for('workspace.roles'))
    affected = [m for m in ws.members if m.role_id == r.id]
    for m in affected:
        m.role_id = None
    for t in ws.teams:
        if t.role_id == r.id:
            t.role_id = None
    name = r.name
    ws.roles.remove(r)
    db.session.delete(r)
    _log('workspace_role_deleted', workspace=ws.id, role=name, members=len(affected))
    db.session.commit()
    flash('Role %s deleted.%s' % (name, ' %d member(s) now have no role of their own.' % len(affected) if affected else ''),
          'success')
    return redirect(url_for('workspace.roles'))


# --------------------------------------------------------------------- all workspaces

@workspace_bp.route('/all')
@staff_page
def all_workspaces():
    _ws()
    spaces = access.workspaces_for(current_user)
    return render_template('workspace/all.html', spaces=spaces, current=access.current_workspace(current_user),
                           modules=access.MODULES)


@workspace_bp.route('/create', methods=['POST'])
@staff_page
def create_workspace():
    name = (request.form.get('name') or '').strip()
    if not name:
        flash('The workspace needs a name.', 'warning')
        return redirect(url_for('workspace.all_workspaces'))
    modules = [k for k in access.MODULE_KEYS if k in set(request.form.getlist('modules')) | access.REQUIRED_MODULES]
    ws = access.create_workspace(name, by=current_user,
                                 modules=None if len(modules) == len(access.MODULE_KEYS) else modules,
                                 description=request.form.get('description'))
    _log('workspace_created', workspace=ws.id, name=ws.name)
    db.session.commit()
    access.set_current_workspace(ws)
    flash('%s is ready. Add its members and roles below.' % ws.name, 'success')
    return redirect(url_for('workspace.overview'))


@workspace_bp.route('/switch/<int:ws_id>')
@staff_page
def switch(ws_id):
    ws = next((w for w in access.workspaces_for(current_user) if w.id == ws_id), None)
    if ws is None:
        abort(404)
    access.set_current_workspace(ws)
    # back to the page they were on (inside this app only); a page the new workspace does not
    # give them is turned away by the guard on arrival, to their home in it
    return redirect(urls.safe_next(request.args.get('next')) or access.home_url(current_user))


# ---------------------------------------------------------------------- the WhatsApp CRM

@workspace_bp.route('/whatsapp/<action>', methods=['POST'])
@staff_page
def whatsapp(action):
    """Moved: linking, checking and unlinking the WhatsApp team are on Set-up -> WhatsApp connection now. 307 keeps
    the form (its csrf token, remove-extra's e-mail)."""
    if action not in ('link', 'sync', 'unlink', 'remove-extra'):
        abort(404)
    return redirect(url_for('admin_crm.connection_team', action=action), code=307)
