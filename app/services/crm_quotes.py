"""Quotes and payments on a lead (Sales CRM 2.0, run 4b).

A quote says what we offered and for how much; a payment is a link (or a bank transfer) we asked the customer to
pay. Both hang on the lead, so the recycle bin and "who sees which leads" hide them with it (crm_bin.CHILDREN,
crm_access), merging two people moves them with their leads, and erasing a person deletes them.

How they meet the rest of the CRM, in one place:

* "Mark as sent" and "+ Payment link" log the stage's own milestone ("I sent the quote" / "I sent the payment
  link", codes Q and PLS) through crm.mark_event -- the code path of the buttons that were already there -- so the
  stage moves exactly as before. The row remembers the line it logged (sent_touch_id / link_touch_id).
* The numbers (crm_numbers `quoted`, `payment_links`) count those milestone lines. A row only counts by itself when
  its pipeline had no such button, so nothing is counted twice. THE MILESTONE LINE WINS.
* Forecast stays one line per lead (crm_money.forecast); quote rows are never added up. A sent quote only fills a
  lead's empty value.
* Nothing here ever messages a customer: "Copy text" and "Put in the message box" hand the words to the agent.
"""
import hmac
import hashlib
import json
import re
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import and_, or_, select

from app import db
from app.models import (CrmAudit, CrmLead, CrmPayment, CrmQuote, CrmTouchpoint, User, WorkspaceTeam,
                        workspace_team_members)
from app.services import crm_money

QUOTE_WORDS = {'draft': 'Not sent yet', 'sent': 'Sent', 'accepted': 'Accepted', 'declined': 'Declined',
               'expired': 'Ran out'}
PAYMENT_WORDS = {'pending': 'Waiting for payment', 'paid': 'Paid', 'failed': 'Failed', 'refunded': 'Refunded'}
PROVIDERS = ('Razorpay', 'Stripe', 'PayPal', 'Bank transfer', 'UPI', 'Cash')
VALID_DAYS = 14
BLOCKED = 'This quote is below the usual price and needs an approval before it can be sent.'
NOT_APPROVER = 'Only an admin or the owner\'s team lead can approve a quote.'
QUOTE_REF_RE = re.compile(r'^\s*q[- ]?(\d{1,9})\s*$', re.I)


class QuoteError(ValueError):
    """Something the person can fix, phrased for them."""


# ================================================================================================ words

def _money(amount, currency):
    return crm_money.money(amount, currency) if amount is not None else 'no amount'


def history(lead, text, user=None):
    """A line on the lead's History in plain words ("marked the quote ₹18,500 as sent"). Written straight to the
    audit table, on this session's connection."""
    db.session.add(CrmAudit(at=datetime.utcnow(), user_id=getattr(user, 'id', None), record_type='lead',
                            record_id=lead.id, field='quote', old=None, new=text[:300]))


# ================================================================================================ approval

def product_limit(lead, amount, currency):
    """True when this amount is below the product's price less its biggest allowed discount (so it needs an
    approval). Money is compared in the reporting currency; with no price, no limit or no rate it cannot say."""
    prod = crm_money.product_row(lead.product)
    pct = crm_money.dec(getattr(prod, 'max_discount_pct', None)) if prod is not None else None
    price = crm_money.dec(getattr(prod, 'price', None)) if prod is not None else None
    amount = crm_money.dec(amount)
    if pct is None or not price or amount is None:
        return False
    rate_map = crm_money.rates()
    floor = crm_money.to_base(price, prod.currency, rate_map) * (Decimal(100) - pct) / Decimal(100)
    have = crm_money.to_base(amount, currency or prod.currency, rate_map)
    if not floor or not have:
        return False
    return have < floor


def blocked(quote):
    """Needs an approval nobody has given yet."""
    return bool(quote.needs_approval and quote.approved_at is None)


def team_mate_ids(user_id):
    """Everyone who shares a workspace team with this user (the user included)."""
    teams = [r[0] for r in db.session.execute(select(workspace_team_members.c.team_id)
                                              .where(workspace_team_members.c.user_id == user_id)).all()]
    ids = {user_id}
    if teams:
        ids |= {r[0] for r in db.session.execute(select(workspace_team_members.c.user_id)
                                                 .where(workspace_team_members.c.team_id.in_(teams))).all()}
    return ids


def _leads_team(user):
    from app.services import access
    return access.can(user, 'crm_tracker')


