"""The sidebars beside a blog post (admin Blog › Sidebars): flyers, ads, links and more, left and right of the words.

A wide screen has room either side of a post; these cards fill it. Each card (models.BlogSideCard) is one of KINDS,
sits in the left or the right sidebar in its place (sort_order), and shows on every post, on the posts of some
categories, or on some posts -- from a start until an end when those are set. Phones have no sidebars: a card shows
under the post there, or not at all (look['phone']).

How wide each sidebar is and whether its last card stays in view while reading are the blog's own settings
(SETTING); how tall a card is, how its picture fits and its colours are the card's (`look`). The manager drags a
card's bottom edge to make it taller or shorter, and drags the sidebar's edge to make it wider.

A tap on a card's link goes through /blog/go/<id> (routes/blog.py), which counts it and sends the reader on: the
address is the card's own, typed by staff, so nothing a reader sends can choose where they land.
"""
import re
from datetime import datetime

from app import db
from app.models import Blog, BlogPattern, BlogSideCard, BlogTerm

# (key, name, icon, what it is)
KINDS = [
    ('flyer', 'Flyer', 'fa-image', 'A picture -- a poster, an offer -- that opens a link when tapped.'),
    ('ad', 'Ad', 'fa-bullhorn', 'A picture, a few words and a button.'),
    ('links', 'Links', 'fa-link', 'A short list of links: your services, forms, other sites.'),
    ('contents', 'On this page', 'fa-list-ol', "The post's own headings, to jump to. It makes itself."),
    ('more', 'More stories', 'fa-newspaper', 'The newest posts from the same category. It makes itself.'),
    ('block', 'Reusable block', 'fa-recycle', 'One of your reusable blocks: columns, a carousel, a video ...'),
]
KIND_KEYS = [k for k, *_ in KINDS]
KIND_BY_KEY = {k: {'key': k, 'name': n, 'icon': i, 'hint': h} for k, n, i, h in KINDS}
THEMES = [('card', 'White card'), ('plain', 'No box'), ('soft', 'Cream'), ('blue', 'Light blue'),
          ('navy', 'Navy'), ('coral', 'Orange'), ('green', 'Green')]
THEME_KEYS = [k for k, _ in THEMES]
FITS = [('whole', 'Show the whole picture'), ('fill', 'Fill the box (the edges may be cut)')]
PHONES = [('below', 'Under the post'), ('hide', 'Not on phones')]
SHOW_ON = [('all', 'Every post'), ('cats', 'Posts in these categories'), ('posts', 'These posts only')]
SIDES = ('left', 'right')

SETTING = 'blog.sidebars'
RAIL_DEFAULT = {'left': {'width': 260, 'sticky': True}, 'right': {'width': 300, 'sticky': True}}
WIDTH_MIN, WIDTH_MAX = 200, 360
HEIGHT_MIN, HEIGHT_MAX = 80, 1200
COUNT_MIN, COUNT_MAX, COUNT_DEFAULT = 2, 8, 4
MAX_LINKS = 12

# a new card of each kind starts like this
LOOK_DEFAULT = {
    'flyer': {'theme': 'plain', 'fit': 'whole', 'phone': 'below'},
    'ad': {'theme': 'card', 'fit': 'fill', 'phone': 'below'},
    'links': {'theme': 'card', 'phone': 'below'},
    'contents': {'theme': 'plain', 'phone': 'hide'},
    'more': {'theme': 'card', 'phone': 'hide', 'count': COUNT_DEFAULT},
    'block': {'theme': 'plain', 'phone': 'below'},
}
SIDE_DEFAULT = {'contents': 'left'}


def _clamp(v, lo, hi):
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------------------------- the two sidebars

def rails():
    """{'left': {'width', 'sticky'}, 'right': {...}}: how wide each sidebar is, and whether its last card stays
    in view while the post is read."""
    from app.services.settings import get_setting
    saved = get_setting(SETTING) or {}
    out = {}
    for side in SIDES:
        mine = saved.get(side) if isinstance(saved, dict) and isinstance(saved.get(side), dict) else {}
        out[side] = {'width': _clamp(mine.get('width'), WIDTH_MIN, WIDTH_MAX) or RAIL_DEFAULT[side]['width'],
                     'sticky': bool(mine.get('sticky', RAIL_DEFAULT[side]['sticky']))}
    return out


