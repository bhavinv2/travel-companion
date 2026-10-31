"""Admin -> Travel Insurance -> Canada quotes: every super visa / visitors to Canada quote, for following up.

A COPY, not a second place to work: each request is also a lead in the Sales CRM (source "Canada quote", the
Travel insurance pipeline), and that is where it is worked. This screen shows what only the quote knows --
the cover, the travellers, what they picked and the price they were shown -- beside today's price for the
same pick (read live from Secure Travel, so "same" or "changed" is a fact, not a guess), the rate check, and
the buttons staff need: the customer's quotes page, the lead, and Secure Travel's checkout with our tracking
code for completing the purchase after the call.
"""
from datetime import datetime, timedelta

from flask import flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.models import CrmSource, InsuranceQuote
from app.routes.admin import admin_bp, admin_required, _page_args
from app.services import canada_quotes, phone as phone_svc

STATUSES = {'callback': 'Asked for a call back', 'quoted': 'Only looked', 'failed': 'Not priced'}


def _repriced(quote, pick):
    """Today's price for a pick: (total, same as shown?) or (None, None) when it cannot be priced now. A pick
    made for one traveller is priced for that traveller alone."""
    travellers = quote.travellers or []
    if pick.get('traveller') is not None:
        travellers = travellers[int(pick['traveller']):int(pick['traveller']) + 1]
    try:
        priced = canada_quotes.price_pick(pick['product'], travellers, int(pick.get('days') or 365),
                                          str(pick['plan']), str(pick['limit']), int(pick.get('deductible') or 0))
    except (canada_quotes.Unavailable, KeyError, ValueError, TypeError):
        return None, None
    if priced is None:
        return None, None
    return priced[0], abs(priced[0] - float(pick.get('total') or 0)) < 0.005


def _rate_check():
    """What the last checks of Secure Travel's two pages found, and where the pages disagree."""
    tables, errors = {}, {}
    for product in canada_quotes.PRODUCTS:
        try:
            tables[product] = canada_quotes.live(product)
        except canada_quotes.Unavailable as e:
            errors[product] = str(e)
    differ = None
    if 'super_visa' in tables and 'visitors' in tables:
        differ = canada_quotes.compare_pages(tables['super_visa'][0], tables['visitors'][0])
    stored = canada_quotes.state()

    def _when(iso):
        try:
            return datetime.fromisoformat(iso) if iso else None
        except ValueError:
            return None

    rows = []
    for product, info in canada_quotes.PRODUCTS.items():
        s = stored.get(product) or {}
        t = tables.get(product)
        rows.append({'product': product, 'label': info['label'], 'url': info['url'],
                     'checked_at': t[1]['checked_at'] if t else _when(s.get('checked_at')),
                     'same': s.get('same'), 'changed_at': _when(s.get('changed_at')),
                     'first_seen': _when(s.get('first_seen')), 'codes_changed': s.get('codes_changed'),
                     'rates': len(t[0].rates) if t else s.get('rates'), 'fingerprint': t[0].fingerprint if t else s.get('fingerprint'),
                     'error': errors.get(product) or (s.get('error') if not t else None),
                     'stale': t[1]['stale'] if t else False})
    return {'rows': rows, 'differ': differ}


@admin_bp.route('/insurance/canada-quotes')
@login_required
@admin_required
def canada_quotes_admin():
    page, per_page = _page_args(25)
    status = request.args.get('status') or ''
    cover = request.args.get('cover') or ''
    q = (request.args.get('q') or '').strip()
    days = request.args.get('days') or ''

    query = InsuranceQuote.query.filter(InsuranceQuote.insurance_type == 'canada')
    if status in STATUSES:
        query = query.filter(InsuranceQuote.status == status)
    if days.isdigit():
        query = query.filter(InsuranceQuote.created_at >= datetime.utcnow() - timedelta(days=int(days)))
    if q:
        from sqlalchemy import or_
        pat = f'%{q}%'
        query = query.filter(or_(InsuranceQuote.name.ilike(pat), InsuranceQuote.email.ilike(pat),
                                 phone_svc.matches(InsuranceQuote.phone, q)))
    rows = query.order_by(InsuranceQuote.created_at.desc()).all()
    if cover in ('super_visa', 'visitors'):           # inside `extra`: a handful of rows, filtered here
        rows = [r for r in rows if (r.extra or {}).get('cover') == cover]
    total = len(rows)
    pages = max((total + per_page - 1) // per_page, 1)
    page = min(page, pages)
    shown = rows[(page - 1) * per_page: page * per_page]

    picks = {}
    for r in shown:
        out = []
        for p in (r.extra or {}).get('picks') or []:
            now, same = _repriced(r, p)
            out.append(dict(p, now=now, same=same))
        picks[r.id] = out

    base = InsuranceQuote.query.filter(InsuranceQuote.insurance_type == 'canada')
    counts = {'all': base.count(), **{k: base.filter(InsuranceQuote.status == k).count() for k in STATUSES}}
    src = CrmSource.query.filter_by(key='ti-canada').first()
    pipeline_url = (url_for('admin_crm.board', p=(src.pipeline.key if src and src.pipeline else 'all'),
                            src=src.id, view='list') if src else None)
    return render_template('admin/canada_quotes.html', quotes=shown, picks=picks, counts=counts, statuses=STATUSES,
                           status=status, cover=cover, q=q, days=days, total=total, page=page, pages=pages,
                           check=_rate_check(), checkout_url=canada_quotes.checkout_url(),
                           tracking_code=canada_quotes.TRACKING_CODE, pipeline_url=pipeline_url,
                           money=canada_quotes.money, covers={'super_visa': 'Super visa', 'visitors': 'Visitor'})


@admin_bp.route('/insurance/canada-quotes/check', methods=['POST'])
@login_required
@admin_required
def canada_rates_check():
    """"Check now": read both of Secure Travel's pages again, whatever the last read's age."""
    said = []
    for product, info in canada_quotes.PRODUCTS.items():
        try:
            _table, check = canada_quotes.live(product, force=True)
            said.append('%s: %s' % (info['label'], {True: 'same as the check before', False: 'CHANGED since the check before',
                                                     None: 'read (nothing to compare with yet)'}[check['same']]))
        except canada_quotes.Unavailable as e:
            said.append('%s: could not be read (%s)' % (info['label'], e))
    flash('Secure Travel checked. ' + ' · '.join(said), 'info')
    return redirect(url_for('admin.canada_quotes_admin'))
