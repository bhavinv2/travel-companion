"""Colour themes for the user-facing site, created and managed by admins.

A theme is six brand colours. Every other shade the CSS needs (hover states, tints, the
muted text colour, the hero washes) is derived from those six, so an admin cannot produce a
palette where a button hover is invisible or a tint clashes with its base.

Stored in app_settings under 'themes' as {'themes': [...], 'active': '<key>'} — the same
mechanism as options/messages/help_center, so there is no migration and a change is live
within the settings cache window.

The output is a block of CSS custom properties injected after the stylesheets in base.html,
overriding the :root defaults in style.css and the .landing block in landing.css.
"""
import re

SETTING_KEY = 'themes'
KEY_RE = re.compile(r'^[a-z0-9_]{1,40}$')
HEX_RE = re.compile(r'^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$')

# The six an admin actually chooses. Everything else is derived.
FIELDS = [
    ('primary', 'Primary', 'Buttons, links, active states, the hero accent.'),
    ('cta', 'Call to action', 'The one warm button — "Find companions".'),
    ('ink', 'Ink', 'Headings and body text; also the dark navbar and footer.'),
    ('surface', 'Surface', 'Page washes behind cards and the hero gradient.'),
    ('border', 'Border', 'Card outlines, dividers, input borders.'),
    ('success', 'Success', 'Confirmations, "connected" chips, positive badges.'),
]

DEFAULT_THEMES = [
    {'key': 'desi_blue', 'name': 'Desi Blue (default)',
     'colors': {'primary': '#2f80ed', 'cta': '#f0940a', 'ink': '#0f2340',
                'surface': '#f4f9ff', 'border': '#d7e6f6', 'success': '#199f7e'}},
    {'key': 'marigold', 'name': 'Marigold',
     'colors': {'primary': '#d97706', 'cta': '#2f80ed', 'ink': '#3b2a12',
                'surface': '#fdf8ef', 'border': '#ecdcc2', 'success': '#3f8f5b'}},
    {'key': 'indigo_night', 'name': 'Indigo Night',
     'colors': {'primary': '#5b53d6', 'cta': '#e0654f', 'ink': '#191a3a',
                'surface': '#f3f2fd', 'border': '#dcd9f4', 'success': '#2a9d8f'}},
    {'key': 'teal_monsoon', 'name': 'Teal Monsoon',
     'colors': {'primary': '#0d7c86', 'cta': '#ef8354', 'ink': '#10292c',
                'surface': '#eff8f8', 'border': '#cfe6e6', 'success': '#2f8f4e'}},
]
DEFAULT_ACTIVE = 'desi_blue'


# ---------------------------------------------------------------------------
# colour helpers
# ---------------------------------------------------------------------------

def _rgb(hex_):
    h = hex_.lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _hex(rgb):
    return '#%02x%02x%02x' % tuple(max(0, min(255, int(round(c)))) for c in rgb)


def mix(a, b, t):
    """t=0 gives a, t=1 gives b."""
    ra, rb = _rgb(a), _rgb(b)
    return _hex([ra[i] + (rb[i] - ra[i]) * t for i in range(3)])


def lighten(c, t):
    return mix(c, '#ffffff', t)


def darken(c, t):
    return mix(c, '#000000', t)


def _lum(c):
    def ch(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(x) for x in _rgb(c))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    """WCAG contrast ratio between two colours (1 = identical, 21 = black on white)."""
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return round((hi + 0.05) / (lo + 0.05), 2)


# ---------------------------------------------------------------------------
# storage
# ---------------------------------------------------------------------------

def _stored():
    try:
        from app.services import settings
        return settings.get_setting(SETTING_KEY, {}) or {}
    except Exception:           # pragma: no cover - table not created yet
        return {}


def themes():
    stored = _stored().get('themes')
    return [dict(t, colors=dict(t['colors'])) for t in (stored if stored is not None else DEFAULT_THEMES)]


def active_key():
    key = _stored().get('active') or DEFAULT_ACTIVE
    return key if any(t['key'] == key for t in themes()) else (themes()[0]['key'] if themes() else DEFAULT_ACTIVE)


def active_theme():
    key = active_key()
    return next((t for t in themes() if t['key'] == key), DEFAULT_THEMES[0])


def is_customised():
    return _stored().get('themes') is not None or _stored().get('active') is not None


# ---------------------------------------------------------------------------
# derivation -> CSS
# ---------------------------------------------------------------------------

