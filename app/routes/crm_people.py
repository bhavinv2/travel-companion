"""Contacts, the contact page, Find a person, the downloads, Bring in & download's imports and Where leads
come from's two editors. Rules on crm_bp (both consoles); the logic is in services/crm_people.py.
"""
import os
import re
import secrets
from datetime import datetime

from flask import abort, current_app, flash, jsonify, redirect, render_template, request
from flask_login import current_user
from sqlalchemy.orm import joinedload, selectinload

from app import db
from app.models import ActivityEvent, CrmLead, CrmPerson, CrmSource, CRM_FORECASTS
from app.routes.crm import IMPORT_DIR, CHAT_FILTERS, _common, _json, _staff, admin_only, crm_bp, crm_url
from app.routes.cs import cs_required
from app.services import (access, crm, crm_access, crm_audit, crm_files, crm_household, crm_merge, crm_money, crm_people,
                          crm_products, crm_records, crm_scope, download_reason, wacrm, wacrm_team)
from app.services import phone as phone_svc
from app.services.ratelimit import rate_limit

PER_PAGE = 50


def _person_or_404(person_id):
    person = db.session.get(CrmPerson, person_id)
    if person is None or not crm_access.can_see_person(current_user, person) or not crm_scope.visible(person):
        abort(404)
    return person


def _safe_next(default):
    nxt = request.values.get('next') or ''
    return nxt if nxt.startswith('/') and not nxt.startswith('//') else default


# ============================================================================================ Contacts

def _contact_filters():
    a = request.args
    f = {'tag': (a.get('tag') or '').strip().lower()[:40],
         'wa': a.get('wa') if a.get('wa') in {k for k, _ in crm_people.WA_FILTERS} else '',
         'enq': a.get('enq') if a.get('enq') in {k for k, _ in crm_people.ENQ_FILTERS} else '',
         'owner': a.get('owner') or '', 'q': ' '.join((a.get('q') or '').split())[:80]}
    if not (f['owner'] in ('mine', 'none') or f['owner'].isdigit()):
        f['owner'] = ''
    return f


