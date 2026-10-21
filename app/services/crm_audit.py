"""History of every change (Sales CRM 2.0, run 3b).

One `before_flush` listener (registered once) writes a `crm_audit` row for each changed field in a
whitelist on CrmLead and CrmPerson: who (the signed-in person of the request, else NULL = the
system), when, and the raw old and new value (ids, ISO dates). Words and money are made when the
history is SHOWN (`history_for`, `describe`), so a renamed stage or a changed currency reads right.
The write is Core on the flush's own connection: no query of the ORM can start a flush inside it.
"""
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from flask import g, has_request_context, session
from sqlalchemy import event, inspect, select

from app import db
from app.models import CrmAudit, CrmLead, CrmPerson, CrmPipeline, CrmStage, User

LEAD_FIELDS = ('stage_id', 'status', 'owner_id', 'amount', 'currency', 'close_date', 'forecast', 'likelihood',
               'temperature', 'details', 'departure_date', 'ends_on', 'fallout_reason', 'product',
               'pipeline_id', 'deleted_at')
PERSON_FIELDS = ('name', 'phone', 'email', 'country', 'consent_whatsapp', 'consent_marketing', 'household_id',
                 'household_role')
WATCHED = {CrmLead: ('lead', LEAD_FIELDS), CrmPerson: ('person', PERSON_FIELDS)}

LABELS = {
    'stage_id': 'the stage', 'status': 'the status', 'owner_id': 'who looks after it', 'amount': 'the value',
    'currency': 'the currency', 'close_date': 'the close date', 'forecast': 'the forecast',
    'likelihood': 'how likely it is', 'temperature': 'the temperature', 'details': 'the details',
    'departure_date': 'the travel date', 'ends_on': 'the cover end date', 'fallout_reason': 'why it was lost',
    'product': 'the product', 'pipeline_id': 'the pipeline', 'deleted_at': 'it',
    'name': 'the name', 'phone': 'the phone number', 'email': 'the e-mail', 'country': 'the country',
    'consent_whatsapp': 'WhatsApp permission', 'consent_marketing': 'permission to send offers',
    'household_id': 'the family', 'household_role': 'their part in the family',
}
_registered = []


def _text(value):
    """The raw value as stored text (None stays None). Money compares as a number, not a string."""
    if value is None:
        return None
    if isinstance(value, bool):
        return '1' if value else '0'
    if isinstance(value, Decimal):
        return format(value.normalize(), 'f')
    if isinstance(value, datetime):
        return value.isoformat(sep=' ', timespec='seconds')
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, default=str)
    return str(value)


def _same(a, b):
    if a == b:
        return True
    try:
        if isinstance(a, (int, float, Decimal)) and isinstance(b, (int, float, Decimal)) \
                and not isinstance(a, bool) and not isinstance(b, bool):
            return Decimal(str(a)) == Decimal(str(b))
    except (InvalidOperation, ValueError):
        pass
    return False


def current_user_id():
    """The signed-in person of this request, without a query; None outside a request."""
    if not has_request_context():
        return None
    if g.get('crm_system'):
        return None                 # an automation rule or a score, after somebody's save: the system's doing
    u = g.get('_login_user')
    if u is not None and getattr(u, 'is_authenticated', False):
        return u.id
    raw = session.get('_user_id')
    try:
        return int(raw) if raw else None
    except (TypeError, ValueError):
        return None


# a column that people change through its relationship (lead.stage = ...): the column only follows at flush
RELATIONSHIP = {'stage_id': 'stage', 'pipeline_id': 'pipeline', 'owner_id': 'owner', 'household_id': 'household'}


