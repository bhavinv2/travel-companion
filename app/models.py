import secrets
from datetime import datetime, date, timedelta
from flask_login import UserMixin
from sqlalchemy import event
from sqlalchemy.orm import validates
from app import db
import bcrypt


# ---------------------------------------------------------------------------
# Enumerations (kept as plain strings so they work identically on SQLite/Postgres)
# ---------------------------------------------------------------------------

USER_ROLES = ('user', 'cs', 'admin')

TRIP_STATUSES = ('unconfirmed', 'open', 'matched', 'closed')
# Every source a post can carry. 'organic' means the traveller posted it themselves — it is set by
# the public post form, and is_claimed/the CS queue/reminder jobs all key off it, so it is never an
# option a human picks. 'excel' is stamped by the importer. CS_TRIP_SOURCES is what staff can choose
# when creating a post on someone's behalf.
TRIP_SOURCES = ('organic', 'whatsapp', 'facebook', 'website', 'other', 'excel')
CS_TRIP_SOURCES = ('whatsapp', 'website', 'facebook', 'other')
TRIP_SOURCE_LABELS = {
    'organic': 'Organic (self-posted)', 'whatsapp': 'WhatsApp', 'facebook': 'Facebook',
    'website': 'Website', 'other': 'Other', 'excel': 'Excel import',
}
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
    'instagram': 'Instagram', 'inapp_chat': 'Chat on NRI Parent Service', 'other': 'Other',
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
    # made on the sign-up page: the only accounts asked to confirm their e-mail (needs_email_check). Accounts
    # staff make or invite, ones that claimed a post and staff accounts are never asked.
    signed_up = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    is_admin = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    role = db.Column(db.String(20), default='user')      # legacy: highest access level (user / cs / admin)
    # Which CS console screens this agent may open. NULL means all of them, which is what
    # everybody has today and what a new hire gets -- an admin narrows it afterwards. See
    # services/cs_access.py; it grants screens, not rows.
    cs_access = db.Column(db.JSON)
    # All roles the account holds, e.g. ["user", "cs"]. Role keys and their access levels are configurable at
    # /admin/options; `role` and `is_admin` are kept in sync by set_roles() so existing checks keep working.
    roles = db.Column(db.JSON)
    phone_verified = db.Column(db.Boolean, default=False)
    # Per-user notification preferences: {"muted": bool, "email": bool, "<category>": bool}
    notify_prefs = db.Column(db.JSON)
    # Staff only: when this person last opened each "what's new" list, {list key: ISO time}.
    # Only for the lists with no status of their own to say "somebody has looked" -- see
    # services/whats_new.py. NULL means never looked.
    seen_marks = db.Column(db.JSON)
    oauth_provider = db.Column(db.String(50))
    oauth_id = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    # Sign-in security (services/signin.py). Raising session_version signs every device out at once: it is part of
    # the id the session and the "remember me" cookie carry (get_id). totp_secret is the authenticator app's key
    # while two-step sign-in is on; backup_codes the hashes of the one-time codes still unused.
    session_version = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    totp_secret = db.Column(db.String(64))
    totp_on_at = db.Column(db.DateTime)
    backup_codes = db.Column(db.JSON)
    # Staff only, the tour guide (services/tours.py): {'ask': 'never' after "Don't ask again", 'asked_at': when the
    # question was last shown (ISO, UTC), 'done': [tour keys finished]}. NULL: never asked, nothing done.
    tour_state = db.Column(db.JSON)

    trips = db.relationship('CompanionRequest', backref='author', lazy='dynamic',
                            foreign_keys='CompanionRequest.user_id')
    notifications = db.relationship('Notification', backref='user', lazy='dynamic')
    feedbacks = db.relationship('Feedback', backref='user', lazy='dynamic')
    contact_points = db.relationship('ContactPoint', backref='owner', lazy='dynamic',
                                     foreign_keys='ContactPoint.user_id')

    def get_id(self):
        """What the session and the "remember me" cookie carry: the id, and the session version once it was raised,
        so raising it (services/signin.sign_out_everywhere) makes every older session and cookie stop working."""
        v = self.session_version or 0
        return str(self.id) if not v else '%d.%d' % (self.id, v)

    @property
    def two_step_on(self):
        return bool(self.totp_secret)

    def set_password(self, password):
        self.password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    def check_password(self, password):
        if not self.password_hash:
            return False
        return bcrypt.checkpw(password.encode('utf-8'), self.password_hash.encode('utf-8'))

    @property
    def full_name(self):
        return f"{self.first_name or ''} {self.last_name or ''}".strip() or self.username

    # ---- roles -------------------------------------------------------------------------------------
    @property
    def role_keys(self):
        """Role keys held by this account (falls back to the legacy single role for old rows)."""
        if self.roles:
            return list(self.roles)
        keys = [self.role or 'user']
        if self.is_admin and 'admin' not in keys:
            keys.append('admin')
        return keys

    def has_role(self, key):
        return key in self.role_keys

    @property
    def role_levels(self):
        from app.options import role_level
        return {role_level(k) for k in self.role_keys}

    def set_roles(self, keys):
        """Assign roles; keeps `role` (highest access level) and `is_admin` in sync."""
        from app.options import role_level, ROLE_LEVELS
        keys = [k for k in dict.fromkeys(keys or []) if k]
        if not keys:
            keys = ['user']
        self.roles = keys
        top = max((role_level(k) for k in keys), key=ROLE_LEVELS.index)
        self.role = top
        self.is_admin = (top == 'admin')
        return keys

    @property
    def is_cs(self):
        """Customer-service staff (or admins) may use the CS console."""
        if self.roles:
            return bool(self.role_levels & {'cs', 'admin'})
        return bool(self.is_admin) or self.role in ('cs', 'admin')

    @property
    def is_influencer(self):
        """Holds the promotion role. Checked by key rather than by level: it is deliberately a
        traveller-level role, so a level test would match every signed-in visitor."""
        return 'influencer' in (self.role_keys or [])

    @property
    def is_traveller(self):
        """Holds a traveller-level role, i.e. may use the public/traveller screens."""
        return 'user' in self.role_levels

    @property
    def needs_email_check(self):
        """Asked to confirm their e-mail (the reminder bar): a sign-up account, not confirmed yet, that signed up
        with a password -- Google / Facebook confirm it already -- and is not staff."""
        return bool(self.signed_up and not self.is_verified and not self.oauth_provider and not self.is_cs)

    @property
    def is_super(self):
        """A Super admin: an Administrator who may also delete for good (services/access.SUPER_ONLY)."""
        return 'superadmin' in self.role_keys

    @property
    def effective_role(self):
        if self.is_admin:
            return 'admin'
        return self.role or 'user'

    def __repr__(self):
        return f'<User {self.username}>'


@db.event.listens_for(User, 'before_insert')
def _user_default_roles(mapper, connection, target):
    if target.roles is None:
        target.roles = target.role_keys


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
    # Per-person travellers when a trip is for more than one person ("one companion for all"):
    # [{who, age_group, gender, needs:[...]}, ...]. The trip-level traveler_* columns keep a
    # summary (union of needs, first traveller's age/gender) so matching is unchanged.
    travellers = db.Column(db.JSON)
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
    # Round trip only: the way home may be a different airline/flight from the outbound.
    return_airline = db.Column(db.String(200))
    return_flight_number = db.Column(db.String(30))
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
    source = db.Column(db.String(20), default='organic', index=True)   # see TRIP_SOURCES
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
    def traveler_age_display(self):
        """Either an exact age ("34") or, for rows saved before the age field became a plain
        number, the old bracket label ("18-30") - never a raw internal key."""
        v = (self.traveler_age_group or '').strip()
        if not v:
            return None
        if v.isdigit():
            return v
        return AGE_GROUP_LABELS.get(v, v)

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
            'travellers': self.travellers or [],
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
            'to_date_flexible': bool(self.to_date_flexible),
            'flying_from_flexible': bool(self.flying_from_flexible),
            'destination_flexible': bool(self.destination_flexible),
            'airline': self.airline,
            'flight_number': self.flight_number,
            'return_airline': self.return_airline,
            'return_flight_number': self.return_flight_number,
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


class TripLeg(db.Model):
    """One flown segment of a post.

    A one-way post has a single leg; a round trip has an outbound and a return; a
    multi-destination post has one leg per hop. Matching runs leg against leg, so a return
    or a middle hop can find a companion of its own instead of being invisible — a post's
    origin/destination columns only ever described its first and last airport.

    These rows are derived from the post and rebuilt by services.legs.sync_legs() whenever
    the route changes; they are never edited directly.
    """
    __tablename__ = 'trip_legs'
    __table_args__ = (
        db.UniqueConstraint('trip_id', 'seq', name='uq_trip_legs_seq'),
        db.Index('ix_trip_legs_route', 'origin_metro', 'dest_metro', 'depart_date'),
    )

    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey('companion_requests.id', ondelete='CASCADE'),
                        nullable=False, index=True)
    seq = db.Column(db.Integer, nullable=False, default=0)
    kind = db.Column(db.String(12), default='leg')        # outbound / return / leg

    origin_text = db.Column(db.String(200))
    origin_iata = db.Column(db.String(5), index=True)
    origin_city = db.Column(db.String(120))
    origin_metro = db.Column(db.String(60), index=True)
    dest_text = db.Column(db.String(200))
    dest_iata = db.Column(db.String(5), index=True)
    dest_city = db.Column(db.String(120))
    dest_metro = db.Column(db.String(60), index=True)

    depart_date = db.Column(db.Date, index=True)
    date_flexible = db.Column(db.Boolean, default=False)
    airline = db.Column(db.String(200))
    flight_number = db.Column(db.String(30))

    trip = db.relationship('CompanionRequest',
                           backref=db.backref('leg_rows', order_by='TripLeg.seq',
                                              cascade='all, delete-orphan', lazy='select'))

    # matching reads legs through the same names it used to read on the post, so the
    # scorers do not need to know which of the two they were handed
    @property
    def from_date(self):
        return self.depart_date

    @property
    def from_date_flexible(self):
        return self.date_flexible

    @property
    def label(self):
        """Short human name for the segment: 'Outbound', 'Return', 'Trip 2 of 3'.

        The model calls these legs, but a traveller reading a multi-stop itinerary thinks
        of each hop as one of their trips, so that is the word the screens use.
        """
        if self.kind == 'outbound':
            return 'Outbound'
        if self.kind == 'return':
            return 'Return'
        total = len(self.trip.leg_rows) if self.trip is not None else 0
        return f'Trip {self.seq + 1} of {total}' if total > 1 else 'Trip'

    @property
    def route_display(self):
        return f"{self.origin_text or self.origin_iata or '?'} → {self.dest_text or self.dest_iata or '?'}"

    @property
    def short_route(self):
        o = self.origin_iata or (self.origin_text or '?')[:3].upper()
        d = self.dest_iata or (self.dest_text or '?')[:3].upper()
        return f'{o} → {d}'

    def to_dict(self):
        return {
            'id': self.id, 'seq': self.seq, 'kind': self.kind, 'label': self.label,
            'origin_text': self.origin_text, 'origin_iata': self.origin_iata,
            'origin_city': self.origin_city,
            'dest_text': self.dest_text, 'dest_iata': self.dest_iata, 'dest_city': self.dest_city,
            'depart_date': self.depart_date.isoformat() if self.depart_date else None,
            'date_flexible': bool(self.date_flexible),
            'airline': self.airline, 'flight_number': self.flight_number,
            'route': self.route_display, 'short_route': self.short_route,
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

    @property
    def display_value(self):
        """The value as a person should read it.

        A phone is spaced so its country code is findable ("+46 764498115", not "+46764498115").
        Only one that carries its + is touched: a legacy row saved as bare national digits has
        no country in it, and prettifying "9175551234" would read its first two digits as India.
        Shown as stored, the not-knowing stays visible. Anything else -- an e-mail, a profile
        link -- is shown exactly as stored. Links (tel:, wa.me) keep using .value.
        """
        from app.services import contacts
        return contacts.display(self.type, self.value)

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
            # what a page should print; `value` stays raw for links and for editing
            d['display'] = self.display_value
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


class UserSession(db.Model):
    """One signed-in browser (services/signin.py): the cookie session holds a random token, this row its hash. A row
    with ended_at set signs that browser out on its next request."""
    __tablename__ = 'user_sessions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    token_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)
    how = db.Column(db.String(20))               # password / google / facebook / remembered / reset / other
    ip = db.Column(db.String(64))
    user_agent = db.Column(db.String(300))
    two_step = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    last_seen_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    ended_at = db.Column(db.DateTime, index=True)
    ended_reason = db.Column(db.String(30))      # signed_out / ended / idle / password / everywhere / deactivated
    ended_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'))

    user = db.relationship('User', foreign_keys=[user_id])
    ended_by = db.relationship('User', foreign_keys=[ended_by_id])

    @property
    def device(self):
        """The browser and system in a few words, from the user agent: "Chrome on Windows"."""
        ua = self.user_agent or ''
        browser = next((n for k, n in (('Edg/', 'Edge'), ('OPR/', 'Opera'), ('Firefox/', 'Firefox'),
                                       ('Chrome/', 'Chrome'), ('Safari/', 'Safari')) if k in ua), 'A browser')
        system = next((n for k, n in (('Android', 'Android'), ('iPhone', 'iPhone'), ('iPad', 'iPad'),
                                      ('Windows', 'Windows'), ('Mac OS', 'Mac'), ('Linux', 'Linux')) if k in ua), '')
        return '%s on %s' % (browser, system) if system else browser


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
    # what Google, shares and the blog list show; empty: the first lines of the post
    summary = db.Column(db.String(300))
    cover_alt = db.Column(db.String(300))          # what the cover shows, for search and screen readers
    # the picture on the blog's list, Read next and More stories (16:9); empty: the cover
    thumb_url = db.Column(db.String(500))
    source_file = db.Column(db.String(255))        # the Word document it was imported from (blog_engine)
    seo_title = db.Column(db.String(300))          # the title Google shows; empty: the title
    focus_keyword = db.Column(db.String(100))      # the words it should be found by (the checks look for them)
    is_featured = db.Column(db.Boolean, default=False, nullable=False, server_default=db.false())
    # where it stands on the public blog: 1 first, 2 next ...; NULL: after those, newest first (Order on the blog)
    sort_order = db.Column(db.Integer, nullable=True, index=True)
    # how the post is laid out: {'width': narrow|normal|wide, 'size': s|m|l, 'spacing': compact|normal|airy}
    layout = db.Column(db.JSON, nullable=True)
    # Published with a published_at still to come: scheduled -- on the site from then (live()).
    is_published = db.Column(db.Boolean, default=False)
    published_at = db.Column(db.DateTime)
    trashed_at = db.Column(db.DateTime)            # in the Trash: off the site until restored
    send_notification = db.Column(db.Boolean, default=True)
    notified_at = db.Column(db.DateTime)           # "went live" was handled (services/blog_posts.went_live)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    author = db.relationship('User', backref='blogs')
    terms = db.relationship('BlogTerm', secondary='blog_post_terms', lazy='selectin',
                            order_by='BlogTerm.name', backref=db.backref('posts', lazy='dynamic'))

    @classmethod
    def live(cls, now=None):
        """The posts readers see: published, their time come, not in the Trash."""
        now = now or datetime.utcnow()
        return cls.query.filter(cls.is_published.is_(True), cls.trashed_at.is_(None),
                                db.or_(cls.published_at.is_(None), cls.published_at <= now))

    @property
    def status(self):
        """trash / scheduled / published / draft -- the one word the screens show."""
        if self.trashed_at:
            return 'trash'
        if self.is_published:
            return 'scheduled' if self.published_at and self.published_at > datetime.utcnow() else 'published'
        return 'draft'

    @property
    def categories(self):
        return [t for t in self.terms if t.kind == 'category']

    @property
    def tags(self):
        return [t for t in self.terms if t.kind == 'tag']

    def reading_minutes(self):
        import re
        words = len(re.sub(r'<[^>]+>', ' ', self.content or '').split())
        return max(1, round(words / 200))

    @property
    def card_picture(self):
        """The picture a card about this post shows: its thumbnail, else its cover (None: neither)."""
        return self.thumb_url or self.cover_image_url or None

    def pictures(self, n=5):
        """[(address, description)]: the thumbnail (else the cover), then the post's own pictures, each once, at most `n` -- the
        pictures a reader swipes through on the blog's list."""
        import re
        from html import unescape
        found = [(self.card_picture, self.cover_alt)]
        for tag in re.findall(r'<img\b[^>]*>', self.content or ''):
            src, alt = re.search(r'\bsrc="([^"]+)"', tag), re.search(r'\balt="([^"]*)"', tag)
            if src:
                found.append((unescape(src.group(1)), unescape(alt.group(1)) if alt else ''))
        out, seen = [], set()
        for src, alt in found:
            key = (src or '').split('?')[0].rstrip('/').rsplit('/', 1)[-1]        # one picture, whatever its address
            if src and key not in seen:
                seen.add(key)
                out.append((src, alt or ''))
            if len(out) >= n:
                break
        return out

    def excerpt(self, length=200):
        if not self.content:
            return ''
        import re
        # The content is HTML; strip tags and collapse whitespace so the card preview reads as
        # plain text instead of leaking "<p>..." into the excerpt.
        text = re.sub(r'<[^>]+>', ' ', self.content)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:length].rstrip() + '...' if len(text) > length else text


