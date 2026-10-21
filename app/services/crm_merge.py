"""Merge two people (Sales CRM 2.0, run 4a) and find the pairs that look like one person.

merge(keep, other): everything that points at `other` is re-pointed at `keep` with bulk UPDATEs (so the
ORM cascades never delete moved rows, and removed -- binned -- enquiries and the tasks, touches and
stage moves hidden with them move too), then `other` is deleted and what `keep` lacked is filled from it.

Every foreign key to crm_people.id, and what is done with it:
    crm_leads.person_id          moved (also the removed ones in the Recycle bin)
    crm_touchpoints.person_id    moved (messages, calls, notes; also those of removed enquiries)
    crm_tasks.person_id          moved (person-only tasks; the tasks of moved enquiries follow their lead)
    crm_identities.person_id     moved; one both people have is kept once (the unique key is global, so this
                                 only happens defensively)
    crm_files.person_id          moved (the files themselves stay where they are on disk)
    crm_audit (record_type 'person', record_id)   moved, so the history stays in one place
    notifications.link '.../crm/contact/<id>'      re-pointed
Not a foreign key but the same idea: crm_households (kept person takes the family if it has none; else the
other simply leaves it, and an empty family is deleted), saved crm_daily_stats from the earliest affected day
(forgotten, so Results recounts live), the WhatsApp CRM (the kept person is marked for sync; the other WhatsApp
contact id is written on a system line and NOTHING is deleted or changed there).
"""
import re
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, update

from app import db
from app.models import (ActivityEvent, CrmAudit, CrmDailyStat, CrmFile, CrmHousehold, CrmIdentity, CrmLead,
                        CrmPerson, CrmTask, CrmTouchpoint, Notification)
from app.services import crm, crm_access, crm_household

SAME = 'Pick a different person to merge with.'
OTHER_WORKSPACE = 'These two people are in different workspaces.'
FIELDS = (('name', 'name'), ('phone', 'phone'), ('email', 'e-mail'), ('country', 'country'))
X = {'synchronize_session': False}


def _plural(n, one, many=None):
    return '%d %s' % (n, one if n == 1 else (many or one + 's'))


def _count(model, *conds):
    return db.session.execute(select(func.count()).select_from(model).where(*conds)
                              .execution_options(include_deleted=True)).scalar() or 0


def plan(keep, other):
    """What a merge would do, in words: {'moves': [..], 'kept': [..], 'filled': [..], 'counts': {...}, 'notes': [..]}.
    In a signed-in GET only the enquiries the viewer may see are counted (the role limit); the merge itself
    (a POST) moves all of them."""
    leads = _count(CrmLead, CrmLead.person_id == other.id)
    binned = _count(CrmLead, CrmLead.person_id == other.id, CrmLead.deleted_at.isnot(None))
    touches = _count(CrmTouchpoint, CrmTouchpoint.person_id == other.id)
    tasks = _count(CrmTask, CrmTask.person_id == other.id) + _count(
        CrmTask, CrmTask.person_id.is_(None), CrmTask.lead_id.in_(select(CrmLead.id).where(CrmLead.person_id == other.id)))
    files = _count(CrmFile, CrmFile.person_id == other.id)
    handles = [i for i in other.identities if i.kind in ('instagram', 'facebook')
               and not any(j.kind == i.kind and j.value == i.value for j in keep.identities)]
    counts = {'leads': leads, 'binned': binned, 'touches': touches, 'tasks': tasks, 'files': files,
              'handles': len(handles)}
    moves = []
    if leads:
        live = _plural(leads - binned, 'enquiry', 'enquiries')
        moves.append(live if not binned else '%s (and %s in the Recycle bin)' % (live, _plural(binned, 'removed one')))
    if touches:
        moves.append(_plural(touches, 'message'))
    if tasks:
        moves.append(_plural(tasks, 'task'))
    if files:
        moves.append(_plural(files, 'file'))
    for h in handles:
        moves.append('%s handle' % h.kind.capitalize())
    if other.household_id and not keep.household_id:
        moves.append('their family')
    kept, filled = [], []
    for attr, label in FIELDS:
        a, b = getattr(keep, attr), getattr(other, attr)
        if a:
            kept.append(label)
        elif b:
            filled.append(label)
    notes = []
    if other.consent_whatsapp and not keep.consent_whatsapp:
        notes.append('WhatsApp permission, which they gave, is kept')
    from app.services import crm_consent
    if crm_consent.withdrawn(other) and not crm_consent.withdrawn(keep):
        notes.append('their “no” to offers stays')
    elif other.consent_marketing and not keep.consent_marketing and not crm_consent.withdrawn(keep):
        notes.append('“OK to send offers”, which they gave, is kept')
    if other.wa_opt_out_at and not keep.wa_opt_out_at:
        notes.append('their opt-out from WhatsApp messages stays')
    if other.wacrm_contact_id and other.wacrm_contact_id != keep.wacrm_contact_id:
        notes.append('their WhatsApp contact is left as it is in the WhatsApp CRM; its id is written on the timeline')
    return {'counts': counts, 'moves': moves, 'kept': kept, 'filled': filled, 'notes': notes}


