"""E-mail sending that never raises and reports whether a message went out.

Providers (MAIL_PROVIDER): 'smtp' (Flask-Mail, default) or 'sendgrid' (HTTPS API, SENDGRID_API_KEY).
Every sent message is appended to OUTBOX so tests and dev tooling can inspect what went out; messages
stopped by the notification switches (see app/services/notify.py) are recorded in notify.SUPPRESSED instead.

ACCOUNT MAIL AND EVERYTHING ELSE. Two kinds of message, treated differently:

  account mail   sign-up verification, password reset, the set-your-password invite for a new
                 staff account. Sent with account=True. Never switched off -- the notification
                 switches exist to stop us mailing people who did not ask to hear from us, and these
                 are how people get into their own accounts; a switch turned off for some other
                 reason used to lock everybody out of password reset without a word.
  everything     match alerts, blog announcements, CS replies, enquiry copies to the team.
    else

The SMTP mailbox is a Gmail account by default (MAIL_SERVER smtp.gmail.com), and Gmail is kept for
account mail ONLY: a personal mailbox has a small daily allowance and gets flagged when it sends in
bulk, and a blocked mailbox would take sign-up and password reset down with it. Everything else goes
through SendGrid when it is configured, and is not e-mailed when it is not (the in-app notification
still happens). An SMTP server that is not Gmail carries both kinds as before.
"""
import logging
from flask import current_app, render_template
from flask_mail import Message as MailMessage
from app import mail

log = logging.getLogger(__name__)

OUTBOX = []

# SMTP hosts kept for account mail only (see the module docstring).
ACCOUNT_ONLY_HOSTS = ('gmail.com', 'googlemail.com')


def smtp_is_account_only():
    """True when the SMTP server is a mailbox kept for sign-in and sign-up mail (Gmail)."""
    host = (current_app.config.get('MAIL_SERVER') or '').lower()
    return any(h in host for h in ACCOUNT_ONLY_HOSTS)


def transport_for(account):
    """'smtp', 'sendgrid', or None when nothing may carry this kind of message."""
    provider = current_app.config.get('MAIL_PROVIDER') or 'smtp'
    has_sendgrid = bool(current_app.config.get('SENDGRID_API_KEY'))
    if account:
        # the mailbox first; SendGrid only when there is no mailbox password to use
        if provider == 'sendgrid' and has_sendgrid and not current_app.config.get('MAIL_PASSWORD'):
            return 'sendgrid'
        return 'smtp'
    if provider == 'sendgrid' or (has_sendgrid and smtp_is_account_only()):
        return 'sendgrid' if has_sendgrid else None
    if smtp_is_account_only():
        return None          # Gmail is kept for sign-in and sign-up mail
    return 'smtp'


def _send_smtp(subject, recipients, body, reply_to):
    if not current_app.config.get('MAIL_PASSWORD'):
        log.info('SMTP mail not configured; would have sent %r to %s', subject, recipients)
        return False
    msg = MailMessage(subject=subject, recipients=list(recipients), body=body,
                      reply_to=reply_to or current_app.config.get('MAIL_DEFAULT_SENDER'))
    mail.send(msg)
    return True


def _send_sendgrid(subject, recipients, body, reply_to):
    import requests
    key = current_app.config.get('SENDGRID_API_KEY')
    if not key:
        log.info('SendGrid not configured; would have sent %r to %s', subject, recipients)
        return False
    payload = {
        'personalizations': [{'to': [{'email': r} for r in recipients]}],
        'from': {'email': current_app.config.get('MAIL_DEFAULT_SENDER'), 'name': 'NRI Parent Service'},
        'subject': subject,
        'content': [{'type': 'text/plain', 'value': body}],
    }
    if reply_to:
        payload['reply_to'] = {'email': reply_to}
    resp = requests.post('https://api.sendgrid.com/v3/mail/send', json=payload, timeout=10,
                         headers={'Authorization': f'Bearer {key}'})
    if resp.status_code != 202:
        log.warning('SendGrid rejected message %r: %s %s', subject, resp.status_code, resp.text[:200])
        return False
    return True


