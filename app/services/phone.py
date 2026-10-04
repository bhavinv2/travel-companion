"""Phone numbers: one list of dialling codes, one way to check one, used everywhere.

Every form on this site that asks for a phone number -- sign-up, the help popup, the contact
page, the Sahayak booking, the admin screens -- used a bare <input type="tel"> with a hint in
the placeholder. So people typed "9848000000" with no country, "0091 98480 00000", or a number
with the wrong country code, and nothing noticed until somebody tried to ring it.

The rules live here rather than in each form:

  * the country is CHOSEN, not guessed from what was typed. A leading 0 means different things
    in different countries, and a number with no code at all cannot be dialled from abroad.
  * what is stored is E.164 -- plus, country code, national number, no spaces -- because that is
    what tel: links, wa.me and every SMS provider want.
  * what is shown is what the person typed, lightly tidied, because that is what they recognise.

The list is the one the insurance bundle already shipped, so a dialling code is the same value
on both sides of the app.
"""
import re

# (ISO 3166-1 alpha-2, country name, dialling code)
COUNTRIES = [
    ('AF', 'Afghanistan', '93'),
    ('AL', 'Albania', '355'),
    ('DZ', 'Algeria', '213'),
    ('AR', 'Argentina', '54'),
    ('AM', 'Armenia', '374'),
    ('AU', 'Australia', '61'),
    ('AT', 'Austria', '43'),
    ('AZ', 'Azerbaijan', '994'),
    ('BH', 'Bahrain', '973'),
    ('BD', 'Bangladesh', '880'),
    ('BY', 'Belarus', '375'),
    ('BE', 'Belgium', '32'),
    ('BT', 'Bhutan', '975'),
    ('BO', 'Bolivia', '591'),
    ('BA', 'Bosnia and Herzegovina', '387'),
    ('BW', 'Botswana', '267'),
    ('BR', 'Brazil', '55'),
    ('BN', 'Brunei', '673'),
    ('BG', 'Bulgaria', '359'),
    ('KH', 'Cambodia', '855'),
    ('CM', 'Cameroon', '237'),
    ('CA', 'Canada', '1'),
    ('CL', 'Chile', '56'),
    ('CN', 'China', '86'),
    ('CO', 'Colombia', '57'),
    ('CR', 'Costa Rica', '506'),
    ('HR', 'Croatia', '385'),
    ('CU', 'Cuba', '53'),
    ('CY', 'Cyprus', '357'),
    ('CZ', 'Czechia', '420'),
    ('DK', 'Denmark', '45'),
    ('DO', 'Dominican Republic', '1'),
    ('EC', 'Ecuador', '593'),
    ('EG', 'Egypt', '20'),
    ('SV', 'El Salvador', '503'),
    ('EE', 'Estonia', '372'),
    ('ET', 'Ethiopia', '251'),
    ('FJ', 'Fiji', '679'),
    ('FI', 'Finland', '358'),
    ('FR', 'France', '33'),
    ('GE', 'Georgia', '995'),
    ('DE', 'Germany', '49'),
    ('GH', 'Ghana', '233'),
    ('GR', 'Greece', '30'),
    ('GT', 'Guatemala', '502'),
    ('HN', 'Honduras', '504'),
    ('HK', 'Hong Kong', '852'),
    ('HU', 'Hungary', '36'),
    ('IS', 'Iceland', '354'),
    ('IN', 'India', '91'),
    ('ID', 'Indonesia', '62'),
    ('IR', 'Iran', '98'),
    ('IQ', 'Iraq', '964'),
    ('IE', 'Ireland', '353'),
    ('IL', 'Israel', '972'),
    ('IT', 'Italy', '39'),
    ('JM', 'Jamaica', '1'),
    ('JP', 'Japan', '81'),
    ('JO', 'Jordan', '962'),
    ('KZ', 'Kazakhstan', '7'),
    ('KE', 'Kenya', '254'),
    ('KW', 'Kuwait', '965'),
    ('KG', 'Kyrgyzstan', '996'),
    ('LA', 'Laos', '856'),
    ('LV', 'Latvia', '371'),
    ('LB', 'Lebanon', '961'),
    ('LY', 'Libya', '218'),
    ('LT', 'Lithuania', '370'),
    ('LU', 'Luxembourg', '352'),
    ('MO', 'Macao', '853'),
    ('MG', 'Madagascar', '261'),
    ('MY', 'Malaysia', '60'),
    ('MV', 'Maldives', '960'),
    ('MT', 'Malta', '356'),
    ('MU', 'Mauritius', '230'),
    ('MX', 'Mexico', '52'),
    ('MD', 'Moldova', '373'),
    ('MC', 'Monaco', '377'),
    ('MN', 'Mongolia', '976'),
    ('ME', 'Montenegro', '382'),
    ('MA', 'Morocco', '212'),
    ('MZ', 'Mozambique', '258'),
    ('MM', 'Myanmar', '95'),
    ('NA', 'Namibia', '264'),
    ('NP', 'Nepal', '977'),
    ('NL', 'Netherlands', '31'),
    ('NZ', 'New Zealand', '64'),
    ('NI', 'Nicaragua', '505'),
    ('NG', 'Nigeria', '234'),
    ('MK', 'North Macedonia', '389'),
    ('NO', 'Norway', '47'),
    ('OM', 'Oman', '968'),
    ('PK', 'Pakistan', '92'),
    ('PA', 'Panama', '507'),
    ('PG', 'Papua New Guinea', '675'),
    ('PY', 'Paraguay', '595'),
    ('PE', 'Peru', '51'),
    ('PH', 'Philippines', '63'),
    ('PL', 'Poland', '48'),
    ('PT', 'Portugal', '351'),
    ('QA', 'Qatar', '974'),
    ('RO', 'Romania', '40'),
    ('RU', 'Russia', '7'),
    ('RW', 'Rwanda', '250'),
    ('SA', 'Saudi Arabia', '966'),
    ('SN', 'Senegal', '221'),
    ('RS', 'Serbia', '381'),
    ('SC', 'Seychelles', '248'),
    ('SG', 'Singapore', '65'),
    ('SK', 'Slovakia', '421'),
    ('SI', 'Slovenia', '386'),
    ('ZA', 'South Africa', '27'),
    ('KR', 'South Korea', '82'),
    ('ES', 'Spain', '34'),
    ('LK', 'Sri Lanka', '94'),
    ('SE', 'Sweden', '46'),
    ('CH', 'Switzerland', '41'),
    ('TW', 'Taiwan', '886'),
    ('TZ', 'Tanzania', '255'),
    ('TH', 'Thailand', '66'),
    ('TN', 'Tunisia', '216'),
    ('TR', 'Turkey', '90'),
    ('TM', 'Turkmenistan', '993'),
    ('UG', 'Uganda', '256'),
    ('UA', 'Ukraine', '380'),
    ('AE', 'United Arab Emirates', '971'),
    ('GB', 'United Kingdom', '44'),
    ('US', 'United States', '1'),
    ('UY', 'Uruguay', '598'),
    ('UZ', 'Uzbekistan', '998'),
    ('VN', 'Vietnam', '84'),
    ('YE', 'Yemen', '967'),
    ('ZM', 'Zambia', '260'),
    ('ZW', 'Zimbabwe', '263'),
]

