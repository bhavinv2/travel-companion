"""Bring what came before the CRM into it.

backfill()      the site's own past enquiries: insurance quotes, contact messages (and Sahayak
                applications), Sahayak bookings, and trip posts that have not flown yet. Each one
                is linked to its record, so running it twice adds nothing twice.
read_sheet()    the "Sales Process 1.5" workbook the team kept by hand. Its tabs are the stages
import_sheet()  (Cold Leads, Prospects, Pipeline, Customer Engagement, Prospect / Pipeline Fallout);
                every row becomes a lead in that stage with its messages (TC #1, CL #2, ...) on the
                timeline, its warmth (LS), its comment, and its next follow-up as a task.

The workbook is read as a stream: one tab expands to ~220 MB of XML, nearly all of it empty cells
a formula was dragged down a million rows. A tab is abandoned after a long run of rows with nobody
in them, so the whole file reads in seconds.

Nothing imported is messaged or announced: old leads arrive quietly (plan=False, notify=False),
and only a follow-up date the sheet itself set becomes a task.
"""
import re
import zipfile
from collections import Counter
from datetime import date, datetime, time, timedelta
import xml.etree.ElementTree as ET

from app import db
from app.models import (CrmLead, CrmPipeline, CrmStage, CrmTask, CrmTouchpoint, CONTACT_TOPICS)
from app.services import crm, crm_products

NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
RNS = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
IST = timedelta(hours=5, minutes=30)
TOPIC_PRODUCT = {'companion': 'TC', 'insurance': 'TI', 'sahayak': 'SH', 'general': 'GEN'}


def _linked(ref_type, ref_id):
    return db.session.query(CrmLead.id).filter_by(ref_type=ref_type, ref_id=ref_id).first() is not None


def _stage(pipe_key, stage_key):
    return (CrmStage.query.join(CrmPipeline, CrmPipeline.id == CrmStage.pipeline_id)
            .filter(CrmPipeline.key == pipe_key, CrmStage.key == stage_key).first())


def _sheet_stage(pipe, sheet):
    """The stage a tab's rows are in: the one SHEETS names for the pipelines the sheet knew, else the
    first stage whose "This stage means" fits the tab."""
    key = SHEETS.get(sheet, {}).get(pipe.key)
    if key:
        found = _stage(pipe.key, key)
        if found is not None:
            return found
    want = SHEET_MEANS.get(sheet)
    return next((s for s in pipe.stages if s.stage_means == want), None)


def _first_lost(pipe_key):
    p = CrmPipeline.query.filter_by(key=pipe_key).first()
    return next((s for s in p.stages if s.kind == 'lost'), None) if p else None


# ============================================================================================ site

DNC = object()          # capture() refused somebody on the do-not-contact list