@crm_bp.route('/contacts')
@cs_required
def contacts():
    """Contacts (E6): one row per person with their enquiries and WhatsApp state, 50 a page, from a fixed
    set of queries."""
    f = _contact_filters()
    from app.routes.crm_family import can_merge
    if request.args.get('dups') and can_merge(current_user):
        pairs = crm_merge.find_pairs(current_user)
        return render_template('cs/crm/duplicates.html', pairs=pairs, **_common())
    query = crm_people.contacts_filter(f, current_user)
    total = query.count()
    pages = max(1, -(-total // PER_PAGE))
    page = max(1, min(request.args.get('page', type=int) or 1, pages))
    people = query.options(selectinload(CrmPerson.identities)).offset((page - 1) * PER_PAGE).limit(PER_PAGE).all()
    filters_on = any(f.values())
    from app.routes.messaging import can_start_chats
    return render_template('cs/crm/contacts.html', people=people, rows=crm_people.contact_rows(people), f=f,
                           total=total, page=page, pages=pages, per_page=PER_PAGE, filters_on=filters_on,
                           has_any=db.session.query(CrmPerson.id).first() is not None,
                           tag_choices=crm_people.tag_choices(), WA_FILTERS=crm_people.WA_FILTERS,
                           ENQ_FILTERS=crm_people.ENQ_FILTERS, staff=_staff(),
                           can_export=access.can(current_user, 'crm_export'),
                           can_import=access.can(current_user, 'crm_data'), crm_people=crm_people,
                           can_merge=can_merge(current_user), view_params={k: v for k, v in f.items() if v},
                           can_chat=can_start_chats(current_user), **_common())


# ============================================================================================ the contact page

@crm_bp.route('/contact/<int:person_id>')
@cs_required
def contact(person_id):
    """The contact page (E7): how to reach them, permission, tags, every enquiry, the last messages. Nothing
    here asks WhatsApp: the tags load from contact_tags."""
    person = _person_or_404(person_id)
    leads = (CrmLead.query.options(joinedload(CrmLead.stage), joinedload(CrmLead.pipeline),
                                   joinedload(CrmLead.owner))
             .filter_by(person_id=person.id).order_by(CrmLead.created_at.desc()).all())
    can_erase = access.can(current_user, 'delete_records')
    sync = None
    if current_user.is_admin or any(l.owner_id == current_user.id for l in leads):
        sync = crm.wa_sync_state(person)
    from app.routes.crm_family import can_merge
    from app.routes.messaging import can_start_chats
    fq = ' '.join((request.args.get('fq') or '').split())[:80]
    return render_template('cs/crm/contact.html', person=person, leads=leads,
                           family=crm_household.card(person, current_user), fq=fq,
                           family_results=crm_merge.search(person, fq, current_user) if fq else [],
                           site_records=crm_records.records_for(person, current_user),
                           files=crm_files.for_person(person.id), can_merge=can_merge(current_user),
                           permission=crm_people.permission(person), sales_tags=crm_people.sales_tags(person),
                           recent=crm_people.recent(person), sync=sync, writes=crm.wa_writes_on(),
                           linked=bool(person.wacrm_contact_id or person.wacrm_conversation_id),
                           can_erase=can_erase, can_add=access.can(current_user, 'crm_add'),
                           can_chat=can_start_chats(current_user),
                           erase=crm_people.erase_plan(person) if (request.args.get('erase') and can_erase) else None,
                           history=crm_audit.history_for('person', person.id),
                           crm_people=crm_people, **_common())


@crm_bp.route('/contact/<int:person_id>/show', methods=['POST'])
@cs_required
@rate_limit(60, 3600)
def contact_show(person_id):
    """Show: a hidden phone number and e-mail (services/crm_mask), logged, for the rest of this sign-in. Back to
    the page it was pressed on."""
    from urllib.parse import urlparse
    from app.services import crm_mask, urls
    person = _person_or_404(person_id)
    ref = urlparse(request.referrer or '')
    back = urls.safe_next(ref.path + ('?' + ref.query if ref.query else '')) if ref.netloc == request.host else None
    crm_mask.show(person, where=back)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
        return jsonify({'ok': True})
    return redirect(back or crm_url('contact', person_id=person.id))


@crm_bp.route('/contact/<int:person_id>/edit', methods=['GET', 'POST'])
@cs_required
def contact_edit(person_id):
    """The one contact form: name, phone, e-mail, Instagram, Facebook. The lead page's More menu opens it too."""
    person = _person_or_404(person_id)
    back = _safe_next(crm_url('contact', person_id=person.id))
    if request.method == 'POST':
        errors = crm_people.save_details(person, request.form, current_user)
        if not errors:
            db.session.commit()
            flash('Saved.', 'success')
            return redirect(back)
        db.session.rollback()
        return render_template('cs/crm/contact_edit.html', person=person, form=request.form,
                               errors=errors, back=back, **_common()), 400
    form = {'name': person.name or '', 'phone': person.phone or '', 'email': person.email or '',
            'instagram': person.identity('instagram') or '', 'facebook': person.identity('facebook') or '',
            'phone_cc': phone_svc.iso_for(person.phone) if person.phone else ''}
    return render_template('cs/crm/contact_edit.html', person=person, form=form, errors={}, back=back, **_common())


@crm_bp.route('/contact/<int:person_id>/tags', methods=['GET', 'POST'])
@cs_required
def contact_tags(person_id):
    """The Tags card: GET the free tags (from WhatsApp, kept 60 s) and what may be picked; POST adds or
    removes one free tag. Sales tags are the Sales CRM's own and are refused here."""
    person = _person_or_404(person_id)
    writes = crm.wa_writes_on()
    cid = person.wacrm_contact_id
    can_create = access.can(current_user, 'wa_tags')
    if request.method == 'GET':
        linked = bool(person.wacrm_contact_id or person.wacrm_conversation_id)
        free = crm_people.free_tags(person) if (linked and wacrm_team.enabled()) else None
        note = (crm.WA_LINE_OFF if not writes else crm_people.TAGS_NOT_IN_WA if not linked
                else crm_people.NO_ANSWER if free is None else None)
        out = {'sales': crm_people.sales_tags(person), 'free': free, 'linked': linked, 'writes': writes,
               'can_create': can_create, 'note': note}
        if request.args.get('all') and writes and linked:
            have = {t.lower() for t in free or []}
            try:
                with wacrm.short_timeouts():
                    items = wacrm_team.tags()
            except wacrm_team.TeamError:
                items = []
            out['choices'] = sorted(({'name': i['name'], 'contacts': i.get('contacts') or 0} for i in items
                                     if i.get('name') and not i.get('managed') and not crm_people.is_sales_tag(i['name'])
                                     and i['name'].lower() not in have), key=lambda c: c['name'].lower())
        return jsonify(out)
    data = _json()
    add, remove = (data.get('add') or '').strip()[:60], (data.get('remove') or '').strip()[:60]
    name = add or remove
    if not name:
        return jsonify({'error': 'Choose a tag.'}), 400
    if not writes:
        return jsonify({'error': crm.WA_WRITES_OFF}), 409
    if not cid:
        return jsonify({'error': crm_people.TAG_NO_CONTACT}), 409
    if crm_people.is_sales_tag(name):
        return jsonify({'error': crm_people.TAG_MANAGED}), 422
    try:
        with wacrm.short_timeouts():
            tags = wacrm_team.contact_tags(cid, add=[add] if add else (), remove=[remove] if remove else (),
                                           create=bool(add and can_create))
    except wacrm_team.TeamError as exc:
        if exc.code == 'managed_tag':
            return jsonify({'error': crm_people.TAG_MANAGED}), 422
        if exc.code == 'unknown_tag':
            return jsonify({'error': crm_people.TAG_UNKNOWN}), 422
        if exc.status == 404:
            return jsonify({'error': crm_people.TAG_NO_CONTACT if exc.code else crm_people.NEEDS_UPDATE}), 409
        return jsonify({'error': crm_people.NO_ANSWER}), 502
    if add and can_create:
        wacrm_team.forget_tags()
    free = sorted({t.get('name') for t in tags if t.get('name') and not t.get('managed')
                   and not crm_people.is_sales_tag(t['name'])}, key=str.lower)
    crm_people.remember_free(cid, free)
    if person.wacrm_conversation_id:
        crm_people.remember_free(person.wacrm_conversation_id, free)
    return jsonify({'success': True, 'free': free})


@crm_bp.route('/contact/<int:person_id>/erase', methods=['POST'])
@cs_required
def contact_erase(person_id):
    """Erase this person (admins): the typed name confirms; the dialog on the contact page lists what goes."""
    person = _person_or_404(person_id)
    back = crm_url('contact', person_id=person.id, erase=1)
    typed = ' '.join((request.form.get('confirm_name') or '').split()).lower()
    if typed != ' '.join(person.display_name.split()).lower():
        flash(crm_people.ERASE_TYPE, 'danger')
        return redirect(back)
    try:
        outcome = crm_people.erase(person, current_user)
    except crm_people.EraseRefused:
        db.session.rollback()
        flash(crm_people.ERASE_NO_ANSWER, 'danger')
        return redirect(back)
    flash(crm_people.ERASE_DONE, 'success')
    if outcome in crm_people.ERASE_WA:
        flash(crm_people.ERASE_WA[outcome], 'warning')
    return redirect(crm_url('contacts'))


# ============================================================================================ Find a person

@crm_bp.route('/find')
@cs_required
def find():
    """Find a person (E25): JSON for the header box. Display only: it never links or merges people."""
    q = ' '.join((request.args.get('q') or '').split())[:80]
    if len(q) < 2:
        return jsonify({'items': []})
    return jsonify(crm_people.find(q, current_user))


# ============================================================================================ Visual Flow

@crm_bp.route('/flow')
@cs_required
def flow():
    """Visual Flow (E26): the whole CRM lifecycle -- every pipeline from the way in to won/lost, with what
    happens at each stage -- and, for the people picked (?person_id=, repeatable), where each one is, how they
    got there and what to do next. Their circles open their lead at the stage bar; "Do it" opens the message
    box; the step-by-step guide's stages open Leads filtered to that stage."""
    ids = []
    for raw in request.args.getlist('person_id'):
        if raw.isdigit() and int(raw) not in ids:
            ids.append(int(raw))
    seen = crm_access.person_filter(current_user)
    by_id = ({p.id: p for p in CrmPerson.query.filter(CrmPerson.id.in_(ids), *([seen] if seen is not None else [])).all()}
             if ids else {})
    people = [by_id[i] for i in ids if i in by_id]
    maps = crm_people.flow_data(people)
    order = {p.id: n for n, p in enumerate(people)}
    entries = sorted((e for m in maps for e in m['entries']), key=lambda e: order[e['person'].id])
    return render_template('cs/crm/flow.html', people=people, maps=maps, entries=entries,
                           colors={p.id: n % 8 for n, p in enumerate(people)},
                           tracked_ids={e['person'].id for e in entries},
                           phases=crm_people.FLOW_PHASES, phase_text={k: t for k, _, t in crm_people.FLOW_PHASES},
                           phase_label={k: l for k, l, _ in crm_people.FLOW_PHASES}, **_common())


@crm_bp.route('/flow/find')
@cs_required
def flow_find():
    """Visual Flow's own search: people only (crm_people.find_people), not the general record search."""
    q = ' '.join((request.args.get('q') or '').split())[:80]
    return jsonify({'items': crm_people.find_people(q, user=current_user) if len(q) >= 2 else []})


# ============================================================================================ downloads

@crm_bp.route('/export/leads')
@cs_required
@admin_only
@download_reason.asked
def export_leads():
    """Leads' "Download this list": the same filters as the list on screen."""
    from app.services import access as _access
    a = request.args
    key = a.get('p') or 'all'
    pipe = None
    if key != 'all':
        from app.models import CrmPipeline
        pipe = CrmPipeline.query.filter_by(key=key).first()
    owner = a.get('owner') or 'all'
    staff_ids = {u.id for u in _staff()}
    owner_id = (current_user.id if owner == 'mine' else 'none' if owner == 'none'
                else int(owner) if owner.isdigit() and int(owner) in staff_ids else None)
    chat = a.get('chat') if a.get('chat') in {k for k, _ in CHAT_FILTERS} else ''
    closes = a.get('closes') if crm_money.closes_bounds(a.get('closes')) else None
    forecast = a.get('forecast') if a.get('forecast') in CRM_FORECASTS else None
    no_value, no_close = bool(a.get('no_value')), bool(a.get('no_close'))
    ids = [int(x) for x in (a.get('ids') or '').split(',') if x.strip().isdigit()][:200] or None
    _more, more_args = crm.lead_more_words(a)
    # as on the screen: a money filter, a date range or chosen leads show every finished one, not the last 30 days
    lifted = closes or forecast or no_value or no_close or ids or more_args['date_on']
    closed_days = 30 if a.get('win') == '30' and not lifted else None
    query = crm.lead_filter(pipe, owner_id=owner_id, q=(a.get('q') or '').strip()[:80], chat=chat,
                            stage_id=a.get('stage', type=int), closed_days=closed_days,
                            follow=a.get('follow') if a.get('follow') in dict(crm.FOLLOW_FILTERS) else None,
                            quoted='week' if a.get('quoted') == 'week' else None,
                            closes=closes, forecast=forecast, no_value=no_value, no_close=no_close,
                            status=a.get('status'), ids=ids, **more_args)
    query = query.order_by(CrmLead.last_activity_at.desc(), CrmLead.id.desc())
    return crm_people.export(query, 'leads', current_user, {k: v for k, v in a.items() if v})


@crm_bp.route('/export/contacts')
@cs_required
@admin_only
@download_reason.asked
def export_contacts():
    f = _contact_filters()
    return crm_people.export(crm_people.contacts_filter(f, current_user), 'contacts', current_user,
                             {k: v for k, v in f.items() if v})


# ============================================================================================ CSV import

def _csv_path(token):
    folder = os.path.join(current_app.config['PRIVATE_UPLOAD_FOLDER'], IMPORT_DIR)
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, '%s.csv' % token)


def _csv_defaults(form):
    owner = form.get('default_owner', type=int)
    return {'product': (form.get('default_product') or '').strip().upper() or None,
            'source': (form.get('default_source') or 'import-other').strip(),
            'owner': owner if owner in {u.id for u in _staff()} else None,
            'phone_cc': (form.get('phone_cc') or 'IN').strip().upper()[:2]}


def _csv_mapping(form, ncols):
    out = {}
    for field, _ in crm_people.FIELDS:
        v = form.get('map_%s' % field)
        out[field] = int(v) if v and v.isdigit() and int(v) < ncols else None
    return out


@crm_bp.route('/data/import-csv', methods=['POST'])
@cs_required
@admin_only
def import_csv():
    """Step 1 of a CSV import: upload (or re-check with other columns) and see what would happen. Nothing is stored."""
    from app.routes.crm import _data_context
    token = request.form.get('token') or ''
    f = request.files.get('list')
    if f is not None and f.filename:
        raw_name = f.filename
        if not raw_name.lower().endswith('.csv'):
            flash('Choose a .csv file of at most 2 MB.', 'danger')
            return redirect(crm_url('data'))
        token = secrets.token_hex(12)
        path = _csv_path(token)
        f.save(path)
        if os.path.getsize(path) > crm_people.CSV_MAX_BYTES:
            os.remove(path)
            flash('Choose a .csv file of at most 2 MB.', 'danger')
            return redirect(crm_url('data'))
        filename = os.path.basename(raw_name)[:120]
        reuse = False
    else:
        if not re.fullmatch(r'[0-9a-f]{24}', token) or not os.path.exists(_csv_path(token)):
            flash('That upload has expired -- choose the file again.', 'danger')
            return redirect(crm_url('data'))
        path, filename, reuse = _csv_path(token), (request.form.get('filename') or 'list.csv')[:120], True
    try:
        headers, rows = crm_people.read_csv(path)
    except ValueError as exc:
        try:
            os.remove(path)
        except OSError:
            pass
        flash(str(exc), 'danger')
        return redirect(crm_url('data'))
    mapping = _csv_mapping(request.form, len(headers)) if reuse else crm_people.guess_map(headers)
    defaults = _csv_defaults(request.form) if reuse else {'product': None, 'source': 'import-other', 'owner': None,
                                                          'phone_cc': 'IN'}
    plan = crm_people.plan_csv(path, mapping, defaults, _staff())
    csv_ctx = {'token': token, 'filename': filename, 'headers': headers, 'mapping': mapping, 'defaults': defaults,
               'plan': plan, 'rows': len(rows)}
    return render_template('cs/crm/data.html', **_data_context(csv=csv_ctx))


@crm_bp.route('/data/import-csv/confirm', methods=['POST'])
@cs_required
@admin_only
def import_csv_confirm():
    """Step 2: store what step 1 showed, quietly, then forget the file."""
    token = request.form.get('token') or ''
    if not re.fullmatch(r'[0-9a-f]{24}', token) or not os.path.exists(_csv_path(token)):
        flash('That upload has expired -- choose the file again.', 'danger')
        return redirect(crm_url('data'))
    path = _csv_path(token)
    try:
        headers, _ = crm_people.read_csv(path)
        counts = crm_people.import_csv(path, _csv_mapping(request.form, len(headers)), _csv_defaults(request.form),
                                       (request.form.get('filename') or 'list.csv')[:120], _staff())
    except ValueError as exc:
        flash(str(exc), 'danger')
        return redirect(crm_url('data'))
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    got = counts['new'] + counts['existing']
    ActivityEvent.log('crm_csv_import', actor=current_user, **{k: v for k, v in counts.items()})
    db.session.commit()
    said = 'Imported %d %s.' % (got, 'person' if got == 1 else 'people')
    if counts['already']:
        said += ' Skipped: %d already here.' % counts['already']
    if counts['unreachable']:
        said += ' %d with no phone or e-mail.' % counts['unreachable']
    if counts['dnc']:
        said += ' %d on the do-not-contact list.' % counts['dnc']
    flash(said, 'success')
    return redirect(crm_url('data'))


# ============================================================================================ From WhatsApp (one-off)

def _wa_feed(kind):
    if not crm.wa_team_on():
        return jsonify({'error': crm_people.WA_FEED_OFF}), 409
    since = (_json().get('since') or '').strip() or None
    run = crm_people.wa_import_contacts if kind == 'contacts' else crm_people.wa_import_notes
    try:
        out = run(since)
    except wacrm_team.TeamError as exc:
        db.session.rollback()
        if exc.status == 404 and not exc.code:
            crm.save_settings(current_user, wa_feed_missing=datetime.utcnow().isoformat(timespec='seconds'))
            return jsonify({'error': crm_people.NEEDS_UPDATE, 'missing': True}), 404
        return jsonify({'error': 'WhatsApp did not answer (%s). Press it again to carry on.' % exc,
                        'since': since}), 502
    if crm.crm_settings_raw().get('wa_feed_missing'):
        crm.save_settings(current_user, wa_feed_missing=None)
    ActivityEvent.log('crm_wa_import', actor=current_user, kind=kind, **out['counts'])
    db.session.commit()
    return jsonify(out)


@crm_bp.route('/data/wa-contacts', methods=['POST'])
@cs_required
@admin_only
def wa_contacts_import():
    return _wa_feed('contacts')


@crm_bp.route('/data/wa-notes', methods=['POST'])
@cs_required
@admin_only
def wa_notes_import():
    return _wa_feed('notes')


# ============================================================================================ Where leads come from

@crm_bp.route('/sources/inboxes', methods=['POST'])
@cs_required
@admin_only
def save_inboxes():
    keys = {s.key for s in CrmSource.query.all()}
    rows, errors = crm_people.parse_inboxes(request.form, keys)
    if errors:
        for e in errors:
            flash(e, 'danger')
        return redirect(crm_url('sources', tab='inboxes'))
    crm.save_settings(current_user, check_channels=rows)
    ActivityEvent.log('crm_inboxes_saved', actor=current_user, rows=len(rows))
    db.session.commit()
    flash('Saved.', 'success')
    return redirect(crm_url('sources', tab='inboxes'))


@crm_bp.route('/sources/inboxes/standard', methods=['POST'])
@cs_required
@admin_only
def standard_inboxes():
    """Inboxes to check: the lead sources' calls & chats and social media, a row each (services/crm_sources)."""
    from flask import current_app
    from app.services import crm_sources
    rows = crm_sources.standard_inboxes(current_app.config.get('WACRM_SOURCE_KEY', 'wa-india'))
    crm.save_settings(current_user, check_channels=rows)
    ActivityEvent.log('crm_inboxes_saved', actor=current_user, rows=len(rows), standard=True)
    db.session.commit()
    flash('The half-hourly check now has the %d calls and chats on the lead sources.' % len(rows), 'success')
    return redirect(crm_url('sources', tab='inboxes'))


@crm_bp.route('/sources/activities', methods=['POST'])
@cs_required
@admin_only
def save_activities():
    """Marketing activities and their campaign details (run 5b: crm_campaigns, per workspace)."""
    from app.services import crm_campaigns
    rows, errors = crm_campaigns.parse(request.form)
    if errors:
        db.session.rollback()
        for e in errors:
            flash(e, 'danger')
        return redirect(crm_url('sources', tab='activities'))
    n = crm_campaigns.save(rows)
    ActivityEvent.log('crm_activities_saved', actor=current_user, rows=n)
    db.session.commit()
    flash('Saved.', 'success')
    return redirect(crm_url('sources', tab='activities'))


@crm_bp.route('/sources/tag-check')
@cs_required
@admin_only
def source_tag_check():
    """Whether a tag may be added by a source (F56), for the picker's Add button."""
    return jsonify(crm_people.source_tag_problem(request.args.get('name'), take_over=()) or {'ok': True})
