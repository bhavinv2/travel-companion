"""Results -> "Download for Excel": the same numbers the screen shows, for the same days, pipeline and person.

One CSV, a block per card or table on the screen, a blank line between blocks:

    the filters, the cards (value, the days before, change), the funnel, where customers come from (and by
    campaign), messages by who sent them, quotes and payment links, why we lost leads, day by day.

`rows(...)` returns plain lists (cells are text or numbers) so the route only has to write them out.
"""
from app.services import crm_money, crm_numbers, crm_words

CARDS = (('new_leads', 'New leads'), ('replied', 'Replied'), ('quoted', 'Quoted'), ('won', 'Won in these days'),
         ('first_contact', 'First contact time (minutes, people only)'),
         ('reply_time', 'Reply time (minutes, people only)'), ('waiting_now', 'Customers waiting now'))
COMPARED = ('new_leads', 'replied', 'quoted', 'won')      # the cards that are compared with the days before


def change(now, before):
    """The card's change in percent against the days before, as the screen shows it: '' when there was nothing
    before and nothing now, 'new' when there was nothing before but something now."""
    a, b = now or 0, before or 0
    if b:
        return round((a - b) / b * 100)
    return 'new' if a else ''


def rows(days, first, last, pipe, person, cards, before, funnel, sources, senders, milestones, reasons,
         day_list, groups, money=None, money_before=None, top=None):
    out = [['Sales results'], ['Days', days, 'From', first.isoformat(), 'To', last.isoformat()],
           ['Pipeline', pipe.name if pipe else 'Every pipeline'],
           ['Whose numbers', person.full_name if person else 'The whole team'], []]
    out += [['Numbers', 'This period', 'The period before', 'Change %', 'What it counts']]
    for key, label in CARDS:
        v = cards.get(key)
        out.append([label, '' if v is None else v, before.get(key, '') if key in COMPARED else '',
                    change(v, before.get(key)) if key in COMPARED else '', crm_numbers.card_definition(key)])
    if money is not None:
        cur = crm_money.reporting_currency()
        for key, label in (('amount', 'Won value (%s)' % cur), ('revenue', 'Our revenue (%s)' % cur)):
            v, b = crm_money.plain_amount(money[key]), crm_money.plain_amount((money_before or {}).get(key))
            out.append([label, v, b, change(float(money[key]), float((money_before or {}).get(key) or 0)),
                        crm_numbers.definition('won_value' if key == 'amount' else 'revenue')])
        if money.get('missing_rates'):
            out.append([crm_money.rate_warning(money['missing_counts'])])
    out += [[], ['Leads that came in these days, and how far each one got', 'Leads', '% of the step before']]
    for r in funnel['rows']:
        out.append([r['label'], r['n'], '' if r['pct'] is None else r['pct']])
    out.append(['Lost', funnel['lost'], ''])
    out += [[], ['Where customers come from', 'Leads', 'Replied', 'Won', 'Won %']]
    names = crm_words.product_names()
    for r in sources['rows']:
        out.append([crm_words.source_display(r['name'], names), r['leads'], r['replied'], r['won'], r['pct']])
    if sources['campaigns']:
        out += [[], ['By campaign', 'Leads', 'Replied', 'Won', 'Won %']]
        out += [[r['name'], r['leads'], r['replied'], r['won'], r['pct']] for r in sources['campaigns']]
    if top:
        out += [[], ['Top sellers', 'Deals won', 'Won value', "% of their target"]]
        out += [[r['user'].full_name, r['deals'], crm_money.plain_amount(r['amount']),
                 '' if r['pct'] is None else r['pct']] for r in top]
    out += [[], ['Messages, by who sent them', 'Messages']] + [[a, n] for a, n in senders]
    out += [[], ['Quotes and payment links', 'Times']] + [[a, n] for a, n in milestones]
    out += [[], ['Why we lost leads', 'Leads']] + [[a, n] for a, n in reasons]
    out += [[], ['Day by day', 'Total'] + [d.isoformat() for d in day_list]]
    for group, grid in groups:
        out.append([group])
        for key, label, how, vals, total in grid:
            out.append([label, '' if total is None else total] + ['' if v is None else v for v in vals])
    return out