blog_post_terms = db.Table(
    'blog_post_terms',
    db.Column('blog_id', db.Integer, db.ForeignKey('blogs.id', ondelete='CASCADE'), primary_key=True),
    db.Column('term_id', db.Integer, db.ForeignKey('blog_terms.id', ondelete='CASCADE'), primary_key=True,
              index=True),
)


class BlogTerm(db.Model):
    """A category or a tag. Categories are the blog's sections (a few, each with its page); tags are
    the many small subjects a post touches. Both have an address: /blog/category/<slug>, /blog/tag/<slug>."""
    __tablename__ = 'blog_terms'
    __table_args__ = (db.UniqueConstraint('kind', 'slug', name='uq_blog_terms_kind_slug'),)
    KINDS = ('category', 'tag')

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(10), nullable=False)
    name = db.Column(db.String(80), nullable=False)
    slug = db.Column(db.String(90), nullable=False)
    description = db.Column(db.String(300))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class BlogRevision(db.Model):
    """One saved version of a post: what it said then, who saved it and why (Draft saved, Published,
    Imported from Word ...). The newest is the post as it is."""
    __tablename__ = 'blog_revisions'

    id = db.Column(db.Integer, primary_key=True)
    blog_id = db.Column(db.Integer, db.ForeignKey('blogs.id', ondelete='CASCADE'), nullable=False, index=True)
    title = db.Column(db.String(300), nullable=False)
    summary = db.Column(db.String(300))
    content = db.Column(db.Text)
    note = db.Column(db.String(120))
    saved_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'))
    saved_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    saved_by = db.relationship('User')
    post = db.relationship('Blog', backref=db.backref('revisions', lazy='dynamic', passive_deletes=True))


class BlogMedia(db.Model):
    """A picture uploaded for the blog -- from the editor, the picture library or a Word document -- so
    the library can offer it again."""
    __tablename__ = 'blog_media'

    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String(500), nullable=False, unique=True)
    name = db.Column(db.String(255))
    width = db.Column(db.Integer)
    height = db.Column(db.Integer)
    bytes = db.Column(db.Integer)
    alt = db.Column(db.String(300))
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    uploaded_by = db.relationship('User')


class BlogPattern(db.Model):
    """A reusable block: blocks saved once, by name, to add to any post (the editor's Add a block › Reusable).
    Synced: each post that uses it holds a copy inside <div class="blog-ref" data-ref="<id>">, and an edit made
    in any of them is copied to all (blog_posts.fresh_refs). Not synced: a starting point, copied into a post
    and changed there."""
    __tablename__ = 'blog_patterns'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    content = db.Column(db.Text, nullable=False, default='')
    synced = db.Column(db.Boolean, nullable=False, default=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    created_by = db.relationship('User')


class BlogSideCard(db.Model):
    """One card in a sidebar beside a blog post (admin Blog › Sidebars, services/blog_sidebars.py): a flyer (a
    picture, maybe a link), an ad (picture, words, a button), a list of links, the post's own headings, more
    stories from its category, or a reusable block. On every post, the posts of some categories, or some posts;
    from `starts_at` until `ends_at` when set. Wide screens show it left or right of the post; phones under it
    (or not at all). `look`: {'theme', 'height' (px; none: as tall as it needs), 'fit' (whole|fill), 'phone'
    (below|hide), 'count' (more stories)}."""
    __tablename__ = 'blog_side_cards'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)                 # for the staff list; readers never see it
    kind = db.Column(db.String(16), nullable=False)                  # blog_sidebars.KINDS
    side = db.Column(db.String(8), nullable=False, default='right', server_default='right')
    sort_order = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    is_on = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())
    title = db.Column(db.String(120))
    body = db.Column(db.String(600))
    image_url = db.Column(db.String(500))
    image_alt = db.Column(db.String(300))
    link_url = db.Column(db.String(500))
    link_label = db.Column(db.String(60))
    new_tab = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    links = db.Column(db.JSON)                                       # [{'label', 'url'}] for a list of links
    pattern_id = db.Column(db.Integer, db.ForeignKey('blog_patterns.id', ondelete='SET NULL'))
    look = db.Column(db.JSON)
    show_on = db.Column(db.String(8), nullable=False, default='all', server_default='all')   # all | cats | posts
    term_ids = db.Column(db.JSON)                                    # the categories, when show_on == 'cats'
    post_ids = db.Column(db.JSON)                                    # the posts, when show_on == 'posts'
    starts_at = db.Column(db.DateTime)
    ends_at = db.Column(db.DateTime)
    clicks = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    pattern = db.relationship('BlogPattern')
    created_by = db.relationship('User')


# Which product a review is about. The same three the help centre and the admin panel use, and
# the same idea as ContactMessage.topic -- one queue, one column saying what it is about.
REVIEW_SITES = ('companion', 'insurance', 'sahayak')
REVIEW_SITE_LABELS = {'companion': 'Travel companion', 'insurance': 'Travel insurance',
                      'sahayak': 'Sahayak'}


class StaffRead(db.Model):
    """One member of staff has opened one row of one staff list.

    Per person, not per row: an agent who joins today has read nothing, whatever colleagues have
    opened, and one agent reading an enquiry must not take it off another's count. Rows never
    change once written; the first opening is the one recorded.
    """
    __tablename__ = 'staff_reads'
    __table_args__ = (db.UniqueConstraint('user_id', 'kind', 'item_id', name='uq_staff_reads'),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'),
                        nullable=False, index=True)
    kind = db.Column(db.String(10), nullable=False)       # ReadMark.READ_KIND of the row's model
    item_id = db.Column(db.Integer, nullable=False)
    read_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


def request_cache(name):
    """A dict that lives exactly as long as the current request -- on the request itself, not on
    `g`, which belongs to the app context and can outlive a request (it does under the test
    client). Outside a request, a fresh dict each time: nothing is cached."""
    from flask import has_request_context, request
    if not has_request_context():
        return {}
    return request.environ.setdefault('app.cache.' + name, {})


def _read_ids(user, kind):
    """The ids of `kind` this person has opened. Once per request: a table of fifty rows asks
    fifty times."""
    cache = request_cache('staff_reads')
    key = (user.id, kind)
    if key not in cache:
        cache[key] = {r.item_id for r in StaffRead.query.filter_by(user_id=user.id, kind=kind)}
    return cache[key]


class ReadMark:
    """Whether the person looking has opened this row yet -- the numbers on the staff menus.

    Status says whether somebody has *acted*; this says whether *you* have *looked*. They are
    different questions: a badge that only drops when the work is finished never moves while you
    read down the list. And it is personal (StaffRead): what a colleague opened is still new to
    you, so a new agent starts with every open item unread.

    Settled work is never unread, for anybody: a closed enquiry, a resolved report, an approved
    review, a match that has left the queue. Otherwise an agent who joins next year starts with
    the whole history lit up, and a badge of four hundred is a badge nobody reads.
    """
    READ_KIND = None

    @classmethod
    def settled(cls):
        """A filter: rows whose work is finished. Each model says what that means for it."""
        return db.false()

    def is_settled(self):
        return False

    @classmethod
    def unread_by(cls, user):
        """A filter: open rows `user` has not opened. Every open one, for nobody signed in."""
        open_rows = ~cls.settled()
        if not getattr(user, 'is_authenticated', False):
            return open_rows
        return db.and_(open_rows, ~db.session.query(StaffRead.id).filter(
            StaffRead.user_id == user.id, StaffRead.kind == cls.READ_KIND,
            StaffRead.item_id == cls.id).exists())

    @property
    def is_unread(self):
        """For the person signed in -- this is what templates ask."""
        from flask_login import current_user
        if not getattr(current_user, 'is_authenticated', False) or self.is_settled():
            return False
        return self.id not in _read_ids(current_user, self.READ_KIND)

    def mark_read(self, by=None):
        """Record that `by` opened this. Returns True if it was new to them."""
        if not getattr(by, 'id', None) or self.id is None:
            return False
        ids = _read_ids(by, self.READ_KIND)
        if self.id in ids:
            return False
        ids.add(self.id)
        # In a savepoint: clicking a status button on an unread row sends the row's "read" and
        # the form at the same moment, and whichever lands second must not fail the request over
        # a mark the first one has just written.
        from sqlalchemy.exc import IntegrityError
        try:
            with db.session.begin_nested():
                db.session.add(StaffRead(user_id=by.id, kind=self.READ_KIND, item_id=self.id))
        except IntegrityError:
            return False
        return True



class Feedback(ReadMark, db.Model):
    """A review left by a signed-in traveller, published once an admin approves it.

    `site` is where it was written, and therefore where it appears. Nothing decides that for the
    reviewer: a review about travel insurance is worth reading on the insurance page and tells
    somebody looking for a flight companion nothing at all.
    """
    __tablename__ = 'feedbacks'

    READ_KIND = 'feedback'

    @classmethod
    def settled(cls):
        return cls.is_approved.is_(True)          # decided: it is live on the site

    def is_settled(self):
        return bool(self.is_approved)
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)  # 1-5
    comment = db.Column(db.Text)
    site = db.Column(db.String(20), default='companion', nullable=False, index=True)
    is_approved = db.Column(db.Boolean, default=False)
    is_featured = db.Column(db.Boolean, default=False)   # hand-picked for the public home page
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def site_label(self):
        return REVIEW_SITE_LABELS.get(self.site or 'companion', self.site)


CONTACT_STATUSES = ('new', 'in_progress', 'closed')
CONTACT_STATUS_LABELS = {'new': 'New', 'in_progress': 'In progress', 'closed': 'Closed'}
# Which service the enquiry is about. One inbox, so CS never has to check two screens; the
# topic is what lets them filter and see at a glance what they are answering.
CONTACT_TOPICS = ('companion', 'insurance', 'sahayak', 'general')
CONTACT_TOPIC_LABELS = {'companion': 'Travel companion', 'insurance': 'Travel insurance',
                        'sahayak': 'Sahayak', 'general': 'General enquiry'}