def search(keep, q, viewer, limit=8):
    """People the viewer may see who match `q`, not `keep` (the merge page's search box)."""
    from app.services import crm_people
    q = ' '.join((q or '').split())
    items = crm_people.find_people(q, limit=limit + 1, user=viewer) if len(q) >= 2 else []
    return [i for i in items if i['id'] != keep.id][:limit]


# ------------------------------------------------------------------------------------ the merge

def _earliest(oid):
    """The first day (India) any enquiry or message of the other person was made."""
    opts = {'include_deleted': True, 'include_hidden': True}
    firsts = [db.session.execute(select(func.min(CrmLead.created_at)).where(CrmLead.person_id == oid)
                                 .execution_options(**opts)).scalar(),
              db.session.execute(select(func.min(CrmTouchpoint.created_at)).where(CrmTouchpoint.person_id == oid)
                                 .execution_options(**opts)).scalar()]
    firsts = [f for f in firsts if f]
    return (min(firsts) + timedelta(hours=5, minutes=30)).date() if firsts else None


def _merge_offers(keep, o):
    """"OK to send offers": given on either is kept (it was given explicitly) -- but a "no" somebody said on either
    (taken back: off, with a date) always stays, like a WhatsApp opt-out. When and how come with whichever wins."""
    k_no = (not keep.consent_marketing) and keep.consent_marketing_at is not None
    o_no = (not o['consent_marketing']) and o['consent_marketing_at'] is not None
    take = False
    if k_no or o_no:
        keep.consent_marketing = False
        take = o_no and not k_no
    elif o['consent_marketing'] and not keep.consent_marketing:
        keep.consent_marketing = True
        take = True
    if take:
        keep.consent_marketing_at = o['consent_marketing_at']
        keep.consent_marketing_how = o['consent_marketing_how']
        keep.consent_marketing_by_id = o['consent_marketing_by_id']


