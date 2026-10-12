"""The Sales CRM: one record per person, one lead per product, and the next step for each lead.

How a lead moves, in one place:

  capture()      every form, pop-up, chat and import calls this with its lead-source key. The source
                 (set up on screen, Sales CRM -> Setup) says which product and pipeline the lead
                 starts in and who owns it. An unknown key is not an error: the lead is kept, and
                 the source appears as "unrouted" for an admin to set up once.
  plan_next()    puts the next playbook step of the lead's stage on someone's list as a task, due by
                 its trigger -- hours after the stage began, or days before the trip departs.
  move_stage()   records who moved it and why, closes the old stage's open task, and plans the
                 first step of the new one.
  record_reply() a reply from the person. Out of a pipeline's first stage it moves the lead to the
                 stage marked "a reply moves here" -- cold lead becomes prospect without anyone
                 having to drag a card.

Nothing here commits halfway: each public function leaves the session flushed and commits once.
capture_safely() is what the public forms call, so a CRM fault can never cost somebody the
enquiry they just sent.
"""
import logging
import re
from datetime import datetime, date, time, timedelta
from urllib.parse import quote

from flask import current_app, request
from sqlalchemy import func, or_

from app import db
from app.models import (CrmAnswer, CrmIdentity, CrmLead, CrmPerson, CrmPipeline, CrmPlaybookStep,
                        CrmSource, CrmStage, CrmStageChange, CrmTask, CrmTouchpoint, User,
                        CRM_CHECK_CHANNELS, CRM_PRODUCT_LABELS, CRM_PRODUCTS)

log = logging.getLogger(__name__)

IST = timedelta(hours=5, minutes=30)
SOURCE_KEY_RE = re.compile(r'^[a-z0-9][a-z0-9-]{1,58}$')
UTM_COOKIE = 'nps_src'
UTM_KEYS = ('utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content', 'gclid',
            'fbclid', 'referrer', 'landing')
NO_ANSWER_LIMIT = 3          # CL #3: the third unanswered call is the last
SETTINGS_KEY = 'crm'
WA_MODES = {'off': 'Off -- nothing goes to the WhatsApp CRM',
            'contacts': 'Add new leads as contacts only',
            'send': 'Contacts, and send messages from here'}


# ======================================================================================= settings

def crm_settings():
    """The CRM's own switches, set on screen (Set-up -> Connect a page)."""
    from app.services import settings
    s = settings.get_setting(SETTINGS_KEY) or {}
    return {'whatsapp_mode': s.get('whatsapp_mode') if s.get('whatsapp_mode') in WA_MODES else 'off',
            'check_channels': list(s.get('check_channels') or CRM_CHECK_CHANNELS)}


def crm_settings_raw():
    from app.services import settings
    return dict(settings.get_setting(SETTINGS_KEY) or {})


def save_settings(actor=None, **changes):
    from app.services import settings
    cur = dict(settings.get_setting(SETTINGS_KEY) or {})
    cur.update(changes)
    settings.set_setting(SETTINGS_KEY, cur, actor)


def wa_mode():
    """What the WhatsApp CRM is used for. Off until an admin says otherwise, even with the keys set,
    so a laptop with the keys in its .env cannot message real customers by accident."""
    from app.services import wacrm
    return crm_settings()['whatsapp_mode'] if wacrm.enabled() else 'off'


def wa_can_send():
    return wa_mode() == 'send'


# ======================================================================================= set-up

def ensure_defaults():
    """Write the starting pipelines, steps, answers and sources the first time the CRM is used.

    Idempotent and cheap: pipelines are only seeded into an empty table, and a built-in source is
    only added when its key is missing, so nothing an admin edited is ever overwritten.
    """
    from app.services import crm_defaults as d
    changed = False
    if not db.session.query(CrmPipeline.id).first():
        automations = []
        for key, name, product, reasons, stages in d.PIPELINES:
            p = CrmPipeline(key=key, name=name, product=product, fallout_reasons=reasons)
            db.session.add(p)
            for pos, stage_def in enumerate(stages):
                skey, sname, kind, on_reply, sla, steps = stage_def[:6]
                st = CrmStage(key=skey, name=sname, kind=kind, on_reply=on_reply, sla_hours=sla,
                              position=pos)
                p.stages.append(st)
                for spos, (code, title, channel, trig, val, auto, body) in enumerate(steps):
                    st.steps.append(CrmPlaybookStep(code=code, title=title, channel=channel,
                                                    trigger=trig, trigger_value=val, auto=auto,
                                                    body=body, position=spos))
                if len(stage_def) > 6 and stage_def[6]:
                    automations.append((p, st, stage_def[6]))
        db.session.flush()
        for p, st, (akind, adays, to_key, reason) in automations:
            target = next((s for s in p.stages if s.key == to_key), None)
            if target is not None:
                st.auto_kind, st.auto_days, st.auto_to, st.auto_reason = akind, adays, target, reason
        changed = True
    if not db.session.query(CrmAnswer.id).filter(CrmAnswer.code.is_(None)).first():
        for product, title, keywords, body in d.ANSWERS:
            db.session.add(CrmAnswer(product=product, title=title, keywords=keywords, body=body))
        changed = True
    if not db.session.query(CrmAnswer.id).filter(CrmAnswer.code.isnot(None)).first():
        for product, code, title, body in d.QUICK_MESSAGES:
            db.session.add(CrmAnswer(product=product, code=code, title=title, body=body))
        changed = True
    if changed:
        db.session.flush()
    have = {k for (k,) in db.session.query(CrmSource.key).all()}
    pipes = {p.key: p for p in CrmPipeline.query.all()}
    for key, name, kind, product, pkey, pages, status in d.SOURCES:
        if key not in have:
            db.session.add(CrmSource(key=key, name=name, kind=kind, product=product, pages=pages,
                                     pipeline=pipes.get(pkey), status=status, built_in=True))
            changed = True
    if changed:
        db.session.commit()


def pipeline_for_product(product):
    from app.services.crm_defaults import PRODUCT_PIPELINE
    key = PRODUCT_PIPELINE.get(product or 'GEN', 'general')
    return (CrmPipeline.query.filter_by(key=key, is_active=True).first()
            or CrmPipeline.query.filter_by(product=product, is_active=True).first()
            or CrmPipeline.query.filter_by(key='general').first())


def source(key):
    return CrmSource.query.filter_by(key=key).first() if key else None


# ======================================================================================= people

def normalise_phone(phone, cc=None):
    """E.164 or None. `cc` is the ISO country picked beside the number, when the form had one."""
    from app.services import phone as phone_svc
    raw = (phone or '').strip()
    if not raw:
        return None
    e164, err = phone_svc.normalise(raw, (cc or '').upper() or ('IN' if not raw.startswith('+') else 'US'))
    return None if err else e164


