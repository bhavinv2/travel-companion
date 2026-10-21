"""Workspace settings: modules, members, teams and roles (services/access.py does the deciding).

Everything here works on the workspace chosen in the header. Who may open each screen is itself a
page in the registry (ws_settings, ws_members, ws_teams, ws_roles, ws_all), so running a
workspace can be handed to somebody without making them a site admin.

Two guard rails, because these are the screens that can lock people out:
  * the owner cannot be removed or demoted, and nobody can change their own membership here --
    the classic way to lose a workspace is somebody tidying up their own role;
  * the Administrator role's pages cannot be edited: it is always every page.
"""
import json
import secrets
from functools import wraps

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user

from app import db
from app.models import ActivityEvent, User, WorkspaceMember, WorkspaceRole, WorkspaceTeam
from app.services import access, crm_scope, urls

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


def _wants_json():
    """The Users screen's side panel posts with fetch and wants an answer, not a page."""
    return request.accept_mimetypes.best == 'application/json'


def _say(message, category, to, status=200):
    """A screen gets a flash and a redirect; the side panel gets the same words as JSON."""
    if _wants_json():
        ok = category in ('success', 'info')
        return jsonify({'success': True, 'message': message} if ok else {'error': message}), (status if not ok else 200)
    flash(message, category)
    return redirect(to)


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

def _new_staff_account(email, first_name=None):
    """A staff account for somebody new: a random password -- they set their own from the e-mailed link."""
    base = ''.join(ch for ch in email.split('@')[0] if ch.isalnum() or ch in '._')[:24] or 'staff'
    username, n = base, 2
    while User.query.filter(db.func.lower(User.username) == username.lower()).first():
        username, n = '%s%d' % (base[:22], n), n + 1
    user = User(email=email, username=username, first_name=(first_name or '').strip()[:60] or None, is_verified=True)
    user.set_password(secrets.token_urlsafe(18))
    user.set_roles(['cs'])
    db.session.add(user)
    db.session.flush()
    return user


def _send_set_password(user, ws):
    """The "you have been added" e-mail with a link to set a password. True when it went."""
    from app.services import mailer, tokens
    link = url_for('auth.reset_password', token=tokens.make_reset_token(user), _external=True)
    return mailer.send('[NRI Parent Service] You have been added to %s' % ws.name, [user.email],
                       'Hello %s,\n\n%s added you to the %s workspace on NRI Parent Service.\n'
                       'Set your password here: %s\n\nSign in: %s'
                       % (user.first_name or user.username, current_user.full_name or 'An admin', ws.name,
                          link, url_for('auth.login', _external=True)),
                       category='account', account=True)


def _person(u):
    """An account as the add form's people picker shows it."""
    return {'id': u.id, 'name': u.full_name or u.username, 'email': u.email or '', 'username': u.username or '',
            'staff': bool(u.is_admin or u.is_cs)}


@workspace_bp.route('/members')
@staff_page
def members():
    """Team members. ?add=1 opens the add form; ?email= (or an address in ?add=) fills in the invite, and
    ?user=<id> (repeatable) picks existing accounts -- Users sends people here to add them."""
    ws = _ws()
    rows = sorted(ws.members, key=lambda m: (not m.is_owner, (m.user.full_name or m.user.email or '').lower()))
    teams = {m.id: access.teams_of(m) for m in rows}
    add = request.args.get('add', '')
    prefill = (request.args.get('email') or (add if '@' in add else '')).strip()[:254]
    have = {m.user_id for m in rows}
    ids = [int(i) for i in request.args.getlist('user') if i.isdigit()][:100]
    picked = [_person(u) for u in User.query.filter(User.id.in_(ids), User.is_active.is_(True)).all()
              if u.id not in have] if ids else []
    return render_template('workspace/members.html', ws=ws, rows=rows, teams=teams, prefill=prefill, picked=picked,
                           open_add=bool(add or prefill or ids), can_open={m.id: access.can_open_summary(m) for m in rows})