class ContactMessage(ReadMark, db.Model):
    """A "Contact us" enquiry from the public form. Visible to CS and admins.

    user_id is nullable because the form deliberately works signed-out — someone who cannot
    log in is exactly the person most likely to need it.
    """
    __tablename__ = 'contact_messages'

    READ_KIND = 'contact'

    @classmethod
    def settled(cls):
        return cls.status == 'closed'             # 'in_progress' is still open work

    def is_settled(self):
        return self.status == 'closed'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), nullable=False, index=True)
    phone = db.Column(db.String(30))
    message = db.Column(db.Text, nullable=False)
    topic = db.Column(db.String(20), default='companion', nullable=False, index=True)
    status = db.Column(db.String(15), default='new', index=True)
    handled_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    handled_at = db.Column(db.DateTime)
    cs_notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    user = db.relationship('User', foreign_keys=[user_id])
    handled_by = db.relationship('User', foreign_keys=[handled_by_id])

    def set_status(self, status, by=None):
        assert status in CONTACT_STATUSES, status
        self.status = status
        if status == 'new':
            self.handled_by_id, self.handled_at = None, None
        else:
            self.handled_by_id = by.id if by else None
            self.handled_at = datetime.utcnow()
            self.mark_read(by=by)        # nobody moves an enquiry on without having read it

    def to_dict(self):
        return {
            'id': self.id, 'name': self.name, 'email': self.email, 'phone': self.phone,
            'message': self.message, 'status': self.status, 'topic': self.topic,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class ContactReply(db.Model):
    """What we wrote back, kept beside the enquiry it answers.

    Reply used to be a mailto: link, so the answer lived in whoever clicked it's own mailbox and
    the console showed an enquiry with nothing beside it. `delivered` records whether the mail
    provider took it -- a reply that failed to send is still worth showing, and worth being able
    to see failed.
    """
    __tablename__ = 'contact_replies'

    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('contact_messages.id', ondelete='CASCADE'),
                           nullable=False, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    body = db.Column(db.Text, nullable=False)
    delivered = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    message = db.relationship('ContactMessage',
                              backref=db.backref('replies', lazy='selectin',
                                                 cascade='all, delete-orphan',
                                                 order_by='ContactReply.created_at'))
    author = db.relationship('User', foreign_keys=[author_id])


class InsuranceQuote(db.Model):
    """A travel-insurance quote request from the public form.

    The pricing itself happens on the partner's side, so this is the only record we keep of
    who asked for what: a lead CS can follow up on when someone quotes but never buys.
    user_id is nullable because the form works signed-out, like ContactMessage.
    """
    __tablename__ = 'insurance_quotes'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    name = db.Column(db.String(120))   # legacy: the form no longer asks for one; email is the lead
    email = db.Column(db.String(255), nullable=False, index=True)
    phone = db.Column(db.String(30))
    insurance_type = db.Column(db.String(20), nullable=False, index=True)
    citizenship = db.Column(db.String(3), nullable=False)
    destination = db.Column(db.String(3))   # Travel Medical only; the other two imply their region
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    # [{"age": "65"}, ...] — one entry per traveller. The partner prices on age alone.
    travellers = db.Column(db.JSON, nullable=False, default=list)
    status = db.Column(db.String(15), default='quoted', index=True)
    quote_url = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    user = db.relationship('User', foreign_keys=[user_id])

    @property
    def age_list(self):
        return [str(t.get('age', '')) for t in (self.travellers or [])]

    @property
    def traveller_count(self):
        return len(self.travellers or [])

    def to_dict(self):
        return {
            'id': self.id, 'name': self.name, 'email': self.email, 'phone': self.phone,
            'insurance_type': self.insurance_type, 'citizenship': self.citizenship,
            'destination': self.destination,
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'travellers': self.travellers or [], 'status': self.status, 'quote_url': self.quote_url,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


SAHAYAK_STATUSES = ('new', 'assigned', 'completed', 'cancelled')
SAHAYAK_STATUS_LABELS = {'new': 'New request', 'assigned': 'Assigned',
                         'completed': 'Completed', 'cancelled': 'Cancelled'}
SAHAYAK_WHEN = ('asap', 'scheduled')
SAHAYAK_WHEN_LABELS = {'asap': 'As soon as possible', 'scheduled': 'At a chosen time'}


class SahayakBooking(db.Model):
    """A request for a Sahayak home healthcare visit.

    This is a request, not a dispatch: there is no Sahayak-facing app and no automated matching
    in this phase, so a booking sits in the CS queue until an agent assigns somebody and records
    how it went. `assigned_to_name` is free text for that reason -- the people doing the visits
    are not users of this system yet, and giving them accounts would pretend otherwise.

    No payment is taken here. `quoted_price` is what the catalogue said when the request was
    made, kept as a record of what the person was shown rather than as a charge.
    """
    __tablename__ = 'sahayak_bookings'

    id = db.Column(db.Integer, primary_key=True)
    # nullable: somebody booking care for a parent may not have an account, and requiring one
    # would turn away exactly the person who needs this most
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)

    service_key = db.Column(db.String(40), nullable=False, index=True)
    service_name = db.Column(db.String(80), nullable=False)   # as shown, in case prices change
    quoted_price = db.Column(db.String(12))

    # who the visit is for -- often not the person booking it
    patient_name = db.Column(db.String(120), nullable=False)
    patient_age = db.Column(db.Integer)
    contact_name = db.Column(db.String(120))
    phone = db.Column(db.String(30), nullable=False)
    email = db.Column(db.String(255), index=True)

    address = db.Column(db.Text, nullable=False)
    landmark = db.Column(db.String(200))
    pincode = db.Column(db.String(12), index=True)
    access_notes = db.Column(db.String(300))      # "ring twice", "gate code 4821"

    when_type = db.Column(db.String(12), default='asap', nullable=False)
    scheduled_for = db.Column(db.DateTime)        # only when when_type == 'scheduled'
    notes = db.Column(db.Text)                    # what the person told us about the need

    status = db.Column(db.String(15), default='new', nullable=False, index=True)
    assigned_to_name = db.Column(db.String(120))  # the Sahayak, by name
    assigned_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    assigned_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    cancelled_reason = db.Column(db.String(200))
    cs_notes = db.Column(db.Text)                 # internal, never shown to the patient

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', foreign_keys=[user_id])
    assigned_by = db.relationship('User', foreign_keys=[assigned_by_id])

    def set_status(self, status, by=None, reason=None):
        assert status in SAHAYAK_STATUSES, status
        self.status = status
        if status == 'assigned':
            self.assigned_by_id = by.id if by else None
            self.assigned_at = datetime.utcnow()
        elif status == 'completed':
            self.completed_at = datetime.utcnow()
        elif status == 'cancelled':
            self.cancelled_reason = (reason or '')[:200] or None

    @property
    def when_display(self):
        if self.when_type == 'scheduled' and self.scheduled_for:
            return self.scheduled_for.strftime('%d %b %Y, %H:%M')
        return 'As soon as possible'

    def to_dict(self):
        return {
            'id': self.id, 'service': self.service_name, 'patient': self.patient_name,
            'phone': self.phone, 'status': self.status, 'when': self.when_display,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


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


class Match(ReadMark, db.Model):
    """A scored pairing of two posts on one specific leg each.

    trip_a_id < trip_b_id so a pair is stored once, and leg_a/leg_b say which segment of
    each post actually lines up. Two posts can therefore match more than once — a pair of
    round trips that share both the outbound and the return is two matches, not one, and
    each is introduced on its own.
    """
    __tablename__ = 'matches'
    __table_args__ = (db.UniqueConstraint('trip_a_id', 'trip_b_id', 'leg_a_id', 'leg_b_id',
                                          name='uq_matches_pair'),)

    READ_KIND = 'match'

    @classmethod
    def settled(cls):
        # out of the CS queue: nobody needs to act on it
        return db.or_(cls.needs_cs_attention.isnot(True), cls.status == 'dismissed')

    def is_settled(self):
        return not self.needs_cs_attention or self.status == 'dismissed'
    id = db.Column(db.Integer, primary_key=True)
    trip_a_id = db.Column(db.Integer, db.ForeignKey('companion_requests.id'), nullable=False, index=True)
    trip_b_id = db.Column(db.Integer, db.ForeignKey('companion_requests.id'), nullable=False, index=True)
    leg_a_id = db.Column(db.Integer, db.ForeignKey('trip_legs.id', ondelete='CASCADE'), index=True)
    leg_b_id = db.Column(db.Integer, db.ForeignKey('trip_legs.id', ondelete='CASCADE'), index=True)
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
    leg_a = db.relationship('TripLeg', foreign_keys=[leg_a_id])
    leg_b = db.relationship('TripLeg', foreign_keys=[leg_b_id])
    parties = db.relationship('MatchParty', backref='match', lazy='select', cascade='all, delete-orphan')

    @staticmethod
    def ordered_ids(x, y):
        return (x, y) if x < y else (y, x)

    def other_trip(self, trip_id):
        return self.trip_b if trip_id == self.trip_a_id else self.trip_a

    def leg_for(self, trip_id):
        """The leg of `trip_id` that this match is about (None on pre-leg rows)."""
        return self.leg_a if trip_id == self.trip_a_id else self.leg_b

    def other_leg(self, trip_id):
        return self.leg_b if trip_id == self.trip_a_id else self.leg_a

    def party_for(self, trip_id):
        return next((p for p in self.parties if p.trip_id == trip_id), None)

    def waiting_trips(self):
        """The side(s) of this match a person has to move along -- the post the CS match queue
        files it under. Both, if both are stuck; trip_a if neither is, so it is never lost."""
        waiting = [t for t in (self.trip_a, self.trip_b)
                   if (self.party_for(t.id) is None or self.party_for(t.id).status == 'pending')]
        return waiting or [self.trip_a]

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
        if for_trip_id:
            mine_leg, their_leg = self.leg_for(for_trip_id), self.other_leg(for_trip_id)
            d['my_leg'] = mine_leg.to_dict() if mine_leg else None
            d['their_leg'] = their_leg.to_dict() if their_leg else None
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


REPORT_STATUSES = ('open', 'resolved')


class MatchReport(ReadMark, db.Model):
    """A problem a traveller flagged about a match from the /match/<token> contact page.

    Reports used to leave only an ActivityEvent + the match's needs_cs_attention flag, so the
    reason text was not browsable. This row makes them a first-class CS item: listed in the
    console (User Voices → Reports), counted in the queue, and resolvable.
    """
    __tablename__ = 'match_reports'

    READ_KIND = 'report'

    @classmethod
    def settled(cls):
        return cls.status == 'resolved'

    def is_settled(self):
        return self.status == 'resolved'
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('matches.id', ondelete='CASCADE'), index=True)
    party_id = db.Column(db.Integer, db.ForeignKey('match_parties.id', ondelete='SET NULL'), nullable=True)
    trip_id = db.Column(db.Integer, db.ForeignKey('companion_requests.id'), nullable=True)   # the reporter's post
    reporter_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)            # null if reported logged-out
    reason = db.Column(db.Text)
    status = db.Column(db.String(20), default='open', index=True)   # open / resolved
    cs_notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    resolved_at = db.Column(db.DateTime, nullable=True)
    resolved_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    match = db.relationship('Match', foreign_keys=[match_id])
    trip = db.relationship('CompanionRequest', foreign_keys=[trip_id])
    reporter = db.relationship('User', foreign_keys=[reporter_id])
    resolved_by = db.relationship('User', foreign_keys=[resolved_by_id])

    def resolve(self, by=None):
        self.status = 'resolved'
        self.resolved_at = datetime.utcnow()
        self.resolved_by_id = by.id if by else None

    def reopen(self):
        self.status = 'open'
        self.resolved_at = None
        self.resolved_by_id = None


# ---------------------------------------------------------------------------
# Site-wide settings (key/value JSON) — used for the notification switches
# ---------------------------------------------------------------------------

class Airport(db.Model):
    """Airport reference data: seeded from the bundled list by migration; admins add rows at /admin/options."""
    __tablename__ = 'airports'

    id = db.Column(db.Integer, primary_key=True)
    iata = db.Column(db.String(5), unique=True, nullable=False, index=True)
    name = db.Column(db.String(150), nullable=False)
    city = db.Column(db.String(100), index=True)
    country = db.Column(db.String(80))
    is_custom = db.Column(db.Boolean, default=False, nullable=False)   # added by an admin (deletable)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def as_dict(self):
        return {'iata': self.iata, 'name': self.name, 'city': self.city, 'country': self.country,
                'custom': self.is_custom, 'id': self.id}


class Airline(db.Model):
    """Airline reference data: seeded from the bundled list by migration; admins add rows at /admin/options."""
    __tablename__ = 'airlines'

    id = db.Column(db.Integer, primary_key=True)
    iata = db.Column(db.String(5), unique=True, nullable=False, index=True)
    name = db.Column(db.String(150), nullable=False)
    country = db.Column(db.String(80))
    is_custom = db.Column(db.Boolean, default=False, nullable=False)   # added by an admin (deletable)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def as_dict(self):
        return {'iata': self.iata, 'name': self.name, 'country': self.country,
                'custom': self.is_custom, 'id': self.id}


NOTIFY_CATEGORIES = ('match_alerts', 'match_intro', 'connection', 'chat', 'announcements', 'cs', 'account')
NOTIFY_CATEGORY_LABELS = {
    'match_alerts': 'New possible companion alerts (heads-up when a matching trip appears)',
    'match_intro': 'Match introductions (contact-page links after "notify both" / "share my contact")',
    'connection': 'Connection requests, accept / decline, trip changed or cancelled',
    'chat': 'New chat messages',
    'announcements': 'Blog posts and admin broadcasts',
    'cs': 'Customer-service alerts (escalations, claimed posts, reports)',
    'account': 'Account e-mails (e-mail verification, password reset)',
}
USER_PREF_CATEGORIES = ('match_alerts', 'match_intro', 'connection', 'chat', 'announcements')


class AppSetting(db.Model):
    __tablename__ = 'app_settings'

    key = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.JSON)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    updated_by = db.relationship('User', foreign_keys=[updated_by_id])