def backfill(days=180, now=None):
    """The site's enquiries of the last `days` days as leads. Returns a Counter of what happened.

    Open, still-useful ones (a trip or cover that has not started; anything from the last 30
    days) get their first follow-up planned. Older ones arrive marked "expired lead" with nothing
    planned, and a quote or booking whose date has passed arrives as fallen out, dated then --
    so the numbers for this month are not swollen by last spring.
    """
    from app.models import CompanionRequest, ContactMessage, InsuranceQuote, SahayakBooking
    crm.ensure_defaults()
    now = now or datetime.utcnow()
    since = now - timedelta(days=days)
    fresh = now - timedelta(days=30)
    today = date.today()
    out = Counter()

    def cap(fn, *args, **kw):
        """An import never brings back somebody who asked to be erased."""
        try:
            return fn(*args, refuse_dnc=True, **kw)
        except crm.DoNotContact:
            return DNC

    def done(lead, key):
        if lead is DNC:
            out['do not contact'] += 1
        else:
            out[key if lead else 'unreachable'] += 1

    for q in (InsuranceQuote.query.filter(InsuranceQuote.created_at >= since)
              .order_by(InsuranceQuote.created_at)):
        if _linked('insurance_quotes', q.id):
            out['already'] += 1
            continue
        past = q.start_date and q.start_date < today
        ages = ', '.join(str(t.get('age')) for t in (q.travellers or []) if isinstance(t, dict))
        lead = cap(
            crm.capture, 'ti-quote', phone=q.phone, email=q.email, product='TI', user_id=q.user_id,
            departure_date=q.start_date, ends_on=q.end_date, ref=('insurance_quotes', q.id),
            when=q.created_at, utm={}, plan=not past, notify=False, sync=False, imported=True,
            start_stage=_first_lost('ti-standard') if past else None,
            fallout_reason='Trip date passed' if past else None,
            details={'plan': q.insurance_type, 'travellers_ages': ages, 'citizenship': q.citizenship,
                     'destination': q.destination, 'quote': q.status})
        if lead is not None and lead is not DNC and past:
            lead.closed_at = datetime.combine(q.start_date, time(0))
        done(lead, 'insurance quotes')

    for m in (ContactMessage.query.filter(ContactMessage.created_at >= since)
              .order_by(ContactMessage.created_at)):
        if _linked('contact_messages', m.id):
            out['already'] += 1
            continue
        text = m.message or ''
        if text.startswith('Newsletter signup'):
            key = 'newsletter'
        elif text.startswith('Sahayak application'):
            key = 'sh-apply'
        elif text.startswith('Support request from the /travel-insurance'):
            key = 'ti-support'
        elif text.startswith('Travel insurance enquiry from the /travel-insurance'):
            key = 'ti-expert'
        else:
            key = 'contact-%s' % (m.topic if m.topic in CONTACT_TOPICS else 'general')
        old = m.created_at and m.created_at < fresh
        lead = cap(crm.capture, key, name=m.name, phone=m.phone, email=m.email,
                           product=TOPIC_PRODUCT.get(m.topic), message=text, user_id=m.user_id,
                           ref=('contact_messages', m.id), when=m.created_at, utm={},
                           plan=not old, notify=False, sync=False, imported=True,
                           temperature='EL' if old else None)
        done(lead, 'contact messages')

    stage_for = {'new': 'new', 'assigned': 'assigned', 'completed': 'done', 'cancelled': 'cancelled'}
    for b in (SahayakBooking.query.filter(SahayakBooking.created_at >= since)
              .order_by(SahayakBooking.created_at)):
        if _linked('sahayak_bookings', b.id):
            out['already'] += 1
            continue
        st = _stage('sahayak-visit', stage_for.get(b.status, 'new'))
        lead = cap(crm.capture, 'sh-booking', name=b.contact_name or b.patient_name, phone=b.phone, email=b.email,
                           product='SH', ref=('sahayak_bookings', b.id), user_id=b.user_id,
                           when=b.created_at, utm={}, start_stage=st, notify=False, sync=False, imported=True,
                           plan=b.status == 'new' and b.created_at >= fresh,
                           fallout_reason='Cancelled' if b.status == 'cancelled' else None,
                           details={'service': b.service_name, 'for': b.patient_name, 'age': b.patient_age,
                                    'pin_code': b.pincode, 'address': b.address})
        done(lead, 'sahayak bookings')

    for t in (CompanionRequest.query.filter(CompanionRequest.created_at >= since,
                                            CompanionRequest.from_date >= today,
                                            CompanionRequest.status.in_(('open', 'unconfirmed')))
              .order_by(CompanionRequest.created_at)):
        if _linked('companion_requests', t.id):
            out['already'] += 1
            continue
        key = 'tc-import' if t.import_key else ('tc-cs-post' if t.created_by_id and not t.user_id else 'tc-trip-post')
        lead = cap(crm.capture_trip, t, key, when=t.created_at, utm={}, notify=False, sync=False, imported=True)
        done(lead, 'trip posts')
    db.session.commit()
    return out


# ============================================================================================ the sheet

