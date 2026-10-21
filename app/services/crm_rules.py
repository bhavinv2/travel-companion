"""Automation rules (Sales CRM 2.0, run 5b): Set-up > Automation > Rules.

A rule says WHEN something happens to a lead (its trigger), IF the lead's fields say so (conditions), THEN do these
things (actions). Every choice is on a fixed list in this file: a rule is data, never code or SQL.

When
    lead_created, stage_changed (to one stage or any), field_changed (one watched field), won, lost -- events that
    happen in a save; no_activity (N days with nothing on the lead) and date_reached (N days before / after a date of
    the lead) -- checked by the jobs runner, once per workspace (jobs.run_all -> run_time_triggers).
If
    conditions [{field, op, value}] on the whitelist COND_FIELDS (pipeline, stage, product, source, owner, value,
    country, rating, status, a detail) with OPS (is, is not, more than, less than, contains, is empty).
Then
    create_task (a to-do, never a follow-up step), assign (a person, or in turn through crm_assign's round robin),
    set_field (rating, forecast, value, a detail), move_stage, notify (a bell), webhook (POST JSON, signed). NOTHING a
    rule does messages a customer: a rule's stage move plans the stage's follow-up like any move, but a follow-up that
    would go by itself waits for a click instead.

How it runs
    * The events are only NOTED inside the save (fire(): crm.capture / crm.move_stage; field changes come from the
      history listener crm_audit, the one before_flush that already sees every changed field). After the commit
      (_after_commit) they run in a session of their own, so a rule never runs for a save that was rolled back.
    * A rule runs at most once per lead per triggering event: crm_rule_runs (rule, lead, event key) is unique.
    * A chain (a rule's move starts another rule...) stops at depth MAX_DEPTH.
    * A failure is written on the rule (last_error) and never raised: the save that triggered it stands.
    * A rule's move is a SYSTEM move, like the jobs runner's: "What a stage needs" (crm_stage_rules) does not stop it.
    * Removed leads (the recycle bin) are never acted on; a rule only ever sees leads of its own workspace.
"""
import hashlib
import hmac
import json
import logging
import os
import re
from collections import OrderedDict
from contextvars import ContextVar
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from time import monotonic

from flask import current_app, has_app_context
from sqlalchemy import event, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.attributes import flag_modified

from app import db
from app.models import (CRM_LIKELIHOOD, CrmField, CrmLead, CrmPipeline, CrmRule, CrmRuleRun, CrmSource, CrmStage,
                        CrmTask, User, WorkspaceTeam)

log = logging.getLogger(__name__)

IST = timedelta(hours=5, minutes=30)
MAX_DEPTH = 3                   # a chain of rules starting each other stops here
MAX_CONDITIONS = 5
MAX_ACTIONS = 5
TIME_LIMIT = 500                # leads one time-trigger rule looks at per jobs run
DATE_WINDOW = 3                 # a date reached up to this many days ago still fires (a missed jobs run catches up)
WEBHOOK_TIMEOUT = 5
WEBHOOK_ENV = 'CRM_RULES_WEBHOOK_SECRET'
PREVIEW_LIMIT = 2000

TRIGGERS = OrderedDict([
    ('lead_created', 'A new lead comes in'),
    ('stage_changed', 'A lead moves to a stage'),
    ('field_changed', 'A detail of a lead changes'),
    ('no_activity', 'Nothing has happened on a lead for some days'),
    ('date_reached', 'A date of the lead comes near or passes'),
    ('won', 'A lead is won'),
    ('lost', 'A lead is lost'),
])
TIME_TRIGGERS = ('no_activity', 'date_reached')

COND_FIELDS = OrderedDict([
    ('pipeline', 'Pipeline'), ('stage', 'Stage'), ('product', 'Product'), ('source', 'Where it came from'),
    ('owner', 'Who looks after it'), ('amount', 'Value'), ('country', 'Country'), ('rating', 'Ready to buy?'),
    ('status', 'Open, won or lost'),
])
CHOICE_FIELDS = ('pipeline', 'stage', 'product', 'source', 'owner', 'country', 'rating', 'status')
OPS = OrderedDict([('is', 'is'), ('is_not', 'is not'), ('gt', 'is more than'), ('lt', 'is less than'),
                   ('contains', 'contains'), ('empty', 'is empty')])
OPS_FOR = {'choice': ('is', 'is_not', 'empty'), 'number': ('is', 'is_not', 'gt', 'lt', 'empty'),
           'text': ('is', 'is_not', 'contains', 'gt', 'lt', 'empty')}
STATUS_WORDS = OrderedDict([('open', 'Open'), ('won', 'Won'), ('lost', 'Lost')])

# field_changed: the lead fields the history listener (crm_audit) reports
WATCH_FIELDS = OrderedDict([
    ('owner_id', 'Who looks after it'), ('amount', 'Value'), ('likelihood', 'Ready to buy?'), ('product', 'Product'),
    ('close_date', 'Close date'), ('departure_date', 'Travel date'), ('ends_on', 'Cover end date'),
    ('forecast', 'Counts in the forecast as'), ('details', 'Any of its details'),
])
DATE_FIELDS = OrderedDict([('departure_date', 'Travel date'), ('ends_on', 'Cover end date'),
                           ('close_date', 'Close date')])

ACTIONS = OrderedDict([
    ('create_task', 'Add a task'), ('assign', 'Give it to someone'), ('set_field', 'Change a detail'),
    ('move_stage', 'Move it to a stage'), ('notify', 'Ring a bell for the team'),
    ('webhook', 'Tell another system (a web address)'),
])
SET_FIELDS = OrderedDict([('rating', 'Ready to buy?'), ('forecast', 'Counts in the forecast as'),
                          ('amount', 'Value')])
NOTIFY_TO = OrderedDict([('owner', 'Whoever looks after it'), ('team_lead', 'Their team lead')])

HELD_NOTE = 'Waits for a click: a rule moved this lead'
NO_SECRET = ('The web address was not called: the server has no rules secret yet (CRM_RULES_WEBHOOK_SECRET). '
             'Nothing else changed.')

