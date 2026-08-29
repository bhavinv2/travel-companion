"""Normalise free-text locations ("Hyderabad (HYD)", "HYD", "Dallas") to IATA / city / metro."""
import json
import os
import re

_AIRPORTS_PATH = os.path.join(os.path.dirname(__file__), '..', 'static', 'js', 'airports.json')
_BY_IATA = None
_BY_CITY = None

# Airports that should match each other when a traveller is flexible about the airport.
# Falls back to the city name for anything not listed, so same-city airports still group.
METRO = {
    'LHR': 'London', 'LGW': 'London', 'STN': 'London', 'LTN': 'London', 'LCY': 'London', 'SEN': 'London',
    'JFK': 'New York', 'EWR': 'New York', 'LGA': 'New York',
    'DFW': 'Dallas', 'DAL': 'Dallas',
    'IAH': 'Houston', 'HOU': 'Houston',
    'ORD': 'Chicago', 'MDW': 'Chicago',
    'SFO': 'San Francisco Bay Area', 'OAK': 'San Francisco Bay Area', 'SJC': 'San Francisco Bay Area',
    'LAX': 'Los Angeles', 'BUR': 'Los Angeles', 'LGB': 'Los Angeles', 'SNA': 'Los Angeles', 'ONT': 'Los Angeles',
    'IAD': 'Washington DC', 'DCA': 'Washington DC', 'BWI': 'Washington DC',
    'MIA': 'Miami', 'FLL': 'Miami',
    'YYZ': 'Toronto', 'YTZ': 'Toronto', 'YHM': 'Toronto',
    'CDG': 'Paris', 'ORY': 'Paris',
    'DXB': 'Dubai', 'DWC': 'Dubai',
    'MEL': 'Melbourne', 'AVV': 'Melbourne',
    'DEL': 'Delhi', 'BOM': 'Mumbai', 'BLR': 'Bengaluru', 'HYD': 'Hyderabad',
    'MAA': 'Chennai', 'CCU': 'Kolkata', 'COK': 'Kochi', 'AMD': 'Ahmedabad',
}

_IATA_IN_PARENS = re.compile(r'\(([A-Za-z]{3})\)\s*$')

# Colloquial / non-IATA codes people actually type in Facebook posts and forum listings.
ALIASES = {
    'RGIA': 'HYD',   # Rajiv Gandhi International Airport, Hyderabad
    'CHI': 'ORD', 'CHICAGO': 'ORD',
    'NYC': 'JFK', 'NEW YORK': 'JFK', 'NY': 'JFK',
    'LON': 'LHR', 'LONDON': 'LHR',
    'VJY': 'VGA',    # Vijayawada
    'BANGALORE': 'BLR', 'BENGALURU': 'BLR', 'BOMBAY': 'BOM', 'MADRAS': 'MAA', 'CALCUTTA': 'CCU',
    'DALLAS': 'DFW', 'HOUSTON': 'IAH', 'SF': 'SFO', 'BAY AREA': 'SFO', 'LA': 'LAX', 'DC': 'IAD',
    'WASHINGTON': 'IAD', 'TORONTO': 'YYZ', 'DUBAI': 'DXB', 'MELBOURNE': 'MEL', 'SYDNEY': 'SYD',
}


def _load():
    global _BY_IATA, _BY_CITY
    if _BY_IATA is not None:
        return
    _BY_IATA, _BY_CITY = {}, {}
    try:
        with open(_AIRPORTS_PATH, encoding='utf-8') as f:
            for a in json.load(f):
                iata = (a.get('iata') or '').upper()
                if not iata:
                    continue
                _BY_IATA[iata] = a
                city = (a.get('city') or '').strip().lower()
                if city:
                    _BY_CITY.setdefault(city, []).append(a)
    except Exception:  # pragma: no cover - file missing in some test setups
        pass


def airport(iata):
    _load()
    return _BY_IATA.get((iata or '').upper())


def normalize_location(text):
    """Return {'iata','city','country','metro','display'} or None if unrecognised."""
    _load()
    if not text:
        return None
    text = text.strip()
    a = None
    m = _IATA_IN_PARENS.search(text)
    if m:
        a = _BY_IATA.get(m.group(1).upper())
    if a is None and len(text) == 3 and text.isalpha():
        a = _BY_IATA.get(text.upper())
    if a is None and text.upper() in ALIASES:
        a = _BY_IATA.get(ALIASES[text.upper()])
    if a is None:
        candidates = _BY_CITY.get(text.lower(), [])
        if candidates:
            # Prefer a known metro airport (usually the main one), otherwise the first.
            a = next((c for c in candidates if c['iata'] in METRO), candidates[0])
    if a is None:
        return None
    iata = a['iata'].upper()
    city = a.get('city') or a.get('name')
    return {
        'iata': iata,
        'city': city,
        'country': a.get('country'),
        'metro': METRO.get(iata, city),
        'display': f"{city} ({iata})",
    }


def apply_route(trip, origin_text=None, dest_text=None):
    """Populate the normalised route columns on a CompanionRequest in place."""
    o = normalize_location(origin_text if origin_text is not None else trip.flying_from)
    d = normalize_location(dest_text if dest_text is not None else trip.destination)
    trip.origin_iata = o['iata'] if o else None
    trip.origin_city = o['city'] if o else None
    trip.origin_metro = o['metro'] if o else None
    trip.dest_iata = d['iata'] if d else None
    trip.dest_city = d['city'] if d else None
    trip.dest_metro = d['metro'] if d else None
    return o, d