@workspace_bp.route('/members/find')
@staff_page
def member_search():
    """The add form's people picker: active accounts that are not in this workspace yet, by name, username,
    e-mail or phone -- travellers too, since anybody with an account can be made a member of staff. ?any=1
    (the New workspace flow) leaves this workspace's members in: they can join the new one as well."""
    from sqlalchemy import and_, or_
    from app.services import phone as phone_svc
    ws = _ws()
    q = ' '.join((request.args.get('q') or '').split())[:80]
    if len(q) < 2:
        return jsonify({'items': []})
    pat = '%%%s%%' % q
    conds = [User.username.ilike(pat), User.email.ilike(pat), User.first_name.ilike(pat), User.last_name.ilike(pat),
             phone_svc.matches(User.phone, q)]
    words = q.split()
    if len(words) > 1:
        conds.append(and_(User.first_name.ilike('%%%s%%' % words[0]), User.last_name.ilike('%%%s%%' % words[-1])))
    have = set() if request.args.get('any') else {m.user_id for m in ws.members}
    found = (User.query.filter(or_(*conds), User.is_active.is_(True))
             .order_by(User.first_name, User.username).limit(40).all())
    return jsonify({'items': [_person(u) for u in found if u.id not in have][:20]})


@workspace_bp.route('/members/add', methods=['POST'])
@staff_page
def add_member():
    """Add people: accounts picked from the site's users (user_ids -- a traveller account becomes staff as well,
    keeping its own roles), and/or one e-mail address -- an existing account joins, a new address gets a staff
    account and, if asked, the set-password e-mail. Everybody added gets the same role and teams."""
    from app.routes.auth import EMAIL_RE
    ws = _ws()
    back = url_for('workspace.members', add=1)
    role = _role_or_none(ws, request.form.get('role_id'))
    teams = _teams_from(ws, request.form.getlist('team_ids'))
    ids = {int(i) for i in request.form.getlist('user_ids') if str(i).isdigit()}
    people = User.query.filter(User.id.in_(ids), User.is_active.is_(True)).order_by(User.id).all() if ids else []
    email = (request.form.get('email') or '').strip().lower()
    if email and not EMAIL_RE.match(email):
        return _say('That e-mail address does not look right.', 'warning', back, 400)
    if not people and not email:
        return _say('Pick somebody from the list, or enter the e-mail address of a new person.', 'warning', back, 400)
    created = None
    if email:
        user = User.query.filter(db.func.lower(User.email) == email).first()
        if user is None:
            user = created = _new_staff_account(email, request.form.get('first_name'))
        if all(p.id != user.id for p in people):
            people.append(user)
    have = {m.user_id for m in WorkspaceMember.query.filter_by(workspace_id=ws.id)}
    added, already = [], []
    for u in people:
        if u.id in have:
            already.append(u)
            continue
        _log('workspace_member_added', workspace=ws.id, user_id=u.id, role=role.name if role else None)
        access.add_member(ws, u, role=role, teams=teams, by=current_user)
        added.append(u)
    db.session.commit()
    sent = False
    if created is not None and created in added and request.form.get('send_link'):
        sent = _send_set_password(created, ws)
    name = lambda u: u.full_name or u.username or u.email                             # noqa: E731
    said = []
    if added:
        said.append(('Added %s%s.' % (', '.join(name(u) for u in added),
                                      ' and sent a set-password e-mail' if sent else ''), 'success'))
    if already:
        said.append(('Already a member: %s.' % ', '.join(name(u) for u in already), 'info'))
    if _wants_json():
        return jsonify({'success': True, 'message': ' '.join(s for s, _ in said)})
    for s, category in said:
        flash(s, category)
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
                           takers=[u for u in crm_scope.in_workspace(cs_access.recipients('crm_board', limit=None), ws.id)
                                   if u.id != m.user_id],
                           is_self=(m.user_id == current_user.id and not current_user.is_admin))


@workspace_bp.route('/members/<int:member_id>', methods=['POST'])
@staff_page
def save_member(member_id):
    ws = _ws()
    m = _member_or_404(ws, member_id)
    if m.user_id == current_user.id and not current_user.is_admin:
        return _say('Ask another admin to change your own access.', 'warning',
                    url_for('workspace.member', member_id=m.id), 400)
    role = _role_or_none(ws, request.form.get('role_id'))
    teams = _teams_from(ws, request.form.getlist('team_ids'))
    access.add_member(ws, m.user, role=role, teams=teams, owner=m.is_owner, by=current_user)
    _log('workspace_member_saved', workspace=ws.id, user_id=m.user_id, role=role.name if role else None,
         teams=[t.name for t in teams])
    db.session.commit()
    return _say('Saved %s.' % (m.user.full_name or m.user.email), 'success', url_for('workspace.members'))


