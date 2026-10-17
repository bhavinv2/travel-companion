"""Set-up -> Pipelines, worked out here so the routes stay thin: the list and the "Needs a WhatsApp template"
checklist, Products, the new-pipeline wizard, and ONE Save of the pipeline editor (checked first, applied in one
transaction, then WhatsApp told). Nothing is written to the WhatsApp CRM unless crm.wa_writes_on().

The editor posts the whole pipeline as JSON:

    {stamp, name, is_active, product, move_leads, catch_all, reasons: [..],
     fields: [{id, ref, label, type, options, on_card, on_add, required}],
     stages: [{id, ref, name, means, on_reply, sla_hours,
               auto: {kind, field, days, to (a stage ref), reason}, button: {label, code},
               steps: [{id, ref, channel, title, kind, code, body, wa_template, wa_params, auto,
                        when: {type: now|after|date, value, unit, sign, field}}]}]}

`ref` is how the page names a row: 's12' / 't7' / 'f3' for saved ones, 'n1', 'n2' ... for new ones.
validate() checks all of it and changes nothing; apply() changes the session and never commits; save() commits once.
"""
import hashlib
import json
import logging
import re
from datetime import datetime

from sqlalchemy import func

from app import db
from app.models import (ActivityEvent, CrmAnswer, CrmField, CrmLead, CrmPerson, CrmPipeline, CrmPlaybookStep, CrmProduct,
                        CrmSource, CrmStage, CrmStageChange, CrmTask,
                        CRM_CHANNEL_LABELS, CRM_DATE_FIELDS, CRM_FIELD_TYPES, CRM_MEANS_LABELS, CRM_STAGE_MEANS,
                        CRM_STEP_CHANNELS, CRM_STEP_KINDS)
from app.services import crm, crm_defaults, crm_kpi, crm_products, wa_templates, wacrm, wacrm_team

log = logging.getLogger(__name__)

# ------------------------------------------------------------------------------------------ the words

SAVED, SAVED_MOVED = 'Saved.', 'Saved. %d lead%s moved to %s.'
E_NAME = 'Name the pipeline.'
E_STALE = 'Someone else changed this pipeline while you were editing. Reload the page to see their changes.'
E_OLD = 'This page is out of date. Reload it and try again.'
E_FIX = 'Some things need fixing before this can be saved.'
E_PRODUCT = 'Choose a product.'
E_MOVE = 'Answer whether its leads move too.'
E_TAG_TAKEN = "%s already uses '%s'. Give this one its own tag, e.g. '%s'."
E_STAGE_NAME = 'Name the stage.'
E_STAGE_DUP = 'Two stages are called “%s”. Give each its own name.'
E_NO_OPEN = 'A pipeline needs at least one stage that is not Won or Lost.'
E_STAGES_MAX = 'A pipeline can have at most 30 stages.'
E_REPLY_ONE = 'Only one stage can be where a reply moves them.'
E_SLA = 'Use a whole number of hours from 1 to 2000, or leave it empty.'
E_AUTO_TO = 'Choose the stage they move to.'
E_AUTO_BACK = 'Move by itself can only go forward: pick a later stage, Won or Lost.'
E_AUTO_DAYS = 'Use a whole number of days from 0 to 365.'
E_AUTO_FIELD = 'Choose the date it counts from.'
E_MEANS_OPEN = 'This stage has %d open lead%s. Move them out before it can mean Won or Lost.'
E_MEANS_CLOSED = '%d lead%s finished in this stage, so it has to stay %s.'
E_REMOVE_OPEN = '“%s” still has %d open lead%s. Move them to another stage first.'
E_REMOVE_CLOSED = "%d lead%s finished in “%s”, so it can't be removed. Rename it instead."
E_REMOVE_USED = 'This stage is used by “Move by itself” in %s. Pick another stage there first.'
E_BUTTON_CODE = 'Use 1 to 20 letters or digits.'
E_BUTTON_DUP = 'Another stage uses the code “%s”.'
E_STEP_TITLE = 'Give the follow-up a name.'
E_STEPS_MAX = 'A stage can have at most 20 follow-ups.'
E_STEP_CODE_DUP = 'Another follow-up in this pipeline uses the code “%s”.'
E_STEP_VALUE = 'Use a whole number from 0 to %d.'
E_STEP_WHEN = 'Choose when it happens.'
E_STEP_FIELD = 'Choose the date it counts from.'
E_STEP_TEMPLATE = 'Choose a template from the list.'
E_STEP_AUTO = 'Goes by itself needs an approved WhatsApp template.'
E_FILLS = 'Choose a value for each fill-in.'
E_FIELD_LABEL = 'Name the detail.'
E_FIELD_DUP = 'Two details are called “%s”.'
E_FIELD_CHOICES = 'Give at least two choices.'
E_FIELD_USED = 'This detail is used by a follow-up or a move in %s. Change that first.'
P_NAME = 'Name the product.'
P_CODE = 'Use 2 to 8 letters or digits, starting with a letter.'
P_CODE_RESERVED = '“%s” is used for a kind of follow-up. Pick another code.'
P_CODE_TAKEN = 'Another product uses “%s”. Pick another code.'
P_CODE_LABEL = "A pipeline's WhatsApp tag is “%s”. Pick another code."
P_CODE_SOURCE = 'A lead source adds the tag “%s”. Pick another code.'
P_CODE_LOCKED = 'Locked: %d lead%s use it.'
L_EMPTY = "Write the tag, e.g. '%s'."
L_BAD = 'Use letters, digits, spaces and - only, at most 30.'
L_PRODUCT = '“%s” is a product code. Pick another tag.'
L_TAKEN = 'Another pipeline uses the tag “%s”.'
L_SOURCE = 'A lead source adds the tag “%s”. Pick another tag.'
L_RESERVED = 'That name is kept for people who opted out. Pick another tag.'
TAG_HAND = 'WhatsApp already uses “%s” on %d contact%s. Pick another name.'
TAKE_OVER = "Take over this tag (it will be taken off contacts that don't qualify)"
PREVIEW = "appears as '%s' and '%s: %s'"
TAG_REPORT = 'This changes the tag on %d %s'
TAG_RULES = ' and is used by %d reply rule%s (%s).'
TAG_CHANGED = 'Changed. Their WhatsApp tags follow in a few minutes.'
BANNER = '%d follow-up%s need%s a WhatsApp template before %s can go after 24 hours'
NOT_CONNECTED = 'WhatsApp is not connected for leads yet.'
DRAFT_MADE = 'Added to WhatsApp templates. Send it for approval there.'
DRAFT_SAME = 'That template is in WhatsApp already.'
DRAFT_NO_WORDS = 'Write its words first.'
HINT_LINK = 'Press Make it a WhatsApp template to use it.'
COPIED_OFF = 'Follow-ups are copied with “Goes by itself” off. Turn it on for each one you want.'
ARRIVE = {'hand': 'Nothing to do: choose %s in Add a lead.',
          'whatsapp': 'In WhatsApp chats, choose %s beside a new chat.',
          'form': 'We made a form source for it. Copy this for your developer.',
          'source': 'Leads from “%s” now come here.'}
ARRIVE_ELSEWHERE = 'Choosing %s starts leads in %s. Make this one its default pipeline in Products to change that.'
MADE = 'Pipeline “%s” made. Check its stages and follow-ups.'
STEP_REMOVED_NOTE = 'Follow-up removed'
E_FAILED = 'Could not save. Nothing was changed.'

# every sentence the editor's script shows (it holds no words of its own)
WORDS = {
    'leave': 'Leave', 'move_q': 'Move its %d leads to %s too?',
    'move_line': 'Their WhatsApp tags change from “%s” to “%s”.', 'move_yes': 'Yes, move them',
    'move_no': 'No, only new leads', 'fix': E_FIX,
    'remove_open': 'This stage still has %d open lead%s. Move them to another stage first.',
    'remove_closed': "%d lead%s finished in this stage, so it can't be removed. Rename it instead.",
    'remove_used': E_REMOVE_USED, 'remove_step_q': 'Remove this follow-up?',
    'remove_step_line': 'Leads waiting on it move past it.', 'remove': 'Remove',
    'save_first': 'Save changes first.', 'not_connected': NOT_CONNECTED,
    'now': 'right away', 'after_hours': '%d hour%s after the last follow-up',
    'after_days': '%d day%s after the last follow-up', 'by_itself': 'goes by itself',
    'no_template': wa_templates.NO_TEMPLATE, 'fill_n': 'Fill-in %d', 'choose': '— choose —',
    'use_another': 'Use another template', 'use_one': 'Use a template', 'no_tpl_option': '— No template: write the words —',
    'words_label': {'whatsapp': 'The message', 'call': 'What to say', 'email': 'The e-mail', 'todo': 'What to do'},
    'open_chat_words': "Words for an open chat (used when the template can't go)",
    'lib_error': 'WhatsApp could not be reached, so its templates are not shown. Try again in a minute.',
    'approved': 'Approved', 'new_stage': 'New stage', 'unnamed': 'Untitled', 'field_label': E_FIELD_LABEL,
    'tag_same': 'That is the tag it has already.', 'tag_none': 'Write the tag first.',
    'stage_open': '%d open lead%s', 'reason_none': '— no reason —', 'tag_changed': TAG_CHANGED,
}