def set_rail(side, width=None, sticky=None, actor=None):
    if side not in SIDES:
        return None
    from app.services.settings import set_setting
    now = rails()
    if width is not None:
        now[side]['width'] = _clamp(width, WIDTH_MIN, WIDTH_MAX) or now[side]['width']
    if sticky is not None:
        now[side]['sticky'] = bool(sticky)
    set_setting(SETTING, now, actor=actor)
    return now[side]


# ---------------------------------------------------------------------------------------------- one card

def look(card):
    """The card's look, every key filled in."""
    base = dict(LOOK_DEFAULT.get(card.kind, {'theme': 'card', 'phone': 'below'}))
    base.setdefault('fit', 'whole')
    base.setdefault('count', COUNT_DEFAULT)
    base['height'] = None
    mine = card.look if isinstance(card.look, dict) else {}
    if mine.get('theme') in THEME_KEYS:
        base['theme'] = mine['theme']
    if mine.get('fit') in ('whole', 'fill'):
        base['fit'] = mine['fit']
    if mine.get('phone') in ('below', 'hide'):
        base['phone'] = mine['phone']
    base['height'] = _clamp(mine.get('height'), HEIGHT_MIN, HEIGHT_MAX) if mine.get('height') else None
    base['count'] = _clamp(mine.get('count'), COUNT_MIN, COUNT_MAX) or base['count']
    return base


def set_look(card, **changes):
    """Change some of the card's look (a new dict: the JSON column only notices a new value)."""
    now = dict(card.look) if isinstance(card.look, dict) else {}
    for k, v in changes.items():
        if k == 'height':
            v = _clamp(v, HEIGHT_MIN, HEIGHT_MAX) if v else None
        now[k] = v
    card.look = {k: v for k, v in now.items() if v is not None}


def status(card, now=None):
    """'on', 'off' (switched off), 'later' (starts later) or 'ended'."""
    now = now or datetime.utcnow()
    if not card.is_on:
        return 'off'
    if card.starts_at and card.starts_at > now:
        return 'later'
    if card.ends_at and card.ends_at <= now:
        return 'ended'
    return 'on'


def shows_on(card, post):
    """Is the card meant for this post (whatever the time)? `post` may be a preview without an id."""
    if card.show_on == 'cats':
        mine = set(card.term_ids or [])
        have = {t.id for t in list(getattr(post, 'categories', []) or []) + list(getattr(post, 'tags', []) or [])
                if getattr(t, 'id', None)}
        return bool(mine & have)
    if card.show_on == 'posts':
        return bool(getattr(post, 'id', None)) and post.id in set(card.post_ids or [])
    return True


def headings(html):
    """How many headings (H2/H3) a post has: "On this page" needs two."""
    return len(re.findall(r'<h[23]\b', html or '', re.I))


def more_posts(card, post):
    """The newest live posts in the post's categories (then the newest of all), not the post itself."""
    n = look(card)['count']
    me = getattr(post, 'id', None) or 0
    cats = [t.id for t in (getattr(post, 'categories', None) or []) if getattr(t, 'id', None)]
    out = []
    if cats:
        out = (Blog.live().filter(Blog.id != me, Blog.terms.any(BlogTerm.id.in_(cats)))
               .order_by(Blog.published_at.desc()).limit(n).all())
    if len(out) < n:
        out += (Blog.live().filter(Blog.id.notin_([me] + [p.id for p in out]))
                .order_by(Blog.published_at.desc()).limit(n - len(out)).all())
    return out


def ready(card, post=None):
    """Has the card what it needs to show? (A flyer needs its picture, links need a link ...)"""
    k = card.kind
    if k == 'flyer':
        return bool(card.image_url)
    if k == 'ad':
        return bool(card.image_url or card.title or card.body)
    if k == 'links':
        return bool(card.links)
    if k == 'block':
        return card.pattern is not None and bool((card.pattern.content or '').strip())
    if k == 'contents':
        return post is None or headings(getattr(post, 'content', '')) >= 2
    return k == 'more'