def _before_flush(sess, flush_context, instances):
    rows = []
    now = datetime.utcnow()             # one time for one save: history_for reads a save's rows together
    for obj in list(sess.dirty):
        spec = WATCHED.get(type(obj))
        if spec is None or obj.id is None:
            continue
        kind, fields = spec
        state = inspect(obj)
        for f in fields:
            new, old, known = _change(sess, obj, state, f)
            if new is _NONE:
                continue
            if not known:
                # the old value was not loaded: read it from the database, which this flush has not changed yet
                col = obj.__table__.c[f]
                try:
                    row = sess.connection().execute(select(col).where(obj.__table__.c.id == obj.id)).first()
                except Exception:          # noqa: BLE001 -- history must never stop a save
                    row = None
                if row is None:
                    continue
                old = row[0]
            if _same(old, new) or (old in (None, '') and new in (None, '')):
                continue
            rows.append({'at': now, 'user_id': None, 'record_type': kind, 'record_id': obj.id,
                         'field': f, 'old': _text(old), 'new': _text(new), 'workspace_id': _workspace_of(sess, obj)})
    if rows:
        uid = current_user_id()
        for r in rows:
            r['user_id'] = uid
        sess.connection().execute(CrmAudit.__table__.insert(), rows)
        # the same changes start automation rules ("a detail changes") and re-score the lead, after the commit
        # (services/crm_rules, crm_scoring): this is the one listener that sees every changed field
        try:
            from app.services import crm_rules, crm_scoring
            crm_rules.field_changes(sess, rows)
            crm_scoring.field_changes(sess, rows)
        except Exception:          # noqa: BLE001 -- history and rules must never stop a save
            pass


_NONE = object()


def _workspace_of(sess, obj):
    """The workspace of the lead / person a history row is about (its own column, read without a query when loaded)."""
    st = inspect(obj)
    if 'workspace_id' in st.dict:
        return st.dict['workspace_id']
    try:
        row = sess.connection().execute(select(obj.__table__.c.workspace_id)
                                        .where(obj.__table__.c.id == obj.id)).first()
    except Exception:          # noqa: BLE001 -- history must never stop a save
        return None
    return row[0] if row is not None else None


def _change(sess, obj, state, f):
    """(new, old, old_known) for a watched field that is being changed, else (_NONE, None, False)."""
    rel = RELATIONSHIP.get(f)
    if rel is not None:
        hist = state.attrs[rel].history
        if hist.added:
            target = hist.added[0]
            new = target.id if target is not None else None
            if new is None and target is not None:
                return _NONE, None, False              # a stage not saved yet: nothing to name
            deleted = [d for d in hist.deleted if d is not None]
            return new, (deleted[0].id if deleted else None), bool(deleted)
        if hist.deleted and not hist.added and rel in state.dict and state.dict.get(rel) is None:
            return None, hist.deleted[0].id, True      # taken away: lead.owner = None
    hist = state.attrs[f].history
    if not hist.added:
        return _NONE, None, False
    if hist.deleted:
        return hist.added[0], hist.deleted[0], True
    return hist.added[0], None, False


def register():
    if not _registered:
        event.listen(db.session, 'before_flush', _before_flush)
        _registered.append(1)


# ---------------------------------------------------------------------------------- showing it

def forget_record(record_type, record_ids):
    """Erasing a person: their history goes with them (privacy)."""
    ids = [i for i in record_ids if i]
    if not ids:
        return 0
    return CrmAudit.query.filter(CrmAudit.record_type == record_type, CrmAudit.record_id.in_(ids)) \
        .delete(synchronize_session=False)


def _day(dt):
    from datetime import timedelta
    local = dt + timedelta(hours=5, minutes=30)
    return '%d %s %s' % (local.day, local.strftime('%b'), local.strftime('%H:%M'))


def _lookup():
    """Names for ids: stages, pipelines, users -- one query each, for the rows being shown."""
    from app.models import CrmHousehold
    return {'stage_id': {s.id: s.name for s in CrmStage.query.all()},
            'pipeline_id': {p.id: p.name for p in CrmPipeline.query.all()},
            'household_id': {h.id: h.name for h in CrmHousehold.query.all()}}


def _value(field, raw, names, users, currency):
    from app.models import CRM_LIKELIHOOD, CRM_FORECASTS
    if raw in (None, ''):
        return 'empty'
    if field in ('stage_id', 'pipeline_id', 'household_id'):
        try:
            return names[field].get(int(raw), 'a removed one')
        except ValueError:
            return raw
    if field == 'owner_id':
        try:
            return users.get(int(raw), 'someone who left')
        except ValueError:
            return raw
    if field == 'amount':
        from app.services import crm_money
        return crm_money.money(raw, currency)
    if field in ('close_date', 'departure_date', 'ends_on'):
        try:
            d = date.fromisoformat(raw)
            return '%d %s %d' % (d.day, d.strftime('%b'), d.year)
        except ValueError:
            return raw
    if field == 'likelihood':
        return CRM_LIKELIHOOD.get(raw, raw)
    if field == 'forecast':
        return CRM_FORECASTS.get(raw, raw)
    if field in ('consent_whatsapp', 'consent_marketing'):
        return 'given' if raw == '1' else 'not given'
    if field == 'status':
        return {'open': 'open', 'won': 'won', 'lost': 'lost'}.get(raw, raw)
    if field == 'details':
        return 'updated'
    return raw