# Most of our visitors are in these. They sit at the top of the picker; the rest follow in
# alphabetical order. US first because that is where most of the people filling these in are --
# the parents are in India, the person asking about them usually is not.
POPULAR = ['US', 'IN', 'CA', 'GB', 'AU', 'AE', 'SG', 'NZ']

BY_ISO = {iso: {'iso': iso, 'name': name, 'dial': dial} for iso, name, dial in COUNTRIES}
# What a form offers before anybody chooses, and how a number typed with no code is read.
DEFAULT_ISO = 'US'

# A national number is 4-14 digits; with the code, E.164 allows at most 15.
_DIGITS = re.compile(r'[^0-9]')
MIN_NATIONAL = 6
MAX_E164 = 15


def choices():
    """The picker's options: the common ones first, then everything else by name."""
    popular = [BY_ISO[i] for i in POPULAR if i in BY_ISO]
    rest = sorted((c for c in BY_ISO.values() if c['iso'] not in set(POPULAR)),
                  key=lambda c: c['name'])
    return popular, rest


def label(iso):
    c = BY_ISO.get((iso or '').upper())
    return '%s +%s' % (c['name'], c['dial']) if c else ''


def flag(iso):
    """The country's flag, from its two letters. '' when they are not two letters.

    A regional-indicator pair, which is what the glyph is made of. Windows has no flag font and
    draws the two letters instead, so this is for places where that still reads -- never beside
    text that already names the country.
    """
    iso = (iso or '').upper()
    if len(iso) != 2 or not iso.isalpha():
        return ''
    return ''.join(chr(0x1F1E6 + ord(ch) - ord('A')) for ch in iso)


# How a number is written down, by dialling code. Deliberately short: a grouping guessed at
# for a country reads worse than leaving what somebody typed, so anything not here keeps its
# own spelling.
_GROUPS = {
    '1': lambda n: '+1 (%s) %s-%s' % (n[:3], n[3:6], n[6:]) if len(n) == 10 else '',
    '91': lambda n: '+91 %s %s' % (n[:5], n[5:]) if len(n) == 10 else '',
    '971': lambda n: '+971 %s %s %s' % (n[:2], n[2:5], n[5:]) if len(n) == 9 else '',
}

