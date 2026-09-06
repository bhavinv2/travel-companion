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