def live_cards(now=None):
    now = now or datetime.utcnow()
    return (BlogSideCard.query.filter(BlogSideCard.is_on.is_(True))
            .filter(db.or_(BlogSideCard.starts_at.is_(None), BlogSideCard.starts_at <= now))
            .filter(db.or_(BlogSideCard.ends_at.is_(None), BlogSideCard.ends_at > now))
            .order_by(BlogSideCard.side, BlogSideCard.sort_order, BlogSideCard.id).all())


def for_post(post, now=None):
    """What a post's page shows beside it: {'left': [cards], 'right': [cards], 'below': [cards for phones],
    'rails': rails(), 'more': {card id: [posts]}}."""
    out = {'left': [], 'right': [], 'below': [], 'rails': rails(), 'more': {}}
    for card in live_cards(now):
        if card.side not in SIDES or not shows_on(card, post) or not ready(card, post):
            continue
        if card.kind == 'more':
            posts = more_posts(card, post)
            if not posts:
                continue
            out['more'][card.id] = posts
        out[card.side].append(card)
    out['below'] = [c for c in out['left'] + out['right'] if look(c)['phone'] == 'below']
    return out


def click(card, i=None):
    """Where a tap on the card goes (None: nowhere), counted."""
    url = card.link_url
    if card.kind == 'links':
        links = card.links or []
        url = links[i]['url'] if i is not None and 0 <= i < len(links) else None
    if not url:
        return None
    db.session.execute(db.update(BlogSideCard).where(BlogSideCard.id == card.id)
                       .values(clicks=BlogSideCard.clicks + 1))
    db.session.commit()
    return url


# ---------------------------------------------------------------------------------------------- the manager

def cards():
    """Every card, each sidebar in its order."""
    return BlogSideCard.query.order_by(BlogSideCard.side, BlogSideCard.sort_order, BlogSideCard.id).all()


def new_card(kind, side=None):
    kind = kind if kind in KIND_KEYS else 'flyer'
    side = side if side in SIDES else SIDE_DEFAULT.get(kind, 'right')
    return BlogSideCard(kind=kind, side=side, name='', is_on=True, show_on='all', look=dict(LOOK_DEFAULT[kind]))


def _next_place(side):
    top = db.session.query(db.func.max(BlogSideCard.sort_order)).filter(BlogSideCard.side == side).scalar()
    return (top or 0) + 1


