"""Why a list is downloaded (Staff Console 2.0, 2026-10-26): every sales download asks first.

A download opened without a reason shows "Why are you downloading this?" (cs/crm/why_download.html) -- a few
choices and a line for anything else -- and goes on to the same address with the reason added, so every button
that downloads (Sales results, per person, Forecast, Team analysis, the report builder, Leads' and Contacts' lists,
the Downloads page) asks without changing. The reason goes into the download's audit-log line (ActivityEvent
'crm_export', Set-up › Security › Audit log), beside who, when and what.

    asked        decorator for a download route
    ask()        the question page itself, for a route that downloads only sometimes (Team analysis)
    given()      the reason this request carries, in words, or None
"""
from functools import wraps
from urllib.parse import urlparse

from flask import render_template, request, url_for

REASONS = (('report', 'A report for the team or a manager'),
           ('calls', 'To call or message the people on it'),
           ('partner', 'For accounts, an insurer or another partner'),
           ('backup', 'A backup copy'),
           ('other', 'Something else'))
NOTE_MAX = 120


def given():
    """The reason in words ('A backup copy', 'Something else: for the audit'), or None when there is none yet."""
    key = request.args.get('reason')
    words = dict(REASONS).get(key)
    if words is None:
        return None
    if key != 'other':
        return words
    note = ' '.join((request.args.get('why') or '').split())[:NOTE_MAX]
    return '%s: %s' % (words, note) if note else None


def _back():
    """Where "Cancel" goes: the page the download was asked from, when it is ours."""
    from app.services import urls
    ref = urlparse(request.referrer or '')
    if ref.netloc == request.host:
        back = urls.safe_next(ref.path + ('?' + ref.query if ref.query else ''))
        if back:
            return back
    from app.routes.crm import crm_url
    return crm_url('downloads')


def ask():
    """The question, before the file: the same address and query string, plus the reason."""
    from app.routes.crm import _common
    keep = [(k, v) for k, v in request.args.items(multi=True) if k not in ('reason', 'why')]
    return render_template('cs/crm/why_download.html', REASONS=REASONS, keep=keep, NOTE_MAX=NOTE_MAX,
                           action=url_for(request.endpoint, **(request.view_args or {})), back=_back(),
                           missing=request.args.get('reason') == 'other', **_common())


def asked(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if given() is None:
            return ask()
        return view(*args, **kwargs)
    return wrapped