def describe(row, names, users, currency=None, sides=None):
    """'changed the value from ₹12,000 to ₹18,500' (the actor and time are added by the caller). `sides`: the
    currencies of the old and the new value of a value row (_amount_sides), else `currency` for both."""
    f = row.field
    if f == 'deleted_at':
        return 'removed this lead' if row.new else 'put this lead back'
    if f == 'details':
        return 'changed the details'
    if f == 'quote':
        return row.new or 'changed a quote'
    if f == 'merged':
        return 'merged another contact into this one (%s)' % (row.new or 'no details')
    if f == 'household_id':
        def fam(raw):
            try:
                return names['household_id'].get(int(raw)) or 'family'
            except (TypeError, ValueError):
                return 'family'
        if row.new in (None, ''):
            return 'took them out of the %s' % fam(row.old)
        if row.old in (None, ''):
            return 'put them in the %s' % fam(row.new)
        return 'moved them from the %s to the %s' % (fam(row.old), fam(row.new))
    if f == 'household_role':
        from app.models import HOUSEHOLD_ROLES
        roles = dict(HOUSEHOLD_ROLES)
        if row.new in (None, ''):
            return 'cleared their part in the family'
        return 'set their part in the family to %s' % roles.get(row.new, row.new).lower()
    label = LABELS.get(f, f)
    old_cur, new_cur = sides or (currency, currency)
    old = _value(f, row.old, names, users, old_cur)
    new = _value(f, row.new, names, users, new_cur)
    if row.old in (None, ''):
        return 'set %s to %s' % (label, new)
    if row.new in (None, ''):
        return 'cleared %s (was %s)' % (label, old)
    return 'changed %s from %s to %s' % (label, old, new)


def history_for(record_type, record_id, currency=None, limit=200):
    """[{'who', 'what', 'at' (text), 'when' (datetime)}] newest first, in words."""
    rows = (CrmAudit.query.filter_by(record_type=record_type, record_id=record_id)
            .order_by(CrmAudit.at.desc(), CrmAudit.id.desc()).limit(limit).all())
    if not rows:
        return []
    names = _lookup()
    ids = {int(r.user_id) for r in rows if r.user_id} | {int(r.new) for r in rows if r.field == 'owner_id' and r.new}
    ids |= {int(r.old) for r in rows if r.field == 'owner_id' and r.old}
    users = {u.id: u.first_name or u.username for u in User.query.filter(User.id.in_(list(ids) or [0]))}
    sides = _amount_sides(rows, currency) if record_type == 'lead' else {}
    out = []
    for r in rows:
        out.append({'who': users.get(r.user_id) if r.user_id else 'The system',
                    'what': describe(r, names, users, currency, sides.get(r.id)), 'at': _day(r.at), 'when': r.at})
    return out


def _amount_sides(rows, currency):
    """{row id: (currency of the old value, currency of the new value)} for a lead's value rows (`rows` newest first).
    Walked back from the lead's currency now: a currency change saved with a value (the same save) is that
    value's new side, the currency before it its old side and everything older's -- so "$350 -> ₹25,000" reads
    right after somebody changed both."""
    # one save can flush more than once (a query in between flushes the value before the currency): rows of the
    # same person within two seconds of each other are one save
    saves = []
    for r in rows:
        last = saves[-1] if saves else None
        if last and last[0].user_id == r.user_id and abs((last[-1].at - r.at).total_seconds()) <= 2:
            last.append(r)
        else:
            saves.append([r])
    out, cur = {}, currency
    for grp in saves:
        cc = next((r for r in grp if r.field == 'currency'), None)
        new_side = (cc.new or cur) if cc is not None else cur
        old_side = (cc.old or new_side) if cc is not None else cur
        for r in grp:
            if r.field == 'amount':
                out[r.id] = (old_side, new_side)
        cur = old_side
    return out