# tab -> the stage its rows are in, per pipeline
SHEETS = {
    'Cold Leads': {'ti-standard': 'cold', 'tc-companion': 'posted', 'general': 'new', 'sahayak-visit': 'new'},
    'Prospects': {'ti-standard': 'prospect', 'tc-companion': 'in_touch', 'general': 'talking',
                  'sahayak-visit': 'confirmed'},
    'Pipeline': {'ti-standard': 'pipeline', 'tc-companion': 'matched', 'general': 'talking',
                 'sahayak-visit': 'assigned'},
    'Customer Engagement': {'ti-standard': 'customer', 'tc-companion': 'connected', 'general': 'resolved',
                            'sahayak-visit': 'done'},
    'Pipeline Fallout': {'ti-standard': 'pipeline_fallout', 'tc-companion': 'closed', 'general': 'closed',
                         'sahayak-visit': 'cancelled'},
    'Prospect Fallout': {'ti-standard': 'prospect_fallout', 'tc-companion': 'closed', 'general': 'closed',
                         'sahayak-visit': 'cancelled'},
}
# tab -> "This stage means", for a pipeline the SHEETS map does not know (one made on screen)
SHEET_MEANS = {'Cold Leads': 'new', 'Prospects': 'talking', 'Pipeline': 'quoted',
               'Customer Engagement': 'won', 'Pipeline Fallout': 'lost', 'Prospect Fallout': 'lost'}
DEFAULT_PRODUCT = {'Cold Leads': 'TC', 'Prospects': 'TC'}           # the others are insurance
ENQ_PRODUCT = {'TC': 'TC', 'TI': 'TI', 'TC+TI': 'TI', 'TC+TI+VC': 'TI', 'VC': 'VC', 'GH': 'GH',
               'S': 'SH', 'H+': 'GEN', 'ENQ.': 'GEN'}
# the sheet's "S" column (List tab): where the lead came from
# (the lead sources' list: services/crm_sources; "reference" is split by the person's number when it is filed)
SOURCE_CODES = {'I': 'meta', 'FB': 'meta', 'F B': 'meta', 'IW': 'wa-india', 'W': 'wa-india',
                'UW': 'wa-usa', 'U W': 'wa-usa', 'T': 'tawk', 'IC': 'company-call', 'UC': 'usa-call', 'R': 'reference',
                'REF': 'reference', 'F&F': 'reference', 'TM': 'other', 'EM': 'other', 'A': 'web-other',
                'D': 'other', 'S': 'import-other'}
RELATION = {'M': 'Mother', 'F': 'Father', 'S': 'Sister', 'B': 'Brother', 'SL': 'Sister-in-law',
            'BL': 'Brother-in-law', 'N': 'Niece / nephew', 'MS': 'Themselves', 'K': 'Kids'}
