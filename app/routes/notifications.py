from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from app import db
from app.models import Notification

notifications_bp = Blueprint('notifications', __name__)


@notifications_bp.route('', methods=['GET'])
@login_required
def list_notifications():
    limit = min(max(request.args.get('limit', 20, type=int), 1), 100)
    q = Notification.query.filter_by(user_id=current_user.id)
    if request.args.get('unread') == '1':
        q = q.filter_by(is_read=False)
    items = q.order_by(Notification.created_at.desc()).limit(limit).all()
    unread = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
    return jsonify({'notifications': [n.to_dict() for n in items], 'unread': unread})


@notifications_bp.route('/<int:nid>/read', methods=['POST'])
@login_required
def mark_read(nid):
    n = Notification.query.get_or_404(nid)
    if n.user_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403
    n.is_read = True
    db.session.commit()
    return jsonify({'success': True})


@notifications_bp.route('/read-all', methods=['POST'])
@login_required
def mark_all_read():
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({'is_read': True})
    db.session.commit()
    return jsonify({'success': True})