# ---------------------------------------------------------------------------
# Phase 3: admin web scraping (recipes, runs, rows) — see app/services/scraper*.py
# ---------------------------------------------------------------------------

SCRAPE_MODES = ('recipe', 'source')
SCRAPE_RUN_KINDS = ('detect', 'preview', 'teach', 'run')
SCRAPE_RUN_STATUSES = ('queued', 'running', 'done', 'failed', 'cancelled')
SCRAPE_ROW_STATUSES = ('new', 'duplicate', 'imported', 'skipped')
SCRAPE_META_COLUMNS = ('_page', '_url', '_fetched_at', '_key')


class ScrapeRecipe(db.Model):
    """A taught fetchall recipe (mode='recipe') or a detected data source (mode='source') for one site."""
    __tablename__ = 'scrape_recipes'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    site = db.Column(db.String(200))
    start_url = db.Column(db.String(500), nullable=False)
    mode = db.Column(db.String(10), default='recipe')      # recipe | source
    recipe_json = db.Column(db.JSON)                        # fetchall recipe dict (mode='recipe')
    source_json = db.Column(db.JSON)                        # {source, kind, page_url, columns} (mode='source')
    field_mapping = db.Column(db.JSON)                      # {scraped_column: importer canonical column | 'ignore'}
    default_source = db.Column(db.String(20), default='website')   # website | facebook
    session_key = db.Column(db.String(300))                 # storage-state file name in SCRAPER_SESSION_DIR
    schedule_enabled = db.Column(db.Boolean, default=False)
    schedule_every_hours = db.Column(db.Integer, default=24)
    is_active = db.Column(db.Boolean, default=True)
    last_run_at = db.Column(db.DateTime)
    last_status = db.Column(db.String(15))
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    created_by = db.relationship('User', foreign_keys=[created_by_id])
    runs = db.relationship('ScrapeRun', backref='recipe', lazy='dynamic', cascade='all, delete-orphan',
                           order_by='ScrapeRun.created_at.desc()')
    rows = db.relationship('ScrapeRow', backref='recipe', lazy='dynamic', cascade='all, delete-orphan')

    @property
    def columns(self):
        """Column names a run of this recipe produces (scraped fields + fetchall meta columns)."""
        if self.mode == 'source':
            cols = list((self.source_json or {}).get('columns') or [])
        else:
            r = self.recipe_json or {}
            cols = list((r.get('fields') or {}).keys())
            cols += [c for c in ((r.get('detail') or {}).get('fields') or {}) if c not in cols]
        return cols + [m for m in SCRAPE_META_COLUMNS if m not in cols]

    @property
    def active_run(self):
        return self.runs.filter(ScrapeRun.status.in_(['queued', 'running'])).first()

    def to_dict(self):
        return {
            'id': self.id, 'name': self.name, 'site': self.site, 'start_url': self.start_url, 'mode': self.mode,
            'default_source': self.default_source, 'is_active': self.is_active,
            'schedule_enabled': self.schedule_enabled, 'schedule_every_hours': self.schedule_every_hours,
            'last_run_at': self.last_run_at.isoformat() if self.last_run_at else None,
            'last_status': self.last_status, 'columns': self.columns, 'field_mapping': self.field_mapping or {},
        }


class ScrapeRun(db.Model):
    """One background job: detect data sources, preview a recipe, teach, or a full run."""
    __tablename__ = 'scrape_runs'
    __table_args__ = (
        # at most one queued/running run per recipe, enforced by the database (works across processes)
        db.Index('uq_scrape_runs_active', 'recipe_id', unique=True,
                 sqlite_where=db.text("status IN ('queued','running')"),
                 postgresql_where=db.text("status IN ('queued','running')")),
    )

    id = db.Column(db.Integer, primary_key=True)
    recipe_id = db.Column(db.Integer, db.ForeignKey('scrape_recipes.id'), nullable=True, index=True)
    kind = db.Column(db.String(10), nullable=False)          # detect | preview | teach | run
    status = db.Column(db.String(15), default='queued', index=True)
    trigger = db.Column(db.String(10), default='manual')     # manual | cli | scheduled
    options = db.Column(db.JSON)       # {url, wait, recipe, incremental, max_pages, max_rows, session_key}
    result = db.Column(db.JSON)        # detect: candidates · preview: {columns, rows, stats, report} · teach: {recipe}
    stats = db.Column(db.JSON)         # run: RunStats fields + blank_ratios + report + columns
    log = db.Column(db.Text)           # last ~300 progress lines
    progress_pages = db.Column(db.Integer, default=0)
    progress_items = db.Column(db.Integer, default=0)
    rows_total = db.Column(db.Integer, default=0)
    rows_new = db.Column(db.Integer, default=0)
    rows_duplicate = db.Column(db.Integer, default=0)
    cancel_requested = db.Column(db.Boolean, default=False)
    error = db.Column(db.Text)
    worker_id = db.Column(db.String(64))
    heartbeat_at = db.Column(db.DateTime)
    started_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    started_at = db.Column(db.DateTime)
    finished_at = db.Column(db.DateTime)

    started_by = db.relationship('User', foreign_keys=[started_by_id])
    rows = db.relationship('ScrapeRow', backref='run', lazy='dynamic')

    @property
    def done(self):
        return self.status in ('done', 'failed', 'cancelled')

    @property
    def duration_seconds(self):
        if not self.started_at:
            return None
        end = self.finished_at or datetime.utcnow()
        return int((end - self.started_at).total_seconds())

    @property
    def report(self):
        return ((self.stats or {}).get('report') or (self.result or {}).get('report') or {})

    def log_tail(self, n=40):
        return (self.log or '').splitlines()[-n:]

    def to_dict(self):
        return {
            'id': self.id, 'recipe_id': self.recipe_id, 'kind': self.kind, 'status': self.status, 'done': self.done,
            'trigger': self.trigger, 'options': self.options or {},
            'progress': {'pages': self.progress_pages or 0, 'items': self.progress_items or 0,
                         'rows_new': self.rows_new or 0, 'rows_total': self.rows_total or 0,
                         'rows_duplicate': self.rows_duplicate or 0},
            'log_tail': self.log_tail(), 'stats': self.stats, 'result': self.result, 'error': self.error,
            'cancel_requested': self.cancel_requested, 'duration_seconds': self.duration_seconds,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'finished_at': self.finished_at.isoformat() if self.finished_at else None,
        }


class ScrapeRow(db.Model):
    """One scraped item. Unique per recipe by fetchall's `_key`, so re-runs never duplicate rows."""
    __tablename__ = 'scrape_rows'
    __table_args__ = (db.UniqueConstraint('recipe_id', 'key', name='uq_scrape_rows_recipe_key'),)

    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(db.Integer, db.ForeignKey('scrape_runs.id'), nullable=False, index=True)
    recipe_id = db.Column(db.Integer, db.ForeignKey('scrape_recipes.id'), nullable=False, index=True)
    row_index = db.Column(db.Integer)
    key = db.Column(db.String(64), nullable=False, index=True)
    data = db.Column(db.JSON)                     # raw scraped row incl. _page/_url/_fetched_at/_key
    page_url = db.Column(db.String(500))
    status = db.Column(db.String(15), default='new', index=True)   # new | duplicate | imported | skipped
    duplicate_of_id = db.Column(db.Integer, db.ForeignKey('companion_requests.id'), nullable=True)
    imported_post_id = db.Column(db.Integer, db.ForeignKey('companion_requests.id'), nullable=True)
    imported_at = db.Column(db.DateTime)
    imported_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    imported_post = db.relationship('CompanionRequest', foreign_keys=[imported_post_id])
    duplicate_of = db.relationship('CompanionRequest', foreign_keys=[duplicate_of_id])
    imported_by = db.relationship('User', foreign_keys=[imported_by_id])

    def to_dict(self):
        return {
            'id': self.id, 'run_id': self.run_id, 'recipe_id': self.recipe_id, 'row_index': self.row_index,
            'key': self.key, 'data': self.data or {}, 'page_url': self.page_url, 'status': self.status,
            'duplicate_of_id': self.duplicate_of_id, 'imported_post_id': self.imported_post_id,
            'imported_at': self.imported_at.isoformat() if self.imported_at else None,
        }


