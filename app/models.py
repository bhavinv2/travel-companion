import secrets
from datetime import datetime, date, timedelta
from flask_login import UserMixin
from app import db
import bcrypt


# ---------------------------------------------------------------------------
# Enumerations (kept as plain strings so they work identically on SQLite/Postgres)
# ---------------------------------------------------------------------------

USER_ROLES = ('user', 'cs', 'admin')

TRIP_STATUSES = ('unconfirmed', 'open', 'matched', 'closed')
TRIP_SOURCES = ('organic', 'facebook', 'website', 'excel')
TRIP_ROLES = ('seeking_help', 'offering_help', 'open')
TRIP_ROLE_LABELS = {
    'seeking_help': 'Seeking help',
    'offering_help': 'Offering help',
    'open': 'Open to either',
}
CLOSED_REASONS = (
    'information_shared', 'no_longer_required', 'travelled',
    'duplicate', 'unreachable', 'spam',
)
CLOSED_REASON_LABELS = {
    'information_shared': 'Information shared',
    'no_longer_required': 'No longer required',
    'travelled': 'Already travelled',
    'duplicate': 'Duplicate post',
    'unreachable': 'Could not reach the person',
    'spam': 'Spam / not genuine',
}
AGE_GROUPS = ('under_18', '18_30', '31_45', '46_60', '60_plus')
AGE_GROUP_LABELS = {
    'under_18': 'Under 18', '18_30': '18–30', '31_45': '31–45', '46_60': '46–60', '60_plus': '60+',
}
GENDERS = ('female', 'male', 'other', 'unspecified')
PREF_GENDERS = ('any', 'female', 'male')

CONTACT_TYPES = ('email', 'mobile', 'whatsapp', 'facebook', 'instagram', 'inapp_chat', 'other')
CONTACT_TYPE_LABELS = {
    'email': 'Email', 'mobile': 'Mobile', 'whatsapp': 'WhatsApp', 'facebook': 'Facebook',
    'instagram': 'Instagram', 'inapp_chat': 'Chat on Connecting Desis', 'other': 'Other',
}
# Font Awesome classes (the FA 6 CSS is already loaded in base.html)
CONTACT_TYPE_ICONS = {
    'email': 'fa-solid fa-envelope',
    'mobile': 'fa-solid fa-mobile-screen',
    'whatsapp': 'fa-brands fa-whatsapp',
    'facebook': 'fa-brands fa-facebook',
    'instagram': 'fa-brands fa-instagram',
    'inapp_chat': 'fa-solid fa-comments',
    'other': 'fa-solid fa-globe',
}


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
    is_verified = db.Column(db.Boolean, default=False)   # e-mail verified
    is_admin = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    role = db.Column(db.String(20), default='user')      # user / cs / admin
    phone_verified = db.Column(db.Boolean, default=False)
    oauth_provider = db.Column(db.String(50))
    oauth_id = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = db.Column(db.DateTime)

    trips = db.relationship('CompanionRequest', backref='author', lazy='dynamic',
                            foreign_keys='CompanionRequest.user_id')
    notifications = db.relationship('Notification', backref='user', lazy='dynamic')
    feedbacks = db.relationship('Feedback', backref='user', lazy='dynamic')
    contact_points = db.relationship('ContactPoint', backref='owner', lazy='dynamic',
                                     foreign_keys='ContactPoint.user_id')

    def set_password(self, password):
        self.password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    def check_password(self, password):
        if not self.password_hash:
            return False
        return bcrypt.checkpw(password.encode('utf-8'), self.password_hash.encode('utf-8'))

    @property
    def full_name(self):
        return f"{self.first_name or ''} {self.last_name or ''}".strip() or self.username

    @property
    def is_cs(self):
        """Customer-service staff (or admins) may use the CS console."""
        return bool(self.is_admin) or self.role in ('cs', 'admin')

    @property
    def effective_role(self):
        if self.is_admin:
            return 'admin'
        return self.role or 'user'

    def __repr__(self):
        return f'<User {self.username}>'