def variables(theme) -> dict:
    """The full CSS custom-property map for a theme, derived from its six colours."""
    c = dict(DEFAULT_THEMES[0]['colors'])
    c.update(theme.get('colors') or {})
    p, cta, ink, surface, border, ok = (c['primary'], c['cta'], c['ink'],
                                        c['surface'], c['border'], c['success'])
    return {
        # global palette (style.css)
        '--coral': p,
        '--coral-dark': darken(p, .22),
        '--coral-light': lighten(p, .90),
        '--coral-dark-text': darken(p, .22),
        '--accent': p,
        '--accent-light': lighten(p, .90),
        '--gold': ok,
        '--gold-light': lighten(ok, .90),
        '--green': lighten(ok, .12),
        '--navy': ink,
        '--navy-light': lighten(ink, .12),
        '--text': ink,
        '--muted': lighten(ink, .38),
        '--bg': surface,
        '--border': border,
        '--shadow': f'0 4px 24px {_rgba(ink, .07)}',
        '--shadow-lg': f'0 14px 44px {_rgba(ink, .13)}',
        # landing hero (landing.css)
        '--l-ink': ink,
        '--l-blue': p,
        '--l-blue-dark': darken(p, .22),
        '--l-sky': lighten(p, .92),
        '--l-sky-2': lighten(p, .84),
        '--l-mint': lighten(ok, .90),
        '--l-cta': cta,
        '--l-cta-dark': darken(cta, .18),
        '--l-card-shadow': f'0 10px 30px {_rgba(ink, .08)}',
    }


def _rgba(hex_, alpha):
    r, g, b = _rgb(hex_)
    return f'rgba({r},{g},{b},{alpha})'


def css(theme=None) -> str:
    """A <style>-ready block. `.landing` repeats the vars because landing.css scopes its
    own set there, and a scoped declaration beats :root regardless of order."""
    v = variables(theme or active_theme())
    body = '\n'.join(f'  {k}: {val};' for k, val in v.items())
    return f':root {{\n{body}\n}}\n.landing {{\n{body}\n}}'


def warnings_for(theme) -> list:
    """Readability problems worth telling the admin about, rather than silently shipping."""
    c = dict(DEFAULT_THEMES[0]['colors'])
    c.update(theme.get('colors') or {})
    out = []
    if contrast(c['primary'], '#ffffff') < 3.0:
        out.append(f"Primary {c['primary']} on white is only {contrast(c['primary'], '#ffffff')}:1 — "
                   "white button text will be hard to read. Try a darker shade.")
    if contrast(c['cta'], '#ffffff') < 2.5:
        out.append(f"Call-to-action {c['cta']} is very light for a button with white text.")
    if contrast(c['ink'], c['surface']) < 7.0:
        out.append(f"Ink on surface is {contrast(c['ink'], c['surface'])}:1 — body text may look washed out.")
    if contrast(c['border'], '#ffffff') > 4.5:
        out.append("The border colour is dark enough to read as a heavy outline on white cards.")
    return out


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def _slug(text, fallback='theme'):
    s = re.sub(r'[^a-z0-9]+', '_', str(text or '').lower()).strip('_')[:40]
    return s or fallback


def clean(rows):
    """Validate admin input. Returns (themes, errors)."""
    out, errors, seen = [], [], set()
    for row in rows or []:
        name = str(row.get('name') or '').strip()
        if not name:
            continue                                   # blank name = deleted
        key = str(row.get('key') or '').strip() or _slug(name)
        if not KEY_RE.match(key):
            key = _slug(name)
        base, n = key, 2
        while key in seen:
            key, n = f'{base}_{n}', n + 1
        seen.add(key)
        colors, bad = {}, []
        for field, _label, _help in FIELDS:
            val = str(row.get(field) or '').strip()
            if not HEX_RE.match(val):
                bad.append(field)
                val = DEFAULT_THEMES[0]['colors'][field]
            colors[field] = val.lower()
        if bad:
            errors.append(f'"{name}": {", ".join(bad)} must be a hex colour like #2f80ed — kept the previous value.')
        out.append({'key': key, 'name': name[:60], 'colors': colors})
    if not out:
        errors.append('Keep at least one theme — the site needs a palette to render.')
    return out, errors


def save(rows, active=None, actor=None):
    from app.services import settings
    items, errors = clean(rows)
    if errors and not items:
        return False, errors
    keys = [t['key'] for t in items]
    chosen = active if active in keys else (active_key() if active_key() in keys else keys[0])
    settings.set_setting(SETTING_KEY, {'themes': items, 'active': chosen}, actor)
    settings.clear_cache()
    return True, errors          # non-fatal warnings still surface


def activate(key, actor=None):
    from app.services import settings
    if not any(t['key'] == key for t in themes()):
        return False
    settings.set_setting(SETTING_KEY, {'themes': themes(), 'active': key}, actor)
    settings.clear_cache()
    return True


def delete(key, actor=None):
    """Returns (ok, message). The last remaining theme cannot be deleted."""
    from app.services import settings
    items = [t for t in themes() if t['key'] != key]
    if len(items) == len(themes()):
        return False, 'That theme no longer exists.'
    if not items:
        return False, 'This is the only theme left — create another one before deleting it.'
    chosen = active_key() if active_key() in [t['key'] for t in items] else items[0]['key']
    settings.set_setting(SETTING_KEY, {'themes': items, 'active': chosen}, actor)
    settings.clear_cache()
    return True, 'Theme deleted.'


def reset(actor=None):
    from app.services import settings
    settings.set_setting(SETTING_KEY, {}, actor)
    settings.clear_cache()
