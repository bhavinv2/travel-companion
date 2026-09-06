"""Option lists for the forms.

Built-in defaults live here; admins change them at /admin/options (stored in app_settings, key "options").
Read lists through get_list(name) - or attribute access such as options.LANGUAGES - so a change made in the
admin screen is visible everywhere within seconds, without a deploy.
"""
import re
from flask import has_app_context

DEFAULT_ON_BEHALF_OF = [
    ('myself', 'Myself'), ('loved_one', 'Loved Ones'), ('mother', 'Mother'), ('father', 'Father'),
    ('parents', 'Parents'), ('sister', 'Sister'), ('brother', 'Brother'), ('son', 'Son'),
    ('daughter', 'Daughter'), ('friend', 'Friend'), ('other', 'Other'),
]

DEFAULT_CONNECT_ME_TO = [
    ('senior_citizens', 'Senior Citizens'), ('travelling_families', 'Travelling Families'),
    ('solo_male', 'Solo (Male)'), ('solo_female', 'Solo (Female)'),
    ('student', 'Student Travellers'), ('tourist', 'Tourists'),
    ('business', 'Business Travel'), ('religious', 'Religious Travel'),
]

DEFAULT_TRAVELLER_NEEDS = [
    ('wheelchair', 'Wheelchair Assistance'), ('toddler', 'Travelling with Toddler'),
    ('first_time', 'First-time Flyer'), ('immigration', 'Help at Immigration / Customs'),
    ('connections', 'Help with Connecting Flights'), ('language_barrier', 'Language Barrier'),
    ('physically_challenged', 'Physically Challenged'), ('mentally_challenged', 'Mentally Challenged'),
    ('medicines', 'Need Medicines / Medical Support'), ('documents', 'Need Documents / Forms Help'),
]

DEFAULT_LANGUAGES = [
    'English', 'Hindi', 'Gujarati', 'Tamil', 'Telugu', 'Kannada', 'Malayalam', 'Marathi',
    'Punjabi', 'Bengali', 'Urdu', 'Sindhi', 'Nepali', 'Sinhala',
]

DEFAULT_CATEGORIES = [
    'Family visit', 'Student travel', 'Medical travel', 'Business', 'Pilgrimage', 'Tourism', 'Relocation', 'Other',
]

ROLE_LEVELS = ('user', 'cs', 'admin')      # what a role may do: traveller screens / CS console / everything
ROLE_LEVEL_LABELS = {'user': 'Traveller screens', 'cs': 'CS console', 'admin': 'Admin panel (everything)'}
DEFAULT_USER_ROLES = [
    {'key': 'user', 'label': 'Traveller', 'level': 'user', 'builtin': True},
    {'key': 'cs', 'label': 'Customer service', 'level': 'cs', 'builtin': True},
    {'key': 'admin', 'label': 'Administrator', 'level': 'admin', 'builtin': True},
]
BUILTIN_ROLE_LEVELS = {r['key']: r['level'] for r in DEFAULT_USER_ROLES}

LANG_MODES = ('babel', 'google')
DEFAULT_SITE_LANGUAGES = [
    {'code': 'en', 'label': 'EN', 'mode': 'babel', 'builtin': True},
    {'code': 'hi', 'label': 'हिंदी', 'mode': 'babel'},
    {'code': 'te', 'label': 'తెలుగు', 'mode': 'babel'},
    {'code': 'ta', 'label': 'தமிழ்', 'mode': 'google'},
    {'code': 'gu', 'label': 'ગુજરાતી', 'mode': 'google'},
    {'code': 'kn', 'label': 'ಕನ್ನಡ', 'mode': 'google'},
    {'code': 'ml', 'label': 'മലയാളം', 'mode': 'google'},
    {'code': 'mr', 'label': 'मराठी', 'mode': 'google'},
    {'code': 'pa', 'label': 'ਪੰਜਾਬੀ', 'mode': 'google'},
    {'code': 'bn', 'label': 'বাংলা', 'mode': 'google'},
    {'code': 'ur', 'label': 'اردو', 'mode': 'google'},
]