# The empty field's placeholder, for the countries whose shape we know. Fictional ranges on
# purpose, so a placeholder is never mistaken for a number worth ringing. static/js/
# phone-field.js carries the same three and swaps between them when the country changes; this
# copy is only what the first paint shows, before any script has run.
_EXAMPLES = {'1': '(555) 123-4567', '91': '98480 00000', '971': '50 123 4567'}


def example(iso=None):
    """What to put in an empty phone box for that country, or '' where the shape is unknown."""
    c = BY_ISO.get((iso or DEFAULT_ISO).upper())
    return _EXAMPLES.get(c['dial'], '') if c else ''


# Every dialling code we know, longest first, for splitting one off the front of a number.
_CODES_BY_LEN = sorted({d for _, _, d in COUNTRIES}, key=len, reverse=True)


def split_dial(e164):
    """(dialling code, the rest) for a stored number, or ('', digits) if we cannot tell.

    Codes overlap -- 1 is the USA and Canada, 7 is Russia and Kazakhstan -- so this cannot say
    which country a number belongs to. It does not need to: the question here is only where
    the code ends, and the longest match answers that.
    """
    d = _DIGITS.sub('', e164 or '')
    for code in _CODES_BY_LEN:
        if d.startswith(code) and len(d) > len(code):
            return code, d[len(code):]
    return '', d


def pretty(e164, fallback=''):
    """A stored number as that country writes it, spaced so the country code is findable.

    +1 (647) 770-2288 and +1 917 900 5094 are the same shape typed by two different people, and
    on a page that lists them one under the other that reads as a mistake. The display is
    derived from E.164 so every number is spelled the same way whoever entered it.

    A country whose grouping is not in _GROUPS still gets a space after its dialling code.
    "+46764498115" is a Swedish mobile, but nothing in it says where the 46 stops -- somebody
    reading a list of these cannot tell the country without counting digits against a table.
    A number a human has already spaced is left exactly as they wrote it.
    """
    d = _DIGITS.sub('', e164 or '')
    if not d:
        return fallback
    for code in sorted(_GROUPS, key=len, reverse=True):
        if d.startswith(code):
            out = _GROUPS[code](d[len(code):])
            if out:
                return out
            break
    if fallback and ' ' in fallback.strip():
        return fallback
    code, rest = split_dial(d)
    return '+%s %s' % (code, rest) if code else '+' + d


def normalise(number, iso=DEFAULT_ISO):
    """(e164, error). e164 is '+<code><national>' with no spaces, or '' when `number` is blank.

    An empty number is not an error: most of these fields are optional, and the caller decides
    whether a missing one matters.
    """
    raw = (number or '').strip()
    if not raw:
        return '', None

    country = BY_ISO.get((iso or '').upper()) or BY_ISO[DEFAULT_ISO]
    dial = country['dial']

    if raw.startswith('+'):
        digits = _DIGITS.sub('', raw)
    else:
        digits = _DIGITS.sub('', raw)
        # 00 is how much of the world writes +
        if digits.startswith('00'):
            digits = digits[2:]
        elif digits.startswith(dial) and len(digits) > len(dial) + MIN_NATIONAL - 1:
            pass                      # they typed the code without the plus
        else:
            # a single leading 0 is a national trunk prefix and is dropped, not dialled
            digits = dial + digits.lstrip('0')

    if not digits:
        return '', 'Enter a phone number.'
    if len(digits) > MAX_E164:
        return '', 'That number has too many digits to be dialled.'

    known = sorted({c['dial'] for c in BY_ISO.values()}, key=len, reverse=True)
    code = next((d for d in known if digits.startswith(d)), '')
    if not code:
        return '', 'That number does not start with a country dialling code.'
    if len(digits) - len(code) < MIN_NATIONAL:
        return '', 'That number looks too short. Check the digits after the country code.'
    return '+' + digits, None


def is_valid(number, iso=DEFAULT_ISO):
    e164, error = normalise(number, iso)
    return bool(e164) and error is None


def digits(number, iso=DEFAULT_ISO):
    """Just the digits, for wa.me and tel: -- '' when the number is unusable."""
    e164, error = normalise(number, iso)
    return e164.lstrip('+') if e164 and not error else ''


def iso_for(e164):
    """Best guess at the country of a stored number, for redrawing the picker."""
    d = _DIGITS.sub('', e164 or '')
    if not d:
        return DEFAULT_ISO
    for iso in POPULAR:                       # prefer ours where codes collide (+1, +7)
        if d.startswith(BY_ISO[iso]['dial']):
            return iso
    best = ''
    for c in BY_ISO.values():
        if d.startswith(c['dial']) and len(c['dial']) > len(best):
            best, found = c['dial'], c['iso']
    return found if best else DEFAULT_ISO