IG_URL = re.compile(r'instagram\.com/([A-Za-z0-9_.]{1,30})', re.I)
FB_URL = re.compile(r'facebook\.com/(?:profile\.php\?id=)?([A-Za-z0-9_.]{1,80})', re.I)


def clean_identity(kind, value):
    """One spelling per handle, so "@Priya.R", "priya.r" and instagram.com/priya.r are one person."""
    v = (value or '').strip()
    if not v:
        return None
    if kind == 'instagram':
        m = IG_URL.search(v)
        v = (m.group(1) if m else v.lstrip('@').split('?')[0].strip('/')).lower()
        return v if re.fullmatch(r'[a-z0-9_.]{1,30}', v) else None
    if kind == 'facebook':
        m = FB_URL.search(v)
        v = (m.group(1) if m else v.lstrip('@').split('?')[0].strip('/'))
        return v[:190] if v and ' ' not in v else None
    return v[:190]


def find_person(phone=None, email=None, identities=None):
    for kind, value in identities or []:
        hit = CrmIdentity.query.filter_by(kind=kind, value=value).first()
        if hit:
            return hit.person
    if phone:
        p = CrmPerson.query.filter_by(phone=phone).first()
        if p:
            return p
    if email:
        q = CrmPerson.query.filter(func.lower(CrmPerson.email) == email.lower())
        # an e-mail match only counts when it does not belong to somebody with another number
        p = q.filter(CrmPerson.phone.is_(None)).first() if phone else q.first()
        if p:
            return p
    return None


def upsert_person(phone=None, email=None, name=None, user_id=None, consent=None, identities=None):
    identities = [(k, v) for k, v in (identities or []) if k and v]
    person = find_person(phone, email, identities)
    if person is None:
        person = CrmPerson(phone=phone, email=email or None)
        db.session.add(person)
    if phone and not person.phone and not CrmPerson.query.filter_by(phone=phone).first():
        person.phone = phone
    if email and not person.email:
        person.email = email
    have = {(i.kind, i.value) for i in person.identities}
    for kind, value in identities:
        if (kind, value) not in have and not CrmIdentity.query.filter_by(kind=kind, value=value).first():
            person.identities.append(CrmIdentity(kind=kind, value=value))
    # a real name beats none, and beats the placeholders some forms send
    if name and (not person.name or person.name.lower() in ('newsletter subscriber', 'unknown')):
        person.name = name[:120]
    if user_id and not person.user_id:
        person.user_id = user_id
    if phone:
        from app.services import phone as phone_svc
        person.country = (phone_svc.iso_for(phone) or '')[:2] or None
    if consent:
        person.consent_whatsapp = True
    db.session.flush()
    return person


# ======================================================================================= capture

def utm_from_request():
    """Where this visitor came from: the first-visit cookie set by static/js/crm-src.js, then the
    current address's own utm_ parameters. Empty outside a request."""
    out = {}
    try:
        import json
        from urllib.parse import unquote
        raw = request.cookies.get(UTM_COOKIE)
        if raw:
            data = json.loads(unquote(raw))
            if isinstance(data, dict):
                out.update({k: str(v)[:200] for k, v in data.items() if k in UTM_KEYS and v})
        for k in UTM_KEYS:
            v = request.args.get(k)
            if v and k not in out:
                out[k] = v[:200]
    except Exception:          # noqa: BLE001 -- no request, or a cookie somebody mangled
        return out
    return out


def _owner_candidates(src):
    """Who may own a lead from `src`: its team, or every CS agent whose console has the CRM."""
    from app.services import cs_access
    staff = cs_access.recipients('crm_board', limit=None)
    team = {int(i) for i in (src.team or [])} if src else set()
    if team:
        users = [u for u in staff if u.id in team]
    else:
        # the agents; an admin only when there is nobody else to give it to
        users = [u for u in staff if not u.is_admin]
    return users or [u for u in staff if u.is_admin]


def assign_owner(src):
    """The candidate holding the fewest open leads -- spreads work evenly without a rota."""
    users = _owner_candidates(src)
    if not users:
        return None
    ids = [u.id for u in users]
    loads = dict(db.session.query(CrmLead.owner_id, func.count(CrmLead.id))
                 .filter(CrmLead.owner_id.in_(ids), CrmLead.status == 'open')
                 .group_by(CrmLead.owner_id).all())
    return min(users, key=lambda u: (loads.get(u.id, 0), u.id))


def _summary(details, message=None):
    lines = []
    if message:
        lines.append(message.strip())
    for k, v in (details or {}).items():
        if v in (None, '', [], {}):
            continue
        if isinstance(v, (list, tuple)):
            v = ', '.join(str(x) for x in v)
        lines.append('%s: %s' % (k.replace('_', ' ').capitalize(), v))
    return '\n'.join(lines)[:4000] or None


