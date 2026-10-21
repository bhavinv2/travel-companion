"""Google Ads lead forms (Sales CRM 2.0, run 4b): POST /api/crm/google-leads. Public, like the other webhooks (no
login, no CSRF); the shared key in the body is the check. The work is in services/crm_lead_ads.py. (The Facebook /
Instagram lead forms arrive on the existing /api/crm/meta-webhook.)"""
import json

from flask import abort, current_app, jsonify, request

from app import csrf, db
from app.routes.crm import crm_public_bp
from app.services import crm_lead_ads


@crm_public_bp.route('/api/crm/google-leads', methods=['POST'])
@csrf.exempt
def google_leads():
    """Google's lead form webhook: {google_key, lead_id, form_id, campaign_id, is_test, user_column_data: [...]}.
    404 while CRM_GOOGLE_LEADS_KEY is unset, 403 for a wrong key. Test leads are answered with 200 and not stored."""
    if not crm_lead_ads.google_key():
        abort(404)
    try:
        body = json.loads(request.get_data().decode('utf-8') or '{}')
    except ValueError:
        return jsonify({'error': 'Not JSON.'}), 400
    if not isinstance(body, dict):
        return jsonify({'error': 'Not JSON.'}), 400
    if not crm_lead_ads.key_ok(body.get('google_key')):
        return jsonify({'error': 'Bad key.'}), 403
    try:
        res = crm_lead_ads.handle_google(body)
    except Exception:          # noqa: BLE001 -- answered and logged; Google would only resend
        db.session.rollback()
        current_app.logger.exception('Google lead not stored')
        return jsonify({'ok': False}), 200
    return jsonify({'ok': True, **res})