# ------------------------------------------------------------------------------------------ constants

FIELD_TYPE_LABELS = {'text': 'Text', 'number': 'Number', 'date': 'Date', 'choice': 'Choice', 'yesno': 'Yes / no'}
CURRENCIES = {'INR': 'Indian rupee (₹)', 'USD': 'US dollar ($)', 'GBP': 'British pound (£)', 'EUR': 'Euro (€)',
              'AUD': 'Australian dollar', 'CAD': 'Canadian dollar', 'AED': 'UAE dirham', 'SGD': 'Singapore dollar'}
ICONS = [('fa-shield-heart', 'Shield'), ('fa-plane-departure', 'Plane'), ('fa-house-medical', 'Home care'),
         ('fa-gift', 'Gift'), ('fa-user-doctor', 'Doctor'), ('fa-comments', 'Chat'), ('fa-user-nurse', 'Nurse'),
         ('fa-heart-pulse', 'Heart'), ('fa-stethoscope', 'Stethoscope'), ('fa-pills', 'Medicine'),
         ('fa-hand-holding-heart', 'Care'), ('fa-people-roof', 'Family'), ('fa-person-cane', 'Elder'),
         ('fa-wheelchair', 'Wheelchair'), ('fa-car', 'Car'), ('fa-suitcase-rolling', 'Suitcase'),
         ('fa-passport', 'Passport'), ('fa-globe', 'Globe'), ('fa-house', 'House'), ('fa-briefcase', 'Work'),
         ('fa-graduation-cap', 'Study'), ('fa-phone', 'Phone'), ('fa-star', 'Star'), ('fa-layer-group', 'Other')]
BUTTONS = list(crm_defaults.MILESTONES.values())       # [('I sent the quote', 'Q'), ('I sent the payment link', 'PLS')]
BUTTON_STOP = {'i', 'we', 'sent', 'send', 'the', 'a', 'an', 'to', 'for', 'of', 'them', 'their', 'they', 'it'}
MAX_STAGES, MAX_STEPS, MAX_FIELDS, MAX_REASONS = 30, 20, 40, 20
AUTO_KINDS = ('no_reply', 'in_stage', 'after_date')
BUILT_IN_LABELS = tuple(CRM_DATE_FIELDS.values())


# ------------------------------------------------------------------------------------------ small helpers

def plural(n):
    return '' if n == 1 else 's'


def rel_url(endpoint, **values):
    """A Set-up address as crm.js wants it: relative to the Sales CRM's own base (/admin/crm/)."""
    from app.routes.crm import crm_url
    full, base = crm_url(endpoint, **values), crm_url('board')
    return full[len(base):] if full.startswith(base) else full


def _slug(text, sep='-', limit=40, default='pipeline'):
    return re.sub(r'[^a-z0-9]+', sep, (text or '').lower()).strip(sep)[:limit].strip(sep) or default


def _clean(text, limit):
    return ' '.join(str(text or '').split())[:limit]


def _int(value, low, high):
    """A whole number from low to high, or None."""
    if isinstance(value, bool):
        return None
    try:
        n = int(str(value).strip()) if not isinstance(value, int) else value
    except (TypeError, ValueError):
        return None
    return n if low <= n <= high else None


def product_mode_owner(code, exclude_id=None):
    """The first pipeline of this product (not a catch-all) whose WhatsApp tag is the product code, or None."""
    q = CrmPipeline.query.filter(CrmPipeline.product == code, CrmPipeline.catch_all.is_(False),
                                 CrmPipeline.tag_mode == 'product')
    if exclude_id:
        q = q.filter(CrmPipeline.id != exclude_id)
    return q.order_by(CrmPipeline.id).first()


def example_label(code, name):
    words = re.findall(r'[A-Za-z0-9]+', name or '')
    w = words[-1].lower() if words else 'renewals'
    if w == code.lower():
        w = '2'
    return ('%s %s' % (code, w))[:30]


def prefix_of(pipe):
    label = (pipe.tag_label or '').strip()
    return label if pipe.tag_mode == 'own' and label else pipe.product


def first_stage_name(pipe):
    st = pipe.first_stage
    return st.name if st is not None else 'New'


def form_snippet(key, code, url):
    """What a developer pastes on a page to send its form's leads here (shown escaped, so this file holds no
    raw phone input in any template)."""
    return ('<form data-lead-source="%s" data-product="%s">\n'
            '<input name="name"> <input name="phone"> <input name="email"> <textarea name="message"></textarea>\n'
            '<button>Send</button>\n</form>\n<script src="%s" defer></script>' % (key, code, url))


def button_code(label, taken):
    """The code a stage's button is saved under: 'Q' / 'PLS' for the two known buttons, else the initials of
    its words; a number is added when another stage has it."""
    known = dict(BUTTONS)
    if label in known:
        base = known[label]
    else:
        words = [w for w in re.findall(r'[A-Za-z0-9]+', label or '') if w.lower() not in BUTTON_STOP]
        base = ''.join(w[0] for w in words).upper()[:6] or 'B'
    code, n = base, 2
    taken_up = {t.upper() for t in taken}
    while code.upper() in taken_up:
        code = '%s%d' % (base, n)
        n += 1
    return code


def field_key(label, taken):
    key = re.sub(r'[^a-z0-9]+', '_', (label or '').lower()).strip('_')[:36] or 'detail'
    if key in CRM_DATE_FIELDS or key.startswith('_'):
        key = 'detail_' + key.lstrip('_')
    base, n = key, 2
    while key in taken:
        key = '%s_%d' % (base[:36], n)
        n += 1
    return key


# ------------------------------------------------------------------------------------------ name and tag checks (F56)

def _first_clash(items):
    return max(items, key=lambda i: i.get('contacts') or 0) if items else None


def _clash_said(clash):
    if not clash:
        return None
    n = clash.get('contacts') or 0
    return TAG_HAND % (clash['name'], n, plural(n))


def name_check(code=None, label=None, product_id=None, pipeline_id=None):
    """Whether a product code (or a pipeline's own tag label) may be used, and what WhatsApp already has under
    that name: {'error', 'clash': {'name', 'contacts'} | None, 'said', 'preview'}. Nothing is asked of
    WhatsApp while writes are off (crm.wa_tag_clashes answers [])."""
    out = {'error': None, 'clash': None, 'said': None, 'preview': ''}
    if code is not None:
        c = (code or '').strip().upper()
        if not crm_products.CODE_RE.match(c):
            out['error'] = P_CODE
            return out
        if c in crm_products.RESERVED:
            out['error'] = P_CODE_RESERVED % c
            return out
        other = CrmProduct.query.filter(func.upper(CrmProduct.code) == c)
        if product_id:
            other = other.filter(CrmProduct.id != int(product_id))
        if other.first() is not None:
            out['error'] = P_CODE_TAKEN % c
            return out
        if any((p.tag_label or '').strip().lower() == c.lower() for p in CrmPipeline.query.filter_by(tag_mode='own')):
            out['error'] = P_CODE_LABEL % c
            return out
        if c.lower() in crm._wa_live_source_tags():
            out['error'] = P_CODE_SOURCE % c
            return out
        out['preview'] = PREVIEW % (c, c, 'New')
        clash = _first_clash(crm.wa_tag_clashes(prefix=c))
    else:
        lab = ' '.join((label or '').split())
        if not lab:
            out['error'] = L_EMPTY % 'TI renewals'
            return out
        if not re.match(r'^[A-Za-z0-9][A-Za-z0-9 \-&]{0,29}$', lab):
            out['error'] = L_BAD
            return out
        if lab.lower() == crm.OPT_OUT_TAG:
            out['error'] = L_RESERVED
            return out
        if crm_products.by_code(lab) is not None:
            out['error'] = L_PRODUCT % lab.upper()
            return out
        others = CrmPipeline.query.filter_by(tag_mode='own')
        if pipeline_id:
            others = others.filter(CrmPipeline.id != int(pipeline_id))
        if any((p.tag_label or '').strip().lower() == lab.lower() for p in others):
            out['error'] = L_TAKEN % lab
            return out
        if lab.lower() in crm._wa_live_source_tags():
            out['error'] = L_SOURCE % lab
            return out
        pipe = db.session.get(CrmPipeline, int(pipeline_id)) if pipeline_id else None
        out['preview'] = PREVIEW % (pipe.product if pipe is not None else lab, lab,
                                    first_stage_name(pipe) if pipe is not None else 'New')
        clash = _first_clash(crm.wa_tag_clashes(prefix=lab))
    out['clash'] = clash
    out['said'] = _clash_said(clash)
    return out