def can_approve(user, lead):
    """Admins, and a team lead (Team today) in a team the lead's owner is in."""
    if user is None or not getattr(user, 'is_authenticated', False):
        return False
    if user.is_admin:
        return True
    if lead is None or lead.owner_id is None or lead.owner_id == user.id:
        return False
    return _leads_team(user) and lead.owner_id in team_mate_ids(user.id)


def approvers_of(lead):
    """Users to ring when a quote needs approval: the admins and the owner's team leads."""
    out = {u.id: u for u in User.query.filter(User.is_admin.is_(True), User.is_active.is_(True)).all()}
    if lead.owner_id:
        mates = team_mate_ids(lead.owner_id) - {lead.owner_id}
        for u in User.query.filter(User.id.in_(sorted(mates) or [0]), User.is_active.is_(True)).all():
            if _leads_team(u):
                out[u.id] = u
    return list(out.values())


def _ring(quote, lead, user):
    from app.services import crm, notify
    name = lead.person.display_name if lead.person else 'a lead'
    for u in approvers_of(lead):
        if user is not None and u.id == user.id:
            continue
        notify.push(u.id, 'crm_approval', title='A quote needs your approval: %s' % name,
                    body='%s, %s' % (quote.title, _money(quote.amount, quote.currency)),
                    link=crm._lead_link(lead))


def waiting_for(user, limit=50):
    """Quotes waiting for this person's approval, newest first: [{'quote', 'lead'}]. Only leads the viewer may see
    (written out here: this also runs from places the request-wide limit does not reach)."""
    from app.services import crm_access
    if user is None or not getattr(user, 'is_authenticated', False):
        return []
    if not (user.is_admin or _leads_team(user)):
        return []
    q = (CrmQuote.query.join(CrmLead, CrmLead.id == CrmQuote.lead_id)
         .filter(CrmQuote.needs_approval.is_(True), CrmQuote.approved_at.is_(None), CrmQuote.status == 'draft',
                 CrmLead.deleted_at.is_(None)))
    crit = crm_access.lead_filter(user)
    if crit is not None:
        q = q.filter(crit)
    if not user.is_admin:
        q = q.filter(CrmLead.owner_id.in_(sorted(team_mate_ids(user.id) - {user.id}) or [0]))
    rows = q.order_by(CrmQuote.id.desc()).limit(limit).all()
    return [{'quote': r, 'lead': r.lead} for r in rows]


# ================================================================================================ quotes

def defaults(lead):
    """What the "+ Quote" form starts with: the lead's value (else the product's price), its currency, a title."""
    prod = crm_money.product_row(lead.product)
    amount, currency = lead.amount, lead.currency
    if amount is None and prod is not None and crm_money.dec(prod.price):
        amount, currency = prod.price, prod.currency
    from app.services import crm_products
    title = (crm_products.labels().get(lead.product) or lead.product or 'Quote')
    return {'title': title, 'amount': crm_money.plain_amount(amount) if amount is not None else '',
            'currency': (currency or crm_money.reporting_currency()).upper(),
            'valid_until': (date.today() + timedelta(days=VALID_DAYS)).isoformat()}


def _clean(data):
    title = ' '.join(str(data.get('title') or '').split())[:160]
    if not title:
        raise QuoteError('Give the quote a name, for example the plan.')
    try:
        amount = crm_money.money_amount(data.get('amount'))
    except ValueError:
        raise QuoteError('Type the amount as a number, like 18500.') from None
    raw = str(data.get('valid_until') or '').strip()
    valid = None
    if raw:
        try:
            valid = datetime.strptime(raw, '%Y-%m-%d').date()
        except ValueError:
            raise QuoteError('Use a real date for "valid until".') from None
    return {'title': title, 'details': (str(data.get('details') or '').strip()[:4000] or None), 'amount': amount,
            'currency': crm_money.clean_currency(data.get('currency')), 'valid_until': valid}


def create(lead, data, user=None):
    vals = _clean(data)
    quote = CrmQuote(lead=lead, status='draft', created_by_id=getattr(user, 'id', None), created_at=datetime.utcnow(),
                     needs_approval=product_limit(lead, vals['amount'], vals['currency']), **vals)
    db.session.add(quote)
    db.session.flush()
    history(lead, 'wrote the quote %s for %s' % (quote.title, _money(quote.amount, quote.currency)), user)
    if quote.needs_approval:
        _ring(quote, lead, user)
    db.session.commit()
    return quote