# spoken-language name <-> UI language code, used to keep the two language lists in sync
LANGUAGE_CODE_BY_NAME = {
    'english': 'en', 'hindi': 'hi', 'telugu': 'te', 'tamil': 'ta', 'gujarati': 'gu', 'kannada': 'kn',
    'malayalam': 'ml', 'marathi': 'mr', 'punjabi': 'pa', 'bengali': 'bn', 'urdu': 'ur', 'sindhi': 'sd',
    'nepali': 'ne', 'sinhala': 'si', 'odia': 'or', 'oriya': 'or', 'assamese': 'as', 'konkani': 'gom',
    'kashmiri': 'ks', 'bhojpuri': 'bho', 'maithili': 'mai', 'french': 'fr', 'spanish': 'es',
    'german': 'de', 'arabic': 'ar', 'portuguese': 'pt', 'dutch': 'nl', 'italian': 'it',
}
LANGUAGE_NAME_BY_CODE = {}
for _n, _c in LANGUAGE_CODE_BY_NAME.items():
    LANGUAGE_NAME_BY_CODE.setdefault(_c, _n.title())
NATIVE_LABEL_BY_CODE = {
    'en': 'EN', 'hi': 'हिंदी', 'te': 'తెలుగు', 'ta': 'தமிழ்', 'gu': 'ગુજરાતી', 'kn': 'ಕನ್ನಡ',
    'ml': 'മലയാളം', 'mr': 'मराठी', 'pa': 'ਪੰਜਾਬੀ', 'bn': 'বাংলা', 'ur': 'اردو', 'sd': 'سنڌي',
    'ne': 'नेपाली', 'si': 'සිංහල', 'or': 'ଓଡ଼ିଆ', 'as': 'অসমীয়া', 'gom': 'कोंकणी',
}


def sync_language_lists(changed, actor=None):
    """Additive sync between the spoken 'Languages' list and 'Site languages'.

    Adding a language on either tab adds its counterpart on the other (site side arrives as
    'Google Translate only'); nothing is ever removed automatically. Returns the name of the
    other list when it was updated, else None."""
    spoken = get_list('languages')
    site = get_list('site_languages')
    if changed == 'languages':
        site_codes = {l['code'] for l in site}
        add = []
        for name in spoken:
            code = LANGUAGE_CODE_BY_NAME.get(str(name).strip().lower())
            if code and code not in site_codes:
                add.append({'code': code, 'label': NATIVE_LABEL_BY_CODE.get(code, str(name)), 'mode': 'google'})
        if add:
            set_list('site_languages', [dict(l) for l in site] + add, actor)
            return 'site_languages'
        return None
    spoken_lower = {str(s).lower() for s in spoken}
    add = []
    for l in site:
        name = 'English' if l['code'] == 'en' else LANGUAGE_NAME_BY_CODE.get(l['code'])
        if name and name.lower() not in spoken_lower:
            add.append(name)
    if add:
        set_list('languages', list(spoken) + add, actor)
        return 'languages'
    return None


SETTING_KEY = 'options'
_KEY_RE = re.compile(r'^[a-z0-9_]{1,40}$')