# ------------------------------------------------------------------------------------------ the list and checklist

def lead_counts(pipe):
    """{stage id: (open leads, finished leads)} for a pipeline's stages."""
    out = {}
    for sid, status, n in (db.session.query(CrmLead.stage_id, CrmLead.status, func.count(CrmLead.id))
                           .filter(CrmLead.pipeline_id == pipe.id).group_by(CrmLead.stage_id, CrmLead.status)):
        o, c = out.get(sid, (0, 0))
        out[sid] = (o + n, c) if status == 'open' else (o, c + n)
    return out


def template_rows(force=False):
    """(rows, needs): one row per WhatsApp follow-up for the checklist, those not ready first; `needs` is how
    many are not ready. Statuses from the WhatsApp CRM's list (a minute old), or fresh when `force`."""
    st = wa_templates.statuses(force=force)
    info = wa_templates.infos()
    cand = {s.id: r for r in wa_templates.candidates() for s in r['steps']}
    steps = (CrmPlaybookStep.query.join(CrmStage, CrmStage.id == CrmPlaybookStep.stage_id)
             .join(CrmPipeline, CrmPipeline.id == CrmStage.pipeline_id)
             .filter(CrmPlaybookStep.channel == 'whatsapp')
             .order_by(CrmPipeline.id, CrmStage.position, CrmPlaybookStep.position).all())
    rows = []
    for step in steps:
        r = cand.get(step.id)
        name = step.wa_template or (r['name'] if r else None) or wa_templates.slug_name(step.code)
        linked = bool(step.wa_template)
        in_wa = name in st
        w = st.get(name)
        status = w if (linked or in_wa) else None
        problems = list(r['problems']) if r else []
        ready = linked and w == 'APPROVED'
        hint = (DRAFT_NO_WORDS if not step.body else '; '.join(problems) if problems
                else HINT_LINK if (not linked and in_wa) else '')
        pipe = step.stage.pipeline
        rows.append({'step': step, 'name': name, 'linked': linked, 'in_wa': in_wa, 'ready': ready,
                     'status_text': wa_templates.status_words(status, (info.get(name) or {}).get('rejection_reason')),
                     'css': wa_templates.status_css(status), 'hint': hint,
                     'can_make': (not ready) and bool(step.body) and not problems
                                 and (not linked or not in_wa or w == 'REJECTED'),
                     'where': '%s › %s › %s' % (pipe.name, step.stage.name, step.title),
                     'pipeline_id': pipe.id})
    rows.sort(key=lambda r: r['ready'])
    return rows, sum(1 for r in rows if not r['ready'])


def list_context(tab, edit=None, errors=None, form=None):
    from flask import url_for
    from flask_login import current_user
    from app.services import access
    pipelines = CrmPipeline.query.order_by(CrmPipeline.id).all()
    stage_n = dict(db.session.query(CrmStage.pipeline_id, func.count(CrmStage.id)).group_by(CrmStage.pipeline_id))
    open_n = dict(db.session.query(CrmLead.pipeline_id, func.count(CrmLead.id)).filter(CrmLead.status == 'open')
                  .group_by(CrmLead.pipeline_id))
    counts = {p.id: (stage_n.get(p.id, 0), open_n.get(p.id, 0)) for p in pipelines}
    products = crm_products.all()
    prod_leads = dict(db.session.query(CrmLead.product, func.count(CrmLead.id)).group_by(CrmLead.product))
    edit_prod = None
    if edit == 'new':
        edit_prod = CrmProduct(code='', name='', icon=crm_products.ICON_DEFAULT, offered=True, currency='INR')
    elif edit and str(edit).isdigit():
        edit_prod = db.session.get(CrmProduct, int(edit))
    rows, needs = template_rows(force=tab == 'templates')
    banner = (BANNER % (needs, plural(needs), 's' if needs == 1 else '', 'it' if needs == 1 else 'they')
              if needs else None)
    return {'tab': tab, 'pipelines': pipelines, 'counts': counts, 'products': products, 'prod_leads': prod_leads,
            'edit_prod': edit_prod, 'errors': errors or {}, 'form': form or {}, 'ICONS': ICONS,
            'CURRENCIES': CURRENCIES, 'TAKE_OVER': TAKE_OVER, 'P_CODE_LOCKED': P_CODE_LOCKED,
            'KPI_ROWS': [(k, crm_kpi.METRICS[k][0]) for k in crm_kpi.PRODUCT_ROWS],
            'rows': rows, 'needs': needs, 'banner': banner, 'tpl_error': wa_templates.error(),
            'can_templates': access.can(current_user, 'wa_templates'),
            'tpl_url': lambda name: url_for('messaging.templates', p='/settings?tab=templates&template=' + name),
            'wa_writes': crm.wa_writes_on()}


# ------------------------------------------------------------------------------------------ products

def product_errors(form, prod, prefix=''):
    """(errors, values) for the product form (prefix 'np_' inside the wizard). The code is locked once the
    product has leads. A hand-made WhatsApp tag of that name is refused unless taking it over is ticked."""
    errors, values = {}, {}
    get = lambda k: form.get(prefix + k)           # noqa: E731
    name = _clean(get('name'), 60)
    if not name:
        errors[prefix + 'name'] = P_NAME
    values['name'] = name
    icons = {c for c, _l in ICONS}
    values['icon'] = get('icon') if get('icon') in icons else (prod.icon if prod is not None and prod.icon in icons
                                                              else crm_products.ICON_DEFAULT)
    values['currency'] = get('currency') if get('currency') in CURRENCIES else 'INR'
    values['kpi_row'] = get('kpi_row') if get('kpi_row') in crm_kpi.PRODUCT_ROWS else None
    if prod is not None and prod.id:
        pid = _int(get('default_pipeline_id'), 1, 10 ** 9) if (get('default_pipeline_id') or '') else None
        values['default_pipeline_id'] = pid if pid and db.session.get(CrmPipeline, pid) is not None else None
        values['offered'] = get('offered') == 'on'
    leads = (db.session.query(func.count(CrmLead.id)).filter(CrmLead.product == prod.code).scalar()
             if prod is not None and prod.id else 0)
    if leads:
        values['code'] = prod.code
    else:
        code = (get('code') or '').strip().upper()
        values['code'] = code
        check = name_check(code=code, product_id=prod.id if prod is not None and prod.id else None)
        if check['error']:
            errors[prefix + 'code'] = check['error']
        elif check['clash'] and get('take_over') != 'on':
            errors[prefix + '_clash'] = True
            errors[prefix + 'code'] = check['said']
    return errors, values


def _next_product_position():
    return (db.session.query(func.max(CrmProduct.position)).scalar() or 0) + 1


def save_product(form, actor):
    """A product saved from Set-up -> Pipelines -> Products. (product, errors). Commits."""
    pid = form.get('id')
    prod = db.session.get(CrmProduct, int(pid)) if pid and str(pid).isdigit() else None
    errors, values = product_errors(form, prod)
    if errors:
        return prod, errors
    new = prod is None
    if new:
        prod = CrmProduct(code=values['code'], name=values['name'], position=_next_product_position())
        db.session.add(prod)
    old_code = prod.code
    prod.name, prod.icon, prod.currency, prod.kpi_row = (values['name'], values['icon'], values['currency'],
                                                          values['kpi_row'])
    if not new:
        prod.offered = values['offered']
        prod.default_pipeline_id = values['default_pipeline_id']
        if values['code'] != old_code:
            for model in (CrmPipeline, CrmSource, CrmAnswer):
                model.query.filter(model.product == old_code).update({'product': values['code']},
                                                                     synchronize_session=False)
            prod.code = values['code']
    else:
        prod.offered = True
    db.session.flush()
    crm_products.invalidate()
    ActivityEvent.log('crm_product_saved', actor=actor, code=prod.code, new=new)
    db.session.commit()
    crm.wa_tag_rule_changed()
    return prod, {}


def set_offered(prod, on, actor):
    prod.offered = bool(on)
    ActivityEvent.log('crm_product_offered', actor=actor, code=prod.code, offered=bool(on))
    db.session.commit()
    crm_products.invalidate()


# ------------------------------------------------------------------------------------------ the editor's data