def capture(source_key, *, name=None, phone=None, phone_cc=None, email=None, product=None,
            details=None, message=None, ref=None, utm=None, departure_date=None, consent=None,
            user_id=None, channel='form', when=None, identities=None, ends_on=None,
            created_by_id=None, start_stage=None, plan=True, notify=True, temperature=None,
            fallout_reason=None, external_id=None, sync=True, imported=False, likelihood=None):
    """Record an enquiry as a lead. Returns the lead, or None when there is nobody to reach.

    The same person asking about the same product again within the source's window is the same
    lead: the new enquiry is added to its timeline rather than starting a second card.

    `identities` reach somebody without a phone or e-mail: [('instagram', 'handle'), ...].
    The importers pass `start_stage` (where the lead already is), plan=False, notify=False and
    sync=False (the WhatsApp CRM allows 120 calls a minute; a bulk import would trip it).
    """
    ensure_defaults()
    key = (source_key or '').strip().lower()
    if not SOURCE_KEY_RE.match(key):
        key = 'unknown'
    src = source(key)
    new_source = src is None
    if new_source:
        # a page nobody has set up yet: keep the lead, and let an admin choose its pipeline once
        src = CrmSource(key=key, name=key.replace('-', ' ').capitalize(), kind='api' if channel == 'form' else 'chat',
                        product=product if product in CRM_PRODUCTS else 'GEN', status='unrouted')
        db.session.add(src)
        db.session.flush()

    e164 = normalise_phone(phone, phone_cc)
    email = (email or '').strip().lower() or None
    if email and ('@' not in email or email.startswith('no-email@')):
        email = None
    identities = [(k, clean_identity(k, v)) for k, v in (identities or [])]
    identities = [(k, v) for k, v in identities if v]
    if not e164 and not email and not identities:
        return None
    person = upsert_person(e164, email, (name or '').strip() or None, user_id=user_id, consent=consent,
                           identities=identities)

    product = product if product in CRM_PRODUCTS else src.product
    now = when or datetime.utcnow()
    details = {k: v for k, v in (details or {}).items() if v not in (None, '', [], {})}
    utm = utm if utm is not None else utm_from_request()

    since = now - timedelta(days=max(src.dedupe_days or 0, 0))
    lead = (CrmLead.query.filter(CrmLead.person_id == person.id, CrmLead.product == product,
                                 CrmLead.status == 'open', CrmLead.last_activity_at >= since)
            .order_by(CrmLead.last_activity_at.desc()).first())
    created = lead is None
    if created:
        pipe = src.pipeline if src.status != 'unrouted' else None
        if start_stage is None and pipe is not None and pipe.product == 'GEN' and product not in (None, 'GEN'):
            # a catch-all source (Instagram, a call) with a known product: that product's pipeline
            better = pipeline_for_product(product)
            if better is not None and better.product != 'GEN':
                start_stage = better.first_stage
        if start_stage is not None:
            pipe = start_stage.pipeline
        stage = start_stage or (pipe.first_stage if pipe else None)
        lead = CrmLead(person=person, product=product, source=src, pipeline=pipe, stage=stage,
                       status=stage.kind if stage else 'open',
                       owner=assign_owner(src), details=details, utm=utm or None,
                       departure_date=departure_date, ends_on=ends_on, created_at=now,
                       last_activity_at=now, entered_stage_at=now, created_by_id=created_by_id,
                       temperature=temperature, likelihood=likelihood, imported=imported)
        if stage is not None and stage.kind != 'open':
            lead.closed_at = now
            lead.fallout_reason = fallout_reason if stage.kind == 'lost' else None
        if ref:
            lead.ref_type, lead.ref_id = ref[0], ref[1]
        db.session.add(lead)
        db.session.flush()
        if lead.stage:
            db.session.add(CrmStageChange(lead=lead, from_stage_id=None, to_stage_id=lead.stage.id,
                                          reason='Came in from %s' % src.name, created_at=now))
    else:
        lead.details = {**(lead.details or {}), **details}
        if departure_date and not lead.departure_date:
            lead.departure_date = departure_date
        if ends_on and not lead.ends_on:
            lead.ends_on = ends_on
        if utm and not lead.utm:
            lead.utm = utm
        lead.last_activity_at = max(lead.last_activity_at or now, now)

    db.session.add(CrmTouchpoint(lead=lead, person_id=person.id, channel=channel, direction='in',
                                 body=_summary(details, message), code=None, created_at=now,
                                 external_id=external_id))
    src.lead_count = (src.lead_count or 0) + 1
    src.last_lead_at = max(src.last_lead_at or now, now)
    if created and plan and src.status == 'live' and lead.status == 'open':
        plan_next(lead, base=max(now, datetime.utcnow()))
    db.session.commit()
    if created:
        if sync:
            _push_to_whatsapp_crm(lead)
        if notify:
            _tell_owner(lead, new_source=new_source)
    return lead


def _lead_link(lead):
    try:
        from flask import url_for
        return url_for('crm.lead', lead_id=lead.id)
    except Exception:          # noqa: BLE001 -- outside a request (CLI, jobs)
        return '/cs/crm/lead/%d' % lead.id


def _tell_owner(lead, new_source=False):
    """A bell notification for whoever got the lead -- and for the admins, the first time a page
    nobody has set up sends one. Best effort: a notification never undoes a lead."""
    from app.services import notify
    try:
        what = '%s · %s' % (CRM_PRODUCT_LABELS.get(lead.product, lead.product),
                            lead.source.name if lead.source else 'unknown source')
        if lead.owner_id:
            notify.push(lead.owner_id, 'crm_lead', title='New lead: %s' % lead.person.display_name,
                        body=what, link=_lead_link(lead))
        if new_source:
            from app.services import cs_access
            for u in User.query.filter(User.is_admin.is_(True), User.is_active.is_(True)).all():
                notify.push(u.id, 'crm_source', title='A new lead source needs setting up',
                            body='"%s" sent its first lead. Choose its pipeline once in Sales CRM -> Set-up.'
                                 % lead.source.key, link='/cs/crm/setup?tab=sources')
        db.session.commit()
    except Exception:          # noqa: BLE001
        db.session.rollback()
        log.warning('CRM notification failed for lead %s', lead.id, exc_info=True)


def capture_safely(source_key, **kw):
    """capture() for the public forms: whatever goes wrong here, the enquiry is already saved."""
    try:
        return capture(source_key, **kw)
    except Exception:        # noqa: BLE001 -- a CRM fault must never cost somebody their enquiry
        db.session.rollback()
        current_app.logger.exception('CRM capture failed for source %r', source_key)
        return None


def capture_trip(trip, source_key, user_id=None, **kw):
    """A trip post as a Travel Companion lead: who to reach (its contact numbers, else the account
    that posted it), the route and the date it leaves. Safe like capture_safely()."""
    phone = email = None
    identities = []
    try:
        for cp in trip.contact_points or []:
            if cp.type in ('mobile', 'whatsapp') and not phone:
                phone = normalise_phone(cp.value)
            elif cp.type == 'email' and not email:
                email = cp.value
            elif cp.type in ('instagram', 'facebook'):
                identities.append((cp.type, cp.value))
        author = getattr(trip, 'author', None)
        if author is not None:
            phone = phone or normalise_phone(author.phone)
            email = email or author.email
        name = trip.poster_name or trip.traveler_name or (author.full_name if author is not None else None)
        details = {'route': ' → '.join(x for x in (trip.flying_from, trip.destination) if x),
                   'they_are': (trip.role or '').replace('_', ' '),
                   'airline': ' '.join(x for x in (trip.airline, trip.flight_number) if x),
                   'post': '#%s (%s)' % (trip.id, trip.status)}
    except Exception:        # noqa: BLE001 -- see capture_safely
        current_app.logger.exception('CRM could not read trip %s', getattr(trip, 'id', None))
        return None
    return capture_safely(source_key, name=name, phone=phone, email=email, product='TC',
                          details=details, departure_date=trip.from_date, ends_on=trip.to_date,
                          ref=('companion_requests', trip.id), user_id=user_id or trip.user_id,
                          identities=identities, created_by_id=trip.created_by_id, **kw)


def trip_claimed(trip):
    """The traveller confirmed a post CS made for them: that is their reply, so the lead moves on
    (posted -> in touch) without anybody dragging it. A post the CRM never saw becomes a lead."""
    try:
        lead = (CrmLead.query.filter_by(ref_type='companion_requests', ref_id=trip.id)
                .order_by(CrmLead.created_at.desc()).first())
        if lead is None:
            return capture_trip(trip, 'tc-cs-post')
        record_reply(lead, 'Confirmed their post through the link we sent.', channel='form')
        db.session.commit()
        return lead
    except Exception:        # noqa: BLE001 -- the claim itself has already been saved
        db.session.rollback()
        current_app.logger.exception('CRM could not record the claim of trip %s', trip.id)
        return None