LISTS = {
    'languages': {
        'title': 'Spoken languages', 'kind': 'values', 'default': DEFAULT_LANGUAGES,
        'help': 'Preferred-language checkboxes on the post form, the CS form, the dashboard filter and the importer. '
                'Kept in sync with the site languages below: adding one here adds it there too (as Google Translate).',
        'columns': [{'key': 'value', 'label': 'Language'}],
    },
    'categories': {
        'title': 'Post categories', 'kind': 'values', 'default': DEFAULT_CATEGORIES,
        'help': 'The optional "Category" dropdown on the public post form and the CS form.',
        'columns': [{'key': 'value', 'label': 'Category'}],
    },
    'on_behalf_of': {
        'title': 'Posting for (on behalf of)', 'kind': 'pairs', 'default': DEFAULT_ON_BEHALF_OF,
        'help': 'Who the traveller is posting for. The key is stored on the post; the label is what people see.',
        'columns': [{'key': 'key', 'label': 'Key (stored)'}, {'key': 'label', 'label': 'Label (shown)'}],
    },
    'connect_me_to': {
        'title': 'Connect me to', 'kind': 'pairs', 'default': DEFAULT_CONNECT_ME_TO,
        'help': 'Kinds of travellers a person would like to be connected with.',
        'columns': [{'key': 'key', 'label': 'Key (stored)'}, {'key': 'label', 'label': 'Label (shown)'}],
    },
    'traveller_needs': {
        'title': 'Traveller needs', 'kind': 'pairs', 'default': DEFAULT_TRAVELLER_NEEDS,
        'help': 'Assistance checkboxes (also recognised by the Excel importer and the scraper mapping).',
        'columns': [{'key': 'key', 'label': 'Key (stored)'}, {'key': 'label', 'label': 'Label (shown)'}],
    },
    'roles': {
        'title': 'User roles', 'kind': 'roles', 'default': DEFAULT_USER_ROLES,
        'help': 'Roles an account can hold (an account may hold several). The access level decides what a role '
                'may open: traveller screens, the CS console, or the admin panel. The three built-in roles cannot '
                'be removed or re-levelled.',
        'columns': [{'key': 'key', 'label': 'Role key'}, {'key': 'label', 'label': 'Label'},
                    {'key': 'level', 'label': 'Access level', 'type': 'select', 'choices': list(ROLE_LEVELS)}],
    },
    'site_languages': {
        'title': 'Site languages', 'kind': 'langs', 'default': DEFAULT_SITE_LANGUAGES,
        'help': 'Languages offered in the header selector. "Curated" languages use the reviewed translations '
                'shipped with the app (Google Translate still fills any string we have not translated yet); '
                '"Google Translate only" languages are translated entirely by the widget. English cannot be removed.',
        'columns': [{'key': 'code', 'label': 'Code'}, {'key': 'label', 'label': 'Label (native script)'},
                    {'key': 'mode', 'label': 'Translation', 'type': 'select', 'choices': list(LANG_MODES)}],
    },
}


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def _stored():
    if not has_app_context():
        return {}
    try:
        from app.services import settings
        return settings.get_setting(SETTING_KEY, {}) or {}
    except Exception:          # pragma: no cover - e.g. table not created yet
        return {}


def get_list(name):
    """The effective list for `name` (customised value if the admins saved one, else the built-in default)."""
    spec = LISTS[name]
    stored = _stored().get(name)
    raw = stored if stored is not None else spec['default']
    if spec['kind'] == 'pairs':
        return [tuple(x) for x in raw]          # JSON turns tuples into lists
    if spec['kind'] in ('roles', 'airports', 'airlines', 'langs'):
        return [dict(x) for x in raw]
    return list(raw)


def is_customised(name):
    return _stored().get(name) is not None


def labels(name):
    return dict(get_list(name))


def rows(name):
    """The list as editable row dicts for the admin screen."""
    kind = LISTS[name]['kind']
    items = get_list(name)
    if kind == 'values':
        return [{'value': v} for v in items]
    if kind == 'pairs':
        return [{'key': k, 'label': l} for k, l in items]
    return items


def role_defs():
    return get_list('roles')


def role_level(key):
    """Access level of a role key; unknown / removed roles fall back to plain traveller access."""
    for r in role_defs():
        if r['key'] == key:
            return r['level'] if r['level'] in ROLE_LEVELS else 'user'
    return BUILTIN_ROLE_LEVELS.get(key, 'user')


def role_labels():
    return {r['key']: r['label'] for r in role_defs()}


# ---------------------------------------------------------------------------
# Writing (admin screen)
# ---------------------------------------------------------------------------

def slug(text):
    return re.sub(r'[^a-z0-9]+', '_', str(text or '').strip().lower()).strip('_')[:40]


def _s(row, key, default=''):
    v = row.get(key, default) if isinstance(row, dict) else default
    return str(v if v is not None else '').strip()