TEMPS = {'L', 'R', 'U', 'Z', 'DL', 'EL'}
MESSAGE_CODES = re.compile(r'^(TC|TI|CL|PI|PF|CE)\s*#\s*\d+|^(FM|F M|BW|CM|ER|HJ|SA|CS|OM|PM)$', re.I)
EMAIL = re.compile(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+')
URL = re.compile(r'https?://\S+|(?:www\.)?(?:instagram|facebook)\.com/\S+', re.I)
STOP_AFTER = 400        # empty-ish rows in a row before a tab is given up


def excel_date(v):
    """An Excel day number (46304) or a d/m/y string as a date; None for anything else."""
    if v is None:
        return None
    s = str(v).strip()
    try:
        n = float(s)
        if 40000 < n < 60000:
            return date(1899, 12, 30) + timedelta(days=int(n))
        return None
    except ValueError:
        pass
    m = re.fullmatch(r'(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})', s)
    if m:
        d, mo, y = (int(x) for x in m.groups())
        y = y + 2000 if y < 100 else y
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    return None


def parse_phone(text):
    """The first phone number in a messy cell: 1.804.497.6837, 1 (408) 593-6794, 91 91368 99093."""
    from app.services import phone as phone_svc
    for part in re.split(r'[,;/|\n]+', str(text or '')):
        if '@' in part or 'http' in part.lower() or '.com/' in part.lower():
            continue
        digits = re.sub(r'\D', '', part)
        if not 10 <= len(digits) <= 15:
            continue
        tries = []
        if part.strip().startswith('+') or len(digits) > 10:
            tries.append('+' + digits)
        if len(digits) == 10:
            tries.append('+91' + digits if digits[0] in '6789' else '+1' + digits)
        for t in tries:
            e164, err = phone_svc.normalise(t, 'US')
            if not err:
                return e164
    return None


HANDLE = re.compile(r'@?([A-Za-z0-9_.]{3,30})')


def parse_contacts(*cells, hint=None):
    """(phone, email, [(kind, handle)], leftover text) from the contact cells of a row.

    `hint` is the row's source code (I = Instagram, FB = Facebook): with it, or with the word
    "instagram" / "facebook" in the cell, a bare handle such as "priya_r · Instagram" is kept as
    that handle rather than lost as text."""
    text = ' , '.join(str(c) for c in cells if c)
    email = next(iter(EMAIL.findall(text)), None)
    idents = []
    for u in URL.findall(text):
        kind = 'instagram' if 'instagram.com' in u.lower() else 'facebook' if 'facebook.com' in u.lower() else None
        if kind:
            idents.append((kind, u))
    rest = URL.sub(' ', EMAIL.sub(' ', text))
    phone = parse_phone(rest)
    low, hint = rest.lower(), (hint or '').upper().replace(' ', '')
    kind = ('instagram' if 'instagram' in low or 'insta' in low or hint == 'I' else
            'facebook' if 'facebook' in low or hint == 'FB' else None)
    if kind and not idents and not phone:
        for tok in re.split(r'[\s,·|/]+', rest):
            m = HANDLE.fullmatch(tok.strip())
            if m and not m.group(1).isdigit() and m.group(1).lower() not in ('instagram', 'insta', 'facebook', 'fb', 'id'):
                idents.append((kind, m.group(1)))
                break
    return phone, email, idents, re.sub(r'[\s,]+', ' ', rest).strip()


def _rows(z, path, shared, styles=None):
    """Each row of a sheet as (row number, {column letter: text}, {column letter: colour}), streamed.
    The colour is the cell's fill, or 'font:<rgb>' when only its text is coloured."""
    col = re.compile(r'([A-Z]+)(\d+)')
    for _, el in ET.iterparse(z.open(path)):
        if el.tag != NS + 'row':
            continue
        cells, colours, rownum = {}, {}, None
        for c in el.iter(NS + 'c'):
            m = col.match(c.get('r') or '')
            if not m:
                continue
            rownum = rownum or int(m.group(2))
            v = c.find(NS + 'v')
            t = c.get('t')
            val = None
            if t == 's' and v is not None:
                val = shared[int(v.text)]
            elif t == 'inlineStr':
                val = ''.join(x.text or '' for x in c.iter(NS + 't'))
            elif v is not None:
                val = v.text
            if val not in (None, ''):
                cells[m.group(1)] = str(val).strip()
            if styles and c.get('s'):
                colour = styles(int(c.get('s')))
                if colour:
                    colours[m.group(1)] = colour
        if rownum is None and el.get('r'):
            rownum = int(el.get('r'))
        el.clear()
        yield rownum, cells, colours


def _styles(z):
    """style index -> 'FFRRGGBB' fill, or 'font:FFRRGGBB' for coloured text, or None."""
    if 'xl/styles.xml' not in z.namelist():
        return None
    st = ET.parse(z.open('xl/styles.xml')).getroot()

    def rgb(node):
        return node.get('rgb') if node is not None else None
    fills = []
    for f in (st.find(NS + 'fills') or []):
        pf = f.find(NS + 'patternFill')
        fills.append(rgb(pf.find(NS + 'fgColor')) if pf is not None and pf.get('patternType') not in (None, 'none') else None)
    fonts = [rgb(f.find(NS + 'color')) for f in (st.find(NS + 'fonts') or [])]
    xfs = [(int(x.get('fillId', 0)), int(x.get('fontId', 0))) for x in (st.find(NS + 'cellXfs') or [])]

    def colour(i):
        if i >= len(xfs):
            return None
        fi, fo = xfs[i]
        # compared on RRGGBB: Excel writes FF in front, other tools 00
        fill = (fills[fi] if fi < len(fills) else None) or ''
        if len(fill) >= 6 and fill[-6:].upper() not in ('FFFFFF', '000000'):
            return fill[-6:].upper()
        font = (fonts[fo] if fo < len(fonts) else None) or ''
        if font[-6:].upper() == 'FF0000':
            return 'font:FF0000'
        return None
    return colour


# the row's colour in the sheet -> how ready they are to buy
GREENS = {'92D050', '00B050', '00FF00', 'C6EFCE', 'A9D08E'}
YELLOWS = {'FFFF00', 'FFC000', 'FFE699', 'FFEB9C', 'F4B084'}


def likelihood_from(colour):
    if not colour:
        return None
    if colour in GREENS:
        return 'hot'
    if colour in YELLOWS:
        return 'warm'
    if colour == 'font:FF0000' or colour in ('FF0000', 'C00000'):
        return 'cold'
    return None


COMMENT_NOISE = re.compile(r'\[Threaded comment\].*?Comment:\s*', re.S)


def _comments(z, sheet_path):
    """{'B26': text} for the cell comments of one sheet -- where the team kept the conversation
    ("9/14 - will get back tomorrow ... 20/9 sent PF#1") and the parents' medical conditions."""
    rels_path = sheet_path.replace('worksheets/', 'worksheets/_rels/') + '.rels'
    if rels_path not in z.namelist():
        return {}
    out = {}
    for r in ET.parse(z.open(rels_path)).getroot():
        target = r.get('Target') or ''
        if 'comments' not in target:
            continue
        path = 'xl/' + target.replace('../', '').lstrip('/').replace('xl/', '')
        if path not in z.namelist():
            continue
        for cm in ET.parse(z.open(path)).getroot().iter(NS + 'comment'):
            text = ''.join(t.text or '' for t in cm.iter(NS + 't')).strip()
            text = COMMENT_NOISE.sub('', text).strip()
            if text:
                out[cm.get('ref')] = text[:4000]
    return out


KPI_TABS = ('KPI', 'HB KPI', 'AP KPI', 'HK KPI')


def read_sheet(path_or_file):
    """Every lead row of the workbook: [{'sheet', 'ref', 'name', 'phone', 'email', 'identities', ...}],
    a per-tab Counter, and the KPI tabs' days {'KPI': [(day, metric, n)], 'HB KPI': [...]}. Reads only."""
    from app.services import crm_kpi
    z = zipfile.ZipFile(path_or_file)
    shared = []
    if 'xl/sharedStrings.xml' in z.namelist():
        for _, el in ET.iterparse(z.open('xl/sharedStrings.xml')):
            if el.tag == NS + 'si':
                shared.append(''.join(t.text or '' for t in el.iter(NS + 't')))
                el.clear()
    styles = _styles(z)
    wb = ET.parse(z.open('xl/workbook.xml')).getroot()
    rels = ET.parse(z.open('xl/_rels/workbook.xml.rels')).getroot()
    target = {r.get('Id'): r.get('Target') for r in rels}
    out, stats, kpi = [], {}, {}
    for idx, s in enumerate(wb.iter(NS + 'sheet')):
        name = (s.get('name') or '').strip()
        path = 'xl/' + target[s.get(RNS + 'id')].lstrip('/').replace('xl/', '')
        if name in KPI_TABS:
            rows = []
            for _, cells, _ in _rows(z, path, shared):
                rows.append(cells)
                if len(rows) > 200:
                    break
            kpi[name] = crm_kpi.read_kpi_rows(rows)
            continue
        if name not in SHEETS:
            continue
        notes = _comments(z, path)
        st = stats.setdefault(name, Counter())
        header, empty_run = {}, 0
        for n, (rownum, cells, colours) in enumerate(_rows(z, path, shared, styles)):
            if not header and any(v.lower().startswith('phone') for v in cells.values()):
                header = {v.strip().lower(): c for c, v in cells.items()}
                continue
            row = _sheet_row(name, idx, n, cells, header)
            if row is None:
                empty_run += 1
                if empty_run > STOP_AFTER:
                    break
                continue
            empty_run = 0
            # the name cell's colour says how ready they are; its comments are the conversation
            name_col = (header.get('lead') or header.get('customer') or header.get('pipeline') or 'B')
            row['likelihood'] = likelihood_from(colours.get(name_col) or colours.get('A'))
            names_cols = {header.get('names'), header.get('ur')} - {None}
            history, medical = [], []
            for ref, text in notes.items():
                m = re.match(r'([A-Z]+)(\d+)$', ref or '')
                if m and rownum and int(m.group(2)) == rownum:
                    (medical if m.group(1) in names_cols else history).append(text)
            row['history'] = history
            if medical:
                row['details']['medical_conditions'] = ' / '.join(medical)[:300]
            st['rows'] += 1
            st['with phone' if row['phone'] else 'with e-mail' if row['email'] else
               'Instagram / Facebook only' if row['identities'] else 'no way to reach'] += 1
            if history:
                st['with notes'] += 1
            if row['likelihood'] == 'hot':
                st['ready to buy'] += 1
            out.append(row)
    return out, stats, kpi


def _sheet_row(sheet, sheet_idx, n, cells, header):
    def get(*names):
        for nm in names:
            c = header.get(nm)
            if c and cells.get(c):
                return cells[c]
        return None

    if not header:              # Cold Leads has no header: B = number, C = what, D/E = contact
        if not (cells.get('C') or cells.get('D')):
            return None
        phone, email, idents, rest = parse_contacts(cells.get('D'), cells.get('E'))
        if not (phone or email or idents):
            return None
        return {'sheet': sheet, 'ref': sheet_idx * 1_000_000 + n, 'name': None, 'phone': phone, 'email': email,
                'identities': idents, 'product': 'TC', 'source': 'tc-cs-post', 'date': None,
                'details': {'post': cells.get('C'), 'other_contact': rest or None, 'note': cells.get('K')},
                'messages': [], 'temperature': None, 'comment': None, 'next_date': None, 'next_step': None,
                'departure': None, 'ends': None}
    phone, email, idents, rest = parse_contacts(get('phone number'), get('emai id', 'email id', 'email'),
                                                hint=get('s'))
    name = get('lead', 'customer', 'pipeline')
    if name and re.fullmatch(r'[\d.\s]+', name):
        name = None
    if not (phone or email or idents):
        return None
    enq = (get('enq.') or '').upper().replace(' ', '')
    product = ENQ_PRODUCT.get(enq) or DEFAULT_PRODUCT.get(sheet, 'TI')
    src = SOURCE_CODES.get((get('s') or '').upper().strip(), 'import-other')
    day = excel_date(get('date'))
    messages = []
    for head, c in header.items():
        code = None
        if MESSAGE_CODES.match(head.upper()):
            code = re.sub(r'\s*#\s*', ' #', head.upper()).replace('F M', 'FM')
        elif head.strip().lower() in ('q', 'pls'):
            code = head.strip().upper()            # quote sent, payment link sent
        if not code:
            continue
        v = (cells.get(c) or '').strip()
        if not v or v.upper() in ('N', 'NO', '0'):
            continue
        messages.append((code, excel_date(v) or day))
    ls = (get('ls') or '').upper()
    return {
        'sheet': sheet, 'ref': sheet_idx * 1_000_000 + n, 'name': name, 'phone': phone, 'email': email,
        'identities': idents, 'product': product, 'source': src, 'date': day,
        'departure': excel_date(get('onward dep', 'start date')), 'ends': excel_date(get('return date', 'end date')),
        'details': {'travellers': get('names'), 'relation': RELATION.get((get('ur') or '').upper(), get('ur')),
                    'age': get('age'), 'from': get('dep.'), 'to': get('arrival'), 'trip_days': get('td'),
                    'pre_existing': get('pe'), 'claim_number': get('claim number'),
                    'enquiry': get('enq.'), 'other_contact': rest if rest and len(rest) > 3 else None},
        'messages': messages, 'temperature': ls if ls in TEMPS else None, 'comment': get('comments'),
        'next_date': excel_date(get('next follow-up', 'next followup')), 'next_step': get('next step'),
    }


def import_sheet(rows, owner_id=None, kpi=None, kpi_users=None):
    """Store what read_sheet() returned. Returns a Counter. Rows already imported are skipped; the
    KPI tabs replace whatever an earlier import of the same tab brought in.

    `kpi_users` says whose each KPI tab is: {'KPI': None (the team), 'HB KPI': user id, ...}; a tab
    with no person chosen is left out."""
    from app.services import crm_kpi
    crm.ensure_defaults()
    out = Counter()
    for r in rows:
        if _linked('sales_sheet', r['ref']):
            out['already'] += 1
            continue
        pipe = crm_products.default_pipeline(r['product'])
        stage = _sheet_stage(pipe, r['sheet']) if pipe is not None else None
        when = datetime.combine(r['date'], time(6, 0)) if r['date'] else datetime.utcnow()
        try:
            lead = crm.capture(r['source'], name=r['name'], phone=r['phone'], email=r['email'],
                               identities=r['identities'], product=r['product'], details=r['details'],
                               departure_date=r['departure'], ends_on=r['ends'], when=when, utm={},
                               ref=('sales_sheet', r['ref']), start_stage=stage, plan=False, notify=False,
                               sync=False, imported=True, temperature=r['temperature'],
                               likelihood=r.get('likelihood'), refuse_dnc=True,
                               fallout_reason='From the sales sheet' if stage and stage.kind == 'lost' else None)
        except crm.DoNotContact:
            out['do not contact'] += 1
            continue
        if lead is None:
            out['unreachable'] += 1
            continue
        if stage is not None and lead.stage_id != stage.id and lead.status == 'open' and \
                (stage.kind != 'open' or (lead.stage and stage.position > lead.stage.position)):
            # the same person on a later tab: they moved on
            crm.move_stage(lead, stage, reason='Sales sheet: %s' % r['sheet'], plan=False, sync=False,
                           fallout_reason='From the sales sheet' if stage.kind == 'lost' else None)
        if r.get('likelihood') and not lead.likelihood:
            lead.likelihood = r['likelihood']
        if owner_id:
            lead.owner_id = owner_id
        for code, day in r['messages']:
            at = datetime.combine(day, time(6, 0)) if day else when
            label = {'Q': 'Quote sent', 'PLS': 'Payment link sent'}.get(code, code)
            db.session.add(CrmTouchpoint(lead=lead, person_id=lead.person_id,
                                         channel='call' if code.startswith('CL') else 'whatsapp',
                                         direction='out', code=code, status='imported', via='import', created_at=at,
                                         body='%s (recorded in the sales sheet)' % label))
        for note in [r['comment']] + list(r.get('history') or []):
            if note:
                db.session.add(CrmTouchpoint(lead=lead, person_id=lead.person_id, channel='note',
                                             direction='none', body=note[:4000], created_at=when))
        if r['next_date'] and lead.status == 'open' and not lead.open_task:
            step = (r['next_step'] or 'Follow-up').strip()[:20]
            db.session.add(CrmTask(lead=lead, code=step, title='Follow up (%s, from the sales sheet)' % step,
                                   channel='call' if step.upper().startswith('CL') else 'whatsapp',
                                   due_at=datetime.combine(r['next_date'], time(9, 0)) - IST,
                                   owner_id=lead.owner_id))
        db.session.commit()
        out[r['sheet']] += 1
    for tab, days in (kpi or {}).items():
        if tab not in (kpi_users or {}):
            continue
        out['KPI days (%s)' % tab] = crm_kpi.import_kpi(days, user_id=kpi_users[tab])
    return out
