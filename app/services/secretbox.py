"""Secrets the portal keeps in its own database -- a WhatsApp number's Meta token and app secret (Set-up › Channels,
2026-10-29). Sealed with Fernet under a key made from the app's SECRET_KEY; a page never shows one again, it is only
replaced or removed. A changed SECRET_KEY leaves them unreadable: open() answers None and the number says to enter
them again.

    seal({'token': ...})   the text to store
    open(text)             the dict again, or None when it cannot be read
"""
import base64
import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app

PURPOSE = 'crm-channel-secrets'


def _box():
    raw = hashlib.sha256(('%s:%s' % (PURPOSE, current_app.config['SECRET_KEY'])).encode('utf-8')).digest()
    return Fernet(base64.urlsafe_b64encode(raw))


def seal(values):
    return _box().encrypt(json.dumps(values or {}).encode('utf-8')).decode('ascii')


def open(text):          # noqa: A001 -- the box's own word, used as secretbox.open()
    if not text:
        return {}
    try:
        out = json.loads(_box().decrypt(str(text).encode('ascii')).decode('utf-8'))
    except (InvalidToken, ValueError, TypeError, UnicodeError):
        return None
    return out if isinstance(out, dict) else None
