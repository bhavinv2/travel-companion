"""The first-week checklist (Staff Console 2.0, 2026-10-26, the tawk.to way): on Home › Health, a short list of what
to set up, each line ticked by itself once it is done -- nothing to tick by hand -- until every line is, or the
person hides it. A line shows only to somebody whose role opens the page it points to.

    steps(user)   [{'key', 'text', 'why', 'url', 'done'}] for this person (empty: hidden, or nothing for them)
    hide(user)    "Hide this list" (remembered for them, in the setting HIDDEN_KEY)
"""
from flask import url_for

from app.services import access

HIDDEN_KEY = 'checklist.hidden'


def _two_step_rule():
    from app.services import signin
    return signin.rules().get('two_step') != 'optional'


def _team():
    from app.models import WorkspaceMember
    ws = access.default_workspace()
    return ws is not None and WorkspaceMember.query.filter_by(workspace_id=ws.id).count() > 1


def _profiles_given():
    """Somebody works with a role made from a ready-made profile (least privilege, not "Sales & service" for all)."""
    from app.models import WorkspaceMember, WorkspaceRole
    rows = (WorkspaceRole.query.join(WorkspaceMember, WorkspaceMember.role_id == WorkspaceRole.id)
            .filter(WorkspaceRole.rights.isnot(None)).all())
    return any((r.rights or {}).get('profile') for r in rows)


def _whatsapp():
    from app.services import crm
    return crm.wa_mode() != 'off'


def _chat():
    from app.services import tawk
    return tawk.enabled()


def _sources():
    from app.models import CrmSource
    return CrmSource.query.filter_by(status='unrouted').count() == 0


# (key, words, why, page it needs, (endpoint, args), done)
STEPS = (
    ('two_step_me', 'Turn on two-step sign-in for yourself',
     'A code from your phone as well as the password: a stolen password alone no longer gets in.',
     None, ('auth.security', {}), lambda u: u.two_step_on),
    ('two_step_rule', 'Ask every administrator for two-step sign-in',
     'Set-up › Security › Sign-in rules. People set it up the next time they sign in.',
     'ws_security', ('security.index', {'tab': 'rules'}), lambda u: _two_step_rule()),
    ('team', 'Add the people who work here', 'Each with their own sign-in, never a shared one.',
     'ws_members', ('workspace.members', {}), lambda u: _team()),
    ('roles', 'Give each person a role that fits their job',
     'Roles › Add the ready-made roles: Sales agent, Service agent, Content editor. Only what each job needs.',
     'ws_roles', ('workspace.roles', {}), lambda u: _profiles_given()),
    ('whatsapp', 'Connect WhatsApp', 'Chats, templates and follow-ups from the leads.',
     'crm_integrations', ('admin_crm.integration', {'key': 'whatsapp'}), lambda u: _whatsapp()),
    ('chat', 'Bring the website chat in', "tawk.to's chats become leads and land in the Inbox.",
     'crm_integrations', ('admin_crm.integration', {'key': 'tawk'}), lambda u: _chat()),
    ('sources', 'Tell every lead source where its leads go', 'A new source waits until somebody picks its pipeline.',
     'crm_sources', ('admin_crm.sources', {}), lambda u: _sources()),
)


def _hidden_for():
    from app.services.settings import get_setting
    return set(get_setting(HIDDEN_KEY) or [])


def steps(user):
    if not getattr(user, 'is_authenticated', False) or user.id in _hidden_for():
        return []
    out = []
    for key, text, why, page, (endpoint, args), done in STEPS:
        if page is not None and not access.can(user, page):
            continue
        try:
            url = url_for(endpoint, **args)
            ok = bool(done(user))
        except Exception:        # noqa: BLE001 -- a line that cannot be worked out is left off, never the page
            continue
        out.append({'key': key, 'text': text, 'why': why, 'url': url, 'done': ok})
    return out if out and not all(s['done'] for s in out) else []


def hide(user):
    from app.services.settings import set_setting
    set_setting(HIDDEN_KEY, sorted(_hidden_for() | {user.id}), actor=user)
