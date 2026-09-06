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
    from app.models import Notification, ConnectionRequest, CompanionRequest, User
    my_trip_ids = [t.id for t in CompanionRequest.query.filter_by(user_id=current_user.id).all()]
    pending_requests = []
    if my_trip_ids:
        for c in (ConnectionRequest.query.filter(ConnectionRequest.trip_id.in_(my_trip_ids),
                                                 ConnectionRequest.status == 'pending')
                  .order_by(ConnectionRequest.created_at.desc()).all()):
            req_user = db.session.get(User, c.requester_id)
            trip = db.session.get(CompanionRequest, c.trip_id)
            anon = bool(c.requester_anonymous)
            their_trip = None
            if req_user and not anon:
                their_trip = (CompanionRequest.query.filter_by(user_id=req_user.id)
                              .order_by(CompanionRequest.created_at.desc()).first())
            pending_requests.append({
                'id': c.id,
                'name': 'Anonymous' if anon else (req_user.username if req_user else 'Traveller'),
                'anonymous': anon,
                'photo': (req_user.photo_url if req_user and req_user.show_photo and not anon else None),
                'member_since': (req_user.created_at.strftime('%b %Y') if req_user and req_user.created_at and not anon else None),
                'languages': (their_trip.preferred_languages or []) if their_trip else [],
                'their_route': their_trip.route_display if their_trip else None,
                'their_date': their_trip.from_date.isoformat() if their_trip and their_trip.from_date else None,
                'their_role': their_trip.role if their_trip else None,
                'route': trip.route_display if trip else '',
                'trip_date': trip.from_date.isoformat() if trip and trip.from_date else None,
                'when': c.created_at.strftime('%b %d, %H:%M') if c.created_at else '',
            })
    notif_list = [n.to_dict() for n in (Notification.query.filter_by(user_id=current_user.id)
                                        .order_by(Notification.created_at.desc()).limit(30).all())]
    return render_template('chat/inbox.html', rooms=rooms, last_messages=last_messages,
                           pending_requests=pending_requests, notif_list=notif_list, hide_chat_bubble=True)


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

    # Notify other user (respects the notification switches / their preferences)
    from app.services import notify
    other_id = room.user2_id if room.user1_id == current_user.id else room.user1_id
    notify.push(other_id, 'message', title=f'New message from {current_user.username}',
                body=(message_text or 'Sent a file')[:100], link='/inbox')

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