_PENDING = 'crm_rule_events'
_depth = ContextVar('crm_rule_depth', default=0)
_registered = []
_any = {}                       # process cache: is there any rule switched on? {'until': monotonic, 'value': bool}
ANY_TTL = 30.0


class RuleError(ValueError):
    """A choice the rule editor does not offer, in words for the person."""


# ============================================================================================ the choices

def _staff():
    from app.services import crm_tasks
    return crm_tasks.staff()


def detail_fields():
    """[(key, label)] the pipelines' own lead fields (CrmField), once per key, for 'a detail' conditions and changes."""
    out, seen = [], set()
    for f in CrmField.query.order_by(CrmField.position, CrmField.id).all():
        if f.key not in seen:
            seen.add(f.key)
            out.append((f.key, f.label))
    return out


def choices():
    """Everything the editor's selects offer, from the current workspace."""
    from app.services import crm_products, crm_scope
    from app.services import phone as phone_svc
    from app.models import CrmPerson
    pipes = CrmPipeline.query.order_by(CrmPipeline.id).all()
    stages = []
    for p in pipes:
        for s in sorted(p.stages, key=lambda s: s.position):
            stages.append((s.id, '%s › %s' % (p.name, s.name)))
    countries = sorted({c for (c,) in db.session.query(CrmPerson.country).filter(CrmPerson.country.isnot(None))
                        .distinct().all() if c})
    names = [(c, (phone_svc.BY_ISO.get(c) or {}).get('name') or c) for c in countries]
    ws = crm_scope.current_workspace()
    teams = [(t.id, t.name) for t in (WorkspaceTeam.query.filter_by(workspace_id=ws.id).order_by(WorkspaceTeam.name)
                                      .all() if ws is not None else [])]
    return {
        'pipeline': [(p.id, p.name) for p in pipes],
        'stage': stages,
        'product': list(crm_products.labels().items()),
        'source': [(s.id, s.name) for s in CrmSource.query.order_by(CrmSource.name).all()],
        'owner': [('none', 'Nobody yet')] + [(u.id, u.full_name) for u in _staff()],
        'country': names,
        'rating': list(CRM_LIKELIHOOD.items()),
        'status': list(STATUS_WORDS.items()),
        'details': detail_fields(),
        'teams': teams,
        'staff': [(u.id, u.full_name) for u in _staff()],
    }


def field_kind(field):
    if field in CHOICE_FIELDS:
        return 'choice'
    if field == 'amount':
        return 'number'
    return 'text'


# ============================================================================================ reading the editor

def _int(v):
    v = str(v if v is not None else '').strip()
    return int(v) if re.fullmatch(r'-?\d{1,6}', v) else None


def _get(form, key):
    v = form.get(key) if hasattr(form, 'get') else None
    return ('' if v is None else str(v)).strip()


def _known(field, value, ch):
    """The value of a choice field, checked against the editor's own list (as text), or None."""
    allowed = {str(k) for k, _ in ch.get(field, [])}
    return value if value in allowed else None


def clean(form, ch=None):
    """The rule from the editor's form: (dict for CrmRule, errors [text]). Every value is checked against a list."""
    ch = ch if ch is not None else choices()
    errors = []
    name = ' '.join(_get(form, 'name').split())[:120]
    if not name:
        errors.append('Give the rule a name.')
    trigger = _get(form, 'trigger')
    if trigger not in TRIGGERS:
        errors.append('Choose when the rule starts.')
        trigger = 'lead_created'
    args = {}
    if trigger == 'stage_changed':
        sid = _get(form, 't_stage')
        if sid:
            if _known('stage', sid, ch) is None:
                errors.append('Choose a stage from the list.')
            else:
                args['to_stage_id'] = int(sid)
    elif trigger == 'field_changed':
        f = _get(form, 't_field')
        if f not in WATCH_FIELDS:
            errors.append('Choose which detail to watch.')
        else:
            args['field'] = f
    elif trigger == 'no_activity':
        days = _int(_get(form, 't_days'))
        if days is None or not 1 <= days <= 365:
            errors.append('Say after how many days (1 to 365).')
        else:
            args['days'] = days
    elif trigger == 'date_reached':
        f = _get(form, 't_date')
        days = _int(_get(form, 't_offset') or '0')
        if f not in DATE_FIELDS:
            errors.append('Choose which date.')
        elif days is None or not 0 <= days <= 365:
            errors.append('Say how many days (0 to 365).')
        else:
            args['field'] = f
            args['offset'] = -days if _get(form, 't_when') == 'before' else days
    conds = []
    for i in range(MAX_CONDITIONS):
        field = _get(form, 'cf_%d' % i)
        if not field:
            continue
        if field.startswith('details.'):
            key = field[8:]
            if key not in {k for k, _ in ch['details']}:
                errors.append('Choose a detail from the list.')
                continue
        elif field not in COND_FIELDS:
            errors.append('Choose a field from the list.')
            continue
        kind = field_kind(field)
        op = _get(form, 'co_%d' % i)
        if op not in OPS_FOR[kind]:
            errors.append('“%s” cannot be checked with “%s”.' % (label_of(field, ch), OPS.get(op, op)))
            continue
        value = ''
        if op != 'empty':
            if kind == 'choice':
                value = _known(field, _get(form, 'cv_%d_%s' % (i, field)), ch)
                if value is None:
                    errors.append('Choose a value for “%s”.' % label_of(field, ch))
                    continue
            else:
                value = _get(form, 'cv_%d' % i)[:200]
                if kind == 'number' or op in ('gt', 'lt'):
                    if _decimal(value) is None:
                        errors.append('“%s” needs a number.' % label_of(field, ch))
                        continue
                elif not value:
                    errors.append('Type what “%s” should be.' % label_of(field, ch))
                    continue
        conds.append({'field': field, 'op': op, 'value': value})
    actions = []
    for j in range(MAX_ACTIONS):
        kind = _get(form, 'at_%d' % j)
        if not kind:
            continue
        if kind not in ACTIONS:
            errors.append('Choose what to do from the list.')
            continue
        a, err = _clean_action(kind, j, form, ch)
        if err:
            errors.append(err)
        else:
            actions.append(a)
    if not actions and not errors:
        errors.append('Add at least one thing to do.')
    data = {'name': name, 'trigger': trigger, 'trigger_args': args or None, 'conditions': conds or None,
            'actions': actions}
    return data, errors


