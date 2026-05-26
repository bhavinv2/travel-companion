from datetime import datetime, date
from flask_login import UserMixin
from app import db
import bcrypt


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255))
    first_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100))
    phone = db.Column(db.String(30))
    photo_url = db.Column(db.String(500))
    show_photo = db.Column(db.Boolean, default=False)
    dob = db.Column(db.Date)
    language_preference = db.Column(db.String(50), default='en')
    bio = db.Column(db.Text)
    marketing_consent = db.Column(db.Boolean, default=False)
    is_verified = db.Column(db.Boolean, default=False)
    is_admin = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    oauth_provider = db.Column(db.String(50))
    oauth_id = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = db.Column(db.DateTime)

    trips = db.relationship('CompanionRequest', backref='author', lazy='dynamic', foreign_keys='CompanionRequest.user_id')
    sent_messages = db.relationship('Message', backref='sender', lazy='dynamic', foreign_keys='Message.sender_id')
    received_messages = db.relationship('Message', backref='recipient', lazy='dynamic', foreign_keys='Message.recipient_id')
    notifications = db.relationship('Notification', backref='user', lazy='dynamic')
    feedbacks = db.relationship('Feedback', backref='user', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    def check_password(self, password):
        if not self.password_hash:
            return False
        return bcrypt.checkpw(password.encode('utf-8'), self.password_hash.encode('utf-8'))

    @property
    def full_name(self):
        return f"{self.first_name or ''} {self.last_name or ''}".strip() or self.username

    def __repr__(self):
        return f'<User {self.username}>'


class CompanionRequest(db.Model):
    __tablename__ = 'companion_requests'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    travel_type = db.Column(db.String(10), nullable=False)  # air / road
    trip_type = db.Column(db.String(30))  # one_way / round_trip / multi_destination

    on_behalf_of = db.Column(db.String(50))
    connect_me_to = db.Column(db.JSON)
    traveller_needs = db.Column(db.JSON)
    special_needs_notes = db.Column(db.Text)

    # Air fields
    flying_from = db.Column(db.String(200))
    flying_from_flexible = db.Column(db.Boolean, default=False)
    destination = db.Column(db.String(200))
    destination_flexible = db.Column(db.Boolean, default=False)
    from_date = db.Column(db.Date)
    from_date_flexible = db.Column(db.Boolean, default=False)
    to_date = db.Column(db.Date)
    to_date_flexible = db.Column(db.Boolean, default=False)
    airline = db.Column(db.String(200))
    flight_number = db.Column(db.String(30))
    preferred_languages = db.Column(db.JSON)

    # Road fields
    road_from = db.Column(db.String(200))
    road_to = db.Column(db.String(200))
    road_from_date = db.Column(db.Date)
    road_from_time = db.Column(db.Time)
    road_from_flexible = db.Column(db.Boolean, default=False)
    road_to_date = db.Column(db.Date)
    road_to_time = db.Column(db.Time)
    road_to_flexible = db.Column(db.Boolean, default=False)
    travelling_by = db.Column(db.String(100))

    legs = db.Column(db.JSON)  # multi-destination: [{from, to, date, airline, flight_number}, ...]

    additional_comments = db.Column(db.Text)
    ticket_booked = db.Column(db.Boolean, default=False)
    category = db.Column(db.String(100))
    is_active = db.Column(db.Boolean, default=True)
    is_anonymous = db.Column(db.Boolean, default=False)
    views = db.Column(db.Integer, default=0)
    expires_at = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages = db.relationship('Message', backref='trip', lazy='dynamic')

    def is_expired(self):
        if self.expires_at:
            return date.today() > self.expires_at
        if self.trip_type == 'multi_destination' and self.legs:
            last_date_str = self.legs[-1].get('date')
            if last_date_str:
                from datetime import datetime as _dt
                return date.today() > _dt.strptime(last_date_str, '%Y-%m-%d').date()
        if self.to_date:
            return date.today() > self.to_date
        if self.from_date:
            return date.today() > self.from_date
        return False

    def to_dict(self):
        return {
            'id': self.id,
            'travel_type': self.travel_type,
            'trip_type': self.trip_type,
            'on_behalf_of': self.on_behalf_of,
            'connect_me_to': self.connect_me_to or [],
            'traveller_needs': self.traveller_needs or [],
            'special_needs_notes': self.special_needs_notes,
            'flying_from': self.flying_from,
            'destination': self.destination,
            'from_date': self.from_date.isoformat() if self.from_date else None,
            'to_date': self.to_date.isoformat() if self.to_date else None,
            'airline': self.airline,
            'flight_number': self.flight_number,
            'preferred_languages': self.preferred_languages or [],
            'road_from': self.road_from,
            'road_to': self.road_to,
            'road_from_date': self.road_from_date.isoformat() if self.road_from_date else None,
            'road_to_date': self.road_to_date.isoformat() if self.road_to_date else None,
            'travelling_by': self.travelling_by,
            'legs': self.legs or [],
            'additional_comments': self.additional_comments,
            'ticket_booked': self.ticket_booked,
            'category': self.category,
            'is_active': self.is_active,
            'is_anonymous': self.is_anonymous,
            'user_id': self.user_id,
            'views': self.views,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'author': {
                'username': self.author.username if not self.is_anonymous else 'Anonymous',
                'photo_url': self.author.photo_url if (not self.is_anonymous and self.author.show_photo) else None,
            }
        }


class Message(db.Model):
    __tablename__ = 'messages'

    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    trip_id = db.Column(db.Integer, db.ForeignKey('companion_requests.id'), nullable=True)
    subject = db.Column(db.String(255))
    body = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    masked_relay = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ChatRoom(db.Model):
    __tablename__ = 'chat_rooms'

    id = db.Column(db.Integer, primary_key=True)
    user1_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    user2_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    trip_id = db.Column(db.Integer, db.ForeignKey('companion_requests.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user1 = db.relationship('User', foreign_keys=[user1_id])
    user2 = db.relationship('User', foreign_keys=[user2_id])
    chat_messages = db.relationship('ChatMessage', backref='room', lazy='dynamic')

    @staticmethod
    def get_or_create(user1_id, user2_id, trip_id=None):
        room = ChatRoom.query.filter(
            ((ChatRoom.user1_id == user1_id) & (ChatRoom.user2_id == user2_id)) |
            ((ChatRoom.user1_id == user2_id) & (ChatRoom.user2_id == user1_id))
        ).first()
        if not room:
            room = ChatRoom(user1_id=user1_id, user2_id=user2_id, trip_id=trip_id)
            from app import db
            db.session.add(room)
            db.session.commit()
        return room


class ChatMessage(db.Model):
    __tablename__ = 'chat_messages'

    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey('chat_rooms.id'), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    message = db.Column(db.Text)
    message_type = db.Column(db.String(20), default='text')  # text/image/file/video
    file_url = db.Column(db.String(500))
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    sender = db.relationship('User', foreign_keys=[sender_id])

    def to_dict(self):
        return {
            'id': self.id,
            'room_id': self.room_id,
            'sender_id': self.sender_id,
            'sender_username': self.sender.username,
            'message': self.message,
            'message_type': self.message_type,
            'file_url': self.file_url,
            'is_read': self.is_read,
            'created_at': self.created_at.isoformat(),
        }


class Blog(db.Model):
    __tablename__ = 'blogs'

    id = db.Column(db.Integer, primary_key=True)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(300), nullable=False)
    slug = db.Column(db.String(350), unique=True, nullable=False)
    content = db.Column(db.Text)
    cover_image_url = db.Column(db.String(500))
    is_published = db.Column(db.Boolean, default=False)
    published_at = db.Column(db.DateTime)
    send_notification = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    author = db.relationship('User', backref='blogs')

    def excerpt(self, length=200):
        if self.content:
            return self.content[:length] + '...' if len(self.content) > length else self.content
        return ''


class Feedback(db.Model):
    __tablename__ = 'feedbacks'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)  # 1-5
    comment = db.Column(db.Text)
    is_approved = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Notification(db.Model):
    __tablename__ = 'notifications'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    type = db.Column(db.String(50))  # trip_match/message/blog/trip_modified/trip_cancelled/connection_request/connection_accepted/connection_denied
    title = db.Column(db.String(255))
    body = db.Column(db.Text)
    is_read = db.Column(db.Boolean, default=False)
    link = db.Column(db.String(500))
    connection_id = db.Column(db.Integer, db.ForeignKey('connection_requests.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ConnectionRequest(db.Model):
    __tablename__ = 'connection_requests'

    id = db.Column(db.Integer, primary_key=True)
    requester_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    trip_id = db.Column(db.Integer, db.ForeignKey('companion_requests.id'), nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending/accepted/denied
    requester_anonymous = db.Column(db.Boolean, default=False)
    recipient_anonymous = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    requester = db.relationship('User', foreign_keys=[requester_id])
    trip = db.relationship('CompanionRequest', foreign_keys=[trip_id])