class CompanionRequest(db.Model):
    """A travel-companion post ("trip"/"listing")."""
    __tablename__ = 'companion_requests'

    id = db.Column(db.Integer, primary_key=True)
    # Nullable since Phase 2: CS-created posts have no owning account until claimed.
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    travel_type = db.Column(db.String(10), nullable=False)  # air / road
    trip_type = db.Column(db.String(30))  # one_way / round_trip / multi_destination

    on_behalf_of = db.Column(db.String(50))
    connect_me_to = db.Column(db.JSON)
    traveller_needs = db.Column(db.JSON)
    special_needs_notes = db.Column(db.Text)

    # Air fields (display strings, e.g. "Hyderabad (HYD)")
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

    # Normalised route (Phase 2) — used by matching
    origin_iata = db.Column(db.String(5), index=True)
    origin_city = db.Column(db.String(120))
    origin_metro = db.Column(db.String(60), index=True)
    dest_iata = db.Column(db.String(5), index=True)
    dest_city = db.Column(db.String(120))
    dest_metro = db.Column(db.String(60), index=True)

    # Road fields (schema only — no UI yet)
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
    ticket_attachment = db.Column(db.String(300))  # private storage key (never under /static)
    category = db.Column(db.String(100))
    is_active = db.Column(db.Boolean, default=True)   # kept for compatibility; mirrors status
    is_anonymous = db.Column(db.Boolean, default=False)
    views = db.Column(db.Integer, default=0)
    expires_at = db.Column(db.Date)

    # Phase 2: intake, people, role, preferences, lifecycle
    source = db.Column(db.String(20), default='organic', index=True)   # organic/facebook/website/excel
    source_url = db.Column(db.String(500))
    import_key = db.Column(db.String(64), unique=True, nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # CS agent
    poster_name = db.Column(db.String(120))
    traveler_name = db.Column(db.String(120))
    role = db.Column(db.String(20), default='seeking_help', index=True)  # seeking_help/offering_help/open
    traveler_age_group = db.Column(db.String(10))
    traveler_gender = db.Column(db.String(15))
    pref_gender = db.Column(db.String(10), default='any')
    pref_age_min = db.Column(db.Integer)
    pref_age_max = db.Column(db.Integer)
    status = db.Column(db.String(15), default='open', index=True)  # unconfirmed/open/matched/closed
    closed_reason = db.Column(db.String(30))
    closed_at = db.Column(db.DateTime)
    closed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    claimed_at = db.Column(db.DateTime)
    cs_notes = db.Column(db.Text)  # internal notes, never shown publicly
    last_match_alert_at = db.Column(db.DateTime)  # throttle for "new possible companion" heads-ups

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    created_by = db.relationship('User', foreign_keys=[created_by_id])
    closed_by = db.relationship('User', foreign_keys=[closed_by_id])
    contact_points = db.relationship('ContactPoint', backref='trip', lazy='select',
                                     foreign_keys='ContactPoint.trip_id',
                                     cascade='all, delete-orphan')
    claim_tokens = db.relationship('ClaimToken', backref='trip', lazy='dynamic',
                                   cascade='all, delete-orphan')

    # --- lifecycle helpers -------------------------------------------------

    def set_status(self, status, reason=None, by=None):
        assert status in TRIP_STATUSES, status
        self.status = status
        self.is_active = status in ('open', 'matched')
        if status == 'closed':
            self.closed_reason = reason
            self.closed_at = datetime.utcnow()
            self.closed_by_id = by.id if by else None
        else:
            self.closed_reason = None
            self.closed_at = None
            self.closed_by_id = None

    @property
    def is_public(self):
        return self.status in ('open', 'matched')

    @property
    def is_claimed(self):
        return self.claimed_at is not None or self.source == 'organic'

    def is_expired(self):
        if self.expires_at:
            return date.today() > self.expires_at
        if self.trip_type == 'multi_destination' and self.legs:
            last_date_str = self.legs[-1].get('date')
            if last_date_str:
                return date.today() > datetime.strptime(last_date_str, '%Y-%m-%d').date()
        if self.to_date:
            return date.today() > self.to_date
        if self.from_date:
            return date.today() > self.from_date
        return False

    @property
    def days_to_departure(self):
        d = self.from_date or self.road_from_date
        return (d - date.today()).days if d else None

    @property
    def route_display(self):
        return f"{self.flying_from or self.road_from or '?'} → {self.destination or self.road_to or '?'}"

    @property
    def display_name(self):
        """Public name of the poster (respects anonymity; CS posts have no account)."""
        if self.is_anonymous:
            return 'Anonymous'
        if self.author:
            return self.author.username
        return (self.poster_name or '').split(' ')[0] or 'Traveller'

    @property
    def consented_contact_types(self):
        return sorted({cp.type for cp in self.contact_points if cp.consent_to_share})

    @property
    def contact_types(self):
        return sorted({cp.type for cp in self.contact_points})

    def to_dict(self, viewer_id=None):
        is_own = viewer_id is not None and self.user_id == viewer_id
        author_photo = None
        if not self.is_anonymous and self.author and self.author.show_photo:
            author_photo = self.author.photo_url
        return {
            'id': self.id,
            'travel_type': self.travel_type,
            'trip_type': self.trip_type,
            'role': self.role,
            'status': self.status,
            'on_behalf_of': self.on_behalf_of,
            'connect_me_to': self.connect_me_to or [],
            'traveller_needs': self.traveller_needs or [],
            'special_needs_notes': self.special_needs_notes,
            'flying_from': self.flying_from,
            'destination': self.destination,
            'origin_iata': self.origin_iata,
            'dest_iata': self.dest_iata,
            'from_date': self.from_date.isoformat() if self.from_date else None,
            'to_date': self.to_date.isoformat() if self.to_date else None,
            'from_date_flexible': bool(self.from_date_flexible),
            'flying_from_flexible': bool(self.flying_from_flexible),
            'destination_flexible': bool(self.destination_flexible),
            'airline': self.airline,
            'flight_number': self.flight_number,
            'preferred_languages': self.preferred_languages or [],
            'road_from': self.road_from,
            'road_to': self.road_to,
            'road_from_date': self.road_from_date.isoformat() if self.road_from_date else None,
            'road_to_date': self.road_to_date.isoformat() if self.road_to_date else None,
            'travelling_by': self.travelling_by,
            'legs': self.legs or [],
            'additional_comments': None if self.is_anonymous and not is_own else self.additional_comments,
            'ticket_booked': self.ticket_booked,
            'traveler_age_group': self.traveler_age_group,
            'traveler_gender': self.traveler_gender,
            'pref_gender': self.pref_gender,
            'pref_age_min': self.pref_age_min,
            'pref_age_max': self.pref_age_max,
            'category': self.category,
            'is_active': self.is_active,
            'is_anonymous': self.is_anonymous,
            'is_own': is_own,
            # Never reveal the account behind an anonymous post to other users.
            'user_id': self.user_id if (is_own or not self.is_anonymous) else None,
            'views': self.views,
            'days_to_departure': self.days_to_departure,
            'contact_types': self.consented_contact_types,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'author': {
                'username': self.display_name,
                'photo_url': author_photo,
            },
        }


class ContactPoint(db.Model):
    """A way to reach the person behind a post. Shared only when consent_to_share is true."""
    __tablename__ = 'contact_points'

    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey('companion_requests.id'), nullable=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    type = db.Column(db.String(20), nullable=False)      # see CONTACT_TYPES
    value = db.Column(db.String(255), nullable=False)
    label = db.Column(db.String(100))                    # e.g. "son's WhatsApp"
    is_preferred = db.Column(db.Boolean, default=False)
    consent_to_share = db.Column(db.Boolean, default=False)
    verified = db.Column(db.Boolean, default=False)
    added_by = db.Column(db.String(10), default='owner')  # owner / cs / import
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self, reveal_value=False):
        d = {
            'id': self.id,
            'type': self.type,
            'label': self.label,
            'is_preferred': self.is_preferred,
            'consent_to_share': self.consent_to_share,
            'verified': self.verified,
            'added_by': self.added_by,
        }
        if reveal_value:
            d['value'] = self.value
        return d