def _clean_action(kind, j, form, ch):
    staff_ids = {str(k) for k, _ in ch['staff']}
    g = lambda k: _get(form, 'a_%s_%d' % (k, j))       # noqa: E731
    if kind == 'create_task':
        title = ' '.join(g('title').split())[:160]
        hours = _int(g('hours') or '24')
        owner = g('owner') or 'lead_owner'
        if not title:
            return None, 'Give the task a title.'
        if hours is None or not 0 <= hours <= 2160:
            return None, 'Say in how many hours the task is due (0 to 2160).'
        if owner != 'lead_owner' and owner not in staff_ids:
            return None, 'Choose who the task is for.'
        return {'type': kind, 'title': title, 'due_in_hours': hours,
                'owner': owner if owner == 'lead_owner' else int(owner)}, None
    if kind == 'assign':
        to = g('to')
        if to == 'round_robin':
            via = g('via')
            if via and not re.fullmatch(r'(source|team):\d+', via):
                return None, 'Choose whose turn decides.'
            if via.startswith('team:') and via[5:] not in {str(k) for k, _ in ch['teams']}:
                return None, 'Choose a team from the list.'
            if via.startswith('source:') and via[7:] not in {str(k) for k, _ in ch['source']}:
                return None, 'Choose a lead source from the list.'
            return {'type': kind, 'user_id': 'round_robin', 'via': via or ''}, None
        if to not in staff_ids:
            return None, 'Choose who gets the lead.'
        return {'type': kind, 'user_id': int(to)}, None
    if kind == 'set_field':
        field = g('field')
        value = g('value')
        if field.startswith('details.'):
            if field[8:] not in {k for k, _ in ch['details']}:
                return None, 'Choose a detail from the list.'
            return {'type': kind, 'field': field, 'value': value[:300]}, None
        if field not in SET_FIELDS:
            return None, 'Choose which detail to change.'
        if field == 'rating':
            value = g('rating')
            if value not in CRM_LIKELIHOOD:
                return None, 'Choose Ready to buy, Thinking about it or Not likely.'
        elif field == 'forecast':
            from app.services import crm_money
            value = g('forecast')
            if value not in crm_money.OPEN_FORECASTS:
                return None, 'Choose how it counts in the forecast.'
        else:
            from app.services import crm_money
            try:
                amount = crm_money.money_amount(value)
            except ValueError:
                amount = None
            if amount is None:
                return None, 'Type the value as a number, like 18500.'
            value = crm_money.plain_amount(amount)
        return {'type': kind, 'field': field, 'value': value}, None
    if kind == 'move_stage':
        sid = g('stage')
        if _known('stage', sid, ch) is None:
            return None, 'Choose the stage to move it to.'
        return {'type': kind, 'stage_id': int(sid)}, None
    if kind == 'notify':
        to = g('notify')
        text = ' '.join(g('text').split())[:200]
        if to not in NOTIFY_TO and to not in staff_ids:
            return None, 'Choose who gets the bell.'
        return {'type': kind, 'to': to if to in NOTIFY_TO else int(to), 'text': text}, None
    if kind == 'webhook':
        url = g('url')[:500]
        if not re.fullmatch(r'https://[^\s/$.?#][^\s]*', url):
            return None, 'The web address must start with https://'
        return {'type': kind, 'url': url}, None
    return None, 'Choose what to do from the list.'


def form_values(rule=None, data=None):
    """The editor's fields for a rule (or for what was typed): flat names, as clean() reads them."""
    out = {}
    src = data if data is not None else ({'name': rule.name, 'trigger': rule.trigger, 'trigger_args': rule.trigger_args,
                                          'conditions': rule.conditions, 'actions': rule.actions}
                                         if rule is not None else None)
    if src is None:
        return {'name': '', 'trigger': 'lead_created'}
    if not isinstance(src.get('actions'), list) and hasattr(src, 'getlist'):
        return {k: src.get(k) for k in src.keys()}             # a form posted back with its errors
    out['name'], out['trigger'] = src.get('name') or '', src.get('trigger') or 'lead_created'
    a = src.get('trigger_args') or {}
    if 'to_stage_id' in a:
        out['t_stage'] = str(a['to_stage_id'])
    if 'field' in a:
        out['t_field' if out['trigger'] == 'field_changed' else 't_date'] = a['field']
    if 'days' in a:
        out['t_days'] = str(a['days'])
    if 'offset' in a:
        out['t_offset'] = str(abs(int(a['offset'])))
        out['t_when'] = 'before' if int(a['offset']) < 0 else 'after'
    for i, c in enumerate(src.get('conditions') or []):
        out['cf_%d' % i], out['co_%d' % i] = c.get('field'), c.get('op')
        if field_kind(c.get('field')) == 'choice':
            out['cv_%d_%s' % (i, c.get('field'))] = str(c.get('value') or '')
        else:
            out['cv_%d' % i] = str(c.get('value') or '')
    for j, act in enumerate(src.get('actions') or []):
        t = act.get('type')
        out['at_%d' % j] = t
        if t == 'create_task':
            out.update({'a_title_%d' % j: act.get('title'), 'a_hours_%d' % j: str(act.get('due_in_hours', 24)),
                        'a_owner_%d' % j: str(act.get('owner') or 'lead_owner')})
        elif t == 'assign':
            if act.get('user_id') == 'round_robin':
                out.update({'a_to_%d' % j: 'round_robin', 'a_via_%d' % j: act.get('via') or ''})
            else:
                out['a_to_%d' % j] = str(act.get('user_id'))
        elif t == 'set_field':
            out['a_field_%d' % j] = act.get('field')
            key = {'rating': 'a_rating_%d', 'forecast': 'a_forecast_%d'}.get(act.get('field'), 'a_value_%d') % j
            out[key] = act.get('value')
        elif t == 'move_stage':
            out['a_stage_%d' % j] = str(act.get('stage_id'))
        elif t == 'notify':
            out.update({'a_notify_%d' % j: str(act.get('to')), 'a_text_%d' % j: act.get('text') or ''})
        elif t == 'webhook':
            out['a_url_%d' % j] = act.get('url')
    return out


