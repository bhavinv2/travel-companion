"""Quotes and payments (Sales CRM 2.0, run 4b): the lead page's "Quotes & payments" card, approving a quote, and
the payment provider's signed webhook.

The rules are on crm_bp (routes/crm.py), so they exist under /cs/crm and /admin/crm; the webhook is on
crm_public_bp. The work is in services/crm_quotes.py. Every route that loads a lead goes through `_lead_or_404`
(record visibility and the recycle bin); a quote or payment is loaded through its lead the same way.
"""
import json
import os

from flask import abort, current_app, flash, jsonify, redirect, request
from flask_login import current_user

from app import csrf, db
from app.models import ActivityEvent, CrmPayment, CrmQuote
from app.routes.crm import _lead_or_404, crm_bp, crm_public_bp, crm_url
from app.routes.cs import cs_required
from app.services import crm_quotes


def _back(lead):
    return crm_url('lead', lead_id=lead.id) + '#quotes'


def _quote_or_404(quote_id):
    q = db.session.get(CrmQuote, quote_id)
    if q is None:
        abort(404)
    _lead_or_404(q.lead_id)                    # hidden with its lead (visibility, recycle bin)
    return q


def _payment_or_404(payment_id):
    p = db.session.get(CrmPayment, payment_id)
    if p is None:
        abort(404)
    _lead_or_404(p.lead_id)
    return p


def _do(lead, fn, ok_message=None):
    try:
        out = fn()
    except crm_quotes.QuoteError as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
        return None
    if ok_message:
        flash(ok_message, 'success')
    return out


@crm_bp.app_template_global('QUOTE_WORDS')
def quote_words():
    return crm_quotes.QUOTE_WORDS


@crm_bp.app_template_global('PAYMENT_WORDS')
def payment_words():
    return crm_quotes.PAYMENT_WORDS


@crm_bp.app_template_global('QUOTE_BLOCKED')
def quote_blocked(q):
    return crm_quotes.blocked(q)


@crm_bp.route('/lead/<int:lead_id>/quote', methods=['POST'])
@cs_required
def quote_add(lead_id):
    lead = _lead_or_404(lead_id)
    q = _do(lead, lambda: crm_quotes.create(lead, request.form, current_user))
    if q is not None:
        flash('Quote saved%s.' % (' - it needs an approval before it can be sent' if q.needs_approval else ''),
              'success')
    return redirect(_back(lead))


@crm_bp.route('/quote/<int:quote_id>/edit', methods=['POST'])
@cs_required
def quote_edit(quote_id):
    q = _quote_or_404(quote_id)
    _do(q.lead, lambda: crm_quotes.update(q, request.form, current_user), 'Quote saved.')
    return redirect(_back(q.lead))


@crm_bp.route('/quote/<int:quote_id>/status', methods=['POST'])
@cs_required
def quote_status(quote_id):
    """Mark as sent / accepted / declined / run out. Sending logs the stage's quote milestone like the old button
    (the lead moves forward); nothing is sent to the customer."""
    q = _quote_or_404(quote_id)
    action = request.form.get('action')
    if action == 'sent':
        _do(q.lead, lambda: crm_quotes.mark_sent(q, current_user), 'Marked as sent. Nothing was sent to the customer.')
    else:
        _do(q.lead, lambda: crm_quotes.set_status(q, action, current_user), 'Saved.')
    return redirect(_back(q.lead))


@crm_bp.route('/quote/<int:quote_id>/approve', methods=['POST'])
@cs_required
def quote_approve(quote_id):
    q = _quote_or_404(quote_id)
    _do(q.lead, lambda: crm_quotes.approve(q, current_user), 'Approved. It can be sent now.')
    nxt = request.form.get('next') or ''
    if nxt.startswith('/') and not nxt.startswith('//'):
        return redirect(nxt)
    return redirect(_back(q.lead))


@crm_bp.route('/quote/<int:quote_id>/delete', methods=['POST'])
@cs_required
def quote_delete(quote_id):
    q = _quote_or_404(quote_id)
    lead = q.lead
    _do(lead, lambda: crm_quotes.delete(q, current_user), 'Quote deleted.')
    return redirect(_back(lead))


@crm_bp.route('/lead/<int:lead_id>/payment', methods=['POST'])
@cs_required
def payment_add(lead_id):
    lead = _lead_or_404(lead_id)
    _do(lead, lambda: crm_quotes.add_payment(lead, request.form, current_user),
        'Payment link saved. Nothing was sent to the customer.')
    return redirect(_back(lead))


@crm_bp.route('/payment/<int:payment_id>/status', methods=['POST'])
@cs_required
def payment_status(payment_id):
    p = _payment_or_404(payment_id)
    lead = p.lead
    action = request.form.get('action')
    msg = 'Marked as paid. The lead is won.' if action == 'paid' else 'Saved.'
    _do(lead, lambda: crm_quotes.set_payment_status(p, action, current_user), msg)
    return redirect(_back(lead))


@crm_bp.route('/payment/<int:payment_id>/delete', methods=['POST'])
@cs_required
def payment_delete(payment_id):
    p = _payment_or_404(payment_id)
    lead = p.lead
    _do(lead, lambda: crm_quotes.delete_payment(p, current_user), 'Payment deleted.')
    return redirect(_back(lead))


# ============================================================================================ the webhook

def webhook_secret():
    return (os.environ.get('CRM_PAYMENT_WEBHOOK_SECRET') or '').strip()


@crm_public_bp.route('/api/crm/payment-webhook', methods=['POST'])
@csrf.exempt
def payment_webhook():
    """The payment provider tells us a payment is paid or failed. Body JSON {reference, status, amount, currency};
    header X-Signature = hex HMAC-SHA256 of the raw body with CRM_PAYMENT_WEBHOOK_SECRET. 404 while that is unset.
    Repeats change nothing."""
    secret = webhook_secret()
    if not secret:
        abort(404)
    raw = request.get_data()
    if not crm_quotes.signature_ok(secret, request.headers.get('X-Signature'), raw):
        return jsonify({'error': 'Bad signature.'}), 403
    try:
        payload = json.loads(raw.decode('utf-8') or '{}')
    except ValueError:
        return jsonify({'error': 'Not JSON.'}), 400
    if not isinstance(payload, dict):
        return jsonify({'error': 'Not JSON.'}), 400
    try:
        res = crm_quotes.handle_webhook(payload)
    except crm_quotes.QuoteError as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 400
    except Exception:          # noqa: BLE001 -- answered and logged; the provider would only resend
        db.session.rollback()
        current_app.logger.exception('Payment webhook failed')
        return jsonify({'ok': False}), 200
    try:
        ActivityEvent.log('crm_payment_webhook', actor=None, result=res.get('result'), lead_id=res.get('lead_id'))
        db.session.commit()
    except Exception:          # noqa: BLE001 -- the log is a courtesy
        db.session.rollback()
    return jsonify({'ok': True, **res})
