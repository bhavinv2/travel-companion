"""The half-hour sound (static/js/check-sound.js, templates/_check_sound.html): at the start of every half hour a
sound on whatever staff page is open, to look at the inboxes and tick them on the half-hourly check.

Each person chooses for themselves, and it is kept with their notification preferences
(User.notify_prefs['check_sound']) so it follows them to any computer: on or off; every half hour or only between
two times on chosen days (India time, as the check); which sound and how loud; ringing again a few minutes later
when the inboxes are not all ticked; a desktop notice as well. A sound file of their own stays in that browser
(IndexedDB): it is never uploaded, so 'own' on another computer plays the chime until it is picked there too.
Only for people who may open the check (the 'crm_checks' page).
"""
import re

KEY = 'check_sound'
SOUNDS = (('chime', 'Chime'), ('bell', 'Bell'), ('dingdong', 'Ding-dong'), ('marimba', 'Marimba'),
          ('pop', 'Soft pop'), ('alarm', 'Alarm (loud)'), ('own', 'My own sound'))
AGAIN = (0, 5, 10, 15)                           # minutes after the half hour starts; 0: never
DAYS = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')
DEFAULTS = {'on': False, 'sound': 'chime', 'volume': 70, 'all_day': True, 'from': '09:00', 'to': '18:00',
            'days': [0, 1, 2, 3, 4, 5, 6], 'again': 0, 'notice': False}
_HM = re.compile(r'^([01]\d|2[0-3]):[0-5]\d$')


def of(user):
    """The person's settings, every key there (the defaults for what they never chose)."""
    got = dict((user.notify_prefs or {}).get(KEY) or {})
    out = dict(DEFAULTS)
    for k, v in got.items():
        if k in out:
            out[k] = v
    return out


def save(user, data):
    """Check and keep what the settings window sent; ValueError (in words for the person) for what cannot be."""
    s = of(user)
    if 'on' in data:
        s['on'] = bool(data['on'])
    if 'sound' in data:
        if data['sound'] not in dict(SOUNDS):
            raise ValueError('Choose one of the sounds.')
        s['sound'] = data['sound']
    if 'volume' in data:
        try:
            s['volume'] = max(5, min(100, int(data['volume'])))
        except (TypeError, ValueError):
            raise ValueError('The loudness is a number from 5 to 100.')
    if 'all_day' in data:
        s['all_day'] = bool(data['all_day'])
    for k in ('from', 'to'):
        if k in data:
            if not _HM.match(str(data[k] or '')):
                raise ValueError('Times are like 09:00.')
            s[k] = data[k]
    if not s['all_day'] and s['from'] == s['to']:
        raise ValueError('"From" and "to" are the same time: choose two times, or every half hour.')
    if 'days' in data:
        days = sorted({d for d in (data['days'] or []) if isinstance(d, int) and 0 <= d <= 6})
        if not days:
            raise ValueError('Choose at least one day.')
        s['days'] = days
    if 'again' in data:
        try:
            again = int(data['again'])
        except (TypeError, ValueError):
            again = -1
        if again not in AGAIN:
            raise ValueError('Ring again after 5, 10 or 15 minutes, or not at all.')
        s['again'] = again
    if 'notice' in data:
        s['notice'] = bool(data['notice'])
    # a new dict, so the JSON column is seen to change
    user.notify_prefs = {**(user.notify_prefs or {}), KEY: s}
    return s


def says(s):
    """The settings in a few words, for the header button's tip and the check page: "On · 09:00–18:00, Mon–Sat"."""
    if not s['on']:
        return 'Off'
    when = 'every half hour' if s['all_day'] else '%s–%s' % (s['from'], s['to'])
    days = s['days']
    if len(days) < 7:
        runs, start = [], days[0]
        for a, b in zip(days, days[1:] + [None]):
            if b != a + 1:
                runs.append(DAYS[start] if start == a else '%s–%s' % (DAYS[start], DAYS[a]))
                start = b
        when += ', ' + ', '.join(runs)
    return 'On · ' + when