@workspace_bp.route('/members/<int:member_id>/remove', methods=['POST'])
@staff_page
def remove_member(member_id):
    ws = _ws()
    m = _member_or_404(ws, member_id)
    if m.user_id == current_user.id and not current_user.is_admin:
        return _say('You cannot remove yourself.', 'warning', url_for('workspace.members'), 400)
    who = m.user.full_name or m.user.email
    from app.services import cs_access
    # their open leads and follow-ups go first: to a person, or to whoever is least busy (in a team)
    hand = request.form.get('hand') or 'least'
    to = team = None
    if hand == 'person':
        to = db.session.get(User, request.form.get('to_id', type=int) or 0)
        if to is None or to.id == m.user_id or to not in crm_scope.in_workspace(
                cs_access.recipients('crm_board', limit=None), ws.id):
            return _say('Choose who gets their leads.', 'warning', url_for('workspace.member', member_id=m.id), 400)
    else:
        tid = request.form.get('team_id', type=int)
        team = next((t for t in ws.teams if t.id == tid), None)
    try:
        moved = access.remove_member(m, hand_over={'to': to, 'team': team}, by=current_user)
    except ValueError as exc:
        db.session.rollback()
        return _say(str(exc), 'warning', url_for('workspace.member', member_id=m.id) if not m.is_owner
                    else url_for('workspace.members'), 400)
    _log('workspace_member_removed', workspace=ws.id, user=who)
    db.session.commit()
    said = '%s is no longer in %s.' % (who, ws.name)
    if moved and (moved[0] or moved[1]):
        said += ' %d lead%s and %d follow-up%s were handed over.' % (
            moved[0], '' if moved[0] == 1 else 's', moved[1], '' if moved[1] == 1 else 's')
    return _say(said, 'success', url_for('workspace.members'))


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


# -------------------------------------------------------------------------------- menu builder

def _layout_from(raw):
    try:
        return access.clean_layout(json.loads(raw) if isinstance(raw, str) else raw)
    except ValueError:
        return None


@workspace_bp.route('/menu')
@staff_page
def menu():
    """Menu builder: this workspace's staff menu -- sections, sub-menus, the order of lines, their names, lines
    left off. Who sees a line is still their roles; the preview shows each role's menu as it would be."""
    ws = _ws()
    lines = [{'key': k, 'label': access.PAGES[k]['label'], 'icon': access.PAGES[k]['icon'],
              'area': access.MODULE_BY_KEY[access.PAGES[k]['module']]['label'],
              'tip': access.PAGES[k]['tip'] or access.PAGES[k]['desc']} for k in access.MENU_PAGES]
    roles = sorted(ws.roles, key=lambda r: (r.system_key != 'admin', r.system_key != 'cs', r.name.lower()))
    return render_template('workspace/menu.html', ws=ws, ws_tab='ws_menu', layout=access.menu_layout(ws),
                           lines=lines, roles=roles, icons=access.MENU_ICONS, custom=bool(ws.menu))


@workspace_bp.route('/menu/preview', methods=['POST'])
@staff_page
def menu_preview():
    """The menu one role would see with the layout on screen (not saved yet)."""
    ws = _ws()
    data = request.get_json(silent=True) or {}
    layout = _layout_from(data.get('layout')) or access.default_layout()
    return jsonify({'groups': access.menu_for_role(ws, _role_or_none(ws, data.get('role')), layout)})


@workspace_bp.route('/menu/save', methods=['POST'])
@staff_page
def save_menu():
    ws = _ws()
    layout = _layout_from(request.form.get('layout'))
    if layout is None:
        flash('That menu could not be read. Nothing was changed.', 'danger')
        return redirect(url_for('workspace.menu'))
    # the same as the menu in code: keep following the code, so a screen added later lands where it belongs
    ws.menu = None if layout == access.clean_layout(access.default_layout()) else layout
    _log('workspace_menu_saved', workspace=ws.id, custom=bool(ws.menu))
    db.session.commit()
    flash('Menu saved. Everybody in %s sees it on their next page.' % ws.name, 'success')
    return redirect(url_for('workspace.menu'))