# ============================================================================================ saving

def save(rule, data, actor=None):
    """Write the cleaned data onto `rule` (a new one when None). No commit. Editing a rule clears its last problem."""
    if rule is None:
        top = db.session.query(db.func.max(CrmRule.position)).scalar() or 0
        rule = CrmRule(position=top + 1, active=False, created_by_id=getattr(actor, 'id', None),
                       created_at=datetime.utcnow(), run_count=0)
        db.session.add(rule)
    rule.name = data['name']
    rule.trigger = data['trigger']
    rule.trigger_args = data['trigger_args']
    rule.conditions = data['conditions']
    rule.actions = data['actions']
    rule.last_error = rule.last_error_at = None
    rule.updated_at = datetime.utcnow()
    db.session.flush()
    forget()
    return rule


def forget():
    _any.clear()


def _rules_changed(*_a):
    forget()


for _ev in ('after_insert', 'after_update', 'after_delete'):
    event.listen(CrmRule, _ev, _rules_changed)


def delete(rule):
    """A rule and the record of where it ran. No commit."""
    CrmRuleRun.query.filter_by(rule_id=rule.id).delete(synchronize_session=False)
    db.session.delete(rule)
    forget()


# ============================================================================================ words

def label_of(field, ch=None):
    if field and field.startswith('details.'):
        key = field[8:]
        ch = ch or {}
        return dict(ch.get('details') or []).get(key) or key.replace('_', ' ').capitalize()
    return COND_FIELDS.get(field) or field


def _value_words(field, value, ch):
    if field in CHOICE_FIELDS:
        return dict((str(k), v) for k, v in ch.get(field, [])).get(str(value), 'a removed choice')
    if field == 'amount':
        from app.services import crm_money
        return crm_money.money(value, crm_money.reporting_currency())
    return '“%s”' % value


def describe(rule, ch=None):
    """'When a lead moves to “Quoted” · if Product is Travel insurance · then add a task “Call them”'."""
    ch = ch or choices()
    a = rule.trigger_args or {}
    when = TRIGGERS.get(rule.trigger, rule.trigger)
    if rule.trigger == 'stage_changed':
        st = dict((str(k), v) for k, v in ch['stage']).get(str(a.get('to_stage_id')))
        when = 'A lead moves to “%s”' % st if st else 'A lead moves to any stage'
    elif rule.trigger == 'field_changed':
        when = '%s of a lead changes' % WATCH_FIELDS.get(a.get('field'), 'A detail')
    elif rule.trigger == 'no_activity':
        when = 'Nothing has happened on a lead for %s days' % a.get('days')
    elif rule.trigger == 'date_reached':
        off = int(a.get('offset') or 0)
        what = DATE_FIELDS.get(a.get('field'), 'a date').lower()
        when = ('It is %d day%s before the %s' % (-off, '' if off == -1 else 's', what) if off < 0 else
                'It is the %s' % what if off == 0 else
                'It is %d day%s after the %s' % (off, '' if off == 1 else 's', what))
    ifs = []
    for c in rule.conditions or []:
        f, op = c.get('field'), c.get('op')
        if op == 'empty':
            ifs.append('%s is empty' % label_of(f, ch))
        else:
            ifs.append('%s %s %s' % (label_of(f, ch), OPS.get(op, op), _value_words(f, c.get('value'), ch)))
    thens = [action_words(act, ch) for act in rule.actions or []]
    out = 'When %s' % when[0].lower() + when[1:]
    if ifs:
        out += ' · if ' + ' and '.join(ifs)
    return out + ' · then ' + ', '.join(thens)


def action_words(act, ch):
    t = act.get('type')
    staff = dict((str(k), v) for k, v in ch.get('staff', []))
    if t == 'create_task':
        who = 'whoever looks after it' if act.get('owner') == 'lead_owner' else staff.get(str(act.get('owner')), 'someone')
        return 'add a task “%s” for %s, due in %s h' % (act.get('title'), who, act.get('due_in_hours'))
    if t == 'assign':
        if act.get('user_id') == 'round_robin':
            via = act.get('via') or ''
            if via.startswith('team:'):
                team = dict((str(k), v) for k, v in ch.get('teams', [])).get(via[5:], 'a team')
                return 'give it to the next person in %s' % team
            if via.startswith('source:'):
                src = dict((str(k), v) for k, v in ch.get('source', [])).get(via[7:], 'a source')
                return 'give it to the next person of “%s”' % src
            return 'give it to the next person in turn'
        return 'give it to %s' % staff.get(str(act.get('user_id')), 'someone who left')
    if t == 'set_field':
        f = act.get('field') or ''
        if f == 'rating':
            return 'set Ready to buy? to %s' % CRM_LIKELIHOOD.get(act.get('value'), act.get('value'))
        if f == 'forecast':
            from app.models import CRM_FORECASTS
            return 'count it in the forecast as %s' % CRM_FORECASTS.get(act.get('value'), act.get('value'))
        if f == 'amount':
            return 'set the value to %s' % _value_words('amount', act.get('value'), ch)
        return 'set %s to “%s”' % (label_of(f, ch), act.get('value'))
    if t == 'move_stage':
        st = dict((str(k), v) for k, v in ch.get('stage', [])).get(str(act.get('stage_id')), 'a removed stage')
        return 'move it to “%s”' % st
    if t == 'notify':
        to = act.get('to')
        who = NOTIFY_TO.get(to) or staff.get(str(to), 'someone who left')
        return 'ring a bell for %s' % who.lower() if to in NOTIFY_TO else 'ring a bell for %s' % who
    if t == 'webhook':
        return 'tell %s' % (re.sub(r'^https://', '', act.get('url') or '').split('/')[0] or 'a web address')
    return t or ''


