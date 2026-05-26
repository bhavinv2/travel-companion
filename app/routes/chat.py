import os
from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user
from app import db, mail
from app.models import ChatRoom, ChatMessage, User, Notification, Message, ConnectionRequest, CompanionRequest
from flask_mail import Message as MailMessage
from datetime import datetime
from werkzeug.utils import secure_filename

chat_bp = Blueprint('chat', __name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'pdf', 'mp4', 'mov'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


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


@chat_bp.route('/api/send-message', methods=['POST'])
@login_required
def send_message():
    data = request.get_json() or {}
    recipient_id = data.get('recipient_id')
    body = data.get('body', '').strip()
    trip_id = data.get('trip_id')
    subject = data.get('subject', 'New message from Connecting Desis')

    if not recipient_id or not body:
        return jsonify({'error': 'recipient_id and body are required'}), 400

    recipient = User.query.get(recipient_id)
    if not recipient:
        return jsonify({'error': 'Recipient not found'}), 404

    # Save in-app message
    msg = Message(
        sender_id=current_user.id,
        recipient_id=recipient_id,
        trip_id=trip_id,
        subject=subject,
        body=body,
        masked_relay=True,
    )
    db.session.add(msg)

    # Get or create chat room
    room = ChatRoom.get_or_create(current_user.id, recipient_id, trip_id)

    # Save chat message
    chat_msg = ChatMessage(
        room_id=room.id,
        sender_id=current_user.id,
        message=body,
        message_type='text',
    )
    db.session.add(chat_msg)

    # In-app notification
    notif = Notification(
        user_id=recipient_id,
        type='message',
        title=f'New message from {current_user.username}',
        body=body[:100],
        link='/inbox',
    )
    db.session.add(notif)

    try:
        db.session.commit()

        # Masked email relay — never expose sender's email
        try:
            relay_msg = MailMessage(
                subject=f"[Connecting Desis] {subject}",
                recipients=[recipient.email],
                body=(
                    f"You have a new message on Connecting Desis!\n\n"
                    f"From: {current_user.username}\n\n"
                    f"Message:\n{body}\n\n"
                    f"Reply via: https://connectingdesis.com/inbox\n\n"
                    f"– Connecting Desis Team\n"
                    f"(Do not reply to this email — use the app to respond)"
                ),
                reply_to=current_app.config.get('MAIL_DEFAULT_SENDER'),
            )
            mail.send(relay_msg)
        except Exception:
            pass

        return jsonify({'success': True, 'room_id': room.id, 'message': chat_msg.to_dict()})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


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
        ChatMessage.is_read == False
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
        message_text = data.get('message', '').strip()
    else:
        message_text = request.form.get('message', '').strip()
        file = request.files.get('file')
        if file and file.filename and allowed_file(file.filename):
            filename = secure_filename(f"{current_user.id}_{int(datetime.utcnow().timestamp())}_{file.filename}")
            file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
            file_url = f"/static/uploads/{filename}"
            ext = filename.rsplit('.', 1)[1].lower()
            if ext in ('mp4', 'mov'):
                message_type = 'video'
            elif ext == 'pdf':
                message_type = 'file'
            else:
                message_type = 'image'

    if not message_text and not file_url:
        return jsonify({'error': 'Message or file required'}), 400

    chat_msg = ChatMessage(
        room_id=room_id,
        sender_id=current_user.id,
        message=message_text,
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
        ChatMessage.is_read == False
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
    return jsonify({'unread_messages': count, 'unread_notifications': notif_count, 'pending_connections': pending_connections})


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
            'other_user': {'id': other.id, 'username': other.username, 'photo_url': other.photo_url if other.show_photo else None},
            'last_message': last_msg.to_dict() if last_msg else None,
            'unread_count': unread,
        })
    return jsonify({'rooms': result})