def update(quote, data, user=None):
    if quote.status != 'draft':
        raise QuoteError('A quote that was sent cannot be changed. Write a new one.')
    vals = _clean(data)
    changed_money = (vals['amount'], vals['currency']) != (quote.amount, quote.currency)
    for k, v in vals.items():
        setattr(quote, k, v)
    if changed_money:
        quote.needs_approval = product_limit(quote.lead, quote.amount, quote.currency)
        quote.approved_by_id = quote.approved_at = None
        if quote.needs_approval:
            _ring(quote, quote.lead, user)
    db.session.commit()
    return quote


def _milestone(lead, code, user, note):
    """Log the stage's milestone through the existing button's code path; (touch id or None, stage moved to).
    No milestone on this pipeline: nothing is logged and the rows count themselves (see the module note)."""
    from app.services import crm
    stage = crm.milestone_stage(lead.pipeline, code)
    if stage is None:
        return None, None
    moved = crm.mark_event(lead, code, user=user, note=note)         # commits
    tp = (CrmTouchpoint.query.filter(CrmTouchpoint.lead_id == lead.id, CrmTouchpoint.channel == 'system',
                                     CrmTouchpoint.code == stage.button_code)
          .order_by(CrmTouchpoint.id.desc()).first())
    return (tp.id if tp is not None else None), moved


def _fill_value(lead, amount, currency, user):
    """A lead with no value takes the amount of the quote / payment (logged on its history like any value change)."""
    if lead.amount is None and amount is not None:
        crm_money.change_value(lead, amount=amount, currency=currency, user=user)


def mark_sent(quote, user=None):
    if blocked(quote):
        raise QuoteError(BLOCKED)
    if quote.status != 'draft':
        raise QuoteError('This quote was already sent.')
    lead = quote.lead
    quote.status, quote.sent_at = 'sent', datetime.utcnow()
    _fill_value(lead, quote.amount, quote.currency, user)
    history(lead, 'marked the quote %s as sent' % _money(quote.amount, quote.currency), user)
    quote.sent_touch_id, _ = _milestone(lead, 'Q', user, quote.title)     # commits
    db.session.commit()
    return quote


def set_status(quote, status, user=None):
    if status not in ('accepted', 'declined', 'expired'):
        raise QuoteError('Unknown choice.')
    if quote.status not in ('sent', 'draft'):
        raise QuoteError('This quote is already %s.' % QUOTE_WORDS.get(quote.status, quote.status).lower())
    quote.status = status
    word = {'accepted': 'accepted', 'declined': 'declined', 'expired': 'run out'}[status]
    history(quote.lead, 'marked the quote %s as %s' % (_money(quote.amount, quote.currency), word), user)
    db.session.commit()
    return quote


def approve(quote, user):
    lead = quote.lead
    if not can_approve(user, lead):
        raise QuoteError(NOT_APPROVER)
    if not quote.needs_approval or quote.approved_at is not None:
        return quote
    quote.approved_by_id, quote.approved_at = user.id, datetime.utcnow()
    history(lead, 'approved the quote %s' % _money(quote.amount, quote.currency), user)
    if quote.created_by_id and quote.created_by_id != user.id:
        from app.services import crm, notify
        notify.push(quote.created_by_id, 'crm_approval', title='Your quote was approved: %s' % lead.person.display_name,
                    body='You can send it now.', link=crm._lead_link(lead))
    db.session.commit()
    return quote


def delete(quote, user=None):
    lead = quote.lead
    if quote.status != 'draft':
        raise QuoteError('Only a quote that was not sent can be deleted.')
    for p in CrmPayment.query.filter_by(quote_id=quote.id).all():
        p.quote_id = None
    history(lead, 'deleted the quote %s' % quote.title, user)
    db.session.delete(quote)
    db.session.commit()


def quote_text(quote, user=None):
    """The words for the customer: the agent copies them or puts them in the message box and presses Send."""
    from app.services import crm
    lead = quote.lead
    first = crm.first_name(lead.person.name) if lead.person and lead.person.name else None
    lines = ['Hi %s,' % (first or 'there'), '',
             'Here is your quote for %s: %s.' % (quote.title, _money(quote.amount, quote.currency))]
    if quote.details:
        lines += ['', quote.details.strip()]
    if quote.valid_until:
        lines += ['', 'This quote is valid until %d %s %d.' % (quote.valid_until.day, quote.valid_until.strftime('%b'),
                                                              quote.valid_until.year)]
    who = (getattr(user, 'first_name', None) or '').strip()
    lines += ['', 'Thank you%s' % (',\n%s' % who if who else '')]
    return '\n'.join(lines)


# ================================================================================================ payments