def validate(name, items):
    """Normalise rows coming from the admin screen into the stored form; raise ValueError on bad input."""
    spec = LISTS[name]
    kind = spec['kind']
    items = list(items or [])
    out, seen = [], set()

    if kind == 'values':
        for row in items:
            v = _s(row, 'value') if isinstance(row, dict) else str(row or '').strip()
            if not v:
                continue
            if len(v) > 60:
                raise ValueError(f'"{v[:20]}..." is too long (max 60 characters)')
            if v.lower() in seen:
                raise ValueError(f'Duplicate value "{v}"')
            seen.add(v.lower())
            out.append(v)
        if not out:
            raise ValueError('The list cannot be empty')
        return out

    if kind == 'pairs':
        for row in items:
            if isinstance(row, (list, tuple)):
                row = {'key': row[0], 'label': row[1] if len(row) > 1 else row[0]}
            label = _s(row, 'label')
            key = slug(_s(row, 'key') or label)
            if not label and not key:
                continue
            if not label:
                raise ValueError(f'Label missing for key "{key}"')
            if not _KEY_RE.match(key):
                raise ValueError(f'Key "{key}" must be lowercase letters, digits or _')
            if key in seen:
                raise ValueError(f'Duplicate key "{key}"')
            seen.add(key)
            out.append([key, label[:80]])
        if not out:
            raise ValueError('The list cannot be empty')
        return out

    if kind == 'roles':
        for row in items:
            label = _s(row, 'label')
            key = slug(_s(row, 'key') or label)
            if not key and not label:
                continue
            level = _s(row, 'level') or 'user'
            if key in BUILTIN_ROLE_LEVELS:
                level = BUILTIN_ROLE_LEVELS[key]           # built-ins keep their level
            if not _KEY_RE.match(key):
                raise ValueError(f'Role key "{key}" must be lowercase letters, digits or _')
            if level not in ROLE_LEVELS:
                raise ValueError(f'Unknown access level "{level}" for role "{key}"')
            if key in seen:
                raise ValueError(f'Duplicate role "{key}"')
            seen.add(key)
            out.append({'key': key, 'label': (label or key.replace('_', ' ').title())[:60], 'level': level,
                        'builtin': key in BUILTIN_ROLE_LEVELS})
        for r in DEFAULT_USER_ROLES:                       # built-ins can never be removed
            if r['key'] not in seen:
                out.append(dict(r))
        out.sort(key=lambda r: (not r['builtin'], ROLE_LEVELS.index(r['level']), r['key']))
        return out


    if kind == 'langs':
        code_re = re.compile(r'^[a-z]{2,3}$')
        for row in items:
            code = _s(row, 'code').lower()
            label = _s(row, 'label')
            mode = _s(row, 'mode') or 'google'
            if not code and not label:
                continue
            if not code_re.match(code):
                raise ValueError(f'"{code or "?"}" is not a valid ISO language code (2-3 lowercase letters)')
            if mode not in LANG_MODES:
                raise ValueError(f'Unknown translation mode "{mode}" for {code}')
            if code in seen:
                raise ValueError(f'Duplicate language "{code}"')
            seen.add(code)
            out.append({'code': code, 'label': (label or code.upper())[:40],
                        'mode': 'babel' if code == 'en' else mode, 'builtin': code == 'en'})
        if 'en' not in seen:
            out.insert(0, {'code': 'en', 'label': 'EN', 'mode': 'babel', 'builtin': True})
        return out

    raise ValueError(f'Unknown list kind {kind}')      # pragma: no cover


def set_list(name, items, actor=None):
    from app.services import settings
    clean = validate(name, items)
    data = dict(_stored())
    data[name] = clean
    settings.set_setting(SETTING_KEY, data, actor)
    return clean


def reset_list(name, actor=None):
    from app.services import settings
    data = dict(_stored())
    data.pop(name, None)
    settings.set_setting(SETTING_KEY, data, actor)
    return get_list(name)


# ---------------------------------------------------------------------------
# Legacy attribute access: options.LANGUAGES, options.ON_BEHALF_OF_LABELS, OPT.CATEGORIES in templates ...
# ---------------------------------------------------------------------------
_ATTRS = {'ON_BEHALF_OF': 'on_behalf_of', 'CONNECT_ME_TO': 'connect_me_to', 'TRAVELLER_NEEDS': 'traveller_needs',
          'LANGUAGES': 'languages', 'CATEGORIES': 'categories', 'SITE_LANGUAGES': 'site_languages'}


def __getattr__(name):
    if name in _ATTRS:
        return get_list(_ATTRS[name])
    if name.endswith('_LABELS') and name[:-7] in _ATTRS:
        return dict(get_list(_ATTRS[name[:-7]]))
    raise AttributeError(name)
