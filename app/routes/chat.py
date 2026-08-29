from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from app import db
from app.models import ChatRoom, ChatMessage, Notification, ConnectionRequest, CompanionRequest
from app.services.storage import save_chat_file

chat_bp = Blueprint('chat', __name__)


@chat_bp.route('/inbox')
@login_required
def inbox():
    rooms = ChatRoom.query.filter(
        (ChatRoom.user1_id == current_user.id) | (ChatRoom.user2_id == current_user.id)
    ).order_by(ChatRoom.created_at.desc()).all()
    last_messages = {
        room.id: ChatMessage.query.filter_by(room_id=room.id)
            .order_by(ChatMessage.created_at.desc()).first()
        for room in rooms
    }
    return render_template('chat/inbox.html', rooms=rooms, last_messages=last_messages, hide_chat_bubble=True)


@chat_bp.route('/api/messages/<int:room_id>', methods=['GET'])
@login_required
def get_messages(room_id):
    room = ChatRoom.query.get_or_404(room_id)
    if room.user1_id != current_user.id and room.user2_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403

    since_id = request.args.get('since_id', 0, type=int)
    messages = ChatMessage.query.filter(
        ChatMessage.room_id == room_id,
        ChatMessage.id > since_id
    ).order_by(ChatMessage.created_at.asc()).all()

    # Mark as read
    ChatMessage.query.filter(
        ChatMessage.room_id == room_id,
        ChatMessage.sender_id != current_user.id,
        ChatMessage.is_read == False  # noqa: E712
    ).update({'is_read': True})
    db.session.commit()

    return jsonify({'messages': [m.to_dict() for m in messages]})


@chat_bp.route('/api/messages/<int:room_id>', methods=['POST'])
@login_required
def post_message(room_id):
    room = ChatRoom.query.get_or_404(room_id)
    if room.user1_id != current_user.id and room.user2_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403

    message_text = None
    file_url = None
    message_type = 'text'

    if request.is_json:
        data = request.get_json()
        message_text = (data.get('message') or '').strip()
    else:
        message_text = (request.form.get('message') or '').strip()
        f = request.files.get('file')
        if f and f.filename:
            file_url, mtype = save_chat_file(f, prefix=f"chat_{current_user.id}")
            if not file_url:
                return jsonify({'error': 'Unsupported or invalid file. Allowed: images, PDF, MP4/MOV.'}), 400
            message_type = mtype

    if not message_text and not file_url:
        return jsonify({'error': 'Message or file required'}), 400

    chat_msg = ChatMessage(
        room_id=room_id,
        sender_id=current_user.id,
        message=message_text[:4000] if message_text else None,
        message_type=message_type,
        file_url=file_url,
    )
    db.session.add(chat_msg)

    # Notify other user
    other_id = room.user2_id if room.user1_id == current_user.id else room.user1_id
    notif = Notification(
        user_id=other_id,
        type='message',
        title=f'New message from {current_user.username}',
        body=(message_text or 'Sent a file')[:100],
        link='/inbox',
    )
    db.session.add(notif)

    try:
        db.session.commit()
        return jsonify({'success': True, 'message': chat_msg.to_dict()})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@chat_bp.route('/api/unread-count', methods=['GET'])
@login_required
def unread_count():
    count = ChatMessage.query.join(ChatRoom).filter(
        ((ChatRoom.user1_id == current_user.id) | (ChatRoom.user2_id == current_user.id)),
        ChatMessage.sender_id != current_user.id,
        ChatMessage.is_read == False  # noqa: E712
    ).count()
    notif_count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
    pending = ConnectionRequest.query.join(ConnectionRequest.trip).filter(
        ConnectionRequest.status == 'pending',
        CompanionRequest.user_id == current_user.id
    ).all()
    pending_connections = [{
        'id': c.id,
        'requester': 'Anonymous' if c.requester_anonymous else c.requester.username,
        'trip_from': c.trip.flying_from or c.trip.road_from or '?',
        'trip_to': c.trip.destination or c.trip.road_to or '?',
    } for c in pending]
    return jsonify({'unread_messages': count, 'unread_notifications': notif_count,
                    'pending_connections': pending_connections})


@chat_bp.route('/api/rooms', methods=['GET'])
@login_required
def get_rooms():
    rooms = ChatRoom.query.filter(
        (ChatRoom.user1_id == current_user.id) | (ChatRoom.user2_id == current_user.id)
    ).order_by(ChatRoom.created_at.desc()).all()

    result = []
    for room in rooms:
        other = room.user2 if room.user1_id == current_user.id else room.user1
        last_msg = ChatMessage.query.filter_by(room_id=room.id).order_by(ChatMessage.created_at.desc()).first()
        unread = ChatMessage.query.filter_by(room_id=room.id, is_read=False).filter(
            ChatMessage.sender_id != current_user.id
        ).count()
        result.append({
            'room_id': room.id,
            'other_user': {'id': other.id, 'username': other.username,
                           'photo_url': other.photo_url if other.show_photo else None},
            'last_message': last_msg.to_dict() if last_msg else None,
            'unread_count': unread,
        })
    return jsonify({'rooms': result})
