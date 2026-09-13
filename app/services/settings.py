"""Site-wide settings stored in the app_settings table (shared across gunicorn workers), with a short
per-process cache. Currently used for the notification switches."""
import copy
import time
from datetime import datetime

from app import db
from app.models import AppSetting, NOTIFY_CATEGORIES

_cache = {}
CACHE_SECONDS = 15

NOTIFY_KEY = 'notifications'
NOTIFY_DEFAULTS = {
    'enabled': True,                                   # master switch: False stops everything
    'channels': {'email': True, 'inapp': True},        # partial: by channel
    'categories': {c: True for c in NOTIFY_CATEGORIES},  # partial: by category
    'note': '',
}


def get_setting(key, default=None):
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and hit[0] > now:
        return hit[1]
    row = db.session.get(AppSetting, key)
    value = row.value if row is not None else default
    _cache[key] = (now + CACHE_SECONDS, value)
    return value


def set_setting(key, value, actor=None):
    row = db.session.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key)
        db.session.add(row)
    row.value = value
    row.updated_at = datetime.utcnow()
    row.updated_by_id = actor.id if actor else None
    db.session.commit()
    _cache.pop(key, None)
    return row


def clear_cache():
    _cache.clear()


def notification_switches() -> dict:
    """Stored switches merged over the defaults (unknown keys ignored, missing keys default to on)."""
    stored = get_setting(NOTIFY_KEY) or {}
    sw = copy.deepcopy(NOTIFY_DEFAULTS)
    if isinstance(stored, dict):
        if 'enabled' in stored:
            sw['enabled'] = bool(stored['enabled'])
        for ch in sw['channels']:
            if ch in (stored.get('channels') or {}):
                sw['channels'][ch] = bool(stored['channels'][ch])
        for cat in sw['categories']:
            if cat in (stored.get('categories') or {}):
                sw['categories'][cat] = bool(stored['categories'][cat])
        sw['note'] = str(stored.get('note') or '')[:500]
    return sw


def set_notification_switches(data: dict, actor=None) -> dict:
    sw = copy.deepcopy(NOTIFY_DEFAULTS)
    sw['enabled'] = bool(data.get('enabled', True))
    for ch in sw['channels']:
        sw['channels'][ch] = bool((data.get('channels') or {}).get(ch, True))
    for cat in sw['categories']:
        sw['categories'][cat] = bool((data.get('categories') or {}).get(cat, True))
    sw['note'] = str(data.get('note') or '')[:500]
    set_setting(NOTIFY_KEY, sw, actor)
    return sw


# ---------------------------------------------------------------------------
# Landing page: admin-configurable contact e-mail + brand colour palette
# ---------------------------------------------------------------------------
import re as _re

LANDING_KEY = 'landing'
# The landing template's :root palette. Keys are the CSS var names (minus the leading --).
LANDING_COLOR_DEFAULTS = {
    'navy': '#0F1F3D', 'navy-2': '#162B52', 'ink': '#1B2438', 'muted': '#5B6579',
    'amber': '#F5A623', 'amber-2': '#E8961A', 'sunset': '#E4632A', 'sky': '#7FB6FF',
    'sand': '#FFF6EA', 'line': '#E6E1D8',
}
LANDING_COLOR_LABELS = {
    'navy': 'Navy (headers, hero)', 'navy-2': 'Navy (hover)', 'ink': 'Body text', 'muted': 'Muted text',
    'amber': 'Amber (primary button)', 'amber-2': 'Amber (hover)', 'sunset': 'Sunset accent',
    'sky': 'Sky (logo accent)', 'sand': 'Sand (section background)', 'line': 'Hairlines / borders',
}
_HEX_RE = _re.compile(r'^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$')


def landing_settings() -> dict:
    """Effective landing settings with defaults filled in (colours always complete)."""
    stored = get_setting(LANDING_KEY, {}) or {}
    colors = dict(LANDING_COLOR_DEFAULTS)
    for k, v in (stored.get('colors') or {}).items():
        if k in LANDING_COLOR_DEFAULTS and isinstance(v, str) and _HEX_RE.match(v.strip()):
            colors[k] = v.strip()
    return {
        'contact_email': (stored.get('contact_email') or '').strip(),
        'contact_email_enabled': bool(stored.get('contact_email_enabled')),
        'colors': colors,
    }


def set_landing_settings(data: dict, actor=None) -> dict:
    cur = landing_settings()
    if 'contact_email' in data:
        cur['contact_email'] = (data.get('contact_email') or '').strip()[:255]
    if 'contact_email_enabled' in data:
        cur['contact_email_enabled'] = bool(data.get('contact_email_enabled'))
    if isinstance(data.get('colors'), dict):
        for k in LANDING_COLOR_DEFAULTS:
            v = (data['colors'].get(k) or '').strip()
            if v and _HEX_RE.match(v):
                cur['colors'][k] = v
    set_setting(LANDING_KEY, cur, actor)
    return cur