# ============================================================================================ conditions

def _decimal(v):
    try:
        d = Decimal(str(v).replace(',', '').strip())
        return d if d.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _lead_value(lead, field, rates=None):
    if field == 'pipeline':
        return lead.pipeline_id
    if field == 'stage':
        return lead.stage_id
    if field == 'product':
        return lead.product
    if field == 'source':
        return lead.source_id
    if field == 'owner':
        return lead.owner_id if lead.owner_id else 'none'
    if field == 'amount':
        if lead.amount is None:
            return None
        from app.services import crm_money
        return crm_money.to_base(lead.amount, lead.currency, rates)
    if field == 'country':
        return lead.person.country if lead.person is not None else None
    if field == 'rating':
        return lead.likelihood
    if field == 'status':
        return lead.status
    if field and field.startswith('details.'):
        return (lead.details or {}).get(field[8:])
    return None


def _empty(v):
    return v is None or v == '' or v == [] or v == {}


def test_condition(cond, lead, rates=None):
    field, op, want = cond.get('field'), cond.get('op'), cond.get('value')
    have = _lead_value(lead, field, rates)
    if op == 'empty':
        return _empty(have) or (field == 'owner' and have == 'none')
    if op in ('gt', 'lt'):
        a, b = _decimal(have), _decimal(want)
        if a is None or b is None:
            return False
        return a > b if op == 'gt' else a < b
    if field == 'amount' and op in ('is', 'is_not'):
        a, b = _decimal(have), _decimal(want)
        same = a is not None and b is not None and a == b
        return same if op == 'is' else not same
    text = '' if _empty(have) else (', '.join(map(str, have)) if isinstance(have, list) else str(have))
    if op == 'contains':
        return str(want or '').lower() in text.lower() if want else False
    same = text.strip().lower() == str(want if want is not None else '').strip().lower()
    return same if op == 'is' else not same


def matches(rule, lead, rates=None):
    return all(test_condition(c, lead, rates) for c in rule.conditions or [])


# ============================================================================================ the events

def fire(trigger, lead, key, **ctx):
    """Inside a save: note that `trigger` happened to `lead` (event `key`), for after the commit. No query."""
    if lead is None or getattr(lead, 'id', None) is None:
        return
    depth = _depth.get()
    if depth >= MAX_DEPTH:
        return                              # a chain this long stops here
    from sqlalchemy.orm import object_session
    sess = object_session(lead) or db.session()
    sess.info.setdefault(_PENDING, []).append((trigger, lead.id, str(key)[:120], ctx, depth))


def field_changes(sess, rows):
    """From the history listener (crm_audit._before_flush): the lead fields that changed in this flush."""
    if _depth.get() >= MAX_DEPTH:
        return
    pend = sess.info.setdefault(_PENDING, [])
    for r in rows:
        if r.get('record_type') != 'lead' or r.get('field') not in WATCH_FIELDS:
            continue
        digest = hashlib.sha1(('%s|%s' % (r.get('old'), r.get('new'))).encode('utf-8')).hexdigest()[:10]
        at = r.get('at') or datetime.utcnow()
        key = 'field:%s:%s:%s' % (r['field'], at.isoformat(timespec='microseconds'), digest)
        pend.append(('field_changed', r['record_id'], key, {'field': r['field']}, _depth.get()))


def _after_rollback(session, previous_transaction):
    if previous_transaction.parent is None:
        session.info.pop(_PENDING, None)
        from app.services import crm_scoring
        session.info.pop(crm_scoring.DUE, None)


def any_active():
    """Is any rule switched on (in any workspace)? Cached for ANY_TTL seconds in this process."""
    now = monotonic()
    if _any.get('until', 0) > now:
        return _any['value']
    got = db.session.query(CrmRule.id).filter(CrmRule.active.is_(True)) \
        .execution_options(all_workspaces=True).first() is not None
    _any.update(until=now + ANY_TTL, value=got)
    return got


def _after_commit(session):
    """After a save: its rule events (and the leads whose score may have changed) are dealt with in a session of
    their own -- the save is done, nothing here can undo it."""
    if session.get_nested_transaction() is not None:
        return
    events = session.info.pop(_PENDING, None)
    from app.services import crm_scoring
    due = session.info.pop(crm_scoring.DUE, None)
    if not events and not due:
        return
    if _any.get('until', 0) > monotonic() and not _any['value']:
        events = None                       # known: no rule is on anywhere
        if not due:
            return
    if not has_app_context():
        return
    app = current_app._get_current_object()
    with app.app_context():                 # its own session
        # what happens here is the system's doing, not the signed-in person's: History says "The system", and no
        # screen filter of theirs (workspace, who sees which leads) applies -- each rule sets its own workspace
        from flask import g
        g.crm_system = True
        try:
            g._login_user = app.login_manager.anonymous_user()
        except Exception:      # noqa: BLE001 -- no sign-in set up (a bare app)
            pass
        try:
            if due:
                crm_scoring.recalc_due(due)
            if events:
                process(events)
        except Exception:      # noqa: BLE001 -- a rule must never break the save that started it
            db.session.rollback()
            log.warning('CRM rules after a save failed', exc_info=True)
        finally:
            db.session.remove()


def register():
    if not _registered:
        event.listen(db.session, 'after_commit', _after_commit)
        event.listen(db.session, 'after_soft_rollback', _after_rollback)
        _registered.append(1)


def _trigger_ok(rule, trigger, ctx):
    a = rule.trigger_args or {}
    if rule.trigger != trigger:
        return False
    if trigger == 'stage_changed' and a.get('to_stage_id'):
        return int(a['to_stage_id']) == ctx.get('to_stage_id')
    if trigger == 'field_changed':
        return a.get('field') == ctx.get('field')
    return True


def _rules_for(wid, trigger):
    from app.services import crm_scope
    q = (CrmRule.query.execution_options(all_workspaces=True)
         .filter(CrmRule.active.is_(True), CrmRule.trigger == trigger))
    if crm_scope.several():
        q = q.filter(crm_scope.match(CrmRule.workspace_id, wid))
    return q.order_by(CrmRule.position, CrmRule.id).all()