def stamp(pipe):
    """A fingerprint of everything the editor edits: a save made from an older page is refused (409)."""
    fields = CrmField.query.filter_by(pipeline_id=pipe.id).order_by(CrmField.position, CrmField.id).all()
    stages = sorted(pipe.stages, key=lambda s: (s.position, s.id))
    struct = {
        'p': [pipe.name, pipe.is_active, pipe.product, pipe.catch_all, pipe.fallout_reasons, pipe.tag_mode,
              pipe.tag_label],
        'f': [[f.id, f.key, f.label, f.type, f.options, f.position, f.on_card, f.on_add, f.required] for f in fields],
        's': [[s.id, s.key, s.name, s.position, s.means, s.on_reply, s.sla_hours, s.auto_kind, s.auto_field,
               s.auto_days, s.auto_to_id, s.auto_reason, s.button_label, s.button_code,
               [[t.id, t.position, t.code, t.title, t.channel, t.body, t.trigger, t.trigger_value, t.trigger_field,
                 t.kind, t.wa_params, bool(t.auto), t.wa_template]
                for t in sorted(s.steps, key=lambda x: (x.position, x.id))]] for s in stages]}
    return hashlib.sha1(json.dumps(struct, sort_keys=True, default=str).encode('utf-8')).hexdigest()


