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

# How long the national number is, for countries where it is fixed. Used for one decision only:
# whether digits that BEGIN with the country's own code are that code typed without the plus, or
# a national number that happens to start with those digits. Prefix and a minimum length cannot
# tell them apart -- "91234 56789" is an ordinary Indian mobile, and was stored as +9123456789,
# the 91 eaten as the country code. Length can: ten digits is the number, twelve is code+number.
# Only fixed-length plans are listed; anywhere else the old rule stands.
_NATIONAL_LEN = {
    '1': 10,     # US, Canada and the rest of the North American plan
    '91': 10,    # India
    '971': 9,    # UAE mobiles
    '966': 9,    # Saudi Arabia
    '65': 8,     # Singapore -- "6512 3456" is a landline, not +65 123456
    '974': 8, '965': 8, '973': 8, '968': 8,   # Qatar, Kuwait, Bahrain, Oman
    '44': 10,    # UK, without its trunk 0
    '61': 9,     # Australia, without its trunk 0
    '852': 8,    # Hong Kong
}
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
    if not (e164 or '').strip().startswith('+'):
        # No + means no country is known -- a row saved before numbers were normalised, as bare
        # national digits. Formatting it would invent one: "9175551234" printed as "+91 75551234",
        # India, for what may well be a US number. Shown as stored, the not-knowing stays visible.
        return (fallback or e164 or '').strip()
    for code in sorted(_GROUPS, key=len, reverse=True):
        if d.startswith(code):
            out = _GROUPS[code](d[len(code):])
            if out:
                return out
            break
    # Somebody's own spacing is kept for a country we have no grouping rule for -- a London number
    # reads "20 7946 0958", and a guess would print something no Briton recognises. But only when
    # it carries the country code: "076 449 8115" for a Swedish number was shown exactly so, and
    # the whole point of the spacing is that the code can be found.
    if fallback and ' ' in fallback.strip() and fallback.strip().startswith('+'):
        return fallback.strip()
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
    # "(0)" is how a number written for both audiences marks its trunk 0: dialled at home, dropped
    # from abroad -- "+44 (0)20 7946 0958". Kept, it made an undialable +440207946...
    raw = raw.replace('(0)', ' ')

    country = BY_ISO.get((iso or '').upper()) or BY_ISO[DEFAULT_ISO]
    dial = country['dial']

    if raw.startswith('+'):
        digits = _DIGITS.sub('', raw)
    else:
        digits = _DIGITS.sub('', raw)
        # 00 is how much of the world writes +
        national_len = _NATIONAL_LEN.get(dial)
        if digits.startswith('00'):
            digits = digits[2:]
        elif dial == '1' and digits.startswith('011') and len(digits) > 3 + MIN_NATIONAL:
            # 011 is how the US and Canada dial out, the way most of the world uses 00. Only for
            # +1: in India 011 is Delhi's area code, and "011 2345 6789" is a Delhi number.
            digits = digits[3:]
        elif national_len and len(digits.lstrip('0')) == national_len:
            # exactly a national number's length: it IS the national number, even when its
            # first digits match the country code (see _NATIONAL_LEN)
            digits = dial + digits.lstrip('0')
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


_PHONEISH = re.compile(r'[\d\s()+.\-]+')


def search_digits(q):
    """The digits to look for when a search box is given something shaped like a phone number,
    else ''. "+91 98765 43210", "(214) 555-0101" and "0091 98765 43210" all qualify; "Ravi" and
    "ravi@x.com" do not. Leading zeros -- an 00 international prefix or a national trunk 0 -- are
    dropped, because the stored E.164 has neither. Fewer than six digits is not a phone search."""
    q = (q or '').strip()
    if not q or not _PHONEISH.fullmatch(q):
        return ''
    d = _DIGITS.sub('', q).lstrip('0')
    return d if len(d) >= MIN_NATIONAL else ''


def search_condition(column, q):
    """A SQL condition: `column` holds the phone number `q` describes, or None if q is not one.

    The screens show numbers spaced ("+91 98765 43210") and store them without spaces, so a
    number copied off the page and pasted into a search box used to find nothing. Both sides
    are compared as bare digits; rows saved before numbers were normalised, spaced or bracketed,
    are found too.
    """
    d = search_digits(q)
    if not d:
        return None
    from sqlalchemy import func
    expr = column
    for ch in (' ', '-', '(', ')', '.', '+'):
        expr = func.replace(expr, ch, '')
    return expr.like('%' + d + '%')


def matches(column, q):
    """`column` ILIKE %q% -- or, when q is shaped like a phone number, the same digits however
    either side is spaced. The drop-in for a search box that also searches phone numbers."""
    from sqlalchemy import or_
    like = column.ilike('%' + (q or '').strip() + '%')
    digits = search_condition(column, q)
    return like if digits is None else or_(like, digits)


# How many digits follow the country code, for the countries where that is fixed enough to check.
# Stricter than normalise(), which takes any six or more: a form a family fills in to have somebody
# ring them back is better told "that is one digit short" than handed a number nobody can dial.
# Ranges where a country really has two lengths -- UAE landlines are 8 and mobiles 9, UK numbers
# 9 or 10 -- so a correct number is never refused.
NATIONAL_RANGE = {
    '1': (10, 10), '91': (10, 10), '971': (8, 9), '966': (9, 9), '65': (8, 8),
    '974': (8, 8), '965': (8, 8), '973': (8, 8), '968': (8, 8), '44': (9, 10),
    '61': (9, 9), '852': (8, 8),
}


def length_error(e164):
    """A plain-words complaint when a normalised number has the wrong number of digits for its
    country, or None. Only for the countries in NATIONAL_RANGE; elsewhere normalise() decides."""
    code, national = split_dial(e164 or '')
    if not code:
        return None
    low, high = NATIONAL_RANGE.get(code, (None, None))
    if low is None or low <= len(national) <= high:
        return None
    want = str(low) if low == high else '%d or %d' % (low, high)
    country = next((c['name'] for c in BY_ISO.values() if c['dial'] == code and c['iso'] in POPULAR), None) \
        or next((c['name'] for c in BY_ISO.values() if c['dial'] == code), 'that country')
    return 'A number in %s has %s digits after +%s -- this one has %d.' % (country, want, code, len(national))


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
