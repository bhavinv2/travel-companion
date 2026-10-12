"""Answer suggestions: the customer's question in, the best ready answers out.

Two libraries are searched together: the CRM's own answers (Sales CRM -> Setup -> Answers, seeded
from the FAQ sheet of Sales Process 1.5) and the public Help & FAQ that admins already keep up to
date for each product. Matching is plain word overlap with a little stemming -- no AI service, no
cost per question, and an answer that comes up is always one somebody on the team wrote.

Scoring, per answer: every word of the question found in the answer's question or keywords counts
three, found only in its text counts one; words of five letters or more also match by their first
five letters ("insured" finds "insurance"). Answers for the lead's own product count a third more.
"""
import math
import re

from app.models import CrmAnswer

STOP = set('''a about above after again all am an and any are as at be because been before being
below between both but by can could did do does doing down during each few for from further had
has have having he her here hers him his how i if in into is it its just me more most my no nor
not now of off on once only or other our out over own same she should so some such than that the
their them then there these they this those through to too under until up very was we were what
when where which while who whom why will with would you your yours hi hello hey dear sir madam
please thanks thank pls kindly want need know tell let get got also like okay ok yes'''.split())

WORD = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)?")
HELP_SITE = {'TI': 'insurance', 'SH': 'sahayak', 'TC': 'companion'}


def _stem(w):
    for suf in ('ing', 'ies', 'ed', 'es', 's'):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[:-len(suf)] + ('y' if suf == 'ies' else '')
    return w


def tokens(text):
    out = []
    for w in WORD.findall((text or '').lower()):
        for part in w.split('-'):
            if part and part not in STOP and (len(part) > 2 or part.isdigit()):
                out.append(_stem(part))
    return out


def _hit(word, bag, prefixes):
    return word in bag or (len(word) >= 5 and word[:5] in prefixes)


def _score(q, head, body):
    hb, bb = set(head), set(body)
    hp, bp = {w[:5] for w in hb if len(w) >= 5}, {w[:5] for w in bb if len(w) >= 5}
    s = 0.0
    for w in set(q):
        if _hit(w, hb, hp):
            s += 3
        elif _hit(w, bb, bp):
            s += 1
    return s / math.sqrt(max(len(set(q)), 1))


def library(product=None):
    """Every answer that could be suggested: (id, kind, product, title, body)."""
    from app.services import help_center
    # answers only: a quick message (it has a code) is picked by hand, never suggested
    rows = [('a%d' % a.id, 'answer', a.product, a.title, a.body, a.keywords or '')
            for a in CrmAnswer.query.filter(CrmAnswer.code.is_(None)).all()]
    by_site = {v: k for k, v in HELP_SITE.items()}
    for site in help_center.SITE_KEYS:
        for f in help_center.faqs(site):
            rows.append(('f%s' % f.get('id'), 'faq', by_site.get(site, 'GEN'),
                         f.get('question') or '', f.get('answer') or '', ''))
    return rows


def suggest(text, product=None, limit=3):
    """The best `limit` answers for `text`, best first: [{'id','kind','title','body','score'}]."""
    q = tokens(text)
    if not q:
        return []
    scored = []
    for rid, kind, prod, title, body, keywords in library(product):
        s = _score(q, tokens(title + ' ' + keywords), tokens(body))
        if s <= 0:
            continue
        if product and prod == product:
            s *= 1.33
        elif product and prod not in (product, 'GEN'):
            s *= 0.8
        scored.append({'id': rid, 'kind': kind, 'product': prod, 'title': title, 'body': body,
                       'score': round(s, 3)})
    scored.sort(key=lambda r: -r['score'])
    # an own answer and the public FAQ often say the same thing twice; keep the better one
    out, seen = [], set()
    for r in scored:
        key = tokens(r['title'])[:4]
        sig = ' '.join(sorted(key))
        if sig in seen:
            continue
        seen.add(sig)
        out.append(r)
        if len(out) == limit:
            break
    return out