def _push_to_whatsapp_crm(lead):
    """Create the contact in the WhatsApp CRM with the source's tags. Best effort."""
    from app.services import wacrm
    if wa_mode() == 'off' or not lead.person.phone:
        return
    try:
        tags = list(lead.source.crm_tags or []) if lead.source else []
        tags += [lead.product.lower()]
        cid = wacrm.upsert_contact(lead.person.phone, lead.person.name, lead.person.email, tags)
        if cid and lead.person.wacrm_contact_id != cid:
            lead.person.wacrm_contact_id = cid
            db.session.commit()
    except Exception:        # noqa: BLE001
        db.session.rollback()
        log.warning('WhatsApp CRM contact sync failed for lead %s', lead.id, exc_info=True)


# ======================================================================================= tasks

def _due(step, lead, base):
    if step.trigger in ('before_departure_days', 'before_end_days'):
        anchor = lead.departure_date if step.trigger == 'before_departure_days' else lead.ends_on
        if anchor:
            day = anchor - timedelta(days=step.trigger_value or 0)
            at = datetime.combine(day, time(9, 0)) - IST      # 9 am in India
            return max(at, base)
        return base + timedelta(hours=24)
    return base + timedelta(hours=step.trigger_value or 0)


def _next_step(stage, after=None):
    steps = list(stage.steps or []) if stage else []
    if after is None:
        return steps[0] if steps else None
    return next((s for s in steps if s.position > after.position), None)


def plan_next(lead, after_step=None, base=None):
    """Put the stage's next step on the owner's list. Returns the task, or None at the end."""
    if lead.source and lead.source.status == 'paused':
        return None
    step = _next_step(lead.stage, after_step)
    if step is None:
        return None
    base = base or datetime.utcnow()
    task = CrmTask(lead=lead, step=step, code=step.code, title=step.title, channel=step.channel,
                   auto=bool(step.auto), due_at=_due(step, lead, base), owner_id=lead.owner_id)
    db.session.add(task)
    db.session.flush()
    return task


def complete_task(task, user=None, skipped=False, note=None):
    if task.status != 'open':
        return None
    task.status = 'skipped' if skipped else 'done'
    task.done_at = datetime.utcnow()
    task.done_by_id = getattr(user, 'id', None)
    task.note = (note or '')[:200] or None
    task.lead.last_activity_at = task.done_at
    return plan_next(task.lead, after_step=task.step)


def snooze_task(task, hours=24):
    task.due_at = max(task.due_at, datetime.utcnow()) + timedelta(hours=hours)


# ======================================================================================= stages

def move_stage(lead, stage, user=None, reason=None, fallout_reason=None, plan=True):
    if stage is None or stage.pipeline_id != lead.pipeline_id or stage.id == lead.stage_id:
        return False
    now = datetime.utcnow()
    for t in lead.tasks:
        if t.status == 'open':
            t.status, t.done_at, t.note = 'skipped', now, 'Stage changed'
    db.session.add(CrmStageChange(lead=lead, from_stage_id=lead.stage_id, to_stage_id=stage.id,
                                  by_id=getattr(user, 'id', None),
                                  reason=(reason or fallout_reason or '')[:160] or None))
    lead.stage = stage
    lead.entered_stage_at = now
    lead.sla_alerted_at = None
    lead.last_activity_at = now
    lead.status = stage.kind
    lead.closed_at = now if stage.kind in ('won', 'lost') else None
    lead.fallout_reason = (fallout_reason or None) if stage.kind == 'lost' else None
    db.session.flush()
    if plan:
        plan_next(lead, base=now)
    return True


def set_pipeline(lead, pipeline, user=None):
    """Route an unrouted lead (or move it to another pipeline): first stage, first step."""
    if pipeline is None:
        return
    for t in lead.tasks:
        if t.status == 'open':
            t.status, t.done_at, t.note = 'skipped', datetime.utcnow(), 'Pipeline changed'
    lead.pipeline = pipeline
    first = pipeline.first_stage
    db.session.add(CrmStageChange(lead=lead, from_stage_id=lead.stage_id, to_stage_id=first.id,
                                  by_id=getattr(user, 'id', None), reason='Pipeline: %s' % pipeline.name))
    lead.stage = first
    lead.status = 'open'
    lead.closed_at = lead.fallout_reason = lead.sla_alerted_at = None
    lead.entered_stage_at = datetime.utcnow()
    db.session.flush()
    plan_next(lead)


# ======================================================================================= touches

def log_touch(lead, channel, direction='out', body=None, code=None, outcome=None, user=None,
              status=None, external_id=None):
    tp = CrmTouchpoint(lead=lead, person_id=lead.person_id, channel=channel, direction=direction,
                       body=(body or None), code=code, outcome=outcome, status=status,
                       agent_id=getattr(user, 'id', None), external_id=external_id)
    db.session.add(tp)
    lead.last_activity_at = datetime.utcnow()
    db.session.flush()
    return tp


def record_reply(lead, text=None, channel='whatsapp', external_id=None):
    """The person answered. Logged, and out of the first stage it promotes the lead."""
    log_touch(lead, channel, 'in', body=text, external_id=external_id)
    lead.temperature = lead.temperature if lead.temperature in ('L',) else 'R'
    pipe = lead.pipeline
    if pipe and lead.stage and lead.status == 'open':
        target = pipe.reply_stage
        first = pipe.first_stage
        if target and lead.stage_id == first.id and target.id != first.id:
            move_stage(lead, target, reason='They replied')
    db.session.flush()


def no_answer_streak(lead):
    """How many calls in a row went unanswered -- three ends the cold-lead attempts."""
    n = 0
    # newest first -- sorted here, because rows added in this session sit at the end of the list
    for tp in sorted(lead.touchpoints, key=lambda t: (t.created_at or datetime.min, t.id or 0), reverse=True):
        if tp.channel != 'call':
            continue
        if tp.outcome in ('no_answer', 'busy', 'switched_off'):
            n += 1
        else:
            break
    return n


# ======================================================================================= messages

def first_name(text):
    return (text or '').strip().split(' ')[0] if text else ''