class SavedFilter(db.Model):
    """A set of filters an agent named and kept, so a daily view is one click instead of twelve.

    The point is that it keeps working tomorrow. What is stored is the filter PARAMS, not the rows
    and not resolved dates -- "departing today" is saved as dep=today and worked out against the
    day it is opened (see services/post_filters.preset_range). An agent who saves "today, from
    Delhi" on Monday sees Tuesday's Delhi departures on Tuesday without touching it.

    Both post listings read the same filter engine, so a saved filter is not tied to one of them;
    it shows on the CS console and the admin listings alike.

    Sharing is opt-in and one-way: a filter belongs to the person who made it, and marking it
    shared puts it on their colleagues' listings read-only. Only the owner can rename, change or
    delete it, so nobody's daily shortcut can disappear because somebody else tidied up.
    """
    __tablename__ = 'saved_filters'

    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    name = db.Column(db.String(60), nullable=False)

    # The filter engine's own params, e.g. {"dep": "today", "from_place": "DEL"}. Stored as given
    # so that adding a filter to post_filters.GROUPS needs no migration here.
    params = db.Column(db.JSON, nullable=False, default=dict)
    sort = db.Column(db.String(20))

    shared = db.Column(db.Boolean, nullable=False, default=False)
    # the one team it is shared with, the owner's (services/team_share.py); shared is true while it is set
    team_id = db.Column(db.Integer, db.ForeignKey('workspace_teams.id', ondelete='SET NULL'), nullable=True, index=True)
    # what the owner dragged it to; ties broken by name so the order is never arbitrary
    position = db.Column(db.Integer, nullable=False, default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # for "recently used" ordering and for spotting shortcuts nobody opens any more
    last_used_at = db.Column(db.DateTime)
    use_count = db.Column(db.Integer, nullable=False, default=0)

    owner = db.relationship('User', foreign_keys=[owner_id])
    team = db.relationship('WorkspaceTeam', foreign_keys=[team_id])

    __table_args__ = (
        db.UniqueConstraint('owner_id', 'name', name='uq_saved_filter_owner_name'),
        db.Index('ix_saved_filters_shared', 'shared'),
    )

    def __repr__(self):
        return '<SavedFilter %r of user %s>' % (self.name, self.owner_id)


@db.event.listens_for(db.session, 'before_flush')
def _back_in_the_queue_is_new_again(session, flush_context, instances):
    """A match that comes back into the CS queue, or a report that is reopened, is new again for
    everybody -- including whoever opened it the first time. Otherwise an escalation lands on a
    post the agent read last week and no badge ever says so.

    Watched here rather than at each place that sets the flag: there are half a dozen (the bridge,
    the escalation job, reports, the CLI), and the next one would be forgotten.
    """
    back = {'match': set(), 'report': set()}
    for obj in session.dirty:
        if isinstance(obj, Match) and obj.id is not None:
            hist = db.inspect(obj).attrs.needs_cs_attention.history
            if hist.added and hist.added[0] and not any(hist.deleted):
                back['match'].add(obj.id)
        elif isinstance(obj, MatchReport) and obj.id is not None:
            hist = db.inspect(obj).attrs.status.history
            if hist.added and hist.added[0] == 'open' and 'open' not in hist.deleted:
                back['report'].add(obj.id)
    for kind, ids in back.items():
        if ids:
            # core, not the ORM: a query here would try to flush the flush it is part of
            session.connection().execute(StaffRead.__table__.delete().where(
                StaffRead.kind == kind, StaffRead.item_id.in_(ids)))
            # and out of this request's copy of who has read what (_read_ids)
            for (_, k), seen in request_cache('staff_reads').items():
                if k == kind:
                    seen.difference_update(ids)


# ---------------------------------------------------------------------------
# Sales CRM (services/crm.py): one record per person, one lead per product they ask about,
# configured by lead sources and pipelines an admin edits on screen rather than in code.
# ---------------------------------------------------------------------------

# Seed data only since U5: products live in crm_products (services/crm_products.py reads them).
CRM_PRODUCTS = ('TC', 'TI', 'SH', 'GH', 'VC', 'GEN')
CRM_PRODUCT_LABELS = {'TC': 'Travel Companion', 'TI': 'Travel Insurance', 'SH': 'Sahayak',
                      'GH': 'Gift Health', 'VC': 'Virtual Consultation', 'GEN': 'General'}
CRM_SOURCE_KINDS = ('form', 'popup', 'chat', 'call', 'ads', 'import', 'manual', 'api')
CRM_SOURCE_KIND_LABELS = {'form': 'Landing-page form', 'popup': 'Pop-up', 'chat': 'Chat / messaging', 'call': 'Phone call',
                          'ads': 'Ad lead form', 'import': 'Import', 'manual': 'Added by staff',
                          'api': 'Partner site (API)'}
# live: leads start their pipeline and get their first message. paused: leads are kept, nothing
# is sent. unrouted: a page nobody has set up yet -- kept, waiting for an admin to choose.
CRM_SOURCE_STATUSES = ('live', 'paused', 'unrouted')
CRM_STAGE_KINDS = ('open', 'won', 'lost')
# "This stage means": decides open / won / lost (kind) and the funnel role
CRM_STAGE_MEANS = ('new', 'talking', 'quoted', 'won', 'lost')
CRM_MEANS_LABELS = {'new': 'Still new (no reply yet)', 'talking': 'Talking', 'quoted': 'Quoted',
                    'won': 'Won (customer)', 'lost': 'Lost'}
MEANS_ROLE = {'new': 'cold', 'talking': 'prospect', 'quoted': 'pipeline', 'won': 'customer', 'lost': 'lost'}
ROLE_MEANS = {v: k for k, v in MEANS_ROLE.items()}
CRM_TEMPERATURES = {'L': 'Loyal', 'R': 'Responsive', 'U': 'Unresponsive', 'Z': 'Zombie',
                    'DL': 'Dead lead', 'EL': 'Expired lead'}
CRM_VIA = ('person', 'auto', 'automation', 'flow', 'ai', 'broadcast', 'import')
# wa_other: they wrote from another WhatsApp number -- their reply, but it never opens the 24-hour clock
CRM_CHANNELS = ('whatsapp', 'call', 'email', 'sms', 'instagram', 'facebook', 'telegram', 'chat',
                'note', 'form', 'system', 'wa_other')
CRM_CHANNEL_LABELS = {'whatsapp': 'WhatsApp', 'call': 'Call', 'email': 'E-mail', 'sms': 'SMS',
                      'instagram': 'Instagram', 'facebook': 'Facebook', 'telegram': 'Telegram',
                      'chat': 'Chat', 'note': 'Note', 'form': 'Form', 'system': 'System',
                      'wa_other': 'WhatsApp (other number)', 'todo': 'To-do'}
# the read-only "Replies" line: what the temperature codes mean, in plain words
CRM_REPLIES = {'L': 'Comes back', 'R': 'Replied', 'U': 'Not replying', 'Z': 'Stopped replying',
               'DL': 'Wrong number', 'EL': 'Cover ended'}
CRM_CALL_OUTCOMES = {'connected': 'Talked', 'no_answer': 'No answer', 'busy': 'Busy',
                     'call_back': 'Asked us to call back', 'wrong_number': 'Wrong number',
                     'switched_off': 'Switched off'}
# when a step is due: hours after the previous one, days before the trip leaves, or days before
# the policy ends (the sales sheet's ER -- expiration reminder)
CRM_STEP_TRIGGERS = ('after_hours', 'date_offset')
# before U5 (kept readable: old rows in flight, tests): days before the trip / before the cover ends
CRM_LEGACY_TRIGGERS = {'before_departure_days': 'departure_date', 'before_end_days': 'ends_on'}
CRM_STEP_CHANNELS = {'whatsapp': 'WhatsApp message', 'call': 'Call', 'email': 'E-mail', 'todo': 'To-do'}
CRM_STEP_KINDS = {'first': 'First contact', 'reminder': 'Reminder', 'care': 'Customer care',
                  'birthday': 'Birthday', 'festival': 'Festival', 'promotion': 'Promotion',
                  'expiry': 'Expiry', 'after_lost': 'After losing', 'other': 'Other'}
CRM_TAG_MODES = ('product', 'own')
CRM_FIELD_TYPES = ('text', 'number', 'date', 'choice', 'yesno')
CRM_DATE_FIELDS = {'departure_date': 'Travels on', 'ends_on': 'Cover ends'}     # the two built-in dates (columns)
# Ways to reach somebody who gave no phone or e-mail. instagram / facebook are a handle or profile
# link typed by staff; ig_id / fb_psid are the ids Meta's webhooks send, which are what a reply
# through the Graph API is addressed to.
CRM_IDENTITY_KINDS = ('instagram', 'facebook', 'ig_id', 'fb_psid', 'telegram')
# The sales sheet's "Checker": every half hour someone confirms each inbox was looked at.
CRM_CHECK_CHANNELS = ['Tawk', 'FB Messenger', 'Instagram Messenger', 'FB Comments', 'Insta Comments',
                      'IND WhatsApp', 'USA WhatsApp', 'Email', 'India Call', 'USA Call', 'Telegram',
                      'TC website']
CRM_CHECK_HOURS = (7, 24)     # IST, half-hour slots from 07:00 to midnight -- the days before CRM_CHECK_ALL_DAY_FROM
# from this India day the half-hourly check runs round the clock, every half hour of the day (user, 2026-10-24); the
# days before keep 07:00 to midnight, so their percentages still mean what they meant
CRM_CHECK_ALL_DAY_FROM = date(2026, 10, 24)
# How ready to buy -- the colour of the row in the sales sheet (green: ready, yellow: thinking).
CRM_LIKELIHOOD = {'hot': 'Ready to buy', 'warm': 'Thinking about it', 'cold': 'Not likely'}
# How sure a deal is, for the Forecast page (a stage's "Counts in the forecast as"; a lead may override it)
CRM_FORECASTS = {'pipeline': 'Pipeline', 'best_case': 'Best case', 'commit': 'Committed', 'won': 'Closed won',
                 'lost': 'Lost'}
# What a stage does by itself: move a lead on after N days without a reply, or once the trip
# has started or passed another date (N days after it), or sat in the stage for N days.
CRM_AUTO_KINDS = {'no_reply': 'days with no reply from them', 'in_stage': 'days in this stage',
                  'after_date': 'days after the trip starts'}


class CrmPipeline(db.Model):
    __tablename__ = 'crm_pipelines'
    __table_args__ = (db.UniqueConstraint('workspace_id', 'key', name='uq_crm_pipelines_ws_key'),)

    id = db.Column(db.Integer, primary_key=True)
    # the workspace whose CRM this belongs to (Sales CRM 2.0, run 5a; NULL = the default workspace, services/crm_scope)
    workspace_id = db.Column(db.Integer, db.ForeignKey('workspaces.id'), nullable=True, index=True)
    key = db.Column(db.String(40), nullable=False)
    name = db.Column(db.String(80), nullable=False)
    product = db.Column(db.String(8), nullable=False, default='GEN')
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    # the first part of its WhatsApp stage tags: the lead's product code ('product') or tag_label ('own')
    tag_mode = db.Column(db.String(8), nullable=False, default='product', server_default='product')
    tag_label = db.Column(db.String(30))
    # leads of a product with its own pipeline pass on from here (General)
    catch_all = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    # what a lost lead may be lost FOR -- shown as buttons, so nobody has to type a reason
    fallout_reasons = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    stages = db.relationship('CrmStage', backref='pipeline', order_by='CrmStage.position',
                             cascade='all, delete-orphan')

    @property
    def first_stage(self):
        return next((s for s in self.stages if s.kind == 'open'), self.stages[0] if self.stages else None)

    @property
    def reply_stage(self):
        return next((s for s in self.stages if s.on_reply), None)

    @property
    def open_stages(self):
        return [s for s in self.stages if s.kind == 'open']


class CrmProduct(db.Model):
    """What a lead asks about (Set-up -> Pipelines -> Products, U6). The code is in WhatsApp tags
    ("TI", "TI: Prospect"); read through services/crm_products.py, never the seed constants."""
    __tablename__ = 'crm_products'
    __table_args__ = (db.UniqueConstraint('workspace_id', 'code', name='uq_crm_products_ws_code'),)

    id = db.Column(db.Integer, primary_key=True)
    # the workspace whose CRM this belongs to (Sales CRM 2.0, run 5a; NULL = the default workspace, services/crm_scope)
    workspace_id = db.Column(db.Integer, db.ForeignKey('workspaces.id'), nullable=True, index=True)
    code = db.Column(db.String(8), nullable=False)
    name = db.Column(db.String(60), nullable=False)
    icon = db.Column(db.String(40), nullable=False, default='fa-layer-group')
    offered = db.Column(db.Boolean, nullable=False, default=True)
    default_pipeline_id = db.Column(db.Integer, db.ForeignKey('crm_pipelines.id'), nullable=True)
    currency = db.Column(db.String(3), nullable=False, default='INR')
    kpi_row = db.Column(db.String(30))        # a crm_kpi row its new leads also count in (TC: tc_posts)
    position = db.Column(db.Integer, nullable=False, default=0)
    # money (Phase 1): the usual amount, what we earn on it ('fixed' amount / 'percent' of it / NULL: all of it),
    # and the usual days from enquiry to sale (the default close date; NULL: 14)
    price = db.Column(db.Numeric(12, 2), nullable=True)
    revenue_kind = db.Column(db.String(8), nullable=True)
    revenue_value = db.Column(db.Numeric(12, 2), nullable=True)
    close_days = db.Column(db.Integer, nullable=True)
    # the biggest discount an agent may quote without asking (percent of the price); NULL: no limit
    max_discount_pct = db.Column(db.Numeric(5, 2), nullable=True)

    default_pipeline = db.relationship('CrmPipeline')


def _forget_products(*_a):
    request_cache('crm_products').clear()


for _ev in ('after_insert', 'after_update', 'after_delete'):
    event.listen(CrmProduct, _ev, _forget_products)


class CrmField(db.Model):
    """A lead detail asked in one pipeline (pipeline_id None: in every one); its value is
    CrmLead.details[key]. The trip's dates stay columns (CRM_DATE_FIELDS), not rows here."""
    __tablename__ = 'crm_fields'

    id = db.Column(db.Integer, primary_key=True)
    pipeline_id = db.Column(db.Integer, db.ForeignKey('crm_pipelines.id'), nullable=True, index=True)
    key = db.Column(db.String(40), nullable=False)
    label = db.Column(db.String(80), nullable=False)
    type = db.Column(db.String(10), nullable=False, default='text')     # CRM_FIELD_TYPES
    options = db.Column(db.JSON)
    position = db.Column(db.Integer, nullable=False, default=0)
    on_card = db.Column(db.Boolean, nullable=False, default=False)
    on_add = db.Column(db.Boolean, nullable=False, default=False)
    required = db.Column(db.Boolean, nullable=False, default=False)

    pipeline = db.relationship('CrmPipeline')

    __table_args__ = (db.UniqueConstraint('pipeline_id', 'key', name='uq_crm_field_key'),)


class CrmStage(db.Model):
    __tablename__ = 'crm_stages'

    id = db.Column(db.Integer, primary_key=True)
    pipeline_id = db.Column(db.Integer, db.ForeignKey('crm_pipelines.id'), nullable=False, index=True)
    key = db.Column(db.String(40), nullable=False)
    name = db.Column(db.String(60), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=0)
    kind = db.Column(db.String(8), nullable=False, default='open')       # open / won / lost
    # a reply from the person moves a lead here out of the first stage (cold lead -> prospect)
    on_reply = db.Column(db.Boolean, nullable=False, default=False)
    sla_hours = db.Column(db.Integer)                                    # how long a lead may sit here
    # automation: after `auto_days` (see CRM_AUTO_KINDS) move the lead to `auto_to` by itself
    auto_kind = db.Column(db.String(10))       # no_reply / in_stage / after_date (CRM_AUTO_KINDS)
    auto_field = db.Column(db.String(40))      # after_date: which date (departure_date, ends_on, a date detail)
    auto_days = db.Column(db.Integer)
    auto_to_id = db.Column(db.Integer, db.ForeignKey('crm_stages.id', use_alter=True,
                                                     name='fk_crm_stage_auto_to'), nullable=True)
    auto_reason = db.Column(db.String(80))
    # what a person must fill in before a lead moves in (run 3b): field keys -- amount, close_date,
    # departure_date, ends_on, or one of the pipeline's own fields. NULL / empty: nothing.
    requires = db.Column(db.JSON, nullable=True)
    # "This stage means" (CRM_STAGE_MEANS): kind and the funnel role follow it
    means = db.Column(db.String(8))
    # the lead page's button for this stage ("I sent the quote" / Q)
    button_label = db.Column(db.String(60))
    button_code = db.Column(db.String(20))
    # the forecast category (CRM_FORECASTS) and the chance to win (0-100) its leads count with; NULL: automatic
    forecast = db.Column(db.String(10), nullable=True)
    probability = db.Column(db.Integer, nullable=True)

    auto_to = db.relationship('CrmStage', remote_side='CrmStage.id', foreign_keys=[auto_to_id], post_update=True)

    __table_args__ = (db.UniqueConstraint('pipeline_id', 'key', name='uq_crm_stage_key'),)

    @validates('means')
    def _means_sets_kind(self, _key, value):
        """"This stage means" decides open / won / lost (kind), so code that reads kind keeps working."""
        if value is not None:
            if value not in CRM_STAGE_MEANS:
                raise ValueError(value)
            self.kind = value if value in ('won', 'lost') else 'open'
        return value

    def derived_role(self):
        """cold / prospect / pipeline / customer / lost by where the stage sits -- the rule from before
        U5, for a stage saved without "This stage means". Compares by identity (unsaved stages have no id)."""
        if self.kind in ('won', 'lost'):
            return 'customer' if self.kind == 'won' else 'lost'
        stages = sorted(self.pipeline.stages, key=lambda s: s.position) if self.pipeline else [self]
        opens = [s for s in stages if s.kind == 'open']
        reply = next((s for s in stages if s.on_reply), None)
        if opens and opens[0] is self:
            return 'cold'
        if reply is not None and reply is self:
            return 'prospect'
        if reply is not None and self.position < reply.position:
            return 'cold'
        return 'pipeline'

    @property
    def role(self):
        return MEANS_ROLE.get(self.means) or self.derived_role()

    @property
    def stage_means(self):
        return self.means or ROLE_MEANS[self.derived_role()]


@event.listens_for(CrmStage, 'before_insert')
@event.listens_for(CrmStage, 'before_update')
def _crm_stage_kind(mapper, connection, target):
    """Every save: kind from means; a won / lost stage saved the old way gets its means."""
    if target.means:
        target.kind = target.means if target.means in ('won', 'lost') else 'open'
    elif target.kind in ('won', 'lost'):
        target.means = target.kind


class CrmSource(db.Model):
    __tablename__ = 'crm_sources'
    __table_args__ = (db.UniqueConstraint('workspace_id', 'key', name='uq_crm_sources_ws_key'),)

    id = db.Column(db.Integer, primary_key=True)
    # the workspace whose CRM this belongs to (Sales CRM 2.0, run 5a; NULL = the default workspace, services/crm_scope)
    workspace_id = db.Column(db.Integer, db.ForeignKey('workspaces.id'), nullable=True, index=True)
    key = db.Column(db.String(60), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    kind = db.Column(db.String(10), nullable=False, default='form')
    product = db.Column(db.String(8), nullable=False, default='GEN')
    pages = db.Column(db.JSON)                          # page addresses it is on, for people to read
    pipeline_id = db.Column(db.Integer, db.ForeignKey('crm_pipelines.id'), nullable=True)
    status = db.Column(db.String(10), nullable=False, default='live')
    team = db.Column(db.JSON)                           # user ids that own its leads; empty = all CS
    crm_tags = db.Column(db.JSON)                       # tags on the WhatsApp CRM contact
    dedupe_days = db.Column(db.Integer, nullable=False, default=30)
    built_in = db.Column(db.Boolean, nullable=False, default=False)   # one of the site's own forms
    lead_count = db.Column(db.Integer, nullable=False, default=0)
    last_lead_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    # how new leads are shared: NULL / 'fewest' = whoever has the fewest open leads, 'round_robin' = in turn
    assign_mode = db.Column(db.String(12), nullable=True)
    rr_last_user_id = db.Column(db.Integer, nullable=True)

    pipeline = db.relationship('CrmPipeline')


class CrmHousehold(db.Model):
    """A family (Sales CRM 2.0): the child abroad who pays, the parents, the carer. People link to it with
    CrmPerson.household_id; services/crm_household.py keeps it (made with the first link, deleted when empty)."""
    __tablename__ = 'crm_households'

    id = db.Column(db.Integer, primary_key=True)
    # the workspace whose CRM this belongs to (Sales CRM 2.0, run 5a; NULL = the default workspace, services/crm_scope)
    workspace_id = db.Column(db.Integer, db.ForeignKey('workspaces.id'), nullable=True, index=True)
    name = db.Column(db.String(120), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)


HOUSEHOLD_ROLES = (('payer', 'Pays (child abroad)'), ('parent', 'Parent'), ('carer', 'Carer'), ('other', 'Other'))


class CrmPerson(db.Model):
    __tablename__ = 'crm_people'
    # one contact per number in each workspace (the same number can be a contact in two workspaces)
    __table_args__ = (db.UniqueConstraint('workspace_id', 'phone', name='uq_crm_people_ws_phone'),)

    id = db.Column(db.Integer, primary_key=True)
    # the workspace whose CRM this belongs to (Sales CRM 2.0, run 5a; NULL = the default workspace, services/crm_scope)
    workspace_id = db.Column(db.Integer, db.ForeignKey('workspaces.id'), nullable=True, index=True)
    phone = db.Column(db.String(20), nullable=True)          # E.164
    email = db.Column(db.String(255), nullable=True, index=True)
    name = db.Column(db.String(120))
    country = db.Column(db.String(2))                                     # ISO code of the number
    consent_whatsapp = db.Column(db.Boolean, nullable=False, default=False)
    # "OK to send offers" (Sales CRM 2.0, run 5b): never the WhatsApp tick above. When it was last given or taken
    # back, how ("form: Diwali offer", "contact page", "merge"), and by whom on the staff (NULL: the person on a form)
    consent_marketing = db.Column(db.Boolean, nullable=False, default=False)
    consent_marketing_at = db.Column(db.DateTime, nullable=True)
    consent_marketing_how = db.Column(db.String(120), nullable=True)
    consent_marketing_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    wacrm_contact_id = db.Column(db.String(64), nullable=True, index=True)
    wacrm_conversation_id = db.Column(db.String(64), nullable=True)
    # told to the WhatsApp CRM after the save, in the background (crm.run_wa_sync): due since
    # when, whether their chat should go to the owner, the last problem, the last success
    wacrm_sync_due_at = db.Column(db.DateTime, nullable=True, index=True)
    wacrm_assign_due = db.Column(db.Boolean, nullable=True, default=False)
    # somebody already here wrote from a chat we had not seen: it goes to their owner after the
    # save, but only if nobody in the WhatsApp CRM has it (an owner change here moves it anyway)
    wacrm_assign_if_free = db.Column(db.Boolean, nullable=True, default=False)
    # their next push is quiet (tags written without starting the WhatsApp CRM's "tag added"
    # automations, contract 19): only while every mark since the last push was a bulk one
    wacrm_quiet = db.Column(db.Boolean, nullable=True, default=False)
    wa_sync_error = db.Column(db.String(300))
    wa_synced_at = db.Column(db.DateTime)
    wa_opt_out_at = db.Column(db.DateTime)            # they asked for no more WhatsApp messages
    # an admin opted them back in: their next push takes the "opted-out" tag off (then this clears)
    wa_opt_in_due = db.Column(db.Boolean, nullable=True, default=False)
    # when their older WhatsApp messages were brought onto the lead page, once; null again after a failed try
    wa_history_at = db.Column(db.DateTime)
    # the WhatsApp number they last wrote to (Set-up › Channels, services/channels.py); NULL = the WhatsApp CRM's, or never
    wa_line_id = db.Column(db.Integer, db.ForeignKey('crm_channel_lines.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # the family they belong to (services/crm_household.py) and their part in it: payer / parent / carer / other
    household_id = db.Column(db.Integer, db.ForeignKey('crm_households.id'), nullable=True, index=True)
    household_role = db.Column(db.String(10), nullable=True)

    household = db.relationship('CrmHousehold', backref=db.backref('members', order_by='CrmPerson.id'))
    leads = db.relationship('CrmLead', backref='person', order_by='CrmLead.created_at.desc()')
    identities = db.relationship('CrmIdentity', backref='person', cascade='all, delete-orphan',
                                 order_by='CrmIdentity.id')

    @property
    def display_name(self):
        handle = next((i.value for i in self.identities if i.kind in ('instagram', 'facebook')), None)
        return self.name or self.phone or self.email or handle or 'Unknown'

    def identity(self, kind):
        return next((i.value for i in self.identities if i.kind == kind), None)


class CrmIdentity(db.Model):
    """Another way to reach a person: an Instagram handle, a Facebook profile, the ids Meta sends."""
    __tablename__ = 'crm_identities'

    id = db.Column(db.Integer, primary_key=True)
    person_id = db.Column(db.Integer, db.ForeignKey('crm_people.id'), nullable=False, index=True)
    kind = db.Column(db.String(20), nullable=False)
    value = db.Column(db.String(190), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # its person's workspace, kept here only so the same handle can be a contact in two workspaces
    workspace_id = db.Column(db.Integer, db.ForeignKey('workspaces.id'), nullable=True, index=True)

    __table_args__ = (db.UniqueConstraint('workspace_id', 'kind', 'value', name='uq_crm_identities_ws'),)


class CrmFile(db.Model):
    """A document kept on a person (and maybe one of their enquiries): a passport copy, a policy, a quote PDF.
    The bytes live in PRIVATE_UPLOAD_FOLDER/crm/<stored_name>, never under static (services/crm_files.py)."""
    __tablename__ = 'crm_files'

    id = db.Column(db.Integer, primary_key=True)
    person_id = db.Column(db.Integer, db.ForeignKey('crm_people.id'), nullable=False, index=True)
    lead_id = db.Column(db.Integer, db.ForeignKey('crm_leads.id'), nullable=True, index=True)
    filename = db.Column(db.String(200), nullable=False)
    stored_name = db.Column(db.String(80), nullable=False, unique=True)
    size = db.Column(db.Integer, nullable=False, default=0)
    content_type = db.Column(db.String(100))
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    uploaded_by = db.relationship('User', foreign_keys=[uploaded_by_id])


class CrmChannelCheck(db.Model):
    """One tick of the inbox check: this channel was looked at in this half hour (IST) by them."""
    __tablename__ = 'crm_channel_checks'

    id = db.Column(db.Integer, primary_key=True)
    day = db.Column(db.Date, nullable=False, index=True)          # the date in India
    slot = db.Column(db.SmallInteger, nullable=False)            # half hours since midnight IST, 0-47
    channel = db.Column(db.String(40), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    checked_at = db.Column(db.DateTime, default=datetime.utcnow)

    workspace_id = db.Column(db.Integer, db.ForeignKey('workspaces.id'), nullable=True, index=True)

    user = db.relationship('User')

    __table_args__ = (db.UniqueConstraint('workspace_id', 'day', 'slot', 'channel', name='uq_crm_checks_ws'),)


class CrmLead(db.Model):
    __tablename__ = 'crm_leads'

    id = db.Column(db.Integer, primary_key=True)
    # the workspace whose CRM this belongs to (Sales CRM 2.0, run 5a; NULL = the default workspace, services/crm_scope)
    workspace_id = db.Column(db.Integer, db.ForeignKey('workspaces.id'), nullable=True, index=True)
    person_id = db.Column(db.Integer, db.ForeignKey('crm_people.id'), nullable=False, index=True)
    product = db.Column(db.String(8), nullable=False, default='GEN')
    source_id = db.Column(db.Integer, db.ForeignKey('crm_sources.id'), nullable=True, index=True)
    pipeline_id = db.Column(db.Integer, db.ForeignKey('crm_pipelines.id'), nullable=True, index=True)
    stage_id = db.Column(db.Integer, db.ForeignKey('crm_stages.id'), nullable=True, index=True)
    status = db.Column(db.String(6), nullable=False, default='open')     # open / won / lost
    temperature = db.Column(db.String(3))
    likelihood = db.Column(db.String(4))   # hot / warm / cold (CRM_LIKELIHOOD)
    # brought in from before the CRM (site backfill, the sales sheet): its history is in the
    # imported KPI numbers already, so the live numbers leave it out
    imported = db.Column(db.Boolean, nullable=False, default=False)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    fallout_reason = db.Column(db.String(80))
    details = db.Column(db.JSON)          # what the form said: trip dates, ages, service, message
    utm = db.Column(db.JSON)              # utm_*, gclid, fbclid, referrer, landing page
    ref_type = db.Column(db.String(30))   # the record it came from: insurance_quotes, ...
    ref_id = db.Column(db.Integer)
    departure_date = db.Column(db.Date)   # drives the "days before departure" steps
    ends_on = db.Column(db.Date)          # policy / trip end: drives the expiration reminder
    entered_stage_at = db.Column(db.DateTime, default=datetime.utcnow)
    # set when the owner was told the lead has sat in its stage too long; cleared on every move
    sla_alerted_at = db.Column(db.DateTime)
    # "Remind me in 1 hour" on a customer waiting on us: hidden on My day, and no waiting bell, until then
    snoozed_until = db.Column(db.DateTime)
    # the "is waiting for your reply" bell went for this wait; our next message to them clears it
    waiting_alerted_at = db.Column(db.DateTime)
    last_activity_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    closed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)   # staff who added it
    # money (Phase 1): the deal value in its own currency, what we earn on it (same currency), the day it
    # should count in, and the agent's own forecast category (NULL: the stage's)
    amount = db.Column(db.Numeric(12, 2), nullable=True)
    currency = db.Column(db.String(3), nullable=True)
    revenue = db.Column(db.Numeric(12, 2), nullable=True)
    close_date = db.Column(db.Date, nullable=True)
    forecast = db.Column(db.String(10), nullable=True)
    # the recycle bin (run 3b): a removed lead is only marked; crm_bin hides it everywhere
    deleted_at = db.Column(db.DateTime, nullable=True, index=True)
    deleted_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    # lead scoring (run 5b, services/crm_scoring): the points it has now (NULL: not scored / scoring off), and
    # whether a person picked the rating ("Ready to buy?") -- then the score never changes it
    score = db.Column(db.Integer, nullable=True)
    likelihood_manual = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    # "Summarise" on the lead page (services/crm_ai): {touch_id, summary, next, at} -- good until a newer touch
    ai_cache = db.Column(db.JSON, nullable=True)

    source = db.relationship('CrmSource')
    pipeline = db.relationship('CrmPipeline')
    stage = db.relationship('CrmStage')
    owner = db.relationship('User', foreign_keys=[owner_id])
    created_by = db.relationship('User', foreign_keys=[created_by_id])
    deleted_by = db.relationship('User', foreign_keys=[deleted_by_id])
    tasks = db.relationship('CrmTask', backref='lead', order_by='CrmTask.due_at',
                            cascade='all, delete-orphan')
    touchpoints = db.relationship('CrmTouchpoint', backref='lead',
                                  order_by='CrmTouchpoint.created_at.desc()',
                                  cascade='all, delete-orphan')

    __table_args__ = (db.Index('ix_crm_leads_ref', 'ref_type', 'ref_id'),)

    @property
    def open_task(self):
        # the next STEP; tasks, calls and meetings added by hand are not "the next step"
        return next((t for t in self.tasks if t.status == 'open' and t.is_step), None)

    @property
    def days_to_departure(self):
        if not self.departure_date:
            return None
        return (self.departure_date - date.today()).days

    @property
    def forecast_category(self):
        from app.services import crm_money
        return crm_money.lead_forecast(self)

    @property
    def win_chance(self):
        from app.services import crm_money
        return crm_money.lead_chance(self)

    @property
    def expected(self):
        from app.services import crm_money
        return crm_money.lead_expected(self)

    @property
    def stuck_hours(self):
        """Hours past its stage's limit (Set-up -> Pipelines, "max hours"), or None when on time."""
        st = self.stage
        if self.status != 'open' or st is None or not st.sla_hours or not self.entered_stage_at:
            return None
        over = (datetime.utcnow() - self.entered_stage_at).total_seconds() / 3600 - st.sla_hours
        return int(over) if over > 0 else None


class CrmCurrencyRate(db.Model):
    """Reporting-currency units for one unit of `code` (the reporting currency is the app setting crm.currency)."""
    __tablename__ = 'crm_currency_rates'

    code = db.Column(db.String(3), primary_key=True)
    rate = db.Column(db.Numeric(14, 6), nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)


class CrmTarget(db.Model):
    """What a person (or a team) aims for in one month: money won (reporting currency), deals, new leads.
    One of user / team is set -- both empty is the whole company (new-leads target only). Uniqueness is kept in
    code (crm_money.save_target), because NULLs in a unique constraint differ between SQLite and PostgreSQL."""
    __tablename__ = 'crm_targets'

    id = db.Column(db.Integer, primary_key=True)
    # the workspace whose CRM this belongs to (Sales CRM 2.0, run 5a; NULL = the default workspace, services/crm_scope)
    workspace_id = db.Column(db.Integer, db.ForeignKey('workspaces.id'), nullable=True, index=True)
    period = db.Column(db.String(7), nullable=False, index=True)          # 'YYYY-MM'
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    team_id = db.Column(db.Integer, db.ForeignKey('workspace_teams.id', ondelete='CASCADE'), nullable=True, index=True)
    pipeline_id = db.Column(db.Integer, db.ForeignKey('crm_pipelines.id'), nullable=True)
    amount = db.Column(db.Numeric(12, 2), nullable=True)
    deals = db.Column(db.Integer, nullable=True)
    leads = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)


class CrmDailyStat(db.Model):
    """One saved number for one India day (Sales CRM 2.0, services/crm_numbers.py): an 'event' metric -- something that
    happened that day -- for one person (user_id NULL = the whole company) in one pipeline (NULL = all pipelines).
    Uniqueness (day, metric, user, pipeline) is kept in code (an upsert), because NULLs in a unique constraint differ
    between SQLite and PostgreSQL."""
    __tablename__ = 'crm_daily_stats'

    id = db.Column(db.Integer, primary_key=True)
    # the workspace whose CRM this belongs to (Sales CRM 2.0, run 5a; NULL = the default workspace, services/crm_scope)
    workspace_id = db.Column(db.Integer, db.ForeignKey('workspaces.id'), nullable=True, index=True)
    day = db.Column(db.Date, nullable=False)
    metric = db.Column(db.String(40), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    pipeline_id = db.Column(db.Integer, db.ForeignKey('crm_pipelines.id'), nullable=True)
    value = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    computed_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.Index('ix_crm_daily_stats_day_metric', 'day', 'metric'),)


CRM_QUOTE_STATUSES = ('draft', 'sent', 'accepted', 'declined', 'expired')
CRM_PAYMENT_STATUSES = ('pending', 'paid', 'failed', 'refunded')


class CrmQuote(db.Model):
    """A quote on a lead (Sales CRM 2.0, run 4b): what we offered, for how much, until when. Hangs on the lead
    (hidden with it in the recycle bin and by visibility). services/crm_quotes.py keeps it."""
    __tablename__ = 'crm_quotes'

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey('crm_leads.id'), nullable=False, index=True)
    title = db.Column(db.String(160), nullable=False)
    details = db.Column(db.Text)
    amount = db.Column(db.Numeric(12, 2), nullable=True)
    currency = db.Column(db.String(3), nullable=True)
    valid_until = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(10), nullable=False, default='draft')
    needs_approval = db.Column(db.Boolean, nullable=False, default=False)
    approved_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    sent_at = db.Column(db.DateTime, nullable=True)
    # the "Quote sent" milestone line that Mark as sent logged (the numbers then count that line, not this row)
    sent_touch_id = db.Column(db.Integer, nullable=True)

    lead = db.relationship('CrmLead', backref=db.backref('quotes', cascade='all, delete-orphan',
                                                          order_by='CrmQuote.id.desc()'))
    approved_by = db.relationship('User', foreign_keys=[approved_by_id])
    created_by = db.relationship('User', foreign_keys=[created_by_id])

    @property
    def reference(self):
        return 'Q-%d' % self.id


class CrmPayment(db.Model):
    """A payment link (or a bank transfer) asked for on a lead; paid when someone marks it or the provider says so."""
    __tablename__ = 'crm_payments'

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey('crm_leads.id'), nullable=False, index=True)
    quote_id = db.Column(db.Integer, db.ForeignKey('crm_quotes.id'), nullable=True)
    amount = db.Column(db.Numeric(12, 2), nullable=True)
    currency = db.Column(db.String(3), nullable=True)
    link_url = db.Column(db.String(500))
    provider = db.Column(db.String(30))
    reference = db.Column(db.String(80), index=True)
    status = db.Column(db.String(10), nullable=False, default='pending')
    paid_at = db.Column(db.DateTime, nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # the "Payment link sent" milestone line it logged (see CrmQuote.sent_touch_id)
    link_touch_id = db.Column(db.Integer, nullable=True)

    lead = db.relationship('CrmLead', backref=db.backref('payments', cascade='all, delete-orphan',
                                                          order_by='CrmPayment.id.desc()'))
    quote = db.relationship('CrmQuote', foreign_keys=[quote_id])
    created_by = db.relationship('User', foreign_keys=[created_by_id])


class CrmView(db.Model):
    """A saved view: a staff page's filters under a name. Leads and Contacts since Sales CRM 2.0 (run 4b); every staff
    page since 2026-10-27 (services/crm_views.py). Not SavedFilter: that one is bound to the post listings' filter
    engine. Shared with ONE team, the owner's (services/team_share.py)."""
    __tablename__ = 'crm_views'

    id = db.Column(db.Integer, primary_key=True)
    # the workspace whose CRM this belongs to (Sales CRM 2.0, run 5a; NULL = the default workspace, services/crm_scope)
    workspace_id = db.Column(db.Integer, db.ForeignKey('workspaces.id'), nullable=True, index=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    # crm_leads / crm_contacts, else the page key (services/access.PAGES) of the page the view is of
    scope = db.Column(db.String(20), nullable=False, default='crm_leads')
    name = db.Column(db.String(60), nullable=False)
    params = db.Column(db.JSON, nullable=False, default=dict)
    # a view of any other page: its endpoint and the words of its path (NULL for Leads and Contacts)
    endpoint = db.Column(db.String(80), nullable=True)
    args = db.Column(db.JSON, nullable=True)
    shared = db.Column(db.Boolean, nullable=False, default=False)        # true while team_id is set
    team_id = db.Column(db.Integer, db.ForeignKey('workspace_teams.id', ondelete='SET NULL'), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    owner = db.relationship('User', foreign_keys=[owner_id])
    team = db.relationship('WorkspaceTeam', foreign_keys=[team_id])


class StaffFavourite(db.Model):
    """One of a staff member's favourites (services/favourites.py): a page with its filters, or a saved view they can
    open. Only theirs; the order is theirs."""
    __tablename__ = 'staff_favourites'
    __table_args__ = (db.UniqueConstraint('user_id', 'key', name='uq_staff_favourite_key'),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    key = db.Column(db.String(40), nullable=False)            # sha1 of the address, so a page is starred once
    label = db.Column(db.String(80), nullable=True)           # NULL: the view's name, else the page's
    endpoint = db.Column(db.String(80), nullable=False)
    args = db.Column(db.JSON, nullable=True)
    params = db.Column(db.JSON, nullable=True)
    view_id = db.Column(db.Integer, db.ForeignKey('crm_views.id', ondelete='CASCADE'), nullable=True)
    position = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    view = db.relationship('CrmView', foreign_keys=[view_id],
                           backref=db.backref('favourites', cascade='all, delete-orphan'))


class CrmSavedReport(db.Model):
    """A report somebody built on the report builder, kept by name (config: whitelisted keys only)."""
    __tablename__ = 'crm_saved_reports'

    id = db.Column(db.Integer, primary_key=True)
    # the workspace whose CRM this belongs to (Sales CRM 2.0, run 5a; NULL = the default workspace, services/crm_scope)
    workspace_id = db.Column(db.Integer, db.ForeignKey('workspaces.id'), nullable=True, index=True)
    name = db.Column(db.String(80), nullable=False)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    shared = db.Column(db.Boolean, nullable=False, default=False)
    config = db.Column(db.JSON, nullable=False, default=dict)
    pinned = db.Column(db.Boolean, nullable=False, default=False)
    position = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    owner = db.relationship('User', foreign_keys=[owner_id])


class CrmRule(db.Model):
    """An automation rule (Sales CRM 2.0, run 5b, services/crm_rules): WHEN something happens to a lead (trigger +
    trigger_args), IF its fields say so (conditions [{field, op, value}]), THEN do these (actions [{type, ...}]).
    Every choice comes from the whitelists in crm_rules; nothing a rule does messages a customer."""
    __tablename__ = 'crm_rules'

    id = db.Column(db.Integer, primary_key=True)
    # the workspace whose CRM this belongs to (NULL = the default workspace, services/crm_scope)
    workspace_id = db.Column(db.Integer, db.ForeignKey('workspaces.id'), nullable=True, index=True)
    name = db.Column(db.String(120), nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    trigger = db.Column(db.String(20), nullable=False)
    trigger_args = db.Column(db.JSON, nullable=True)
    conditions = db.Column(db.JSON, nullable=True)
    actions = db.Column(db.JSON, nullable=True)
    position = db.Column(db.Integer, nullable=False, default=0)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_run_at = db.Column(db.DateTime, nullable=True)
    run_count = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    last_error = db.Column(db.String(300), nullable=True)
    last_error_at = db.Column(db.DateTime, nullable=True)
    # the clash with a stage's own automatic move last rung about (check_automation_conflicts); NULL: none
    conflict = db.Column(db.String(300), nullable=True)


class CrmRuleRun(db.Model):
    """A rule ran for a lead on one triggering event: at most once (the unique key), so a repeat of the same event,
    a second worker or a chain coming back round never runs it twice."""
    __tablename__ = 'crm_rule_runs'
    __table_args__ = (db.UniqueConstraint('rule_id', 'lead_id', 'event_key', name='uq_crm_rule_runs'),)

    id = db.Column(db.Integer, primary_key=True)
    rule_id = db.Column(db.Integer, db.ForeignKey('crm_rules.id'), nullable=False, index=True)
    lead_id = db.Column(db.Integer, db.ForeignKey('crm_leads.id'), nullable=False, index=True)
    event_key = db.Column(db.String(120), nullable=False)
    ok = db.Column(db.Boolean, nullable=False, default=True)
    at = db.Column(db.DateTime, default=datetime.utcnow)


class CrmScoreRule(db.Model):
    """One line of lead scoring (run 5b, services/crm_scoring): a signal ("they replied", "the trip is within 14
    days") and the points it is worth (minus for a bad sign)."""
    __tablename__ = 'crm_score_rules'

    id = db.Column(db.Integer, primary_key=True)
    workspace_id = db.Column(db.Integer, db.ForeignKey('workspaces.id'), nullable=True, index=True)
    name = db.Column(db.String(120), nullable=False)
    points = db.Column(db.Integer, nullable=False, default=0)
    signal = db.Column(db.String(30), nullable=False)
    args = db.Column(db.JSON, nullable=True)
    active = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())
    position = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class CrmCampaign(db.Model):
    """A marketing activity or paid campaign (Lead sources -> Marketing activities; run 5b moved them here from the
    'crm' setting): who does it and where it stands, and -- for the Campaigns table on Sales results -- the
    utm_campaign it carries in its links, the lead source it feeds, its dates and what it cost."""
    __tablename__ = 'crm_campaigns'

    id = db.Column(db.Integer, primary_key=True)
    workspace_id = db.Column(db.Integer, db.ForeignKey('workspaces.id'), nullable=True, index=True)
    platform = db.Column(db.String(200), nullable=True)
    name = db.Column(db.String(200), nullable=True)               # the activity ("Search ads")
    who = db.Column(db.String(200), nullable=True)
    status = db.Column(db.String(200), nullable=True)             # where it stands ("Ongoing")
    utm_campaign = db.Column(db.String(120), nullable=True, index=True)
    source_id = db.Column(db.Integer, db.ForeignKey('crm_sources.id'), nullable=True)
    starts_on = db.Column(db.Date, nullable=True)
    ends_on = db.Column(db.Date, nullable=True)
    cost = db.Column(db.Numeric(12, 2), nullable=True)
    currency = db.Column(db.String(3), nullable=True)
    position = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    source = db.relationship('CrmSource')


class CrmTouchpoint(db.Model):
    """Something that passed between us and the person: a message either way, a call, a form."""
    __tablename__ = 'crm_touchpoints'

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey('crm_leads.id'), nullable=True, index=True)
    person_id = db.Column(db.Integer, db.ForeignKey('crm_people.id'), nullable=False, index=True)
    channel = db.Column(db.String(10), nullable=False, default='note')
    direction = db.Column(db.String(4), nullable=False, default='none')   # in / out / none
    code = db.Column(db.String(20))           # the playbook step it carried out, e.g. "TI #3"
    outcome = db.Column(db.String(20))        # for calls: connected / no_answer / ...
    body = db.Column(db.Text)
    status = db.Column(db.String(12))         # sent / delivered / read / failed, for messages
    fail_reason = db.Column(db.String(300))   # why WhatsApp did not deliver it, in plain words (crm.wa_failure_text)
    # who sent an outbound message (CRM_VIA); null on older rows: a person when agent_id is set, else automation
    via = db.Column(db.String(12))
    agent_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    external_id = db.Column(db.String(120), index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    # the WhatsApp number it went through (Set-up › Channels); NULL = the WhatsApp CRM's, or not WhatsApp
    line_id = db.Column(db.Integer, db.ForeignKey('crm_channel_lines.id', ondelete='SET NULL'), nullable=True,
                        index=True)

    agent = db.relationship('User', foreign_keys=[agent_id])
    line = db.relationship('CrmChannelLine', foreign_keys=[line_id])


class CrmChannelLine(db.Model):
    """A WhatsApp number the portal talks to itself, through Meta's Cloud API (Set-up › Channels, 2026-10-29), beside
    the WhatsApp CRM, which keeps its own number. What it is, how it is reached and what Meta last said about it;
    services/channels.py and services/wa_meta.py do the work."""
    __tablename__ = 'crm_channel_lines'

    id = db.Column(db.Integer, primary_key=True)
    # the workspace whose CRM its people and leads belong to (NULL = the default one)
    workspace_id = db.Column(db.Integer, db.ForeignKey('workspaces.id', ondelete='SET NULL'), nullable=True,
                             index=True)
    key = db.Column(db.String(30), nullable=False, unique=True)
    label = db.Column(db.String(60), nullable=False)               # "USA"
    provider = db.Column(db.String(20), nullable=False, default='meta')
    phone = db.Column(db.String(20))                                # +19179005094, as Meta lists it
    phone_number_id = db.Column(db.String(40), nullable=False, unique=True)
    waba_id = db.Column(db.String(40))                              # its WhatsApp Business Account
    secrets = db.Column(db.Text)                                    # sealed {'token', 'app_secret'} (services/secretbox)
    verify_token = db.Column(db.String(64), nullable=False)         # Meta's address check echoes it
    source_key = db.Column(db.String(60))                           # the lead source its newcomers come in under
    prefixes = db.Column(db.JSON)                                   # ['+1']: who it writes first to
    also_on = db.Column(db.JSON)                                    # ['tawk']: other systems that hear this number
    status = db.Column(db.String(12), nullable=False, default='new')   # new / live / paused / error
    last_error = db.Column(db.String(300))
    connected_at = db.Column(db.DateTime)
    last_in_at = db.Column(db.DateTime)
    last_out_at = db.Column(db.DateTime)
    templates = db.Column(db.JSON)                                  # its account's templates, as Meta last listed them
    templates_at = db.Column(db.DateTime)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class CrmTask(db.Model):
    """The next thing to do for a lead: a message to send or a call to make, by a time."""
    __tablename__ = 'crm_tasks'

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey('crm_leads.id'), nullable=True, index=True)
    step_id = db.Column(db.Integer, db.ForeignKey('crm_playbook_steps.id'), nullable=True)
    code = db.Column(db.String(20))
    title = db.Column(db.String(160), nullable=False)
    channel = db.Column(db.String(10), nullable=False, default='whatsapp')
    auto = db.Column(db.Boolean, nullable=False, default=False)
    due_at = db.Column(db.DateTime, nullable=False, index=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    status = db.Column(db.String(8), nullable=False, default='open')     # open / sending / done / skipped
    done_at = db.Column(db.DateTime)          # done_at: when it was done; while "sending", when it was taken
    done_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    note = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # tasks, calls and meetings that people add by hand (Sales CRM 2.0). kind 'step' is a follow-up step
    # of a pipeline (or a call-back / imported follow-up): only those have a lead for certain.
    person_id = db.Column(db.Integer, db.ForeignKey('crm_people.id'), nullable=True, index=True)
    kind = db.Column(db.String(10), nullable=False, default='step', server_default='step')
    ends_at = db.Column(db.DateTime, nullable=True)
    location = db.Column(db.String(200), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    priority = db.Column(db.String(8), nullable=True)           # low / normal / high

    step = db.relationship('CrmPlaybookStep')
    owner = db.relationship('User', foreign_keys=[owner_id])
    created_by = db.relationship('User', foreign_keys=[created_by_id])
    person = db.relationship('CrmPerson', backref=db.backref('tasks', cascade='all, delete-orphan'))

    @property
    def is_step(self):
        return (self.kind or 'step') == 'step'

    @property
    def is_overdue(self):
        return self.status == 'open' and self.due_at < datetime.utcnow()


class CrmAudit(db.Model):
    """One changed field of a lead, a person, a task...: who, when, what it was and what it became.
    Raw values (ids, ISO dates); services/crm_audit turns them into words when they are shown."""
    __tablename__ = 'crm_audit'

    id = db.Column(db.Integer, primary_key=True)
    # the workspace whose CRM this belongs to (Sales CRM 2.0, run 5a; NULL = the default workspace, services/crm_scope)
    workspace_id = db.Column(db.Integer, db.ForeignKey('workspaces.id'), nullable=True, index=True)
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    user_id = db.Column(db.Integer, nullable=True)           # NULL: the system (a job, a reply, an import)
    record_type = db.Column(db.String(12), nullable=False)    # lead / person / task / quote ...
    record_id = db.Column(db.Integer, nullable=False)
    field = db.Column(db.String(40), nullable=False)
    old = db.Column(db.Text)
    new = db.Column(db.Text)

    __table_args__ = (db.Index('ix_crm_audit_record', 'record_type', 'record_id'),)


class CrmStageChange(db.Model):
    __tablename__ = 'crm_stage_changes'

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey('crm_leads.id'), nullable=False, index=True)
    from_stage_id = db.Column(db.Integer, db.ForeignKey('crm_stages.id'), nullable=True)
    to_stage_id = db.Column(db.Integer, db.ForeignKey('crm_stages.id'), nullable=False)
    by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)   # None: the system
    reason = db.Column(db.String(160))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    # newest first; the id breaks ties, because two moves in one clock tick (a move and the
    # automation that follows it) are otherwise in any order -- and Undo reads the first one
    lead = db.relationship('CrmLead', backref=db.backref('stage_changes', cascade='all, delete-orphan',
                                                         order_by='(CrmStageChange.created_at.desc(), CrmStageChange.id.desc())'))
    from_stage = db.relationship('CrmStage', foreign_keys=[from_stage_id])
    to_stage = db.relationship('CrmStage', foreign_keys=[to_stage_id])
    by = db.relationship('User', foreign_keys=[by_id])


class CrmPlaybookStep(db.Model):
    """One message or call in a stage's sequence -- the TC #1 / TI #3 / PI #2 of the sales sheet."""
    __tablename__ = 'crm_playbook_steps'

    id = db.Column(db.Integer, primary_key=True)
    stage_id = db.Column(db.Integer, db.ForeignKey('crm_stages.id'), nullable=False, index=True)
    position = db.Column(db.Integer, nullable=False, default=0)
    code = db.Column(db.String(20), nullable=False)
    title = db.Column(db.String(160), nullable=False)
    channel = db.Column(db.String(10), nullable=False, default='whatsapp')   # whatsapp / call / email / todo
    body = db.Column(db.Text)              # the message, with {name} {agent} {product}... filled in
    # after_hours: hours after the last step; date_offset: days from a date of the lead (negative: before)
    trigger = db.Column(db.String(24), nullable=False, default='after_hours')
    trigger_value = db.Column(db.Integer, nullable=False, default=0)
    trigger_field = db.Column(db.String(40))     # date_offset: departure_date, ends_on or a date detail
    kind = db.Column(db.String(16))              # CRM_STEP_KINDS: what the "numbers" count it as
    wa_params = db.Column(db.JSON)               # template fill-in map (U6)
    auto = db.Column(db.Boolean, nullable=False, default=False)   # sent without a person, once connected
    wa_template = db.Column(db.String(80))  # the approved WhatsApp template it maps to, if any

    stage = db.relationship('CrmStage', backref=db.backref('steps', order_by='CrmPlaybookStep.position',
                                                           cascade='all, delete-orphan'))


class CrmAnswer(db.Model):
    """A ready answer to a question people ask -- suggested when their message reads like it."""
    __tablename__ = 'crm_answers'

    id = db.Column(db.Integer, primary_key=True)
    # the workspace whose CRM this belongs to (Sales CRM 2.0, run 5a; NULL = the default workspace, services/crm_scope)
    workspace_id = db.Column(db.Integer, db.ForeignKey('workspaces.id'), nullable=True, index=True)
    title = db.Column(db.String(160), nullable=False)       # the question, in their words
    keywords = db.Column(db.String(400))                    # more words that should find it
    # set on a ready message rather than an answer: BW, FM, HJ... picked from "Quick messages"
    # on the lead page and counted under its code; answers (no code) are what "They asked" offers
    code = db.Column(db.String(20))
    body = db.Column(db.Text, nullable=False)
    product = db.Column(db.String(8), nullable=False, default='GEN')
    use_count = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CrmActivity(db.Model):
    """A number on the KPI sheet the CRM cannot count by itself (Google reviews, blogs on the
    WordPress site...), entered by the person who did it; or a day of the old KPI tabs brought in
    from the sales sheet (source 'import'). user_id None: the team's own row."""
    __tablename__ = 'crm_activities'

    id = db.Column(db.Integer, primary_key=True)
    # the workspace whose CRM this belongs to (Sales CRM 2.0, run 5a; NULL = the default workspace, services/crm_scope)
    workspace_id = db.Column(db.Integer, db.ForeignKey('workspaces.id'), nullable=True, index=True)
    day = db.Column(db.Date, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    metric = db.Column(db.String(30), nullable=False)
    count = db.Column(db.Float, nullable=False, default=0)
    source = db.Column(db.String(8), nullable=False, default='manual')     # manual / import
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CrmDoNotContact(db.Model):
    """Somebody erased at their request (contact page -> Erase this person): a salted hash of their phone
    and e-mail (services/crm_people.dnc_hash), never the number or address. Imports skip a match; a new
    enquiry they make themselves clears it."""
    __tablename__ = 'crm_do_not_contact'

    id = db.Column(db.Integer, primary_key=True)
    phone_hash = db.Column(db.String(64), nullable=True, index=True)
    email_hash = db.Column(db.String(64), nullable=True, index=True)
    reason = db.Column(db.String(40), nullable=False, default='erased')
    at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)


# ---------------------------------------------------------------------------
# Workspaces: who may open which screens (services/access.py)
#
# A workspace switches modules on (Sales CRM, WhatsApp, Sahayak ...); a module is a group of
# pages; a role is a set of pages; people get pages through their own role and the roles of the
# teams they are in. What a page IS lives in code (services/access.MODULES) -- it is a screen --
# and everything about who sees it lives here, so it is changed on a screen, not in a deploy.
# ---------------------------------------------------------------------------

workspace_team_members = db.Table(
    'workspace_team_members',
    db.Column('team_id', db.Integer, db.ForeignKey('workspace_teams.id', ondelete='CASCADE'), primary_key=True),
    db.Column('user_id', db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
)


class Workspace(db.Model):
    __tablename__ = 'workspaces'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(60), nullable=False, unique=True)
    description = db.Column(db.String(255))
    # module keys switched on; NULL = every module, so a module that ships later shows up rather
    # than staying invisible until somebody thinks to tick it
    modules = db.Column(db.JSON)
    # the WhatsApp CRM workspace this one is kept in step with: {account_id, name, synced_at,
    # error}. NULL = not linked.
    wacrm = db.Column(db.JSON)
    # the staff menu as arranged on Team -> Menu builder: {'sections': [...], 'labels': {page: name},
    # 'hidden': [page, ...]} (access.menu_layout reads it). NULL = the menu in code (access.SECTIONS).
    menu = db.Column(db.JSON)
    # the business WhatsApp number this workspace runs (E.164), as set up in "New workspace". The workspace
    # linked to the WhatsApp CRM shows the number the CRM reports instead (wacrm_team.number_of).
    whatsapp_phone = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)

    roles = db.relationship('WorkspaceRole', backref='workspace', cascade='all, delete-orphan',
                            order_by='WorkspaceRole.id')
    teams = db.relationship('WorkspaceTeam', backref='workspace', cascade='all, delete-orphan',
                            order_by='WorkspaceTeam.name')
    members = db.relationship('WorkspaceMember', backref='workspace', cascade='all, delete-orphan')


class WorkspaceRole(db.Model):
    __tablename__ = 'workspace_roles'
    __table_args__ = (db.UniqueConstraint('workspace_id', 'name', name='uq_workspace_role_name'),)

    id = db.Column(db.Integer, primary_key=True)
    workspace_id = db.Column(db.Integer, db.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False, index=True)
    name = db.Column(db.String(80), nullable=False)
    description = db.Column(db.String(255))
    pages = db.Column(db.JSON)                        # page keys from services/access.PAGES
    # 'admin' / 'cs' for the two every workspace starts with; NULL for the ones staff make. The
    # administrator's pages cannot be edited: a workspace must always have a way back in.
    system_key = db.Column(db.String(20))
    # which leads people with this role see in the Sales CRM: NULL / 'all' = everyone's, 'team' = their
    # team's, 'own' = only their own (services/crm_access)
    crm_scope = db.Column(db.String(8), nullable=True)
    # what it may DO on those pages (services/role_rights): {'profile', 'view': [look-only page keys], 'remove',
    # 'mask'}; NULL = as before roles had rights (nothing look-only, removing allowed, nothing hidden)
    rights = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class WorkspaceTeam(db.Model):
    __tablename__ = 'workspace_teams'
    __table_args__ = (db.UniqueConstraint('workspace_id', 'name', name='uq_workspace_team_name'),)

    id = db.Column(db.Integer, primary_key=True)
    workspace_id = db.Column(db.Integer, db.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False, index=True)
    name = db.Column(db.String(80), nullable=False)
    description = db.Column(db.String(255))
    role_id = db.Column(db.Integer, db.ForeignKey('workspace_roles.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    role = db.relationship('WorkspaceRole')
    users = db.relationship('User', secondary=workspace_team_members, order_by='User.first_name')


class WorkspaceMember(db.Model):
    __tablename__ = 'workspace_members'
    __table_args__ = (db.UniqueConstraint('workspace_id', 'user_id', name='uq_workspace_member'),)

    id = db.Column(db.Integer, primary_key=True)
    workspace_id = db.Column(db.Integer, db.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    # NULL: their pages come from their teams only
    role_id = db.Column(db.Integer, db.ForeignKey('workspace_roles.id', ondelete='SET NULL'), nullable=True)
    is_owner = db.Column(db.Boolean, default=False, nullable=False)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)
    added_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    # their place in the linked WhatsApp CRM: the role it was last given, when, and what went wrong
    wacrm_role = db.Column(db.String(20))
    wacrm_synced_at = db.Column(db.DateTime)
    wacrm_error = db.Column(db.String(255))
    # away until this moment (UTC): no new leads are shared with them (services/crm_assign)
    away_until = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User', foreign_keys=[user_id])
    role = db.relationship('WorkspaceRole')