def process(events):
    """Run the rules for events noted in a save (in the session of _after_commit)."""
    if not any_active():
        return 0
    from app.services import crm_scope
    ran = 0
    for trigger, lead_id, key, ctx, depth in events:
        lead = CrmLead.query.execution_options(all_workspaces=True).filter(CrmLead.id == lead_id).first()
        if lead is None:
            continue                        # gone, or in the recycle bin
        wid = crm_scope.of(lead)
        with crm_scope.use(wid if crm_scope.several() else None):
            for rule in _rules_for(wid, trigger):
                if _trigger_ok(rule, trigger, ctx or {}):
                    if run_one(rule, lead, key, depth) == 'ran':
                        ran += 1
                lead = db.session.get(CrmLead, lead_id)
                if lead is None or lead.deleted_at is not None:
                    break
    return ran


# ============================================================================================ running one

def run_one(rule, lead, key, depth=0, now=None):
    """Run `rule` for `lead` on event `key`: 'ran', 'no' (conditions), 'done' (already ran), 'skip', 'failed'."""
    from app.services import crm_scope
    if lead is None or lead.deleted_at is not None:
        return 'skip'
    rule_ws = rule.workspace_id if rule.workspace_id is not None else crm_scope.default_id()
    if crm_scope.several() and crm_scope.of(lead) != rule_ws:
        return 'skip'                       # a rule of one workspace never touches another's leads
    if not matches(rule, lead):
        return 'no'
    if CrmRuleRun.query.filter_by(rule_id=rule.id, lead_id=lead.id, event_key=key).first() is not None:
        return 'done'
    now = now or datetime.utcnow()
    rid, lid = rule.id, lead.id
    hooks = []
    token = _depth.set(depth + 1)
    try:
        db.session.add(CrmRuleRun(rule_id=rid, lead_id=lid, event_key=key[:120], ok=True, at=now))
        db.session.flush()
        for act in list(rule.actions or []):
            if act.get('type') == 'webhook':
                hooks.append(act)
            else:
                _do(act, rule, lead, now)
        rule.last_run_at = now
        rule.run_count = (rule.run_count or 0) + 1
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return 'done'
    except Exception as exc:      # noqa: BLE001 -- written on the rule, never raised
        db.session.rollback()
        _failed(rid, lid, key, exc, now)
        return 'failed'
    finally:
        _depth.reset(token)
    for act in hooks:
        try:
            _webhook(act, rid, lid, now)
        except Exception as exc:      # noqa: BLE001
            db.session.rollback()
            _note_error(rid, exc, now)
    return 'ran'


def _say(exc):
    text = str(exc) or exc.__class__.__name__
    return text[:290]


def _failed(rid, lid, key, exc, now):
    log.warning('CRM rule %s failed on lead %s', rid, lid, exc_info=exc)
    try:
        rule = db.session.get(CrmRule, rid)
        if rule is not None:
            rule.last_error = 'Lead %d: %s' % (lid, _say(exc))
            rule.last_error_at = now
            rule.last_run_at = now
        db.session.add(CrmRuleRun(rule_id=rid, lead_id=lid, event_key=key[:120], ok=False, at=now))
        db.session.commit()
    except Exception:      # noqa: BLE001
        db.session.rollback()


def _note_error(rid, exc, now):
    try:
        rule = db.session.get(CrmRule, rid)
        if rule is not None:
            rule.last_error = exc if isinstance(exc, str) else _say(exc)
            rule.last_error_at = now
            db.session.commit()
    except Exception:      # noqa: BLE001
        db.session.rollback()


class ActionError(RuntimeError):
    pass


def _do(act, rule, lead, now):
    t = act.get('type')
    if t == 'create_task':
        return _create_task(act, rule, lead, now)
    if t == 'assign':
        return _assign(act, rule, lead, now)
    if t == 'set_field':
        return _set_field(act, rule, lead)
    if t == 'move_stage':
        return _move(act, rule, lead, now)
    if t == 'notify':
        return _notify(act, rule, lead)
    raise ActionError('An action this version does not know: %s' % t)


def _active_staff_ids():
    return {u.id for u in _staff() if u.is_active}


def _create_task(act, rule, lead, now):
    owner = lead.owner_id if act.get('owner') == 'lead_owner' else act.get('owner')
    if owner is not None and owner not in _active_staff_ids():
        owner = lead.owner_id               # the person picked has left: whoever looks after the lead
    task = CrmTask(lead_id=lead.id, person_id=lead.person_id, kind='todo', channel='todo',
                   title=(act.get('title') or rule.name)[:160], status='open', auto=False, code=None,
                   due_at=now + timedelta(hours=int(act.get('due_in_hours') or 0)), owner_id=owner,
                   notes='Added by the rule “%s”.' % rule.name, priority='normal', created_by_id=None)
    db.session.add(task)
    db.session.flush()
    from app.services import crm_tasks
    crm_tasks._bell(task, None)


def _assign(act, rule, lead, now):
    from app.services import crm, crm_assign
    uid = act.get('user_id')
    if uid == 'round_robin':
        via = act.get('via') or ''
        if via.startswith('team:'):
            team = db.session.get(WorkspaceTeam, int(via[5:]))
            if team is None:
                raise ActionError('The team of this rule was deleted.')
            owner = crm_assign.team_turn(team, act.get('last'), now)
            if owner is not None:
                acts = [dict(x) for x in rule.actions]
                for x in acts:
                    if x is not None and x.get('type') == 'assign' and x.get('via') == via:
                        x['last'] = owner.id
                rule.actions = acts
                flag_modified(rule, 'actions')
        else:
            src = db.session.get(CrmSource, int(via[7:])) if via.startswith('source:') else lead.source
            owner = crm_assign.source_turn(src, now)
        if owner is None:
            raise ActionError('Nobody could take the lead in turn.')
        uid = owner.id
    elif uid not in _active_staff_ids():
        raise ActionError('The person this rule gives leads to cannot take leads any more.')
    crm.set_owner(lead, uid, by=None, ring=True)