def fill(text, lead, user=None):
    """Fill {name}, {agent} and the rest into a message for this lead."""
    if not text:
        return ''
    from flask import url_for
    from app.services import offices
    owner = lead.owner or user
    values = {
        'name': first_name(lead.person.name) or 'there',
        'agent': first_name(getattr(owner, 'first_name', None) or getattr(owner, 'username', None))
                 or 'the NRI Parent Service team',
        'product': CRM_PRODUCT_LABELS.get(lead.product, '').lower(),
        'departure': lead.departure_date.strftime('%d %b') if lead.departure_date else 'soon',
        'days': lead.days_to_departure if lead.days_to_departure is not None else 'a few',
        'ends': lead.ends_on.strftime('%d %b') if lead.ends_on else 'soon',
        'helplines': ', '.join('%s (%s)' % (n['display'], n['label']) for n in offices.numbers()[:3])
                     or 'our helpline',
    }
    site = (current_app.config.get('SITE_URL') or '').rstrip('/')
    for var, endpoint in (('insurance_link', 'insurance.landing'), ('companion_link', 'main.all_trips'),
                          ('sahayak_link', 'sahayak.landing'), ('site_link', 'main.index')):
        try:
            from app.services import urls
            path = urls.public_url(endpoint)
            values[var] = path if path.startswith('http') else site + path
        except Exception:      # noqa: BLE001 -- outside a request, or a route that is not there
            values[var] = site or ''

    def sub(m):
        return str(values.get(m.group(1), m.group(0)))
    return re.sub(r'\{([a-z_]+)\}', sub, text)


def whatsapp_link(lead, text):
    digits = (lead.person.phone or '').lstrip('+')
    if not digits:
        return ''
    return 'https://wa.me/%s?text=%s' % (digits, quote(text or ''))


def send_whatsapp(lead, text, user=None, code=None, task=None):
    """Send through the WhatsApp CRM when it is connected, otherwise hand back a wa.me link for
    the agent's own WhatsApp. Either way the message is logged and the task ticked off.

    Returns {'mode': 'sent'} or {'mode': 'link', 'url': ...}.
    """
    from app.services import wacrm
    result = {'mode': 'link', 'url': whatsapp_link(lead, text)}
    status = 'opened'
    external = None
    if wa_can_send() and lead.person.phone:
        try:
            external = wacrm.send_text(lead.person.phone, text)
            result, status = {'mode': 'sent'}, 'sent'
        except wacrm.WacrmError as exc:
            # outside the 24-hour window Meta wants a template; the agent's own WhatsApp still works
            result['warning'] = str(exc)
    log_touch(lead, 'whatsapp', 'out', body=text, code=code, user=user, status=status,
              external_id=external)
    if task is not None:
        complete_task(task, user=user)
    db.session.commit()
    return result


def log_call(lead, outcome, note=None, user=None, task=None):
    """A call and how it went. Returns the number of unanswered calls in a row."""
    log_touch(lead, 'call', 'out', body=note, code=task.code if task else None, outcome=outcome,
              user=user)
    if outcome == 'connected':
        lead.temperature = 'R'
        pipe = lead.pipeline
        if pipe and lead.stage and pipe.reply_stage and lead.stage_id == pipe.first_stage.id:
            move_stage(lead, pipe.reply_stage, user=user, reason='Talked on the phone')
            task = None             # moving the stage already planned the next step
    elif outcome == 'wrong_number':
        lead.temperature = 'DL'
    if task is not None and task.status == 'open':
        complete_task(task, user=user, note=outcome)
    db.session.commit()
    return no_answer_streak(lead)


# ======================================================================================= jobs

def run_auto_steps(now=None, limit=200):
    """Send the steps marked automatic that are due -- only once the WhatsApp CRM is connected,
    and only through an approved template or inside the 24-hour window Meta allows."""
    from app.services import wacrm
    if not wa_can_send():
        return {'crm_auto_sent': 0}
    now = now or datetime.utcnow()
    sent = 0
    due = (CrmTask.query.filter(CrmTask.status == 'open', CrmTask.auto.is_(True),
                                CrmTask.channel == 'whatsapp', CrmTask.due_at <= now)
           .order_by(CrmTask.due_at).limit(limit).all())
    for task in due:
        lead = task.lead
        if not lead.person.phone or lead.status == 'lost':
            # nothing to send to, or nobody to send it to any more: off the list, not retried
            task.status, task.done_at, task.note = 'skipped', now, 'Not sent automatically'
            db.session.commit()
            continue
        try:
            step = task.step
            if step and step.wa_template:
                external = wacrm.send_template(lead.person.phone, step.wa_template,
                                               params=[first_name(lead.person.name) or 'there'])
                body = '[template %s]' % step.wa_template
            else:
                body = fill(step.body if step else task.title, lead)
                external = wacrm.send_text(lead.person.phone, body)
            log_touch(lead, 'whatsapp', 'out', body=body, code=task.code, status='sent',
                      external_id=external)
            complete_task(task)
            db.session.commit()
            sent += 1
        except Exception:      # noqa: BLE001 -- one bad number must not stop the rest
            db.session.rollback()
            log.warning('CRM auto step %s failed', task.id, exc_info=True)
    return {'crm_auto_sent': sent}


def run_stage_automations(now=None, limit=500):
    """The stages that move leads by themselves (Set-up -> Pipelines): after N days with no reply
    from them, or N days after the trip starts. The reason is recorded like a person's move."""
    now = now or datetime.utcnow()
    today = (now + IST).date()
    moved = 0
    for st in CrmStage.query.filter(CrmStage.auto_kind.isnot(None), CrmStage.auto_to_id.isnot(None)).all():
        days = max(st.auto_days or 0, 0)
        target = st.auto_to
        if target is None or target.pipeline_id != st.pipeline_id or target.id == st.id:
            continue
        q = CrmLead.query.filter(CrmLead.stage_id == st.id, CrmLead.status == 'open')
        if st.auto_kind == 'no_reply':
            q = q.filter(CrmLead.entered_stage_at <= now - timedelta(days=days))
        elif st.auto_kind == 'departed':
            q = q.filter(CrmLead.departure_date.isnot(None),
                         CrmLead.departure_date <= today - timedelta(days=days))
        else:
            continue
        for lead in q.limit(limit).all():
            if st.auto_kind == 'no_reply':
                heard = (CrmTouchpoint.query.filter(CrmTouchpoint.lead_id == lead.id,
                                                    CrmTouchpoint.direction == 'in',
                                                    CrmTouchpoint.channel != 'form',
                                                    CrmTouchpoint.created_at >= lead.entered_stage_at)
                         .first())
                if heard:
                    continue
            reason = st.auto_reason or 'Moved automatically'
            move_stage(lead, target, reason=reason + ' (automatic)',
                       fallout_reason=reason if target.kind == 'lost' else None)
            moved += 1
    db.session.commit()
    return {'crm_auto_moved': moved}


EVENTS = {
    # code: (what happened, the stage it moves the lead to, if the pipeline has it)
    'Q': ('Quote sent', 'quoted'),
    'PLS': ('Payment link sent', 'pipeline'),
}


