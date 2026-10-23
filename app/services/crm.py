"""The Sales CRM: one record per person, one lead per product, and the next step for each lead.

How a lead moves, in one place:

  capture()      every form, pop-up, chat and import calls this with its lead-source key. The source
                 (set up on screen, Sales CRM -> Setup) says which product and pipeline the lead
                 starts in and who owns it; the pipeline comes first, then the same person asking
                 again in that pipeline is the same lead. An unknown key is not an error: the lead is kept, and
                 the source appears as "unrouted" for an admin to set up once.
  plan_next()    puts the next playbook step of the lead's stage on someone's list as a task, due by
                 its trigger -- hours after the last step, or days before / after a date of the lead
                 (the trip, the cover ending, a date detail). A missing date plans nothing: it waits.
  move_stage()   records who moved it and why, closes the old stage's open task, and plans the
                 first step of the new one.
  record_reply() a reply from the person. Out of a pipeline's first stage it moves the lead to the
                 stage marked "a reply moves here" -- cold lead becomes prospect without anyone
                 having to drag a card.
  mark_wa_due()  every change the WhatsApp CRM should know (a new or repeat enquiry, a stage, an
                 owner, a name, a number) only marks the person. Straight after the save a
                 background thread brings their contact into step (run_wa_sync), and the jobs
                 runner retries whoever is still marked. Off (Set-up → WhatsApp) marks nothing
                 and writes nothing. Bulk marks (the backfill, a source's changed tags) are quiet:
                 the tags go without starting the WhatsApp CRM's tag automations.
  record_whatsapp_in()  a WhatsApp message from them (the webhook, or the jobs runner catching up
                 on one it missed) on the lead we last wrote to; a new lead for somebody new or
                 long gone; STOP and the like opt them out. A closed lead is never reopened.

Nothing here commits halfway: each public function leaves the session flushed and commits once.
capture_safely() is what the public forms call, so a CRM fault can never cost somebody the
enquiry they just sent.
"""
import hashlib
import json
import logging
import re
import threading
from contextlib import contextmanager
from datetime import datetime, date, time, timedelta
from time import monotonic
from urllib.parse import quote

from flask import current_app, has_app_context, request
from sqlalchemy import and_, case, event, false, func, or_, select
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.orm.exc import ObjectDeletedError

from app import db
from app.models import (CrmAnswer, CrmField, CrmIdentity, CrmLead, CrmPerson, CrmPipeline, CrmPlaybookStep,
                        CrmSource, CrmStage, CrmStageChange, CrmTask, CrmTouchpoint, User,
                        CRM_CHANNEL_LABELS, CRM_CHECK_CHANNELS, CRM_DATE_FIELDS, CRM_LEGACY_TRIGGERS, ROLE_MEANS)
from app.services import crm_money, crm_products

log = logging.getLogger(__name__)

IST = timedelta(hours=5, minutes=30)
SOURCE_KEY_RE = re.compile(r'^[a-z0-9][a-z0-9-]{1,58}$')
UTM_COOKIE = 'nps_src'
UTM_KEYS = ('utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content', 'gclid',
            'fbclid', 'referrer', 'landing')
NO_ANSWER_LIMIT = 3          # CL #3: the third unanswered call is the last
SETTINGS_KEY = 'crm'
WA_MODES = {'off': 'Not yet', 'contacts': 'Keep contacts in step', 'send': 'Keep in step and send follow-ups'}
WA_MODE_SAYS = {
    'off': 'Nothing is written to WhatsApp. Leads stay here only.',
    'contacts': ('Every lead becomes a WhatsApp contact with its stage tag, and its chat goes to whoever looks '
                 'after it. Nothing is sent by itself; people send from the lead page or WhatsApp chats.'),
    'send': ('As above, and follow-ups marked “Goes by itself” are sent when due (only those due in the last '
             '24 hours; older ones wait for a click).')}
WA_FIRST_OK_LABEL = 'Automatic first messages need their OK'
WA_FIRST_OK_SAYS = 'Waits until they tick “Send my quote and updates on WhatsApp” or write to us first.'


# ======================================================================================= settings

def crm_settings():
    """The CRM's own switches, set on screen (Set-up → WhatsApp)."""
    from app.services import settings
    s = settings.get_setting(SETTINGS_KEY) or {}
    rows = check_rows(s.get('check_channels'))
    return {'whatsapp_mode': s.get('whatsapp_mode') if s.get('whatsapp_mode') in WA_MODES else 'off',
            # check_rows: every inbox on the half-hourly check; check_channels: the names a person ticks
            # (an inbox that ticks itself right now is left out)
            'check_rows': rows,
            'check_channels': [r['name'] for r in rows if not check_ticks_itself(r)],
            # an automatic step that would be somebody's first WhatsApp message waits for a click unless
            # they agreed (a form's tick) or wrote to us -- Set-up -> Connect; on unless switched off
            'wa_first_needs_ok': s.get('wa_first_needs_ok') is not False,
            # the waiting bell goes after this many minutes of a customer waiting on us
            'waiting_alert_minutes': _minutes(s.get('waiting_alert_minutes'))}


# an old list of names read as inbox rows: the USA WhatsApp inbox lives on a phone, so it is renamed
CHECK_RENAMED = {'USA WhatsApp': 'USA WhatsApp (on the phone)'}
# lower name -> (source key, ticks itself); None = the WhatsApp source (config WACRM_SOURCE_KEY)
CHECK_GUESS = {'ind whatsapp': (None, True), 'usa whatsapp': ('wa-usa', False), 'tawk': ('tawk', False),
               'fb messenger': ('meta', False), 'instagram messenger': ('meta', False),
               'telegram': ('telegram', False), 'india call': ('company-call', False), 'usa call': ('usa-call', False)}


def wa_replies_linked():
    """WhatsApp replies reach us (the replies link is set up), so we know who is waiting there."""
    from app.services import wacrm
    return bool(wacrm.enabled() and _wa_webhook_saved().get('id'))


def check_ticks_itself(row):
    """An inbox row that ticks itself right now: automatic, the WhatsApp source, and replies arriving."""
    return bool(row.get('auto') and row.get('source_key') == current_app.config.get('WACRM_SOURCE_KEY', 'wa-india')
                and wa_replies_linked())


def check_rows(raw=None):
    """The inboxes to check as rows [{name, source_key, auto}], from the stored rows or an old list of
    names. Names are unique ignoring case, at most 30."""
    wa_key = current_app.config.get('WACRM_SOURCE_KEY', 'wa-india') if has_app_context() else 'wa-india'
    out, seen = [], set()
    for item in (raw if raw else CRM_CHECK_CHANNELS):
        if isinstance(item, dict):
            name = str(item.get('name') or '').strip()[:40]
            src, auto = (item.get('source_key') or None), bool(item.get('auto'))
        else:
            name = str(item or '').strip()
            guess = CHECK_GUESS.get(name.lower(), (None, False))
            name = CHECK_RENAMED.get(name, name)[:40]
            src = wa_key if name.lower() == 'ind whatsapp' else guess[0]
            auto = guess[1]
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        out.append({'name': name, 'source_key': src, 'auto': auto})
    return out[:30]


def _minutes(v):
    """Minutes for the waiting bell: a whole number from 5 to 1440; the default when missing or odd."""
    try:
        return max(5, min(1440, int(v)))
    except (TypeError, ValueError):
        return WAITING_ALERT_MINUTES


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


def wa_writes_on():
    """Whether the portal may write to the WhatsApp CRM: contacts, chats, tags, quick replies,
    templates, tag rules. Only on "Keep contacts in step" (or "Keep in step and send follow-ups"), with it connected.
    Reading is always allowed. The team sync (members, sign-in, workspace) does not ask this."""
    from app.services import wacrm
    return wa_mode() in ('contacts', 'send') and wacrm.enabled()


def wa_team_on():
    """The WhatsApp CRM's portal link can be used for the CRM being worked on: it is set up, and this is the workspace
    WhatsApp is linked to (another workspace's leads have WhatsApp off: services/crm_scope)."""
    from app.services import crm_scope, wacrm_team
    return wacrm_team.enabled() and crm_scope.wa_here()


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
        codes = set(crm_products.codes())
        for key, name, product, reasons, stages in d.PIPELINES:
            p = CrmPipeline(key=key, name=name, product=product, fallout_reasons=reasons,
                            catch_all=key in d.CATCH_ALL)
            db.session.add(p)
            for pos, stage_def in enumerate(stages):
                skey, sname, kind, on_reply, sla, steps = stage_def[:6]
                st = CrmStage(key=skey, name=sname, kind=kind, on_reply=on_reply, sla_hours=sla,
                              position=pos)
                if skey in d.MILESTONES:
                    st.button_label, st.button_code = d.MILESTONES[skey]
                p.stages.append(st)
                for spos, (code, title, channel, trig, val, auto, body) in enumerate(steps):
                    trig, field, val = d.seed_trigger(trig, val)
                    st.steps.append(CrmPlaybookStep(code=code, title=title, channel=channel,
                                                    trigger=trig, trigger_field=field, trigger_value=val,
                                                    auto=auto, body=body, position=spos,
                                                    kind=d.step_kind(code, codes)))
                if len(stage_def) > 6 and stage_def[6]:
                    automations.append((p, st, stage_def[6]))
            for st in p.stages:
                st.means = ROLE_MEANS[st.derived_role()]
        db.session.flush()
        for p, st, (akind, adays, to_key, reason) in automations:
            target = next((s for s in p.stages if s.key == to_key), None)
            if target is not None:
                akind, afield = d.seed_auto(akind)
                st.auto_kind, st.auto_field, st.auto_days, st.auto_to, st.auto_reason = (
                    akind, afield, adays, target, reason)
        changed = True
    # a seed whose title a quick reply already has is skipped: titles are unique (WhatsApp matches by title)
    titles = {(t or '').strip().lower() for (t,) in db.session.query(CrmAnswer.title).all()}
    if not db.session.query(CrmAnswer.id).filter(CrmAnswer.code.is_(None)).first():
        for product, title, keywords, body in d.ANSWERS:
            if title.strip().lower() not in titles:
                titles.add(title.strip().lower())
                db.session.add(CrmAnswer(product=product, title=title, keywords=keywords, body=body))
        changed = True
    if not db.session.query(CrmAnswer.id).filter(CrmAnswer.code.isnot(None)).first():
        for product, code, title, body in d.QUICK_MESSAGES:
            if title.strip().lower() not in titles:
                titles.add(title.strip().lower())
                db.session.add(CrmAnswer(product=product, code=code, title=title, body=body))
        changed = True
    if changed:
        db.session.flush()
    changed = crm_products.ensure_seeded() or changed
    have = {k for (k,) in db.session.query(CrmSource.key).all()}
    pipes = {p.key: p for p in CrmPipeline.query.all()}
    for key, name, kind, product, pkey, pages, status in d.SOURCES:
        if key not in have:
            db.session.add(CrmSource(key=key, name=name, kind=kind, product=product, pages=pages,
                                     pipeline=pipes.get(pkey), status=status, built_in=True))
            changed = True
    if changed:
        db.session.flush()
    from app.services import crm_sources
    changed = crm_sources.tidy() or changed      # the old sources' leads onto the list, once
    if changed:
        db.session.commit()


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
    """Who may own a lead from `src`: its Workspace team ({'team_id'}), or the people ticked, else every
    agent whose console has the CRM, else an admin."""
    from app.models import WorkspaceTeam
    from app.services import crm_scope, cs_access
    # only people of the workspace the lead comes into (the source's)
    wid = src.workspace_id if src is not None and src.workspace_id is not None else crm_scope.stamp_id()
    staff = crm_scope.in_workspace(cs_access.recipients('crm_board', limit=None), wid)
    team = src.team if src else None
    ids = set()
    if isinstance(team, dict):
        tid = team.get('team_id')
        t = db.session.get(WorkspaceTeam, int(tid)) if str(tid or '').isdigit() else None
        ids = {u.id for u in t.users} if t is not None else set()
    elif team:
        ids = {int(i) for i in team if str(i).isdigit()}
    users = [u for u in staff if u.id in ids] if ids else []
    if not users:
        users = [u for u in staff if not u.is_admin]       # nobody of theirs can take it: anyone in sales
    return users or [u for u in staff if u.is_admin]


def assign_owner(src):
    """Who gets a new lead from this source: see services/crm_assign (fewest open leads, or in turn;
    nobody who is away). Returns the user, or None."""
    from app.services import crm_assign
    return crm_assign.choose(src)[0]


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


def pipeline_for(src, product, start_stage=None):
    """(pipeline, start stage) for a new enquiry from this source about this product: the source's pipeline;
    a catch-all one passes a lead with a known product on to that product's own pipeline; a pipeline not
    taking new leads passes them on to the product's pipeline (else the catch-all) and keeps them only when
    no other would. An importer's start stage says it outright."""
    pipe = src.pipeline if src.status != 'unrouted' else None
    if start_stage is None and pipe is not None and pipe.catch_all and product != pipe.product:
        better = crm_products.default_pipeline(product)
        if better is not None and not better.catch_all:
            pipe, start_stage = better, better.first_stage
    if start_stage is None and pipe is not None and not pipe.is_active:
        better = crm_products.default_pipeline(product)
        if better is not None and better.id != pipe.id and better.is_active:
            pipe, start_stage = better, better.first_stage
    if start_stage is not None:
        pipe = start_stage.pipeline
    return pipe, start_stage


def start_waiting_leads(src, user=None):
    """Leads that waited while this source was unrouted start its pipeline now (the first stage's follow-up
    is planned, an owner is chosen). No commit. How many started."""
    if src.pipeline is None:
        return 0
    waiting = CrmLead.query.filter(CrmLead.source_id == src.id, CrmLead.pipeline_id.is_(None),
                                   CrmLead.status == 'open').all()
    for lead in waiting:
        set_pipeline(lead, src.pipeline, user=user)
        if not lead.owner_id:
            owner = assign_owner(src)
            set_owner(lead, owner.id if owner is not None else None, by=user)
    return len(waiting)


class DoNotContact(Exception):
    """capture(refuse_dnc=True) for somebody erased at their request: nothing was saved."""


CONSENT_NOTE = 'Agreed to WhatsApp messages (%s)'
OFFERS_NOTE = 'OK to send offers (%s)'


def ticked(value):
    """A form's tick box as True / False: from a form post ('on', '1') or JSON (true)."""
    return value is True or str(value or '').strip().lower() in ('1', 'on', 'true', 'yes')


def capture(source_key, *, workspace_id=None, **kw):
    """Record an enquiry as a lead (see _capture). Which workspace's CRM it goes to (Sales CRM 2.0, run 5a): an
    explicit `workspace_id`, else the `person`'s, else the one being worked in (a signed-in staff member, a job, the
    WhatsApp webhook), else -- a public form, nobody signed in -- the SOURCE decides (crm_scope.source_workspace)."""
    from app.services import crm_scope
    with crm_scope.for_capture(source_key, person=kw.get('person'), workspace_id=workspace_id):
        return _capture(source_key, **kw)


def _capture(source_key, *, name=None, phone=None, phone_cc=None, email=None, product=None,
             details=None, message=None, ref=None, utm=None, departure_date=None, consent=None,
             user_id=None, channel='form', when=None, identities=None, ends_on=None,
             created_by_id=None, start_stage=None, plan=True, notify=True, temperature=None,
             fallout_reason=None, external_id=None, sync=True, imported=False, likelihood=None,
             person=None, note=None, refuse_dnc=False, consent_from=None, offers_consent=False, assign=None):
    """Record an enquiry as a lead. Returns the lead, or None when there is nobody to reach.

    The same person asking again within the source's window, about anything that goes to the same
    pipeline, is the same lead: the new enquiry is added to its timeline rather than starting a
    second card.

    `identities` reach somebody without a phone or e-mail: [('instagram', 'handle'), ...].
    The importers pass `start_stage` (where the lead already is), plan=False, notify=False and
    sync=False (nothing is marked for the WhatsApp CRM; the backfill brings open ones in later, a
    few at a time).
    `person`: somebody already here (a WhatsApp message long after their last lead closed): no lookup.
    `note`: a lead made by hand from somebody's WhatsApp chat: this note (by `created_by_id`) is
    logged instead of a message from them, so it never opens WhatsApp's 24 hours or counts as a reply.
    `refuse_dnc`: an importer (raises DoNotContact for an erased person); otherwise a match is an enquiry
    they made themselves and clears the entry. `consent_from`: the form, for the note when `consent` is new.
    `offers_consent`: the form's own "OK to send offers" tick (never the WhatsApp tick, `consent`).
    `assign`: who a NEW lead goes to, instead of the source's way (crm_assign.MODES): 'none', 'fewest' or
    'round_robin'. By default a source gives it to nobody: it waits to be taken.
    """
    ensure_defaults()
    from app.services import crm_sources
    e164 = normalise_phone(phone, phone_cc)
    key = (source_key or '').strip().lower()
    if not SOURCE_KEY_RE.match(key):
        key = 'unknown'
    key = crm_sources.canonical(key, e164 or (person.phone if person is not None else None))   # an old key: its item
    src = source(key)
    new_source = src is None
    code = crm_products.by_code(product)
    email = (email or '').strip().lower() or None
    if email and ('@' not in email or email.startswith('no-email@')):
        email = None
    identities = [(k, clean_identity(k, v)) for k, v in (identities or [])]
    identities = [(k, v) for k, v in identities if v]
    hits = []
    if person is None:
        if not e164 and not email and not identities:
            return None
        if e164 or email:
            from app.services import crm_people
            hits = crm_people.dnc_find(e164, email)
            if hits and refuse_dnc:
                raise DoNotContact()
    if new_source:
        # a page nobody has set up yet: keep the lead, and let an admin choose its pipeline once
        src = CrmSource(key=key, name=key.replace('-', ' ').capitalize(), kind='api' if channel == 'form' else 'chat',
                        product=code.code if code else crm_products.general_code(), status='unrouted')
        db.session.add(src)
        db.session.flush()

    consent_new = False
    if person is None:
        person = upsert_person(e164, email, (name or '').strip() or None, user_id=user_id, consent=None,
                               identities=identities)
    if consent:
        consent_new = not person.consent_whatsapp
        person.consent_whatsapp = True
    if hits and not refuse_dnc:
        from app.services import crm_people
        crm_people.dnc_forget(hits, source=key)

    product = code.code if code else src.product
    now = when or datetime.utcnow()
    details = {k: v for k, v in (details or {}).items() if v not in (None, '', [], {})}
    utm = utm if utm is not None else utm_from_request()

    # 1. which pipeline: the source's; a catch-all source with a known product passes it on to that
    #    product's own pipeline; an importer's start stage says it outright
    pipe, start_stage = pipeline_for(src, product, start_stage)
    # 2. the same person asking again within the source's days, in THIS pipeline, is the same lead
    since = now - timedelta(days=max(src.dedupe_days or 0, 0))
    q = CrmLead.query.filter(CrmLead.person_id == person.id, CrmLead.status == 'open',
                             CrmLead.last_activity_at >= since)
    q = (q.filter(CrmLead.pipeline_id == pipe.id) if pipe is not None
         else q.filter(CrmLead.pipeline_id.is_(None), CrmLead.product == product))
    lead = q.order_by(CrmLead.last_activity_at.desc()).first()
    created = lead is None
    if created:
        stage = start_stage or (pipe.first_stage if pipe else None)
        from app.services import crm_assign
        owner, owner_note = crm_assign.choose(src, mode=assign)
        lead = CrmLead(person=person, product=product, source=src, pipeline=pipe, stage=stage,
                       status=stage.kind if stage else 'open',
                       owner=owner, details=details, utm=utm or None,
                       departure_date=departure_date, ends_on=ends_on, created_at=now,
                       last_activity_at=now, entered_stage_at=now, created_by_id=created_by_id,
                       temperature=temperature, likelihood=likelihood, imported=imported,
                       # a rating that came with it (the sales sheet's colour) is a person's: scoring leaves it
                       likelihood_manual=bool(likelihood))
        if stage is not None and stage.kind != 'open':
            lead.closed_at = now
            lead.fallout_reason = fallout_reason if stage.kind == 'lost' else None
        if ref:
            lead.ref_type, lead.ref_id = ref[0], ref[1]
        db.session.add(lead)
        db.session.flush()
        crm_money.apply_new_lead_defaults(lead)        # the product's usual price and a close date (not for importers)
        if lead.stage:
            db.session.add(CrmStageChange(lead=lead, from_stage_id=None, to_stage_id=lead.stage.id,
                                          reason='Came in from %s' % src.name, created_at=now))
        if owner_note:
            db.session.add(CrmTouchpoint(lead=lead, person_id=person.id, channel='note', direction='none',
                                         body=owner_note, created_at=now))
    else:
        lead.details = {**(lead.details or {}), **details}
        if departure_date and not lead.departure_date:
            lead.departure_date = departure_date
        if ends_on and not lead.ends_on:
            lead.ends_on = ends_on
        if utm and not lead.utm:
            lead.utm = utm
        lead.last_activity_at = max(lead.last_activity_at or now, now)
        # a general enquiry that now names a product (its own pipeline is this one: Gift Health in General)
        if pipe is not None and pipe.catch_all and lead.product == pipe.product and product != pipe.product:
            lead.product = product

    if note:
        db.session.add(CrmTouchpoint(lead=lead, person_id=person.id, channel='note', direction='none',
                                     body=note[:4000], agent_id=created_by_id, created_at=now))
    else:
        db.session.add(CrmTouchpoint(lead=lead, person_id=person.id, channel=channel, direction='in',
                                     body=_summary(details, message), code=None, created_at=now,
                                     external_id=external_id))
    if consent_new:
        db.session.add(CrmTouchpoint(lead=lead, person_id=person.id, channel='note', direction='none',
                                     body=CONSENT_NOTE % (consent_from or src.name), created_at=now))
    if offers_consent:
        from app.services import crm_consent
        if crm_consent.from_form(person, consent_from or src.name, at=now):
            db.session.add(CrmTouchpoint(lead=lead, person_id=person.id, channel='note', direction='none',
                                         body=OFFERS_NOTE % (consent_from or src.name), created_at=now))
    src.lead_count = (src.lead_count or 0) + 1
    src.last_lead_at = max(src.last_lead_at or now, now)
    if created and plan and src.status == 'live' and lead.status == 'open':
        plan_next(lead, base=max(now, datetime.utcnow()))
    if sync:
        # a new enquiry or a repeat one: their WhatsApp contact and its tags follow, after the save
        mark_wa_due(person)
    # automation rules ("a new lead comes in") and the lead's score: after the commit (services/crm_rules)
    from app.services import crm_rules, crm_scoring
    db.session.flush()
    if created and not imported:
        crm_rules.fire('lead_created', lead, 'created')
    crm_scoring.touched(lead)
    db.session.commit()
    if created and notify:
        _tell_owner(lead, new_source=new_source)
    return lead


MADE_FROM_CHAT = 'Made a lead from their WhatsApp chat.'


def _lead_link(lead):
    try:
        from flask import url_for
        return url_for('crm.lead', lead_id=lead.id)
    except Exception:          # noqa: BLE001 -- outside a request (CLI, jobs)
        return '/cs/crm/lead/%d' % lead.id


def _tell_owner(lead, new_source=False):
    """A bell notification for whoever got the lead; a lead given to nobody (the default) rings everybody who
    could take it -- the source's people, nobody away -- and the admins. And for the admins, the first time a
    page nobody has set up sends one. Best effort: a notification never undoes a lead."""
    from app.services import crm_assign, notify
    try:
        what = '%s · %s' % (crm_products.labels().get(lead.product, lead.product),
                            lead.source.name if lead.source else 'unknown source')
        if lead.owner_id:
            notify.push(lead.owner_id, 'crm_lead', title='New lead: %s' % lead.person.display_name,
                        body=what, link=_lead_link(lead))
        else:
            people = _owner_candidates(lead.source)
            away = crm_assign.away_ids([u.id for u in people])
            ids = {u.id for u in people if u.id not in away}
            ids |= {u.id for u in User.query.filter(User.is_admin.is_(True), User.is_active.is_(True)).all()}
            for uid in sorted(ids):
                notify.push(uid, 'crm_lead', title=UNOWNED_BELL, body=what, link=_lead_link(lead))
        if new_source:
            from app.services import cs_access
            for u in User.query.filter(User.is_admin.is_(True), User.is_active.is_(True)).all():
                notify.push(u.id, 'crm_source', title='A new lead source needs setting up',
                            body='"%s" sent its first lead. Choose its pipeline once in Set-up → Lead sources.'
                                 % lead.source.key, link='/admin/crm/sources')
        db.session.commit()
    except Exception:          # noqa: BLE001
        db.session.rollback()
        log.warning('CRM notification failed for lead %s', lead.id, exc_info=True)


def capture_safely(source_key, **kw):
    """capture() for the public forms: whatever goes wrong here, the enquiry is already saved."""
    try:
        return capture(source_key, **kw)
    except DoNotContact:
        raise              # an importer asked to be told; never raised for a form
    except Exception:        # noqa: BLE001 -- a CRM fault must never cost somebody their enquiry
        db.session.rollback()
        current_app.logger.exception('CRM capture failed for source %r', source_key)
        return None


def trip_reach(trip):
    """Who a trip post reaches: (name, phone, email, identities) -- its contact numbers, else the
    account that posted it."""
    phone = email = None
    identities = []
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
    return name, phone, email, identities


def open_trip_lead_of_poster(trip):
    """The open Travel Companion lead of whoever a post reaches, when the post itself is not a lead:
    capture() put the post on that lead (same person, same pipeline), so it is in the CRM already."""
    _, phone, email, identities = trip_reach(trip)
    if not (phone or email or identities):
        return None
    person = find_person(phone, email, [(k, clean_identity(k, v)) for k, v in identities])
    if person is None:
        return None
    return next((l for l in sorted(person.leads, key=lambda l: l.last_activity_at or datetime.min, reverse=True)
                 if l.status == 'open' and l.product == 'TC'), None)


def capture_trip(trip, source_key, user_id=None, **kw):
    """A trip post as a Travel Companion lead: who to reach (its contact numbers, else the account
    that posted it), the route and the date it leaves. Safe like capture_safely()."""
    try:
        name, phone, email, identities = trip_reach(trip)
        details = {'route': ' → '.join(x for x in (trip.flying_from, trip.destination) if x),
                   'they_are': (trip.role or '').replace('_', ' '),
                   'airline': ' '.join(x for x in (trip.airline, trip.flight_number) if x),
                   'post': '#%s (%s)' % (trip.id, trip.status)}
    except Exception:        # noqa: BLE001 -- see capture_safely
        current_app.logger.exception('CRM could not read trip %s', getattr(trip, 'id', None))
        return None
    # staff making a lead of the post (lead_from_record) pass themselves; a post coming in counts its own maker
    kw.setdefault('created_by_id', trip.created_by_id)
    return capture_safely(source_key, name=name, phone=phone, email=email, product='TC',
                          details=details, departure_date=trip.from_date, ends_on=trip.to_date,
                          ref=('companion_requests', trip.id), user_id=user_id or trip.user_id,
                          identities=identities, **kw)


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


def tag_prefix(lead):
    """The first part of the lead's stage tag: its pipeline's own label ("TI renewals") when it has
    one, else the lead's product code ("TI") -- what every pipeline used before U5, so no tag changed."""
    pipe = lead.pipeline
    label = (pipe.tag_label or '').strip() if pipe is not None and pipe.tag_mode == 'own' else ''
    return label or lead.product


def stage_tag(lead):
    """The contact tag for where this lead is: "TI: Prospect". The prefix keeps two enquiries by
    one person (insurance and companion) from overwriting each other's stage."""
    return '%s: %s' % (tag_prefix(lead), lead.stage.name) if lead.stage else None


