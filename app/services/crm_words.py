"""Words for the codes the Sales CRM keeps in its data (Sales CRM 2.0, phase 0).

The codes stay in the database, in downloads and in the pipeline set-up editor's "code" field. Anything a
salesperson reads says words instead, and says them from here so the same code reads the same everywhere:

    message_word('BW')                   -> 'Birthday wish'
    message_name('TI #3', 'Quote nudge') -> 'Quote nudge'   (the step's own title wins)
    milestone_word('PLS')                -> 'Payment link sent'
    reply_word('R')                      -> 'Replied'
    source_display('TC: trip posted')    -> 'Travel Companion — trip posted'
"""
import re

from app.models import CRM_REPLIES

# a follow-up / ready message's code prefix -> what it is, in words
MESSAGE_WORDS = {
    'BW': 'Birthday wish', 'FM': 'Festival message', 'OM': 'Festival message', 'HJ': 'Happy journey',
    'SA': 'Safely arrived', 'CM': 'Casual check-in', 'ER': 'Cover ending', 'PM': 'Promotion',
    'SE': 'Shift-end message', 'CS': 'Feedback poll', 'PF': 'After lost', 'PI': 'Reminder', 'CE': 'Care message',
}
FOLLOW_UP = 'Follow-up'          # TC, TI, SH, GH, VC, GEN, CL, FU ... and anything not listed

MILESTONE_WORDS = {'Q': 'Quote sent', 'PLS': 'Payment link sent'}

# the "Replies" line of a lead: what its temperature code means
REPLY_WORDS = {None: 'Not replied yet', **CRM_REPLIES}

_PREFIX = re.compile(r'^\s*([A-Za-z]+)')
_SOURCE = re.compile(r'^\s*([A-Z][A-Z0-9]{1,7})\s*:\s*(.+)$')


def age_text(since, now):
    """How long something has been so: '5 h' under a day, else '3 d'. '' when it has no start."""
    if since is None:
        return ''
    hours = max(0, int((now - since).total_seconds() // 3600))
    return '%d h' % hours if hours < 24 else '%d d' % (hours // 24)


def message_word(code):
    """'BW' -> 'Birthday wish'; any other code (a product's first contact, TI #3 ...) -> 'Follow-up'."""
    m = _PREFIX.match(code or '')
    return MESSAGE_WORDS.get(m.group(1).upper(), FOLLOW_UP) if m else FOLLOW_UP


def message_name(code, title=None):
    """What to call a follow-up or ready message on screen: its own title, else the word for its code."""
    title = (title or '').strip()
    return title or message_word(code)


def milestone_word(code, default=None):
    return MILESTONE_WORDS.get((code or '').strip().upper(), default if default is not None else (code or ''))


def reply_word(temperature):
    return REPLY_WORDS.get(temperature, REPLY_WORDS[None])


def step_titles():
    """{code: title} of the pipelines' follow-up steps and the ready messages, for showing a sent message by
    name. The first step with a code wins. One query each."""
    from app import db
    from app.models import CrmAnswer, CrmPipeline, CrmPlaybookStep, CrmStage
    out = {}
    for code, title in (db.session.query(CrmPlaybookStep.code, CrmPlaybookStep.title)
                        .join(CrmStage, CrmStage.id == CrmPlaybookStep.stage_id)
                        .join(CrmPipeline, CrmPipeline.id == CrmStage.pipeline_id)
                        .order_by(CrmPipeline.id, CrmStage.position, CrmPlaybookStep.position)):
        out.setdefault(code, title)
    for code, title in db.session.query(CrmAnswer.code, CrmAnswer.title).filter(CrmAnswer.code.isnot(None)):
        out.setdefault(code, title)
    return out


def product_names():
    from app.models import CRM_PRODUCT_LABELS
    try:
        from app.services import crm_products
        names = dict(crm_products.labels())
    except Exception:          # noqa: BLE001 -- no app context: the built-in names
        names = {}
    return {**CRM_PRODUCT_LABELS, **names}


def source_display(name, names=None):
    """A lead source's name for a screen: 'TC: trip posted on the site' -> 'Travel Companion — trip posted on the
    site'. The stored name is never changed; a name with no product code in front is returned as it is."""
    m = _SOURCE.match(name or '')
    if not m:
        return name
    product = (names or product_names()).get(m.group(1))
    return '%s — %s' % (product, m.group(2).strip()) if product else name
