"""What a stage needs before a lead moves in (Sales CRM 2.0, run 3b).

`CrmStage.requires` is a list of field keys: the lead's own value / close date / travel date / cover end
date, or one of its pipeline's custom fields (CrmField.key, kept in lead.details). A person's move (drag,
the stage bar, a milestone button, Move to... for many) checks it and, when something is missing, asks for
it in one small form and moves. What the system does by itself (jobs, replies, "lost by no reply") is never
stopped: it does not call these functions.
"""
from datetime import date, datetime

from app import db
from app.models import CrmField, CrmLead

BUILTIN = (('amount', 'Value', 'money'), ('close_date', 'Close date', 'date'),
           ('departure_date', 'Travels on', 'date'), ('ends_on', 'Cover ends', 'date'))
BUILTIN_KEYS = {k for k, _, _ in BUILTIN}
NEED = 'To move it to %s we need: %s.'


def choices(pipeline):
    """[(key, label, type)] a stage of `pipeline` can ask for: the built-in ones, then its custom fields."""
    out = list(BUILTIN)
    q = CrmField.query.filter(CrmField.pipeline_id.in_([pipeline.id, None]) if pipeline is not None
                              else CrmField.pipeline_id.is_(None)).order_by(CrmField.position, CrmField.id)
    seen = set(BUILTIN_KEYS)
    for f in q:
        if f.key not in seen:
            out.append((f.key, f.label, {'number': 'number', 'date': 'date', 'choice': 'choice',
                                         'yesno': 'yesno'}.get(f.type, 'text')))
            seen.add(f.key)
    return out


def clean_requires(raw, pipeline):
    """The keys from the editor that the pipeline can really ask for, in the editor's order."""
    ok = {k for k, _, _ in choices(pipeline)}
    out = []
    for k in raw or []:
        if k in ok and k not in out:
            out.append(k)
    return out


def _empty(v):
    return v is None or v == '' or v == [] or v == {}


def _has(lead, key):
    if key in BUILTIN_KEYS:
        return not _empty(getattr(lead, key, None))
    return not _empty((lead.details or {}).get(key))


def missing(lead, stage):
    """[{'key', 'label', 'type', 'options'}] still empty on the lead for this stage ([] = free to move)."""
    keys = list(stage.requires or []) if stage is not None else []
    if not keys:
        return []
    meta = {k: (label, typ) for k, label, typ in choices(stage.pipeline)}
    opts = {f.key: f.options for f in CrmField.query.filter(
        CrmField.pipeline_id.in_([stage.pipeline_id, None]), CrmField.key.in_(keys))}
    out = []
    for k in keys:
        if k in meta and not _has(lead, k):
            item = {'key': k, 'label': meta[k][0], 'type': meta[k][1], 'options': opts.get(k) or []}
            if k == 'amount':
                # the form says which money the number is in (a USD product's lead is in dollars)
                from app.services import crm_money
                prod = crm_money.product_row(lead.product)
                item['currency'] = crm_money.clean_currency(lead.currency, getattr(prod, 'currency', None))
            out.append(item)
    return out


def apply(lead, values, stage):
    """Store the typed values on the lead (only the keys the stage asks for). Raises ValueError with a
    sentence for a value that does not read right. No commit."""
    from app.services import crm_money
    allowed = {m['key']: m for m in missing(lead, stage)}
    for key, raw in (values or {}).items():
        meta = allowed.get(key)
        if meta is None:
            continue
        text = ('' if raw is None else str(raw)).strip()
        if not text:
            continue
        if key == 'amount':
            try:
                crm_money.set_amount(lead, text, (values or {}).get('currency') or None)
            except (ValueError, ArithmeticError):
                raise ValueError('The value did not look right.')
            if lead.amount is None:
                raise ValueError('The value did not look right.')
        elif key in BUILTIN_KEYS:
            try:
                setattr(lead, key, datetime.strptime(text, '%Y-%m-%d').date())
            except ValueError:
                raise ValueError('%s: pick a date.' % meta['label'])
        else:
            if meta['type'] == 'date':
                try:
                    datetime.strptime(text, '%Y-%m-%d')
                except ValueError:
                    raise ValueError('%s: pick a date.' % meta['label'])
            lead.details = {**(lead.details or {}), key: text[:500]}


def check(lead, stage, values=None):
    """Before a person's move. Returns (ok, missing_after): applies `values` first. Raises ValueError for a
    value that does not read right."""
    if not (stage.requires or []):
        return True, []
    if values:
        apply(lead, values, stage)
        db.session.flush()
    left = missing(lead, stage)
    return (not left), left


def sentence(stage, items):
    return NEED % (stage.name, ', '.join(m['label'].lower() for m in items))
