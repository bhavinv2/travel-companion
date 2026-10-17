"""Set-up -> WhatsApp connection (E21) and Automatic messages -> What goes out by itself (E14).

It works out what those pages show. The live checks call the WhatsApp CRM with short timeouts and are
only asked for after the page has drawn (`checks()`, from the page's script). Everything else reads this
database.
"""
from datetime import datetime

from sqlalchemy.orm import selectinload

from app.models import CrmPerson, CrmPipeline, CrmPlaybookStep, CrmStage
from app.services import crm, wa_templates, wacrm, wacrm_team

SCOPE_WORDS = {'contacts:read': 'read contacts', 'contacts:write': 'change contacts',
               'messages:send': 'send messages', 'webhooks:manage': 'set up the replies link'}
HOOK_OFF_TRIES = 15            # the WhatsApp CRM switches an address off after this many failed deliveries


def _line(state, text, **extra):
    return dict(extra, state=state, text=text)


def _when(value):
    at = crm._parse_utc(value)
    return (at + crm.IST).strftime('%d %b, %H:%M') if at else None


def _key_line():
    """Address set + connection key accepted. Returns (line, unreachable)."""
    if not wacrm.enabled():
        return _line('bad', "Not set up on this server yet: it needs the WhatsApp CRM's address and connection "
                            'key (see For the developer).'), False
    try:
        me = wacrm.me()
    except wacrm.WacrmError as exc:
        if not exc.reached:
            return _line('bad', '✗ WhatsApp could not be reached at the address set'), True
        if exc.status in (401, 403):
            return _line('bad', '✓ Address set · ✗ Connection key not accepted: WhatsApp says it is wrong or '
                                'switched off'), False
        return _line('bad', '✓ Address set · ✗ Could not check the connection key: %s' % exc), False
    scopes = set((me.get('key') or {}).get('scopes') or [])
    missing = [words for scope, words in SCOPE_WORDS.items() if scope not in scopes]
    if missing:
        return _line('warn', '✓ Address set · ⚠ Connection key accepted, but it may not: ' + ', '.join(missing)), False
    return _line('ok', '✓ Address set · ✓ Connection key accepted (sending works)'), False


def _replies_line(unreachable):
    hook = crm._wa_webhook_saved()
    if not hook.get('id'):
        return _line('bad', "✗ Replies are not connected yet: WhatsApp can't tell us when someone writes",
                     action='webhook')
    if unreachable:
        return _line('skip', 'Replies: not checked (WhatsApp could not be reached)')
    try:
        rows = wacrm.list_webhooks() or []
    except wacrm.WacrmError as exc:
        return _line('warn', '⚠ Could not check the replies link: %s' % exc)
    ours = (next((w for w in rows if str(w.get('id')) == str(hook['id'])), None)
            or next((w for w in rows if hook.get('url') and w.get('url') == hook['url']), None))
    if ours is None:
        return _line('bad', '✗ The replies link is missing in WhatsApp', action='webhook')
    failures = int(ours.get('failure_count') or 0)
    last = _when(ours.get('last_delivery_at'))
    if ours.get('is_active') is False:
        return _line('bad', '✗ Replies are not arriving — WhatsApp switched the replies link off after %d failed tries'
                     % (failures or HOOK_OFF_TRIES), action='webhook_on')
    if failures > 0:
        return _line('warn', '⚠ Replies are arriving, but the last %d tries failed%s'
                     % (failures, (' · last one %s' % last) if last else ''))
    if last:
        return _line('ok', '✓ Replies are arriving · last one %s' % last)
    return _line('ok', '✓ The replies link is on · nothing has arrived yet')


def _team_line(ws):
    if not wacrm_team.enabled():
        return _line('bad', '✗ Team sign-in is not set up on this server (see For the developer)')
    s = wacrm_team.status(ws)
    if not s.get('linked'):
        other = ('WhatsApp is linked to %s now. Linking here moves the link to this workspace.' % s['other']
                 if s.get('other') else None)
        return _line('bad', '✗ Team sign-in — this workspace is not linked to WhatsApp yet', action='team_link',
                     other=other)
    n = s.get('synced') or 0
    failed = [{'member': m, 'name': m.user.full_name or m.user.username, 'reason': m.wacrm_error}
              for m in ws.members if m.wacrm_error and m.user is not None]
    text = '✓ Team sign-in — %d %s can use WhatsApp' % (n, 'person' if n == 1 else 'people')
    if failed:
        text += ' · %d not yet:' % len(failed)
    return _line('warn' if failed else 'ok', text, failed=failed, error=s.get('error'), linked=True,
                 extra=(ws.wacrm or {}).get('extra') or [])