def _set_field(act, rule, lead):
    from app.services import crm_money
    f, v = act.get('field') or '', act.get('value')
    if f == 'rating':
        lead.likelihood = v if v in CRM_LIKELIHOOD else None
    elif f == 'forecast':
        if lead.status == 'open':
            crm_money.change_value(lead, forecast=v)
    elif f == 'amount':
        crm_money.change_value(lead, amount=v)
    elif f.startswith('details.'):
        key = f[8:]
        merged = dict(lead.details or {})
        if v in (None, ''):
            merged.pop(key, None)
        else:
            merged[key] = str(v)[:300]
        lead.details = merged
    else:
        raise ActionError('A detail this version cannot change: %s' % f)
    db.session.flush()


def _move(act, rule, lead, now):
    """A system move, like the jobs runner's: "What a stage needs" does not stop it. A follow-up the new stage plans
    that would go by itself waits for a click instead (a rule never messages a customer)."""
    from app.services import crm
    stage = db.session.get(CrmStage, int(act.get('stage_id') or 0))
    if stage is None:
        raise ActionError('The stage of this rule was deleted.')
    if stage.pipeline_id != lead.pipeline_id or stage.id == lead.stage_id or lead.status != 'open':
        return                              # another pipeline's stage, already there, or closed: nothing to do
    reason = 'Moved by the rule “%s”' % rule.name
    before = {t.id for t in lead.tasks}
    crm.move_stage(lead, stage, user=None, reason=reason[:160],
                   fallout_reason=reason[:80] if stage.kind == 'lost' else None)
    for t in lead.tasks:
        if t.id not in before and t.status == 'open' and t.auto:
            t.auto = False
            t.note = HELD_NOTE
    db.session.flush()


def _team_leads(lead):
    from app.services import crm_quotes
    if not lead.owner_id:
        return []
    mates = crm_quotes.team_mate_ids(lead.owner_id) - {lead.owner_id}
    users = User.query.filter(User.id.in_(sorted(mates) or [0]), User.is_active.is_(True)).all()
    return [u.id for u in users if crm_quotes._leads_team(u)]


def _notify(act, rule, lead):
    from app.services import crm, crm_products, notify
    to = act.get('to')
    if to == 'owner':
        ids = [lead.owner_id] if lead.owner_id else []
    elif to == 'team_lead':
        ids = _team_leads(lead)
        if not ids:
            ids = [u.id for u in User.query.filter(User.is_admin.is_(True), User.is_active.is_(True)).all()]
    else:
        ids = [int(to)] if str(to).isdigit() else []
    title = (act.get('text') or rule.name)[:200]
    who = lead.person.display_name if lead.person is not None else 'A lead'
    body = '%s · %s · the rule “%s”' % (who, crm_products.labels().get(lead.product, lead.product), rule.name)
    for uid in ids:
        notify.push(uid, 'crm_rule', title=title, body=body[:500], link=crm._lead_link(lead))


def webhook_fields(lead):
    """What a web address is told about a lead: its sales fields, never how to reach the person."""
    return {'product': lead.product, 'pipeline': lead.pipeline.name if lead.pipeline else None,
            'stage': lead.stage.name if lead.stage else None, 'status': lead.status,
            'owner': lead.owner.full_name if lead.owner else None,
            'source': lead.source.name if lead.source else None,
            'amount': str(lead.amount) if lead.amount is not None else None, 'currency': lead.currency,
            'country': lead.person.country if lead.person is not None else None,
            'created_at': lead.created_at.isoformat(timespec='seconds') if lead.created_at else None}


def _post(url, body, headers):
    """The one place a rule calls out (tests replace it; nothing is ever called in a test)."""
    import requests
    resp = requests.post(url, data=body, headers=headers, timeout=WEBHOOK_TIMEOUT)
    if resp.status_code >= 400:
        raise ActionError('The web address answered %d.' % resp.status_code)
    return resp.status_code


def _webhook(act, rid, lid, now):
    secret = (os.environ.get(WEBHOOK_ENV) or '').strip()
    if not secret:
        _note_error(rid, NO_SECRET, now)
        return 'skipped'
    rule = db.session.get(CrmRule, rid)
    lead = CrmLead.query.filter(CrmLead.id == lid).first()
    if rule is None or lead is None:
        return 'skipped'
    payload = {'event': rule.trigger, 'rule_id': rid, 'lead_id': lid, 'fields': webhook_fields(lead)}
    body = json.dumps(payload, sort_keys=True).encode('utf-8')
    sig = hmac.new(secret.encode('utf-8'), body, hashlib.sha256).hexdigest()
    _post(act.get('url'), body, {'Content-Type': 'application/json', 'X-Signature': sig})
    return 'sent'


# ============================================================================================ time triggers

def run_time_triggers(now=None, limit=TIME_LIMIT):
    """The jobs runner, once per workspace: rules started by days without activity or by a date of the lead."""
    if not any_active():
        return {'crm_rules_ran': 0}
    from app.services import crm_scope
    now = now or datetime.utcnow()
    today = (now + IST).date()
    wid = crm_scope.current_id()
    ran = 0
    rules = (CrmRule.query.filter(CrmRule.active.is_(True), CrmRule.trigger.in_(TIME_TRIGGERS))
             .order_by(CrmRule.position, CrmRule.id).all())
    for rule in rules:
        a = rule.trigger_args or {}
        q = CrmLead.query.filter(CrmLead.status == 'open')
        if rule.trigger == 'no_activity':
            days = int(a.get('days') or 0)
            if days < 1:
                continue
            q = q.filter(CrmLead.last_activity_at.isnot(None), CrmLead.last_activity_at <= now - timedelta(days=days))
            leads = q.order_by(CrmLead.last_activity_at).limit(limit).all()
            pairs = [(l, 'idle:%s' % l.last_activity_at.isoformat(timespec='seconds')) for l in leads]
        else:
            field = a.get('field')
            if field not in DATE_FIELDS:
                continue
            off = int(a.get('offset') or 0)
            col = getattr(CrmLead, field)
            # the day the rule fires is the date + offset: so the date is today - offset (a few days of catch-up)
            last = today - timedelta(days=off)
            first = last - timedelta(days=DATE_WINDOW)
            leads = q.filter(col.isnot(None), col <= last, col >= first).order_by(col).limit(limit).all()
            pairs = [(l, 'date:%s:%s:%d' % (field, getattr(l, field).isoformat(), off)) for l in leads]
        rid = rule.id
        for lead, key in pairs:
            rule = db.session.get(CrmRule, rid)
            if rule is None or not rule.active:
                break
            lead = db.session.get(CrmLead, lead.id)
            if lead is None:
                continue
            if wid is not None and not crm_scope.visible(lead, wid):
                continue
            if run_one(rule, lead, key, 0, now) == 'ran':
                ran += 1
    return {'crm_rules_ran': ran}


