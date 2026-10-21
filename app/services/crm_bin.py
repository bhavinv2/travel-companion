"""The recycle bin (Sales CRM 2.0, run 3b): removing a lead only marks it (`deleted_at`).

ONE mechanism hides removed leads everywhere: a `do_orm_execute` listener adds
`with_loader_criteria(CrmLead, deleted_at IS NULL)` to every SELECT that involves CrmLead -- queries,
counts, joins from other models, relationship loads (person.leads, task.lead), sub-selects -- unless the
statement carries execution option `include_deleted=True` (the recycle bin page, restore, purge,
erasing a person). Reloading columns of a row that is already loaded (expired attributes) is not filtered.
"""
from datetime import datetime, timedelta

from sqlalchemy import Select, delete, event, exists
from sqlalchemy.orm import with_loader_criteria

from app import db
from app.models import CrmLead, CrmPayment, CrmQuote, CrmStageChange, CrmTask, CrmTouchpoint

KEEP_DAYS = 30
_registered = []


# what hangs on a lead is hidden with it: its tasks, touches and stage moves are kept but never listed
CHILDREN = (CrmTask, CrmTouchpoint, CrmStageChange, CrmQuote, CrmPayment)


def _lead_is_gone(cls):
    L = CrmLead.__table__.alias()
    return ~exists().where(L.c.id == cls.lead_id, L.c.deleted_at.isnot(None)).correlate(cls)


def _on_execute(state):
    if not state.is_select or state.is_column_load or state.execution_options.get('include_deleted'):
        return
    if not isinstance(state.statement, Select):
        return
    # no look at the mappers: Query.count() wraps the real select in another one, which shows none. The
    # criteria only act where the model is really selected from (including inside sub-selects).
    state.statement = state.statement.options(*_options())


_OPTS = []


def _options():
    """The same options for every statement (built once)."""
    if not _OPTS:
        _OPTS.append(with_loader_criteria(CrmLead, lambda cls: cls.deleted_at.is_(None), include_aliases=True))
        _OPTS.extend(with_loader_criteria(child, _lead_is_gone(child), include_aliases=True) for child in CHILDREN)
    return _OPTS


def register():
    if not _registered:
        event.listen(db.session, 'do_orm_execute', _on_execute)
        _registered.append(1)


def removed_query():
    """Leads in the bin (removed within KEEP_DAYS), newest first."""
    since = datetime.utcnow() - timedelta(days=KEEP_DAYS)
    return (CrmLead.query.execution_options(include_deleted=True)
            .filter(CrmLead.deleted_at.isnot(None), CrmLead.deleted_at >= since)
            .order_by(CrmLead.deleted_at.desc()))


# ------------------------------------------------------------------------------------ the actions

def _forget_saved_numbers(lead):
    """Days already saved in crm_daily_stats still count this lead: forget them from the day it came in, and
    the jobs runner saves them again (until then those days are counted live, so nothing is wrong)."""
    from app.models import CrmDailyStat
    from app.services import crm_scope
    since = ((lead.created_at or datetime.utcnow()) + timedelta(hours=5, minutes=30)).date()
    # only the lead's own workspace's days (each workspace saves its own numbers)
    CrmDailyStat.query.filter(CrmDailyStat.day >= since, crm_scope.here(CrmDailyStat, crm_scope.of(lead))) \
        .delete(synchronize_session=False)


def remove(lead, user=None):
    """Remove = put in the bin. The contact, tasks, touches and history stay. Returns the person's name."""
    from app.models import ActivityEvent
    from app.services import crm
    person = lead.person
    name = person.display_name if person else '?'
    lead_id = lead.id
    lead.deleted_at = datetime.utcnow()
    lead.deleted_by_id = user.id if user is not None and getattr(user, 'id', None) else None
    db.session.flush()
    _forget_saved_numbers(lead)
    _after_leaving(person)
    try:
        ActivityEvent.log('crm_lead_removed', actor=user, lead_id=lead_id)
    except Exception:          # noqa: BLE001 -- the log is a courtesy
        pass
    db.session.commit()
    return name


def _after_leaving(person):
    """WhatsApp: no enquiry left -> the portal's tags come off; else their tags follow the leads left."""
    from app.services import crm
    if person is None:
        return
    if not CrmLead.query.filter_by(person_id=person.id).first():
        crm._wa_drop_tags_later(person.wacrm_contact_id, keep_for=person.id)
        person.wacrm_sync_due_at = None
        person.wacrm_assign_due = person.wacrm_assign_if_free = False
    else:
        crm.mark_wa_due(person)


def get_removed(lead_id):
    return (CrmLead.query.execution_options(include_deleted=True)
            .filter(CrmLead.id == lead_id, CrmLead.deleted_at.isnot(None)).first())


def restore(lead, user=None):
    """Put a removed lead back where it was; the person is brought up to date in WhatsApp again."""
    from app.models import ActivityEvent
    from app.services import crm
    lead.deleted_at = None
    lead.deleted_by_id = None
    db.session.flush()
    _forget_saved_numbers(lead)
    crm.mark_wa_due(lead.person)
    try:
        ActivityEvent.log('crm_lead_restored', actor=user, lead_id=lead.id)
    except Exception:          # noqa: BLE001
        pass
    db.session.commit()
    return lead


def hard_delete(lead):
    """The lead and everything on it, for good (the bin's purge, Erase this person). Children go with
    explicit statements: the ORM cascade would not see them, they are hidden with the lead."""
    from app.models import CrmAudit, CrmRuleRun
    from app.services import crm_files
    lid = lead.id
    crm_files.keep_on_person(lid)           # files stay on the person (lead_id emptied); Erase deletes them
    for model in CHILDREN:
        db.session.execute(delete(model).where(model.lead_id == lid).execution_options(synchronize_session=False))
    db.session.execute(delete(CrmRuleRun).where(CrmRuleRun.lead_id == lid))      # where automation rules ran on it
    db.session.execute(delete(CrmAudit).where(CrmAudit.record_type == 'lead', CrmAudit.record_id == lid))
    db.session.expunge(lead)
    db.session.execute(delete(CrmLead).where(CrmLead.id == lid).execution_options(synchronize_session=False))
    return lid


def purge(lead, user=None):
    """Delete a removed lead for good: through the same path a removal always had, so the WhatsApp
    contact is cleaned up when this was the person's last enquiry."""
    from app.models import ActivityEvent
    person = lead.person
    lid = hard_delete(lead)
    db.session.flush()
    _after_leaving(person)
    try:
        ActivityEvent.log('crm_lead_purged', actor=user, lead_id=lid)
    except Exception:          # noqa: BLE001
        pass
    db.session.commit()
    return lid


def purge_old(now=None, limit=200):
    """Job: leads removed more than KEEP_DAYS ago are deleted for good."""
    now = now or datetime.utcnow()
    old = (CrmLead.query.execution_options(include_deleted=True)
           .filter(CrmLead.deleted_at.isnot(None), CrmLead.deleted_at < now - timedelta(days=KEEP_DAYS))
           .order_by(CrmLead.deleted_at).limit(limit).all())
    n = 0
    for lead in old:
        purge(lead)
        n += 1
    return {'crm_bin_purged': n}