def send(subject, recipients, body, reply_to=None, category='other', force=False, account=False):
    """Return True if the message was handed to the mail provider, False otherwise.

    `category` is one of app.models.NOTIFY_CATEGORIES ('account', 'match_alerts', …) and is checked
    against the global notification switches and the recipient's preferences before anything is sent.
    `force=True` skips that gate (for e-mails governed by their own dedicated toggle, e.g. the landing
    contact address) — the caller is responsible for its own opt-in check.
    `account=True` marks sign-in/sign-up mail: it skips the switches too, and is the only kind the
    Gmail mailbox carries. See the module docstring.
    """
    from app.services import notify
    if isinstance(recipients, str):
        recipients = [recipients]
    if not (force or account):
        recipients = [r for r in recipients if r and notify.email_allowed(category, r)]
    else:
        recipients = [r for r in recipients if r]
    if not recipients:
        return False
    transport = transport_for(account)
    if transport is None:
        notify.SUPPRESSED.append({'channel': 'email', 'category': category, 'to': list(recipients),
                                  'reason': 'gmail_reserved_for_account_mail'})
        log.info('Not e-mailed (the Gmail mailbox is kept for sign-in/sign-up mail): %r', subject)
        return False
    OUTBOX.append({'subject': subject, 'recipients': list(recipients), 'body': body, 'category': category,
                   'account': bool(account), 'transport': transport})
    if current_app.config.get('TESTING') or current_app.config.get('MAIL_SUPPRESS_SEND'):
        return True
    try:
        if transport == 'sendgrid':
            return _send_sendgrid(subject, recipients, body, reply_to)
        return _send_smtp(subject, recipients, body, reply_to)
    except Exception:  # pragma: no cover - network failure
        log.exception('Failed to send e-mail %r to %s', subject, recipients)
        return False


def diagnose(to):
    """Send one real account-type test message to `to`. Returns (ok, what happened, in plain words).

    For the admin "send me a test e-mail" button -- the only way to see from inside the app why a
    password-reset e-mail is not arriving, since send() deliberately never raises.
    """
    cfg = current_app.config
    transport = transport_for(True)
    subject = '[NRI Parent Service] Test e-mail'
    body = ('This is a test from the admin panel. If you can read it, sign-up and password-reset '
            'e-mails can be delivered.')
    if transport == 'smtp' and not cfg.get('MAIL_PASSWORD'):
        return False, ('MAIL_PASSWORD is not set, so nothing can be sent. For Gmail it must be an '
                       'App Password (Google Account > Security > 2-Step Verification > App '
                       'passwords), not the normal Gmail password.')
    if transport == 'sendgrid' and not cfg.get('SENDGRID_API_KEY'):
        return False, 'SENDGRID_API_KEY is not set.'
    if cfg.get('TESTING') or cfg.get('MAIL_SUPPRESS_SEND'):
        OUTBOX.append({'subject': subject, 'recipients': [to], 'body': body, 'category': 'account',
                       'account': True, 'transport': transport})
        return True, 'Test e-mail handed to %s (sending is suppressed here).' % transport
    import smtplib
    import socket
    try:
        if transport == 'sendgrid':
            ok = _send_sendgrid(subject, [to], body, None)
            return ok, ('Sent through SendGrid to %s.' % to if ok else
                        'SendGrid refused it -- see the server log for its answer.')
        _send_smtp(subject, [to], body, None)
        return True, 'Sent to %s through %s. Check that inbox (and spam).' % (to, cfg.get('MAIL_SERVER'))
    except smtplib.SMTPAuthenticationError:
        return False, ('%s refused the username/password. Gmail needs an App Password here, not '
                       'the normal account password (Google Account > Security > 2-Step '
                       'Verification > App passwords), and MAIL_USERNAME must be that Gmail '
                       'address.' % cfg.get('MAIL_SERVER'))
    except (socket.timeout, TimeoutError, ConnectionRefusedError, smtplib.SMTPConnectError,
            smtplib.SMTPServerDisconnected, OSError) as e:
        return False, ('Could not reach %s:%s (%s). The host may block outgoing mail ports -- some '
                       'hosting plans do -- in which case SMTP cannot work from this server and '
                       'an HTTPS provider such as SendGrid is needed.'
                       % (cfg.get('MAIL_SERVER'), cfg.get('MAIL_PORT'), type(e).__name__))
    except Exception as e:  # noqa: BLE001 -- reported, not raised
        log.exception('test e-mail failed')
        return False, 'Sending failed: %s' % type(e).__name__


def send_template(subject, recipients, template, category='other', **ctx):
    body = render_template(template, **ctx)
    return send(subject, recipients, body, category=category)