def mark_event(lead, code, user=None, note=None):
    """A button on the lead: Quote sent (Q) / Payment link sent (PLS). Logged under its code, and
    the lead moves forward to the matching stage -- never back. Returns the stage it moved to."""
    label, stage_key = EVENTS[code]
    log_touch(lead, 'whatsapp', 'out', body=note or label, code=code, user=user, status='sent')
    target = next((s for s in (lead.pipeline.stages if lead.pipeline else []) if s.key == stage_key), None)
    moved = None
    if target is not None and lead.status == 'open' and lead.stage and target.position > lead.stage.position:
        move_stage(lead, target, user=user, reason=label)
        moved = target
    db.session.commit()
    return moved


def quick_messages(product=None):
    """The ready messages with a code (BW, FM, HJ...), the lead's product first."""
    rows = CrmAnswer.query.filter(CrmAnswer.code.isnot(None)).all()
    rows.sort(key=lambda a: (a.product not in (product, 'GEN'), a.product != product, a.code))
    return rows


# ======================================================================================= whatsapp thread

def whatsapp_thread(lead, limit=40):
    """The conversation with this person in the WhatsApp CRM, oldest first, for the lead page.
    Reading only: nothing is created there. {'messages': [...], 'url': inbox link} or {'error'}."""
    from app.services import wacrm
    if not wacrm.enabled():
        return {'error': 'The WhatsApp CRM is not connected on this server.'}
    person = lead.person
    try:
        if not person.wacrm_contact_id and person.phone:
            person.wacrm_contact_id = wacrm.find_contact(person.phone)
        if not person.wacrm_conversation_id and person.wacrm_contact_id:
            person.wacrm_conversation_id = wacrm.conversation_for(person.wacrm_contact_id)
        db.session.commit()
        if not person.wacrm_conversation_id:
            return {'messages': [], 'url': None}
        msgs = wacrm.conversation_messages(person.wacrm_conversation_id, limit=limit)
    except wacrm.WacrmError as exc:
        db.session.rollback()
        return {'error': str(exc)}
    return {'messages': list(reversed(msgs)), 'url': wacrm.inbox_url(person.wacrm_conversation_id)}


