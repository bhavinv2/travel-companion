"""The time every staff screen shows: India (the default), a US zone, or UTC -- the clock switch in the header.

Storage stays UTC. The business day stays India time: a day's bounds, the half-hourly check's half hours, the
calendar's days and what "today" means are worked out in IST wherever they were. Only what a person READS moves:
the times printed beside things (a message, a tick, a task, when a lead came in) and the times typed into a
form (a task's due time), so what you type is what you see.

The choice is a cookie (`tz`), per browser, read once per request. US zones keep daylight saving by the US rule
(second Sunday of March to the first Sunday of November, at 2 a.m. local), worked out here rather than from a tz
database, which is not on every host this runs on (see app/__init__.py's |ist). India has no daylight saving.
"""
from datetime import datetime, timedelta

from flask import has_request_context, request

COOKIE = 'tz'
DEFAULT = 'IST'
# key: (name, standard offset in minutes, daylight-saving abbreviation or None, standard abbreviation)
ZONES = {
    'IST': ('India', 330, None, 'IST'),
    'ET': ('US Eastern', -300, 'EDT', 'EST'),
    'CT': ('US Central', -360, 'CDT', 'CST'),
    'MT': ('US Mountain', -420, 'MDT', 'MST'),
    'PT': ('US Pacific', -480, 'PDT', 'PST'),
    'UTC': ('UTC', 0, None, 'UTC'),
}


def key():
    """The zone this request shows times in."""
    if not has_request_context():
        return DEFAULT
    k = request.cookies.get(COOKIE) or DEFAULT
    return k if k in ZONES else DEFAULT


def _sunday(year, month, nth):
    first = datetime(year, month, 1)
    return first + timedelta(days=(6 - first.weekday()) % 7 + 7 * (nth - 1))


def _summer(utc, std_minutes):
    """Is the US on daylight saving at `utc` (a naive UTC datetime) in the zone `std_minutes` from UTC?"""
    std = timedelta(minutes=std_minutes)
    start = _sunday(utc.year, 3, 2) + timedelta(hours=2) - std                       # 2:00 standard time
    end = _sunday(utc.year, 11, 1) + timedelta(hours=2) - std - timedelta(hours=1)   # 2:00 daylight time
    return start <= utc < end


def offset(utc=None, zone=None):
    """The zone's distance from UTC at the moment `utc` (default now)."""
    name, std, dst, _abbr = ZONES[zone or key()]
    utc = utc or datetime.utcnow()
    return timedelta(minutes=std + (60 if dst and _summer(utc, std) else 0))


def label(utc=None, zone=None):
    """'IST', 'EDT' or 'EST', 'UTC' -- what the zone is called at that moment."""
    _name, std, dst, abbr = ZONES[zone or key()]
    utc = utc or datetime.utcnow()
    return dst if dst and _summer(utc, std) else abbr


def local(utc, zone=None):
    """A stored UTC datetime as the wall-clock time of the chosen zone (naive). None stays None."""
    if utc is None:
        return None
    return utc + offset(utc, zone)


def to_utc(wall, zone=None):
    """A wall-clock time typed in the chosen zone, as UTC: the inverse of local()."""
    if wall is None:
        return None
    guess = wall - offset(wall, zone)
    return wall - offset(guess, zone)


def fmt(utc, pattern='%d %b %Y, %H:%M', zone=None):
    """`utc` printed in the chosen zone; '' for None."""
    return local(utc, zone).strftime(pattern) if utc is not None else ''


def switcher(now=None):
    """The header's switch: {'key', 'short', 'zones': [{'key', 'name', 'label', 'now'}]}."""
    now = now or datetime.utcnow()
    k = key()
    return {'key': k, 'short': label(now, k),
            'zones': [{'key': z, 'name': ZONES[z][0], 'label': label(now, z), 'now': fmt(now, '%H:%M', z)}
                      for z in ZONES]}