def checks(ws, now=None):
    """The four check lines and the reply rules to pause, asked live: {'key', 'replies', 'team', 'number',
    'rules', 'rules_state'}. Each line is {'state': 'ok'|'warn'|'bad'|'skip', 'text', ...}. After a "could not
    be reached" nothing else is asked (one timeout, not four)."""
    out = {'rules': [], 'rules_state': 'off'}
    with wacrm.short_timeouts():
        out['key'], unreachable = _key_line()
        out['replies'] = _replies_line(unreachable)
        out['team'] = _team_line(ws)
        out['number'] = None
        if wacrm_team.enabled() and not unreachable:
            try:
                info = wacrm_team.workspace_info() or {}
                wa = info.get('whatsapp') or {}
                if wa.get('connected'):
                    phone = wa.get('display_phone')
                    out['number'] = _line('ok', '✓ WhatsApp number connected' + (': %s' % phone if phone else ''))
                else:
                    out['number'] = _line('bad', '✗ No WhatsApp number is connected yet')
            except wacrm_team.TeamError as exc:
                out['number'] = _line('warn', '⚠ Could not ask WhatsApp which number is connected: %s' % exc)
                if exc.status is None:
                    unreachable = True
        if wacrm_team.enabled() and not unreachable:
            try:
                items = wacrm_team.automations()
                out['rules'] = crm.remember_rule_conflicts(items)
                out['rules_state'] = 'ok'
            except wacrm_team.TeamError as exc:
                out['rules_state'] = 'old' if exc.status == 404 else 'error'
    return out


def needs_attention(now=None, limit=50):
    """{'sync': [{'person', 'lead', 'reason'}], 'stuck': [{'task', 'minutes'}], 'count'}: people the WhatsApp
    CRM refused (while writes are on), newest first, and follow-ups stuck "sending" (crm.stuck_sends)."""
    now = now or datetime.utcnow()
    sync = []
    if crm.wa_writes_on():
        people = (CrmPerson.query.filter(CrmPerson.wa_sync_error.isnot(None), CrmPerson.wacrm_sync_due_at.is_(None))
                  .options(selectinload(CrmPerson.leads)).order_by(CrmPerson.id.desc()).limit(limit).all())
        for p in people:
            sync.append({'person': p, 'lead': crm._wa_main_lead(p) or (p.leads[0] if p.leads else None),
                         'reason': crm._plain_sync_error(p.wa_sync_error)})
    stuck = [{'task': t, 'minutes': int((now - t.done_at).total_seconds() // 60) if t.done_at else None}
             for t in crm.stuck_sends(now, limit)]
    return {'sync': sync, 'stuck': stuck, 'count': len(sync) + len(stuck)}


def _template_words(step):
    name = step.wa_template or wa_templates.slug_name(step.code)
    st = wa_templates.statuses().get(name)
    if not st:
        return 'no WhatsApp template yet'
    reason = (wa_templates.infos().get(name) or {}).get('rejection_reason')
    return 'template ' + wa_templates.status_words(st, reason)


def automatic_page(now=None):
    """What goes out by itself: {'steps', 'moves', 'rules', 'rules_state', 'conflicts', 'sending', 'mode_label',
    'flows_active', 'ai_auto_reply'} -- the last two are None when the WhatsApp CRM did not say."""
    enabled = wacrm_team.enabled()
    steps = []
    rows = (CrmPlaybookStep.query.join(CrmStage, CrmPlaybookStep.stage_id == CrmStage.id)
            .join(CrmPipeline, CrmStage.pipeline_id == CrmPipeline.id)
            .filter(CrmPlaybookStep.auto.is_(True), CrmPlaybookStep.channel == 'whatsapp')
            .order_by(CrmPipeline.id, CrmStage.position, CrmPlaybookStep.position).all())
    for s in rows:
        steps.append({'step': s, 'pipeline': s.stage.pipeline, 'stage': s.stage, 'when': crm.step_when(s),
                      'tpl': _template_words(s) if enabled else None, 'active': s.stage.pipeline.is_active})
    moves = []
    for st in (CrmStage.query.join(CrmPipeline, CrmStage.pipeline_id == CrmPipeline.id)
               .filter(CrmStage.auto_kind.isnot(None), CrmStage.auto_to_id.isnot(None))
               .order_by(CrmPipeline.id, CrmStage.position).all()):
        to = st.auto_to
        if to is None or to.pipeline_id != st.pipeline_id or to.id == st.id:
            continue
        moves.append({'stage': st, 'pipeline': st.pipeline, 'to': to.name, 'words': crm.auto_move_words(st)})
    rules, state, conflicts = [], 'off', []
    flows = ai = None
    if enabled:
        try:
            with wacrm.short_timeouts():
                info = wacrm_team.automations_info()
            items = info['items']
            rules = [{'id': str(i.get('id')), 'name': i.get('name') or '', 'active': bool(i.get('active')),
                      'sends': bool(i.get('sends')), 'conflict': crm.rule_conflict(i)} for i in items]
            conflicts = crm.remember_rule_conflicts(items)
            flows, ai = info['flows_active'], info['ai_auto_reply']
            state = 'ok'
        except wacrm_team.TeamError as exc:
            state = 'old' if exc.status == 404 else 'error'
    return {'steps': steps, 'moves': moves, 'rules': rules, 'rules_state': state, 'conflicts': conflicts,
            'flows_active': flows, 'ai_auto_reply': ai,
            'sending': crm.wa_can_send(), 'mode_label': crm.WA_MODES[crm.crm_settings()['whatsapp_mode']]}