OPT_OUT_TAG = 'opted-out'
WA_SYNC_BATCH = 30            # people per jobs run: at most ~120 calls (4 a person)
WA_INLINE_LIMIT = 10          # people synced straight after one save; the rest wait for the jobs runner
WA_SYNC_BUDGET = 45           # seconds a sync straight after a save may spend (its own background thread)
WA_JOBS_BUDGET = 30           # seconds the jobs runner's sync may spend: with the last person (4 calls of 3 + 6 s)
                              # the jobs request still answers well inside the 120 s worker timeout
WA_LOCK_WAIT = 20             # seconds a sync after a save waits for another sync in this worker
WA_JOBS_LOCK_WAIT = 1         # the jobs runner does not wait: a busy worker leaves the marks for the next run
WA_RETRY_STATUSES = frozenset({401, 403, 404, 408, 429})   # refusals that are not about this person
WA_RETIRED_TAGS_KEY = 'wa_retired_tags'   # 'crm' setting: tags a source used to add (newest first)
WA_RETIRED_MAX = 200
WA_WRITES_OFF = 'WhatsApp is not connected for leads yet. Change it in Set-up → WhatsApp.'
WA_BACKFILL_SAID = ('Bringing %d %s into WhatsApp: they become contacts with their tags, a few at a time. '
                    'Nothing is sent to them.')
WA_BACKFILL_NONE = 'Everybody with a lead and a phone is in WhatsApp already, or on the way.'
# W1's strict phone rule (wacrm src/lib/whatsapp/phone-utils.ts phoneMatchKind)
WA_NEAR_DIGITS = 8            # the shorter side of any match that is not exact
WA_LOCAL_DIGITS = 10          # the longest number read as "saved without its country code"
WA_MOBILE_LONG = 13           # the long form of the extra-mobile-digit numbers; the short form is 12
WA_MOBILE_FORMS = (('52', 2, '1', None),       # Mexico: 52 1 + 10 digits
                   ('54', 2, '9', None),       # Argentina: 54 9 + 10 digits
                   ('55', 4, '9', '6789'))     # Brazil: 55 + area + 9; only old-style mobiles (6-9) gained it
WA_RETRY_AFTER = timedelta(hours=1)
WA_LEASE = timedelta(minutes=5)   # a sync that dies (restart, deploy) is picked up again after this
WA_ERRORS = {'ambiguous_contact': 'Two WhatsApp contacts could be this number. Open full chat, check the number, then press Try again.',
             'invalid_phone': 'WhatsApp says this phone number is not valid',
             'not_configured': 'The WhatsApp CRM has no WhatsApp number connected yet'}
# what the sync kept before the words changed -> the code, so the lead page says it the new way
WA_ERRORS_BEFORE = {'More than one WhatsApp contact could be this number -- merge them in WhatsApp -> Contacts':
                    'ambiguous_contact'}
NOT_MEMBER = '%s is not in the WhatsApp team yet; the chat goes to them once they are'
WA_NEW_LEAD_AFTER = timedelta(days=30)   # a message this long after their last lead closed is a new enquiry
WA_STOP_WORDS = frozenset({'stop', 'unsubscribe', 'stop messages', 'stop promotions', 'stop all',
                           'dont message'})
WA_OPT_OUT_CODE = 131050                 # Meta: they stopped marketing messages from us inside WhatsApp
WA_LEFT_OUT = ('Broadcasts, WhatsApp automations and automatic steps leave them out now; you can still '
               'answer when they write.')
META_OPT_OUT_NOTE = 'WhatsApp says they stopped marketing messages from us. ' + WA_LEFT_OUT
WA_TRY_ELSE = ' Send an approved template, or call them.'
WA_CATCHUP_KEY, WA_HEALTH_KEY = 'crm_wa_catchup', 'crm_wa_health'   # their own settings rows, never "crm"
WA_CATCHUP_LIMIT = 200
WA_CATCHUP_FIRST = timedelta(hours=24)   # the first run looks back one day
WA_CATCHUP_SETTLE = timedelta(minutes=2)  # the newest messages are left for the webhook
WA_HEALTH_EVERY = timedelta(hours=1)
WA_HEALTH_RETELL = timedelta(hours=24)
WA_HOOK_BELLS = {
    'switched_on': ('WhatsApp replies were off; they are on again',
                    'The WhatsApp CRM stopped sending us replies after several failed tries. It is switched '
                    'back on, and the last message of each chat comes in with the next jobs runs. If it keeps '
                    'happening, press "Connect replies" in Set-up → WhatsApp.'),
    'off': ('Replies stopped arriving from WhatsApp',
            'The WhatsApp CRM stopped sending us replies after several failed tries. Press "Connect replies" '
            'in Set-up → WhatsApp to switch them back on.'),
    'missing': ('Replies stopped arriving from WhatsApp',
                'Our address is no longer in the WhatsApp CRM, so replies do not reach the leads. Press '
                '"Connect replies" in Set-up → WhatsApp.'),
}
_wa_lock = threading.RLock()


def _digits(v):
    return ''.join(ch for ch in str(v or '') if ch.isdigit())


_ISO = re.compile(r'^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:?\d{2})?$')


def _parse_utc(value):
    """A naive UTC datetime from ISO 8601 text as the WhatsApp CRM writes it ("...Z", "+00:00",
    up to nine decimals), or None."""
    m = _ISO.match(str(value or '').strip())
    if not m:
        return None
    try:
        dt = datetime.fromisoformat('%sT%s' % (m.group(1), m.group(2)))
    except ValueError:
        return None
    if m.group(3):
        dt = dt.replace(microsecond=int(m.group(3)[:6].ljust(6, '0')))
    tz = m.group(4)
    if tz and tz != 'Z':
        sign = -1 if tz[0] == '-' else 1
        dt -= sign * timedelta(hours=int(tz[1:3]), minutes=int(tz[-2:]))
    return dt


def wa_e164(digits):
    """E.164 for a number as the WhatsApp CRM keeps it (digits, with the country code as WhatsApp
    gives it); 10 digits or fewer were saved without one and are read as our forms read them
    (India). None when it is not a real number."""
    d = _digits(digits)
    if len(d) < 8:
        return None
    return normalise_phone(d if len(d) <= 10 else '+' + d)


def _wa_name(name):
    """A name from the WhatsApp CRM, or None when it is only their number (it names a contact by
    its number when it has nothing better)."""
    n = (name or '').strip()[:120]
    return n if n and not re.fullmatch(r'[\d\s+().-]+', n) else None


def _wa_trunk_forms(d):
    """`d` with a 0 put in, or its 0 taken out, right after a 1-3 digit country code."""
    out = []
    for at in (1, 2, 3):
        out.append(d[:at] + '0' + d[at:])
        if d[at:at + 1] == '0' and len(d) - 1 >= WA_NEAR_DIGITS:
            out.append(d[:at] + d[at + 1:])
    return out


def _wa_mobile_form(d):
    """The same mobile with or without its extra digit (WA_MOBILE_FORMS), or None."""
    for cc, at, digit, short_ok in WA_MOBILE_FORMS:
        if not d.startswith(cc):
            continue
        ok = (lambda s: short_ok is None or (len(s) > at and s[at] in short_ok))
        if len(d) == WA_MOBILE_LONG and d[at] == digit:
            short = d[:at] + d[at + 1:]
            return short if ok(short) else None
        if len(d) == WA_MOBILE_LONG - 1 and ok(d):
            return d[:at] + digit + d[at:]
        return None
    return None


def _wa_local_forms(d):
    """`d` without a 1-3 digit country code, when what is left is 8-10 digits not starting with 0."""
    return [d[at:] for at in (1, 2, 3)
            if WA_NEAR_DIGITS <= len(d) - at <= WA_LOCAL_DIGITS and d[at] != '0']


def same_whatsapp_number(ours, theirs):
    """Whether the WhatsApp CRM's contact number is this person's, by its own strict rule (W1,
    phoneMatchKind): the same digits; the same number written another way -- a 0 or 00 in front,
    a trunk 0 after a 1-3 digit country code (370 0 63949836), the extra mobile digit of Mexico
    (52 1), Argentina (54 9) or Brazil (55 + area + 9, mobiles only); or theirs saved without its
    country code (8-10 digits) that is ours without a 1-3 digit code. Only their side may lack the
    code. Two full international numbers that share only their last digits are two people."""
    g, s = _digits(ours), _digits(theirs)
    if not g or not s:
        return False
    if g == s:
        return True
    S, G = re.sub(r'^0{1,2}', '', s), re.sub(r'^0{1,2}', '', g)
    if min(len(S), len(G)) < WA_NEAR_DIGITS:
        return False
    if S == G or G in _wa_trunk_forms(S) or _wa_mobile_form(S) == G:
        return True
    return S in _wa_local_forms(G)


def _real_name(person):
    n = (person.name or '').strip()
    return n if n and n.lower() not in ('newsletter subscriber', 'unknown') else None


def mark_wa_due(person, assign=False, assign_if_free=False, quiet=False):
    """The WhatsApp CRM should learn about this person: marked here, told after the save (see
    run_wa_sync). `assign`: their owner changed here, so the chat goes to the owner too.
    `assign_if_free`: they wrote from a chat we had not seen, so it goes to the owner only if
    nobody has it. `quiet`: a bulk change (the backfill, a source's tags): their tags are written
    without starting the WhatsApp CRM's "tag added" automations (contract 19), but only when every
    mark since their last push was quiet. Any other change, before or after, makes it a normal
    push. A hand-over of the chat is never quiet. No call, no commit, no rollback. False (nothing
    marked) when WhatsApp is off, or there is nothing to find them by (no number, no WhatsApp
    contact)."""
    if person is None or not (person.phone or person.wacrm_contact_id) or not wa_writes_on():
        return False
    from app.services import crm_scope
    if not crm_scope.wa_person(person):
        return False                           # a contact of a workspace WhatsApp is not linked to
    if quiet and not (assign or assign_if_free):
        if person.wacrm_sync_due_at is None:
            person.wacrm_quiet = True          # nothing was waiting: this push can be quiet
    else:
        person.wacrm_quiet = False             # a person's own change: the push is a normal one
    person.wacrm_sync_due_at = datetime.utcnow()
    if assign:
        person.wacrm_assign_due = True
    if assign_if_free:
        person.wacrm_assign_if_free = True
    if person.id is None:
        db.session.flush()
    db.session.info.setdefault('wa_due', set()).add(person.id)
    return True


def _wa_drop_tags_later(contact_id, keep_for=None):
    """After the save, take the portal's tags off a contact this person no longer has (a changed
    number, a removed person). The contact and its chat stay. Somebody else on the same contact
    is brought into step instead, which puts the right tags on it."""
    if not contact_id or not wa_writes_on():
        return
    others =CrmPerson.query.filter(CrmPerson.wacrm_contact_id == str(contact_id), CrmPerson.id != keep_for).all()
    if others:
        for o in others:
            mark_wa_due(o)
        return
    db.session.info.setdefault('wa_cleanup', []).append(str(contact_id))


def change_phone(person, e164):
    """A new number for them. The WhatsApp CRM ids were the old number's: they go, the old contact
    loses the portal's tags (its chat stays in WhatsApp), and the new number comes in after the save."""
    from app.services import phone as phone_svc
    if not e164 or e164 == person.phone:
        return False
    _wa_drop_tags_later(person.wacrm_contact_id, keep_for=person.id)
    person.phone = e164
    person.country = (phone_svc.iso_for(e164) or '')[:2] or None
    person.wacrm_contact_id = person.wacrm_conversation_id = None
    mark_wa_due(person)
    return True


def _stage_renames(stage, old_name):
    """[{'from': 'TI: Cold lead', 'to': 'TI: Fresh lead'}] for each prefix the stage's tags use (its
    leads' products, or the pipeline's own label) -- not for a name another stage with the same prefix
    also has (two Sahayak pipelines with a "Confirmed"): that one is re-tagged instead."""
    pipe = stage.pipeline

    def prefixes(st):
        pp = st.pipeline
        if pp is not None and pp.tag_mode == 'own' and (pp.tag_label or '').strip():
            return {pp.tag_label.strip()}
        found = {p for (p,) in db.session.query(CrmLead.product).filter(CrmLead.stage_id == st.id).distinct() if p}
        return found | ({pp.product} if pp is not None else set())

    mine = prefixes(stage)
    shared = set()
    for o in CrmStage.query.filter(func.lower(CrmStage.name) == (old_name or '').lower(),
                                   CrmStage.id != stage.id).all():
        shared |= {x.lower() for x in prefixes(o)}
    return [{'from': '%s: %s' % (x, old_name), 'to': '%s: %s' % (x, stage.name)}
            for x in sorted(mine) if x.lower() not in shared and pipe is not None]


def _stage_people(stage):
    """Everybody with an open lead in the stage, and anybody already in the WhatsApp CRM whose lead finished there."""
    return (CrmPerson.query.join(CrmLead, CrmLead.person_id == CrmPerson.id)
            .filter(CrmLead.stage_id == stage.id,
                    or_(CrmLead.status == 'open', CrmPerson.wacrm_contact_id.isnot(None)))
            .distinct().all())


def stages_renamed(pairs):
    """Several stages renamed in one save (the pipeline editor): [(stage, old name)]. All the tags are renamed
    in place in the WhatsApp CRM in ONE call, before anybody is marked; then each person is brought into step
    quietly. Returns how many were marked."""
    pairs = [(st, old) for st, old in pairs if old and old != st.name]
    if not pairs:
        return 0
    people = {}
    for st, _old in pairs:
        for p in _stage_people(st):
            people[p.id] = p
    if wa_writes_on():
        # before any mark: its commit (the rule push saves a setting) must start no sync
        wa_rename_tags([r for st, old in pairs for r in _stage_renames(st, old)])
    return sum(1 for p in people.values() if mark_wa_due(p, quiet=True))


def stage_renamed(stage, old_name=None):
    """A stage's new name reaches the tags: renamed in place in the WhatsApp CRM first, then everybody
    with an open lead in it, and anybody already in the WhatsApp CRM whose lead finished there, is
    brought into step quietly (contract 19: no "tag added" automations). Returns how many were marked."""
    people = _stage_people(stage)
    if old_name and wa_writes_on():
        # before any mark: its commit (the rule push saves a setting) must start no sync
        wa_rename_tags(_stage_renames(stage, old_name))
    return sum(1 for p in people if mark_wa_due(p, quiet=True))


def _wa_mark_quietly(people, now=None, phone_only=False):
    """Mark many people at once, quietly (mark_wa_due's `quiet`): one UPDATE and no thread -- the
    jobs runner brings them in, WA_SYNC_BATCH a run. `people`: a select of person ids. Somebody
    already due keeps their mark, and how it goes. Flushes first, so marks made earlier in this
    save count. Call it last in a save: the people in the session are not refreshed. No commit.
    How many were marked; 0 while writes are off."""
    if not wa_writes_on():
        return 0
    db.session.flush()
    reach = (CrmPerson.phone.isnot(None) if phone_only else
             or_(CrmPerson.phone.isnot(None), CrmPerson.wacrm_contact_id.isnot(None)))
    return (CrmPerson.query.filter(reach, CrmPerson.wacrm_sync_due_at.is_(None), CrmPerson.id.in_(people))
            .update({'wacrm_sync_due_at': now or datetime.utcnow(), 'wacrm_quiet': True},
                    synchronize_session=False))


WA_RULE_KEY = 'crm_wa_tag_rule'            # its own settings row: pushed_at, hash, error, due, old
WA_RULE_EVERY = timedelta(hours=24)
WA_RULE_MAX = 300                          # entries per map (contract)
WA_RULE_BUDGET = 1500                      # characters of the compact rule: the WhatsApp CRM keeps all its
                                           # portal rules in 3000 (with quick-reply fingerprints)
WA_RULE_RETIRED = 20                       # retired prefixes sent at most
WA_OLD_TAG, WA_OPTED_OUT_LABEL, WA_SOURCE_LABEL = 'Old tag', 'Opted out', 'Source: %s'


def wa_tag_rule():
    """{'prefixes': {...}, 'names': {...}} -- which tags are the Sales CRM's, for PUT /api/portal/managed-tags:
    prefixes: each product code -> its name, each pipeline's own tag label -> the pipeline's name, recent
    retired prefixes -> "Old tag"; names: "opted-out" -> "Opted out", each product tag (lower-case code) ->
    its name, each source tag -> "Source: <source name>", then retired source tags -> "Old tag" while it
    fits WA_RULE_BUDGET (the last retired names go first, then retired prefixes). Keys are merged
    ignoring case; a product wins over a label of the same letters."""
    raw = crm_settings_raw()
    pref = {}                                  # lower -> (key, label)
    retired_p = [str(x).strip() for x in (raw.get(WA_RETIRED_PREFIXES_KEY) or []) if str(x).strip()]
    retired_p = retired_p[:WA_RULE_RETIRED]
    for x in retired_p:
        pref[x.lower()] = (x, WA_OLD_TAG)
    for pipe in CrmPipeline.query.order_by(CrmPipeline.id).all():
        label = (pipe.tag_label or '').strip()
        if pipe.tag_mode == 'own' and label:
            pref[label.lower()] = (label, (pipe.name or label)[:100])
    for prod in crm_products.all():
        pref[prod.code.lower()] = (prod.code, (prod.name or prod.code)[:100])
    names = {OPT_OUT_TAG: WA_OPTED_OUT_LABEL}
    for prod in crm_products.all():
        names[prod.code.lower()] = (prod.name or prod.code)[:100]
    seen = {k.lower() for k in names}
    for src in CrmSource.query.order_by(CrmSource.name, CrmSource.id).all():
        for t in src.crm_tags or []:
            t = str(t or '').strip()
            if t and t.lower() not in seen:
                names[t] = WA_SOURCE_LABEL % (src.name or src.key)[:90]
                seen.add(t.lower())
    retired_n = []
    for t in raw.get(WA_RETIRED_TAGS_KEY) or []:
        t = str(t or '').strip()
        if t and t.lower() not in seen:
            names[t] = WA_OLD_TAG
            retired_n.append(t)
            seen.add(t.lower())

    def build():
        return {'prefixes': dict([(k, l) for k, l in pref.values()][:WA_RULE_MAX]),
                'names': dict(list(names.items())[:WA_RULE_MAX])}
    rule = build()
    while len(json.dumps(rule, separators=(',', ':'))) > WA_RULE_BUDGET:
        if retired_n:
            names.pop(retired_n.pop(), None)
        elif retired_p:
            pref.pop(retired_p.pop().lower(), None)
        else:
            break
        rule = build()
    return rule


def _wa_rule_hash(rule):
    return hashlib.sha1(json.dumps(rule, sort_keys=True).encode('utf-8')).hexdigest()


def wa_push_tag_rule(now=None):
    """Tell the WhatsApp CRM the Sales-tag rule now. Only while writes are on and the team link is set
    up. True: it took it; False: refused or no answer (logged; kept due for the jobs runner, except a
    refusal only a person can fix); None: nothing sent (off, not connected, an old WhatsApp CRM -- 404,
    logged and ignored). Saves its own settings row (commits)."""
    from app.services import settings, wacrm, wacrm_team
    if not (wa_writes_on() and wacrm_team.enabled()):
        return None
    now = now or datetime.utcnow()
    rule = wa_tag_rule()
    state = dict(settings.get_setting(WA_RULE_KEY) or {})
    result = False
    try:
        with wacrm.short_timeouts():
            wacrm_team.put_managed_tags(rule['prefixes'], rule['names'])
        state.update(pushed_at=now.isoformat(timespec='seconds'), hash=_wa_rule_hash(rule), error=None,
                     due=False, old=False)
        result = True
    except wacrm_team.TeamError as exc:
        if exc.status == 404:
            log.info('The WhatsApp CRM does not know the Sales-tag rule yet (older version)')
            state.update(pushed_at=now.isoformat(timespec='seconds'), old=True, due=False)
            result = None
        else:
            log.warning('The WhatsApp CRM did not take the Sales-tag rule: %s', exc)
            state.update(error=str(exc)[:200],
                         due=exc.status is None or exc.status >= 500 or exc.status in WA_RETRY_STATUSES)
    settings.set_setting(WA_RULE_KEY, state)
    return result


def wa_tag_rule_changed():
    """After a set-up save (products, pipeline tags, stages, source tags) or switching writes on: push
    the rule when it is not what the WhatsApp CRM last took. Never raises (a save must not fail on it)."""
    from app.services import settings, wacrm_team
    try:
        if not (wa_writes_on() and wacrm_team.enabled()):
            return None
        state = settings.get_setting(WA_RULE_KEY) or {}
        if state.get('hash') == _wa_rule_hash(wa_tag_rule()) and not state.get('error') and not state.get('old'):
            return True
        return wa_push_tag_rule()
    except Exception:          # noqa: BLE001
        db.session.rollback()
        log.warning('Sales-tag rule push failed', exc_info=True)
        return False


def wa_tag_rule_daily(now=None):
    """The jobs runner: again once a day (or when it is due, or the rule changed) -- only where a push
    happened before or replies are connected here ("Connect replies"), so nothing is written to a
    WhatsApp CRM nobody linked. {'crm_wa_tag_rule': 'ok' | 'failed' | 'old'} or {}."""
    from app.services import settings, wacrm_team
    if not (wa_writes_on() and wacrm_team.enabled()):
        return {}
    now = now or datetime.utcnow()
    state = settings.get_setting(WA_RULE_KEY) or {}
    if not (state.get('pushed_at') or _wa_webhook_saved().get('id')):
        return {}
    last = _parse_utc(state.get('pushed_at')) if state.get('pushed_at') else None
    if not (state.get('due') or last is None or now - last >= WA_RULE_EVERY
            or state.get('hash') != _wa_rule_hash(wa_tag_rule())):
        return {}
    r = wa_push_tag_rule(now)
    return {'crm_wa_tag_rule': 'ok' if r else 'old' if r is None else 'failed'}


def wa_rename_tags(renames):
    """Rename Sales tags in the WhatsApp CRM in place (ids, rules and broadcasts keep pointing at them):
    the rule is pushed first when it may not have it (renames of tags it does not count as Sales tags are
    skipped "not_managed"). {'renamed': [...], 'skipped': [...]} or None when it could not ask (off, not
    connected, an older WhatsApp CRM -- 404 -- or no answer). Logged, never raised; the caller re-marks
    the people either way, which is the re-tag fallback."""
    from app.services import wacrm, wacrm_team
    if not renames or not (wa_writes_on() and wacrm_team.enabled()):
        return None
    wa_tag_rule_changed()
    try:
        with wacrm.short_timeouts():
            out = wacrm_team.rename_tags(renames)
    except wacrm_team.TeamError as exc:
        if exc.status == 404:
            log.info('The WhatsApp CRM cannot rename tags in place (older version): re-tagged instead')
        else:
            log.warning('The WhatsApp CRM did not rename tags: %s', exc)
        return None
    if out.get('skipped'):
        log.info('%d tag rename(s) skipped by the WhatsApp CRM: %s', len(out['skipped']),
                 ', '.join('%s (%s)' % (x.get('from'), x.get('reason')) for x in out['skipped'][:10]))
    return out


def pipeline_tag_changed(pipe, old_mode, old_label, actor=None):
    """A pipeline's WhatsApp tag changed (U6 "Change WhatsApp tag"): the old prefix is retired (still the
    portal's, so leftovers come off), the rule is pushed, every "<old>: <stage>" is renamed in place to
    "<new>: <stage>" where that is one-to-one, then everybody with a lead in it is re-marked quietly
    (jobs runner). Call it after setting pipe.tag_mode / tag_label, before the commit. {'renamed', 'marked'}."""
    old_label = (old_label or '').strip()
    products = sorted({p for (p,) in db.session.query(CrmLead.product).filter(CrmLead.pipeline_id == pipe.id)
                       .distinct() if p}) or [pipe.product]
    old = [old_label] if old_mode == 'own' and old_label else products
    label = (pipe.tag_label or '').strip()
    new = [label] if pipe.tag_mode == 'own' and label else products
    gone = {n.lower() for n in new}
    wa_retire_prefixes([o for o in old if o.lower() not in gone], actor)
    renames = []
    if len(new) == 1 and len(old) >= 1:
        for st in pipe.stages:
            for o in old:
                if o.lower() != new[0].lower():
                    renames.append({'from': '%s: %s' % (o, st.name), 'to': '%s: %s' % (new[0], st.name)})
        if len(old) > 1:
            renames = []                   # several old prefixes into one: not one-to-one
    res = wa_rename_tags(renames) if renames else None
    marked = wa_mark_pipeline(pipe)
    return {'renamed': len((res or {}).get('renamed') or []), 'marked': marked}


def wa_mark_pipeline(pipe, now=None):
    """Everybody with a lead in the pipeline (open, or already in the WhatsApp CRM) is brought into step
    quietly by the jobs runner -- after a tag change or a product change. No commit. How many were marked."""
    return _wa_mark_quietly(select(CrmLead.person_id).where(
        CrmLead.pipeline_id == pipe.id,
        or_(CrmLead.status == 'open',
            CrmLead.person_id.in_(select(CrmPerson.id).where(CrmPerson.wacrm_contact_id.isnot(None))))), now)


def wa_tag_clashes(prefix=None, names=()):
    """Tags made in the WhatsApp CRM that a new product code, own tag label or source tag would make the
    Sales CRM's (F56): [{'name', 'contacts'}] the rule does not cover yet -- "<prefix>", "<prefix>: ..."
    or one of `names` (ignoring case). [] when it cannot ask (writes off, not connected, older version)."""
    from app.services import wacrm, wacrm_team
    if not (wa_writes_on() and wacrm_team.enabled()):
        return []
    try:
        with wacrm.short_timeouts():
            items = wacrm_team.list_tags()
    except wacrm_team.TeamError:
        return []
    pre = (prefix or '').strip().lower()
    want = {str(n).strip().lower() for n in names or () if str(n).strip()}
    out = []
    for item in items:
        n = (item.get('name') or '').strip()
        low = n.lower()
        if item.get('managed'):
            continue
        if low in want or (pre and (low == pre or low.startswith(pre + ': '))):
            out.append({'name': n, 'contacts': item.get('contacts') or 0})
    return out


def wa_backfill(now=None):
    """Bring everybody with a lead and a phone -- open leads and won and lost customers, imported ones too --
    into the WhatsApp CRM, quietly: their contact and its tags only, without starting its tag automations. No chat is
    made and nothing is sent. This only marks them; the jobs runner does the work, WA_SYNC_BATCH a
    run. Somebody whose last sync was refused (a person had to sort it out) is tried again.
    Returns how many were marked."""
    if not wa_writes_on():
        return 0
    n = _wa_mark_quietly(select(CrmLead.person_id), now, phone_only=True)
    db.session.commit()
    return n


def wa_mark_source(src, now=None):
    """A source's tags changed (Set-up -> Sources): everybody with an open lead from it is brought
    into step quietly, by the jobs runner. No commit. Returns how many were marked."""
    return _wa_mark_quietly(select(CrmLead.person_id).where(CrmLead.source_id == src.id,
                                                            CrmLead.status == 'open'), now)


def _wa_live_source_tags():
    """Every tag a lead source adds now (Set-up -> Sources), lower case."""
    return {t.strip().lower() for s in CrmSource.query.all() for t in (s.crm_tags or []) if t and t.strip()}


def _wa_source_tags():
    """The source tags the portal looks after, lower case: every tag a source adds, and every one
    a source used to add (wa_retire_tags) -- so the sync takes those off. Never "opted-out"."""
    old = {str(t).strip().lower() for t in (crm_settings_raw().get(WA_RETIRED_TAGS_KEY) or []) if str(t).strip()}
    return (_wa_live_source_tags() | old) - {OPT_OUT_TAG}


