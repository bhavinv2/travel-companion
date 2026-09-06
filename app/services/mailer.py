"""E-mail sending that never raises and reports whether a message went out.

Providers (MAIL_PROVIDER): 'smtp' (Flask-Mail, default) or 'sendgrid' (HTTPS API, SENDGRID_API_KEY).
Every sent message is appended to OUTBOX so tests and dev tooling can inspect what went out; messages
stopped by the notification switches (see app/services/notify.py) are recorded in notify.SUPPRESSED instead.
"""
import logging
from flask import current_app, render_template
from flask_mail import Message as MailMessage
from app import mail

log = logging.getLogger(__name__)

OUTBOX = []


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
        'from': {'email': current_app.config.get('MAIL_DEFAULT_SENDER'), 'name': 'Connecting Desis'},
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


def send(subject, recipients, body, reply_to=None, category='other'):
    """Return True if the message was handed to the mail provider, False otherwise.

    `category` is one of app.models.NOTIFY_CATEGORIES ('account', 'match_alerts', …) and is checked
    against the global notification switches and the recipient's preferences before anything is sent.
    """
    from app.services import notify
    if isinstance(recipients, str):
        recipients = [recipients]
    recipients = [r for r in recipients if r and notify.email_allowed(category, r)]
    if not recipients:
        return False
    OUTBOX.append({'subject': subject, 'recipients': list(recipients), 'body': body, 'category': category})
    if current_app.config.get('TESTING') or current_app.config.get('MAIL_SUPPRESS_SEND'):
        return True
    try:
        if current_app.config.get('MAIL_PROVIDER') == 'sendgrid':
            return _send_sendgrid(subject, recipients, body, reply_to)
        return _send_smtp(subject, recipients, body, reply_to)
    except Exception:  # pragma: no cover - network failure
        log.exception('Failed to send e-mail %r to %s', subject, recipients)
        return False


def send_template(subject, recipients, template, category='other', **ctx):
    body = render_template(template, **ctx)
    return send(subject, recipients, body, category=category)
