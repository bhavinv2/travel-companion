from app.services.locations import normalize_location
from app.services.contacts import detect_type, normalize_value, validate, parse_contact_rows


def test_normalize_location_from_display_string(app):
    loc = normalize_location('Hyderabad (HYD)')
    assert loc['iata'] == 'HYD'
    assert loc['metro'] == 'Hyderabad'


def test_normalize_location_from_iata_and_metro(app):
    assert normalize_location('dfw')['metro'] == 'Dallas'
    assert normalize_location('DAL')['metro'] == 'Dallas'      # same metro as DFW
    assert normalize_location('LGW')['metro'] == 'London'


def test_normalize_location_from_city_name(app):
    loc = normalize_location('London')
    assert loc is not None and loc['metro'] == 'London'


def test_normalize_location_aliases(app):
    assert normalize_location('RGIA')['iata'] == 'HYD'
    assert normalize_location('CHi')['metro'] == 'Chicago'
    assert normalize_location('New York')['metro'] == 'New York'


def test_normalize_location_unknown(app):
    assert normalize_location('Nowhere Special') is None
    assert normalize_location('') is None


def test_detect_contact_types():
    assert detect_type('ravi@example.com') == 'email'
    assert detect_type('+1 (214) 555-0100') == 'mobile'
    assert detect_type('https://facebook.com/ravi.k') == 'facebook'
    assert detect_type('@ravi_k') == 'instagram'
    assert detect_type('wa.me/12145550100') == 'whatsapp'
    assert detect_type('pigeon post') == 'other'


def test_normalize_contact_values():
    assert normalize_value('email', 'Ravi@Example.COM') == 'ravi@example.com'
    assert normalize_value('mobile', '+1 (214) 555-0100') == '+12145550100'
    assert normalize_value('mobile', '00 44 20 7946 0958') == '+442079460958'
    assert normalize_value('instagram', '@ravi_k') == 'https://instagram.com/ravi_k'
    assert normalize_value('facebook', 'facebook.com/ravi') == 'https://facebook.com/ravi'


def test_validate_contact_values():
    assert validate('email', 'not-an-email')[0] is False
    assert validate('mobile', '123')[0] is False
    assert validate('mobile', '+1 214 555 0100')[0] is True
    assert validate('inapp_chat', '')[0] is True
    assert validate('nonsense', 'x')[0] is False


def test_parse_contact_rows_from_json_detects_and_skips_blanks(app):
    rows, errors = parse_contact_rows([
        {'type': 'auto', 'value': 'ravi@example.com', 'consent': True},
        {'type': 'auto', 'value': '', 'label': 'blank row'},
        {'type': 'mobile', 'value': '12', 'consent': False},
    ])
    assert [r['type'] for r in rows] == ['email']
    assert rows[0]['consent'] is True
    assert len(errors) == 1 and '12' in errors[0]
