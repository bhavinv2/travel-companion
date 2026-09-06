"""Read an uploaded e-ticket and pull out the trip details the post form needs.

Digital airline e-tickets are PDFs with a real text layer, so pypdf gets us the words without OCR.
Photos and screenshots have no text layer; we say so plainly rather than guessing, and the caller
falls back to manual entry with the file still attached.

Everything returned is a *suggestion*: the form is pre-filled but every field stays editable, because
ticket layouts vary wildly between airlines and a confident wrong answer is worse than an empty box.
"""
import io
import re
from datetime import date, datetime

MAX_PAGES = 6          # e-tickets put the itinerary up front; don't chew through a 40-page bundle
MAX_CHARS = 40000

# "QR573", "QR 573", "6E 1425", "AI-101"
FLIGHT_RE = re.compile(r'\b([A-Z]{2}|[A-Z]\d|\d[A-Z])[\s\-]?(\d{1,4})\b')
# "HYD - DFW", "HYD to DFW", "HYD → DFW"
PAIR_RE = re.compile(r'\b([A-Z]{3})\b\s*(?:-|–|—|→|>|to|TO)\s*\b([A-Z]{3})\b')
CODE_RE = re.compile(r'\b([A-Z]{3})\b')

DATE_PATTERNS = [
    (re.compile(r'\b(\d{1,2})[\s\-/](Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s\-/](\d{2,4})\b', re.I),
     ('d', 'b', 'y')),
    (re.compile(r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s\-/](\d{1,2})[\s,\-/]+(\d{2,4})\b', re.I),
     ('b', 'd', 'y')),
    (re.compile(r'\b(\d{4})-(\d{2})-(\d{2})\b'), ('y', 'm', 'd')),
    (re.compile(r'\b(\d{1,2})/(\d{1,2})/(\d{4})\b'), ('d', 'm', 'y')),
]
MONTHS = {m: i + 1 for i, m in enumerate(
    ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'])}

# words that look like IATA codes but never are, so a stray match doesn't become an airport
STOPWORDS = {
    'PDF', 'THE', 'AND', 'FOR', 'YOU', 'ALL', 'NEW', 'ONE', 'TWO', 'PNR', 'GST', 'USD', 'INR', 'EUR',
    'GBP', 'TAX', 'FEE', 'SUB', 'TOT', 'ADT', 'CHD', 'INF', 'ETK', 'TKT', 'SEQ', 'REF', 'BAG', 'KGS',
    'MRS', 'MSR', 'DOB', 'ID', 'ETA', 'ETD', 'ARR', 'DEP', 'TER', 'GAT', 'SEA', 'ECO', 'BUS', 'FIR',
    'NON', 'PER', 'MAY', 'SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'AIR', 'FLT', 'NUM', 'QTY',
}


def _text_from_pdf(raw: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(raw))
    out = []
    for page in reader.pages[:MAX_PAGES]:
        try:
            out.append(page.extract_text() or '')
        except Exception:
            continue
        if sum(len(x) for x in out) > MAX_CHARS:
            break
    return '\n'.join(out)[:MAX_CHARS]


def _parse_dates(text):
    """Every date in the document, earliest first, ignoring anything already past."""
    found = set()
    today = date.today()
    for rx, order in DATE_PATTERNS:
        for m in rx.finditer(text):
            parts = dict(zip(order, m.groups()))
            try:
                y = int(parts['y']) if 'y' in parts else today.year
                if y < 100:
                    y += 2000
                mo = MONTHS[parts['b'][:3].lower()] if 'b' in parts else int(parts['m'])
                d = int(parts['d'])
                cand = date(y, mo, d)
            except (ValueError, KeyError):
                continue
            if today.replace(year=today.year - 1) <= cand <= today.replace(year=today.year + 2):
                found.add(cand)
    return sorted(x for x in found if x >= today) or sorted(found)


def _airport_sequence(text):
    """Every IATA code in the text, in order, keeping repeats — the repeats are what tell a
    connection (HYD DOH DOH DFW) apart from a return (BOM DXB DXB BOM)."""
    from app.services.locations import airport
    out = []
    for m in CODE_RE.finditer(text):
        code = m.group(1)
        if code in STOPWORDS:
            continue
        if airport(code):
            out.append(code)
    return out


def _route_from(sequence):
    """(origin, destination) for an itinerary. The destination is where the traveller ends up,
    not the first stop: a connection ends at the last airport, a return ends back home so the
    turnaround point is the real destination."""
    if len(sequence) < 2:
        return None, None
    origin = sequence[0]
    tail = [c for c in sequence if c != origin]
    if not tail:
        return None, None
    if sequence[-1] != origin:
        return origin, sequence[-1]          # one way, possibly with connections
    # returns to the origin: the destination is the stop it spends the journey reaching
    counts = {}
    for c in tail:
        counts[c] = counts.get(c, 0) + 1
    return origin, max(counts, key=lambda c: (counts[c], -tail.index(c)))


def _flight(text):
    """(airline_name, flight_number) from the first token whose prefix is a known airline."""
    from app.services import airlines
    for m in FLIGHT_RE.finditer(text):
        prefix, num = m.group(1), m.group(2)
        name = airlines.name_for(prefix)
        if name:
            return name, f'{prefix}{num}'
    return None, None


def parse_text(text: str) -> dict:
    """Pull trip fields out of already-extracted ticket text."""
    from app.services.locations import normalize_location
    fields, found = {}, []

    sequence = _airport_sequence(text)
    origin, dest = _route_from(sequence)
    if origin is None:
        # a bare "HYD - DFW" line with no other codes anywhere
        pair = PAIR_RE.search(text)
        if pair and pair.group(1) != pair.group(2):
            from app.services.locations import airport
            if airport(pair.group(1)) and airport(pair.group(2)):
                origin, dest = pair.group(1), pair.group(2)

    if origin and dest:
        o = normalize_location(origin)
        d = normalize_location(dest)
        if o and d and o['iata'] != d['iata']:
            fields['flying_from'] = o['display']
            fields['destination'] = d['display']
            found.append(f"route {o['iata']} to {d['iata']}")
            stops = [c for c in dict.fromkeys(sequence) if c not in (origin, dest)]
            if stops:
                found.append('via ' + ', '.join(stops))

    airline, flight_no = _flight(text)
    if airline:
        fields['airline'] = airline
        found.append(f'airline {airline}')
    if flight_no:
        fields['flight_number'] = flight_no
        found.append(f'flight {flight_no}')

    dates = _parse_dates(text)
    if dates:
        fields['from_date'] = dates[0].isoformat()
        found.append(f'departure {dates[0].isoformat()}')
        if len(dates) > 1 and dates[1] != dates[0]:
            fields['to_date'] = dates[1].isoformat()
            found.append(f'return {dates[1].isoformat()}')

    return {'fields': fields, 'found': found}


def parse_upload(fileobj, filename: str) -> dict:
    """Entry point for the route. Never raises: returns {ok, fields, found, message}."""
    name = (filename or '').lower()
    raw = fileobj.read()
    if not raw:
        return {'ok': False, 'fields': {}, 'found': [],
                'message': 'That file was empty. Please choose your e-ticket again.'}

    if name.endswith('.pdf'):
        try:
            text = _text_from_pdf(raw)
        except Exception:
            return {'ok': False, 'fields': {}, 'found': [],
                    'message': "We could not open that PDF. Fill the form in yourself and it will still be attached."}
        if len(text.strip()) < 40:
            return {'ok': False, 'fields': {}, 'found': [],
                    'message': ('That PDF looks like a scan rather than a text e-ticket, so there is nothing to read. '
                                'Fill the form in yourself — the file stays attached.')}
        result = parse_text(text)
        if not result['fields']:
            return {'ok': False, **result,
                    'message': ('We read the PDF but could not recognise the flight details. '
                                'Please fill them in — everything else is saved.')}
        return {'ok': True, **result,
                'message': 'Found ' + ', '.join(result['found']) + '. Check each field before posting.'}

    if name.endswith(('.png', '.jpg', '.jpeg', '.webp')):
        return {'ok': False, 'fields': {}, 'found': [],
                'message': ('Screenshots and photos have no text we can read. Upload the PDF e-ticket your airline '
                            'e-mailed you, or fill the form in yourself — the image stays attached either way.')}

    return {'ok': False, 'fields': {}, 'found': [],
            'message': 'Upload a PDF e-ticket, or a JPG/PNG image if that is all you have.'}
