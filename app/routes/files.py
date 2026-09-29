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
    """Whether this deployment can actually serve.

    It used to answer 'ok' unconditionally, which is a liveness check: it says the process is up.
    Two things fail independently of the process being up, and the second is the nasty one:

      * the database can be unreachable, which is obvious within seconds;
      * the database can be reachable but BEHIND the code -- a deploy whose migrations did not
        run. Everything works except the screens touching the new table, and those give an
        opaque 500 with nothing in the response to say why. Placing one of those from the
        outside took an afternoon, which is the reason the check grew.

    Public callers still get ok/degraded and nothing else. The revisions only help somebody who
    can act on them, and naming your schema to the world is free reconnaissance.
    """
    from flask import current_app, jsonify
    from flask_login import current_user
    from sqlalchemy import text as sa_text
    from app import db

    detail, healthy = {}, True
    try:
        db.session.execute(sa_text('SELECT 1'))
        detail['database'] = 'ok'
    except Exception as exc:               # pragma: no cover - needs a broken database
        healthy = False
        detail['database'] = 'unreachable: %s' % type(exc).__name__

    if detail['database'] == 'ok':
        current, head = _migration_state(current_app, db)
        # A database built by create_all() has no stamp at all. That is the development and test
        # shape, and it is also exactly what a deploy that never ran its migrations looks like,
        # so it is reported rather than waved through -- but only as information, because in
        # those two settings the schema does match the code.
        detail['migration'] = {'current': current, 'head': head}
        if current and head and current != head:
            healthy = False
            detail['migration']['problem'] = (
                'the database is behind the code; run "flask db upgrade" on this deployment')

    body = {'status': 'ok' if healthy else 'degraded'}
    if current_user.is_authenticated and getattr(current_user, 'is_admin', False):
        body.update(detail)
    return jsonify(body), (200 if healthy else 503)


def _migration_state(app, db):
    """(applied revision, revision this code expects). (None, None) if it cannot be read."""
    try:
        from alembic.migration import MigrationContext
        from alembic.script import ScriptDirectory

        head = ScriptDirectory.from_config(
            app.extensions['migrate'].migrate.get_config()).get_current_head()
        with db.engine.connect() as conn:
            return MigrationContext.configure(conn).get_current_revision(), head
    except Exception:                      # pragma: no cover - alembic not configured
        return None, None
