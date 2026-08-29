"""Signed, expiring tokens for e-mail verification and password reset (no DB table needed)."""
from flask import current_app
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

VERIFY_SALT = 'email-verify'
RESET_SALT = 'password-reset'
VERIFY_MAX_AGE = 3 * 24 * 3600
RESET_MAX_AGE = 2 * 3600


def _serializer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'])


def make_verify_token(user):
    return _serializer().dumps({'uid': user.id, 'email': user.email}, salt=VERIFY_SALT)


def load_verify_token(token):
    try:
        return _serializer().loads(token, salt=VERIFY_SALT, max_age=VERIFY_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


def make_reset_token(user):
    # Binding the current password hash makes the token single-use: it stops validating once the password changes.
    return _serializer().dumps({'uid': user.id, 'pw': (user.password_hash or '')[-12:]}, salt=RESET_SALT)


def load_reset_token(token):
    try:
        return _serializer().loads(token, salt=RESET_SALT, max_age=RESET_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