def merge(keep, other, actor=None):
    """Move everything of `other` onto `keep`, delete `other`, write one History line on `keep`. Commits.
    Returns the summary text. The caller has checked that the actor may see both people."""
    if keep.id == other.id:
        raise ValueError(SAME)
    from app.services import crm_scope
    if crm_scope.of(keep) != crm_scope.of(other):
        raise ValueError(OTHER_WORKSPACE)          # two workspaces' contacts are never one person
    kid, oid = keep.id, other.id
    other_name = other.display_name
    db.session.flush()
    # what we need from `other` before it goes
    o = {a: getattr(other, a) for a in ('name', 'phone', 'email', 'country', 'user_id', 'wacrm_contact_id',
                                        'wacrm_conversation_id', 'consent_whatsapp', 'consent_marketing',
                                        'consent_marketing_at', 'consent_marketing_how', 'consent_marketing_by_id',
                                        'wa_opt_out_at', 'household_id', 'household_role')}
    keep_handles = {(i.kind, i.value) for i in keep.identities}
    other_identities = [(i.id, i.kind, i.value) for i in other.identities]
    counts = plan(keep, other)['counts']
    since = _earliest(oid)
    # 1. re-point every foreign key (bulk, so nothing the ORM has loaded is cascaded away)
    db.session.execute(update(CrmLead).where(CrmLead.person_id == oid).values(person_id=kid).execution_options(**X))
    db.session.execute(update(CrmTouchpoint).where(CrmTouchpoint.person_id == oid).values(person_id=kid)
                       .execution_options(**X))
    db.session.execute(update(CrmTask).where(CrmTask.person_id == oid).values(person_id=kid).execution_options(**X))
    db.session.execute(update(CrmFile).where(CrmFile.person_id == oid).values(person_id=kid).execution_options(**X))
    db.session.execute(update(CrmAudit).where(CrmAudit.record_type == 'person', CrmAudit.record_id == oid)
                       .values(record_id=kid).execution_options(**X))
    for iid, kind, value in other_identities:
        if (kind, value) in keep_handles:
            db.session.execute(delete(CrmIdentity).where(CrmIdentity.id == iid).execution_options(**X))
        else:
            db.session.execute(update(CrmIdentity).where(CrmIdentity.id == iid).values(person_id=kid)
                               .execution_options(**X))
    for n in Notification.query.filter(Notification.link.like('%%/crm/contact/%d' % oid)).all():
        n.link = re.sub(r'/crm/contact/%d$' % oid, '/crm/contact/%d' % kid, n.link)
    db.session.flush()
    # 2. `other` goes
    db.session.expire_all()
    stale = db.session.get(CrmPerson, oid)
    if stale is not None:
        db.session.expunge(stale)
    db.session.execute(delete(CrmPerson).where(CrmPerson.id == oid).execution_options(**X))
    db.session.flush()
    db.session.expire_all()
    keep = db.session.get(CrmPerson, kid)
    # 3. what `keep` lacked, from `other` (the audit listener writes each as a normal change)
    taken_phone = False
    if o['name'] and not keep.name:
        keep.name = o['name']
    if o['email'] and not keep.email:
        keep.email = o['email']
    if o['phone'] and not keep.phone:
        keep.phone = o['phone']
        taken_phone = True
    if o['country'] and not keep.country:
        keep.country = o['country']
    if o['user_id'] and not keep.user_id:
        keep.user_id = o['user_id']
    if taken_phone and not keep.wacrm_contact_id:
        keep.wacrm_contact_id, keep.wacrm_conversation_id = o['wacrm_contact_id'], o['wacrm_conversation_id']
    # consent: the more permissive, because the other person gave it explicitly; an opt-out always stays
    keep.consent_whatsapp = bool(keep.consent_whatsapp or o['consent_whatsapp'])
    _merge_offers(keep, o)
    if o['wa_opt_out_at'] and not keep.wa_opt_out_at:
        keep.wa_opt_out_at = o['wa_opt_out_at']
    # the family: the kept person takes it if they had none; otherwise the other just left it
    if o['household_id']:
        if keep.household_id is None and db.session.get(CrmHousehold, o['household_id']) is not None:
            keep.household_id = o['household_id']
            keep.household_role = o['household_role'] or 'other'
        else:
            crm_household.drop_if_empty(o['household_id'])
    # 4. one clear History line, and a system line about the other WhatsApp contact
    bits = []
    for key, one, many in (('leads', 'enquiry', 'enquiries'), ('touches', 'message', None), ('tasks', 'task', None),
                           ('files', 'file', None)):
        if counts[key]:
            bits.append(_plural(counts[key], one, many))
    summary = '%s: %s' % (other_name, ', '.join(bits) if bits else 'nothing to move')
    from app.services.crm_audit import current_user_id
    db.session.add(CrmAudit(at=datetime.utcnow(), user_id=getattr(actor, 'id', None) or current_user_id(),
                            record_type='person', record_id=kid, field='merged', old=None, new=summary[:500]))
    cid = o['wacrm_contact_id']
    if cid and cid != keep.wacrm_contact_id:
        db.session.add(CrmTouchpoint(person_id=kid, channel='note', direction='none',
                                     body=('Merged with another contact. Their WhatsApp contact (id %s) was left '
                                           'as it is in the WhatsApp CRM.' % cid)))
    # 5. saved daily numbers from the earliest affected day are forgotten: Results recounts live
    if since is not None:            # this workspace's days only
        CrmDailyStat.query.filter(CrmDailyStat.day >= since, crm_scope.here(CrmDailyStat, crm_scope.of(keep))) \
            .delete(synchronize_session=False)
    ActivityEvent.log('crm_people_merged', actor=actor, kept_id=kid, removed_id=oid, leads=counts['leads'],
                      touches=counts['touches'], tasks=counts['tasks'], files=counts['files'])
    crm.mark_wa_due(keep)
    db.session.commit()
    try:
        crm._wa_inbound.pop(crm._digits(o['phone']), None)
    except Exception:          # noqa: BLE001 -- a cache
        pass
    return summary


