"""Two-step sign-in codes: the six digits an authenticator app (Google Authenticator, Microsoft Authenticator, Authy,
1Password ...) shows every 30 seconds -- RFC 6238 time-based one-time passwords, HMAC-SHA1, as every app expects.

    new_secret()            a fresh key, base32
    code(secret, at=None)   the code for that moment (tests and the set-up check use it)
    verify(secret, given)   the code typed is right now, or 30 seconds either side (a phone's clock drifts)
    uri(secret, account)    the otpauth:// address the QR code carries
    qr_svg(text)            that QR code as an inline SVG (segno; no picture leaves the server)
    new_backup_codes()      ten one-time codes for a lost phone: (plain, hashed)
"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

ISSUER = 'NRI Parent Service'
STEP = 30
DIGITS = 6
BACKUP_COUNT = 10


def new_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode('ascii').rstrip('=')


def _key(secret):
    s = (secret or '').strip().replace(' ', '').upper()
    return base64.b32decode(s + '=' * (-len(s) % 8))


def code(secret, at=None, step_offset=0):
    counter = int((time.time() if at is None else at) // STEP) + step_offset
    digest = hmac.new(_key(secret), struct.pack('>Q', counter), hashlib.sha1).digest()
    o = digest[-1] & 0x0F
    number = (struct.unpack('>I', digest[o:o + 4])[0] & 0x7FFFFFFF) % (10 ** DIGITS)
    return str(number).zfill(DIGITS)


def verify(secret, given, at=None, window=1):
    given = ''.join(ch for ch in str(given or '') if ch.isdigit())
    if not secret or len(given) != DIGITS:
        return False
    return any(hmac.compare_digest(code(secret, at, k), given) for k in range(-window, window + 1))


def uri(secret, account):
    label = quote('%s:%s' % (ISSUER, account))
    return 'otpauth://totp/%s?secret=%s&issuer=%s&digits=%d&period=%d' % (label, secret, quote(ISSUER), DIGITS, STEP)


def qr_svg(text):
    import segno
    return segno.make(text, error='m').svg_inline(scale=5, border=2, dark='#0f2340')


def _norm(c):
    return ''.join(ch for ch in str(c or '').lower() if ch.isalnum())


def new_backup_codes():
    """([plain codes to show once], [their hashes to keep]) -- "xxxx-xxxx", lower-case letters and digits."""
    from werkzeug.security import generate_password_hash
    alphabet = 'abcdefghjkmnpqrstuvwxyz23456789'
    plain = ['%s-%s' % (''.join(secrets.choice(alphabet) for _ in range(4)),
                        ''.join(secrets.choice(alphabet) for _ in range(4))) for _ in range(BACKUP_COUNT)]
    return plain, [generate_password_hash(_norm(p)) for p in plain]


def use_backup_code(hashes, given):
    """(matched, the hashes left): a backup code works once."""
    from werkzeug.security import check_password_hash
    g = _norm(given)
    if len(g) != 8:
        return False, list(hashes or [])
    left = list(hashes or [])
    for h in left:
        if check_password_hash(h, g):
            left.remove(h)
            return True, left
    return False, left