def payment_defaults(lead):
    q = next((q for q in lead.quotes if q.status in ('sent', 'accepted')), None)
    amount = q.amount if q is not None else lead.amount
    currency = (q.currency if q is not None else lead.currency) or crm_money.reporting_currency()
    return {'amount': crm_money.plain_amount(amount) if amount is not None else '', 'currency': currency,
            'quote_id': q.id if q is not None else ''}


def add_payment(lead, data, user=None):
    try:
        amount = crm_money.money_amount(data.get('amount'))
    except ValueError:
        raise QuoteError('Type the amount as a number, like 18500.') from None
    url = str(data.get('link_url') or '').strip()[:500]
    if url and not re.match(r'^https?://', url, re.I):
        raise QuoteError('The payment link should start with http:// or https://.')
    provider = ' '.join(str(data.get('provider') or '').split())[:30] or None
    reference = ' '.join(str(data.get('reference') or '').split())[:80] or None
    quote = None
    if str(data.get('quote_id') or '').isdigit():
        quote = CrmQuote.query.filter_by(id=int(data['quote_id']), lead_id=lead.id).first()
    pay = CrmPayment(lead=lead, quote=quote, amount=amount, link_url=url or None, provider=provider,
                     reference=reference, currency=crm_money.clean_currency(data.get('currency')),
                     status='pending', created_by_id=getattr(user, 'id', None), created_at=datetime.utcnow())
    db.session.add(pay)
    db.session.flush()
    _fill_value(lead, pay.amount, pay.currency, user)
    history(lead, 'asked for a payment of %s%s' % (_money(pay.amount, pay.currency),
                                                   ' by %s' % provider if provider else ''), user)
    pay.link_touch_id, _ = _milestone(lead, 'PLS', user, provider)       # commits
    db.session.commit()
    return pay


def mark_paid(pay, user=None, amount=None, currency=None):
    """The customer paid. The lead takes the paid amount when it has none, gets a close date when it has none and
    moves to its pipeline's won stage (a normal move, reason "Paid"; a stage's entry rules are for people moving a
    lead, not for this). A payment already paid changes nothing. Returns True when something changed."""
    from app.services import crm
    if pay.status == 'paid':
        return False
    lead = pay.lead
    now = datetime.utcnow()
    if amount is not None and pay.amount is None:
        pay.amount = amount
        pay.currency = crm_money.clean_currency(currency, pay.currency)
    pay.status, pay.paid_at = 'paid', now
    if lead.amount is None and pay.amount is not None:
        crm_money.set_amount(lead, pay.amount, pay.currency)
        crm.log_touch(lead, 'system', 'none', body='Value set to %s from the payment' % _money(lead.amount, lead.currency),
                      user=user, activity=False)
    if lead.close_date is None:
        lead.close_date = (now + crm.IST).date()
    if pay.quote is not None and pay.quote.status in ('sent', 'draft'):
        pay.quote.status = 'accepted'
    history(lead, 'recorded a payment of %s as paid' % _money(pay.amount, pay.currency), user)
    won = next((s for s in (lead.pipeline.stages if lead.pipeline else []) if s.kind == 'won'), None)
    if won is not None and lead.stage_id != won.id:
        crm.move_stage(lead, won, user=user, reason='Paid')
    crm.log_touch(lead, 'system', 'none', body='Payment of %s received' % _money(pay.amount, pay.currency), user=user)
    if lead.owner_id and (user is None or lead.owner_id != getattr(user, 'id', None)):
        from app.services import notify
        notify.push(lead.owner_id, 'crm_paid', title='Paid: %s' % lead.person.display_name,
                    body=_money(pay.amount, pay.currency), link=crm._lead_link(lead))
    db.session.commit()
    return True


def set_payment_status(pay, status, user=None):
    if status == 'paid':
        mark_paid(pay, user)
        return pay
    if status not in ('failed', 'refunded', 'pending'):
        raise QuoteError('Unknown choice.')
    if pay.status == status:
        return pay
    if pay.status == 'paid' and status != 'refunded':
        raise QuoteError('This payment was paid. Mark it as refunded if the money went back.')
    pay.status = status
    word = {'failed': 'failed', 'refunded': 'refunded', 'pending': 'waiting for payment'}[status]
    history(pay.lead, 'marked the payment of %s as %s' % (_money(pay.amount, pay.currency), word), user)
    if status == 'failed':
        _tell_failed(pay)
    db.session.commit()
    return pay


