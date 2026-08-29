"""Scheduler entry point. Protected by a shared secret so it can be hit by Railway cron / Cloud Scheduler."""
import hmac
from flask import Blueprint, request, jsonify, current_app, abort
from app import csrf
from app.services import jobs

jobs_bp = Blueprint('jobs', __name__)


@jobs_bp.route('/internal/jobs/run', methods=['POST'])
@csrf.exempt
def run_jobs():
    secret = current_app.config.get('JOBS_SECRET')
    if not secret:
        abort(404)   # disabled until configured
    provided = request.headers.get('X-Jobs-Secret', '')
    if not hmac.compare_digest(provided, secret):
        abort(403)
    return jsonify({'success': True, **jobs.run_all()})