def wa_retire_tags(removed, actor=None):
    """Tags a source no longer adds stay the portal's (the 'crm' setting WA_RETIRED_TAGS_KEY), so
    the sync keeps taking them off people's WhatsApp contacts. Newest first, at most
    WA_RETIRED_MAX; never "opted-out", never a tag a source still adds (one put back leaves the
    list). Saves -- which commits -- only when the list changes. Returns the list."""
    live = _wa_live_source_tags()
    old = [str(t).strip().lower() for t in (crm_settings_raw().get(WA_RETIRED_TAGS_KEY) or []) if str(t).strip()]
    out = []
    for t in sorted(str(x).strip().lower() for x in (removed or ()) if str(x).strip()) + old:
        if t != OPT_OUT_TAG and t not in live and t not in out:
            out.append(t)
    out = out[:WA_RETIRED_MAX]
    if out != old:
        save_settings(actor, **{WA_RETIRED_TAGS_KEY: out})
    return out


WA_RETIRED_PREFIXES_KEY = 'wa_retired_prefixes'   # 'crm' setting: stage-tag prefixes no longer used (newest first)
WA_RETIRED_PREFIX_MAX = 50


def _wa_rule():
    """What makes a tag the portal's, lower case: (product codes -- the bare product tags --, the first
    parts of stage tags: every code, every own label, the retired prefixes). The seed's codes without an
    app context."""
    codes = frozenset(c.lower() for c in crm_products.codes())
    if not has_app_context():
        return codes, codes
    old = {str(x).strip().lower() for x in crm_settings_raw().get(WA_RETIRED_PREFIXES_KEY) or [] if str(x).strip()}
    return codes, frozenset(x for x in _wa_live_prefixes() | old if x)


def _wa_live_prefixes():
    """Every product code and every own tag label in use, lower case."""
    labels = {(l or '').strip().lower() for (l,) in db.session.query(CrmPipeline.tag_label)
              .filter(CrmPipeline.tag_mode == 'own', CrmPipeline.tag_label.isnot(None))}
    return frozenset(c.lower() for c in crm_products.codes()) | labels


def wa_retire_prefixes(old, actor=None):
    """Stage-tag prefixes no longer used (a pipeline's changed tag) stay the portal's, so the sync keeps
    taking those tags off. Never a live prefix, newest first, at most WA_RETIRED_PREFIX_MAX. Saves --
    which commits -- only when the list changes. Returns the list."""
    live = _wa_live_prefixes()
    cur = [str(x).strip() for x in (crm_settings_raw().get(WA_RETIRED_PREFIXES_KEY) or []) if str(x).strip()]
    out, seen = [], set()
    for x in [str(o).strip() for o in (old or ()) if str(o).strip()] + cur:
        if x.lower() not in live and x.lower() not in seen:
            out.append(x)
            seen.add(x.lower())
    out = out[:WA_RETIRED_PREFIX_MAX]
    if out != cur:
        save_settings(actor, **{WA_RETIRED_PREFIXES_KEY: out})
    return out


def _wa_is_portal_tag(name, source_tags, rule=None):
    """`source_tags` comes from _wa_source_tags(), retired tags included."""
    n = (name or '').strip().lower()
    if n == OPT_OUT_TAG:
        return False                     # never taken off by the portal
    codes, prefixes = rule or _wa_rule()
    return n in codes or any(n.startswith(x + ': ') for x in prefixes) or n in source_tags


def _wa_wanted_tags(person):
    """The tags the portal puts on their contact: the product ("ti") of each lead, and per stage-tag
    prefix (the product code, or the pipeline's own label) where its lead is ("TI: Prospect") -- the
    open lead, else the latest finished one, so Won / Lost stays visible; every lead's source tags;
    and "opted-out" once they opted out."""
    def rank(l):
        return (l.status == 'open', l.last_activity_at or l.created_at or datetime.min, l.id or 0)
    best, want = {}, set()
    for lead in person.leads:
        prefix = tag_prefix(lead)
        if prefix not in best or rank(lead) > rank(best[prefix]):
            best[prefix] = lead
        want |= {t for t in ((lead.source.crm_tags or []) if lead.source else []) if t}
    want |= {l.product.lower() for l in person.leads}
    for prefix, lead in best.items():
        st = stage_tag(lead)
        if st:
            want.add(st)
    if person.wa_opt_out_at:
        want.add(OPT_OUT_TAG)
    return want


def _wa_tag_list(have, want, source_tags, drop=(), rule=None):
    """The contact's new tag list, or None when nothing changes. Tags set by hand in the WhatsApp
    CRM stay; a portal tag that no longer fits goes. Compared ignoring case, as it does. `drop`:
    names that go whatever else is true (the "opted-out" tag after an admin opted them back in)."""
    rule = rule or _wa_rule()
    drop_l = {d.lower() for d in drop}
    want_l = {w.lower(): w for w in want if w.lower() not in drop_l}
    have_l = {h.lower() for h in have}
    final = [h for h in have if h.lower() not in drop_l
             and (h.lower() in want_l or not _wa_is_portal_tag(h, source_tags, rule))]
    final += [w for k, w in want_l.items() if k not in have_l]
    return None if {f.lower() for f in final} == have_l else sorted(final)


def _wa_drop_tags(contact_id, source_tags, rule=None):
    from app.services import wacrm
    rule = rule or _wa_rule()
    try:
        data = wacrm.get_contact(contact_id) or {}
        have = [t.get('name') for t in data.get('tags') or [] if isinstance(t, dict) and t.get('name')]
        keep = [t for t in have if not _wa_is_portal_tag(t, source_tags, rule)]
        if len(keep) != len(have):
            wacrm.update_contact(contact_id, tags=sorted(keep))
    except Exception:      # noqa: BLE001 -- best effort; the contact keeps its old tags
        log.info('WhatsApp CRM tags not taken off contact %s', contact_id, exc_info=True)


def _wa_main_lead(person):
    """Their most recently active open lead: its owner looks after the chat."""
    opens = [l for l in person.leads if l.status == 'open']
    return max(opens, key=lambda l: (l.last_activity_at or l.created_at or datetime.min, l.id), default=None)


def _wa_claim(person, now=None):
    """Take this person for a sync: their mark becomes a short lease, so another worker leaves
    them alone. None when somebody else just took them (or they are gone, or backing off)."""
    try:
        due = person.wacrm_sync_due_at
    except ObjectDeletedError:
        return None                      # removed since the list was read
    if due is None or due > (now or datetime.utcnow()):
        return None
    lease = datetime.utcnow() + WA_LEASE
    n = (CrmPerson.query.filter(CrmPerson.id == person.id, CrmPerson.wacrm_sync_due_at == due)
         .update({'wacrm_sync_due_at': lease}, synchronize_session=False))
    db.session.commit()
    return lease if n else None


def _wa_parks(exc):
    """Whether the WhatsApp CRM refused this person for a reason only a person can sort out -- a
    number it will not take, two contacts that could be the number (4xx): kept as their problem
    and not tried again every hour. A wrong key or address, or a feature an older WhatsApp CRM
    lacks (401, 403, 404), a slow or busy server (408, 429), no WhatsApp number connected
    (not_configured), a server fault or no answer: tried again in an hour."""
    status = getattr(exc, 'status', None)
    return (status is not None and 400 <= status < 500 and status not in WA_RETRY_STATUSES
            and getattr(exc, 'code', None) != 'not_configured')


def _wa_finish(person_id, claimed, done, error=None, retry=True, contact_id=None,
               conversation_id=None, contact_changed=False, park=False, keep_assign=False):
    """Write how a sync went -- only while the lease is still ours: a save in the meantime marked
    them again, and the next sync (with the newer state) writes instead. True when written.
    `park`: refused for a reason only a person can sort out (_wa_parks): the problem is kept and
    nothing is tried again by itself; the next change to them (mark_wa_due) tries again, the
    chat's hand-over too. `keep_assign`: done, but their chat still has to go to the owner once
    the WhatsApp team link is set up; the next mark does it."""
    now = datetime.utcnow()
    vals = {'wa_sync_error': (error or '')[:300] or None}
    if contact_id:
        vals['wacrm_contact_id'] = contact_id
    if conversation_id:
        vals['wacrm_conversation_id'] = conversation_id
    elif contact_changed:
        vals['wacrm_conversation_id'] = None
    if done:
        vals.update(wacrm_sync_due_at=None, wacrm_quiet=False, wa_synced_at=now, wa_opt_in_due=False)
        if not keep_assign:
            vals.update(wacrm_assign_due=False, wacrm_assign_if_free=False)
    elif park:
        vals.update(wacrm_sync_due_at=None, wacrm_quiet=False)      # assign flags kept: the next mark finishes
    else:
        vals['wacrm_sync_due_at'] = now + WA_RETRY_AFTER if retry else now   # the quiet flag stays for the retry
    n = (CrmPerson.query.filter(CrmPerson.id == person_id, CrmPerson.wacrm_sync_due_at == claimed)
         .update(vals, synchronize_session=False))
    if not n and done:
        # another worker finished them while we worked: once more, so the newest state has the last word
        (CrmPerson.query.filter(CrmPerson.id == person_id, CrmPerson.wacrm_sync_due_at.is_(None))
         .update({'wacrm_sync_due_at': now}, synchronize_session=False))
    db.session.commit()
    return bool(n)


class _WaProblem(Exception):
    pass


def _wa_fill_number(person, contact_id):
    """Somebody we know only by their WhatsApp CRM contact (they wrote in without a number): the
    number and name that contact has, kept on them -- not when somebody here has that number
    already, which a person sorts out. (digits or '', the problem or None)."""
    from app.services import wacrm
    from app.services import phone as phone_svc
    try:
        data = wacrm.get_contact(contact_id) or {}
    except wacrm.WacrmError as exc:
        if exc.status == 404:
            return '', None              # gone from the WhatsApp CRM: nothing more to find
        raise
    e164 = wa_e164(data.get('phone'))
    if not e164:
        return '', None                  # a WhatsApp user name with no number
    other = CrmPerson.query.filter(CrmPerson.phone == e164, CrmPerson.id != person.id).first()
    if other is not None:
        return '', "Their WhatsApp number is person %d's here already" % other.id
    person.phone = e164
    person.country = (phone_svc.iso_for(e164) or '')[:2] or None
    found = _wa_name(data.get('name'))
    if found and not _real_name(person):
        person.name = found
    db.session.flush()
    return _digits(e164), None


def _wa_sync_person(person, source_tags, now=None, rule=None):
    """One person into step: their contact (made when new, and certainly theirs), its tags, name
    and e-mail, then -- only when the owner changed here, or they wrote from a chat nobody has --
    the chat to the owner. Somebody known only by their contact gets its number first.
    'ok' | 'failed' | 'down' (the WhatsApp CRM did not answer) | 'skipped'."""
    from app.services import wacrm, wacrm_team
    claimed = _wa_claim(person, now)
    if claimed is None:
        return 'skipped'
    pid, digits, name = person.id, _digits(person.phone), _real_name(person)
    quiet = bool(person.wacrm_quiet)
    before = person.wacrm_contact_id
    if not digits and not before:
        _wa_finish(pid, claimed, True)
        return 'ok'
    cid = conversation_id = pending = None
    verified = waits = False
    try:
        if not digits:
            # 0. somebody who wrote in before we had their number: the one their contact has
            digits, problem = _wa_fill_number(person, before)
            if not digits:
                if problem:
                    _wa_finish(pid, claimed, False, error=problem, park=True)
                    return 'failed'
                _wa_finish(pid, claimed, True)
                return 'ok'
            name = _real_name(person)
        # 1. their contact, found by number (made when new) -- and certainly theirs
        data = wacrm.find_or_create_contact(person.phone, name=name, email=person.email)
        cid = str(data.get('id') or '') or None
        if not cid:
            raise _WaProblem('The WhatsApp CRM did not return their contact')
        if data.get('phone') and not same_whatsapp_number(digits, data['phone']):
            raise _WaProblem('WhatsApp matched a different number, ending %s' % _digits(data['phone'])[-4:])
        holder = CrmPerson.query.filter(CrmPerson.wacrm_contact_id == cid, CrmPerson.id != pid).first()
        if holder is not None:
            raise _WaProblem('Same WhatsApp contact as person %d' % holder.id)
        verified = True
        # 2. the portal's tags, and the name and e-mail when they differ
        patch = {}
        have = [t.get('name') for t in data.get('tags') or [] if isinstance(t, dict) and t.get('name')]
        untag = bool(person.wa_opt_in_due) and person.wa_opt_out_at is None
        tags = _wa_tag_list(have, _wa_wanted_tags(person), source_tags,
                            drop=(OPT_OUT_TAG,) if untag else (), rule=rule)
        if tags is not None:
            patch['tags'] = tags
        if name and 'name' in data and (data.get('name') or '').strip() != name:
            patch['name'] = name
        if person.email and 'email' in data and (data.get('email') or '').strip().lower() != person.email.lower():
            patch['email'] = person.email
        if patch:
            wacrm.update_contact(cid, quiet=quiet, **patch)
        # 3. the chat goes to the owner: the owner changed here (it moves to them), or somebody
        #    already here wrote from a chat we had not seen (only if nobody has it)
        force = bool(person.wacrm_assign_due)
        handover = force or bool(person.wacrm_assign_if_free)
        waits = handover and not wacrm_team.enabled()   # no team link yet: the next mark hands it over
        if handover and not waits:
            lead = _wa_main_lead(person)
            email = ((lead.owner.email or '') if lead is not None and lead.owner is not None else '').strip().lower()
            if email:
                r = wacrm_team.ensure_conversation(digits, name=name, email=person.email,
                                                   create=True, assign_email=email)
                if str(r.get('contact_id') or '') != cid:
                    raise _WaProblem('WhatsApp gave two different contacts for this number')
                conversation_id = str(r.get('conversation_id') or '') or None
                if force and (r.get('assignee_email') or '').lower() != email:
                    if r.get('assignment') == 'not_member':
                        pending = NOT_MEMBER % email
                    elif conversation_id:
                        try:
                            wacrm_team.assign_conversation(None, email, conversation_id=conversation_id)
                        except wacrm_team.TeamError as exc:
                            if exc.status != 422:
                                raise
                            pending = NOT_MEMBER % email
    except (wacrm.WacrmError, wacrm_team.TeamError) as exc:
        down = getattr(exc, 'status', 0) is None
        _wa_finish(pid, claimed, False, error=WA_ERRORS.get(getattr(exc, 'code', None)) or str(exc),
                   retry=not down, contact_id=cid if verified else None,
                   conversation_id=conversation_id if verified else None,
                   contact_changed=verified and before is not None and cid != before, park=_wa_parks(exc))
        log.warning('WhatsApp CRM sync failed for person %s', pid)
        return 'down' if down else 'failed'
    except _WaProblem as exc:
        _wa_finish(pid, claimed, False, error=str(exc), park=True)
        log.warning('WhatsApp CRM sync refused for person %s: %s', pid, exc)
        return 'failed'
    except Exception:      # noqa: BLE001 -- one person must not stop the rest
        db.session.rollback()
        log.exception('WhatsApp CRM sync broke for person %s', pid)
        _wa_finish(pid, claimed, False, error='Something went wrong -- see the server log')
        return 'failed'
    if pending:
        _wa_finish(pid, claimed, False, error=pending, contact_id=cid, conversation_id=conversation_id,
                   contact_changed=before is not None and cid != before, park=True)
        return 'failed'
    _wa_finish(pid, claimed, True, contact_id=cid, conversation_id=conversation_id,
               contact_changed=before is not None and cid != before, keep_assign=waits)
    return 'ok'


def run_wa_sync(ids=None, cleanups=(), limit=None, budget=None, now=None):
    """Bring the people marked due into step with the WhatsApp CRM, one person at a time (see
    mark_wa_due). `ids`: just these, straight after a save, in a background thread: it may wait
    WA_LOCK_WAIT for another sync in this worker and spends up to WA_SYNC_BUDGET. None: the oldest
    due, for the jobs runner, which waits at most WA_JOBS_LOCK_WAIT and spends up to
    WA_JOBS_BUDGET, so the jobs request answers in time. Never sends a message. Counts for the
    jobs report."""
    from app.services import wacrm
    out = {'crm_wa_synced': 0, 'crm_wa_failed': 0}
    if not wa_writes_on():
        return out                       # nothing is written while it is off; marks wait
    jobs = ids is None
    if not _wa_lock.acquire(timeout=WA_JOBS_LOCK_WAIT if jobs else WA_LOCK_WAIT):
        return out                       # this worker is busy syncing; the marks stay for later
    try:
        with wacrm.short_timeouts():
            source_tags = _wa_source_tags()
            rule = _wa_rule()
            for contact_id in cleanups or ():
                _wa_drop_tags(contact_id, source_tags, rule)
            if ids is not None and not ids:
                return out
            now = now or datetime.utcnow()
            q = CrmPerson.query.filter(CrmPerson.wacrm_sync_due_at.isnot(None),
                                       CrmPerson.wacrm_sync_due_at <= now)
            if ids is not None:
                q = q.filter(CrmPerson.id.in_(list(ids)))
            people = (q.order_by(CrmPerson.wacrm_sync_due_at, CrmPerson.id).populate_existing()
                      .limit(limit or (WA_INLINE_LIMIT if ids is not None else WA_SYNC_BATCH)).all())
            started = monotonic()
            if budget is None:
                budget = WA_JOBS_BUDGET if jobs else WA_SYNC_BUDGET
            for person in people:
                if monotonic() - started > budget:
                    break
                result = _wa_sync_person(person, source_tags, now, rule=rule)
                if result == 'ok':
                    out['crm_wa_synced'] += 1
                elif result in ('failed', 'down'):
                    out['crm_wa_failed'] += 1
                if result == 'down':
                    break                # it is not answering: the rest wait for the next run
    finally:
        _wa_lock.release()
    out['crm_wa_waiting'] = CrmPerson.query.filter(CrmPerson.wacrm_sync_due_at.isnot(None)).count()
    return out


def _wa_run_isolated(app, ids, cleanups):
    with app.app_context():                       # its own session: the save is already committed
        try:
            run_wa_sync(ids, cleanups)
        except Exception:      # noqa: BLE001 -- the marks stay; the jobs runner tries again
            db.session.rollback()
            log.warning('WhatsApp CRM sync after a save failed', exc_info=True)
        finally:
            db.session.remove()


@contextmanager
def wa_sync_later():
    """Saves inside this mark people for the WhatsApp CRM but start no sync of their own: the jobs
    runner (run_wa_sync) brings them in, a few at a time. A catch-up that makes many leads must
    not start a thread for each."""
    db.session.info['wa_later'] = True
    try:
        yield
    finally:
        db.session.info.pop('wa_later', None)


def _wa_after_commit(session):
    """Straight after a save, the people it marked go to the WhatsApp CRM in a background thread,
    so nobody waits for it (WA_SYNC_INLINE, in tests: here and now)."""
    if session.get_nested_transaction() is not None:
        return                                     # a savepoint: the real commit comes later
    if session.info.get('wa_later'):
        session.info.pop('wa_due', None)     # they stay marked: the jobs runner's run_wa_sync takes them
    ids = session.info.pop('wa_due', None)
    cleanups = session.info.pop('wa_cleanup', None)
    if not ids and not cleanups:
        return
    app = current_app._get_current_object()
    args = (app, sorted(ids or ()), list(cleanups or ()))
    if app.config.get('WA_SYNC_INLINE'):
        _wa_run_isolated(*args)
    else:
        try:
            threading.Thread(target=_wa_run_isolated, args=args, daemon=True, name='wacrm-sync').start()
        except Exception:      # noqa: BLE001 -- the save is done; its marks wait for the jobs runner
            log.warning('WhatsApp CRM sync not started after a save; the jobs runner brings them in',
                        exc_info=True)


def _wa_after_rollback(session, previous_transaction):
    if previous_transaction.parent is None:        # the whole save was undone (not a savepoint)
        session.info.pop('wa_due', None)
        session.info.pop('wa_cleanup', None)


event.listen(db.session, 'after_commit', _wa_after_commit)
event.listen(db.session, 'after_soft_rollback', _wa_after_rollback)


# ======================================================================================= from the WhatsApp CRM

def wa_person(contact_id=None, phone=None):
    """The person a WhatsApp CRM event is about, or None: by their contact id, then by the WhatsApp
    user id kept for people without a number, then by number -- exactly, else certainly the same
    number (same_whatsapp_number) and only when that is one person. Never a guess. Writes nothing."""
    cid = str(contact_id).strip()[:64] if contact_id else None
    d = _digits(phone)
    if cid:
        holders = CrmPerson.query.filter_by(wacrm_contact_id=cid).order_by(CrmPerson.id).limit(5).all()
        if len(holders) > 1:
            log.warning('WhatsApp contact %s is on %d people here', cid, len(holders))
            holders.sort(key=lambda p: (_digits(p.phone) != d, not same_whatsapp_number(p.phone, d), p.id))
        if holders:
            return holders[0]
        hit = CrmIdentity.query.filter_by(kind='wacrm', value=cid).first()
        if hit is not None:
            return hit.person
    if len(d) < 8:
        return None
    e164 = wa_e164(d)
    p = CrmPerson.query.filter_by(phone=e164).first() if e164 else None
    if p is not None:
        return p
    near = [p for p in CrmPerson.query.filter(CrmPerson.phone.like('%' + d[-8:])).limit(20).all()
            if same_whatsapp_number(p.phone, d)]
    if len(near) > 1:
        log.warning('WhatsApp number ending %s could be %d people here; none was picked', d[-4:], len(near))
    return near[0] if len(near) == 1 else None


def wa_person_by_chat(conversation_id):
    """The one person here holding this WhatsApp conversation, or None."""
    if not conversation_id:
        return None
    rows = CrmPerson.query.filter_by(wacrm_conversation_id=str(conversation_id)).limit(2).all()
    return rows[0] if len(rows) == 1 else None


def wa_link(person, contact_id=None, conversation_id=None, phone=None, name=None):
    """Keep what a WhatsApp CRM event says about somebody we have: their contact id (never one
    another person here holds, never over a different one -- the sync then checks which is
    theirs, and the chat is not taken from it), their chat, and the number and name we did not
    have. No call. True when the chat is one we had not seen for them."""
    from app.services import phone as phone_svc
    cid = str(contact_id).strip()[:64] if contact_id else None
    conv = str(conversation_id).strip()[:64] if conversation_id else None
    recheck = False
    if cid and person.wacrm_contact_id != cid:
        held = CrmPerson.query.filter(CrmPerson.wacrm_contact_id == cid, CrmPerson.id != person.id).first()
        if person.wacrm_contact_id is None and held is None:
            person.wacrm_contact_id = cid
        else:
            recheck, conv = True, None
    if not person.phone:
        e164 = wa_e164(phone)
        if e164 and not CrmPerson.query.filter(CrmPerson.phone == e164, CrmPerson.id != person.id).first():
            person.phone = e164
            person.country = (phone_svc.iso_for(e164) or '')[:2] or None
            recheck = True
    found = _wa_name(name)
    if found and not _real_name(person):
        person.name = found
    new_chat = bool(conv) and person.wacrm_conversation_id != conv
    if new_chat:
        person.wacrm_conversation_id = conv
    if recheck:
        mark_wa_due(person)
    return new_chat


def wa_lead_for(person, template_name=None):
    """Which open lead a WhatsApp message belongs to when they have several (two enquiries, one
    chat): the one whose open step uses this template (a message sent from WhatsApp), else the one
    we last wrote to on WhatsApp, else the newest. None when none is open."""
    opens = [l for l in person.leads if l.status == 'open']
    if template_name:
        hits = [l for l in opens if l.open_task is not None and l.open_task.step is not None
                and l.open_task.step.wa_template == template_name]
        opens = hits or opens
    if len(opens) <= 1:
        return opens[0] if opens else None
    last = dict(db.session.query(CrmTouchpoint.lead_id, func.max(CrmTouchpoint.created_at))
                .filter(CrmTouchpoint.lead_id.in_([l.id for l in opens]), CrmTouchpoint.channel == 'whatsapp',
                        CrmTouchpoint.direction == 'out')
                .group_by(CrmTouchpoint.lead_id).all())
    return max(opens, key=lambda l: (last.get(l.id) or datetime.min, l.created_at or datetime.min, l.id or 0))


def is_stop_message(text):
    """Whether the whole message only asks us to stop -- STOP, Unsubscribe, "Stop promotions" (the
    button WhatsApp puts on marketing templates), "Don't message"... -- ignoring case, spaces and
    punctuation. A longer message is somebody talking, not opting out."""
    t = re.sub(r'[^\w\s]', '', (text or '').lower()).replace('_', ' ')
    return ' '.join(t.split()) in WA_STOP_WORDS


def _stop_note(text):
    return 'They asked for no more WhatsApp messages ("%s"). %s' % (' '.join((text or '').split())[:40], WA_LEFT_OUT)


def wa_opt_out(person, lead=None, note=None, at=None):
    """They asked for no more WhatsApp messages (a STOP reply, or WhatsApp's own opt-out): kept on
    the person, noted on their lead, and after the save their contact gets the "opted-out" tag,
    which the WhatsApp CRM's broadcasts, automations and AI reply leave out. True when this is new."""
    if person.wa_opt_out_at is not None:
        return False
    person.wa_opt_out_at = at or datetime.utcnow()
    if lead is not None and note:
        log_touch(lead, 'note', 'none', body=note, at=at)
    if not mark_wa_due(person) and (person.phone or person.wacrm_contact_id):
        # even while WhatsApp is off here: the tag waits, and goes once it is switched on
        person.wacrm_sync_due_at = person.wacrm_sync_due_at or datetime.utcnow()
    return True


def wa_opt_in(person, lead=None, user=None):
    """An admin opted them back in (they asked to hear from us again): the opt-out is cleared, a
    note says who, and after the save their contact loses the "opted-out" tag -- the one tag the
    sync never takes off by itself, so wa_opt_in_due asks for it once. True when this is new."""
    if person.wa_opt_out_at is None:
        return False
    person.wa_opt_out_at = None
    person.wa_opt_in_due = True
    if lead is not None:
        log_touch(lead, 'note', 'none', body=OPTED_IN_NOTE % (user.full_name if user else 'an admin'),
                  activity=False)
    if not mark_wa_due(person) and (person.phone or person.wacrm_contact_id):
        person.wacrm_sync_due_at = person.wacrm_sync_due_at or datetime.utcnow()   # waits for writes on
    return True


def wa_body(text, content_type=None):
    """What a WhatsApp message is kept as: its words, with the kind in front for a photo, document,
    voice note and the like ("[image] look at this"), so the lead page can say "Photo"."""
    t = (text or '').strip()
    ct = (content_type or '').strip().lower()
    if ct in WA_MEDIA_LABELS or ct in WA_REPLY_TYPES:
        return '[%s] %s' % (ct, t) if t else '[%s]' % ct
    return t or '[%s]' % (ct or 'message')


def wa_media(body):
    """What a kept body was, for the timeline: ('media', label, words), ('button', None, words),
    ('template', label, '') or (None, None, body) for plain words."""
    b = body or ''
    m = _WA_PREFIX.match(b)
    if m:
        kind = m.group(1)
        rest = b[m.end():]
        if kind == 'template':
            return 'template', 'Approved template', ''
        if kind in WA_REPLY_TYPES:
            return 'button', None, (rest or (m.group(2) or '')).strip()
        label = WA_MEDIA_LABELS.get(kind) or ('Message' if kind == 'message' else kind.capitalize())
        return 'media', label, rest.strip()
    if b.startswith('Template: '):
        return 'template', 'Approved template', ''
    return None, None, b