def when_of(step):
    """A follow-up's timing as the drawer shows it."""
    field = crm.step_date_field(step)
    if field:
        n = crm.step_offset_days(step)
        return {'type': 'date', 'value': abs(n), 'sign': 'before' if n < 0 else 'after', 'field': field}
    v = step.trigger_value or 0
    if v == 0:
        return {'type': 'now'}
    if v % 24 == 0:
        return {'type': 'after', 'value': v // 24, 'unit': 'days'}
    return {'type': 'after', 'value': v, 'unit': 'hours'}


def step_json(s):
    return {'id': s.id, 'ref': 't%d' % s.id, 'channel': s.channel, 'title': s.title, 'kind': s.kind or 'other',
            'code': s.code, 'when': when_of(s), 'body': s.body or '', 'wa_template': s.wa_template,
            'wa_params': wa_templates.step_param_keys(s), 'auto': bool(s.auto)}


def step_summary(s, lib=None):
    """One line for the stage card: 'WhatsApp · “Welcome” · right away · goes by itself · ✓ Approved'."""
    bits = [CRM_CHANNEL_LABELS.get(s.channel, s.channel), '“%s”' % s.title, crm.step_when(s)]
    if s.channel == 'whatsapp':
        if s.auto:
            bits.append('goes by itself')
        lib = lib if lib is not None else {}
        row = lib.get(s.wa_template) if s.wa_template else None
        if row is not None and row.get('status') == 'APPROVED':
            bits.append('✓ ' + wa_templates.STATUS_WORDS['APPROVED'])
        else:
            bits.append(wa_templates.status_words(row.get('status') if row else None,
                                                  row.get('rejection_reason') if row else None))
    return ' · '.join(bits)


def date_options(pipe):
    return crm.date_fields(pipe)


def editor_context(pipe, user, open_step=None, made=None, source_key=None):
    from flask import url_for
    stages = sorted(pipe.stages, key=lambda s: (s.position, s.id))
    counts = lead_counts(pipe)
    own_fields = CrmField.query.filter_by(pipeline_id=pipe.id).order_by(CrmField.position, CrmField.id).all()
    global_fields = CrmField.query.filter(CrmField.pipeline_id.is_(None)).order_by(CrmField.position, CrmField.id).all()
    lib = wa_templates.library()
    labels = wa_templates.template_labels()
    lib_by = {r['name']: r for r in lib}
    templates = {}
    for r in lib:
        n = r['name']
        templates[n] = {'status': r['status'], 'status_text': wa_templates.status_words(r['status'], r['rejection_reason']),
                        'css': wa_templates.status_css(r['status']), 'category': r['category'], 'body': r['body'],
                        'variables': r['variables'], 'label': labels.get(n) or n.replace('_', ' '),
                        'approved': r['status'] == 'APPROVED'}
    approved = sorted((n for n, t in templates.items() if t['approved']), key=lambda n: templates[n]['label'].lower())
    dates = []
    for key, label in date_options(pipe):
        dates.append({'key': key, 'label': label, 'before': crm._date_words(key, pipe, -1),
                      'after': crm._date_words(key, pipe, 1), 'on': crm._date_words(key, pipe, 0)})
    taken = {}
    for prod in crm_products.all():
        owner = product_mode_owner(prod.code, pipe.id)
        if owner is not None:
            taken[prod.code] = owner.name
    snippet = None
    if made == 'form' and source_key:
        snippet = form_snippet(source_key, pipe.product, url_for('static', filename='js/lead-capture.js', _external=True))
    data = {
        'stamp': stamp(pipe),
        'urls': {'save': rel_url('pipeline_save', pid=pipe.id), 'tag': rel_url('pipeline_tag', pid=pipe.id),
                 'draft': rel_url('template_draft'), 'label_check': rel_url('tag_check'),
                 'templates': (url_for('messaging.templates', p='/settings?tab=templates&template=__NAME__')
                               if _can_open_templates(user) else '')},
        'writes_on': crm.wa_writes_on(), 'product': pipe.product, 'products': crm_products.labels(),
        'product_leads': db.session.query(func.count(CrmLead.id)).filter(
            CrmLead.pipeline_id == pipe.id, CrmLead.product == pipe.product).scalar() or 0,
        'taken': taken, 'dates': dates, 'lib_error': wa_templates.library_error(), 'templates': templates,
        'approved': approved, 'open_step': open_step, 'words': WORDS,
        'fills': [{'key': k, 'label': v} for k, v in wa_templates.FILL_LABELS.items()],
        'channel_short': dict(CRM_CHANNEL_LABELS), 'tag_text': prefix_of(pipe), 'tag_mode': pipe.tag_mode,
        'tag_label': pipe.tag_label or '', 'field_types': dict(FIELD_TYPE_LABELS),
        'variable_tokens': list(wa_templates.VARIABLE_TOKENS),
    }
    return {'pipe': pipe, 'stages': stages, 'lead_counts': counts, 'fields': own_fields,
            'global_fields': global_fields, 'MEANS': CRM_MEANS_LABELS, 'FIELD_TYPES': FIELD_TYPE_LABELS,
            'STEP_CHANNELS': CRM_STEP_CHANNELS, 'STEP_KINDS': CRM_STEP_KINDS, 'FILLS': wa_templates.FILL_LABELS,
            'BUTTONS': BUTTONS, 'dates': dates, 'tag_text': prefix_of(pipe), 'snippet': snippet, 'data': data,
            'TAKE_OVER': TAKE_OVER, 'E_REMOVE_USED': E_REMOVE_USED,
            'step_json': step_json, 'summary': lambda s: step_summary(s, lib_by),
            'reasons': list(pipe.fallout_reasons or [])}


def _can_open_templates(user):
    from app.services import access
    return bool(access.can(user, 'wa_templates'))


# ------------------------------------------------------------------------------------------ validate

def validate(pipe, data):
    """(plan, errors): the posted pipeline checked against the stored one. Changes nothing. `errors` is
    {key: message}: '_' (top), name, product, catch_all, reasons, fields, '<field ref>', '<stage ref>.<what>',
    '<follow-up ref>'."""
    errors = {}
    data = data if isinstance(data, dict) else {}
    plan = {}

    def err(key, msg):
        errors.setdefault(key, msg)

    # ---- header
    name = _clean(data.get('name'), 80)
    if not name:
        err('name', E_NAME)
    plan['name'] = name
    plan['is_active'] = bool(data.get('is_active'))
    product = crm_products.by_code(data.get('product'))
    plan['product'] = product.code if product else pipe.product
    plan['product_changed'] = False
    plan['move_leads'] = False
    plan['catch_all'] = bool(data.get('catch_all'))
    if product is None:
        err('product', E_PRODUCT)
    elif product.code != pipe.product:
        plan['product_changed'] = True
        leads = db.session.query(func.count(CrmLead.id)).filter(
            CrmLead.pipeline_id == pipe.id, CrmLead.product == pipe.product).scalar() or 0
        if leads:
            if data.get('move_leads') is True or data.get('move_leads') is False:
                plan['move_leads'] = data['move_leads']
            else:
                err('product', E_MOVE)
        if pipe.tag_mode == 'product' and not plan['catch_all']:
            owner = product_mode_owner(product.code, pipe.id)
            if owner is not None:
                err('product', E_TAG_TAKEN % (owner.name, product.code, example_label(product.code, name)))
    elif pipe.catch_all and not plan['catch_all'] and pipe.tag_mode == 'product':
        owner = product_mode_owner(pipe.product, pipe.id)
        if owner is not None:
            err('catch_all', E_TAG_TAKEN % (owner.name, pipe.product, example_label(pipe.product, name)))
    reasons, seen = [], set()
    for r in data.get('reasons') or []:
        r = _clean(r, 80)
        if r and r.lower() not in seen:
            seen.add(r.lower())
            reasons.append(r)
    plan['reasons'] = reasons[:MAX_REASONS]

    # ---- the details asked
    stored_fields = {f.id: f for f in CrmField.query.filter_by(pipeline_id=pipe.id).all()}
    global_keys = {k for (k,) in db.session.query(CrmField.key).filter(CrmField.pipeline_id.is_(None))}
    posted = data.get('fields') if isinstance(data.get('fields'), list) else []
    if len(posted) > MAX_FIELDS:
        err('fields', 'A pipeline can ask at most %d details.' % MAX_FIELDS)
        posted = posted[:MAX_FIELDS]
    taken_keys = {f.key for f in stored_fields.values()} | global_keys | set(CRM_DATE_FIELDS)
    labels_seen = {l.lower() for l in BUILT_IN_LABELS}
    fields, new_keys, posted_ids = [], {}, set()
    for i, raw in enumerate(posted):
        raw = raw if isinstance(raw, dict) else {}
        ref = str(raw.get('ref') or 'f_%d' % i)
        fid = raw.get('id')
        old = None
        if fid not in (None, ''):
            old = stored_fields.get(fid if isinstance(fid, int) else _int(fid, 1, 10 ** 9))
            if old is None:
                err('_', E_OLD)
                continue
            posted_ids.add(old.id)
        label = _clean(raw.get('label'), 80)
        if not label:
            err(ref, E_FIELD_LABEL)
        elif label.lower() in labels_seen:
            err(ref, E_FIELD_DUP % label)
        labels_seen.add(label.lower())
        ftype = old.type if old is not None else (raw.get('type') if raw.get('type') in CRM_FIELD_TYPES else 'text')
        options = None
        if ftype == 'choice':
            opts = raw.get('options')
            if isinstance(opts, str):
                opts = opts.splitlines()
            options = []
            for o in opts or []:
                o = _clean(o, 60)
                if o and o not in options:
                    options.append(o)
            options = options[:30]
            if len(options) < 2:
                err(ref, E_FIELD_CHOICES)
        if old is not None:
            key = old.key
        else:
            key = field_key(label, taken_keys)
            taken_keys.add(key)
            new_keys[ref] = key
        on_add = bool(raw.get('on_add'))
        fields.append({'id': old.id if old is not None else None, 'ref': ref, 'key': key, 'label': label,
                       'type': ftype, 'options': options, 'position': i, 'on_card': bool(raw.get('on_card')),
                       'on_add': on_add, 'required': bool(raw.get('required')) and on_add})
    plan['fields'] = fields
    plan['removed_fields'] = [f.id for f in stored_fields.values() if f.id not in posted_ids]
    removed_keys = {stored_fields[i].key for i in plan['removed_fields']}
    date_keys = set(CRM_DATE_FIELDS) | {f['key'] for f in fields if f['type'] == 'date'}
    date_keys |= {f.key for f in CrmField.query.filter(CrmField.pipeline_id.is_(None), CrmField.type == 'date')}

    def resolve_date(value):
        value = (value or '').strip() if isinstance(value, str) else ''
        if value.startswith('new:'):
            value = new_keys.get(value[4:], '')
        return value if value in date_keys else ''

    # ---- stages
    stored_stages = {s.id: s for s in pipe.stages}
    posted_stages = data.get('stages') if isinstance(data.get('stages'), list) else []
    if len(posted_stages) > MAX_STAGES:
        err('_', E_STAGES_MAX)
        posted_stages = posted_stages[:MAX_STAGES]
    counts = lead_counts(pipe)
    stages, names_seen, posted_stage_ids = [], set(), set()
    refs = []
    for i, raw in enumerate(posted_stages):
        raw = raw if isinstance(raw, dict) else {}
        ref = str(raw.get('ref') or 'n_s%d' % i)
        refs.append(ref)
    ref_pos = {r: i for i, r in enumerate(refs)}
    means_of = {}
    for i, raw in enumerate(posted_stages):
        means_of[refs[i]] = raw.get('means') if isinstance(raw, dict) and raw.get('means') in CRM_STAGE_MEANS else 'talking'
    reply_seen = False
    button_codes = {}
    for i, raw in enumerate(posted_stages):
        raw = raw if isinstance(raw, dict) else {}
        ref = refs[i]
        sid = raw.get('id')
        old = None
        if sid not in (None, ''):
            old = stored_stages.get(sid if isinstance(sid, int) else _int(sid, 1, 10 ** 9))
            if old is None:
                err('_', E_OLD)
                continue
            posted_stage_ids.add(old.id)
        sname = _clean(raw.get('name'), 60)
        if not sname:
            err(ref + '.name', E_STAGE_NAME)
        elif sname.lower() in names_seen:
            err(ref + '.name', E_STAGE_DUP % sname)
        names_seen.add(sname.lower())
        means = means_of[ref]
        kind_new = means if means in ('won', 'lost') else 'open'
        if old is not None:
            open_n, closed_n = counts.get(old.id, (0, 0))
            old_means = old.stage_means
            kind_old = old_means if old_means in ('won', 'lost') else 'open'
            if open_n and kind_new != 'open':
                err(ref + '.means', E_MEANS_OPEN % (open_n, plural(open_n)))
            elif closed_n and kind_new != kind_old:
                err(ref + '.means', E_MEANS_CLOSED % (closed_n, plural(closed_n), CRM_MEANS_LABELS[old_means]))
        on_reply = bool(raw.get('on_reply'))
        if on_reply and reply_seen:
            err(ref + '.on_reply', E_REPLY_ONE)
        reply_seen = reply_seen or on_reply
        sla = raw.get('sla_hours')
        if sla in (None, ''):
            sla = None
        else:
            sla = _int(sla, 1, 2000)
            if sla is None:
                err(ref + '.sla_hours', E_SLA)
        # moves by itself
        auto = raw.get('auto') if isinstance(raw.get('auto'), dict) else {}
        a = {'kind': None, 'field': None, 'days': None, 'to': None, 'reason': None}
        akind = auto.get('kind') or ''
        if akind:
            if akind not in AUTO_KINDS:
                err(ref + '.auto', E_AUTO_TO)
            else:
                a['kind'] = akind
                days = _int(auto.get('days'), 0, 365)
                if days is None:
                    err(ref + '.auto', E_AUTO_DAYS)
                a['days'] = days
                to = auto.get('to')
                if to not in ref_pos or to == ref:
                    err(ref + '.auto', E_AUTO_TO)
                else:
                    a['to'] = to
                    if (akind in ('in_stage', 'after_date') and ref_pos[to] < i
                            and means_of.get(to) not in ('won', 'lost')):
                        err(ref + '.auto', E_AUTO_BACK)
                if akind == 'after_date':
                    field = resolve_date(auto.get('field'))
                    if not field:
                        err(ref + '.auto', E_AUTO_FIELD)
                    a['field'] = field or None
                a['reason'] = _clean(auto.get('reason'), 80) or None
        # the button on the lead
        button = raw.get('button') if isinstance(raw.get('button'), dict) else {}
        blabel = _clean(button.get('label'), 60)
        bcode = str(button.get('code') or '').strip()
        if blabel and bcode:
            if not re.match(r'^[A-Za-z0-9]{1,20}$', bcode):
                err(ref + '.button', E_BUTTON_CODE)
            else:
                bcode = bcode.upper()
                if bcode in button_codes:
                    err(ref + '.button', E_BUTTON_DUP % bcode)
                button_codes[bcode] = ref
        elif not blabel:
            bcode = ''
        steps = _validate_steps(pipe, raw, ref, old, errors, resolve_date, removed_keys)
        stages.append({'id': old.id if old is not None else None, 'ref': ref, 'name': sname, 'means': means,
                       'on_reply': on_reply, 'sla_hours': sla, 'auto': a, 'button_label': blabel or None,
                       'button_code': bcode or None, 'steps': steps})
    plan['stages'] = stages
    if not any(means_of.get(r) not in ('won', 'lost') for r in refs):
        err('_', E_NO_OPEN)
    # the details taken away must not be in use by a follow-up or a move that stays
    for stg in stages:
        used = {s['field'] for s in stg['steps'] if s['field']} | ({stg['auto']['field']} if stg['auto']['field'] else set())
        if used & removed_keys:
            err('fields', E_FIELD_USED % (stg['name'] or 'a stage'))
    # stages taken away
    plan['removed_stages'] = []
    for st in stored_stages.values():
        if st.id in posted_stage_ids:
            continue
        plan['removed_stages'].append(st.id)
        open_n, closed_n = counts.get(st.id, (0, 0))
        if open_n:
            err('_', E_REMOVE_OPEN % (st.name, open_n, plural(open_n)))
        elif closed_n:
            err('_', E_REMOVE_CLOSED % (closed_n, plural(closed_n), st.name))
        removed_ref = 's%d' % st.id
        for stg in stages:
            if stg['auto']['to'] == removed_ref:
                err(stg['ref'] + '.auto', E_AUTO_TO)
    posted_step_ids = {s['id'] for stg in stages for s in stg['steps'] if s['id']}
    plan['removed_steps'] = [t.id for st in stored_stages.values() for t in st.steps if t.id not in posted_step_ids]
    return plan, errors


def _validate_steps(pipe, raw, sref, old_stage, errors, resolve_date, removed_keys):
    def err(key, msg):
        errors.setdefault(key, msg)

    posted = raw.get('steps') if isinstance(raw.get('steps'), list) else []
    if len(posted) > MAX_STEPS:
        err(sref + '.name', E_STEPS_MAX)
        posted = posted[:MAX_STEPS]
    stored = {t.id: t for st in pipe.stages for t in st.steps}
    info = wa_templates.infos() if any(isinstance(p, dict) and p.get('auto') for p in posted) else {}
    out = []
    for i, r in enumerate(posted):
        r = r if isinstance(r, dict) else {}
        tref = str(r.get('ref') or '%s_t%d' % (sref, i))
        tid = r.get('id')
        old = None
        if tid not in (None, ''):
            old = stored.get(tid if isinstance(tid, int) else _int(tid, 1, 10 ** 9))
            if old is None:
                err('_', E_OLD)
                continue
        title = _clean(r.get('title'), 160)
        if not title:
            err(tref, E_STEP_TITLE)
        channel = r.get('channel') if r.get('channel') in CRM_STEP_CHANNELS else 'whatsapp'
        kind = r.get('kind') if r.get('kind') in CRM_STEP_KINDS else 'other'
        # when
        when = r.get('when') if isinstance(r.get('when'), dict) else {}
        wtype, trigger, field, value = when.get('type'), 'after_hours', None, 0
        if wtype == 'now':
            pass
        elif wtype == 'after':
            unit = 'days' if when.get('unit') == 'days' else 'hours'
            n = _int(when.get('value'), 0, 365 if unit == 'days' else 2000)
            if n is None:
                err(tref, E_STEP_VALUE % (365 if unit == 'days' else 2000))
            else:
                value = n * 24 if unit == 'days' else n
        elif wtype == 'date':
            n = _int(when.get('value'), 0, 365)
            fld = resolve_date(when.get('field'))
            if n is None:
                err(tref, E_STEP_VALUE % 365)
            elif not fld:
                err(tref, E_STEP_FIELD)
            else:
                trigger, field = 'date_offset', fld
                value = -n if when.get('sign') == 'before' else n
        else:
            err(tref, E_STEP_WHEN)
        code = str(r.get('code') or '').strip()[:20]
        body = str(r.get('body') or '').strip()[:4000] or None
        tpl = r.get('wa_template')
        tpl = str(tpl).strip() if tpl else None
        if tpl and not re.match(r'^[a-z0-9_]{1,80}$', tpl):
            err(tref, E_STEP_TEMPLATE)
            tpl = None
        if channel != 'whatsapp':
            tpl = None
        params = r.get('wa_params')
        if params in (None, [], ''):
            params = None
        elif not isinstance(params, list) or not (1 <= len(params) <= 20) or any(
                not isinstance(k, str) or k not in wa_templates.FILL_LABELS for k in params):
            err(tref, E_FILLS)
            params = None
        if tpl is None:
            params = None
        known_vars = (info.get(tpl) or wa_templates.template_info(tpl) or {}).get('variables') if tpl else None
        if params is not None and known_vars is not None and len(params) != known_vars:
            err(tref, E_FILLS)
        auto = bool(r.get('auto')) and channel == 'whatsapp'
        if auto:
            newly = old is None or not old.auto or (old.wa_template or None) != tpl
            if newly:
                if not (tpl and wa_templates.approved(tpl)):
                    err(tref, E_STEP_AUTO)
                else:
                    have = len(params) if params is not None else wa_templates.blanks(body)
                    if known_vars is not None and have != known_vars:
                        err(tref, E_FILLS)
        out.append({'id': old.id if old is not None else None, 'ref': tref, 'channel': channel, 'title': title,
                    'kind': kind, 'code': code, 'trigger': trigger, 'field': field, 'value': value, 'body': body,
                    'wa_template': tpl, 'wa_params': params, 'auto': auto})
    # a code typed by hand (new, or changed) is unique among the pipeline's follow-ups
    return out


def _check_step_codes(pipe, plan, errors):
    """Codes are unique in the whole pipeline, so this runs once the stages are all known."""
    stored = {t.id: t for st in pipe.stages for t in st.steps}
    seen = {}
    for stg in plan['stages']:
        for s in stg['steps']:
            if s['code']:
                seen.setdefault(s['code'].lower(), []).append(s)
    for code, rows in seen.items():
        if len(rows) < 2:
            continue
        for s in rows:
            old = stored.get(s['id'])
            if old is None or (old.code or '').strip().lower() != code:
                errors.setdefault(s['ref'], E_STEP_CODE_DUP % s['code'])


# ------------------------------------------------------------------------------------------ apply and save

def _stage_key(name, taken):
    base = _slug(name, sep='_', limit=36, default='stage')
    key, n = base, 2
    while key in taken:
        key = '%s_%d' % (base, n)
        n += 1
    taken.add(key)
    return key


def apply(pipe, plan, actor):
    """Make the stored pipeline what the plan says. Changes the session; never commits. A summary of what
    changed (counts), for the audit line and the toast."""
    summary = {'stages_added': 0, 'stages_removed': 0, 'stages_renamed': 0, 'steps_added': 0, 'steps_removed': 0,
               'fields_added': 0, 'fields_removed': 0, 'moved': 0, 'renamed_pairs': []}
    # ---- header
    pipe.name, pipe.is_active, pipe.catch_all = plan['name'], plan['is_active'], plan['catch_all']
    pipe.fallout_reasons = plan['reasons']
    if plan['product_changed']:
        old, new = pipe.product, plan['product']
        pipe.product = new
        CrmSource.query.filter(CrmSource.pipeline_id == pipe.id, CrmSource.product == old).update(
            {'product': new}, synchronize_session=False)
        was = CrmProduct.query.filter_by(code=old).first()
        if was is not None and was.default_pipeline_id == pipe.id:
            was.default_pipeline_id = None
        now_p = CrmProduct.query.filter_by(code=new).first()
        if now_p is not None and not now_p.default_pipeline_id:
            now_p.default_pipeline_id = pipe.id
        if plan['move_leads']:
            summary['moved'] = CrmLead.query.filter(CrmLead.pipeline_id == pipe.id, CrmLead.product == old).update(
                {'product': new}, synchronize_session=False)
            crm.wa_mark_pipeline(pipe)
        summary['product'] = [old, new]
        crm_products.invalidate()
    # ---- details asked
    stored = {f.id: f for f in CrmField.query.filter_by(pipeline_id=pipe.id).all()}
    for f in plan['fields']:
        row = stored.get(f['id'])
        if row is None:
            row = CrmField(pipeline_id=pipe.id, key=f['key'], label=f['label'], type=f['type'])
            db.session.add(row)
            summary['fields_added'] += 1
        row.label, row.options, row.position = f['label'], f['options'], f['position']
        row.on_card, row.on_add, row.required = f['on_card'], f['on_add'], f['required']
    for fid in plan['removed_fields']:
        db.session.delete(stored[fid])
        summary['fields_removed'] += 1
    # ---- stages
    st_by_id = {s.id: s for s in pipe.stages}
    taken_keys = {s.key for s in pipe.stages}
    rows, by_ref = [], {}
    for i, sp in enumerate(plan['stages']):
        st = st_by_id.get(sp['id'])
        if st is None:
            st = CrmStage(key=_stage_key(sp['name'], taken_keys), name=sp['name'])
            pipe.stages.append(st)
            summary['stages_added'] += 1
        elif st.name != sp['name']:
            summary['renamed_pairs'].append((st, st.name))
            summary['stages_renamed'] += 1
        st.name, st.means, st.on_reply, st.sla_hours = sp['name'], sp['means'], sp['on_reply'], sp['sla_hours']
        st.button_label = sp['button_label']
        st.position = i
        rows.append((st, sp))
        by_ref[sp['ref']] = st
    for st, sp in rows:
        if sp['button_label']:
            others = [o['button_code'] for _s, o in rows if o is not sp and o['button_code']]
            st.button_code = sp['button_code'] or button_code(sp['button_label'], others)
            sp['button_code'] = st.button_code
        else:
            st.button_code = None
    db.session.flush()
    for st, sp in rows:
        a = sp['auto']
        target = by_ref.get(a['to']) if a['kind'] else None
        if a['kind'] and target is not None:
            st.auto_kind, st.auto_days, st.auto_field, st.auto_reason, st.auto_to = (
                a['kind'], a['days'], a['field'], a['reason'], target)
        else:
            st.auto_kind = st.auto_days = st.auto_field = st.auto_reason = None
            st.auto_to = None
    # ---- follow-ups
    step_by_id = {t.id: t for s in pipe.stages for t in s.steps}
    for st, sp in rows:
        for pos, tp in enumerate(sp['steps']):
            step = step_by_id.get(tp['id'])
            if step is None:
                step = CrmPlaybookStep(stage=st, code='STEP', title='STEP', position=pos)     # NOT NULL, set below
                db.session.add(step)
                summary['steps_added'] += 1
            elif step.stage is not st:
                step.stage = st
            step.position = pos
            step.channel, step.title, step.kind = tp['channel'], tp['title'], tp['kind']
            step.trigger, step.trigger_field, step.trigger_value = tp['trigger'], tp['field'], tp['value']
            step.body, step.wa_template, step.wa_params, step.auto = (tp['body'], tp['wa_template'],
                                                                      tp['wa_params'], tp['auto'])
            tp['row'] = step
    for _st, sp in rows:
        for tp in sp['steps']:
            tp['row'].code = tp['code'] or crm.next_step_code(pipe, tp['row'].kind)
    # ---- follow-ups taken away (their open tasks are skipped), then the stages taken away
    now = datetime.utcnow()
    gone_steps = list(plan['removed_steps'])
    for sid in plan['removed_stages']:
        st = st_by_id.get(sid)
        if st is not None:
            gone_steps += [t.id for t in st.steps if t.id not in gone_steps]
    for tid in gone_steps:
        CrmTask.query.filter_by(step_id=tid, status='open').update(
            {'status': 'skipped', 'note': STEP_REMOVED_NOTE, 'done_at': now}, synchronize_session=False)
        CrmTask.query.filter_by(step_id=tid).update({'step_id': None}, synchronize_session=False)
    summary['steps_removed'] = len(gone_steps)
    db.session.flush()
    for tid in plan['removed_steps']:
        step = step_by_id.get(tid)
        if step is not None:
            db.session.delete(step)
    for sid in plan['removed_stages']:
        st = st_by_id.get(sid)
        if st is None:
            continue
        CrmStage.query.filter(CrmStage.auto_to_id == st.id).update({'auto_to_id': None}, synchronize_session=False)
        CrmStageChange.query.filter((CrmStageChange.to_stage_id == st.id) |
                                    (CrmStageChange.from_stage_id == st.id)).delete(synchronize_session=False)
        db.session.delete(st)
        summary['stages_removed'] += 1
    db.session.flush()
    return summary


def save(pipe, data, actor):
    """One Save of the pipeline editor: {'status': 200 | 409 | 422 | 500, 'body': {...}}."""
    data = data if isinstance(data, dict) else {}
    if data.get('stamp') != stamp(pipe):
        return {'status': 409, 'body': {'error': E_STALE}}
    plan, errors = validate(pipe, data)
    _check_step_codes(pipe, plan, errors)
    if errors:
        return {'status': 422, 'body': {'errors': errors, 'error': E_FIX}}
    try:
        summary = apply(pipe, plan, actor)
        pairs = summary.pop('renamed_pairs')
        ActivityEvent.log('crm_pipeline_saved', actor=actor, pipeline=pipe.key, **summary)
        db.session.commit()
    except Exception:      # noqa: BLE001 -- nothing may be half saved
        db.session.rollback()
        log.warning('Pipeline editor save failed', exc_info=True)
        return {'status': 500, 'body': {'error': E_FAILED}}
    try:
        if pairs:
            crm.stages_renamed(pairs)
            db.session.commit()
        crm.wa_tag_rule_changed()
    except Exception:      # noqa: BLE001 -- the structure is saved; the tags catch up through the jobs runner
        db.session.rollback()
        log.warning('Pipeline editor: tags not brought into step', exc_info=True)
    n = summary['moved']
    prod = crm_products.by_code(pipe.product)
    return {'status': 200, 'body': {
        'success': True, 'stamp': stamp(pipe),
        'message': SAVED_MOVED % (n, plural(n), prod.name if prod else pipe.product) if n else SAVED}}


def set_active(pipe, on, actor):
    """The "Taking new leads" switch. Returns the toast."""
    pipe.is_active = bool(on)
    ActivityEvent.log('crm_pipeline_active', actor=actor, pipeline=pipe.key, active=bool(on))
    db.session.commit()
    if not on and CrmSource.query.filter(CrmSource.pipeline_id == pipe.id).first() is not None:
        target = crm_products.default_pipeline(pipe.product)
        if target is not None and target.id != pipe.id:
            return 'Saved. New leads go to %s instead.' % target.name
    return 'Saved'


# ------------------------------------------------------------------------------------------ the tag dialog

def _rules_using(pipe):
    """The names of the WhatsApp CRM's reply rules (automations) triggered by one of this pipeline's tags."""
    if not wacrm_team.enabled():
        return []
    try:
        with wacrm.short_timeouts():
            items = wacrm_team.automations()
    except wacrm_team.TeamError:
        return []
    pre = prefix_of(pipe).lower() + ': '
    return [i.get('name') or 'Untitled' for i in items
            if any(str(t).lower().startswith(pre) for t in i.get('trigger_tags') or [])]


def tag_report(pipe, mode, label):
    """What changing the pipeline's WhatsApp tag would do: {'error', 'clash', 'said', 'preview', 'same'}."""
    mode = 'own' if mode == 'own' else 'product'
    out = {'error': None, 'clash': None, 'said': None, 'preview': '', 'same': False}
    label = ' '.join((label or '').split())
    if mode == 'own':
        check = name_check(label=label, pipeline_id=pipe.id)
        out['error'], out['clash'] = check['error'], check['clash']
        new_prefix = label
        clash_said = check['said']
    else:
        owner = product_mode_owner(pipe.product, pipe.id) if not pipe.catch_all else None
        if owner is not None:
            out['error'] = E_TAG_TAKEN % (owner.name, pipe.product, example_label(pipe.product, pipe.name))
        new_prefix = pipe.product
        clash_said = None
    out['same'] = (mode == pipe.tag_mode and new_prefix.lower() == prefix_of(pipe).lower())
    people = (db.session.query(func.count(func.distinct(CrmLead.person_id)))
              .outerjoin(CrmPerson, CrmPerson.id == CrmLead.person_id)
              .filter(CrmLead.pipeline_id == pipe.id,
                      (CrmLead.status == 'open') | (CrmPerson.wacrm_contact_id.isnot(None))).scalar() or 0)
    rules = _rules_using(pipe)
    said = TAG_REPORT % (people, 'person' if people == 1 else 'people')
    if rules:
        shown = ', '.join('“%s”' % r for r in rules[:3]) + (' and %d more' % (len(rules) - 3) if len(rules) > 3 else '')
        said += TAG_RULES % (len(rules), plural(len(rules)), shown)
    else:
        said += '.'
    out['said'] = said
    if clash_said:
        out['clash_said'] = clash_said
    if not out['error']:
        out['preview'] = PREVIEW % (pipe.product, new_prefix, first_stage_name(pipe))
    return out


def change_tag(pipe, mode, label, take_over, actor, stamp_in):
    """"Change WhatsApp tag": {'status', 'body'}. The tags are renamed in place (ids and rules keep pointing at
    them) and everybody is brought into step quietly."""
    if stamp_in != stamp(pipe):
        return {'status': 409, 'body': {'error': E_STALE}}
    mode = 'own' if mode == 'own' else 'product'
    label = ' '.join((label or '').split())
    rep = tag_report(pipe, mode, label)
    if rep['error']:
        return {'status': 422, 'body': {'error': rep['error']}}
    if rep['clash'] and not take_over:
        return {'status': 422, 'body': {'error': rep.get('clash_said') or _clash_said(rep['clash']),
                                        'clash': rep['clash']}}
    if rep['same']:
        return {'status': 200, 'body': {'success': True, 'tag_text': prefix_of(pipe), 'preview': rep['preview'],
                                        'stamp': stamp(pipe), 'message': 'Saved'}}
    old_mode, old_label, old_prefix = pipe.tag_mode, pipe.tag_label, prefix_of(pipe)
    pipe.tag_mode = mode
    pipe.tag_label = label if mode == 'own' else None
    res = crm.pipeline_tag_changed(pipe, old_mode, old_label, actor)
    ActivityEvent.log('crm_pipeline_tag_changed', actor=actor, pipeline=pipe.key, old=old_prefix,
                      new=prefix_of(pipe), renamed=res['renamed'], marked=res['marked'])
    db.session.commit()
    crm.wa_tag_rule_changed()
    return {'status': 200, 'body': {'success': True, 'tag_text': prefix_of(pipe), 'preview': rep['preview'],
                                    'stamp': stamp(pipe), 'message': TAG_CHANGED}}


# ------------------------------------------------------------------------------------------ the wizard

def wizard_context(form, errors):
    pipes = CrmPipeline.query.order_by(CrmPipeline.id).all()
    taken = {}
    for prod in crm_products.all():
        owner = product_mode_owner(prod.code)
        if owner is not None:
            taken[prod.code] = {'pipeline': owner.name, 'example': example_label(prod.code, '')}
    return {'products': crm_products.all(), 'pipelines': pipes,
            'sources': CrmSource.query.order_by(CrmSource.name).all(), 'taken': taken,
            'first_stages': {p.id: first_stage_name(p) for p in pipes}, 'ICONS': ICONS, 'CURRENCIES': CURRENCIES,
            'KPI_ROWS': [(k, crm_kpi.METRICS[k][0]) for k in crm_kpi.PRODUCT_ROWS], 'TAKE_OVER': TAKE_OVER,
            'E_TAG_TAKEN': E_TAG_TAKEN, 'form': form or {}, 'errors': errors or {}, 'P_CODE_LOCKED': P_CODE_LOCKED}


def _copy_into(src, pipe, keep_templates):
    """A copy of a pipeline's stages, follow-ups (with "Goes by itself" off) and lead details."""
    pipe.fallout_reasons = list(src.fallout_reasons or [])
    mapping = {}
    for st in sorted(src.stages, key=lambda s: (s.position, s.id)):
        n = CrmStage(key=st.key, name=st.name, means=st.stage_means, on_reply=st.on_reply, sla_hours=st.sla_hours,
                     auto_kind=st.auto_kind, auto_field=st.auto_field, auto_days=st.auto_days,
                     auto_reason=st.auto_reason, button_label=st.button_label, button_code=st.button_code,
                     position=st.position)
        pipe.stages.append(n)
        mapping[st.id] = n
    db.session.flush()
    for st in src.stages:
        if st.auto_to_id and st.auto_to_id in mapping:
            mapping[st.id].auto_to = mapping[st.auto_to_id]
    for st in sorted(src.stages, key=lambda s: (s.position, s.id)):
        for t in sorted(st.steps, key=lambda x: (x.position, x.id)):
            step = CrmPlaybookStep(stage=mapping[st.id], code='STEP', title=t.title, position=t.position)
            db.session.add(step)
            step.channel, step.body, step.kind = t.channel, t.body, t.kind or 'other'
            step.trigger, step.trigger_field, step.trigger_value = t.trigger, t.trigger_field, t.trigger_value
            step.auto = False
            if keep_templates:
                step.wa_template, step.wa_params = t.wa_template, t.wa_params
            step.code = crm.next_step_code(pipe, step.kind)
    for f in CrmField.query.filter_by(pipeline_id=src.id).order_by(CrmField.position, CrmField.id):
        db.session.add(CrmField(pipeline=pipe, key=f.key, label=f.label, type=f.type, options=f.options,
                                position=f.position, on_card=f.on_card, on_add=f.on_add, required=f.required))


def create_pipeline(form, actor, snippet_url):
    """The wizard's answers -> (pipeline, notes, errors). One transaction; nothing is sent to anyone."""
    errors = {}
    name = _clean(form.get('name'), 80)
    if not name:
        errors['name'] = E_NAME
    new_values, code = None, None
    if form.get('product') == '__new':
        perrs, new_values = product_errors(form, None, 'np_')
        errors.update(perrs)
        code = new_values.get('code')
    else:
        prod = crm_products.by_code(form.get('product'))
        if prod is None:
            errors['product'] = E_PRODUCT
        else:
            code = prod.code
    start = form.get('start') if form.get('start') in ('copy', 'simple') else 'simple'
    src = None
    if start == 'copy':
        cid = form.get('copy_from')
        src = db.session.get(CrmPipeline, int(cid)) if cid and str(cid).isdigit() else None
        if src is None:
            errors['copy_from'] = 'Choose the pipeline to copy.'
    tag_mode = 'own' if form.get('tag_mode') == 'own' else 'product'
    label = ' '.join((form.get('tag_label') or '').split())
    if tag_mode == 'product' and code and form.get('product') != '__new':
        owner = product_mode_owner(code)
        if owner is not None:
            errors['tag_label'] = E_TAG_TAKEN % (owner.name, code, example_label(code, name))
    elif tag_mode == 'own':
        check = name_check(label=label)
        if check['error']:
            errors['tag_label'] = check['error']
        elif check['clash'] and form.get('tag_take_over') != 'on':
            errors['_clash_label'] = True
            errors['tag_label'] = check['said']
    arrive = form.get('arrive') if form.get('arrive') in ('hand', 'whatsapp', 'form', 'source') else 'hand'
    source = None
    if arrive == 'source':
        sid = form.get('source_id')
        source = db.session.get(CrmSource, int(sid)) if sid and str(sid).isdigit() else None
        if source is None:
            errors['source_id'] = 'Choose the source.'
    if errors:
        return None, {}, errors
    if new_values is not None:
        prod_row = CrmProduct(code=code, name=new_values['name'], icon=new_values['icon'],
                              currency=new_values['currency'], kpi_row=new_values['kpi_row'], offered=True,
                              position=_next_product_position())
        db.session.add(prod_row)
        db.session.flush()
        crm_products.invalidate()
    else:
        prod_row = CrmProduct.query.filter_by(code=code).first()
    key = _slug(name, limit=40)
    base, n = key, 2
    while CrmPipeline.query.filter_by(key=key).first():
        key = '%s-%d' % (base[:36], n)
        n += 1
    pipe = CrmPipeline(key=key, name=name, product=code, tag_mode=tag_mode,
                       tag_label=label if tag_mode == 'own' else None, catch_all=False, is_active=True,
                       fallout_reasons=list(crm_defaults.SIMPLE_REASONS))
    db.session.add(pipe)
    if start == 'copy':
        _copy_into(src, pipe, keep_templates=src.product == code)
    else:
        for pos, (skey, sname, means, on_reply) in enumerate(crm_defaults.SIMPLE_PATH):
            pipe.stages.append(CrmStage(key=skey, name=sname, means=means, on_reply=on_reply, position=pos))
    db.session.flush()
    if prod_row is not None and not prod_row.default_pipeline_id:
        prod_row.default_pipeline_id = pipe.id
    notes = {'said': MADE % name}
    if start == 'copy':
        notes['said'] += ' ' + COPIED_OFF
    pname = prod_row.name if prod_row is not None else code
    if arrive in ('hand', 'whatsapp'):
        if prod_row is not None and prod_row.default_pipeline_id not in (None, pipe.id):
            other = db.session.get(CrmPipeline, prod_row.default_pipeline_id)
            notes['said'] += ' ' + ARRIVE_ELSEWHERE % (pname, other.name if other is not None else '')
        else:
            notes['said'] += ' ' + ARRIVE[arrive] % pname
    elif arrive == 'source':
        source.pipeline, source.product = pipe, code
        if source.status == 'unrouted':
            source.status = 'live'
        db.session.flush()
        crm.start_waiting_leads(source, actor)
        notes['said'] += ' ' + ARRIVE['source'] % source.name
    else:
        skey, k = _slug(name + '-form', limit=50), 2
        base_key = skey
        while CrmSource.query.filter_by(key=skey).first():
            skey = '%s-%d' % (base_key[:46], k)
            k += 1
        db.session.add(CrmSource(key=skey, name=('%s form' % name)[:100], kind='form', product=code, pipeline=pipe,
                                 status='live'))
        notes['said'] += ' ' + ARRIVE['form']
        notes['source_key'] = skey
    ActivityEvent.log('crm_pipeline_created', actor=actor, pipeline=key, product=code, start=start, arrive=arrive)
    db.session.commit()
    crm.wa_tag_rule_changed()
    return pipe, notes, {}


# ------------------------------------------------------------------------------------------ "Make it a WhatsApp template"

def make_template(step, actor, stamp_in=None):
    """One follow-up's words -> one WhatsApp template draft. {'status', 'error' | 'success', ...}. Only while
    the portal may write to WhatsApp; nothing goes to Meta or to any customer."""
    if not (crm.wa_writes_on() and wacrm_team.enabled()):
        return {'status': 409, 'error': NOT_CONNECTED}
    pipe = step.stage.pipeline
    if stamp_in is not None and stamp_in != stamp(pipe):
        return {'status': 409, 'error': E_STALE}
    try:
        out = wa_templates.push_step_draft(step)
    except wacrm_team.TeamError as exc:
        db.session.rollback()
        return {'status': 422, 'error': 'The WhatsApp CRM said: %s' % exc}
    if out.get('error'):
        db.session.rollback()
        return {'status': 422, 'error': out['error']}
    ActivityEvent.log('crm_template_draft', actor=actor, step=step.id, name=out['name'], created=out['created'])
    db.session.commit()
    row = wa_templates.infos().get(out['name']) or {}
    status = row.get('status') or 'DRAFT'
    return {'status': 200, 'success': True, 'name': out['name'], 'status_text': wa_templates.status_words(status),
            'css': wa_templates.status_css(status), 'body': out['body'], 'variables': out['variables'],
            'category': out['category'], 'params': out['params'], 'steps': {str(step.id): out['name']},
            'stamp': stamp(pipe), 'message': DRAFT_MADE if out['created'] else DRAFT_SAME}