# ------------------------------------------------------------------------------------ possible duplicates

def _tail(phone, n=9):
    d = re.sub(r'\D', '', phone or '').lstrip('0')
    return d[-n:] if len(d) >= 7 else ''


def _words(name):
    return ' '.join((name or '').lower().split())


def find_pairs(viewer, limit=60, pool=20000):
    """Pairs of people who may be one: share an e-mail; or the same name and country with phones that differ
    only by country code / a leading zero; or the same name made within a day of each other. Only people the
    viewer may see. [{'a', 'b', 'why': [..]}], the newest pairs first. One query; the grouping is done here."""
    q = db.session.query(CrmPerson.id, CrmPerson.name, CrmPerson.email, CrmPerson.phone, CrmPerson.country,
                         CrmPerson.created_at)
    seen = crm_access.person_filter(viewer)
    if seen is not None:
        q = q.filter(seen)
    rows = q.order_by(CrmPerson.id.desc()).limit(pool).all()
    pairs = {}

    def add(a, b, why):
        pairs.setdefault((min(a, b), max(a, b)), [])
        if why not in pairs[(min(a, b), max(a, b))]:
            pairs[(min(a, b), max(a, b))].append(why)

    by_email, by_name = {}, {}
    for r in rows:
        if r.email:
            by_email.setdefault(r.email.strip().lower(), []).append(r)
        w = _words(r.name)
        if len(w) >= 3:
            by_name.setdefault(w, []).append(r)
    for group in by_email.values():
        if 1 < len(group) <= 6:
            for i, a in enumerate(group):
                for b in group[i + 1:]:
                    add(a.id, b.id, 'the same e-mail')
    for group in by_name.values():
        if not 1 < len(group) <= 6:
            continue
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                ta, tb = _tail(a.phone), _tail(b.phone)
                if ta and ta == tb and a.phone != b.phone and (a.country or '') == (b.country or ''):
                    add(a.id, b.id, 'the same name and country, and a phone number that differs only by its country code')
                if a.created_at and b.created_at and abs(a.created_at - b.created_at) <= timedelta(days=1):
                    add(a.id, b.id, 'the same name, added within a day of each other')
    if not pairs:
        return []
    ids = {i for k in pairs for i in k}
    people = {p.id: p for p in CrmPerson.query.filter(CrmPerson.id.in_(ids)).all()}
    out = []
    for (a, b), why in sorted(pairs.items(), key=lambda kv: -max(kv[0])):
        if a in people and b in people:
            out.append({'a': people[a], 'b': people[b], 'why': why})
        if len(out) >= limit:
            break
    return out