def record_whatsapp_in(contact_id=None, conversation_id=None, phone=None, name=None, wamid=None,
                       text=None, content_type=None, at=None, chat_has_assignee=None):
    """Somebody wrote to us on WhatsApp: the webhook's message.received, or the jobs runner
    catching up on one it missed (`at`: when they wrote). On the right lead:

      an open lead          their reply (record_reply), on the lead we last wrote to (wa_lead_for)
      only closed leads     logged on the latest and its owner told -- or, when it closed over
                            30 days ago, a new lead from the WhatsApp source. Never reopened.
      nobody here           a new lead from the WhatsApp source (WACRM_SOURCE_KEY)
      STOP and the like     logged, and they are opted out (wa_opt_out) instead of moving on

    A chat we had not seen for somebody already here goes to their lead's owner after the save,
    only if nobody in the WhatsApp CRM has it. Calls nothing outside; commits.
    'logged' | 'closed' | 'new_lead' | 'created' | 'opted_out' | 'duplicate' | 'ignored' | 'failed'."""
    if wamid and CrmTouchpoint.query.filter_by(external_id=wamid).first():
        return 'duplicate'
    cid = str(contact_id).strip()[:64] if contact_id else None
    body = wa_body(text, content_type)
    stop = is_stop_message(text)
    when = at or datetime.utcnow()
    person = wa_person(cid, phone)
    if person is None:
        return _wa_newcomer(cid, conversation_id, phone, name, wamid, body, stop, text, at)
    new_chat = wa_link(person, cid, conversation_id, phone, name)
    _wa_inbound.pop(_digits(person.phone), None)      # they just wrote: the next free text asks again
    lead = wa_lead_for(person)
    if lead is not None:
        if stop:
            log_touch(lead, 'whatsapp', 'in', body=body, external_id=wamid, at=at)
            result = 'opted_out' if wa_opt_out(person, lead, _stop_note(text), at=at) else 'logged'
        else:
            record_reply(lead, body, channel='whatsapp', external_id=wamid, at=at)
            result = 'logged'
    else:
        latest = max(person.leads, default=None,
                     key=lambda l: (l.closed_at or l.last_activity_at or l.created_at or datetime.min, l.id or 0))
        closed = latest.closed_at or latest.last_activity_at or when if latest is not None else None
        if stop:
            if latest is not None:
                log_touch(latest, 'whatsapp', 'in', body=body, external_id=wamid, at=at)
            wa_opt_out(person, latest, _stop_note(text), at=at)
            result = 'opted_out'
        elif latest is None or closed <= when - WA_NEW_LEAD_AFTER:
            key = current_app.config.get('WACRM_SOURCE_KEY') or 'wa-india'
            if capture_safely(key, person=person, channel='whatsapp', message=body, utm={},
                              external_id=wamid, when=at) is None:
                return 'failed'
            result = 'new_lead'
        else:
            log_touch(latest, 'whatsapp', 'in', body=body, external_id=wamid, at=at)
            _tell_closed_owner(latest)
            result = 'closed'
    if new_chat and not chat_has_assignee:
        mark_wa_due(person, assign_if_free=True)
    db.session.commit()
    return result


def _wa_newcomer(cid, conversation_id, phone, name, wamid, body, stop, text, at):
    """Somebody the Sales CRM does not have: a lead from the WhatsApp source -- or, when all they
    said is stop (to a WhatsApp CRM broadcast), no lead, but their no is kept on a person."""
    e164 = wa_e164(phone)
    if not (e164 or cid):
        return 'ignored'
    # a WhatsApp user id with no number still reaches them through the CRM
    ids = [('wacrm', cid)] if cid else None
    if stop:
        person = upsert_person(e164, None, _wa_name(name), identities=ids)
        wa_link(person, cid, conversation_id, phone)
        wa_opt_out(person, at=at)
        db.session.commit()
        return 'opted_out'
    key = current_app.config.get('WACRM_SOURCE_KEY') or 'wa-india'
    lead = capture_safely(key, name=_wa_name(name), phone=e164, message=body, channel='whatsapp', utm={},
                          external_id=wamid, identities=ids, when=at, sync=False)
    if lead is None:
        return 'failed'
    wa_link(lead.person, cid, conversation_id, phone)
    mark_wa_due(lead.person)      # their contact and tags, after the save -- the ids above are kept first
    db.session.commit()
    return 'created'


def _tell_closed_owner(lead):
    if not lead.owner_id:
        return
    from app.services import notify
    notify.push(lead.owner_id, 'crm_lead', title='%s wrote on WhatsApp' % lead.person.display_name,
                body='Their %s lead is closed (%s), so it was not reopened. Answer in the WhatsApp chat, '
                     'or add a new lead if they want something new.'
                     % (crm_products.labels().get(lead.product, lead.product), lead.status),
                link=_lead_link(lead))


def wa_failure_text(code=None, title=None, person=None):
    """What to tell the agent when WhatsApp did not deliver their message: Meta's own reason
    (error_code / error_title on the status event), in plain words for the common ones."""
    if code == 131047:
        return WA_WINDOW_CLOSED + WA_TRY_ELSE
    if code == 131049:
        if person is not None and us_number(person.phone):
            return ('WhatsApp does not deliver marketing messages to this number (US numbers are paused by '
                    'Meta). Call or e-mail them, or answer when they write.')
        return ('WhatsApp held back this marketing message: Meta limits how many marketing messages one '
                'person gets. Try again in a few days, or call them.')
    if code == WA_OPT_OUT_CODE:
        return ('They stopped marketing messages from us in WhatsApp, so they are marked as opted out. '
                'Call them, or answer when they write.')
    if (title or '').strip():
        return 'WhatsApp says: %s.%s' % (str(title).strip().rstrip('.')[:160], WA_TRY_ELSE)
    return 'Usually their last message is over 24 hours old.' + WA_TRY_ELSE


# ======================================================================================= tasks

WAIT_NOTE = 'Waiting for the date'                 # a follow-up whose date was taken away (skipped, re-planned later)
DATE_PHRASES = {'departure_date': 'the travel date', 'ends_on': 'the date the cover ends'}
WAIT_TITLE = 'Needs %s'                             # "Needs the travel date"
WAIT_FOR_DATE = 'Add %s to plan %d follow-up%s'     # "Add the travel date to plan 1 follow-up"
REPLAN_MOVED = '%d follow-up%s moved to %s'         # "2 follow-ups moved to 10 Nov"
REPLAN_MOVED_MANY = '%d follow-ups moved; the next is on %s'
REPLAN_PLANNED = '%d follow-up%s planned for %s'
REPLAN_WAITS = '%d follow-up%s now wait%s for %s'   # "1 follow-up now waits for the travel date"


def lead_fields(pipeline):
    """The details asked in this pipeline (CrmField rows for every pipeline, and its own), one per key,
    the pipeline's own winning; in order."""
    q = CrmField.query
    if pipeline is not None:
        q = q.filter(or_(CrmField.pipeline_id.is_(None), CrmField.pipeline_id == pipeline.id))
    else:
        q = q.filter(CrmField.pipeline_id.is_(None))
    out = {}
    for f in q.order_by(CrmField.position, CrmField.id).all():
        if f.key not in out or f.pipeline_id is not None:
            out[f.key] = f
    return list(out.values())


def date_fields(pipeline):
    """[(key, label)] of every date a follow-up or a move can count from: the trip's two, then the
    date details of the pipeline."""
    return list(CRM_DATE_FIELDS.items()) + [(f.key, f.label) for f in lead_fields(pipeline) if f.type == 'date']


def date_phrase(field, pipeline=None):
    """"the travel date" -- the words for a date in a sentence."""
    if field in DATE_PHRASES:
        return DATE_PHRASES[field]
    f = next((f for f in lead_fields(pipeline) if f.key == field), None)
    if f is not None and f.label:
        return 'the ' + f.label[:1].lower() + f.label[1:]
    return 'the ' + (field or 'date').replace('_', ' ')


def lead_date(lead, field):
    """A date of the lead: the trip's two are columns, any other is a detail ("YYYY-MM-DD"). None when
    missing or not a date."""
    if field in CRM_DATE_FIELDS:
        return getattr(lead, field, None)
    v = (lead.details or {}).get(field)
    try:
        return datetime.strptime(str(v), '%Y-%m-%d').date() if v else None
    except ValueError:
        return None


def step_date_field(step):
    """Which date a step counts from, or None (hours after the last step). Reads the old trigger
    names too: rows from before s5crm009."""
    trig = getattr(step, 'trigger', None)
    if trig == 'date_offset':
        return getattr(step, 'trigger_field', None) or 'departure_date'
    return CRM_LEGACY_TRIGGERS.get(trig)


def step_offset_days(step):
    """Days from the date: negative is before it."""
    v = step.trigger_value or 0
    if step.trigger == 'date_offset':
        return v
    return -v if step.trigger in CRM_LEGACY_TRIGGERS else 0


def _due(step, lead, base):
    """When a follow-up is due: hours after `base`, or 9 am India time N days before / after a date of
    the lead -- never before `base`. None when that date is missing: it waits for it (no 24-hour guess)."""
    field = step_date_field(step)
    if field:
        anchor = lead_date(lead, field)
        if anchor is None:
            return None
        at = datetime.combine(anchor + timedelta(days=step_offset_days(step)), time(9, 0)) - IST   # 9 am in India
        return max(at, base)
    return base + timedelta(hours=step.trigger_value or 0)


def _next_step(stage, after=None):
    steps = list(stage.steps or []) if stage else []
    if after is None:
        return steps[0] if steps else None
    return next((s for s in steps if s.position > after.position), None)


def plan_next(lead, after_step=None, base=None):
    """Put the stage's next step on the owner's list. Returns the task, or None at the end -- or while
    the next one waits for a date the lead does not have yet."""
    if lead.source and lead.source.status == 'paused':
        return None
    step = _next_step(lead.stage, after_step)
    if step is None:
        return None
    base = base or datetime.utcnow()
    due = _due(step, lead, base)
    if due is None:
        return None
    task = CrmTask(lead=lead, step=step, code=step.code, title=step.title, channel=step.channel,
                   auto=bool(step.auto), due_at=due, owner_id=lead.owner_id)
    db.session.add(task)
    db.session.flush()
    return task


def _pending_step(lead):
    """(step done last, the step that comes next) for a lead with nothing open or being sent in its
    stage, from its loaded tasks; None when there is no stage, something is open, or its source is paused."""
    if lead.stage is None or (lead.source and lead.source.status == 'paused'):
        return None
    if any(t.status in ('open', 'sending') and t.is_step for t in lead.tasks):
        return None
    since = lead.entered_stage_at or datetime.min
    done = [t for t in lead.tasks if t.step is not None and t.step.stage_id == lead.stage_id
            and (t.created_at or datetime.min) >= since and t.note != WAIT_NOTE]
    after = max(done, key=lambda t: (t.created_at or datetime.min, t.id or 0)).step if done else None
    step = _next_step(lead.stage, after)
    return (after, step) if step is not None else None


def _waiting(lead):
    """(step done last, the next step, the date it needs) when the next follow-up waits for a date."""
    pend = _pending_step(lead)
    if pend is None:
        return None
    after, step = pend
    field = step_date_field(step)
    if field and lead_date(lead, field) is None:
        return after, step, field
    return None


def waiting_line(lead):
    """{'title', 'text', 'field', 'label'} for the lead card when the next follow-up needs a date the
    lead lacks ("Needs the travel date" / "Add the travel date to plan 1 follow-up"), else None."""
    w = _waiting(lead)
    if w is None:
        return None
    _after, step, field = w
    n = sum(1 for s in lead.stage.steps if s.position >= step.position and step_date_field(s) == field)
    phrase = date_phrase(field, lead.pipeline)
    return {'title': WAIT_TITLE % phrase, 'text': WAIT_FOR_DATE % (phrase, n, '' if n == 1 else 's'),
            'field': field, 'label': CRM_DATE_FIELDS.get(field)}


def _day_text(dt):
    d = (dt + IST).date()
    return '%d %s' % (d.day, d.strftime('%b'))


def replan_dates(lead, fields, now=None):
    """Dates of this lead changed (departure_date, ends_on, a date detail): every open follow-up that counts
    from one gets its new time; one whose date was taken away waits again (skipped as WAIT_NOTE); one that
    waited is planned now. Moves by themselves read the date at each jobs run, so they follow anyway.
    Conditional UPDATEs: a follow-up being sent (status "sending") is never touched. The toast, or None."""
    now = now or datetime.utcnow()
    moved, planned, waiting, wait_field = [], [], 0, None
    for t in list(lead.tasks):
        if t.status != 'open' or t.step is None or step_date_field(t.step) not in fields:
            continue
        due = _due(t.step, lead, now)
        if due is None:
            n = (CrmTask.query.filter(CrmTask.id == t.id, CrmTask.status == 'open')
                 .update({'status': 'skipped', 'done_at': now, 'note': WAIT_NOTE}, synchronize_session=False))
            if n:
                waiting += 1
                wait_field = step_date_field(t.step)
        elif due != t.due_at:
            n = (CrmTask.query.filter(CrmTask.id == t.id, CrmTask.status == 'open')
                 .update({'due_at': due}, synchronize_session=False))
            if n:
                moved.append(due)
        db.session.expire(t)
    pend = _pending_step(lead)
    if pend is not None:
        after, step = pend
        if step_date_field(step) in fields and _due(step, lead, now) is not None:
            t = plan_next(lead, after_step=after, base=now)
            if t is not None:
                planned.append(t.due_at)
    if moved:
        everything = moved + planned
        days = {_day_text(d) for d in everything}
        if len(days) == 1:
            return REPLAN_MOVED % (len(everything), '' if len(everything) == 1 else 's', days.pop())
        return REPLAN_MOVED_MANY % (len(everything), _day_text(min(everything)))
    if planned:
        return REPLAN_PLANNED % (len(planned), '' if len(planned) == 1 else 's', _day_text(min(planned)))
    if waiting:
        return REPLAN_WAITS % (waiting, '' if waiting == 1 else 's', 's' if waiting == 1 else '',
                               date_phrase(wait_field, lead.pipeline))
    return None


def uses_date(pipeline, field):
    """Whether a follow-up or a move by itself of this pipeline counts from `field` (one query)."""
    if pipeline is None:
        return False
    if any(st.auto_field == field for st in pipeline.stages):
        return True
    return (db.session.query(CrmPlaybookStep.id).join(CrmStage, CrmStage.id == CrmPlaybookStep.stage_id)
            .filter(CrmStage.pipeline_id == pipeline.id, CrmPlaybookStep.trigger == 'date_offset',
                    CrmPlaybookStep.trigger_field == field).first() is not None)


def next_step_code(pipeline, kind):
    """A new follow-up's code: its kind's prefix (PI, CE, BW, FM, PM, ER, PF; FU for other), or for a
    first contact the pipeline's product code, with the next free number in that pipeline ("TI #5")."""
    from app.services.crm_defaults import STEP_KIND_CODES
    prefix = STEP_KIND_CODES.get(kind) or (pipeline.product if pipeline else crm_products.general_code())
    pat = re.compile(r'^%s(?:\s*#\s*(\d+))?$' % re.escape(prefix), re.I)
    used = [int(m.group(1) or 1) for st in (pipeline.stages if pipeline else []) for s_ in st.steps
            for m in [pat.match((s_.code or '').strip())] if m]
    return '%s #%d' % (prefix, max(used) + 1 if used else 1)


def _plural(n):
    return '' if n == 1 else 's'


def _date_words(field, pipeline, n):
    """The words after the days: "before they travel", "after the cover ends", "on <label>"."""
    sign = 'before' if n < 0 else 'after' if n > 0 else 'on'
    if field == 'departure_date':
        return {'before': 'before they travel', 'after': 'after they travel', 'on': 'on the day they travel'}[sign]
    if field == 'ends_on':
        return {'before': 'before the cover ends', 'after': 'after the cover ends',
                'on': 'on the day the cover ends'}[sign]
    f = next((f for f in lead_fields(pipeline) if f.key == field), None)
    label = f.label if f is not None else (field or 'the date').replace('_', ' ')
    return '%s %s' % (sign, label)