# ============================================================================================ test-run

def preview(rule_like, user, now=None, limit=5):
    """"Which open leads would this match now?" -- {'count', 'examples': [lead], 'capped', 'what'}. Nothing is run."""
    from app.services import crm_access
    now = now or datetime.utcnow()
    today = (now + IST).date()
    a = rule_like.trigger_args or {}
    trig = rule_like.trigger
    what = 'open leads'
    q = CrmLead.query.filter(CrmLead.deleted_at.is_(None))
    if trig in ('won', 'lost'):
        q = q.filter(CrmLead.status == trig, CrmLead.closed_at >= now - timedelta(days=30))
        what = 'leads %s in the last 30 days' % trig
    else:
        q = q.filter(CrmLead.status == 'open')
    if trig == 'stage_changed' and a.get('to_stage_id'):
        q = q.filter(CrmLead.stage_id == int(a['to_stage_id']))
        what = 'open leads in that stage now'
    elif trig == 'no_activity' and a.get('days'):
        q = q.filter(CrmLead.last_activity_at <= now - timedelta(days=int(a['days'])))
    elif trig == 'date_reached' and a.get('field') in DATE_FIELDS:
        col = getattr(CrmLead, a['field'])
        last = today - timedelta(days=int(a.get('offset') or 0))
        q = q.filter(col.isnot(None), col <= last, col >= last - timedelta(days=DATE_WINDOW))
    crit = crm_access.lead_filter(user)
    if crit is not None:
        q = q.filter(crit)
    leads = q.order_by(CrmLead.last_activity_at.desc(), CrmLead.id.desc()).limit(PREVIEW_LIMIT).all()
    from app.services import crm_money
    rates = crm_money.rates()
    hits = [l for l in leads if all(test_condition(c, l, rates) for c in rule_like.conditions or [])]
    return {'count': len(hits), 'examples': hits[:limit], 'capped': len(leads) >= PREVIEW_LIMIT, 'what': what}


class Draft:
    """A rule that is not saved: what the editor shows, for preview() and describe()."""
    def __init__(self, data):
        self.name = data.get('name')
        self.trigger = data.get('trigger')
        self.trigger_args = data.get('trigger_args')
        self.conditions = data.get('conditions')
        self.actions = data.get('actions') or []


# ============================================================================================ conflicts

def stage_conflicts(rules=None):
    """[{'rule_id', 'name', 'why'}]: switched-on rules whose stage move fights a stage's own automatic move (one
    moves a lead on and the other moves it back, or both move it out of the same stage)."""
    rules = rules if rules is not None else CrmRule.query.filter(CrmRule.active.is_(True)).all()
    stages = {s.id: s for s in CrmStage.query.all()}
    out = []
    for r in rules:
        targets = [stages.get(int(a.get('stage_id') or 0)) for a in r.actions or [] if a.get('type') == 'move_stage']
        targets = [t for t in targets if t is not None]
        if not targets:
            continue
        froms = []
        a = r.trigger_args or {}
        if r.trigger == 'stage_changed' and a.get('to_stage_id'):
            froms.append(stages.get(int(a['to_stage_id'])))
        for c in r.conditions or []:
            if c.get('field') == 'stage' and c.get('op') == 'is' and str(c.get('value') or '').isdigit():
                froms.append(stages.get(int(c['value'])))
        why = None
        for s in [f for f in froms if f is not None]:
            for t in targets:
                if t.auto_to_id and t.auto_to_id == s.id:
                    why = ('moves leads to “%s”, and “%s” moves them back to “%s” by itself'
                           % (t.name, t.name, s.name))
                elif s.auto_to_id and s.auto_to_id != t.id and t.id != s.id:
                    other = stages.get(s.auto_to_id)
                    why = ('moves leads out of “%s” to “%s”, but “%s” also moves them on by itself (to “%s”)'
                           % (s.name, t.name, s.name, other.name if other else 'another stage'))
                if why:
                    break
            if why:
                break
        if why:
            out.append({'rule_id': r.id, 'name': r.name, 'why': why})
    return out


CONFLICT_BELL = 'A rule may fight a stage’s own move'
CONFLICT_BODY = 'The rule “%s” %s. Change the rule or the stage in Pipelines.'


def ring_conflicts(now=None):
    """check_automation_conflicts (the jobs runner): ring the admins once for each NEW clash between a rule's stage
    move and a stage's own automatic move, in the workspace being run. How many rules clash now."""
    from app.services import crm, notify
    found = {c['rule_id']: c for c in stage_conflicts()}
    rules = CrmRule.query.all()
    admins = None
    changed = False
    for r in rules:
        c = found.get(r.id)
        why = c['why'][:300] if c else None
        if why == r.conflict:
            continue
        changed = True
        r.conflict = why
        if why:
            if admins is None:
                admins = User.query.filter(User.is_admin.is_(True), User.is_active.is_(True)).all()
            for u in admins:
                notify.push(u.id, 'crm_rules', title=CONFLICT_BELL, body=(CONFLICT_BODY % (r.name, why))[:500],
                            link='/admin/crm/rules')
    if changed:
        db.session.commit()
    return len(found)