@workspace_bp.route('/menu/reset', methods=['POST'])
@staff_page
def reset_menu():
    ws = _ws()
    ws.menu = None
    _log('workspace_menu_reset', workspace=ws.id)
    db.session.commit()
    flash('The menu is back to the standard one.', 'success')
    return redirect(url_for('workspace.menu'))


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
                'pages': [p for p in m['pages'] if (not p['with'] or p['grant']) and p['key'] not in access.SUPER_ONLY]}
               for m in access.MODULES]
    from app.services import crm_access
    return render_template('workspace/role.html', ws=ws, r=r, modules=modules, chosen=chosen,
                           CRM_SCOPES=crm_access.SCOPE_LABELS, copy_of=copy_of, locked=bool(r and r.system_key == 'admin'))


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
        scope = request.form.get('crm_scope')
        r.crm_scope = scope if scope in ('team', 'own') else None          # NULL: everyone's leads, as always
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
    _seed_crm(ws)
    access.set_current_workspace(ws)
    flash('%s is ready. Add its members and roles below.' % ws.name, 'success')
    return redirect(url_for('workspace.overview'))


# --------------------------------------------------------------------- + New workspace, in one flow

# the roles every workspace starts with (access.create_workspace), as the flow names them
NEW_ROLES = (('admin', 'Administrator'), ('lead', 'Team lead'), ('cs', 'Sales & service'), ('', 'No role (teams only)'))


def _start_roles(ws):
    return {'admin': access.system_role(ws, 'admin'), 'cs': access.system_role(ws, 'cs'),
            'lead': next((r for r in ws.roles if r.name == 'Team lead'), None), '': None}


def _create_from_plan(plan):
    """Make a whole workspace from the flow's plan: {name, description, modules, phone, people: [{id, role}],
    invites: [{email, first_name, role}], teams: [{name, role, members: ['me' | 'u<id>' | 'e<email>']}],
    send_links}. Everything is checked before anything is made, and it is made in one transaction: a
    half-made workspace is never left behind. Returns (errors, workspace, accounts made)."""
    from app.routes.auth import EMAIL_RE
    from app.services import phone as phone_svc
    roles_ok = {k for k, _ in NEW_ROLES}
    errors = []
    name = ' '.join(str(plan.get('name') or '').split())[:120]
    if not name:
        errors.append('Give the workspace a name.')
    picked = set(plan.get('modules') or []) | access.REQUIRED_MODULES
    modules = [k for k in access.MODULE_KEYS if k in picked]
    phone, problem = phone_svc.normalise(str(plan.get('phone') or ''), 'IN')
    problem = problem or (phone and phone_svc.length_error(phone))
    if problem:
        errors.append('WhatsApp number: %s' % problem)
    members = {'me': (current_user, 'admin')}                 # ref -> (user, role key); the maker is the owner
    for p in plan.get('people') or []:
        u = db.session.get(User, int(p.get('id') or 0)) if str(p.get('id') or '').isdigit() else None
        if u is None or not u.is_active:
            errors.append('One of the people picked is not an active account any more.')
        elif u.id != current_user.id:
            members['u%d' % u.id] = (u, p.get('role') if p.get('role') in roles_ok else 'cs')
    invites = []
    for i in plan.get('invites') or []:
        email = str(i.get('email') or '').strip().lower()
        if not EMAIL_RE.match(email):
            errors.append('"%s" is not an e-mail address.' % email[:80])
        else:
            invites.append((email, str(i.get('first_name') or ''), i.get('role') if i.get('role') in roles_ok else 'cs'))
    teams, seen = [], set()
    for t in plan.get('teams') or []:
        tname = ' '.join(str(t.get('name') or '').split())[:80]
        if not tname:
            errors.append('Every team needs a name.')
        elif tname.lower() in seen:
            errors.append('Two teams are called "%s".' % tname)
        else:
            seen.add(tname.lower())
            teams.append((tname, t.get('role') if t.get('role') in roles_ok else '', list(t.get('members') or [])))
    if errors:
        return errors, None, []

    ws = access.create_workspace(name, by=current_user, modules=None if len(modules) == len(access.MODULE_KEYS) else modules,
                                 description=plan.get('description'))
    ws.whatsapp_phone = phone or None
    roles = _start_roles(ws)
    made = []
    for email, first, role in invites:
        u = User.query.filter(db.func.lower(User.email) == email).first()
        if u is None:
            u = _new_staff_account(email, first)
            made.append(u)
        if u.id != current_user.id:
            members.setdefault('u%d' % u.id, (u, role))
        members['e' + email] = members.get('u%d' % u.id, members['me'])
    team_rows = []
    for tname, role, refs in teams:
        t = WorkspaceTeam(workspace_id=ws.id, name=tname, role=roles.get(role))
        db.session.add(t)
        team_rows.append((t, refs))
    db.session.flush()
    in_teams = {}
    for t, refs in team_rows:
        for ref in refs:
            if ref in members:
                in_teams.setdefault(members[ref][0].id, []).append(t)
    done = set()
    for ref, (u, role) in members.items():
        if u.id in done:
            continue
        done.add(u.id)
        if u.id == current_user.id:                           # already the owner: just their teams
            m = WorkspaceMember.query.filter_by(workspace_id=ws.id, user_id=u.id).first()
            access.set_teams(m, in_teams.get(u.id, []))
        else:
            access.add_member(ws, u, role=roles.get(role), teams=in_teams.get(u.id, []), by=current_user, commit=False)
    _log('workspace_created', workspace=ws.id, name=ws.name, people=len(done), teams=len(team_rows),
         whatsapp=ws.whatsapp_phone)
    db.session.commit()
    _seed_crm(ws)
    access.set_current_workspace(ws)
    return [], ws, made


