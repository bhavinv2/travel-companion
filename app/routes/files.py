"""Serve private uploads (ticket attachments) to the post owner or CS only."""
import os
from flask import Blueprint, abort, send_file, redirect
from flask_login import login_required, current_user
from app.models import CompanionRequest
from app.services import storage

files_bp = Blueprint('files', __name__)


@files_bp.route('/files/private/<key>')
@login_required
def private_file(key):
    trip = CompanionRequest.query.filter_by(ticket_attachment=key).first()
    if trip is None:
        abort(404)
    if not (current_user.is_cs or (trip.user_id and trip.user_id == current_user.id)):
        abort(403)
    if storage.backend() == 's3':
        url = storage.private_url(key)
        if not url:
            abort(404)
        return redirect(url)
    path = storage.private_path(key)
    if not path or not os.path.exists(path):
        abort(404)
    return send_file(path, as_attachment=False)


@files_bp.route('/healthz')
def healthz():
    return {'status': 'ok'}