def step_when(step):
    """When a follow-up happens, in words: "right away", "2 days after the last follow-up",
    "3 days before they travel"."""
    field = step_date_field(step)
    if field:
        n = step_offset_days(step)
        pipe = step.stage.pipeline if getattr(step, 'stage', None) is not None else None
        words = _date_words(field, pipe, n)
        return words if n == 0 else '%d day%s %s' % (abs(n), _plural(abs(n)), words)
    v = step.trigger_value or 0
    if v == 0:
        return 'right away'
    if v % 24 == 0:
        return '%d day%s after the last follow-up' % (v // 24, _plural(v // 24))
    return '%d hour%s after the last follow-up' % (v, _plural(v))


def step_sentence(step):
    """A follow-up in words, for How we sell: 'WhatsApp “Welcome” right away, goes by itself'."""
    out = '%s “%s” %s' % (CRM_CHANNEL_LABELS.get(step.channel, step.channel), step.title, step_when(step))
    return out + (', goes by itself' if step.auto and step.channel == 'whatsapp' else '')


def auto_sentence(stage):
    """What a stage does by itself, in words: 'moves by itself after 3 days with no reply, to Closed'."""
    kind, days = stage.auto_kind, stage.auto_days or 0
    if kind == 'departed':
        kind = 'after_date'
    to = stage.auto_to.name if stage.auto_to else ''
    if kind == 'no_reply':
        return 'moves by itself after %d day%s with no reply, to %s' % (days, _plural(days), to)
    if kind == 'in_stage':
        return 'moves by itself after %d day%s in this stage, to %s' % (days, _plural(days), to)
    field = stage.auto_field or 'departure_date'
    when = (_date_words(field, stage.pipeline, 0) if days == 0
            else '%d day%s %s' % (days, _plural(days), _date_words(field, stage.pipeline, 1)))
    return 'moves by itself %s, to %s' % (when, to)


def auto_move_words(stage):
    """When a stage moves its leads by itself: "after 3 days with no reply", "after 7 days in this stage",
    "2 days after they travel"."""
    kind, days = stage.auto_kind, stage.auto_days or 0
    if kind == 'departed':
        kind = 'after_date'
    if kind == 'no_reply':
        return 'after %d day%s with no reply' % (days, _plural(days))
    if kind == 'in_stage':
        return 'after %d day%s in this stage' % (days, _plural(days))
    field = stage.auto_field or 'departure_date'
    if days == 0:
        return _date_words(field, stage.pipeline, 0)
    return '%d day%s %s' % (days, _plural(days), _date_words(field, stage.pipeline, 1))


def auto_text(stage):
    """What a stage does by itself, in words: "7 days without a reply → Closed"."""
    kind, field = stage.auto_kind, stage.auto_field or 'departure_date'
    if kind == 'departed':
        kind = 'after_date'
    days = stage.auto_days or 0
    if kind == 'no_reply':
        words = 'without a reply'
    elif kind == 'in_stage':
        words = 'in this stage'
    elif field == 'departure_date':
        words = 'after travel'
    elif field == 'ends_on':
        words = 'after the cover ends'
    else:
        f = next((f for f in lead_fields(stage.pipeline) if f.key == field), None)
        words = 'after %s' % (f.label if f is not None else field.replace('_', ' '))
    return '%d day%s %s → %s' % (days, _plural(days), words, stage.auto_to.name if stage.auto_to else '')


def complete_task(task, user=None, skipped=False, note=None):
    """An open step, or one being sent (status "sending"). The next step is planned only while the
    lead is still in this step's stage."""
    if task.status not in ('open', 'sending'):
        return None
    task.status = 'skipped' if skipped else 'done'
    task.done_at = datetime.utcnow()
    task.done_by_id = getattr(user, 'id', None)
    task.note = (note or '')[:200] or None
    if not task.is_step:
        return None          # a task, call or meeting someone added by hand: nothing is planned after it
    task.lead.last_activity_at = task.done_at
    if task.step_id is None and task.code is None:
        return None          # a follow-up made by hand ("Call back") plans nothing when it is done
    if task.step is not None and task.lead.stage_id is not None and task.step.stage_id != task.lead.stage_id:
        return None          # the lead moved on while it was being sent: its new stage has its own plan
    return plan_next(task.lead, after_step=task.step)


def snooze_task(task, hours=24):
    task.due_at = max(task.due_at, datetime.utcnow()) + timedelta(hours=hours)


# ======================================================================================= stages

def move_stage(lead, stage, user=None, reason=None, fallout_reason=None, plan=True, sync=True):
    if stage is None or stage.pipeline_id != lead.pipeline_id or stage.id == lead.stage_id:
        return False
    now = datetime.utcnow()
    for t in lead.tasks:
        if t.status == 'open' and t.is_step:          # a task someone added by hand stays
            t.status, t.done_at, t.note = 'skipped', now, 'Stage changed'
    change = CrmStageChange(lead=lead, from_stage_id=lead.stage_id, to_stage_id=stage.id,
                            by_id=getattr(user, 'id', None), reason=(reason or fallout_reason or '')[:160] or None)
    db.session.add(change)
    lead.stage = stage
    lead.entered_stage_at = now
    lead.sla_alerted_at = None
    lead.last_activity_at = now
    lead.status = stage.kind
    lead.closed_at = now if stage.kind in ('won', 'lost') else None
    lead.fallout_reason = (fallout_reason or None) if stage.kind == 'lost' else None
    if stage.kind == 'won':
        crm_money.lead_won(lead, today=(now + IST).date())
    db.session.flush()
    # automation rules ("a lead moves to a stage", "won", "lost") and the score: after the commit (crm_rules)
    from app.services import crm_rules, crm_scoring
    crm_rules.fire('stage_changed', lead, 'stage:%d' % change.id, to_stage_id=stage.id)
    if stage.kind in ('won', 'lost'):
        crm_rules.fire(stage.kind, lead, '%s:%d' % (stage.kind, change.id))
    crm_scoring.touched(lead)
    if plan:
        plan_next(lead, base=now)
    # their WhatsApp contact's stage tag follows, once this is saved (the owner did not change)
    if sync:
        mark_wa_due(lead.person)
    return True


def set_pipeline(lead, pipeline, user=None):
    """Route an unrouted lead (or move it to another pipeline): first stage, first step."""
    if pipeline is None:
        return
    for t in lead.tasks:
        if t.status == 'open' and t.is_step:
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
    mark_wa_due(lead.person)


# ======================================================================================= touches

def log_touch(lead, channel, direction='out', body=None, code=None, outcome=None, user=None,
              status=None, external_id=None, at=None, activity=True, via=None):
    """`at`: when it happened, for one learnt about late (the jobs runner catching up on a WhatsApp
    message); now otherwise. `activity` False: a line for the record (who looks after the lead, an
    opt-in) that does not count as the lead being worked on. `via`: who sent an outbound message
    (CRM_VIA); a person's own when `user` is given."""
    when = at or datetime.utcnow()
    via = via or ('person' if direction == 'out' and user is not None else None)
    tp = CrmTouchpoint(lead=lead, person_id=lead.person_id, channel=channel, direction=direction,
                       body=(body or None), code=code, outcome=outcome, status=status, via=via,
                       agent_id=getattr(user, 'id', None), external_id=external_id, created_at=when)
    db.session.add(tp)
    if activity:
        lead.last_activity_at = max(lead.last_activity_at or when, when) if at else when
    if direction == 'out' and status != 'failed':
        from app.services.crm_metrics import REPLY_CHANNELS
        if channel in REPLY_CHANNELS:
            # our answer ends their wait: the waiting bell may ring again next time, and a snooze is over
            for l in lead.person.leads:
                if l.waiting_alerted_at is not None or l.snoozed_until is not None:
                    l.waiting_alerted_at = l.snoozed_until = None
    db.session.flush()
    from app.services import crm_scoring
    crm_scoring.touched(lead)                    # a reply, a quote sent...: the score is worked out after the commit
    return tp


def record_reply(lead, text=None, channel='whatsapp', external_id=None, at=None):
    """The person answered. Logged, and out of the first stage it promotes the lead. `at`: when
    they wrote, for a reply learnt about late."""
    log_touch(lead, channel, 'in', body=text, external_id=external_id, at=at)
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


# ======================================================================================= lead details

def clean_detail(field, value):
    """(value, why) for a lead detail typed on screen: the value worked out for the field's type, or why not."""
    t = field.type
    if t == 'date':
        v = value.strip() if isinstance(value, str) else ('' if value is None else str(value))
        try:
            if v:
                datetime.strptime(v, '%Y-%m-%d')
        except ValueError:
            return None, 'Use a real date.'
        return v, None
    if t == 'number':
        try:
            return (float(value) if str(value if value is not None else '').strip() != '' else ''), None
        except (TypeError, ValueError):
            return None, 'Use a number.'
    if t == 'choice':
        v = value.strip() if isinstance(value, str) else ''
        if v and v not in (field.options or []):
            return None, 'Choose one of the choices.'
        return v, None
    if t == 'yesno':
        if isinstance(value, bool):
            return value, None
        word = str(value if value is not None else '').strip().lower()
        if word in ('yes', 'true', '1', 'on'):
            return True, None
        if word in ('no', 'false', '0', 'off'):
            return False, None
        return '', None
    return str(value if value is not None else '').strip()[:300], None


def detail_text(field, value):
    """A lead detail as it reads on the card."""
    if value in (None, '', [], {}):
        return '—'
    if field.type == 'date':
        try:
            d = datetime.strptime(str(value), '%Y-%m-%d')
            return '%d %s %d' % (d.day, d.strftime('%b'), d.year)
        except ValueError:
            return str(value)
    if field.type == 'yesno':
        return 'Yes' if value is True or str(value).lower() in ('yes', 'true', '1') else 'No'
    if field.type == 'number':
        try:
            return '%g' % float(value)
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def card_fields(lead):
    """[(field, value)] the lead card shows: the pipeline's details marked "Show on the lead card"."""
    have = lead.details or {}
    return [(f, have.get(f.key)) for f in lead_fields(lead.pipeline) if f.on_card]


def other_details(lead):
    """[(label, value)] of the details a lead has that no field of its pipeline shows on the card."""
    fields = {f.key: f for f in lead_fields(lead.pipeline)}
    shown = {f.key for f in fields.values() if f.on_card}
    out = []
    for k, v in (lead.details or {}).items():
        if k.startswith('_') or k in shown:
            continue
        f = fields.get(k)
        out.append((f.label if f is not None else k.replace('_', ' ').capitalize(), v))
    return out


def add_fields(tiles):
    """{product code: [fields asked when adding a lead]} for the tiles on Add a lead; '' is "Something else"."""
    out = {p.code: [f for f in lead_fields(crm_products.default_pipeline(p.code)) if f.on_add] for p in tiles}
    out[''] = [f for f in lead_fields(crm_products.default_pipeline(None)) if f.on_add]
    return out


# ======================================================================================= messages

def first_name(text):
    return (text or '').strip().split(' ')[0] if text else ''


def fill_values(lead, user=None):
    """{token: value} for this lead -- what {name}, {agent} ... become, in a message or in a
    template's blanks."""
    from app.services import offices
    owner = lead.owner or user
    values = {
        'name': first_name(lead.person.name) or 'there',
        'agent': first_name(getattr(owner, 'first_name', None) or getattr(owner, 'username', None))
                 or 'the NRI Parent Service team',
        'product': crm_products.labels().get(lead.product, '').lower(),
        'departure': lead.departure_date.strftime('%d %b') if lead.departure_date else 'soon',
        'days': lead.days_to_departure if lead.days_to_departure is not None else 'a few',
        'ends': lead.ends_on.strftime('%d %b') if lead.ends_on else 'soon',
        'helplines': ', '.join('%s (%s)' % (n['display'], n['label']) for n in offices.numbers()[:3])
                     or 'our helpline',
    }
    site = (current_app.config.get('SITE_URL') or '').rstrip('/')
    from app.services import urls
    for var, endpoint in (('insurance_link', 'insurance.landing'), ('companion_link', 'main.all_trips'),
                          ('sahayak_link', 'sahayak.landing'), ('site_link', 'main.index')):
        try:
            values[var] = urls.site_link(endpoint)
        except Exception:      # noqa: BLE001 -- outside a request, or a route that is not there
            values[var] = site or ''
    return values


def fill_with(text, values):
    """Fill {name}, {agent} and the rest into a message from values already worked out."""
    def sub(m):
        return str(values.get(m.group(1), m.group(0)))
    return re.sub(r'\{([a-z_]+)\}', sub, text or '')


def fill(text, lead, user=None):
    """Fill {name}, {agent} and the rest into a message for this lead."""
    return fill_with(text, fill_values(lead, user)) if text else ''


def quick_replies_for(lead, user=None, limit=40):
    """The ready answers filled in for this lead, theirs (the product) first: [(answer, words)]."""
    values = fill_values(lead, user)
    rows = CrmAnswer.query.all()
    rows.sort(key=lambda a: (a.product not in (lead.product, 'GEN'), a.product != lead.product,
                             (a.title or '').lower()))
    return [(a, fill_with(a.body, values)) for a in rows[:limit]]


def suggested_reply(lead, user=None):
    """The ready answer that fits what they last wrote on WhatsApp, filled in for them, or None."""
    from app.services import crm_answers
    tp = (CrmTouchpoint.query.filter_by(person_id=lead.person_id, channel='whatsapp', direction='in')
          .order_by(CrmTouchpoint.created_at.desc(), CrmTouchpoint.id.desc()).first())
    if tp is None:
        return None
    _, _, words = wa_media(tp.body)
    if not (words or '').strip():
        return None
    hit = crm_answers.suggest(words, lead.product, limit=1)
    if not hit:
        return None
    return {'id': hit[0]['id'], 'title': hit[0]['title'], 'text': fill_with(hit[0]['body'], fill_values(lead, user))}


def whatsapp_link(lead, text):
    digits = (lead.person.phone or '').lstrip('+')
    if not digits:
        return ''
    return 'https://wa.me/%s?text=%s' % (digits, quote(text or ''))


WA_SEND_STUCK = timedelta(minutes=15)     # a step still "sending" this long waits for a person to check the chat
WA_AUTO_BUDGET = 60                       # seconds run_auto_steps may spend before it stops taking steps
WA_AUTO_LATE = timedelta(hours=24)        # an automatic step overdue longer than this waits for a click
WA_CONFIRM_FOR = timedelta(seconds=60)    # how long the WhatsApp CRM's "they last wrote at" is trusted
# Canada's area codes (NANPA, with the reserved non-geographic ones): any other +1 number is treated
# as the United States', where Meta does not deliver marketing templates
CANADA_AREA_CODES = frozenset('''
204 226 236 249 250 257 263 289 306 343 354 365 367 368 382 403 416 418 428 431 437 438 450 468
474 506 514 519 548 579 581 584 587 600 604 613 622 633 639 644 647 655 672 677 683 688 705 709
742 753 778 780 782 807 819 825 867 873 879 902 905 942'''.split())
WA_OPTED_OUT = 'They asked for no more WhatsApp messages. Call or e-mail them, or answer when they write.'
WA_US_MARKETING = 'WhatsApp does not deliver marketing templates to US numbers; call or e-mail instead.'
WA_NEEDS_OK = 'Needs a click: they have not agreed to WhatsApp messages yet'
WA_LATE = 'Was due %s; check before sending'
WA_BLANKS = 'The approved template has %s, the follow-up has %s. Make them match in Set-up → Pipelines.'
WA_WINDOW_CLOSED = 'Their last message is over 24 hours old, so WhatsApp only lets an approved template through.'
WA_WINDOW_SHUT = ('Over 24 hours since they last wrote, so WhatsApp only lets an approved template '
                  'through -- send it from your WhatsApp.')
WA_NOT_SENDING = ('Sending from here is switched off (Set-up → WhatsApp). Start the chat '
                  'in WhatsApp chats instead.')
WA_MAYBE_SENT = 'WhatsApp did not answer, so it may have gone. Check their chat before you send it again.'
WA_MAYBE_SENT_NOTE = 'May have gone: WhatsApp did not answer. Check the chat before sending again'
SEND_TAKEN = 'This step is being sent already. Look again in a minute.'
STEP_DONE = 'That step is done already. Reload the page to see what is next.'
_wa_inbound = {}      # phone digits -> (asked at, their last message to us as the WhatsApp CRM has it, chat status)

WINDOW_HOURS = 24
# the lead page's words, all in one place
MILESTONE_HINT = 'Records it and moves them to %s. Nothing is sent to the customer.'
OWNER_LINE, NOBODY = 'Looked after by: %s → %s', 'Not given to anyone'
OPTED_IN_NOTE = 'Opted back in to WhatsApp (by %s)'
OPTED_IN_SAID = 'Opted back in. Their tag is removed in WhatsApp too.'
OPTED_IN_LATER = 'Opted back in. Their tag comes off in WhatsApp once it is connected.'
WA_LINE_OFF = 'WhatsApp is not connected for leads yet'
WA_LINE_NO_PHONE = 'There is no phone number for them yet.'
WA_LINE_OPEN = 'Chat open, %s left to write freely'
WA_LINE_CLOSED = 'Only an approved template can go now'
WA_LINE_NEVER = "They haven't written yet. WhatsApp only allows an approved template first."
WA_LINE_OPTED_OUT = 'Opted out on %s. Send nothing unless they write.'
WA_LINE_OPTED_OUT_OPEN = 'Opted out on %s, but they wrote since. Chat open, %s left to answer.'
CHAT_STATUS = {'open': 'Open', 'pending': 'On hold', 'closed': 'Done'}      # shown as "Chat: Open"
SYNC_OK, SYNC_WAITING, SYNC_PROBLEM = 'In step with WhatsApp', 'Waiting to sync', 'Not in step: %s'
SYNC_NOT_ADDED = 'not added to WhatsApp yet'
BOX_OFF = 'WhatsApp is not connected for leads yet.'
BOX_CLOSED = "They haven't written in 24 hours, so WhatsApp only allows an approved template."
BOX_OPTED_OUT_OPEN = 'They opted out. You can still answer while the chat is open.'
SOCIAL_CLOSED = '%s allows replies only within 24 hours of their last message'
WA_CHAT_CLOSED = 'WhatsApp says the chat has closed. Choose an approved template.'
WA_WRONG_NUMBER = 'That chat belongs to another number. Nothing was sent.'
WA_NO_CHAT = 'WhatsApp did not make their chat. Nothing was sent.'
WA_NOT_APPROVED = 'That template is not approved by WhatsApp yet. Choose another.'
WA_FILL_INS = 'Some fill-ins are empty. Fill them in first.'
WA_WRITE_FIRST = 'Write the message first.'
WA_PICK_TEMPLATE = 'Only an approved template can go now. Choose one in the message box.'
CALL_BACK_TITLE = 'Call back'
WROTE_CHANNELS = (('wa_other', 'WhatsApp (other number)'), ('telegram', 'Telegram'), ('sms', 'SMS'),
                  ('instagram', 'Instagram'), ('facebook', 'Facebook'), ('email', 'E-mail'), ('call', 'Phone call'))
WA_HISTORY_LIMIT = 50
WA_MEDIA_LABELS = {'image': 'Photo', 'document': 'Document', 'audio': 'Voice note', 'video': 'Video',
                   'location': 'Location', 'sticker': 'Sticker', 'contacts': 'Contact card'}
WA_REPLY_TYPES = ('interactive', 'button')
_WA_PREFIX = re.compile(r'^\[(image|document|audio|video|location|sticker|contacts|interactive|button|'
                        r'template|reaction|unsupported|message)(?: ([^\]]*))?\]\s*', re.S)


def us_number(phone):
    """+1 and not Canada's: the rest of the North American plan counts as the US, the careful side."""
    d = _digits(phone)
    return len(d) == 11 and d[0] == '1' and d[1:4] not in CANADA_AREA_CODES


def _blanks_text(n):
    return '%d fill-in%s' % (n, '' if n == 1 else 's')


def _us_marketing(lead, info):
    """A marketing template (or one whose kind is not known) to a US number."""
    return us_number(lead.person.phone) and (info.get('category') or 'MARKETING') == 'MARKETING'


def _real_whatsapp_in(person_id):
    """Their own WhatsApp messages here: the ones WhatsApp gave an id (the webhook, the catch-up)."""
    return db.session.query(CrmTouchpoint.id).filter(
        CrmTouchpoint.person_id == person_id, CrmTouchpoint.channel == 'whatsapp',
        CrmTouchpoint.direction == 'in', CrmTouchpoint.external_id.isnot(None), CrmTouchpoint.external_id != '')


def _wa_last_inbound(person):
    """(known, when they last wrote or None) as the WhatsApp CRM has it -- found by their number the
    way a send finds them; create=False writes nothing and ignores assign_email. Asked at most once
    a minute per number. (False, None) when it cannot say."""
    from app.services import wacrm, wacrm_team
    digits = _digits(person.phone)
    if not digits or not wa_team_on():
        return False, None
    now = datetime.utcnow()
    hit = _wa_inbound.get(digits)
    if hit is not None and now - hit[0] < WA_CONFIRM_FOR:
        return True, hit[1]
    try:
        with wacrm.short_timeouts():
            r = wacrm_team.ensure_conversation(digits, create=False) or {}
    except wacrm_team.TeamError as exc:
        log.info('WhatsApp CRM could not say when the number ending %s last wrote: %s', digits[-4:], exc)
        return False, None
    last = _parse_utc(r.get('last_inbound_at')) if r.get('conversation_id') else None
    if len(_wa_inbound) > 500:
        _wa_inbound.clear()
    _wa_inbound[digits] = (now, last, r.get('status') if r.get('conversation_id') else None)
    return True, last


def _wa_cached_inbound(person, now=None):
    """(known, last, chat status) from what the WhatsApp CRM said in the last minute; (False, None,
    None) when nothing fresh is kept. No call."""
    hit = _wa_inbound.get(_digits(person.phone))
    if hit is not None and (now or datetime.utcnow()) - hit[0] < WA_CONFIRM_FOR:
        return True, hit[1], (hit[2] if len(hit) > 2 else None)
    return False, None, None


def whatsapp_window_open(lead, now=None, confirm=False):
    """Whether they wrote on WhatsApp in the last 24 hours -- the only time WhatsApp lets a
    business send free text. After that only an approved template goes through.

    Only their real WhatsApp messages count, never a note, a form, a typed-in reply or a lead made
    by hand; after they opted out, only what they wrote since. `confirm`: the WhatsApp CRM, which
    keeps Meta's clock, is asked too (at most once a minute per number), just before free text goes."""
    now = now or datetime.utcnow()
    since = now - timedelta(hours=WINDOW_HOURS)
    out_at = lead.person.wa_opt_out_at
    if out_at is not None and out_at > since:
        since = out_at          # after opting out only what they wrote since counts (not the STOP itself)
    if _real_whatsapp_in(lead.person_id).filter(CrmTouchpoint.created_at > since).first() is None:
        return False
    if not confirm:
        return True
    known, last = _wa_last_inbound(lead.person)
    # it cannot say: our own record (its server refuses free text outside the 24 hours anyway)
    return (last is not None and last > since) if known else True


def _template_held(lead, name, step):
    """Why an approved template is not used for them, or None: a marketing one to a US number, or
    one with other blanks than the step's words make."""
    from app.services import wa_templates
    info = wa_templates.template_info(name)
    if _us_marketing(lead, info):
        return WA_US_MARKETING
    have, want = info.get('variables'), (wa_templates.step_blanks(step) if step is not None else 0)
    if have is not None and have != want:
        return WA_BLANKS % (_blanks_text(have), _blanks_text(want))
    return None


def send_plan(lead, step=None, confirm=False, by_hand=False, window_open=None):
    """How a WhatsApp message for this lead would go out, decided once for the button and the
    automatic run alike: {'mode': 'template' | 'text' | 'link' | 'blocked', 'template', 'reason'}.

      template  the step has a template Meta approved: it goes, whenever they last wrote
      text      no approved template, but they wrote in the last 24 hours: free text goes
      link      neither (or the WhatsApp CRM is not sending): the agent's own WhatsApp opens
      blocked   not on WhatsApp at all; the reason says what to do instead: they opted out and
                have not written since, or a marketing template to a US number

    Screens leave `confirm` off, so nothing is asked while a page draws; a send asks the WhatsApp
    CRM when they last wrote (whatsapp_window_open). `by_hand`: a person presses Send in the lead
    page's box, so "Keep contacts in step" is enough (not only "send follow-ups"). `window_open`: whether
    their chat is open, already known (My day, from one batched query): nothing is asked."""
    from app.services import wa_templates
    name = step.wa_template if step is not None else None
    person = lead.person

    def _window(confirm=confirm):
        return window_open if window_open is not None else whatsapp_window_open(lead, confirm=confirm)
    if not person.phone:
        return {'mode': 'link', 'template': name, 'reason': 'There is no phone number for them.'}
    opted_out = person.wa_opt_out_at is not None
    if not (wa_writes_on() if by_hand else wa_can_send()):
        if opted_out and not _window(False):
            return {'mode': 'blocked', 'template': name, 'reason': WA_OPTED_OUT}
        return {'mode': 'link', 'template': name, 'reason': ''}
    held = None
    if name and not opted_out and wa_templates.approved(name):
        held = _template_held(lead, name, step)
        if held is None:
            return {'mode': 'template', 'template': name, 'reason': ''}
    if _window():
        return {'mode': 'text', 'template': name, 'reason': ''}
    if opted_out:
        return {'mode': 'blocked', 'template': name, 'reason': WA_OPTED_OUT}
    if held == WA_US_MARKETING:
        return {'mode': 'blocked', 'template': name, 'reason': held}
    if held:
        return {'mode': 'link', 'template': name, 'reason': held}
    if by_hand:
        return {'mode': 'link', 'template': name, 'reason': WA_PICK_TEMPLATE}
    if name:
        status = wa_templates.statuses().get(name)
        why = ('its template "%s" is %s' % (name, status.lower())) if status else \
              ('its template "%s" is not in WhatsApp yet' % name)
    else:
        why = 'this step has no WhatsApp template'
    return {'mode': 'link', 'template': name,
            'reason': 'Over 24 hours since they last wrote, and %s -- send it from your WhatsApp.' % why}


def _claim_send(task, now=None):
    """Take a step for sending: committed before WhatsApp is called, so a second click, the other
    worker or an overlapping jobs run finds it taken. `done_at` holds when it was taken, until it
    is done. False when it was not open any more."""
    n = (CrmTask.query.filter(CrmTask.id == task.id, CrmTask.status == 'open')
         .update({'status': 'sending', 'done_at': now or datetime.utcnow()}, synchronize_session=False))
    db.session.commit()
    return bool(n)


def _release_send(task, note=None):
    """WhatsApp certainly did not send it: the step is open again (with why, when there is a why)."""
    vals = {'status': 'open', 'done_at': None}
    if note:
        vals['note'] = note[:200]
    (CrmTask.query.filter(CrmTask.id == task.id, CrmTask.status == 'sending')
     .update(vals, synchronize_session=False))
    db.session.commit()


def _note_send(task, note):
    (CrmTask.query.filter(CrmTask.id == task.id, CrmTask.status == 'sending')
     .update({'note': note[:200]}, synchronize_session=False))
    db.session.commit()


def _wa_refusal(exc):
    if getattr(exc, 'code', None) == 'window_closed':
        return WA_WINDOW_CLOSED
    return str(exc) or 'WhatsApp did not take it'


def _wa_send(task, call):
    """One send through the WhatsApp CRM, its step taken first (_claim_send). Everything it needs is
    worked out before; only the call sits between the claim and the outcome.

      'sent', wamid    done by the caller
      'taken'          somebody else is sending (or sent) this step: nothing went
      'unsure', exc    no answer, or a server fault after Meta: it may have gone, so the step stays
                       "sending" for a person to check (stuck_sends) and is never sent again by itself
      'down', exc      no connection was ever made: nothing went, the step is open as it was
      'refused', exc   it said no (Meta refused, the 24 hours, a bad number): open again, with why
    """
    from app.services import wacrm
    if task is not None and not _claim_send(task):
        return 'taken', None
    try:
        return 'sent', call()
    except wacrm.WacrmError as exc:
        if (exc.status is None and exc.reached) or ((exc.status or 0) >= 500 and exc.code != 'meta_error'):
            if task is not None:
                _note_send(task, WA_MAYBE_SENT_NOTE)       # stays "sending": a person checks (stuck_sends)
            log.warning('WhatsApp send for step %s may have gone: %s', getattr(task, 'id', None), exc)
            return 'unsure', exc
        if task is not None:
            _release_send(task, None if exc.status is None else 'WhatsApp did not send it: %s' % _wa_refusal(exc))
        return ('down' if exc.status is None else 'refused'), exc


def _send_outcome(outcome, exc):
    if outcome == 'taken':
        return {'mode': 'taken', 'reason': SEND_TAKEN}
    if outcome == 'unsure':
        return {'mode': 'unsure', 'reason': WA_MAYBE_SENT}
    return {'mode': 'down' if outcome == 'down' else 'failed', 'reason': _wa_refusal(exc)}


def send_step(lead, task, user=None, text=None, plan=None, auto=False):
    """Carry out a WhatsApp step: through its approved template, as free text inside the 24-hour
    window, or as a wa.me link otherwise. Logged and ticked off once it went. `auto`: the jobs
    runner, which never gets a link (nobody would press send).
    Returns {'mode': 'sent' | 'link' | 'blocked' | 'taken' | 'unsure' | 'failed' | 'down',
    'via'?: 'template' | 'text', 'url'?, 'reason'?}."""
    from app.services import wacrm, wa_templates
    step = task.step if task is not None else None
    body = text if text is not None else fill(step.body if step and step.body else (task.title if task else ''),
                                             lead, user)
    plan = plan or send_plan(lead, step, confirm=True)
    code = task.code if task is not None else None
    if plan['mode'] == 'blocked':
        return {'mode': 'blocked', 'reason': plan['reason']}
    if plan['mode'] == 'template':
        phone, name = lead.person.phone, plan['template']
        params = wa_templates.step_params(step, fill_values(lead, user))      # worked out before the claim
        outcome, value = _wa_send(task, lambda: wacrm.send_template(phone, name, language=wa_templates.LANGUAGE,
                                                                     params=params))
        if outcome != 'sent':
            return _send_outcome(outcome, value)
        # the timeline shows the approved words, filled in with the values that went
        body = wa_templates.template_text(name, params) or body
        log_touch(lead, 'whatsapp', 'out', body=body, code=code, user=user, status='sent', external_id=value,
                  via='auto' if auto else None)
        if task is not None:
            complete_task(task, user=user)
        db.session.commit()
        return {'mode': 'sent', 'via': 'template'}
    if plan['mode'] == 'text':
        result = send_whatsapp(lead, body, user=user, code=code, task=task, checked=True, auto=auto)
        result['via'] = 'text'
        return result
    if auto:
        return {'mode': 'failed', 'reason': plan.get('reason') or 'no approved template'}
    result = send_whatsapp_link(lead, body, user=user, code=code, task=task)
    if plan.get('reason'):
        result['reason'] = plan['reason']
    return result


def send_whatsapp_link(lead, text, user=None, code=None, task=None):
    """The agent sends it from their own WhatsApp: a wa.me link with the words in, logged."""
    log_touch(lead, 'whatsapp', 'out', body=text, code=code, user=user, status='opened')
    if task is not None:
        complete_task(task, user=user)
    db.session.commit()
    return {'mode': 'link', 'url': whatsapp_link(lead, text)}


def send_whatsapp(lead, text, user=None, code=None, task=None, checked=False, auto=False):
    """Free text through the WhatsApp CRM only while it is sending and they wrote in the last 24
    hours, confirmed with it first unless send_plan just did (`checked`); otherwise a wa.me link
    for the agent's own WhatsApp, logged and the task ticked off. Nothing at all to somebody who
    opted out and has not written since. `auto`: the jobs runner, which never gets a link.

    Returns {'mode': 'sent'}, {'mode': 'link', 'url', 'reason'?}, or one that did not go
    ('blocked' | 'taken' | 'unsure' | 'failed' | 'down', with 'reason').
    """
    from app.services import wacrm
    person = lead.person
    result = {'mode': 'link', 'url': whatsapp_link(lead, text)}
    if wa_can_send() and person.phone:
        if checked or whatsapp_window_open(lead, confirm=True):
            phone = person.phone
            outcome, value = _wa_send(task, lambda: wacrm.send_text(phone, text))
            if outcome != 'sent':
                return _send_outcome(outcome, value)
            log_touch(lead, 'whatsapp', 'out', body=text, code=code, user=user, status='sent', external_id=value,
                      via='auto' if auto else None)
            if task is not None:
                complete_task(task, user=user)
            db.session.commit()
            return {'mode': 'sent'}
        if person.wa_opt_out_at is not None:
            return {'mode': 'blocked', 'reason': WA_OPTED_OUT}
        result['reason'] = WA_WINDOW_SHUT
    elif person.wa_opt_out_at is not None and not whatsapp_window_open(lead):
        return {'mode': 'blocked', 'reason': WA_OPTED_OUT}
    if auto:
        return {'mode': 'failed', 'reason': result.get('reason') or WA_NOT_SENDING}
    log_touch(lead, 'whatsapp', 'out', body=text, code=code, user=user, status='opened')
    if task is not None:
        complete_task(task, user=user)
    db.session.commit()
    return result


class WaChatRefused(Exception):
    """The lead page's chat could not be made safely. `kind`: no_phone | ambiguous | wrong_number |
    invalid | failed | down. The message is the sentence for the agent."""
    def __init__(self, message, kind='failed'):
        super().__init__(message)
        self.kind = kind


def wa_ensure_chat(person, create=True, assign_email=None, now=None):
    """Their contact and chat in the WhatsApp CRM (contract 1): made when missing (create), given to
    assign_email only if nobody has it, and certainly theirs -- the number it answers for is theirs
    by W1's rule (same_whatsapp_number: a contact saved without its country code is the same
    number, a different number is refused), and no other person here holds that contact. The ids
    are kept through wa_link. The dict ensure answered ({} when create=False found nothing).
    Raises WaChatRefused. No commit."""
    from app.services import wacrm_team
    digits = _digits(person.phone)
    if len(digits) < 8:
        raise WaChatRefused(WA_LINE_NO_PHONE, 'no_phone')
    try:
        r = wacrm_team.ensure_conversation(digits, name=_real_name(person), email=person.email, create=create,
                                           assign_email=(assign_email if create else None)) or {}
    except wacrm_team.TeamError as exc:
        if exc.code == 'ambiguous_contact' or exc.status == 409:
            raise WaChatRefused(WA_ERRORS['ambiguous_contact'], 'ambiguous')
        if exc.code == 'invalid_phone':
            raise WaChatRefused(WA_ERRORS['invalid_phone'], 'invalid')
        if exc.code == 'not_configured':
            raise WaChatRefused(WA_ERRORS['not_configured'], 'failed')
        raise WaChatRefused(str(exc) or 'WhatsApp did not answer', 'down' if exc.status is None else 'failed')
    cid = str(r.get('contact_id') or '') or None
    if cid is None:
        if create:
            raise WaChatRefused(WA_NO_CHAT, 'failed')
        return r
    if not r.get('contact_phone') or not same_whatsapp_number(digits, r['contact_phone']):
        raise WaChatRefused(WA_WRONG_NUMBER, 'wrong_number')
    if CrmPerson.query.filter(CrmPerson.wacrm_contact_id == cid, CrmPerson.id != person.id).first() is not None:
        raise WaChatRefused(WA_WRONG_NUMBER, 'wrong_number')
    wa_link(person, cid, r.get('conversation_id'), phone=r.get('contact_phone'))
    _wa_inbound[digits] = (now or datetime.utcnow(),
                           _parse_utc(r.get('last_inbound_at')) if r.get('conversation_id') else None,
                           r.get('status') if r.get('conversation_id') else None)
    return r


def send_by_hand(lead, user, kind, text=None, template=None, params=None, task=None, answer=None):
    """A message a person chose to send from the lead page's box (or the card beside WhatsApp chats):
    free text inside the 24 hours, or an approved template. Works in "Keep contacts in step" and "Keep in
    step and send follow-ups"; never in Not yet. The chat is ensured first and must be theirs (wa_ensure_chat); a follow-up it
    carries out -- the one given, else the due WhatsApp follow-up with this template -- is taken before
    it goes, so nothing goes twice, and ticked only once WhatsApp took it. Never a wa.me link.
    {'mode': 'sent' | 'unsure' | 'off' | 'blocked' | 'taken' | 'window_closed' | 'wrong_number' |
    'ambiguous' | 'invalid' | 'no_phone' | 'failed' | 'down', 'reason'?, 'via'?}"""
    from app.services import wacrm, wa_templates
    person = lead.person
    now = datetime.utcnow()
    if not wa_writes_on():
        return {'mode': 'off', 'reason': BOX_OFF}
    if not person.phone:
        return {'mode': 'no_phone', 'reason': WA_LINE_NO_PHONE}
    if task is None and kind == 'template':
        due = lead.open_task
        if (due is not None and due.channel == 'whatsapp' and due.step is not None
                and due.step.wa_template and due.step.wa_template == template):
            task = due
    if task is not None and task.status != 'open':
        return {'mode': 'taken', 'reason': SEND_TAKEN if task.status == 'sending' else STEP_DONE}
    values = None
    info = {}
    if kind == 'template':
        if person.wa_opt_out_at is not None:
            return {'mode': 'blocked', 'reason': WA_OPTED_OUT}
        if not template or not wa_templates.approved(template):
            return {'mode': 'blocked', 'reason': WA_NOT_APPROVED}
        info = wa_templates.template_info(template)
        if _us_marketing(lead, info):
            return {'mode': 'blocked', 'reason': WA_US_MARKETING}
        if params is None and task is not None and task.step is not None and task.step.wa_template == template:
            values = fill_values(lead, user)
            params = wa_templates.step_params(task.step, values)
        params = [str(p).strip() for p in params or []]
        need = info.get('variables')
        if (need is not None and len(params) != need) or any(not p for p in params):
            return {'mode': 'blocked', 'reason': WA_FILL_INS}
        words = wa_templates.template_text(template, params) or '[template %s]' % template
    else:
        text = (text or '').strip()
        if not text and task is not None:
            text = fill(task.step.body if task.step is not None and task.step.body else task.title, lead, user)
        if not text:
            return {'mode': 'blocked', 'reason': WA_WRITE_FIRST}
        text = text[:4000]
        words = text
    email = ((lead.owner.email or '') if lead.owner is not None else '').strip() or None
    try:
        r = wa_ensure_chat(person, create=True, assign_email=email, now=now)
    except WaChatRefused as exc:
        db.session.rollback()
        return {'mode': exc.kind, 'reason': str(exc)}
    db.session.commit()              # the ids are kept even if nothing goes
    digits = _digits(person.phone)
    if kind == 'text':
        out_at = person.wa_opt_out_at
        if 'last_inbound_at' in r:
            last = _parse_utc(r.get('last_inbound_at')) if r.get('conversation_id') else None
            since = max(now - timedelta(hours=WINDOW_HOURS), out_at or datetime.min)
            closed = last is None or last <= since
            never = last is None
        else:
            closed, never = not whatsapp_window_open(lead), False     # an older WhatsApp CRM: our own record
        if closed:
            if out_at is not None:
                return {'mode': 'blocked', 'reason': WA_OPTED_OUT}
            return {'mode': 'window_closed', 'reason': WA_LINE_NEVER if never else WA_CHAT_CLOSED}
    phone = person.phone
    if kind == 'template':
        language = info.get('language') or None
        outcome, value = _wa_send(task, lambda: wacrm.send_template(phone, template, language=language,
                                                                     params=params))
    else:
        outcome, value = _wa_send(task, lambda: wacrm.send_text(phone, text))
    if outcome == 'refused' and getattr(value, 'code', None) == 'window_closed':
        _wa_inbound.pop(digits, None)
        return {'mode': 'window_closed', 'reason': WA_CHAT_CLOSED}
    if outcome != 'sent':
        return _send_outcome(outcome, value)
    code = task.code if task is not None else (answer.code if answer is not None else None)
    log_touch(lead, 'whatsapp', 'out', body=words, code=code, user=user, status='sent', external_id=value)
    if answer is not None:
        answer.use_count = (answer.use_count or 0) + 1
    if task is not None:
        complete_task(task, user=user)
    db.session.commit()
    return {'mode': 'sent', 'via': kind}


def box_templates(lead, user=None):
    """The approved templates for the lead page's box: {'known', 'error', 'items'}; each item is
    {name, label, language, body, vars, fill, blocked, warn, chosen}. The next follow-up's template
    (chosen) comes first with its fill-ins worked out. None at all for somebody who opted out."""
    from app.services import wa_templates
    known = wa_templates.heard()
    out = {'known': known, 'error': wa_templates.error() if known else None, 'items': []}
    if lead.person.wa_opt_out_at is not None or not known:
        return out
    values = fill_values(lead, user)
    task = lead.open_task
    step = task.step if task is not None and task.channel == 'whatsapp' else None
    pick = step.wa_template if step is not None else None
    kf = wa_templates.known_fills(values)
    items = []
    for t in wa_templates.approved_templates():
        name, n = t['name'], t.get('variables')
        warn = None
        if name == pick:
            fills = wa_templates.step_params(step, values)
            if n is not None and wa_templates.step_blanks(step) != n:
                warn = WA_BLANKS % (_blanks_text(n), _blanks_text(wa_templates.step_blanks(step)))
        elif name in kf:
            fills = list(kf[name]['fill'])
        else:
            fills = [values['name']] + [''] * max((n or 1) - 1, 0)
        if n is not None:
            fills = (fills + [''] * n)[:n]
        label = kf[name]['title'] if name in kf else name.replace('_', ' ')
        items.append({'name': name, 'label': label, 'language': t.get('language'), 'body': t.get('body') or '',
                      'vars': n, 'fill': fills, 'warn': warn, 'chosen': name == pick,
                      'blocked': WA_US_MARKETING if _us_marketing(lead, t) else None})
    items.sort(key=lambda i: (not i['chosen'], i['label'].lower()))
    out['items'] = items
    return out


# ======================================================================================= the lead page's strip

def ist_day_text(dt):
    d = dt + IST
    return '%d %s' % (d.day, d.strftime('%b'))


def wa_chat_state(lead, confirm=False, now=None):
    """Where their WhatsApp chat stands, for the strip and the box -- from portal data, plus what
    the WhatsApp CRM said in the last minute. `confirm` asks it (at most once a minute): only the
    live endpoint does, never the page. {'mode', 'state', 'left', 'last_in', 'opted_out_at',
    'chat_status'}; state: off | no_phone | opted_out_open | opted_out | open | never | closed."""
    from app.services import crm_metrics
    now = now or datetime.utcnow()
    mode, person = wa_mode(), lead.person
    digits = _digits(person.phone)
    last = crm_metrics.last_touches([person.id])[person.id]['wa_last_in']
    known, w_last, status = False, None, None
    if digits and mode != 'off':
        if confirm:
            known, w_last = _wa_last_inbound(person)
            status = (_wa_inbound.get(digits) or (0, 0, None))[2] if known else None
        else:
            known, w_last, status = _wa_cached_inbound(person, now)
    if known:
        last = w_last                       # the WhatsApp CRM keeps Meta's clock
    out_at = person.wa_opt_out_at
    since = max(now - timedelta(hours=WINDOW_HOURS), out_at or datetime.min)
    open_ = last is not None and last > since
    left = crm_metrics.window_left_hours(last, now) if open_ else 0
    if mode == 'off':
        state = 'off'
    elif not digits:
        state = 'no_phone'
    elif out_at is not None and open_:
        state = 'opted_out_open'
    elif out_at is not None:
        state = 'opted_out'
    elif open_:
        state = 'open'
    elif last is None:
        state = 'never'
    else:
        state = 'closed'
    return {'mode': mode, 'state': state, 'left': int(round(left or 0)), 'last_in': last,
            'opted_out_at': out_at, 'chat_status': status}


def wa_line(wa):
    """The sentence on the journey card's WhatsApp strip."""
    st = wa['state']
    left = '%dh' % wa['left'] if wa['left'] >= 1 else 'less than 1h'
    when = ist_day_text(wa['opted_out_at']) if wa['opted_out_at'] else ''
    return {'off': WA_LINE_OFF, 'no_phone': WA_LINE_NO_PHONE, 'open': WA_LINE_OPEN % left,
            'closed': WA_LINE_CLOSED, 'never': WA_LINE_NEVER, 'opted_out': WA_LINE_OPTED_OUT % when,
            'opted_out_open': WA_LINE_OPTED_OUT_OPEN % (when, left)}[st]


def box_note(wa):
    """The sentence above the message box ('' when the chat is open and nothing needs saying)."""
    when = ist_day_text(wa['opted_out_at']) if wa['opted_out_at'] else ''
    return {'off': BOX_OFF, 'no_phone': WA_LINE_NO_PHONE, 'opted_out': WA_LINE_OPTED_OUT % when,
            'opted_out_open': BOX_OPTED_OUT_OPEN, 'open': '', 'closed': BOX_CLOSED,
            'never': WA_LINE_NEVER}[wa['state']]


def social_windows(lead, now=None):
    """{channel: whether Meta still lets us answer there} for the Instagram / Messenger they wrote
    on: they wrote in the last 24 hours. One query. Typed-in replies carry no id, so never count."""
    chans = social_reply_channels(lead)
    if not chans:
        return {}
    since = (now or datetime.utcnow()) - timedelta(hours=WINDOW_HOURS)
    rows = dict(db.session.query(CrmTouchpoint.channel, func.max(CrmTouchpoint.created_at))
                .filter(CrmTouchpoint.person_id == lead.person_id, CrmTouchpoint.channel.in_(chans),
                        CrmTouchpoint.direction == 'in', CrmTouchpoint.external_id.isnot(None),
                        CrmTouchpoint.external_id != '')
                .group_by(CrmTouchpoint.channel).all())
    return {ch: bool(rows.get(ch) and rows[ch] > since) for ch in chans}


def _plain_sync_error(err):
    return WA_ERRORS.get(WA_ERRORS_BEFORE.get(err, ''), err)


def wa_sync_state(person, now=None):
    """Whether they are in step with the WhatsApp CRM, for admins and the owner: {'state', 'text',
    'retry'}, or None while writes are off or there is nothing to sync. No call."""
    if not wa_writes_on() or not (person.phone or person.wacrm_contact_id):
        return None
    now = now or datetime.utcnow()
    due, err = person.wacrm_sync_due_at, person.wa_sync_error
    if err and (due is None or due > now + WA_LEASE):
        return {'state': 'problem', 'text': SYNC_PROBLEM % _plain_sync_error(err), 'retry': True}
    if due is not None:
        return {'state': 'waiting', 'text': SYNC_WAITING, 'retry': False}
    if person.wa_synced_at:
        return {'state': 'ok', 'text': SYNC_OK, 'retry': False}
    return {'state': 'problem', 'text': SYNC_PROBLEM % SYNC_NOT_ADDED, 'retry': True}


# ======================================================================================= older messages

def wa_import_history(lead, now=None):
    """Their older WhatsApp messages onto the lead page, once: the latest WA_HISTORY_LIMIT of their chat
    (GET /api/v1/conversations/{id}/messages), at the times they were written, each once (by its
    WhatsApp id). Only for somebody whose chat we know and who has no WhatsApp message with an id here
    yet. History only: no stage, temperature, follow-up or "last activity" change, nothing counted in the
    numbers (status 'imported'). Taken first, so two tabs do not both do it; on any failure nothing is
    kept and the next opening of the lead page tries again. How many came in, or None."""
    from app.services import wacrm
    person = lead.person
    pid, conv = person.id, person.wacrm_conversation_id
    if not conv or person.wa_history_at is not None or not wacrm.enabled():
        return None
    if db.session.query(CrmTouchpoint.id).filter(
            CrmTouchpoint.person_id == pid, CrmTouchpoint.channel == 'whatsapp',
            CrmTouchpoint.external_id.isnot(None), CrmTouchpoint.external_id != '').first() is not None:
        return None
    now = now or datetime.utcnow()
    lead_id = lead.id
    n = (CrmPerson.query.filter(CrmPerson.id == pid, CrmPerson.wa_history_at.is_(None))
         .update({'wa_history_at': now}, synchronize_session=False))
    db.session.commit()
    if not n:
        return None
    try:
        with wacrm.short_timeouts():
            rows = wacrm.conversation_messages(conv, limit=WA_HISTORY_LIMIT)
        rows = [r for r in reversed(list(rows or [])) if isinstance(r, dict)]
        seen, keep = set(), []
        for r in rows:
            wamid = str(r.get('whatsapp_message_id') or '').strip()[:120]
            at = _parse_utc(r.get('created_at'))
            if wamid and at and wamid not in seen:
                seen.add(wamid)
                keep.append((wamid, at, r))
        have = set()
        if seen:
            have = {w for (w,) in db.session.query(CrmTouchpoint.external_id)
                    .filter(CrmTouchpoint.external_id.in_(sorted(seen)))}
        person = db.session.get(CrmPerson, pid)
        lead = db.session.get(CrmLead, lead_id)
        target = wa_lead_for(person) or lead
        added = 0
        for wamid, at, r in keep:
            if wamid in have:
                continue
            ct = r.get('content_type')
            if ct == 'template':
                body = r.get('content_text') or '[template %s]' % (r.get('template_name') or '')
            else:
                body = wa_body(r.get('content_text'), ct)
            db.session.add(CrmTouchpoint(lead=target, person_id=pid, channel='whatsapp',
                                         direction='in' if r.get('direction') == 'inbound' else 'out',
                                         body=body[:4000], status='imported', via='import', external_id=wamid,
                                         created_at=at))
            added += 1
        db.session.commit()
        return added
    except Exception:      # noqa: BLE001 -- history is a nicety: the next opening tries again
        db.session.rollback()
        log.info('Older WhatsApp messages not brought in for person %s', pid, exc_info=True)
        (CrmPerson.query.filter(CrmPerson.id == pid, CrmPerson.wa_history_at == now)
         .update({'wa_history_at': None}, synchronize_session=False))
        db.session.commit()
        return None


def call_back_at(choice, at=None, now=None):
    """When "Call back" is for, as UTC: 'in 1 hour', 'this evening' (6 pm India time, an hour from
    now at the soonest), 'tomorrow morning' (10 am) or a time they picked ('at', as typed in
    India: 2026-10-12T17:30). None when it does not parse or is not later than now."""
    now = now or datetime.utcnow()
    today = (now + IST).date()
    if choice == '1h':
        return now + timedelta(hours=1)
    if choice == 'evening':
        return max(datetime.combine(today, time(18, 0)) - IST, now + timedelta(hours=1))
    if choice == 'morning':
        return datetime.combine(today + timedelta(days=1), time(10, 0)) - IST
    if choice == 'at':
        try:
            when = datetime.strptime((at or '').strip()[:16], '%Y-%m-%dT%H:%M') - IST
        except ValueError:
            return None
        return when if when > now else None
    return None


def first_follow_up(lead):
    """The open task when it is the first follow-up of the pipeline's first stage, else None."""
    t = lead.open_task
    if t is None or t.step is None or not lead.pipeline or lead.stage_id != lead.pipeline.first_stage.id:
        return None
    return t if t.step is _next_step(lead.stage) else None


def log_call(lead, outcome, note=None, user=None, task=None, call_back_at=None):
    """A call and how it went. Returns the number of unanswered calls in a row. `call_back_at`
    (for "Call back"): a follow-up call goes on their list for then."""
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
    if outcome == 'call_back' and call_back_at and lead.status == 'open':
        db.session.add(CrmTask(lead=lead, step=None, code=None, title=CALL_BACK_TITLE, channel='call', auto=False,
                               due_at=call_back_at, owner_id=lead.owner_id or getattr(user, 'id', None)))
    db.session.commit()
    return no_answer_streak(lead)


# ======================================================================================= jobs

def run_auto_steps(now=None, limit=200, budget=None):
    """Send the steps marked automatic that are due -- only once the WhatsApp CRM is sending, and
    only through an approved template or inside the 24-hour window Meta allows. A step that should
    not go by itself goes back on the owner's list, once, with why:

      they opted out               never sent by itself
      overdue by over a day        "Was due ...; check before sending" (switching sending on does
                                   not send the backlog)
      they are waiting for us      they wrote after it was planned: it waits (a person answers first)
      needs their OK               a first message (a template) to somebody who neither ticked
                                   WhatsApp on a form nor wrote to us, while Set-up asks for it
      WhatsApp would not take it   no approved template outside the 24 hours, a US number, other
                                   blanks, or WhatsApp said no

    Each step is taken before it goes (_wa_send), so an overlapping run never sends it twice; one
    that may have gone waits for a person (stuck_sends), and the run stops. No new steps are taken
    after WA_AUTO_BUDGET seconds: the rest go next run."""
    if not wa_can_send():
        return {'crm_auto_sent': 0}
    now = now or datetime.utcnow()
    needs_ok = crm_settings()['wa_first_needs_ok']
    started, budget = monotonic(), (WA_AUTO_BUDGET if budget is None else budget)
    sent = 0
    due = (CrmTask.query.filter(CrmTask.status == 'open', CrmTask.auto.is_(True),
                                CrmTask.channel == 'whatsapp', CrmTask.due_at <= now)
           .order_by(CrmTask.due_at).limit(limit).all())
    from app.services import crm_metrics
    touches = crm_metrics.last_touches({t.lead.person_id for t in due})
    for task in due:
        if monotonic() - started > budget:
            break                                          # the rest go next run
        try:
            lead = task.lead
            person = lead.person
            if not person.phone or lead.status == 'lost':
                # nothing to send to, or nobody to send it to any more: off the list, not retried
                _auto_skip(task, now)
                continue
            if person.wa_opt_out_at:
                # they said stop: back to the owner's list, once, and never sent by itself
                _auto_hold(task, 'Not sent automatically: they asked for no more WhatsApp messages')
                continue
            if task.due_at < now - WA_AUTO_LATE:
                _auto_hold(task, WA_LATE % (task.due_at + IST).strftime('%d %b'))
                continue
            last = (touches.get(person.id) or {}).get('reply_last')
            if last and last[1] == 'in' and last[2] > (task.created_at or datetime.min):
                continue      # they wrote after it was planned and nobody answered: it waits for a person (next run again)
            plan = send_plan(lead, task.step, confirm=True)
            if plan['mode'] in ('link', 'blocked'):
                # nothing that WhatsApp will let us send by itself: back to the owner's list, once,
                # with the reason, instead of being tried again every run
                _auto_hold(task, 'Not sent automatically: ' + (plan.get('reason') or 'no approved template'))
                continue
            if (plan['mode'] == 'template' and needs_ok and not person.consent_whatsapp
                    and _real_whatsapp_in(person.id).first() is None):
                _auto_hold(task, WA_NEEDS_OK)
                continue
            result = send_step(lead, task, plan=plan, auto=True)
            mode = result.get('mode')
            if mode == 'sent':
                sent += 1
            elif mode == 'failed':
                _auto_hold(task, 'Not sent automatically: ' + (result.get('reason') or 'WhatsApp did not take it'))
            elif mode in ('unsure', 'down'):
                break               # WhatsApp is not answering properly: nothing more this run
        except Exception:      # noqa: BLE001 -- one bad number must not stop the rest
            db.session.rollback()
            log.warning('CRM auto step %s failed', task.id, exc_info=True)
    return {'crm_auto_sent': sent, 'crm_sends_to_check': _stuck(now).count()}


def auto_send_preview(now=None):
    """What switching to "Keep in step and send follow-ups" would do now: {'now': open follow-ups marked to go
    by themselves that are due and were due within WA_AUTO_LATE (run_auto_steps may send them; each still checks
    the template, their OK and that they are not waiting on us), 'older': due longer ago (run_auto_steps puts
    those back on the owner's list and never sends them)}. Two counts."""
    now = now or datetime.utcnow()
    q = CrmTask.query.filter(CrmTask.status == 'open', CrmTask.auto.is_(True), CrmTask.channel == 'whatsapp',
                             CrmTask.due_at <= now)
    recent = q.filter(CrmTask.due_at >= now - WA_AUTO_LATE).count()
    return {'now': recent, 'older': q.filter(CrmTask.due_at < now - WA_AUTO_LATE).count()}


def _auto_hold(task, note):
    """Back on the owner's list, never sent by itself -- only while it is still open."""
    (CrmTask.query.filter(CrmTask.id == task.id, CrmTask.status == 'open')
     .update({'auto': False, 'note': note[:200]}, synchronize_session=False))
    db.session.commit()


def _auto_skip(task, now):
    (CrmTask.query.filter(CrmTask.id == task.id, CrmTask.status == 'open')
     .update({'status': 'skipped', 'done_at': now, 'note': 'Not sent automatically'}, synchronize_session=False))
    db.session.commit()


def _stuck(now=None):
    now = now or datetime.utcnow()
    return CrmTask.query.filter(CrmTask.status == 'sending',
                                or_(CrmTask.done_at.is_(None), CrmTask.done_at <= now - WA_SEND_STUCK))


def stuck_sends(now=None, limit=100):
    """Steps still "sending" WA_SEND_STUCK after they were taken -- the worker stopped mid-send, or
    WhatsApp did not say whether it went. Never sent again by themselves: a person checks the chat
    (settle_send). Oldest first, for Set-up."""
    return _stuck(now).order_by(CrmTask.done_at).limit(limit).all()


def settle_send(task, went, user=None):
    """A person checked the chat of a step stuck "sending": it went (done, next step planned) or
    it did not (back on the owner's list, never automatic again). False when it is not stuck."""
    if task.status != 'sending':
        return False
    if went:
        complete_task(task, user=user, note='Checked: it went')
    else:
        task.status, task.done_at, task.auto, task.note = 'open', None, False, 'Checked: it did not go'
    db.session.commit()
    return True


def run_stage_automations(now=None, limit=500):
    """The stages that move leads by themselves (Set-up -> Pipelines): after N days with no reply
    from them, N days in the stage, or N days after a date of the lead (the trip, the cover ending, a
    date detail). In the last two only forward -- never back to an earlier open stage -- and a closed
    lead never moves. The reason is recorded like a person's move."""
    now = now or datetime.utcnow()
    today = (now + IST).date()
    moved = 0
    for st in CrmStage.query.filter(CrmStage.auto_kind.isnot(None), CrmStage.auto_to_id.isnot(None)).all():
        days, target, kind = max(st.auto_days or 0, 0), st.auto_to, st.auto_kind
        if target is None or target.pipeline_id != st.pipeline_id or target.id == st.id:
            continue
        field = st.auto_field or 'departure_date'
        if kind == 'departed':                 # rows from before s5crm009 (none after it)
            kind, field = 'after_date', 'departure_date'
        if kind in ('in_stage', 'after_date') and not (target.kind != 'open' or target.position > st.position):
            continue                           # forward only: no loops
        q = CrmLead.query.filter(CrmLead.stage_id == st.id, CrmLead.status == 'open')
        if kind in ('no_reply', 'in_stage'):
            q = q.filter(CrmLead.entered_stage_at <= now - timedelta(days=days))
        elif kind == 'after_date' and field in CRM_DATE_FIELDS:
            col = getattr(CrmLead, field)
            q = q.filter(col.isnot(None), col <= today - timedelta(days=days))
        elif kind == 'after_date':
            q = q.filter(CrmLead.details.isnot(None))
        else:
            continue
        for lead in q.limit(limit).all():
            if kind == 'after_date' and field not in CRM_DATE_FIELDS:
                d = lead_date(lead, field)
                if d is None or d > today - timedelta(days=days):
                    continue
            if kind == 'no_reply':
                heard = (CrmTouchpoint.query.filter(CrmTouchpoint.lead_id == lead.id,
                                                    CrmTouchpoint.direction == 'in',
                                                    CrmTouchpoint.channel != 'form',
                                                    CrmTouchpoint.created_at >= lead.entered_stage_at)
                         .first())
                if heard:
                    continue
            reason = st.auto_reason or 'Moved automatically'
            # an imported lead whose person is not in the WhatsApp CRM yet stays out of it until the
            # backfill, a move by a person or a reply brings them in -- imports start no automations
            unsynced = lead.imported and not lead.person.wacrm_contact_id
            move_stage(lead, target, reason=reason + ' (automatic)',
                       fallout_reason=reason if target.kind == 'lost' else None, sync=not unsynced)
            moved += 1
    db.session.commit()
    return {'crm_auto_moved': moved}


def _wa_webhook_saved():
    return crm_settings_raw().get('wacrm_webhook') or {}


def wa_catch_up(now=None):
    """Each jobs run: the last message of every WhatsApp chat that changed since the last run
    (wacrm_team.activity), so a reply the webhook missed -- the CRM was down, or it had switched
    us off -- still reaches its lead, at the time it was written. WA_CATCHUP_LIMIT chats a run;
    the newest two minutes are left for the webhook. Only where "Connect replies" was done here.
    Their WhatsApp contacts follow through the jobs runner's sync, not one thread each."""
    from app.services import settings, wacrm, wacrm_team
    if not (wacrm_team.enabled() and _wa_webhook_saved().get('id')):
        return {}
    now = now or datetime.utcnow()
    state = dict(settings.get_setting(WA_CATCHUP_KEY) or {})
    try:
        with wacrm.short_timeouts():
            page = wacrm_team.activity(state.get('since') or now - WA_CATCHUP_FIRST, limit=WA_CATCHUP_LIMIT)
    except wacrm_team.TeamError as exc:
        if exc.status == 422 and state.pop('since', None):
            settings.set_setting(WA_CATCHUP_KEY, state)      # a place it no longer understands: the last day again
        log.warning('WhatsApp CRM catch-up failed: %s', exc)
        return {'crm_wa_caught_up': 'failed'}
    items = page['items']
    wamids = [(i.get('last_inbound') or {}).get('whatsapp_message_id') for i in items]
    wamids = [w for w in wamids if w]
    known = {r[0] for r in db.session.query(CrmTouchpoint.external_id)
             .filter(CrmTouchpoint.external_id.in_(wamids)).all()} if wamids else set()
    caught, cursor = 0, state.get('since')
    with wa_sync_later():
        for item in items:
            last = _parse_utc(item.get('last_message_at'))
            if last is not None and last > now - WA_CATCHUP_SETTLE:
                break                     # still arriving: the webhook is on its way; the next run looks again
            li = item.get('last_inbound') or {}
            wamid, at = li.get('whatsapp_message_id'), _parse_utc(li.get('at'))
            if wamid and at and wamid not in known:
                try:
                    r = record_whatsapp_in(contact_id=item.get('contact_id'),
                                           conversation_id=item.get('conversation_id'),
                                           phone=item.get('contact_phone'), name=item.get('contact_name'),
                                           wamid=wamid, text=li.get('text'), content_type=li.get('content_type'),
                                           at=at, chat_has_assignee=bool(item.get('assignee_email')))
                    caught += r not in ('duplicate', 'ignored', 'failed')
                    known.add(wamid)
                except Exception:      # noqa: BLE001 -- one bad message must not stop the rest
                    db.session.rollback()
                    log.exception('WhatsApp CRM catch-up: message %s not stored', wamid)
            cursor = item.get('last_message_at') or cursor
    if cursor and cursor != state.get('since'):
        state.update(since=cursor, at=now.isoformat(timespec='seconds'))
        settings.set_setting(WA_CATCHUP_KEY, state)
    return {'crm_wa_caught_up': caught}


def wa_webhook_health(now=None):
    """At most hourly: is our webhook still on in the WhatsApp CRM? It switches an address off
    after 15 failed deliveries in a row, and then every reply is missed. Switched back on (not
    while WhatsApp is off here) and the admins told -- once an incident, at most once a day.
    Only where "Connect replies" was done here."""
    from app.services import settings, wacrm
    hook = _wa_webhook_saved()
    if not (wacrm.enabled() and hook.get('id')):
        return {}
    now = now or datetime.utcnow()
    state = dict(settings.get_setting(WA_HEALTH_KEY) or {})
    checked = _parse_utc(state.get('checked_at'))
    if checked is not None and now - checked < WA_HEALTH_EVERY:
        return {}
    state['checked_at'] = now.isoformat(timespec='seconds')
    problem = None
    try:
        with wacrm.short_timeouts():
            rows = wacrm.list_webhooks() or []
            ours = (next((w for w in rows if str(w.get('id')) == str(hook['id'])), None)
                    or next((w for w in rows if hook.get('url') and w.get('url') == hook['url']), None))
            if ours is None:
                problem = 'missing'
            elif ours.get('is_active') is False:
                problem = 'off'
                if wa_writes_on():
                    wacrm.switch_webhook_on(ours['id'])
                    problem = 'switched_on'
    except wacrm.WacrmError as exc:
        log.warning('WhatsApp CRM webhook check failed: %s', exc)
        if problem is None:
            settings.set_setting(WA_HEALTH_KEY, state)
            return {'crm_wa_webhook': 'unreachable'}
    if problem is None:
        state['problem'] = None
    else:
        told = _parse_utc(state.get('told_at'))
        if state.get('problem') is None and (told is None or now - told >= WA_HEALTH_RETELL):
            from app.services import notify
            title, body = WA_HOOK_BELLS[problem]
            for u in User.query.filter(User.is_admin.is_(True), User.is_active.is_(True)).all():
                notify.push(u.id, 'crm_failed', title=title, body=body, link='/admin/crm/connection')
            state['told_at'] = now.isoformat(timespec='seconds')
        state['problem'] = problem
    settings.set_setting(WA_HEALTH_KEY, state)      # commits the bells too
    return {'crm_wa_webhook': problem or 'ok'}


WA_RULES_KEY = 'crm_wa_rules'         # own settings row: checked_at, seen_at, conflicts [{id, name, why}], told [id], old
WA_RULES_EVERY = timedelta(hours=24)
RULE_STRIP_ONE = '⚠ 1 reply rule may repeat our follow-ups: “%s”'
RULE_STRIP_MANY = '⚠ %d reply rules may repeat our follow-ups: %s'
RULE_BELL = 'A reply rule may repeat our follow-ups'
RULE_BELL_BODY = '“%s” %s. Pause it in Reply rules, or check it does not repeat a follow-up.'


def is_sales_tag(name):
    """A tag the Sales CRM writes (contract 16's rule as this portal keeps it): a product, a stage tag, a source
    tag (retired ones too) or "opted-out"."""
    n = (name or '').strip().lower()
    return n == OPT_OUT_TAG or _wa_is_portal_tag(n, _wa_source_tags())


def rule_conflict(item):
    """Why a WhatsApp reply rule may repeat our follow-ups, in words, or None: it is on, it sends a message
    (contract 4 `sends`), and it starts when a Sales tag is added, a chat is given to someone, a new contact is
    made, or on a schedule for everyone or for people with a Sales tag (a schedule on free tags only is left out:
    nothing the Sales CRM does adds people to it)."""
    if not (item.get('active') and item.get('sends')):
        return None
    kind = item.get('trigger_type')
    tags = [str(t) for t in item.get('trigger_tags') or []]
    sales = next((t for t in tags if is_sales_tag(t)), None)
    if kind == 'tag_added' and sales:
        return 'sends when “%s” is added' % sales
    if kind == 'time_based':
        if not tags:
            return 'sends on a schedule to everyone'
        if sales:
            return 'sends on a schedule to people tagged “%s”' % sales
        return None
    if kind == 'conversation_assigned':
        return 'sends when a chat is given to someone'
    if kind == 'new_contact_created':
        return 'sends when a new contact is made'
    return None


def rule_conflicts(items):
    """[{'id', 'name', 'why'}] for the reply rules rule_conflict flags, in the WhatsApp CRM's order."""
    out = []
    for item in items or []:
        why = rule_conflict(item)
        if why:
            out.append({'id': str(item.get('id')), 'name': str(item.get('name') or ''), 'why': why})
    return out


def rule_strip(conflicts):
    """The one-line warning for a list of conflicts: RULE_STRIP_ONE / RULE_STRIP_MANY (three names, then ...)."""
    if not conflicts:
        return ''
    if len(conflicts) == 1:
        return RULE_STRIP_ONE % conflicts[0]['name']
    shown = ', '.join('“%s”' % c['name'] for c in conflicts[:3]) + (' …' if len(conflicts) > 3 else '')
    return RULE_STRIP_MANY % (len(conflicts), shown)


def remember_rule_conflicts(items, now=None):
    """A page just read the reply rules: keep their conflicts for the Reply rules frame (no bell; the daily
    check rings). Saves its row (commits). Returns the conflicts."""
    from app.services import settings
    now = now or datetime.utcnow()
    conflicts = rule_conflicts(items)
    state = dict(settings.get_setting(WA_RULES_KEY) or {})
    state.update(conflicts=conflicts, seen_at=now.isoformat(timespec='seconds'), old=False)
    settings.set_setting(WA_RULES_KEY, state)
    return conflicts


def known_rule_conflicts():
    """The conflicts last seen (a page or the daily check), without asking the WhatsApp CRM: (conflicts, when)."""
    from app.services import settings
    state = settings.get_setting(WA_RULES_KEY) or {}
    conflicts = [c for c in state.get('conflicts') or [] if isinstance(c, dict) and c.get('id')]
    return conflicts, _parse_utc(state.get('seen_at'))


def check_automation_conflicts(now=None):
    """The jobs runner, once a day: read the WhatsApp CRM's reply rules (contract 4) and ring the admins once for
    each NEW rule that may repeat our follow-ups (RULE_BELL). Only where the WhatsApp team link is set up.
    {} when it is not time yet or not connected; {'crm_reply_rules': n | 'old' | 'failed'}.
    It also rings, once per rule, when an automation rule's stage move fights a stage's own automatic move (the
    workspace being run; crm_rules.ring_conflicts): {'crm_rule_conflicts': n} when there are any."""
    from app.services import crm_rules, crm_scope, notify, settings, wacrm, wacrm_team
    out = {}
    try:
        clashes = crm_rules.ring_conflicts(now)
        if clashes:
            out['crm_rule_conflicts'] = clashes
    except Exception:          # noqa: BLE001 -- the reply-rule check below still runs
        db.session.rollback()
        log.warning('Checking automation rules against stage moves failed', exc_info=True)
    if not (wacrm_team.enabled() and wacrm_team.linked_workspace() is not None and crm_scope.wa_here()):
        return out
    now = now or datetime.utcnow()
    state = dict(settings.get_setting(WA_RULES_KEY) or {})
    checked = _parse_utc(state.get('checked_at'))
    if checked is not None and now - checked < WA_RULES_EVERY:
        return out
    try:
        with wacrm.short_timeouts():
            items = wacrm_team.automations()
    except wacrm_team.TeamError as exc:
        if exc.status == 404:                    # an older WhatsApp CRM: no list, nothing to ring about
            state.update(old=True, checked_at=now.isoformat(timespec='seconds'))
            settings.set_setting(WA_RULES_KEY, state)
            return {**out, 'crm_reply_rules': 'old'}
        log.warning('Reply rules not read from the WhatsApp CRM: %s', exc)
        return {**out, 'crm_reply_rules': 'failed'}     # checked_at stays: the next run tries again
    conflicts = rule_conflicts(items)
    told = {str(i) for i in state.get('told') or []}
    admins = User.query.filter(User.is_admin.is_(True), User.is_active.is_(True)).all()
    for c in conflicts:
        if c['id'] in told:
            continue
        for u in admins:
            notify.push(u.id, 'crm_rules', title=RULE_BELL, body=RULE_BELL_BODY % (c['name'], c['why']),
                        link='/admin/crm/automatic')
    state.update(checked_at=now.isoformat(timespec='seconds'), seen_at=now.isoformat(timespec='seconds'),
                 conflicts=conflicts, told=[c['id'] for c in conflicts], old=False)
    settings.set_setting(WA_RULES_KEY, state)      # commits the bells too
    return {**out, 'crm_reply_rules': len(conflicts)}


LEGACY_MILESTONES = {'Q': 'I sent the quote', 'PLS': 'I sent the payment link'}  # old rows (WhatsApp "out" until U3)


def owner_line(before, after):
    return OWNER_LINE % (before.full_name if before else NOBODY, after.full_name if after else NOBODY)


def milestones(lead):
    """The lead page's buttons, one per stage with a "Button on the lead": [(code, label, stage name)]."""
    return [(s.button_code, s.button_label, s.name) for s in (lead.pipeline.stages if lead.pipeline else [])
            if s.button_label and s.button_code]


def milestone_stage(pipeline, code):
    """The stage of this pipeline whose button has this code, or None."""
    c = (code or '').strip().upper()
    if not c:
        return None
    return next((s for s in (pipeline.stages if pipeline else []) if s.button_label
                 and (s.button_code or '').upper() == c), None)


def milestone_ask(stage):
    """What moving into a stage with a button asks first: "Did you send the quote?" for "I sent the quote",
    else 'Log “<label>” too?'. '' without a button."""
    label = (getattr(stage, 'button_label', None) or '').strip()
    if not label or not getattr(stage, 'button_code', None):
        return ''
    if label.lower().startswith('i sent '):
        return 'Did you send %s?' % label[7:].rstrip(' .?!')
    return 'Log “%s” too?' % label


def mark_event(lead, code, user=None, note=None, amount=None, currency=None):
    """A button on the lead: a person says they did it. A system line under the stage's code -- never a
    WhatsApp message, nothing goes to the customer -- and the lead moves forward to that stage, never back.
    Returns the stage it moved to. ValueError for a code no stage of the lead's pipeline has."""
    stage = milestone_stage(lead.pipeline, code)
    if stage is None:
        raise ValueError(code)
    log_touch(lead, 'system', 'none', body=('%s: %s' % (stage.button_label, note)) if note else stage.button_label,
              code=stage.button_code, user=user)
    if amount not in (None, ''):
        crm_money.change_value(lead, amount=amount, currency=currency, user=user)
    moved = None
    if lead.status == 'open' and lead.stage and stage.position > lead.stage.position:
        move_stage(lead, stage, user=user, reason=stage.button_label)
        moved = stage
    db.session.commit()
    return moved


def answer_kind(a):
    """A quick reply's "Type (for the numbers)": '' for a plain answer (no code), else the kind its code reads as
    (crm_defaults.step_kind)."""
    if not a.code:
        return ''
    from app.services import crm_defaults
    return crm_defaults.step_kind(a.code, set(crm_products.codes()))


def answer_code(kind, product, current=None, exclude_id=None):
    """The code a quick reply gets for this type: None for a plain answer; its own code while the type still
    reads the same (HJ stays HJ under Other); else the kind's prefix (crm_defaults.STEP_KIND_CODES; a first
    contact uses the product's code), bare when no other reply has it, else "BW #2", "BW #3" ... Unknown kinds
    keep `current`."""
    if not kind:
        return None
    from app.models import CRM_STEP_KINDS
    from app.services import crm_defaults
    if kind not in CRM_STEP_KINDS:
        return current
    if current and crm_defaults.step_kind(current, set(crm_products.codes())) == kind:
        return current
    prefix = (product or crm_products.general_code()) if kind == 'first' else crm_defaults.STEP_KIND_CODES.get(kind, 'FU')
    taken = {(c or '').strip().upper() for (c,) in db.session.query(CrmAnswer.code)
             .filter(CrmAnswer.code.isnot(None), CrmAnswer.id != (exclude_id or -1)).all()}
    if prefix.upper() not in taken:
        return prefix
    n = 2
    while '%s #%d' % (prefix, n) in {t for t in taken}:
        n += 1
    return '%s #%d' % (prefix, n)


def quick_reply_used(lead, text, user=None):
    """The quick reply `text` is, as WhatsApp chats fill it in for this lead -- their first name (or "there") and
    the first name of whoever sent it or of whoever looks after the lead (or "there") -- with its use counted.
    None when it is none of them, or it was changed before it went. Replies with a lead-only fill-in are not in
    WhatsApp and are skipped."""
    from app.services import wa_templates
    said = ' '.join((text or '').split())
    if not said:
        return None
    contact = {first_name(lead.person.name) or 'there', 'there'}
    agents = {'there'}
    for u in (lead.owner, user):
        if u is None:
            continue
        for v in (first_name(getattr(u, 'first_name', None) or getattr(u, 'username', None)),
                  first_name(getattr(u, 'full_name', None))):
            if v:
                agents.add(v)
    static = wa_templates._static_values()
    for a in CrmAnswer.query.all():
        if wa_templates.lead_only(a.body):
            continue
        body = wa_templates.quick_reply_text(a.body, static)
        for c in contact:
            for g in agents:
                filled = body.replace('{{contact.first_name}}', c).replace('{{agent.first_name}}', g)
                if ' '.join(filled.split()) == said:
                    a.use_count = (a.use_count or 0) + 1
                    return a
    return None


def ready_message_code(lead, text, user=None):
    """The code of the quick reply `text` is (quick_reply_used), so it counts under that code; None otherwise."""
    a = quick_reply_used(lead, text, user)
    return a.code if a is not None else None


def quick_messages(product=None):
    """The ready messages with a code (BW, FM, HJ...), the lead's product first."""
    rows = CrmAnswer.query.filter(CrmAnswer.code.isnot(None)).all()
    rows.sort(key=lambda a: (a.product not in (product, 'GEN'), a.product != product, a.code))
    return rows


# ======================================================================================= whatsapp thread

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
            from app.services import crm_metrics, notify
            was_waiting = crm_metrics.waiting_on_us(crm_metrics.last_touches([person.id])[person.id])
            record_reply(lead, text, channel=channel, external_id=ev.get('external_id'))
            if not was_waiting and lead.owner_id and lead.status == 'open':
                # only the first message of a wait rings, so a run of messages is one bell
                notify.push(lead.owner_id, 'crm_lead',
                            title=SOCIAL_BELL % (first_name(person.display_name) or 'A customer', REPLY_LABELS[channel]),
                            body=text[:90], link=_lead_link(lead) + '?via=' + channel)
            db.session.commit()
            return lead
    return capture(channel, name=name, identities=idents, message=text, channel=channel, utm={},
                   external_id=ev.get('external_id'))


# ======================================================================================= numbers

# ======================================================================================= the daily work

# the daily work's words, all in one place
REPLY_LABELS = {'whatsapp': 'WhatsApp', 'instagram': 'Instagram', 'facebook': 'Messenger', 'email': 'E-mail'}
ROLE_STEPS = (('cold', 'New'), ('prospect', 'Talking'), ('pipeline', 'Quoted'), ('customer', 'Won'), ('lost', 'Lost'))
STEP_TIP = 'Step %d of %d: %s'
STUCK_DEFAULT_HOURS = 72          # "Stuck in a stage" for a stage with no warning hours of its own
TASK_OWN_WHATSAPP = "Open my WhatsApp (replies won't come here)"
TASK_US_BLOCKED = "WhatsApp doesn't deliver promotions to US numbers"
TASK_NO_EMAIL = 'There is no e-mail address for them yet.'
TASK_NO_WORDS = 'This follow-up has no words of its own. Write them in the message box.'
WAITING_ALERT_MINUTES = 15
WAITING_ALERT_FROM = 7            # India time: the waiting bell rings from 07:00 to midnight
WAITING_ALERT_MAX = timedelta(hours=24)   # an older wait does not ring (it is on My day anyway)
WAITING_BELL = '%s is waiting for your reply (%s)'
OWNER_BELL_CHAT = "%s's lead and WhatsApp chat are yours now"
OWNER_BELL = "%s's lead is yours now"
OWNER_BELL_EACH = 3               # up to this many leads at once: a bell each; more: one bell
OWNER_BELL_MANY = '%d leads are yours now'
OWNER_BELL_BY = 'Given to you by %s.'
HAND_BELL = "%d of %s's leads are yours now"
SOCIAL_BELL = '%s replied on %s'
UNOWNED_BELL = 'New enquiry, not given to anyone'
REPEAT_BELL = '%s sent another enquiry'
SIGNOFF_LIMIT = 40                # open chats one press reaches
SIGNOFF_BUDGET = 60               # seconds one press may spend; the rest go on the next press
SIGNOFF_SAID, SIGNOFF_ALREADY, SIGNOFF_FAILED = 'Sent to %d.', ' %d had it already today.', ' %d could not go: %s.'
SIGNOFF_NOBODY = 'Nobody on your leads has a chat open right now.'
SIGNOFF_TIME = 'Ran out of time. Press it again for the rest'
REACH_SOME, REACH_ALL, REACH_NONE = '%d of %d can get it (%s).', 'All %d can get it.', 'Nobody in this stage can get it yet.'
REACH_NO_NUMBER = ('%d has no WhatsApp number', '%d have no WhatsApp number')
REACH_OPTED = '%d opted out'
REACH_NOT_YET = ('%d is not in WhatsApp yet', '%d are not in WhatsApp yet')
BULK_GIVEN, BULK_MOVED = 'Gave %d lead%s to %s.', 'Moved %d lead%s to %s.'
BULK_OTHER_PIPE = ' %d %s in another pipeline and stayed.'
HAND_NOBODY = 'Nobody else can take their leads. Pick a person, or add somebody to Sales first.'
HAND_NOBODY_TEAM = 'Nobody in that team can take their leads. Pick another team or a person.'
TICK_LABELS = {'sent': 'Sent', 'delivered': 'Delivered', 'read': 'Read', 'failed': 'Not delivered',
               'opened': 'From own WhatsApp', 'sending': 'Sending'}


def _board_link(**args):
    try:
        from flask import url_for
        return url_for('crm.board', **args)
    except Exception:          # noqa: BLE001 -- outside a request (CLI, jobs)
        return '/cs/crm/?view=list&owner=mine'


# ------------------------------------------------------------------------------ My day's one button

def task_plan(task, text, entry=None, now=None):
    """The one button on a My day card, decided before the page draws -- with no call and no query:
    `entry` is the person's crm_metrics.last_touches() value, the templates are what the WhatsApp CRM
    last said (call it inside wa_templates.cache_only()). {'kind', 'label', 'template'?, 'reason'?,
    'alt'?}; kind: template | text | open | own | call | email | done | blocked."""
    from app.services import phone as phone_svc
    now = now or datetime.utcnow()
    lead, person = task.lead, task.lead.person
    if task.channel == 'whatsapp':
        if not person.phone:
            return {'kind': 'blocked', 'reason': WA_LINE_NO_PHONE, 'alt': 'open'}
        if task.step is None or not task.step.body:
            # made by hand or from the sales sheet: its title is never sent as a message
            return {'kind': 'open', 'label': 'Open and send', 'reason': TASK_NO_WORDS}
        last_in = (entry or {}).get('wa_last_in')
        window = bool(last_in and last_in > now - timedelta(hours=WINDOW_HOURS))
        p = send_plan(lead, task.step, by_hand=True, window_open=window)
        if p['mode'] == 'blocked':
            return {'kind': 'blocked', 'reason': TASK_US_BLOCKED if p['reason'] == WA_US_MARKETING else p['reason'],
                    'alt': 'call'}
        if not wa_writes_on():
            return {'kind': 'own', 'label': TASK_OWN_WHATSAPP}
        if p['mode'] == 'template':
            return {'kind': 'template', 'label': 'Send template', 'template': p['template']}
        if p['mode'] == 'text':
            if re.search(r'\{[a-z_]+\}', text or ''):
                return {'kind': 'open', 'label': 'Open and send', 'reason': WA_FILL_INS}
            return {'kind': 'text', 'label': 'Send'}
        return {'kind': 'open', 'label': 'Open and send', 'reason': p.get('reason') or ''}
    if task.channel == 'call':
        if person.phone:
            return {'kind': 'call', 'label': 'Call %s' % phone_svc.pretty(person.phone, person.phone)}
        return {'kind': 'blocked', 'reason': WA_LINE_NO_PHONE, 'alt': 'open'}
    if task.channel == 'email':
        if person.email:
            return {'kind': 'email', 'label': 'Write e-mail'}
        return {'kind': 'blocked', 'reason': TASK_NO_EMAIL, 'alt': 'open'}
    return {'kind': 'done', 'label': 'Done'}


# ------------------------------------------------------------------------------ who looks after a lead

def chat_follows(lead, marked):
    """Whether their WhatsApp chat goes to this lead's owner after the save (U1's rule): it was marked,
    the team link is on, and this is their most recently active open lead (_wa_main_lead)."""
    from app.services import wacrm_team
    if not (marked and lead.owner_id and wacrm_team.enabled()):
        return False
    main = _wa_main_lead(lead.person)
    return main is not None and main.owner_id == lead.owner_id


def tell_new_owner(lead, chat=False):
    """The bell for whoever looks after a lead now: "Meera's lead and WhatsApp chat are yours now" --
    "and WhatsApp chat" only when it really follows. No commit."""
    from app.services import notify
    stage = lead.stage.name if lead.stage else 'not in a pipeline yet'
    notify.push(lead.owner_id, 'crm_assigned',
                title=(OWNER_BELL_CHAT if chat else OWNER_BELL) % (first_name(lead.person.display_name) or 'A customer'),
                body='%s · %s' % (crm_products.labels().get(lead.product, lead.product), stage), link=_lead_link(lead))


def set_owner(lead, owner_id, by=None, ring=True, mark=True, chat=None):
    """Give a lead to somebody (None: Not given to anyone): a line on its history, its open follow-ups
    with it, and -- after the save, with `mark` -- its WhatsApp chat (mark_wa_due assign). Rings the new
    owner when it was not their own doing (`by` is somebody else, or nobody). `chat`: whether the chat
    is theirs, when the caller knows (an inbox assignment). (changed, chat follows). No commit."""
    owner_id = owner_id or None
    if owner_id == lead.owner_id:
        return False, False
    after = db.session.get(User, owner_id) if owner_id else None
    log_touch(lead, 'system', 'none', body=owner_line(lead.owner, after), user=by, activity=False)
    lead.owner = after
    for t in lead.tasks:
        if t.status == 'open' and t.is_step:          # a task given to someone by hand stays theirs
            t.owner_id = owner_id
    marked = mark_wa_due(lead.person, assign=True) if mark else False
    if chat is None:
        chat = chat_follows(lead, marked)
    if ring and owner_id and owner_id != getattr(by, 'id', None):
        tell_new_owner(lead, chat=chat)
    return True, chat


def tell_given(items, by=None):
    """Bells for leads given in one go (bulk "Give to…"): up to OWNER_BELL_EACH a person, a bell each;
    more, one bell. `items`: [(lead, chat follows)]. Never the giver's own. No commit."""
    from app.services import notify
    by_owner = {}
    for lead, chat in items:
        if lead.owner_id and lead.owner_id != getattr(by, 'id', None):
            by_owner.setdefault(lead.owner_id, []).append((lead, chat))
    for uid, rows in by_owner.items():
        if len(rows) <= OWNER_BELL_EACH:
            for lead, chat in rows:
                tell_new_owner(lead, chat=chat)
        else:
            notify.push(uid, 'crm_assigned', title=OWNER_BELL_MANY % len(rows),
                        body=OWNER_BELL_BY % (by.full_name if by else 'WhatsApp'),
                        link=_board_link(view='list', owner='mine'))


def hand_over(user, to=None, team=None, by=None):
    """Somebody leaves: their open leads and open follow-ups go to `to`, or one by one to whoever is
    least busy (fewest open leads, as assign_owner) in `team` -- or among everybody who works leads.
    Their chats follow (set_owner marks assign). Each receiver gets one bell. Raises ValueError
    (HAND_NOBODY / HAND_NOBODY_TEAM) when nobody can take them. (leads, follow-ups) moved. No commit."""
    from app.services import cs_access, notify
    leads = (CrmLead.query.filter(CrmLead.owner_id == user.id, CrmLead.status == 'open')
             .order_by(CrmLead.last_activity_at.desc()).all())
    tasks = CrmTask.query.filter(CrmTask.owner_id == user.id, CrmTask.status == 'open').all()
    if not leads and not tasks:
        return 0, 0
    if to is not None:
        pool = [to]
    elif team is not None:
        pool = [u for u in cs_access.recipients('crm_board', limit=None) if u in team.users and u.id != user.id]
        if not pool:
            raise ValueError(HAND_NOBODY_TEAM)
    else:
        pool = [u for u in _owner_candidates(None) if u.id != user.id]
        if not pool:
            pool = [u for u in User.query.filter(User.is_admin.is_(True), User.is_active.is_(True)).all()
                    if u.id != user.id]
        if not pool:
            raise ValueError(HAND_NOBODY)
    ids = [u.id for u in pool]
    loads = dict(db.session.query(CrmLead.owner_id, func.count(CrmLead.id))
                 .filter(CrmLead.owner_id.in_(ids), CrmLead.status == 'open').group_by(CrmLead.owner_id).all())
    got = {}
    for lead in leads:
        u = min(pool, key=lambda x: (loads.get(x.id, 0), x.id))
        _changed, chat = set_owner(lead, u.id, by=by, ring=False)
        loads[u.id] = loads.get(u.id, 0) + 1
        got.setdefault(u.id, []).append((lead, chat))
    for t in tasks:
        if t.owner_id == user.id:
            lead_owner = t.lead.owner_id if t.lead is not None else None
            t.owner_id = lead_owner if lead_owner not in (None, user.id) else pool[0].id
    for uid, rows in got.items():
        if uid == getattr(by, 'id', None):
            continue
        if len(rows) == 1:
            tell_new_owner(rows[0][0], chat=rows[0][1])
        else:
            notify.push(uid, 'crm_assigned',
                        title=HAND_BELL % (len(rows), first_name(user.full_name) or user.email),
                        body=OWNER_BELL_BY % (by.full_name if by else 'an admin'),
                        link=_board_link(view='list', owner='mine'))
    return len(leads), len(tasks)


# ------------------------------------------------------------------------------ stuck in a stage

def stuck_filter(now=None):
    """SQL: an open lead with no stage move for its stage's warning hours (Set-up -> Pipelines), else
    STUCK_DEFAULT_HOURS -- "Stuck in a stage". One query for the stages; use it in a filter."""
    now = now or datetime.utcnow()
    stages = CrmStage.query.filter_by(kind='open').all()
    return and_(CrmLead.status == 'open',
                or_(*[and_(CrmLead.stage_id == s.id,
                           CrmLead.entered_stage_at <= now - timedelta(hours=s.sla_hours or STUCK_DEFAULT_HOURS))
                      for s in stages] or [false()]))


def stuck_for(lead, now=None):
    """Hours since its last stage move when it is stuck (stuck_filter's rule), else None. No query."""
    st = lead.stage
    if lead.status != 'open' or st is None or st.kind != 'open' or not lead.entered_stage_at:
        return None
    hours = ((now or datetime.utcnow()) - lead.entered_stage_at).total_seconds() / 3600
    return int(hours) if hours >= (st.sla_hours or STUCK_DEFAULT_HOURS) else None


def stuck_text(hours):
    return '%d hours' % hours if hours < 48 else '%d days' % (hours // 24)


# ------------------------------------------------------------------------------ Leads: board and list

def lead_load():
    """The loader options for a list of leads: person (with identities), owner, stage, and where it came from
    and who added it, in the same trip, so a card or row never asks for them one lead at a time."""
    return (joinedload(CrmLead.person).selectinload(CrmPerson.identities), joinedload(CrmLead.owner),
            joinedload(CrmLead.stage), joinedload(CrmLead.source), joinedload(CrmLead.created_by))


# Leads' filter panel: which date to filter on, its ready-made ranges (India days: looking back for
# when they came in or were last active, looking ahead for when they close or travel), follow-ups
LEAD_DATES = (('created', 'Came in'), ('activity', 'Last activity'), ('close', 'Expected to close'),
              ('travel', 'Travels on'))
PAST_RANGES = (('today', 'Today'), ('yesterday', 'Yesterday'), ('7d', 'Last 7 days'), ('30d', 'Last 30 days'),
               ('month', 'This month'), ('lastmonth', 'Last month'))
AHEAD_RANGES = (('passed', 'Already passed'), ('today', 'Today'), ('next7', 'Next 7 days'),
                ('next30', 'Next 30 days'), ('month', 'This month'), ('nextmonth', 'Next month'))
FOLLOW_FILTERS = (('late', 'Late'), ('today', 'Due today'), ('none', 'Nothing planned'))


def date_ranges(field):
    return AHEAD_RANGES if field in ('close', 'travel') else PAST_RANGES


def date_range_choices():
    """Both sets as one row of choices, in an order that reads right for either: [(word, label, 'past ahead')]."""
    past, ahead = dict(PAST_RANGES), dict(AHEAD_RANGES)
    order = ('passed', 'today', 'yesterday', '7d', '30d', 'next7', 'next30', 'month', 'lastmonth', 'nextmonth')
    return [(k, past.get(k) or ahead[k], ' '.join(n for n, s in (('past', past), ('ahead', ahead)) if k in s))
            for k in order]


def date_span(rng, today, d1=None, d2=None):
    """(first day, the day after the last) of a Leads date range, as India dates; None leaves that end open.
    'custom' is d1..d2, both days included."""
    one = timedelta(days=1)
    first = today.replace(day=1)
    following = (first + timedelta(days=32)).replace(day=1)
    return {'custom': (d1, d2 + one if d2 else None),
            'today': (today, today + one), 'yesterday': (today - one, today),
            '7d': (today - timedelta(days=6), today + one), '30d': (today - timedelta(days=29), today + one),
            'month': (first, following), 'lastmonth': ((first - one).replace(day=1), first),
            'next7': (today, today + timedelta(days=7)), 'next30': (today, today + timedelta(days=30)),
            'nextmonth': (following, (following + timedelta(days=32)).replace(day=1)),
            'passed': (None, today)}.get(rng, (None, None))


def _iso_day(v):
    try:
        d = date.fromisoformat(str(v or '')[:10])
    except ValueError:
        return None
    return d if 2000 <= d.year <= 2100 else None


def lead_more_words(a, now=None):
    """Leads' panel words beyond the first few, checked, for the board, the list and Download this list:
    ({word: value or None}, the lead_filter() arguments they make). dt: which date (LEAD_DATES; 'created' is
    left out); dr: a range of that date's set, or 'custom' with d1 / d2 (YYYY-MM-DD, either may be blank);
    src: a lead source id, 'g:<group>' (a group of the lead sources' list) or 'none'; lk: how likely
    (CRM_LIKELIHOOD); how: how it came (crm_sources.ORIGINS: organic, manual, imported)."""
    from app.models import CRM_LIKELIHOOD
    now = now or datetime.utcnow()
    dt = a.get('dt') if a.get('dt') in dict(LEAD_DATES) else 'created'
    d1, d2 = _iso_day(a.get('d1')), _iso_day(a.get('d2'))
    dr = a.get('dr') or ''
    if dr != 'custom' and dr not in dict(date_ranges(dt)):
        dr = 'custom' if (d1 or d2) and not dr else ''        # typed dates without choosing "Custom"
    if dr == 'custom':
        if d1 and d2 and d1 > d2:
            d1, d2 = d2, d1
        if not (d1 or d2):
            dr = ''
    if dr != 'custom':
        d1 = d2 = None
    start, until = date_span(dr, (now + IST).date(), d1, d2) if dr else (None, None)
    from app.services import crm_sources
    src = a.get('src') or ''
    src = src if src == 'none' or (src.isdigit() and len(src) < 10) or src[2:] in crm_sources.GROUP_NAMES else ''
    lk = a.get('lk') if a.get('lk') in CRM_LIKELIHOOD else ''
    how = a.get('how') if a.get('how') in crm_sources.ORIGIN else ''
    words = {'dt': dt if dt != 'created' else None, 'dr': dr or None,
             'd1': d1.isoformat() if d1 else None, 'd2': d2.isoformat() if d2 else None,
             'src': src or None, 'lk': lk or None, 'how': how or None}
    args = {'date_on': dt if dr else None, 'date_from': start, 'date_until': until,
            'source': (int(src) if src.isdigit() else src) if src else None, 'likelihood': lk or None,
            'how': how or None}
    return words, args


def date_words_text(words):
    """The date filter in a few words, for its chip: "Came in: Last 7 days", "Travels on: 3 Nov – 10 Nov"."""
    dt = words.get('dt') or 'created'
    what = dict(LEAD_DATES)[dt]
    if words.get('dr') != 'custom':
        return '%s: %s' % (what, dict(date_ranges(dt)).get(words.get('dr'), ''))
    d1, d2 = _iso_day(words.get('d1')), _iso_day(words.get('d2'))

    def day(d):
        return '%d %s' % (d.day, d.strftime('%b')) + (' %d' % d.year if d.year != (datetime.utcnow() + IST).year else '')
    if d1 and d2:
        return '%s: %s' % (what, day(d1)) if d1 == d2 else '%s: %s – %s' % (what, day(d1), day(d2))
    return '%s: from %s' % (what, day(d1)) if d1 else '%s: until %s' % (what, day(d2))


def lead_filter(pipeline=None, owner_id=None, q=None, chat=None, stage_id=None, closed_days=30,
                follow=None, now=None, closes=None, forecast=None, no_value=False, no_close=False,
                status=None, ids=None, quoted=None, date_on=None, date_from=None, date_until=None,
                source=None, likelihood=None, how=None):
    """The leads Leads shows, as a query (none runs here): one pipeline (None: every pipeline -- the
    list only); whose (a user id, 'none' for Not given to anyone, None for anyone); a search; the chat
    filter ('waiting' | 'open' | 'nochat'); one stage; finished leads only from the last
    `closed_days` days (None: all); follow='late': an open follow-up past due, 'today': one due today (India time),
    'none': still open with no follow-up planned; quoted='week': a quote was sent in the last 7 days (the
    "Quote sent" line or a quote marked as sent); date_on (LEAD_DATES) between India days date_from and
    date_until (the day after the last; either may be None); source: a lead source id, 'g:<group>' or 'none';
    likelihood; how: organic, manual or imported (services/crm_sources.origin)."""
    from app.services import crm_metrics
    now = now or datetime.utcnow()
    query = CrmLead.query.join(CrmPerson, CrmPerson.id == CrmLead.person_id)
    pids = select(CrmLead.person_id)
    if pipeline is not None:
        query = query.filter(CrmLead.pipeline_id == pipeline.id)
        pids = pids.where(CrmLead.pipeline_id == pipeline.id)
    if owner_id == 'none':
        query = query.filter(CrmLead.owner_id.is_(None))
    elif owner_id:
        query = query.filter(CrmLead.owner_id == owner_id)
    if stage_id:
        query = query.filter(CrmLead.stage_id == stage_id)
    if closed_days:
        query = query.filter(or_(CrmLead.status == 'open',
                                 CrmLead.closed_at >= now - timedelta(days=closed_days)))
    if chat == 'waiting':
        w = crm_metrics.waiting_rows(CrmTouchpoint.person_id.in_(pids)).subquery()
        query = query.filter(CrmLead.person_id.in_(select(w.c.person_id)))
    elif chat == 'open':
        query = query.filter(CrmLead.person_id.in_(crm_metrics.window_open_people(
            CrmTouchpoint.person_id.in_(pids), now)))
    elif chat == 'nochat':
        query = query.filter(CrmPerson.wacrm_conversation_id.is_(None))
    if follow == 'late':
        query = query.filter(CrmLead.id.in_(select(CrmTask.lead_id).where(CrmTask.status == 'open',
                                                                          CrmTask.due_at < now)))
    if follow == 'today':
        start = datetime.combine((now + IST).date(), datetime.min.time()) - IST
        query = query.filter(CrmLead.id.in_(select(CrmTask.lead_id).where(
            CrmTask.status == 'open', CrmTask.due_at >= start, CrmTask.due_at < start + timedelta(days=1))))
    if follow == 'none':
        query = query.filter(CrmLead.status == 'open', CrmLead.id.notin_(select(CrmTask.lead_id).where(
            CrmTask.status == 'open', CrmTask.lead_id.isnot(None))))
    if date_on and (date_from or date_until):
        col = {'created': CrmLead.created_at, 'activity': CrmLead.last_activity_at,
               'close': CrmLead.close_date, 'travel': CrmLead.departure_date}[date_on]

        def edge(d):              # a date column takes the India day; a UTC time column, the moment it starts
            return d if date_on in ('close', 'travel') else datetime.combine(d, time.min) - IST
        if date_from:
            query = query.filter(col >= edge(date_from))
        if date_until:
            query = query.filter(col < edge(date_until))
    if source == 'none':
        query = query.filter(CrmLead.source_id.is_(None))
    elif isinstance(source, str) and source.startswith('g:'):
        from app.services import crm_sources
        ids = [s.id for s in CrmSource.query.all() if crm_sources.group_of(s) == source[2:]]
        query = query.filter(CrmLead.source_id.in_(ids or [0]))
    elif source:
        query = query.filter(CrmLead.source_id == source)
    if how == 'imported':
        query = query.filter(CrmLead.imported.is_(True))
    elif how in ('manual', 'organic'):
        # added by somebody of ours, or not (a form, a message, a customer's own post)
        from app.services import crm_sources
        makers = [r[0] for r in db.session.query(CrmLead.created_by_id).filter(CrmLead.created_by_id.isnot(None))
                  .distinct().all()]
        staff = crm_sources.staff_ids(makers)
        made_by_staff = CrmLead.created_by_id.in_(staff or [0])
        query = query.filter(CrmLead.imported.is_(False), made_by_staff if how == 'manual'
                             else or_(CrmLead.created_by_id.is_(None), ~made_by_staff))
    if likelihood:
        query = query.filter(CrmLead.likelihood == likelihood)
    if quoted == 'week':
        from app.models import CrmQuote
        since = now - timedelta(days=7)
        query = query.filter(or_(
            CrmLead.id.in_(select(CrmTouchpoint.lead_id).where(
                CrmTouchpoint.code == 'Q', CrmTouchpoint.channel == 'system', CrmTouchpoint.created_at >= since)),
            CrmLead.id.in_(select(CrmQuote.lead_id).where(CrmQuote.sent_at >= since))))
    if status in ('open', 'won', 'lost'):
        query = query.filter(CrmLead.status == status)
    if ids:
        query = query.filter(CrmLead.id.in_(list(ids)[:200]))
    if closes or forecast or no_value or no_close:
        query = crm_money.apply_filters(query, closes, forecast, no_value, no_close)
    if q:
        from app.services import crm_people
        cond = crm_people.person_match(q)
        if cond is not None:
            query = query.filter(cond)
    return query


def lead_cards(leads, now=None):
    """What each card or row shows, for many leads in three queries (never one per lead): {lead id:
    {'task', 'touch', 'chips': [(class, text, tooltip)], 'chat': (state, label), 'last_contact'}}."""
    from app.services import crm_metrics, crm_timeline
    now = now or datetime.utcnow()
    ids = [l.id for l in leads]
    if not ids:
        return {}
    tasks = {}
    for t in (CrmTask.query.options(joinedload(CrmTask.step))
              .filter(CrmTask.lead_id.in_(ids), CrmTask.status == 'open', CrmTask.kind == 'step')
              .order_by(CrmTask.due_at)):
        tasks.setdefault(t.lead_id, t)
    touches = crm_metrics.last_touches({l.person_id for l in leads})
    last = dict(db.session.query(CrmTouchpoint.lead_id, func.max(CrmTouchpoint.created_at))
                .filter(CrmTouchpoint.lead_id.in_(ids), CrmTouchpoint.direction.in_(('in', 'out')),
                        CrmTouchpoint.channel != 'form').group_by(CrmTouchpoint.lead_id).all())
    mode = wa_mode()
    out = {}
    for l in leads:
        person, entry = l.person, touches.get(l.person_id) or {}
        chips = []
        waiting = window = nochat = tick = None
        if crm_metrics.waiting_on_us(entry):
            chips.append(('wait', 'Wrote, waiting on us', 'They wrote last and nobody has answered yet.'))
            waiting = ('waiting', 'Waiting on us')
        left = crm_metrics.window_left_hours(entry.get('wa_last_in'), now) if entry.get('wa_last_in') else None
        if left:
            hrs = '%dh' % left if left >= 1 else 'under 1h'
            chips.append(('win', '24 h: %s left' % ('%dh' % left if left >= 1 else 'less than 1h'),
                          'WhatsApp lets us write freely until then.'))
            window = ('open', 'Open, %s left' % hrs)
        if mode != 'off' and person.phone and not person.wacrm_conversation_id:
            chips.append(('nochat', 'No chat yet', 'There is no WhatsApp chat with them yet.'))
            nochat = ('nochat', 'No chat yet')
        wl = entry.get('wa_last')
        if wl and wl[0] == 'out' and wl[2] in crm_timeline.TICKS:
            text = TICK_LABELS.get(wl[2], wl[2])
            chips.append(('tick t-%s' % wl[2], text, 'Our last WhatsApp message: ' + text.lower()))
            tick = ('tick', text)
        if person.wa_opt_out_at is not None:
            chips.append(('optout', 'Opted out', 'They asked for no more WhatsApp messages.'))
        stuck = stuck_for(l, now)
        if stuck is not None:
            chips.append(('stuck', 'Stuck: %s in this stage' % stuck_text(stuck), 'No stage move for that long.'))
        if person.wa_opt_out_at is not None:
            chat = ('optout', 'Opted out')
        else:
            chat = waiting or window or nochat or tick or ('', '—')
        out[l.id] = {'task': tasks.get(l.id), 'touch': entry, 'chips': chips, 'chat': chat,
                     'last_contact': last.get(l.id)}
    return out


def board(pipeline, owner_id=None, q=None, chat=None, closed_days=30, hidden=(), limit_per_stage=60, now=None,
          follow=None, **more):
    """Leads of a pipeline by stage, newest activity first: {'columns': [{'stage', 'leads', 'total'}],
    'cards': lead_cards()}. Hidden stages are left out. A fixed number of queries whatever the size."""
    base = lead_filter(pipeline, owner_id, q, chat, None, closed_days, follow, now, **more)
    hidden = [int(h) for h in hidden or ()]
    if hidden:
        base = base.filter(CrmLead.stage_id.notin_(hidden))
    totals = dict(base.with_entities(CrmLead.stage_id, func.count(CrmLead.id)).group_by(CrmLead.stage_id).all())
    rn = func.row_number().over(partition_by=CrmLead.stage_id,
                                order_by=(CrmLead.last_activity_at.desc(), CrmLead.id.desc()))
    ranked = base.with_entities(CrmLead.id.label('id'), rn.label('rn')).subquery()
    ids = [i for (i,) in db.session.query(ranked.c.id).filter(ranked.c.rn <= limit_per_stage)]
    leads = CrmLead.query.options(*lead_load()).filter(CrmLead.id.in_(ids)).all() if ids else []
    leads.sort(key=lambda l: (l.last_activity_at or datetime.min, l.id), reverse=True)
    values = crm_money.totals_by_stage(base)         # each column's money, in the reporting currency
    columns = []
    for st in pipeline.stages:
        if st.id in hidden:
            continue
        columns.append({'stage': st, 'leads': [l for l in leads if l.stage_id == st.id],
                        'total': totals.get(st.id, 0), 'value': values.get(st.id)})
    return {'columns': columns, 'cards': lead_cards(leads, now)}


def lead_list(pipeline=None, page=1, per_page=50, **filters):
    """One page of the list view (no card limit): {'leads', 'cards', 'total', 'page', 'pages'}."""
    query = lead_filter(pipeline, **filters)
    total = query.count()
    pages = max(1, -(-total // per_page))
    page = max(1, min(page, pages))
    leads = (query.options(*lead_load()).order_by(CrmLead.last_activity_at.desc(), CrmLead.id.desc())
             .offset((page - 1) * per_page).limit(per_page).all())
    return {'leads': leads, 'cards': lead_cards(leads, filters.get('now')), 'total': total, 'page': page,
            'pages': pages}


def stage_tags(stage, products):
    """The WhatsApp tags that mark people in this stage: "<prefix>: <stage name>" per product, or the
    pipeline's own label (stage_tag)."""
    pipe = stage.pipeline
    label = (pipe.tag_label or '').strip() if pipe is not None and pipe.tag_mode == 'own' else ''
    if label:
        return ['%s: %s' % (label, stage.name)]
    return sorted({'%s: %s' % (p, stage.name) for p in products} or {'%s: %s' % (stage.pipeline.product, stage.name)})


def stage_reach(pipeline, stages):
    """Who "Message everyone in this stage" would reach, counted from portal data (two queries):
    {stage id: {'text', 'reach', 'tags'}}. Everybody with a lead in the stage (open stages: open leads;
    won / lost: every lead there, as the tag stays). Each person once: opted out, then no WhatsApp
    number (no phone and no WhatsApp contact), then not in WhatsApp yet (a phone, no contact yet);
    the rest can get it."""
    ids = [s.id for s in stages]
    if not ids:
        return {}
    P, L = CrmPerson, CrmLead
    opted = P.wa_opt_out_at.isnot(None)
    free = P.wa_opt_out_at.is_(None)
    rows = (db.session.query(
        L.stage_id, func.count(func.distinct(P.id)),
        func.count(func.distinct(case((opted, P.id)))),
        func.count(func.distinct(case((and_(free, P.phone.is_(None), P.wacrm_contact_id.is_(None)), P.id)))),
        func.count(func.distinct(case((and_(free, P.phone.isnot(None), P.wacrm_contact_id.is_(None)), P.id)))))
        .join(P, P.id == L.person_id)
        .filter(L.pipeline_id == pipeline.id, L.stage_id.in_(ids)).group_by(L.stage_id).all())
    counts = {r[0]: r[1:] for r in rows}
    products = {}
    for sid, product in db.session.query(L.stage_id, L.product).filter(
            L.pipeline_id == pipeline.id, L.stage_id.in_(ids)).distinct():
        products.setdefault(sid, set()).add(product)
    out = {}
    for st in stages:
        people, opt, no_number, not_yet = counts.get(st.id, (0, 0, 0, 0))
        reach = people - opt - no_number - not_yet
        parts = []
        if no_number:
            parts.append(REACH_NO_NUMBER[0 if no_number == 1 else 1] % no_number)
        if opt:
            parts.append(REACH_OPTED % opt)
        if not_yet:
            parts.append(REACH_NOT_YET[0 if not_yet == 1 else 1] % not_yet)
        if not people:
            text = REACH_NONE
        elif not parts:
            text = REACH_ALL % people
        else:
            text = REACH_SOME % (reach, people, ', '.join(parts))
        out[st.id] = {'text': text, 'reach': reach, 'tags': stage_tags(st, products.get(st.id, ()))}
    return out


# ------------------------------------------------------------------------------ the shift-end message

def signoff_leads(user, now=None):
    """The open chats the sign-off reaches: one lead per person (their most recently active), on
    `user`'s open leads, whose WhatsApp chat is open (crm_metrics.window_open_people), with a phone and
    not opted out. Two queries."""
    from app.services import crm_metrics
    mine = select(CrmLead.person_id).where(CrmLead.status == 'open', CrmLead.owner_id == user.id)
    open_people = crm_metrics.window_open_people(CrmTouchpoint.person_id.in_(mine), now)
    leads = (CrmLead.query.options(*lead_load()).join(CrmPerson, CrmPerson.id == CrmLead.person_id)
             .filter(CrmLead.status == 'open', CrmLead.owner_id == user.id, CrmLead.person_id.in_(open_people),
                     CrmPerson.phone.isnot(None), CrmPerson.wa_opt_out_at.is_(None))
             .order_by(CrmLead.last_activity_at.desc(), CrmLead.id.desc()).all())
    seen, out = set(), []
    for l in leads:
        if l.person_id not in seen:
            seen.add(l.person_id)
            out.append(l)
    return out


def send_signoff(user, text, now=None):
    """The shift-end message to each of `user`'s open chats, their first name filled in, through
    send_by_hand (the one safe path: the chat is checked to be theirs and still open before anything
    goes). Somebody who got the sign-off from `user` today is skipped, so pressing it again only
    reaches the rest. Stops after SIGNOFF_LIMIT chats or SIGNOFF_BUDGET seconds, or when WhatsApp stops
    answering. {'sent': n, 'already': n, 'failed': [(name, reason)]}. Commits (send_by_hand does)."""
    now = now or datetime.utcnow()
    leads = signoff_leads(user, now)
    out = {'sent': 0, 'already': 0, 'failed': []}
    if not leads:
        return out
    start = datetime.combine((now + IST).date(), time.min) - IST
    earlier = {}
    for pid, code, body in (db.session.query(CrmTouchpoint.person_id, CrmTouchpoint.code, CrmTouchpoint.body)
                            .filter(CrmTouchpoint.person_id.in_([l.person_id for l in leads]),
                                    CrmTouchpoint.channel == 'whatsapp', CrmTouchpoint.direction == 'out',
                                    CrmTouchpoint.agent_id == user.id, CrmTouchpoint.created_at >= start)):
        earlier.setdefault(pid, []).append((code, body))
    se = CrmAnswer.query.filter_by(code='SE').first()
    began, tried = monotonic(), 0
    for lead in leads:
        words = fill(text, lead, user)
        if any(code == 'SE' or body == words for code, body in earlier.get(lead.person_id, ())):
            out['already'] += 1
            continue
        if tried >= SIGNOFF_LIMIT or monotonic() - began > SIGNOFF_BUDGET:
            out['failed'].append((None, SIGNOFF_TIME))
            break
        tried += 1
        r = send_by_hand(lead, user, 'text', text=words, answer=se)
        if r['mode'] == 'sent':
            out['sent'] += 1
        elif r['mode'] in ('unsure', 'down'):
            out['failed'].append((lead.person.display_name, r.get('reason') or ''))
            break
        else:
            out['failed'].append((lead.person.display_name, r.get('reason') or ''))
    return out


def signoff_said(out):
    """The sentence for a finished sign-off."""
    if not out['sent'] and not out['failed'] and not out['already']:
        return SIGNOFF_NOBODY
    s = SIGNOFF_SAID % out['sent']
    if out['already']:
        s += SIGNOFF_ALREADY % out['already']
    if out['failed']:
        s += SIGNOFF_FAILED % (len(out['failed']), (out['failed'][0][1] or '').rstrip('.'))
    return s


# ------------------------------------------------------------------------------ the waiting bell

def _waited(delta):
    minutes = max(int(delta.total_seconds() // 60), 0)
    return '%d min' % minutes if minutes < 60 else '%d h' % (minutes // 60)


def run_waiting_alerts(now=None, limit=300):
    """The bell for a customer waiting on us (crm_metrics: they wrote last on WhatsApp, Instagram or
    Facebook and nobody has answered) longer than the 'crm' setting waiting_alert_minutes (15),
    counted from their latest message: "Priya is waiting for your reply (15 min)". Once per wait, to
    whoever looks after their most recently active lead that is not snoozed -- the admins when nobody
    does; only from 07:00 to midnight India time; never while snoozed ("Remind me in 1 hour"). A wait
    older than WAITING_ALERT_MAX does not ring. Taken with one UPDATE per person first, so two jobs
    runs never ring twice; log_touch clears it when we write to them."""
    from app.services import crm_metrics, notify
    now = now or datetime.utcnow()
    if (now + IST).hour < WAITING_ALERT_FROM:
        return {'crm_waiting_alerts': 0}
    minutes = crm_settings()['waiting_alert_minutes']
    w = crm_metrics.waiting_rows(CrmTouchpoint.person_id.in_(
        select(CrmLead.person_id).where(CrmLead.status == 'open'))).subquery()
    rows = db.session.execute(
        select(w.c.person_id, w.c.channel, w.c.created_at)
        .where(w.c.created_at <= now - timedelta(minutes=minutes), w.c.created_at > now - WAITING_ALERT_MAX)
        .order_by(w.c.created_at).limit(limit)).all()
    if not rows:
        return {'crm_waiting_alerts': 0}
    by_person = {}
    for l in (CrmLead.query.options(joinedload(CrmLead.person).selectinload(CrmPerson.identities))
              .filter(CrmLead.person_id.in_([r.person_id for r in rows]), CrmLead.status == 'open')):
        by_person.setdefault(l.person_id, []).append(l)
    admins = None
    rung = 0
    for r in rows:
        leads = by_person.get(r.person_id) or []
        if not leads or any(l.waiting_alerted_at is not None for l in leads):
            continue
        free = [l for l in leads if l.snoozed_until is None or l.snoozed_until <= now]
        if not free:
            continue
        lead = max(free, key=lambda l: (l.last_activity_at or l.created_at or datetime.min, l.id))
        n = (CrmLead.query.filter(CrmLead.person_id == r.person_id, CrmLead.status == 'open',
                                  CrmLead.waiting_alerted_at.is_(None))
             .update({'waiting_alerted_at': now}, synchronize_session=False))
        if not n:
            continue
        if lead.owner_id:
            targets = [lead.owner_id]
        else:
            if admins is None:
                admins = [u.id for u in User.query.filter(User.is_admin.is_(True), User.is_active.is_(True))]
            targets = admins
        for uid in targets:
            notify.push(uid, 'crm_waiting',
                        title=WAITING_BELL % (first_name(lead.person.display_name) or 'A customer',
                                              _waited(now - r.created_at)),
                        body='%s · on %s' % (crm_products.labels().get(lead.product, lead.product),
                                             REPLY_LABELS.get(r.channel, r.channel)),
                        link=_lead_link(lead) + '?via=' + r.channel)
        rung += 1
    db.session.commit()
    return {'crm_waiting_alerts': rung}


# ======================================================================================= where a lead is

def stage_role(stage):
    """cold / prospect / pipeline / customer / lost -- the pipeline symbol shown everywhere. From "This
    stage means"; worked out from where it sits for a stage saved without one."""
    return 'new' if stage is None else stage.role


def derive_means(stage):
    """"This stage means" for a stage saved without one, from where it sits."""
    return stage.stage_means


ASKED_KEY = '_asked'             # details: "Something else" was the answer on the catch-all line
PRODUCT_MOVED, PRODUCT_SET, PRODUCT_KEPT = 'Moved to %s.', 'Saved: %s.', 'Kept in %s.'
ASK_MOVES, ASK_STAYS = 'Moves them to %s, with its follow-ups.', 'Keeps them here, as %s.'


def asks_product(lead):
    """An open lead in a catch-all pipeline that only knows it as the pipeline's own product (General),
    and nobody chose Something else: the page asks "What do they want?"."""
    p = lead.pipeline
    return bool(p is not None and p.catch_all and lead.status == 'open' and lead.product == p.product
                and not (lead.details or {}).get(ASKED_KEY))


def product_choices(lead):
    """The tiles for that question, [{'code', 'name', 'icon', 'tip'}], or None when it is not asked."""
    if not asks_product(lead):
        return None
    out = []
    for p in crm_products.tiles():
        target = crm_products.default_pipeline(p.code)
        moves = target is not None and target.id != lead.pipeline_id and not target.catch_all
        out.append({'code': p.code, 'name': p.name, 'icon': p.icon,
                    'tip': ASK_MOVES % target.name if moves else ASK_STAYS % p.name})
    return out


def set_product(lead, code, user=None):
    """The answer to "What do they want?" (or the product changed): the lead takes the product and, when
    that product has its own pipeline, moves there (set_pipeline: first stage, its follow-ups; the history
    stays). '' is Something else: it stays, and the question is not asked again. (toast words, moved).
    ValueError for a product that is not offered."""
    if not (code or '').strip():
        lead.details = {**(lead.details or {}), ASKED_KEY: 'other'}
        return PRODUCT_KEPT % (lead.pipeline.name if lead.pipeline else 'General'), False
    prod = crm_products.by_code(code)
    if prod is None or not prod.offered:
        raise ValueError(code)
    lead.product = prod.code
    crm_money.recalc_revenue(lead)
    target = crm_products.default_pipeline(prod.code)
    if (target is not None and target.id != lead.pipeline_id and not target.catch_all
            and target.is_active and target.first_stage is not None):
        set_pipeline(lead, target, user=user)
        return PRODUCT_MOVED % target.name, True
    mark_wa_due(lead.person)
    return PRODUCT_SET % prod.name, False


ROLE_LABELS = {'new': 'Not routed', 'cold': 'Cold lead', 'prospect': 'Prospect', 'pipeline': 'Pipeline',
               'customer': 'Customer', 'lost': 'Lost'}


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


def lead_for_record(kind, record_id, record=None):
    """The lead a record became -- or, for a trip post, the open lead its poster already has, which
    "+ Sales CRM" on the post went into (it never shows a second "add" button for it)."""
    ref_type = RECORD_KINDS.get(kind, (None,))[0]
    if not ref_type:
        return None
    lead = (CrmLead.query.filter_by(ref_type=ref_type, ref_id=record_id)
            .order_by(CrmLead.created_at.desc()).first())
    if lead is None and kind == 'trip':
        trip = record if record is not None else _record(kind, record_id)
        lead = open_trip_lead_of_poster(trip) if trip is not None else None
    return lead


def lead_from_record(kind, record_id, user=None):
    """Make a lead of something the site already has -- a quote, a contact message, a booking, a
    trip post, an account. Returns (lead, created). An existing lead for it is returned as it is;
    so is the open lead the same person already has in that pipeline, with this record added to it."""
    r = _record(kind, record_id)
    existing = lead_for_record(kind, record_id, record=r)
    if existing is not None:
        return existing, False
    if r is None:
        return None, False
    by = getattr(user, 'id', None)
    common = dict(utm={}, created_by_id=by, notify=False, refuse_dnc=True)
    if kind == 'insurance_quote':
        ages = ', '.join(str(t.get('age')) for t in (r.travellers or []) if isinstance(t, dict))
        lead = capture('ti-quote', name=r.name, phone=r.phone, email=r.email, product='TI', user_id=r.user_id,
                       departure_date=r.start_date, ends_on=r.end_date, ref=('insurance_quotes', r.id),
                       details={'plan': r.insurance_type, 'travellers_ages': ages, 'citizenship': r.citizenship,
                                'destination': r.destination, 'quote': r.status}, **common)
    elif kind == 'contact_message':
        text = r.message or ''
        key = ('sh-apply' if text.startswith('Sahayak application') else
               'ti-expert' if text.startswith(('Support request from the /travel-insurance',
                                               'Travel insurance enquiry from the /travel-insurance')) else
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
        lead = capture('web-other', name=r.full_name, phone=r.phone, email=r.email, user_id=r.id,
                       ref=('users', r.id), **common)
    if lead is None:
        return None, False
    ref_type = RECORD_KINDS[kind][0]
    created = (lead.ref_type, lead.ref_id) == (ref_type, record_id)
    if not created and not lead.ref_type:
        # the same person's open lead (one made by hand, from a chat): this record is where it came from
        lead.ref_type, lead.ref_id = ref_type, record_id
        db.session.commit()
    return lead, created


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
    # one query per kind for the leads these records already became (newest lead wins)
    by_type = {}
    for kind, rid, *_ in out:
        by_type.setdefault(RECORD_KINDS[kind][0], set()).add(rid)
    leads = {}
    for ref_type, ids in by_type.items():
        for ld in (CrmLead.query.filter(CrmLead.ref_type == ref_type, CrmLead.ref_id.in_(ids))
                   .order_by(CrmLead.created_at.desc())):
            leads.setdefault((ref_type, ld.ref_id), ld)
    rows = []
    for kind, rid, title, sub, when, what in out:
        rows.append({'kind': kind, 'id': rid, 'title': title or '—', 'sub': sub, 'when': when, 'what': what,
                     'label': RECORD_KINDS[kind][1],
                     'lead': leads.get((RECORD_KINDS[kind][0], rid)) or (lead_for_record(kind, rid) if kind == 'trip' else None)})
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
    """Take a lead out of the Sales CRM (added by mistake): it goes to the Recycle bin for 30 days
    (services/crm_bin), then it is deleted for good. The contact stays (Contacts) with their other
    enquiries and their own timeline items; the record it came from on the site is not touched."""
    from app.services import crm_bin
    return crm_bin.remove(lead, user=user)