def _tell_failed(pay):
    from app.services import crm, notify
    lead = pay.lead
    crm.log_touch(lead, 'system', 'none', body='Payment of %s failed' % _money(pay.amount, pay.currency), activity=False)
    if lead.owner_id:
        notify.push(lead.owner_id, 'crm_failed', title='A payment failed: %s' % lead.person.display_name,
                    body=_money(pay.amount, pay.currency), link=crm._lead_link(lead))


def delete_payment(pay, user=None):
    if pay.status == 'paid':
        raise QuoteError('A payment that was paid stays on the record.')
    history(pay.lead, 'deleted a payment of %s' % _money(pay.amount, pay.currency), user)
    db.session.delete(pay)
    db.session.commit()


# ================================================================================================ the webhook

def sign(secret, raw):
    return hmac.new(secret.encode('utf-8'), raw, hashlib.sha256).hexdigest()


def signature_ok(secret, header, raw):
    """X-Signature = hex HMAC-SHA256 of the raw body with the shared secret. Constant-time compare."""
    if not secret or not header:
        return False
    return hmac.compare_digest(sign(secret, raw), str(header).strip().lower())


def handle_webhook(payload):
    """{reference, status, amount, currency}: find the payment and move it on. Repeats change nothing.
    Returns {'result': ...}. Commits."""
    ref = ' '.join(str((payload or {}).get('reference') or '').split())[:80]
    status = str((payload or {}).get('status') or '').strip().lower()
    if not ref or status not in ('paid', 'failed', 'refunded', 'pending'):
        raise QuoteError('Send a reference and a status (paid, failed, refunded).')
    pay = (CrmPayment.query.filter(CrmPayment.reference == ref).order_by(CrmPayment.id.desc()).first())
    if pay is None:
        return {'result': 'unknown'}
    if status == 'paid':
        try:
            amount = crm_money.money_amount((payload or {}).get('amount'))
        except ValueError:
            amount = None
        changed = mark_paid(pay, None, amount=amount, currency=(payload or {}).get('currency'))
        return {'result': 'paid' if changed else 'already', 'lead_id': pay.lead_id}
    if pay.status == status or pay.status == 'paid' and status != 'refunded':
        return {'result': 'already', 'lead_id': pay.lead_id}
    set_payment_status(pay, status, None)
    return {'result': status, 'lead_id': pay.lead_id}


# ================================================================================================ page + find

def card(lead, user):
    """What the lead page's "Quotes & payments" card draws."""
    quotes = list(lead.quotes)
    payments = list(lead.payments)
    return {'quotes': quotes, 'payments': payments, 'defaults': defaults(lead), 'pay_defaults': payment_defaults(lead),
            'can_approve': can_approve(user, lead), 'providers': PROVIDERS,
            'currencies': crm_money.currency_choices(lead), 'texts': {q.id: quote_text(q, user) for q in quotes},
            'has_q': bool(lead.pipeline and any((s.button_code or '').upper() == 'Q' and s.button_label
                                                for s in lead.pipeline.stages))}


def ref_condition(q, user=None):
    """A condition on CrmPerson for a search that is a quote reference ("Q-12") or a payment reference: the people
    whose visible, unremoved leads hold it. None when q is neither."""
    q = ' '.join((q or '').split())[:80]
    if not q:
        return None
    from app.services import crm_access
    if user is None:
        from flask import has_request_context
        from flask_login import current_user
        user = current_user if has_request_context() and current_user.is_authenticated else None
    L = CrmLead.__table__
    visible = [L.c.deleted_at.is_(None)]
    ids = crm_access.visible_owner_ids(user) if user is not None else None
    if ids is not None:
        visible.append(or_(L.c.owner_id.in_(sorted(ids)), L.c.owner_id.is_(None)))
    Q, P = CrmQuote.__table__, CrmPayment.__table__
    parts = []
    m = QUOTE_REF_RE.match(q)
    if m:
        parts.append(select(L.c.person_id).join(Q, Q.c.lead_id == L.c.id).where(Q.c.id == int(m.group(1)), *visible))
    if len(q) >= 3:
        parts.append(select(L.c.person_id).join(P, P.c.lead_id == L.c.id)
                     # the escape character is said outright: "pay_X81" (Razorpay) must match on SQLite too (run 5b)
                     .where(P.c.reference.ilike('%%%s%%' % q.replace('\\', '').replace('%', '').replace('_', r'\_'),
                                                escape='\\'), *visible))
    if not parts:
        return None
    from app.models import CrmPerson
    return or_(*[CrmPerson.id.in_(p) for p in parts])