def from_form(card, f):
    """Fill `card` from the editor's form; [what is wrong] (empty: it can be saved)."""
    from app.services import blog_engine as be
    from app.services.blog_posts import parse_ist
    errors = []
    kind = f.get('kind') if f.get('kind') in KIND_KEYS else card.kind
    card.kind = kind
    side = f.get('side') if f.get('side') in SIDES else (card.side or 'right')
    if card.id is None or side != card.side:
        card.sort_order = _next_place(side)
    card.side = side
    card.title = (f.get('title') or '').strip()[:120] or None
    card.body = (f.get('body') or '').strip()[:600] or None
    image = (f.get('image_url') or '').strip()
    card.image_url = (be._safe_url(image, image=True) or '')[:500] or None
    if image and not card.image_url:
        errors.append('That picture address cannot be used: upload the picture instead.')
    card.image_alt = (f.get('image_alt') or '').strip()[:300] or None
    link = (f.get('link_url') or '').strip()
    card.link_url = (be._safe_url(link) or '')[:500] or None
    if link and not card.link_url:
        errors.append('The link must start with https://, http://, / (a page of this site), mailto: or tel:.')
    card.link_label = (f.get('link_label') or '').strip()[:60] or None
    card.new_tab = f.get('new_tab') == 'on'
    links = []
    for label, url in zip(f.getlist('link_label_n'), f.getlist('link_url_n')):
        label, url = (label or '').strip()[:80], (url or '').strip()
        if not label and not url:
            continue
        safe = be._safe_url(url)
        if not safe:
            errors.append('“%s”: a link must start with https://, http://, / , mailto: or tel:.' % (label or url)[:40])
            continue
        links.append({'label': label or safe[:80], 'url': safe[:500]})
    card.links = links[:MAX_LINKS] or None
    pattern = db.session.get(BlogPattern, _clamp(f.get('pattern_id'), 1, 2 ** 31) or 0)
    card.pattern_id = pattern.id if pattern else None
    card.pattern = pattern
    height = f.get('height_mode') == 'fixed' and _clamp(f.get('height'), HEIGHT_MIN, HEIGHT_MAX)
    card.look = {k: v for k, v in {
        'theme': f.get('theme') if f.get('theme') in THEME_KEYS else LOOK_DEFAULT[kind]['theme'],
        'fit': f.get('fit') if f.get('fit') in ('whole', 'fill') else LOOK_DEFAULT[kind].get('fit'),
        'phone': f.get('on_phone') if f.get('on_phone') in ('below', 'hide') else LOOK_DEFAULT[kind]['phone'],
        'height': height or None,
        'count': _clamp(f.get('count'), COUNT_MIN, COUNT_MAX) if kind == 'more' else None,
    }.items() if v is not None}
    card.show_on = f.get('show_on') if f.get('show_on') in ('all', 'cats', 'posts') else 'all'
    terms = sorted({i for i in (_clamp(x, 1, 2 ** 31) for x in f.getlist('terms')) if i})
    posts = sorted({i for i in (_clamp(x, 1, 2 ** 31) for x in f.getlist('posts')) if i})
    card.term_ids = [t.id for t in BlogTerm.query.filter(BlogTerm.id.in_(terms or [0]))] or None
    card.post_ids = [p.id for p in Blog.query.filter(Blog.id.in_(posts or [0]))] or None
    if card.show_on == 'cats' and not card.term_ids:
        errors.append('Pick at least one category, or show it on every post.')
    if card.show_on == 'posts' and not card.post_ids:
        errors.append('Pick at least one post, or show it on every post.')
    card.starts_at = parse_ist(f.get('starts_at'))
    card.ends_at = parse_ist(f.get('ends_at'))
    if card.starts_at and card.ends_at and card.ends_at <= card.starts_at:
        errors.append('It must end after it starts.')
    card.is_on = f.get('is_on') == 'on'
    name = (f.get('name') or '').strip()[:120]
    card.name = name or (card.title or KIND_BY_KEY[kind]['name'])[:120]
    if not ready(card):
        errors.append({'flyer': 'A flyer needs its picture.',
                       'ad': 'An ad needs a picture, a heading or some words.',
                       'links': 'Add at least one link.',
                       'block': 'Pick a reusable block (make one in the editor first).'}.get(kind, ''))
    return [e for e in errors if e]


def set_order(left, right):
    """Both sidebars in the order dragged: [card ids] each. A card dragged across changes side."""
    n = 0
    for side, ids in (('left', left), ('right', right)):
        for place, cid in enumerate(i for i in (_clamp(x, 1, 2 ** 31) for x in ids) if i):
            card = db.session.get(BlogSideCard, cid)
            if card is not None:
                card.side, card.sort_order = side, place + 1
                n += 1
    return n


def copy(card, user=None):
    twin = BlogSideCard(**{c.name: getattr(card, c.name) for c in BlogSideCard.__table__.columns
                           if c.name not in ('id', 'created_at', 'updated_at', 'clicks', 'created_by_id')})
    twin.name = ('Copy of %s' % card.name)[:120]
    twin.is_on = False                          # a copy waits until it is changed and switched on
    twin.sort_order = _next_place(card.side)
    twin.created_by_id = getattr(user, 'id', None)
    db.session.add(twin)
    return twin


def where_label(card, names):
    """'Every post', 'Travel Insurance, Visas' or '2 posts' (`names`: {term id: name})."""
    if card.show_on == 'cats':
        got = [names.get(i) for i in (card.term_ids or []) if names.get(i)]
        return ', '.join(got) if got else 'No category'
    if card.show_on == 'posts':
        n = len(card.post_ids or [])
        return '%d post%s' % (n, '' if n == 1 else 's')
    return 'Every post'


def preview_post(target):
    """What the manager's preview stands for: 'all' (every card), 'cat:<id>' or 'post:<id>' ->
    (a post-like thing, its label); (None, 'Every post') for 'all'."""
    from types import SimpleNamespace
    kind, _, ident = (target or '').partition(':')
    i = _clamp(ident, 1, 2 ** 31)
    if kind == 'cat' and i:
        t = db.session.get(BlogTerm, i)
        if t is not None:
            return SimpleNamespace(id=None, categories=[t], tags=[], content=''), 'Posts in %s' % t.name
    if kind == 'post' and i:
        p = db.session.get(Blog, i)
        if p is not None:
            return p, p.title
    return None, 'Every post'
