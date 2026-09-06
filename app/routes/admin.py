from functools import wraps
import os
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, current_app
from flask_login import login_required, current_user, login_user
from app import db, mail
from app.models import User, CompanionRequest, Feedback, Blog, Notification, AppSetting, USER_ROLES
from flask_mail import Message as MailMessage
from datetime import datetime, timedelta
from slugify import slugify

admin_bp = Blueprint('admin', __name__)


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Admin access required.', 'danger')
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated


def _page_args(default_per=25):
    """Read ?page= and ?per_page= safely (per_page capped at 100)."""
    try:
        page = max(int(request.args.get('page') or 1), 1)
    except ValueError:
        page = 1
    try:
        per_page = min(max(int(request.args.get('per_page') or default_per), 1), 100)
    except ValueError:
        per_page = default_per
    return page, per_page


@admin_bp.route('/login', methods=['GET', 'POST'])
def admin_login():
    if current_user.is_authenticated and current_user.is_admin:
        return redirect(url_for('admin.dashboard'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password) and user.is_admin and user.is_active:
            login_user(user)
            user.last_login = datetime.utcnow()
            db.session.commit()
            return redirect(url_for('admin.dashboard'))
        flash('Invalid credentials or not an admin account.', 'danger')
    return render_template('admin/login.html')


@admin_bp.route('/')
@login_required
@admin_required
def dashboard():
    stats = {
        'total_users': User.query.count(),
        'active_listings': CompanionRequest.query.filter(CompanionRequest.status.in_(['open', 'matched'])).count(),
        'total_messages': Notification.query.count(),
        'pending_feedback': Feedback.query.filter_by(is_approved=False).count(),
    }
    recent_users = User.query.order_by(User.created_at.desc()).limit(10).all()
    recent_trips = CompanionRequest.query.order_by(CompanionRequest.created_at.desc()).limit(10).all()
    return render_template('admin/dashboard.html', stats=stats, recent_users=recent_users, recent_trips=recent_trips)


@admin_bp.route('/users')
@login_required
@admin_required
def users():
    search = request.args.get('q', '')
    query = User.query
    if search:
        query = query.filter(
            (User.username.ilike(f'%{search}%')) | (User.email.ilike(f'%{search}%'))
        )
    page, per_page = _page_args(25)
    total = query.count()
    pages = max((total + per_page - 1) // per_page, 1)
    page = min(page, pages)
    users_list = query.order_by(User.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    from app import options
    return render_template('admin/users.html', users=users_list, search=search, roles=options.role_defs(),
                           role_labels=options.role_labels(), page=page, pages=pages, total=total)


@admin_bp.route('/users/<int:user_id>/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        return jsonify({'error': 'You cannot deactivate yourself.'}), 400
    user.is_active = not user.is_active
    db.session.commit()
    return jsonify({'success': True, 'is_active': user.is_active})


@admin_bp.route('/users/<int:user_id>/role', methods=['POST'])
@login_required
@admin_required
def set_user_role(user_id):
    """Legacy single-role endpoint (kept for old clients); prefer /users/<id>/roles."""
    user = User.query.get_or_404(user_id)
    data = request.get_json(silent=True) or request.form
    role = data.get('role')
    if role not in USER_ROLES:
        return jsonify({'error': 'Invalid role'}), 400
    if user.id == current_user.id and role != 'admin':
        return jsonify({'error': 'You cannot remove your own admin role.'}), 400
    user.set_roles([role])
    db.session.commit()
    return jsonify({'success': True, 'role': role})


@admin_bp.route('/users/<int:user_id>/roles', methods=['POST'])
@login_required
@admin_required
def set_user_roles(user_id):
    """Assign any combination of roles to an account (roles are defined at /admin/options)."""
    from app import options
    from app.models import ActivityEvent
    user = User.query.get_or_404(user_id)
    data = request.get_json(silent=True) or {}
    keys = data.get('roles') or []
    if not isinstance(keys, list):
        return jsonify({'error': 'roles must be a list'}), 400
    known = {r['key'] for r in options.role_defs()}
    bad = [k for k in keys if k not in known]
    if bad:
        return jsonify({'error': f"Unknown role(s): {', '.join(map(str, bad))}"}), 400
    if user.id == current_user.id and not any(options.role_level(k) == 'admin' for k in keys):
        return jsonify({'error': 'You cannot remove your own admin access.'}), 400
    before = user.role_keys
    user.set_roles(keys)
    ActivityEvent.log('user_roles_changed', actor=current_user, user_id=user.id, before=before, after=user.role_keys)
    db.session.commit()
    return jsonify({'success': True, 'roles': user.role_keys, 'level': user.effective_role})


@admin_bp.route('/users/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_user():
    """Admins create accounts (travellers, CS agents, other admins) without going through sign-up."""
    import secrets
    from app import options
    from app.models import ActivityEvent
    from app.routes.auth import EMAIL_RE, USERNAME_RE
    from app.services import mailer, tokens
    roles = options.role_defs()
    form = request.form if request.method == 'POST' else {}
    if request.method == 'POST':
        email = (form.get('email') or '').strip().lower()
        username = (form.get('username') or '').strip()
        password = form.get('password') or ''
        keys = [k for k in form.getlist('roles') if k in {r['key'] for r in roles}] or ['user']
        errors = []
        if not email or not EMAIL_RE.match(email):
            errors.append('Valid e-mail is required.')
        if not USERNAME_RE.match(username):
            errors.append('Username must be 3-30 letters, digits, dots or underscores.')
        if password and len(password) < 8:
            errors.append('Password must be at least 8 characters (leave blank to generate one).')
        if email and User.query.filter_by(email=email).first():
            errors.append('E-mail already registered.')
        if username and User.query.filter(db.func.lower(User.username) == username.lower()).first():
            errors.append('Username already taken.')
        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('admin/user_new.html', roles=roles, form=form, selected_roles=keys), 200
        generated = None
        if not password:
            password = generated = secrets.token_urlsafe(9)
        user = User(email=email, username=username, first_name=(form.get('first_name') or '').strip() or None,
                    last_name=(form.get('last_name') or '').strip() or None, phone=(form.get('phone') or '').strip() or None,
                    is_verified=True)
        user.set_password(password)
        user.set_roles(keys)
        db.session.add(user)
        db.session.flush()
        ActivityEvent.log('user_created_by_admin', actor=current_user, user_id=user.id, roles=user.role_keys)
        db.session.commit()
        sent = False
        if form.get('send_link') == 'on':
            link = f"{current_app.config['SITE_URL']}/auth/reset/{tokens.make_reset_token(user)}"
            sent = mailer.send('[Connecting Desis] Your account is ready', [email],
                               f'Hello {user.first_name or user.username},\n\nAn account was created for you on Connecting Desis '
                               f'({", ".join(user.role_keys)}).\nSet your password here: {link}\n\nLogin: {current_app.config["SITE_URL"]}/auth/login',
                               category='account')
        flash(f'Account {email} created with roles: {", ".join(user.role_keys)}.' + (' Set-password e-mail sent.' if sent else ''), 'success')
        if generated:
            flash(f'Temporary password for {email}: {generated} - share it securely, it is not shown again.', 'info')
        return redirect(url_for('admin.users'))
    return render_template('admin/user_new.html', roles=roles, form=form, selected_roles=['user'])


@admin_bp.route('/messages')
@login_required
@admin_required
def messages_page():
    """One screen for every editable message: CS copy snippets + transactional e-mails."""
    from app.services import messages as msg
    groups = {'cs_copy': [], 'email': []}
    for key, spec in msg.TEMPLATES.items():
        eff = msg.effective(key)
        groups[spec['kind']].append({'key': key, 'title': spec['title'], 'help': spec.get('help', ''),
                                     'vars': spec.get('vars', []), 'subject': eff['subject'],
                                     'body': eff['body'], 'edited': eff['edited']})
    return render_template('admin/messages.html', groups=groups, custom=msg.custom_snippets())


def _check_jinja(*texts):
    from flask import current_app
    for t in texts:
        current_app.jinja_env.from_string(t or '')


@admin_bp.route('/messages/<key>', methods=['POST'])
@login_required
@admin_required
def save_message(key):
    from app.models import ActivityEvent
    from app.services import messages as msg
    if key not in msg.TEMPLATES:
        return jsonify({'error': 'Unknown template'}), 404
    p = request.get_json(silent=True) or {}
    try:
        _check_jinja(p.get('body'), p.get('subject'))
    except Exception as e:
        return jsonify({'error': f'Template error: {e}'}), 400
    eff = msg.save_override(key, p.get('subject'), p.get('body'), current_user)
    ActivityEvent.log('message_template_changed', actor=current_user, key=key, edited=eff['edited'])
    db.session.commit()
    return jsonify({'success': True, **eff})


@admin_bp.route('/messages/<key>/reset', methods=['POST'])
@login_required
@admin_required
def reset_message(key):
    from app.models import ActivityEvent
    from app.services import messages as msg
    if key not in msg.TEMPLATES:
        return jsonify({'error': 'Unknown template'}), 404
    eff = msg.save_override(key, '', '', current_user)
    ActivityEvent.log('message_template_changed', actor=current_user, key=key, edited=False)
    db.session.commit()
    return jsonify({'success': True, **eff})


@admin_bp.route('/messages/custom', methods=['POST'])
@login_required
@admin_required
def save_custom_snippets():
    from app.models import ActivityEvent
    from app.services import messages as msg
    p = request.get_json(silent=True) or {}
    items = p.get('items')
    if not isinstance(items, list):
        return jsonify({'error': 'items must be a list'}), 400
    try:
        for row in items:
            _check_jinja((row or {}).get('body'))
        clean = msg.set_custom(items, current_user)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': f'Template error: {e}'}), 400
    ActivityEvent.log('message_snippets_changed', actor=current_user, count=len(clean))
    db.session.commit()
    return jsonify({'success': True, 'items': clean})


@admin_bp.route('/messages/preview', methods=['POST'])
@login_required
@admin_required
def preview_message():
    from app.services import messages as msg
    p = request.get_json(silent=True) or {}
    ctx = msg.sample_ctx()
    try:
        return jsonify({'subject': msg.render_string(p.get('subject'), **ctx),
                        'body': msg.render_string(p.get('body'), **ctx)})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@admin_bp.route('/voices')
@login_required
@admin_required
def voices():
    """Everything users send us, in one place: enquiries from the Contact form and the
    reviews they leave. Mirrors the two tabs on the public "Talk to us" widget."""
    from app.models import ContactMessage, CONTACT_STATUSES, CONTACT_STATUS_LABELS
    tab = request.args.get('tab') or 'contact'
    if tab == 'reviews':          # older links used this name
        tab = 'feedback'
    if tab not in ('contact', 'feedback'):
        tab = 'contact'
    page, per_page = _page_args(25)

    status = request.args.get('status') or ''
    q = (request.args.get('q') or '').strip()
    cq = ContactMessage.query
    if status in CONTACT_STATUSES:
        cq = cq.filter(ContactMessage.status == status)
    if q:
        from sqlalchemy import or_
        pat = f'%{q}%'
        cq = cq.filter(or_(ContactMessage.name.ilike(pat), ContactMessage.email.ilike(pat),
                           ContactMessage.phone.ilike(pat), ContactMessage.message.ilike(pat)))
    cq = cq.order_by(ContactMessage.created_at.desc())
    c_total = cq.count()
    c_pages = max((c_total + per_page - 1) // per_page, 1)
    c_page = min(page, c_pages) if tab == 'contact' else 1
    messages = cq.offset((c_page - 1) * per_page).limit(per_page).all()
    counts = {s: ContactMessage.query.filter_by(status=s).count() for s in CONTACT_STATUSES}

    fq = Feedback.query.order_by(Feedback.created_at.desc())
    f_total = fq.count()
    f_pages = max((f_total + per_page - 1) // per_page, 1)
    f_page = min(page, f_pages) if tab == 'feedback' else 1
    feedbacks = fq.offset((f_page - 1) * per_page).limit(per_page).all()
    pending = Feedback.query.filter_by(is_approved=False).count()

    return render_template('admin/voices.html', tab=tab,
                           messages=messages, c_total=c_total, c_page=c_page, c_pages=c_pages,
                           counts=counts, status=status, q=q,
                           feedbacks=feedbacks, f_total=f_total, f_page=f_page, f_pages=f_pages,
                           pending=pending,
                           CONTACT_STATUSES=CONTACT_STATUSES, CONTACT_STATUS_LABELS=CONTACT_STATUS_LABELS)


@admin_bp.route('/voices/<int:mid>/status', methods=['POST'])
@login_required
@admin_required
def voice_status(mid):
    """Let an admin action a contact message. Without this the "new" badge counts work the
    admin can see but cannot clear, so the number never moves."""
    from app.models import ContactMessage, CONTACT_STATUSES, ActivityEvent
    m = ContactMessage.query.get_or_404(mid)
    status = request.form.get('status')
    if status not in CONTACT_STATUSES:
        flash('Unknown status.', 'danger')
        return redirect(url_for('admin.voices', tab='contact'))
    m.set_status(status, by=current_user)
    note = (request.form.get('cs_notes') or '').strip()[:2000]
    if note != (m.cs_notes or ''):
        m.cs_notes = note or None
    ActivityEvent.log('contact_message_updated', actor=current_user, contact_id=m.id, status=status)
    db.session.commit()
    flash(f'Marked as {status.replace("_", " ")}.', 'success')
    return redirect(request.form.get('next') or url_for('admin.voices', tab='contact'))


@admin_bp.route('/contact')
@login_required
@admin_required
def contact_messages():
    """Kept so older links and bookmarks still land somewhere sensible."""
    return redirect(url_for('admin.voices', tab='contact', **request.args.to_dict()))


@admin_bp.route('/themes', methods=['GET', 'POST'])
@login_required
@admin_required
def themes_page():
    """Create, edit, activate and delete the colour themes the public site renders in."""
    from app.services import theming
    from app.models import ActivityEvent

    if request.method == 'POST':
        action = request.form.get('action') or 'save'

        if action == 'reset':
            theming.reset(current_user)
            ActivityEvent.log('theme_reset', actor=current_user)
            db.session.commit()
            flash('Themes restored to the shipped palettes.', 'success')
            return redirect(url_for('admin.themes_page'))

        if action == 'activate':
            key = request.form.get('key') or ''
            if theming.activate(key, current_user):
                ActivityEvent.log('theme_activated', actor=current_user, theme=key)
                db.session.commit()
                flash(f'"{key}" is now live on the site.', 'success')
            else:
                flash('That theme no longer exists.', 'danger')
            return redirect(url_for('admin.themes_page'))

        if action == 'delete':
            ok, msg = theming.delete(request.form.get('key') or '', current_user)
            if ok:
                ActivityEvent.log('theme_deleted', actor=current_user, theme=request.form.get('key'))
                db.session.commit()
            flash(msg, 'success' if ok else 'danger')
            return redirect(url_for('admin.themes_page'))

        # save: parallel arrays, one entry per theme card
        fields = ('key', 'name') + tuple(f for f, _l, _h in theming.FIELDS)
        cols = {f: request.form.getlist('t_' + f) for f in fields}
        n = max((len(v) for v in cols.values()), default=0)
        rows = [{f: (cols[f][i] if i < len(cols[f]) else '') for f in fields} for i in range(n)]
        ok, problems = theming.save(rows, request.form.get('active'), current_user)
        if ok:
            ActivityEvent.log('theme_saved', actor=current_user, count=len(theming.themes()),
                              active=theming.active_key())
            db.session.commit()
            flash('Themes saved — the site is already using them.', 'success')
        for p in problems:
            flash(p, 'warning' if ok else 'danger')
        return redirect(url_for('admin.themes_page'))

    items = theming.themes()
    return render_template('admin/themes.html', active='themes', themes=items,
                           active_key=theming.active_key(), default_key=theming.DEFAULT_ACTIVE,
                           fields=theming.FIELDS,
                           customised=theming.is_customised(),
                           warnings={t['key']: theming.warnings_for(t) for t in items},
                           preview={t['key']: theming.variables(t) for t in items})


@admin_bp.route('/help', methods=['GET', 'POST'])
@login_required
@admin_required
def help_center_page():
    """Categories and FAQs for the public /help page. Saved together so a FAQ can never
    reference a category that the same submit deleted."""
    from app.services import help_center
    from app.models import ActivityEvent

    def _rows(prefix, fields):
        """Read parallel form arrays (cat_title[], cat_icon[], ...) back into row dicts."""
        cols = {f: request.form.getlist(f'{prefix}_{f}') for f in fields}
        n = max((len(v) for v in cols.values()), default=0)
        return [{f: (cols[f][i] if i < len(cols[f]) else '') for f in fields} for i in range(n)]

    if request.method == 'POST':
        if request.form.get('action') == 'reset':
            help_center.reset(current_user)
            ActivityEvent.log('help_center_reset', actor=current_user)
            db.session.commit()
            flash('Help centre restored to the shipped questions.', 'success')
            return redirect(url_for('admin.help_center_page'))

        cats = _rows('cat', ('key', 'title', 'icon', 'blurb'))
        fqs = _rows('faq', ('id', 'category', 'question', 'answer'))
        ok, errors = help_center.save(cats, fqs, current_user)
        if ok:
            ActivityEvent.log('help_center_saved', actor=current_user,
                              categories=len(help_center.categories()), faqs=len(help_center.faqs()))
            db.session.commit()
            flash('Help centre saved — the public page is already showing it.', 'success')
            return redirect(url_for('admin.help_center_page'))
        for e in errors:
            flash(e, 'danger')

    return render_template('admin/help.html', active='help',
                           categories=help_center.categories(), faqs=help_center.faqs(),
                           icons=help_center.ICON_CHOICES,
                           customised=help_center.is_customised())


@admin_bp.route('/options')
@login_required
@admin_required
def options_page():
    """One screen for every configurable dropdown / list (languages, categories, roles, airports, ...)."""
    from app import options
    from app.services import locations
    lists = [(name, spec, options.rows(name), options.is_customised(name)) for name, spec in options.LISTS.items()]
    specs = {name: {'kind': spec['kind']} for name, spec in options.LISTS.items()}
    from app.services import airlines as airlines_svc
    airports = locations.all_airports()
    airlines = airlines_svc.all_airlines()
    return render_template('admin/options.html', lists=lists, specs=specs, level_labels=options.ROLE_LEVEL_LABELS,
                           airports_total=len(airports), airports_custom=sum(1 for a in airports if a.get('custom')),
                           airlines_total=len(airlines), airlines_custom=sum(1 for a in airlines if a.get('custom')))


def _resync_roles():
    """Re-derive `role` / `is_admin` for every account after role levels changed."""
    for u in User.query.filter(User.roles.isnot(None)).all():
        u.set_roles(u.role_keys)


@admin_bp.route('/options/translations')
@login_required
@admin_required
def translations_list():
    """The curated strings of one language: shipped catalog + admin overrides from the DB."""
    from flask import current_app
    from app import options
    from app.services import settings
    langs = [l for l in options.get_list('site_languages') if l.get('mode') == 'babel' and l['code'] != 'en']
    lang = (request.args.get('lang') or (langs[0]['code'] if langs else 'hi')).strip().lower()
    if lang not in {l['code'] for l in langs}:
        return jsonify({'error': f'"{lang}" is set to Google Translate only - switch it to curated '
                                 'on the Site languages tab to edit its strings.',
                        'languages': langs}), 400
    from babel.messages.pofile import read_po
    tdir = os.path.join(current_app.root_path, 'translations')
    all_ids, shipped = set(), {}
    for code in (sorted(os.listdir(tdir)) if os.path.isdir(tdir) else []):
        po_path = os.path.join(tdir, code, 'LC_MESSAGES', 'messages.po')
        if not os.path.exists(po_path):
            continue
        with open(po_path, 'rb') as f:
            cat = read_po(f)
        for m in cat:
            if m.id:
                all_ids.add(str(m.id))
                if code == lang:
                    shipped[str(m.id)] = str(m.string or '')
    ovr = (settings.get_setting('translation_overrides', {}) or {}).get(lang, {})
    items = [{'id': k, 'shipped': shipped.get(k, ''), 'override': ovr.get(k, '')}
             for k in sorted(all_ids, key=str.lower)]
    for k in sorted(set(ovr) - all_ids):
        items.append({'id': k, 'shipped': '', 'override': ovr[k]})
    return jsonify({'lang': lang, 'languages': langs, 'items': items, 'overridden': len(ovr)})


@admin_bp.route('/options/translations/save', methods=['POST'])
@login_required
@admin_required
def translations_save():
    from app.models import ActivityEvent
    from app.services import settings
    payload = request.get_json(silent=True) or {}
    lang = (payload.get('lang') or '').strip().lower()
    if not lang.isalpha() or not 2 <= len(lang) <= 3:
        return jsonify({'error': 'Missing or invalid language'}), 400
    items = payload.get('items') or {}
    if not isinstance(items, dict):
        return jsonify({'error': 'items must be an object of {source: translation}'}), 400
    data = dict(settings.get_setting('translation_overrides', {}) or {})
    cur = dict(data.get(lang) or {})
    changed = 0
    for k, v in items.items():
        k, v = str(k), str(v or '').strip()
        if v:
            if cur.get(k) != v:
                cur[k] = v[:500]
                changed += 1
        elif k in cur:
            del cur[k]
            changed += 1
    if cur:
        data[lang] = cur
    else:
        data.pop(lang, None)
    settings.set_setting('translation_overrides', data, current_user)
    ActivityEvent.log('translations_changed', actor=current_user, lang=lang, changed=changed)
    db.session.commit()
    return jsonify({'success': True, 'overridden': len(cur), 'changed': changed})


@admin_bp.route('/options/<name>', methods=['POST'])
@login_required
@admin_required
def save_options(name):
    from app import options
    from app.models import ActivityEvent
    if name not in options.LISTS:
        return jsonify({'error': 'Unknown list'}), 404
    payload = request.get_json(silent=True) or {}
    try:
        clean = options.set_list(name, payload.get('items') or [], current_user)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    if name == 'roles':
        _resync_roles()
    sync = None
    if name in ('languages', 'site_languages'):
        other = options.sync_language_lists(name, current_user)
        if other:
            sync = {'name': other, 'rows': options.rows(other), 'customised': options.is_customised(other)}
    ActivityEvent.log('options_changed', actor=current_user, list=name, count=len(clean))
    db.session.commit()
    return jsonify({'success': True, 'rows': options.rows(name), 'customised': True, 'sync': sync})


@admin_bp.route('/options/<name>/reset', methods=['POST'])
@login_required
@admin_required
def reset_options(name):
    from app import options
    from app.models import ActivityEvent
    if name not in options.LISTS:
        return jsonify({'error': 'Unknown list'}), 404
    options.reset_list(name, current_user)
    if name == 'roles':
        _resync_roles()
    ActivityEvent.log('options_reset', actor=current_user, list=name)
    db.session.commit()
    return jsonify({'success': True, 'rows': options.rows(name), 'customised': False})


@admin_bp.route('/options/airports/search')
@login_required
@admin_required
def airports_search():
    """Search the merged airport list; with no query, list the admin-added airports."""
    from app.services import locations
    q = (request.args.get('q') or '').strip().lower()
    rows = locations.all_airports()
    out = []
    if len(q) >= 2:
        for a in rows:
            hay = ' '.join(str(a.get(k) or '') for k in ('iata', 'city', 'name', 'country')).lower()
            if (a.get('iata') or '').lower().startswith(q) or q in hay:
                out.append(a)
        out.sort(key=lambda a: (not a.get('custom'), not (a.get('iata') or '').lower().startswith(q),
                                (a.get('city') or '').lower() != q, str(a.get('name') or '')))
    else:
        customs = [a for a in rows if a.get('custom')]
        base = sorted((a for a in rows if not a.get('custom')), key=lambda a: str(a.get('city') or a.get('name') or ''))
        out = customs + base
    page, per_page = _page_args(30)
    matches = len(out)
    pages = max((matches + per_page - 1) // per_page, 1)
    page = min(page, pages)
    out = out[(page - 1) * per_page: page * per_page]
    return jsonify({'results': out, 'total': len(rows), 'custom': sum(1 for a in rows if a.get('custom')),
                    'page': page, 'pages': pages, 'matches': matches})


@admin_bp.route('/options/airports/add', methods=['POST'])
@login_required
@admin_required
def airports_add():
    import re as _re
    from app.models import Airport, ActivityEvent
    from app.services import locations
    d = request.get_json(silent=True) or {}
    iata = (d.get('iata') or '').strip().upper()
    name = (d.get('name') or '').strip()
    city = (d.get('city') or '').strip()
    country = (d.get('country') or '').strip()
    if not _re.match(r'^[A-Z0-9]{3}$', iata):
        return jsonify({'error': f'"{iata or "?"}" is not a 3-letter IATA code'}), 400
    if not name:
        return jsonify({'error': 'Airport name is required'}), 400
    if locations.airport(iata) or Airport.query.filter_by(iata=iata).first():
        return jsonify({'error': f'{iata} already exists'}), 400
    a = Airport(iata=iata, name=name[:150], city=(city or name)[:100], country=country[:80], is_custom=True)
    db.session.add(a)
    ActivityEvent.log('airport_added', actor=current_user, iata=iata, city=a.city)
    db.session.commit()
    locations.reset_cache()
    return jsonify({'success': True, 'airport': a.as_dict()})


@admin_bp.route('/options/airports/<int:airport_id>/delete', methods=['POST'])
@login_required
@admin_required
def airports_delete(airport_id):
    from app.models import Airport, ActivityEvent
    from app.services import locations
    a = Airport.query.get_or_404(airport_id)
    if not a.is_custom:
        return jsonify({'error': 'Built-in airports cannot be removed.'}), 400
    ActivityEvent.log('airport_removed', actor=current_user, iata=a.iata)
    db.session.delete(a)
    db.session.commit()
    locations.reset_cache()
    return jsonify({'success': True})


@admin_bp.route('/options/airlines/search')
@login_required
@admin_required
def airlines_search():
    """Search the merged airline list; with no query, list the admin-added airlines."""
    from app.services import airlines as airlines_svc
    q = (request.args.get('q') or '').strip().lower()
    rows = airlines_svc.all_airlines()
    out = []
    if len(q) >= 2:
        for a in rows:
            hay = ' '.join(str(a.get(k) or '') for k in ('iata', 'name', 'country')).lower()
            if (a.get('iata') or '').lower().startswith(q) or q in hay:
                out.append(a)
        out.sort(key=lambda a: (not a.get('custom'), not (a.get('iata') or '').lower().startswith(q),
                                str(a.get('name') or '')))
    else:
        customs = [a for a in rows if a.get('custom')]
        base = sorted((a for a in rows if not a.get('custom')), key=lambda a: str(a.get('name') or ''))
        out = customs + base
    page, per_page = _page_args(30)
    matches = len(out)
    pages = max((matches + per_page - 1) // per_page, 1)
    page = min(page, pages)
    out = out[(page - 1) * per_page: page * per_page]
    return jsonify({'results': out, 'total': len(rows), 'custom': sum(1 for a in rows if a.get('custom')),
                    'page': page, 'pages': pages, 'matches': matches})


@admin_bp.route('/options/airlines/add', methods=['POST'])
@login_required
@admin_required
def airlines_add():
    import re as _re
    from app.models import Airline, ActivityEvent
    from app.services import airlines as airlines_svc
    d = request.get_json(silent=True) or {}
    iata = (d.get('iata') or '').strip().upper()
    name = (d.get('name') or '').strip()
    country = (d.get('country') or '').strip()
    if not _re.match(r'^[A-Z0-9]{2,3}$', iata):
        return jsonify({'error': f'"{iata or "?"}" is not a 2-3 character airline code'}), 400
    if not name:
        return jsonify({'error': 'Airline name is required'}), 400
    if airlines_svc.airline(iata) or Airline.query.filter_by(iata=iata).first():
        return jsonify({'error': f'{iata} already exists'}), 400
    a = Airline(iata=iata, name=name[:150], country=country[:80], is_custom=True)
    db.session.add(a)
    ActivityEvent.log('airline_added', actor=current_user, iata=iata)
    db.session.commit()
    airlines_svc.reset_cache()
    return jsonify({'success': True, 'airline': a.as_dict()})


@admin_bp.route('/options/airlines/<int:airline_id>/delete', methods=['POST'])
@login_required
@admin_required
def airlines_delete(airline_id):
    from app.models import Airline, ActivityEvent
    from app.services import airlines as airlines_svc
    a = Airline.query.get_or_404(airline_id)
    if not a.is_custom:
        return jsonify({'error': 'Built-in airlines cannot be removed.'}), 400
    ActivityEvent.log('airline_removed', actor=current_user, iata=a.iata)
    db.session.delete(a)
    db.session.commit()
    airlines_svc.reset_cache()
    return jsonify({'success': True})


@admin_bp.route('/listings')
@login_required
@admin_required
def listings():
    from sqlalchemy import or_
    from app.models import Match, ContactPoint, TRIP_STATUSES
    page, per_page = _page_args(25)
    q = (request.args.get('q') or '').strip()
    status = request.args.get('status') or ''
    query = CompanionRequest.query
    if status:
        query = query.filter(CompanionRequest.status == status)
    if q:
        pat = f"%{q}%"
        query = (query.outerjoin(User, CompanionRequest.user_id == User.id)
                 .filter(or_(CompanionRequest.flying_from.ilike(pat), CompanionRequest.destination.ilike(pat),
                             CompanionRequest.origin_iata.ilike(pat), CompanionRequest.dest_iata.ilike(pat),
                             CompanionRequest.poster_name.ilike(pat), CompanionRequest.traveler_name.ilike(pat),
                             CompanionRequest.airline.ilike(pat), CompanionRequest.flight_number.ilike(pat),
                             User.username.ilike(pat), User.email.ilike(pat))))
    query = query.order_by(CompanionRequest.created_at.desc())
    total = query.count()
    pages = max((total + per_page - 1) // per_page, 1)
    page = min(page, pages)
    trips = query.offset((page - 1) * per_page).limit(per_page).all()
    # live (non-dismissed) matches per listed post - same at-a-glance flag the CS list has
    ids = {t.id for t in trips}
    match_info = {}
    if ids:
        for m in Match.query.filter((Match.trip_a_id.in_(ids)) | (Match.trip_b_id.in_(ids)),
                                    Match.status != 'dismissed').all():
            for tid in (m.trip_a_id, m.trip_b_id):
                if tid in ids:
                    e = match_info.setdefault(tid, {'n': 0, 'best': 0})
                    e['n'] += 1
                    e['best'] = max(e['best'], m.score or 0)
    return render_template('admin/listings.html', trips=trips, page=page, pages=pages, total=total,
                           match_info=match_info, q=q, status=status, TRIP_STATUSES=TRIP_STATUSES)


@admin_bp.route('/listings/<int:trip_id>/disable', methods=['POST'])
@login_required
@admin_required
def disable_listing(trip_id):
    trip = CompanionRequest.query.get_or_404(trip_id)
    trip.set_status('closed', reason='spam', by=current_user)
    db.session.commit()
    return jsonify({'success': True})


@admin_bp.route('/feedback')
@login_required
@admin_required
def feedback():
    """Kept so older links and bookmarks still land somewhere sensible."""
    return redirect(url_for('admin.voices', tab='feedback', **request.args.to_dict()))


@admin_bp.route('/feedback/<int:fid>/approve', methods=['POST'])
@login_required
@admin_required
def approve_feedback(fid):
    fb = Feedback.query.get_or_404(fid)
    fb.is_approved = True
    db.session.commit()
    return jsonify({'success': True})


@admin_bp.route('/feedback/<int:fid>/feature', methods=['POST'])
@login_required
@admin_required
def feature_feedback(fid):
    fb = Feedback.query.get_or_404(fid)
    if not fb.is_approved:
        return jsonify({'error': 'Approve the review first'}), 400
    fb.is_featured = not bool(fb.is_featured)
    db.session.commit()
    return jsonify({'success': True, 'featured': bool(fb.is_featured)})


@admin_bp.route('/feedback/<int:fid>/reject', methods=['POST'])
@login_required
@admin_required
def reject_feedback(fid):
    fb = Feedback.query.get_or_404(fid)
    db.session.delete(fb)
    db.session.commit()
    return jsonify({'success': True})


def _unique_slug(title):
    base = slugify(title)[:300] or 'post'
    slug, n = base, 1
    while Blog.query.filter_by(slug=slug).first():
        n += 1
        slug = f'{base}-{n}'
    return slug


@admin_bp.route('/blog/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_blog():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        cover = request.form.get('cover_image_url', '').strip()[:500] or None
        is_published = request.form.get('is_published') == 'on'
        send_notif = request.form.get('send_notification') == 'on'

        if not title or not content:
            flash('Title and content are required.', 'danger')
            return render_template('admin/blog_form.html', form=request.form)

        post = Blog(
            author_id=current_user.id,
            title=title,
            slug=_unique_slug(title),
            content=content,
            cover_image_url=cover,
            is_published=is_published,
            published_at=datetime.utcnow() if is_published else None,
            send_notification=send_notif,
        )
        db.session.add(post)
        db.session.commit()

        if is_published and send_notif:
            _notify_all_blog(post)

        flash('Blog post created!', 'success')
        if is_published:
            return redirect(f'/blog/{post.slug}')
        return redirect(url_for('admin.dashboard'))

    return render_template('admin/blog_form.html')


def _notify_all_blog(post):
    """In-app notification for everyone; e-mail only to users who opted in (marketing_consent).
    Both go through the notification switches (category 'announcements')."""
    from app.services import notify, mailer
    users = User.query.filter_by(is_active=True).all()
    for user in users:
        notify.push(user.id, 'blog', title=f'New Blog Post: {post.title}', body=post.excerpt(100),
                    link=f'/blog/{post.slug}')
        if user.marketing_consent:
            mailer.send(
                f"[Connecting Desis] New Story: {post.title}", [user.email],
                (f"Check out our latest blog post!\n\n{post.title}\n\n{post.excerpt(200)}\n\n"
                 f"Read more: {current_app.config['SITE_URL']}/blog/{post.slug}\n\n"
                 f"You receive this because you opted in to updates. To stop, change your notification "
                 f"settings at {current_app.config['SITE_URL']}/settings/notifications."),
                category='announcements',
            )
    db.session.commit()


@admin_bp.route('/notifications', methods=['GET', 'POST'])
@login_required
@admin_required
def notification_switches():
    """Master / channel / category switches that stop notifications site-wide (all or partial)."""
    from sqlalchemy import func
    from app.services import settings as app_settings
    from app.models import NOTIFY_CATEGORIES, NOTIFY_CATEGORY_LABELS, ActivityEvent
    if request.method == 'POST':
        data = {
            'enabled': request.form.get('enabled') == 'on',
            'channels': {'email': request.form.get('channel_email') == 'on',
                         'inapp': request.form.get('channel_inapp') == 'on'},
            'categories': {c: request.form.get(f'cat_{c}') == 'on' for c in NOTIFY_CATEGORIES},
            'note': (request.form.get('note') or '').strip(),
        }
        sw = app_settings.set_notification_switches(data, current_user)
        ActivityEvent.log('notification_switches_changed', actor=current_user, enabled=sw['enabled'],
                          channels=sw['channels'], categories_off=[c for c, on in sw['categories'].items() if not on])
        db.session.commit()
        flash('Notification switches saved.' if sw['enabled'] else 'All notifications are now stopped.', 'success')
        return redirect(url_for('admin.notification_switches'))
    sw = app_settings.notification_switches()
    since = datetime.utcnow() - timedelta(days=7)
    counts = dict(db.session.query(Notification.type, func.count(Notification.id))
                  .filter(Notification.created_at >= since).group_by(Notification.type).all())
    from app.services.notify import CATEGORY_FOR_TYPE
    per_category = {}
    for ntype, n in counts.items():
        per_category[CATEGORY_FOR_TYPE.get(ntype, 'other')] = per_category.get(CATEGORY_FOR_TYPE.get(ntype, 'other'), 0) + n
    row = db.session.get(AppSetting, app_settings.NOTIFY_KEY)
    return render_template('admin/notifications.html', sw=sw, categories=NOTIFY_CATEGORIES,
                           labels=NOTIFY_CATEGORY_LABELS, per_category=per_category, setting_row=row)


@admin_bp.route('/broadcast', methods=['POST'])
@login_required
@admin_required
def broadcast():
    data = request.get_json() or {}
    title = (data.get('title') or '').strip()[:255]
    body = (data.get('body') or '').strip()
    if not title or not body:
        return jsonify({'error': 'title and body required'}), 400

    from app.services import notify
    users = User.query.filter_by(is_active=True).all()
    sent = 0
    for user in users:
        if notify.push(user.id, 'broadcast', title=title, body=body, link='/') is not None:
            sent += 1
    db.session.commit()
    return jsonify({'success': True, 'sent_to': sent, 'skipped': len(users) - sent})
