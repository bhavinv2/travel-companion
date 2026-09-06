"""Airline reference data: the `airlines` DB table when seeded (base + custom), else the bundled JSON file."""
import json
import os

_PATH = os.path.join(os.path.dirname(__file__), '..', 'static', 'js', 'airlines.json')
_ALL = None
_BY_IATA = None
_LOADED_AT = 0.0
_CACHE_TTL = 60       # seconds; admin edits call reset_cache() in-process, other workers refresh on expiry


def _fetch():
    base, custom = [], []
    try:
        from app.models import Airline
        for a in Airline.query.all():
            (custom if a.is_custom else base).append(a.as_dict())
    except Exception:      # no app context / table not created yet
        pass
    if not base:           # unseeded table (e.g. tests): fall back to the bundled list
        try:
            with open(_PATH, encoding='utf-8') as f:
                base = [a for a in json.load(f) if a.get('iata')]
        except Exception:  # pragma: no cover
            base = []
    return base + custom


def _load():
    global _ALL, _BY_IATA, _LOADED_AT
    import time
    if _ALL is not None and time.time() - _LOADED_AT < _CACHE_TTL:
        return
    _ALL, _BY_IATA = [], {}
    for a in _fetch():
        iata = (a.get('iata') or '').upper()
        if not iata:
            continue
        _ALL.append(a)
        _BY_IATA.setdefault(iata, a)
    _LOADED_AT = time.time()


def all_airlines():
    """The full merged airline list (cached), for autocomplete and the admin screen."""
    _load()
    return _ALL


def airline(code):
    _load()
    return _BY_IATA.get((code or '').upper())


def name_for(code):
    a = airline(code)
    return a['name'] if a else None


def reset_cache():
    global _ALL, _BY_IATA, _LOADED_AT
    _ALL = _BY_IATA = None
    _LOADED_AT = 0.0