def _seed_crm(ws):
    """A new workspace's own Sales CRM: a copy of the starting pipelines, products, lead sources and ready answers
    (Sales CRM 2.0, run 5a). Best effort: the first CRM page opened in the workspace makes them anyway."""
    try:
        crm_scope.seed(ws.id)
    except Exception:          # noqa: BLE001 -- the workspace is made; never undo it for its CRM set-up
        db.session.rollback()
        current_app.logger.exception('CRM defaults not seeded for workspace %s', ws.id)


@workspace_bp.route('/new', methods=['GET', 'POST'])
@staff_page
def new_workspace():
    """+ New workspace, in one flow: its name and areas, its people and their roles, its teams and its business
    WhatsApp number -- set up from one screen and made in one go, instead of five screens one after another."""
    _ws()
    from app.services import wacrm_team
    linked = wacrm_team.linked_workspace()
    ctx = dict(modules=access.MODULES, roles=NEW_ROLES, linked=linked,
               linked_wa=wacrm_team.number_of(linked) if linked else None,
               find_url=url_for('workspace.member_search', any=1), me=_person(current_user))
    if request.method == 'POST':
        try:
            plan = json.loads(request.form.get('plan') or '')
        except ValueError:
            plan = None
        if not isinstance(plan, dict):
            errors, ws, made = ['The setup could not be read. Nothing was made.'], None, []
        else:
            errors, ws, made = _create_from_plan(plan)
        if errors:
            db.session.rollback()
            if isinstance(plan, dict):                       # the people go back on screen with their names
                for p in plan.get('people') or []:
                    u = db.session.get(User, int(p['id'])) if str(p.get('id', '')).isdigit() else None
                    if u is not None:
                        p.update(name=u.full_name or u.username, email=u.email or '')
            return render_template('workspace/new.html', plan=plan if isinstance(plan, dict) else None,
                                   errors=errors, **ctx), 400
        sent = sum(1 for u in made if plan.get('send_links') and _send_set_password(u, ws))
        flash('%s is ready: %d %s%s.' % (ws.name, len(ws.members), 'person' if len(ws.members) == 1 else 'people',
                                         ', %d set-password e-mail%s sent' % (sent, '' if sent == 1 else 's') if sent else ''),
              'success')
        return redirect(url_for('workspace.members'))
    return render_template('workspace/new.html', plan=None, errors=[], **ctx)


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