class ClaimToken(db.Model):
    """Single-use link that lets a person confirm a CS-created post and add their contact details."""
    __tablename__ = 'claim_tokens'

    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False, index=True)
    trip_id = db.Column(db.Integer, db.ForeignKey('companion_requests.id'), nullable=False)
    purpose = db.Column(db.String(30), default='collect_contact')
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    created_by = db.relationship('User', foreign_keys=[created_by_id])

    @staticmethod
    def issue(trip, days=14, purpose='collect_contact', created_by=None):
        tok = ClaimToken(
            token=secrets.token_urlsafe(32),
            trip_id=trip.id,
            purpose=purpose,
            expires_at=datetime.utcnow() + timedelta(days=days),
            created_by_id=created_by.id if created_by else None,
        )
        db.session.add(tok)
        return tok

    @property
    def is_valid(self):
        return self.used_at is None and self.expires_at > datetime.utcnow()


class ActivityEvent(db.Model):
    """Audit trail of everything that happens to a post / match (who did what, when)."""
    __tablename__ = 'activity_events'

    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey('companion_requests.id'), nullable=True, index=True)
    match_id = db.Column(db.Integer, nullable=True, index=True)   # FK added when matches table lands (2B)
    actor_type = db.Column(db.String(10), default='system')       # user / cs / system
    actor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    event = db.Column(db.String(40), nullable=False, index=True)
    meta = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    actor = db.relationship('User', foreign_keys=[actor_id])
    trip = db.relationship('CompanionRequest', foreign_keys=[trip_id],
                           backref=db.backref('events', lazy='dynamic', order_by='ActivityEvent.created_at.desc()'))

    @staticmethod
    def log(event, trip=None, actor=None, match_id=None, **meta):
        actor_type = 'system'
        if actor is not None:
            actor_type = 'cs' if getattr(actor, 'is_cs', False) else 'user'
        ev = ActivityEvent(
            trip_id=trip.id if trip is not None else None,
            match_id=match_id,
            actor_type=actor_type,
            actor_id=actor.id if actor is not None else None,
            event=event,
            meta=meta or None,
        )
        db.session.add(ev)
        return ev


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
    # trip_match/message/blog/trip_modified/trip_cancelled/connection_request/connection_accepted/
    # connection_denied/match_found/contact_shared/cs_escalation/post_claimed
    type = db.Column(db.String(50))
    title = db.Column(db.String(255))
    body = db.Column(db.Text)
    is_read = db.Column(db.Boolean, default=False)
    link = db.Column(db.String(500))
    connection_id = db.Column(db.Integer, db.ForeignKey('connection_requests.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'type': self.type,
            'title': self.title,
            'body': self.body,
            'is_read': self.is_read,
            'link': self.link,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


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


# ---------------------------------------------------------------------------
# Phase 2B: matching & communication bridge
# ---------------------------------------------------------------------------

MATCH_STATUSES = ('suggested', 'notified', 'viewed', 'connected', 'dismissed')
DISMISS_REASONS = ('not_suitable', 'duplicate', 'wrong_direction', 'post_changed', 'post_closed', 'not_suitable_by_party')
PARTY_STATUSES = ('pending', 'sent', 'opened', 'contact_viewed', 'connected', 'not_suitable', 'no_response')
PARTY_CHANNELS = ('email', 'inapp', 'manual_mobile', 'manual_whatsapp', 'manual_facebook',
                  'manual_instagram', 'manual_other', 'none')
CHANNEL_LABELS = {
    'email': 'E-mail (automatic)', 'inapp': 'In-app notification (automatic)',
    'manual_mobile': 'Call / SMS (manual)', 'manual_whatsapp': 'WhatsApp (manual)',
    'manual_facebook': 'Facebook DM (manual)', 'manual_instagram': 'Instagram DM (manual)',
    'manual_other': 'Other (manual)', 'none': 'Not reachable yet',
}


class Match(db.Model):
    """A scored pairing of two posts. trip_a_id < trip_b_id so each pair exists once."""
    __tablename__ = 'matches'
    __table_args__ = (db.UniqueConstraint('trip_a_id', 'trip_b_id', name='uq_matches_pair'),)

    id = db.Column(db.Integer, primary_key=True)
    trip_a_id = db.Column(db.Integer, db.ForeignKey('companion_requests.id'), nullable=False, index=True)
    trip_b_id = db.Column(db.Integer, db.ForeignKey('companion_requests.id'), nullable=False, index=True)
    score = db.Column(db.Integer, nullable=False, default=0)
    criteria = db.Column(db.JSON)          # [{key, label, ok, detail, points, weight}, ...]
    status = db.Column(db.String(15), default='suggested', index=True)
    dismissed_reason = db.Column(db.String(40))
    cs_owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    needs_cs_attention = db.Column(db.Boolean, default=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    trip_a = db.relationship('CompanionRequest', foreign_keys=[trip_a_id],
                             backref=db.backref('matches_as_a', lazy='dynamic'))
    trip_b = db.relationship('CompanionRequest', foreign_keys=[trip_b_id],
                             backref=db.backref('matches_as_b', lazy='dynamic'))
    cs_owner = db.relationship('User', foreign_keys=[cs_owner_id])
    parties = db.relationship('MatchParty', backref='match', lazy='select', cascade='all, delete-orphan')

    @staticmethod
    def ordered_ids(x, y):
        return (x, y) if x < y else (y, x)

    def other_trip(self, trip_id):
        return self.trip_b if trip_id == self.trip_a_id else self.trip_a

    def party_for(self, trip_id):
        return next((p for p in self.parties if p.trip_id == trip_id), None)

    def involves_user(self, user_id):
        return user_id is not None and user_id in (self.trip_a.user_id, self.trip_b.user_id)

    @property
    def is_open(self):
        return self.status != 'dismissed' and self.trip_a.is_public and self.trip_b.is_public

    def to_dict(self, for_trip_id=None, viewer_id=None):
        other = self.other_trip(for_trip_id) if for_trip_id else None
        d = {
            'id': self.id,
            'score': self.score,
            'criteria': self.criteria or [],
            'status': self.status,
            'needs_cs_attention': self.needs_cs_attention,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
        if other is not None:
            d['other'] = other.to_dict(viewer_id=viewer_id)
            mine = self.party_for(for_trip_id)
            theirs = self.party_for(other.id)
            d['my_status'] = mine.status if mine else None
            d['their_status'] = theirs.status if theirs else None
            d['my_token'] = mine.token if mine else None
        return d


class MatchParty(db.Model):
    """One side of a match: how (and whether) that person was told, and what they did next."""
    __tablename__ = 'match_parties'
    __table_args__ = (db.UniqueConstraint('match_id', 'trip_id', name='uq_match_parties_side'),)

    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('matches.id'), nullable=False, index=True)
    trip_id = db.Column(db.Integer, db.ForeignKey('companion_requests.id'), nullable=False, index=True)
    channel = db.Column(db.String(20), default='none')
    token = db.Column(db.String(64), unique=True, nullable=False, index=True)
    status = db.Column(db.String(20), default='pending', index=True)
    sent_at = db.Column(db.DateTime)
    sent_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    opened_at = db.Column(db.DateTime)
    viewed_at = db.Column(db.DateTime)
    last_activity_at = db.Column(db.DateTime)
    escalated_at = db.Column(db.DateTime)   # set by the escalation job when no movement after notification
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    trip = db.relationship('CompanionRequest', foreign_keys=[trip_id])
    sent_by = db.relationship('User', foreign_keys=[sent_by_id])

    @staticmethod
    def get_or_create(match, trip_id, channel='none'):
        p = match.party_for(trip_id)
        if p is None:
            p = MatchParty(match=match, trip_id=trip_id, channel=channel, token=secrets.token_urlsafe(32))
            db.session.add(p)
        return p

    def touch(self, status=None):
        self.last_activity_at = datetime.utcnow()
        if status:
            self.status = status

    def to_dict(self):
        return {
            'id': self.id, 'trip_id': self.trip_id, 'channel': self.channel, 'status': self.status,
            'sent_at': self.sent_at.isoformat() if self.sent_at else None,
            'opened_at': self.opened_at.isoformat() if self.opened_at else None,
            'viewed_at': self.viewed_at.isoformat() if self.viewed_at else None,
        }