def run_sla_alerts(now=None, limit=500):
    """Tell the owner (or the admins, when nobody owns it) about a lead that has sat in its stage
    longer than the stage allows -- once per stage; moving it clears the mark."""
    from app.services import cs_access, notify
    now = now or datetime.utcnow()
    rows = (CrmLead.query.join(CrmStage, CrmLead.stage_id == CrmStage.id)
            .filter(CrmLead.status == 'open', CrmStage.sla_hours > 0, CrmLead.sla_alerted_at.is_(None),
                    CrmLead.entered_stage_at.isnot(None))
            .order_by(CrmLead.entered_stage_at).limit(limit).all())
    sent = 0
    admins = None
    for lead in rows:
        limit_h = lead.stage.sla_hours
        if lead.entered_stage_at + timedelta(hours=limit_h) > now:
            continue
        waited = int((now - lead.entered_stage_at).total_seconds() // 3600)
        if lead.owner_id:
            targets = [lead.owner_id]
        else:
            if admins is None:
                admins = [u.id for u in User.query.filter(User.is_admin.is_(True), User.is_active.is_(True))]
            targets = admins
        for uid in targets:
            notify.push(uid, 'crm_stuck', title='Waiting too long: %s' % lead.person.display_name,
                        body='In "%s" for %d hours (the limit is %d).' % (lead.stage.name, waited, limit_h),
                        link=_lead_link(lead))
        lead.sla_alerted_at = now
        sent += 1
    db.session.commit()
    return {'crm_stuck_alerts': sent}


# ======================================================================================= instagram / facebook

SOCIAL_ID = {'instagram': 'ig_id', 'facebook': 'fb_psid'}


def social_reply_channels(lead):
    """Where a reply can go from here: the Meta channels this person has written to us on."""
    from app.services import meta
    if not meta.enabled():
        return []
    return [ch for ch, kind in SOCIAL_ID.items() if lead.person.identity(kind)]


def send_social(lead, channel, text, user=None, task=None, code=None):
    """Answer on Instagram or Messenger through the Page. Raises meta.MetaError with a sentence a
    person can act on when Meta says no (usually: their last message is over 24 hours old)."""
    from app.services import meta
    rid = lead.person.identity(SOCIAL_ID.get(channel, ''))
    if not rid:
        raise meta.MetaError('They have not written to us on %s, and Meta lets a business reply only.'
                             % channel.capitalize())
    mid = meta.send_text(rid, text)
    log_touch(lead, channel, 'out', body=text, code=task.code if task else code, user=user, status='sent',
              external_id=mid)
    if task is not None and task.status == 'open':
        complete_task(task, user=user)
    db.session.commit()
    return {'mode': 'sent'}


def record_social(ev):
    """One Instagram / Facebook message or comment (meta.parse_events): a reply on the person's
    lead, or a new lead under the "instagram" / "facebook" source. Returns the lead or None."""
    from app.services import meta
    if ev.get('external_id') and CrmTouchpoint.query.filter_by(external_id=ev['external_id']).first():
        return None
    channel, kind = ev['channel'], SOCIAL_ID[ev['channel']]
    text = ev['text'] if ev['kind'] == 'message' else 'Comment: %s' % ev['text']
    idents = [(kind, ev['sender_id'])]
    person = find_person(identities=idents)
    name, username = ev.get('name'), ev.get('username')
    if person is None:
        prof = meta.profile(ev['sender_id'], channel) if not (name or username) else {}
        name, username = name or prof.get('name'), username or prof.get('username')
        if username and channel == 'instagram':
            idents.append(('instagram', username))
        person = find_person(identities=[(k, clean_identity(k, v)) for k, v in idents])
    if person is not None:
        for k, v in idents:
            v = clean_identity(k, v)
            if v and not person.identity(k) and not CrmIdentity.query.filter_by(kind=k, value=v).first():
                person.identities.append(CrmIdentity(kind=k, value=v))
        lead = next((l for l in person.leads if l.status == 'open'), None) or (person.leads[0] if person.leads else None)
        if lead is not None:
            record_reply(lead, text, channel=channel, external_id=ev.get('external_id'))
            db.session.commit()
            return lead
    return capture(channel, name=name, identities=idents, message=text, channel=channel, utm={},
                   external_id=ev.get('external_id'))


# ======================================================================================= numbers

def board(pipeline, owner_id=None, q=None, limit_per_stage=60):
    """Open leads of a pipeline by stage, newest activity first, for the board."""
    query = CrmLead.query.filter(CrmLead.pipeline_id == pipeline.id)
    if owner_id == 'none':
        query = query.filter(CrmLead.owner_id.is_(None))
    elif owner_id:
        query = query.filter(CrmLead.owner_id == owner_id)
    if q:
        like = '%%%s%%' % q.strip()
        query = query.join(CrmPerson).filter(or_(CrmPerson.name.ilike(like), CrmPerson.phone.ilike(like),
                                                 CrmPerson.email.ilike(like)))
    columns = []
    for st in pipeline.stages:
        sq = query.filter(CrmLead.stage_id == st.id)
        if st.kind != 'open':
            # finished leads: the recent ones only; the board is for work in progress
            sq = sq.filter(CrmLead.closed_at >= datetime.utcnow() - timedelta(days=30))
        total = sq.count()
        leads = sq.order_by(CrmLead.last_activity_at.desc()).limit(limit_per_stage).all()
        columns.append({'stage': st, 'leads': leads, 'total': total})
    return columns


def insights(days=30):
    since = datetime.utcnow() - timedelta(days=days)
    new_by_source = (db.session.query(CrmSource.name, func.count(CrmLead.id))
                     .join(CrmLead, CrmLead.source_id == CrmSource.id)
                     .filter(CrmLead.created_at >= since)
                     .group_by(CrmSource.name).order_by(func.count(CrmLead.id).desc()).all())
    by_product = dict(db.session.query(CrmLead.product, func.count(CrmLead.id))
                      .filter(CrmLead.created_at >= since).group_by(CrmLead.product).all())
    won = CrmLead.query.filter(CrmLead.status == 'won', CrmLead.closed_at >= since).count()
    lost = CrmLead.query.filter(CrmLead.status == 'lost', CrmLead.closed_at >= since).count()
    created = CrmLead.query.filter(CrmLead.created_at >= since).count()
    reasons = (db.session.query(CrmLead.fallout_reason, func.count(CrmLead.id))
               .filter(CrmLead.status == 'lost', CrmLead.closed_at >= since,
                       CrmLead.fallout_reason.isnot(None))
               .group_by(CrmLead.fallout_reason).order_by(func.count(CrmLead.id).desc()).all())
    moves = (db.session.query(CrmStage.name, CrmPipeline.name, func.count(CrmStageChange.id))
             .join(CrmStage, CrmStage.id == CrmStageChange.to_stage_id)
             .join(CrmPipeline, CrmPipeline.id == CrmStage.pipeline_id)
             .filter(CrmStageChange.created_at >= since)
             .group_by(CrmStage.name, CrmPipeline.name, CrmStage.position)
             .order_by(CrmPipeline.name, CrmStage.position).all())
    owners = (db.session.query(User.username, func.count(CrmTask.id))
              .join(CrmTask, CrmTask.done_by_id == User.id)
              .filter(CrmTask.status == 'done', CrmTask.done_at >= since)
              .group_by(User.username).order_by(func.count(CrmTask.id).desc()).all())
    overdue = CrmTask.query.filter(CrmTask.status == 'open', CrmTask.due_at < datetime.utcnow()).count()
    messages = CrmTouchpoint.query.filter(CrmTouchpoint.direction == 'out',
                                          CrmTouchpoint.created_at >= since).count()
    replies = CrmTouchpoint.query.filter(CrmTouchpoint.direction == 'in',
                                         CrmTouchpoint.channel != 'form',
                                         CrmTouchpoint.created_at >= since).count()
    return {'days': days, 'created': created, 'won': won, 'lost': lost, 'overdue': overdue,
            'messages': messages, 'replies': replies, 'new_by_source': new_by_source,
            'by_product': by_product, 'reasons': reasons, 'moves': moves, 'owners': owners}


# ======================================================================================= where a lead is

def stage_role(stage):
    """cold / prospect / pipeline / customer / lost -- the pipeline symbol shown everywhere."""
    if stage is None:
        return 'new'
    if stage.kind == 'won':
        return 'customer'
    if stage.kind == 'lost':
        return 'lost'
    stages = sorted(stage.pipeline.stages, key=lambda s: s.position) if stage.pipeline else [stage]
    opens = [s for s in stages if s.kind == 'open']
    reply = next((s for s in stages if s.on_reply), None)
    if opens and stage.id == opens[0].id:
        return 'cold'
    if reply is not None and stage.id == reply.id:
        return 'prospect'
    if reply is not None and stage.position < reply.position:
        return 'cold'
    return 'pipeline'


ROLE_LABELS = {'new': 'Not routed', 'cold': 'Cold lead', 'prospect': 'Prospect', 'pipeline': 'Pipeline',
               'customer': 'Customer', 'lost': 'Fell out'}


# ======================================================================================= existing records -> leads

RECORD_KINDS = {
    'insurance_quote': ('insurance_quotes', 'Insurance quote'),
    'contact_message': ('contact_messages', 'Contact message'),
    'sahayak_booking': ('sahayak_bookings', 'Sahayak booking'),
    'trip': ('companion_requests', 'Trip post'),
    'user': ('users', 'Site account'),
}


def _record(kind, record_id):
    from app.models import CompanionRequest, ContactMessage, InsuranceQuote, SahayakBooking
    model = {'insurance_quote': InsuranceQuote, 'contact_message': ContactMessage,
             'sahayak_booking': SahayakBooking, 'trip': CompanionRequest, 'user': User}.get(kind)
    return db.session.get(model, record_id) if model else None


def lead_for_record(kind, record_id):
    ref_type = RECORD_KINDS.get(kind, (None,))[0]
    if not ref_type:
        return None
    return (CrmLead.query.filter_by(ref_type=ref_type, ref_id=record_id)
            .order_by(CrmLead.created_at.desc()).first())


def lead_from_record(kind, record_id, user=None):
    """Make a lead of something the site already has -- a quote, a contact message, a booking, a
    trip post, an account. Returns (lead, created). An existing lead for it is returned as it is."""
    existing = lead_for_record(kind, record_id)
    if existing is not None:
        return existing, False
    r = _record(kind, record_id)
    if r is None:
        return None, False
    by = getattr(user, 'id', None)
    common = dict(utm={}, created_by_id=by, notify=False)
    if kind == 'insurance_quote':
        ages = ', '.join(str(t.get('age')) for t in (r.travellers or []) if isinstance(t, dict))
        lead = capture('ti-quote', name=r.name, phone=r.phone, email=r.email, product='TI', user_id=r.user_id,
                       departure_date=r.start_date, ends_on=r.end_date, ref=('insurance_quotes', r.id),
                       details={'plan': r.insurance_type, 'travellers_ages': ages, 'citizenship': r.citizenship,
                                'destination': r.destination, 'quote': r.status}, **common)
    elif kind == 'contact_message':
        text = r.message or ''
        key = ('sh-apply' if text.startswith('Sahayak application') else
               'ti-support' if text.startswith('Support request from the /travel-insurance') else
               'ti-expert' if text.startswith('Travel insurance enquiry from the /travel-insurance') else
               'contact-%s' % (r.topic or 'general'))
        lead = capture(key, name=r.name, phone=r.phone, email=r.email, message=text, user_id=r.user_id,
                       product={'companion': 'TC', 'insurance': 'TI', 'sahayak': 'SH'}.get(r.topic, 'GEN'),
                       ref=('contact_messages', r.id), **common)
    elif kind == 'sahayak_booking':
        lead = capture('sh-booking', name=r.contact_name or r.patient_name, phone=r.phone, email=r.email,
                       product='SH', user_id=r.user_id, ref=('sahayak_bookings', r.id),
                       details={'service': r.service_name, 'for': r.patient_name, 'age': r.patient_age,
                                'pin_code': r.pincode, 'address': r.address}, **common)
    elif kind == 'trip':
        lead = capture_trip(r, 'tc-trip-post' if r.user_id else 'tc-cs-post', **common)
    else:  # a site account
        lead = capture('site-account', name=r.full_name, phone=r.phone, email=r.email, user_id=r.id,
                       ref=('users', r.id), **common)
    return lead, lead is not None


def search_records(q, limit=8):
    """Things the site already knows about somebody, for "Add a lead -> From existing data"."""
    from app.models import CompanionRequest, ContactMessage, InsuranceQuote, SahayakBooking
    q = (q or '').strip()
    if len(q) < 2:
        return []
    like = '%%%s%%' % q
    digits = re.sub(r'\D', '', q)
    dlike = '%%%s%%' % digits[-9:] if len(digits) >= 5 else None

    def ph(col):
        return [col.ilike(dlike)] if dlike else []
    out = []
    for r in (InsuranceQuote.query.filter(or_(InsuranceQuote.email.ilike(like), InsuranceQuote.name.ilike(like),
                                              *ph(InsuranceQuote.phone)))
              .order_by(InsuranceQuote.created_at.desc()).limit(limit)):
        out.append(('insurance_quote', r.id, r.name or r.email, '%s · %s' % (r.email, r.phone or ''), r.created_at,
                    'Insurance quote for %s' % r.start_date.strftime('%d %b %Y') if r.start_date else 'Insurance quote'))
    for r in (ContactMessage.query.filter(or_(ContactMessage.email.ilike(like), ContactMessage.name.ilike(like),
                                              *ph(ContactMessage.phone)))
              .order_by(ContactMessage.created_at.desc()).limit(limit)):
        out.append(('contact_message', r.id, r.name, '%s · %s' % (r.email, r.phone or ''), r.created_at,
                    (r.message or '')[:90]))
    for r in (SahayakBooking.query.filter(or_(SahayakBooking.patient_name.ilike(like),
                                              SahayakBooking.contact_name.ilike(like),
                                              SahayakBooking.email.ilike(like), *ph(SahayakBooking.phone)))
              .order_by(SahayakBooking.created_at.desc()).limit(limit)):
        out.append(('sahayak_booking', r.id, r.contact_name or r.patient_name, r.phone or '', r.created_at,
                    'Sahayak: %s for %s' % (r.service_name, r.patient_name)))
    for r in (CompanionRequest.query.filter(or_(CompanionRequest.poster_name.ilike(like),
                                                CompanionRequest.traveler_name.ilike(like)))
              .order_by(CompanionRequest.created_at.desc()).limit(limit)):
        out.append(('trip', r.id, r.poster_name or r.traveler_name or 'Trip #%d' % r.id, r.route_display,
                    r.created_at, 'Trip post #%d, %s' % (r.id, r.from_date.strftime('%d %b %Y') if r.from_date else '')))
    for r in (User.query.filter(or_(User.email.ilike(like), User.username.ilike(like), User.first_name.ilike(like),
                                    User.last_name.ilike(like), *ph(User.phone)))
              .order_by(User.id.desc()).limit(limit)):
        out.append(('user', r.id, r.full_name, '%s · %s' % (r.email, r.phone or ''), r.created_at if hasattr(r, 'created_at') else None,
                    'Site account'))
    rows = []
    for kind, rid, title, sub, when, what in out:
        rows.append({'kind': kind, 'id': rid, 'title': title or '—', 'sub': sub, 'when': when, 'what': what,
                     'label': RECORD_KINDS[kind][1], 'lead': lead_for_record(kind, rid)})
    rows.sort(key=lambda r: r['when'] or datetime.min, reverse=True)
    return rows


# ======================================================================================= undo, reopen, remove

def undo_last_move(lead, user=None):
    """Put the lead back where it was before its last move (a slip of the mouse, a wrong drop).
    Returns the stage it went back to, or None when there is nothing to undo."""
    last = (CrmStageChange.query.filter(CrmStageChange.lead_id == lead.id, CrmStageChange.from_stage_id.isnot(None))
            .order_by(CrmStageChange.created_at.desc(), CrmStageChange.id.desc()).first())
    if last is None or last.to_stage_id != lead.stage_id or last.from_stage is None:
        return None
    back = last.from_stage
    move_stage(lead, back, user=user, reason='Undone: back from %s' % (lead.stage.name if lead.stage else '?'))
    db.session.commit()
    return back


def reopen(lead, user=None):
    """A won or lost lead back to work, in the open stage it was in before it closed."""
    if lead.status == 'open' or lead.pipeline is None:
        return None
    prev = (CrmStageChange.query.filter(CrmStageChange.lead_id == lead.id, CrmStageChange.to_stage_id == lead.stage_id)
            .order_by(CrmStageChange.created_at.desc(), CrmStageChange.id.desc()).first())
    back = prev.from_stage if prev is not None and prev.from_stage is not None and prev.from_stage.kind == 'open' \
        else lead.pipeline.first_stage
    move_stage(lead, back, user=user, reason='Reopened')
    db.session.commit()
    return back


def can_remove(lead, user):
    return bool(user and (user.is_admin or lead.created_by_id == user.id or lead.owner_id == user.id))


def remove_lead(lead, user=None):
    """Take a lead out of the CRM (added by mistake). Its person goes too when nothing else of
    theirs is left. The record it came from on the site is not touched."""
    from app.models import ActivityEvent
    person = lead.person
    name = person.display_name if person else '?'
    lead_id = lead.id
    db.session.delete(lead)
    db.session.flush()
    if person is not None and not CrmLead.query.filter_by(person_id=person.id).first():
        CrmTouchpoint.query.filter_by(person_id=person.id).delete(synchronize_session=False)
        db.session.delete(person)
    try:
        ActivityEvent.log('crm_lead_removed', actor=user, lead_id=lead_id, name=name)
    except Exception:          # noqa: BLE001 -- the log is a courtesy
        pass
    db.session.commit()
    return name
