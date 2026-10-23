"""Blog studio: Word documents in, blog posts out.

The writer downloads the template (template_docx) and writes the post in Word (or Google Docs,
downloaded as .docx); an admin uploads one or several documents (import_upload). Every document
becomes a DRAFT post, and the editor (routes/admin_blog.py) lists the rules it breaks (checks)
until somebody publishes it.

Writers are not technical, so the format is Word itself -- nothing to learn but three words:

  Post details box (a table at the top)      Title / Summary / Cover picture / Cover description /
                                             Web address. "Title:" and "Summary:" lines at the top
                                             work too; without either, the first line is the title.
  Word's Heading 2 / Heading 3 styles        section headings (a short all-bold line also is one --
                                             a guess, and the import report says so)
  a picture pasted or inserted               a picture right there: its Word "Alt Text" says what it
                                             shows, an italic line right under it is its caption. A
                                             picture before the post starts is the cover.
  Tip: ...   Quote: ...   Button: <linked words>   a tip box, a pull quote, a button
  everything else                            as written: bold, italics, underline, links, lists, tables

The template's yellow boxes (the "how to use" box at the top, the writing guide at the end) are for
the writer and never published: a table whose first words are in GUIDE_MARKS is skipped.

The older label format still reads, for anyone who keeps pictures as separate files (a zip):
@title: @slug: @summary: @cover: @cover-alt: @h2 @h3 @image: file | alt | caption, @quote: @note:
@cta: text | link, @divider, and // writer notes.

Nothing here trusts HTML it is given. Content is rebuilt through an allowlist (sanitize) on every
save, and again when the public page shows it (render).
"""
import hashlib
import io
import posixpath
import re
import zipfile
from functools import lru_cache
from html import escape, unescape
from html.parser import HTMLParser
from xml.etree import ElementTree as ET

from flask import current_app
from slugify import slugify

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
PKG_REL = '{http://schemas.openxmlformats.org/package/2006/relationships}'
WP = '{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}'
A = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
V = '{urn:schemas-microsoft-com:vml}'
O = '{urn:schemas-microsoft-com:office:office}'
DOCX_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'

MAX_DOCX = 40 * 1024 * 1024          # one Word file, its pictures inside it
MAX_XML_PART = 30 * 1024 * 1024      # one part inside it, unpacked (a zip bomb stops here)
MAX_EMBEDDED = 25 * 1024 * 1024      # one picture inside it, unpacked (Word keeps the original photo)
MAX_IMAGES = 200
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGES_TOTAL = 150 * 1024 * 1024
IMAGE_EXT = ('jpg', 'jpeg', 'png', 'webp')
COVER_WIDTH = 1200                   # the share card is 1200 x 630
BODY_WIDTH = 1600                    # wider than the column ever shows
KEEP_AS_IS = 400 * 1024              # a picture this small and narrow enough is stored untouched
PNG_TO_JPEG = 500 * 1024             # Word keeps pasted photos as PNG: one this big without see-through parts goes JPG

# The rules the checks apply (and the guide page and the template repeat)
TITLE_GOOD = (20, 65)
SUMMARY_GOOD = (70, 160)
MIN_WORDS = 300
WORDS_PER_H2 = 450
LONG_PARAGRAPH = 120
HEADING_GUESS_MAX = 100              # an all-bold line longer than this is a bold paragraph

LABELS = {
    'title': 'title', 'slug': 'slug', 'address': 'slug', 'url': 'slug',
    'summary': 'summary', 'description': 'summary', 'excerpt': 'summary', 'meta': 'summary',
    'cover': 'cover', 'cover-image': 'cover', 'cover-picture': 'cover',
    'cover-alt': 'cover-alt', 'coveralt': 'cover-alt', 'cover-description': 'cover-alt',
    'h1': 'h2', 'h2': 'h2', 'heading': 'h2', 'h3': 'h3', 'h4': 'h3', 'subheading': 'h3', 'sub-heading': 'h3',
    'image': 'image', 'img': 'image', 'picture': 'image', 'photo': 'image',
    'quote': 'quote', 'note': 'note', 'tip': 'note', 'cta': 'cta', 'button': 'cta',
    'divider': 'divider', 'line': 'divider',
}
DETAILS = ('title', 'slug', 'summary', 'cover', 'cover-alt')

# What the guide shows -- on the import page and at the end of the Word template, from these same
# lists, so the two never differ: (what you do in Word, what it becomes)
FORMAT_RULES = (
    ('The Title box — or simply the first line', 'The post title.'),
    ('The Summary box', 'What Google, WhatsApp shares and the blog list show. 1–2 sentences, 70–160 characters.'),
    ('A picture in the Cover picture box — or a picture above the first paragraph', 'The cover picture at the top of the post.'),
    ('Word’s Heading 2 (Home → Styles), or a short line in bold', 'A section heading.'),
    ('Word’s Heading 3', 'A smaller heading inside a section.'),
    ('Bold, italics, underline, links (Ctrl+K), bullet points, numbering, tables', 'Kept just as they are.'),
    ('A picture pasted or inserted anywhere (Insert → Pictures)', 'A picture in that place. Right-click it → Edit Alt Text to say what it shows.'),
    ('An italic line right under a picture', 'That picture’s caption.'),
    ('A line that starts with Tip:', 'A highlighted tip box.'),
    ('A line that starts with Quote:', 'A large pull quote.'),
    ('A line that starts with Button: — with the words linked (Ctrl+K)', 'A button to that page.'),
)
# The older label format: for pictures kept as separate files and sent as a zip
ADVANCED_RULES = (
    ('@title: How to buy travel insurance for parents', 'The post title. Required (or make it the first line).'),
    ('@slug: travel-insurance-for-parents', 'The address: /blog/travel-insurance-for-parents. Optional, made from the title.'),
    ('@summary: One or two sentences, 70–160 characters', 'Shown in Google results, shares and the blog list.'),
    ('@cover: parents-insurance-cover.jpg', 'The cover picture, from the zip.'),
    ('@cover-alt: Indian parents at a US airport', 'What the cover shows, for Google and screen readers.'),
    ('@h2 Compare the plans', 'A section heading (or Word’s Heading 2 style).'),
    ('@h3 Policy maximum', 'A smaller heading inside a section (or Heading 3).'),
    ('@image: parents-insurance-1.jpg | A doctor with an elderly patient | Optional caption',
     'A picture from the zip: file name | what it shows | caption.'),
    ('@quote: The best plan is not the cheapest one.', 'A pull quote.'),
    ('@note: Check whether the policy can be extended.', 'A highlighted tip box.'),
    ('@cta: Get a free quote | /travel-insurance', 'A button: its text | where it goes (a site path or https:// link).'),
    ('@divider', 'A line across the page.'),
    ('// anything', 'A note for the writer. Never published.'),
)
IMAGE_RULES = (
    'Paste or insert pictures straight into the document, where they belong. Nothing else to send.',
    'The cover is landscape, about 1200 × 630 — it is also the picture WhatsApp and Facebook show.',
    'Pictures in the post look best at least 1200 px wide. Big ones are made smaller for you.',
    'Right-click a picture → Edit Alt Text and say in a few words what it shows.',
    'Photos and screenshots (JPG or PNG) work best. Only use pictures you have the right to use.',
    'Do not put text inside a picture: write it in the post, where Google and phones can read it.',
)
# What the checks in the editor stop and suggest (blog_engine.checks): (what happens, which ones)
CHECK_RULES = (
    ('Stops publishing', 'No title, an address another post already uses, an empty post, a picture that could not be read.'),
    ('Suggestions', 'A long title, a summary that is too short or too long, no cover picture, pictures without a '
                    'description, fewer than %d words, no section headings, very long paragraphs, http:// links.' % MIN_WORDS),
)
ADVANCED_IMAGE_RULES = (
    'Name each file in lowercase with hyphens, no spaces: parents-insurance-cover.jpg, parents-insurance-1.jpg …',
    'Use exactly the file name you wrote after @cover or @image, and put all of them in one .zip.',
    'JPG, PNG or WebP, under 10 MB each.',
)


# The first words of the template's boxes for the writer: a table starting with one is never published
GUIDE_MARKS = ('how to use this template', 'writing guide')


class DocxError(ValueError):
    """A file that cannot be read as a Word document, said for the person who uploaded it."""


class ImageError(ValueError):
    pass


# ============================================================================== reading .docx

def _on(rpr, tag):
    if rpr is None:
        return False
    el = rpr.find(W + tag)
    if el is None:
        return False
    return (el.get(W + 'val') or 'true').lower() not in ('0', 'false', 'off', 'none')


def _num_of(numpr):
    if numpr is None:
        return None
    nid, lvl = numpr.find(W + 'numId'), numpr.find(W + 'ilvl')
    if nid is None:
        return None
    try:
        return nid.get(W + 'val'), int(lvl.get(W + 'val')) if lvl is not None else 0
    except (TypeError, ValueError):
        return None


class _Doc:
    """One open .docx: its styles, list numbering and link targets."""

    def __init__(self, data):
        if len(data) > MAX_DOCX:
            raise DocxError('This file is larger than 40 MB. Make the pictures in it smaller '
                            '(click a picture → Picture Format → Compress Pictures) and save it again.')
        if data[:4] == b'\xd0\xcf\x11\xe0':
            raise DocxError('This is an old Word file (.doc). Open it in Word and save it as .docx.')
        try:
            self.zip = zipfile.ZipFile(io.BytesIO(data))
        except (zipfile.BadZipFile, ValueError):
            raise DocxError('This is not a Word document (.docx).')
        self.root = self._part('word/document.xml')
        if self.root is None or self.root.find(W + 'body') is None:
            raise DocxError('This is not a Word document (.docx).')
        self._read_styles()
        self._read_numbering()
        self._read_links()

    def _part(self, name):
        try:
            info = self.zip.getinfo(name)
        except KeyError:
            return None
        if info.file_size > MAX_XML_PART:
            raise DocxError('This document is too large to read.')
        try:
            return ET.fromstring(self.zip.read(info))
        except ET.ParseError:
            raise DocxError('This Word document is damaged: Word may still open it -- save a fresh copy.')

    def _read_styles(self):
        self.styles = {}
        root = self._part('word/styles.xml')
        for s in (root.iter(W + 'style') if root is not None else ()):
            name, based = s.find(W + 'name'), s.find(W + 'basedOn')
            rpr = s.find(W + 'rPr')
            self.styles[s.get(W + 'styleId')] = {
                'name': ((name.get(W + 'val') if name is not None else '') or '').lower(),
                'based': based.get(W + 'val') if based is not None else None,
                'num': _num_of(s.find(W + 'pPr/' + W + 'numPr')),
                'b': _on(rpr, 'b'), 'i': _on(rpr, 'i')}

    def _chain(self, sid):
        seen = []
        while sid in self.styles and sid not in seen and len(seen) < 8:
            seen.append(sid)
            yield self.styles[sid]
            sid = self.styles[sid]['based']

    def style_kind(self, sid):
        """'title', 'h2', 'h3' or 'quote' for Word's own styles (and styles based on them)."""
        for s in self._chain(sid):
            name = s['name']
            if name == 'title':
                return 'title'
            m = re.match(r'heading (\d)', name)
            if m:
                return 'h2' if int(m.group(1)) <= 2 else 'h3'
            if name in ('quote', 'intense quote'):
                return 'quote'
            if name == 'caption':
                return 'caption'
        return None

    def style_num(self, sid):
        return next((s['num'] for s in self._chain(sid) if s['num']), None)

    def char_style(self, sid):
        s = self.styles.get(sid) or {}
        name = s.get('name', '')
        return {'b': s.get('b') or name == 'strong', 'i': s.get('i') or name == 'emphasis'}

    def _read_numbering(self):
        self.lists = {}
        root = self._part('word/numbering.xml')
        if root is None:
            return
        abstract = {}
        for a in root.iter(W + 'abstractNum'):
            levels = {}
            for lvl in a.findall(W + 'lvl'):
                fmt = lvl.find(W + 'numFmt')
                try:
                    levels[int(lvl.get(W + 'ilvl', '0'))] = fmt.get(W + 'val') if fmt is not None else 'decimal'
                except ValueError:
                    continue
            abstract[a.get(W + 'abstractNumId')] = levels
        for n in root.iter(W + 'num'):
            a = n.find(W + 'abstractNumId')
            if a is not None:
                self.lists[n.get(W + 'numId')] = abstract.get(a.get(W + 'val'), {})

    def list_format(self, num):
        """'bullet', 'decimal', ... for a paragraph's numbering; None when it is not a list."""
        nid, lvl = num
        if nid in (None, '0') or nid not in self.lists:
            return None
        levels = self.lists[nid]
        return levels.get(lvl) or levels.get(0) or 'decimal'

    def _read_links(self):
        self.links, self.media = {}, {}
        root = self._part('word/_rels/document.xml.rels')
        for r in (root.iter(PKG_REL + 'Relationship') if root is not None else ()):
            kind = r.get('Type') or ''
            if kind.endswith('/hyperlink'):
                self.links[r.get('Id')] = r.get('Target')
            elif kind.endswith('/image') and r.get('TargetMode') != 'External':
                self.media[r.get('Id')] = r.get('Target')

    def picture_data(self, rid):
        """(bytes, extension) of a picture inside the document, or None."""
        target = self.media.get(rid)
        if not target:
            return None
        path = target.lstrip('/') if target.startswith('/') else posixpath.normpath(posixpath.join('word', target))
        try:
            info = self.zip.getinfo(path)
        except KeyError:
            return None
        if info.file_size > MAX_EMBEDDED:
            return None
        ext = path.rsplit('.', 1)[-1].lower()
        return self.zip.read(info), {'jpeg': 'jpg', 'jpe': 'jpg'}.get(ext, ext)

    @staticmethod
    def _picture_ref(el):
        """A picture in a run: {'rid', 'link', 'alt'} -- or None for a drawn line or shape."""
        blip = next((x for x in el.iter() if x.tag in (A + 'blip', V + 'imagedata')), None)
        if blip is None:
            return None
        rid = blip.get(R + 'embed') or blip.get(R + 'id')
        doc_pr = next((x for x in el.iter() if x.tag == WP + 'docPr'), None)
        alt = (doc_pr.get('descr') or doc_pr.get('title') or '') if doc_pr is not None else (blip.get(O + 'title') or '')
        return {'rid': rid, 'link': bool(blip.get(R + 'link')) and not rid, 'alt': alt}

    # ---- the body, block by block
    def blocks(self, node=None):
        for el in (node if node is not None else self.root.find(W + 'body')):
            if el.tag == W + 'p':
                yield 'p', self.paragraph(el)
            elif el.tag == W + 'tbl':
                yield 'table', [[[self.paragraph(p) for p in tc.iter(W + 'p')] for tc in tr.findall(W + 'tc')]
                                for tr in el.findall(W + 'tr')]
            elif el.tag == W + 'sdt':
                content = el.find(W + 'sdtContent')
                if content is not None:
                    yield from self.blocks(content)
            elif el.tag == W + 'customXml':
                yield from self.blocks(el)

    def paragraph(self, p):
        """{'style', 'num', 'segs': [[text, bold, italic, underline, href]], 'pics': [picture refs]}"""
        ppr = p.find(W + 'pPr')
        sid = num = None
        if ppr is not None:
            st = ppr.find(W + 'pStyle')
            sid = st.get(W + 'val') if st is not None else None
            num = _num_of(ppr.find(W + 'numPr'))
        if num is None and sid:
            num = self.style_num(sid)
        segs, pics, state = [], [], {'field': None, 'instr': '', 'href': None}

        def run(r, href):
            rpr = r.find(W + 'rPr')
            rs = rpr.find(W + 'rStyle') if rpr is not None else None
            cs = self.char_style(rs.get(W + 'val')) if rs is not None else {}
            fmt = [_on(rpr, 'b') or cs.get('b', False), _on(rpr, 'i') or cs.get('i', False), _on(rpr, 'u')]
            for ch in r:
                tag = ch.tag
                if tag == W + 'fldChar':          # a Word field: HYPERLINK "url" written the long way
                    kind = ch.get(W + 'fldCharType')
                    if kind == 'begin':
                        state['field'], state['instr'] = 'instr', ''
                    elif kind == 'separate':
                        m = re.search(r'HYPERLINK\s+"([^"]+)"', state['instr'])
                        state['field'], state['href'] = 'result', (m.group(1) if m else None)
                    elif kind == 'end':
                        state['field'], state['href'] = None, None
                elif tag == W + 'instrText':
                    if state['field'] == 'instr':
                        state['instr'] += ch.text or ''
                elif state['field'] == 'instr':
                    continue
                elif tag == W + 't':
                    segs.append([ch.text or '', *fmt, href or state['href']])
                elif tag == W + 'tab':
                    segs.append([' ', *fmt, href or state['href']])
                elif tag in (W + 'br', W + 'cr'):
                    if ch.get(W + 'type') in (None, 'textWrapping'):
                        segs.append(['\n', False, False, False, None])
                elif tag == W + 'noBreakHyphen':
                    segs.append(['-', *fmt, href or state['href']])
                elif tag in (W + 'drawing', W + 'pict', W + 'object') or tag.endswith('}AlternateContent'):
                    pic = self._picture_ref(ch)       # a photo carries an image reference; a drawn line does not
                    if pic is not None:
                        pics.append(pic)

        def walk(node, href):
            for ch in node:
                tag = ch.tag
                if tag == W + 'r':
                    run(ch, href)
                elif tag == W + 'hyperlink':
                    rid = ch.get(R + 'id')
                    walk(ch, self.links.get(rid) if rid else href)   # a link to a bookmark has no page to go to
                elif tag == W + 'fldSimple':
                    m = re.search(r'HYPERLINK\s+"([^"]+)"', ch.get(W + 'instr') or '')
                    walk(ch, m.group(1) if m else href)
                elif tag in (W + 'ins', W + 'smartTag', W + 'sdt', W + 'sdtContent', W + 'customXml', W + 'moveTo'):
                    walk(ch, href)
                # w:del (a tracked deletion), bookmarks, proofing marks: not text

        walk(p, None)
        return {'style': sid, 'num': num, 'segs': segs, 'pics': pics}


def _clean(segs):
    """Join runs that look the same and trim the paragraph's ends."""
    out = []
    for s in segs:
        if not s[0]:
            continue
        if out and out[-1][1:] == s[1:]:
            out[-1][0] += s[0]
        else:
            out.append(list(s))
    while out and not out[0][0].strip():
        out.pop(0)
    while out and not out[-1][0].strip():
        out.pop()
    if out:
        out[0][0] = out[0][0].lstrip()
        out[-1][0] = out[-1][0].rstrip()
    return out


def _drop(segs, n):
    """The runs after the first n characters (what follows a label, with its formatting)."""
    out = []
    for s in segs:
        if n >= len(s[0]):
            n -= len(s[0])
            continue
        out.append([s[0][n:], *s[1:]])
        n = 0
    return _clean(out)


def link_ok(href):
    href = (href or '').strip()
    return bool(re.match(r'(https?://|mailto:|tel:)', href, re.I) or (href.startswith('/') and not href.startswith('//')))


def _inline(segs):
    def fmt(s):
        text, b, i, u, _ = s
        t = escape(text, quote=False).replace('\n', '<br/>')
        if not text.strip():
            return t
        if u:
            t = '<u>%s</u>' % t
        if i:
            t = '<em>%s</em>' % t
        if b:
            t = '<strong>%s</strong>' % t
        return t
    out, i = [], 0
    while i < len(segs):
        href, j = segs[i][4], i
        while j < len(segs) and segs[j][4] == href:
            j += 1
        inner = ''.join(fmt(s) for s in segs[i:j])
        out.append('<a href="%s">%s</a>' % (escape(href.strip()), inner) if href and link_ok(href) else inner)
        i = j
    return ''.join(out)


def _list_html(items):
    """[(ordered, level, html)] -> nested <ul>/<ol>."""
    out, stack = [], []
    for ordered, level, html in items:
        tag = 'ol' if ordered else 'ul'
        level = min(level, len(stack))                 # never more than one level deeper at a time
        while len(stack) > level + 1:
            out.append('</li></%s>' % stack.pop())
        if len(stack) == level + 1:
            if stack[-1] == tag:
                out.append('</li><li>%s' % html)
                continue
            out.append('</li></%s>' % stack.pop())
        out.append('<%s><li>%s' % (tag, html))
        stack.append(tag)
    while stack:
        out.append('</li></%s>' % stack.pop())
    return ''.join(out)


def _label(plain):
    """(key, characters the label takes) for a line starting with @, or (None, 0)."""
    m = re.match(r'@([A-Za-z][\w -]{0,24}?)\s*:\s*', plain)
    if m and _key(m.group(1)):
        return _key(m.group(1)), m.end()
    m = re.match(r'@([A-Za-z][\w-]{0,24})(?:\s+|$)', plain)
    if m and _key(m.group(1)):
        return _key(m.group(1)), m.end()
    return None, 0


def _key(word):
    return LABELS.get(re.sub(r'[\s_]+', '-', word.strip().lower()))


def missing_figure(name, alt='', caption=''):
    cap = '<figcaption>%s</figcaption>' % escape(caption) if caption else ''
    return '<figure class="blog-img blog-img-missing" data-file="%s" data-alt="%s">%s</figure>' % (
        escape(name), escape(alt), cap)


def _clean_alt(alt):
    """Word's Alt Text, without the "Description automatically generated" Word adds to its own guesses."""
    alt = re.sub(r'(?i)(description automatically generated(\s+with\s+\w+\s+confidence)?|'
                 r'ai-generated content may be incorrect)\.?', ' ', alt or '')
    return ' '.join(alt.split())[:200]


def _para_text(p):
    return ''.join(s[0] for s in _clean(p['segs']))


def _first_line(cell):
    return next((t for t in (_para_text(p).strip() for p in cell) if t), '')


def _cell_text(cell):
    return ' '.join(t for t in (_para_text(p).strip() for p in cell) if t)


def _detail_key(label):
    """Which detail a row of the Post details box holds, from its label ("Title", "Cover picture" ...)."""
    words = ' '.join(re.sub(r'[^a-z ]+', ' ', re.sub(r'\(.*?\)', '', (label or '').lower())).split())
    if not words:
        return None
    if words.startswith('cover'):
        return 'cover-alt' if any(w in words for w in ('description', 'alt', 'describe', 'text')) else 'cover'
    if words in ('title', 'post title', 'blog title', 'headline'):
        return 'title'
    if words.startswith('summary') or words in ('short summary', 'description', 'excerpt'):
        return 'summary'
    if words in ('web address', 'address', 'slug', 'url', 'link', 'page address'):
        return 'slug'
    return None


# Plain words at the start of a line. Title / Summary / Web address / Cover description only count
# above the post (where a writer puts details); later on they are ordinary sentences.
_PLAIN = re.compile(r'(tip|note|important|remember|quote|button|caption|post title|title|summary|web address|'
                    r'cover description)\s*[:：]\s*', re.I)
_PLAIN_KEYS = {'tip': 'note', 'note': 'note', 'important': 'note', 'remember': 'note', 'quote': 'quote',
               'button': 'cta', 'caption': 'caption', 'title': 'title', 'post title': 'title',
               'summary': 'summary', 'web address': 'slug', 'cover description': 'cover-alt'}
_TOP_ONLY = ('title', 'summary', 'slug', 'cover-alt')


class _Builder:
    def __init__(self, doc):
        self.doc = doc
        self.meta, self.out, self.items = {}, [], []    # out: HTML strings, and {'name', 'alt', 'caption'} pictures
        self.images, self.notes = [], []                # images: file names the post asks the zip for
        self.embedded, self._seen = {}, {}              # pictures inside the document, by the name the post uses
        self.guessed = 0
        self.title_from_first = self.started = self.after_sample = False
        self.cover_alt_from_picture = ''

    def note(self, text):
        if text not in self.notes:
            self.notes.append(text)

    def _flush(self):
        if self.items:
            self.out.append(_list_html(self.items))
            self.items = []

    def add(self, html):
        self._flush()
        self.out.append(html)
        self.started = True

    def _declares_title(self, blocks):
        for kind, b in blocks:
            if kind == 'table':
                if any(len(row) >= 2 and _detail_key(_first_line(row[0])) == 'title' and _cell_text(row[1])
                       for row in b):
                    return True
                continue
            plain = _para_text(b)
            if (_label(plain)[0] == 'title' or re.match(r'(post\s+)?title\s*[:：]', plain, re.I)
                    or self.doc.style_kind(b['style']) == 'title'):
                return True
        return False

    def build(self):
        blocks = list(self.doc.blocks())
        titled = self._declares_title(blocks)
        for kind, b in blocks:
            if kind == 'table':
                self.table(b)
            else:
                self.paragraph(b, titled)
        self._flush()
        html = '\n'.join(missing_figure(x['name'], x['alt'], x['caption']) if isinstance(x, dict) else x
                         for x in self.out if x)
        if self.title_from_first:
            self.note('There was no title box, so the first line became the title.')
        if self.guessed:
            self.note('%d short bold line%s became section heading%s. Use Word’s Heading 2 style to be sure.'
                      % (self.guessed, '' if self.guessed == 1 else 's', '' if self.guessed == 1 else 's'))
        title = (self.meta.get('title') or '').strip()[:300]
        return {'title': title,
                'slug': slugify(self.meta.get('slug') or title, max_length=80, word_boundary=True),
                'summary': (self.meta.get('summary') or '').strip()[:300],
                'cover': (self.meta.get('cover') or '').strip(),
                'cover_alt': (self.meta.get('cover-alt') or self.cover_alt_from_picture or '').strip()[:300],
                'html': html, 'images': self.images, 'embedded': self.embedded, 'notes': self.notes,
                'words': word_count(html)}

    # ---- paragraphs
    def paragraph(self, para, titled):
        segs = _clean(para['segs'])
        plain = ''.join(s[0] for s in segs)
        after_sample, self.after_sample = self.after_sample, False
        if plain.startswith('//'):
            return
        if plain.strip() and not (after_sample and self._captionish(para, segs, plain)):
            self.text(para, segs, plain, titled)       # (a sample picture's caption goes with it)
        for pic in para['pics']:
            self.picture(pic)

    def _captionish(self, para, segs, plain):
        return (self.doc.style_kind(para['style']) == 'caption' or plain.lower().startswith('caption')
                or (para['num'] is None and len(plain) <= 200 and all(s[2] for s in segs if s[0].strip())))

    def text(self, para, segs, plain, titled):
        if plain.startswith('@'):
            key, used = _label(plain)
            if key:
                return self.labelled(key, plain[used:].strip(), _drop(segs, used))
            self.note('"%s" is not one of the labels, so it was kept as text.' % plain.split()[0][:30])
        m = _PLAIN.match(plain) if para['num'] is None else None
        if m:
            key = _PLAIN_KEYS[' '.join(m.group(1).lower().split())]
            rest, rsegs = plain[m.end():].strip(), _drop(segs, m.end())
            if key in _TOP_ONLY:
                if not self.started and rest:
                    self.meta[key] = rest
                    return
            elif key == 'note' and rsegs:
                return self.add('<aside class="blog-note">%s</aside>' % _inline(rsegs))
            elif key == 'quote' and rsegs:
                return self.add('<blockquote>%s</blockquote>' % _inline(rsegs))
            elif key == 'cta':
                return self.button(rest, rsegs, segs)
            elif key == 'caption' and self.caption(rest):
                return
        kind = self.doc.style_kind(para['style'])
        if (kind == 'caption' or (self._last_figure() is not None and self._captionish(para, segs, plain))) \
                and self.caption(plain):
            return
        if kind == 'title':
            if 'title' not in self.meta:
                self.meta['title'] = plain
                return
            kind = 'h2'
        if kind in ('h2', 'h3'):
            return self.add('<%s>%s</%s>' % (kind, escape(plain), kind))
        if kind == 'quote':
            return self.add('<blockquote>%s</blockquote>' % _inline(segs))
        if para['num'] is not None:
            fmt = self.doc.list_format(para['num'])
            if fmt is not None:
                self.items.append((fmt not in ('bullet', 'none'), para['num'][1], _inline(segs)))
                self.started = True
                return
        if not titled and 'title' not in self.meta and not self.started and len(plain) <= 150:
            self.meta['title'], self.title_from_first = plain, True
            return
        if (all(s[1] for s in segs if s[0].strip()) and len(plain) <= HEADING_GUESS_MAX
                and plain[-1] not in '.!?:;,'):
            self.guessed += 1
            return self.add('<h2>%s</h2>' % escape(plain))
        self.add('<p>%s</p>' % _inline(segs))

    def button(self, rest, segs, line):
        """Button: words -- the link is the one on the words (Ctrl+K), or a site page / https:// address
        typed after them ("Button: Get a quote → /travel-insurance", or "text | link"). Without a link
        the line stays as it was written."""
        href = next((s[4] for s in segs if s[4] and link_ok(s[4])), None)
        text = rest
        if '|' in rest:
            text, _, typed = rest.partition('|')
            href = href or typed.strip()
        else:
            m = re.search(r'(https?://\S+|(?<!\S)/\S*)', rest)
            if m:
                href = href or m.group(1)
                text = rest[:m.start()] + rest[m.end():]
        text = text.strip(' \t-–—→>:|')
        if not text or not link_ok(href):
            self.note('A "Button:" line needs a link: select the button’s words and press Ctrl+K. '
                      '"%s" was kept as text.' % rest[:60])
            return self.add('<p>%s</p>' % _inline(line))
        self.add('<p class="blog-cta-wrap"><a class="blog-cta" href="%s">%s</a></p>' % (escape(href.strip()), escape(text)))

    # ---- pictures
    def _last_figure(self):
        if self.items or not self.out or not isinstance(self.out[-1], dict) or self.out[-1]['caption']:
            return None
        return self.out[-1]

    def caption(self, text):
        fig = self._last_figure()
        if fig is None or not text.strip():
            return False
        fig['caption'] = text.strip()[:300]
        return True

    def picture(self, pic, cover=False):
        """A picture inside the document: the cover when it comes before the post (or sits in the Cover
        box), otherwise a picture right where it is."""
        if pic['link'] or not pic['rid']:
            self.note('A picture linked from outside the document was left out: insert the picture itself '
                      '(Insert → Pictures → This Device).')
            return
        got = self.doc.picture_data(pic['rid'])
        if got is None:
            self.note('A picture in the document could not be read, so it was left out.')
            return
        data, ext = got
        digest = hashlib.sha1(data).hexdigest()
        if digest in _sample_digests():
            if cover:
                self.note('The cover is still the template’s sample picture, so the post has no cover yet.')
            else:
                self.note('A sample picture from the template is still in the post, so it was left out.')
                self.after_sample = True
            return
        name = self._seen.get(digest)
        if name is None:
            name = self._seen[digest] = 'picture-%d.%s' % (len(self._seen) + 1, ext)
            self.embedded[name] = data
        alt = _clean_alt(pic['alt'])
        if cover or (not self.started and 'cover' not in self.meta):
            self.meta['cover'] = name
            self.cover_alt_from_picture = alt
            return
        self._flush()
        self.out.append({'name': name, 'alt': alt, 'caption': ''})
        self.started = True

    # ---- the older labels
    def labelled(self, key, value, segs):
        if key in DETAILS:
            if not value:
                self.note('@%s has nothing after it.' % key)
            else:
                if key in self.meta:
                    self.note('@%s is there twice; the last one is used.' % key)
                self.meta[key] = value
        elif key in ('h2', 'h3'):
            if value:
                self.add('<%s>%s</%s>' % (key, escape(value), key))
        elif key == 'image':
            name, alt, caption = ([p.strip() for p in value.split('|')] + ['', '', ''])[:3]
            if not name:
                self.note('An @image line has no file name.')
                return
            self.images.append(name)
            if not alt:
                self.note('The picture %s has no description (the text after the first |).' % name)
            self._flush()
            self.out.append({'name': name, 'alt': alt, 'caption': caption})
            self.started = True
        elif key in ('quote', 'note'):
            if segs:
                self.add(('<blockquote>%s</blockquote>' if key == 'quote' else
                          '<aside class="blog-note">%s</aside>') % _inline(segs))
        elif key == 'cta':
            text, _, link = value.partition('|')
            text, link = text.strip(), link.strip()
            if not text or not link_ok(link):
                self.note('@cta needs "Button text | link", the link being a site path like /travel-insurance '
                          'or an https:// address: "%s" was left out.' % value[:60])
                return
            self.add('<p class="blog-cta-wrap"><a class="blog-cta" href="%s">%s</a></p>' % (escape(link), escape(text)))
        elif key == 'divider':
            self.add('<hr/>')

    # ---- tables: the instructions box, the Post details box, or a table in the post
    def table(self, rows):
        if not rows or not rows[0]:
            return
        if _cell_text(rows[0][0]).lower().startswith(GUIDE_MARKS):
            return
        details = [(k, row) for row in rows if len(row) >= 2 for k in [_detail_key(_first_line(row[0]))] if k]
        if len(details) >= 2:
            for key, row in details:
                cells = [p for cell in row[1:] for p in cell]
                if key == 'cover':
                    pics = [pic for p in cells for pic in p['pics']]
                    if pics:
                        self.picture(pics[0], cover=True)
                else:
                    text = ' '.join(t for t in (_para_text(p).strip() for p in cells) if t)
                    if text:
                        self.meta[key] = text
            return
        out = []
        for row in rows:
            cells = ['<br/>'.join(_inline(s) for s in (_clean(p['segs']) for p in paras) if s) for paras in row]
            if any(p['pics'] for paras in row for p in paras):
                self.note('Pictures inside a table were left out: put them on their own line under it.')
            if any(cells):
                out.append(cells)
        if not out:
            return
        head, body = (out[0], out[1:]) if len(out) > 1 else (None, out)
        html = '<table>'
        if head:
            html += '<thead><tr>%s</tr></thead>' % ''.join('<th>%s</th>' % c for c in head)
        html += '<tbody>%s</tbody></table>' % ''.join(
            '<tr>%s</tr>' % ''.join('<td>%s</td>' % c for c in r) for r in body)
        self.add(html)


def parse_docx(data):
    """A .docx as {'title', 'slug', 'summary', 'cover', 'cover_alt', 'html', 'images', 'embedded', 'notes',
    'words'}. Pictures are left as missing-picture boxes named after the file they need: one inside
    the document ('picture-1.png', its bytes in 'embedded') or one from the zip ('images');
    import_upload stores them and attach_images() puts them in."""
    return _Builder(_Doc(data)).build()


# ============================================================================== pictures

def image_key(name):
    base = (name or '').replace('\\', '/').rsplit('/', 1)[-1].strip().lower()
    return re.sub(r'[\s_]+', '-', base)


class Pictures:
    """The uploaded pictures of one import, found by file name (with or without its extension), each
    made web-sized and stored once however many posts use it."""

    def __init__(self, files=()):
        self.found, self.notes, self.used, self._stored = {}, [], set(), {}
        total = 0
        for f in files:
            fname = f.filename or ''
            data = f.read()
            if fname.lower().endswith('.zip'):
                try:
                    z = zipfile.ZipFile(io.BytesIO(data))
                except (zipfile.BadZipFile, ValueError):
                    self.notes.append('%s is not a zip file that can be opened.' % fname)
                    continue
                for info in z.infolist():
                    n = info.filename
                    base = n.rsplit('/', 1)[-1]
                    if info.is_dir() or '__MACOSX' in n or base.startswith('.') or not base:
                        continue
                    if base.rsplit('.', 1)[-1].lower() not in IMAGE_EXT:
                        self.notes.append('%s in the zip is not a JPG, PNG or WebP picture, so it was skipped.' % base)
                        continue
                    if info.file_size > MAX_IMAGE_BYTES:
                        self.notes.append('%s is larger than 10 MB, so it was skipped.' % base)
                        continue
                    if total + info.file_size > MAX_IMAGES_TOTAL or len(self.found) >= MAX_IMAGES:
                        self.notes.append('The zip holds more than this import can take: the rest of it was skipped.')
                        break
                    total += info.file_size
                    self._add(base, z.read(info))
            elif fname.rsplit('.', 1)[-1].lower() in IMAGE_EXT:
                if len(data) > MAX_IMAGE_BYTES:
                    self.notes.append('%s is larger than 10 MB, so it was skipped.' % fname)
                else:
                    self._add(fname, data)
            elif fname:
                self.notes.append('%s was skipped: upload pictures as JPG, PNG or WebP, or one .zip of them.' % fname)

    def _add(self, name, data):
        key = image_key(name)
        if key in self.found:
            self.notes.append('Two pictures are called %s; the first one is used.' % name)
            return
        self.found[key] = (name, data)

    def lookup(self, name):
        key = image_key(name)
        if key in self.found:
            return key
        stem = key.rsplit('.', 1)[0]
        hits = [k for k in self.found if k.rsplit('.', 1)[0] == stem]
        return hits[0] if len(hits) == 1 else None

    def url(self, name, width):
        """The stored picture's address, or None when it is not here (or not a picture)."""
        key = self.lookup(name)
        if key is None:
            return None
        self.used.add(key)
        if (key, width) not in self._stored:
            fname, data = self.found[key]
            try:
                self._stored[(key, width)] = store_image(data, fname, width)
            except ImageError as e:
                self.notes.append(str(e))
                self._stored[(key, width)] = None
        return self._stored[(key, width)]

    def unused(self):
        return [self.found[k][0] for k in self.found if k not in self.used]


def prepare_image(data, name, width):
    """(bytes, extension) of a picture made no wider than `width`, turned the right way up. What Word
    keeps that a browser should not get -- a BMP, a TIFF, a big photo saved as PNG -- becomes a JPG."""
    from PIL import Image, ImageOps
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception:          # noqa: BLE001 -- anything Pillow cannot read is "not a picture"
        if name.lower().endswith(('.emf', '.wmf')):
            raise ImageError('%s is a Word drawing, not a photo. Save it as a picture (right-click → Save as '
                             'Picture → PNG) and paste that in instead.' % name)
        raise ImageError('%s could not be read as a picture.' % name)
    fmt = (im.format or '').upper()
    clear = im.mode in ('RGBA', 'LA') or (im.mode == 'P' and 'transparency' in im.info)
    ext = {'JPEG': 'jpg', 'PNG': 'png', 'WEBP': 'webp'}.get(fmt)
    force = False
    if ext is None:
        if fmt not in ('GIF', 'BMP', 'TIFF', 'MPO', 'DIB'):
            raise ImageError('%s is a %s file; use a JPG or PNG picture.' % (name, fmt or 'drawing'))
        ext, force = ('png' if clear else 'jpg'), True
    elif ext == 'png' and not clear and len(data) > PNG_TO_JPEG:
        ext, force = 'jpg', True
    turned = im.getexif().get(274, 1) not in (1, None)
    if im.width <= width and len(data) <= KEEP_AS_IS and not turned and not force:
        return data, ext
    im = ImageOps.exif_transpose(im)
    if im.width > width:
        im = im.resize((width, max(1, round(im.height * width / im.width))), Image.LANCZOS)
    out = io.BytesIO()
    if ext == 'jpg':
        if im.mode not in ('RGB', 'L'):
            im = im.convert('RGB')
        im.save(out, 'JPEG', quality=84, optimize=True, progressive=True)
    elif ext == 'png':
        im.save(out, 'PNG', optimize=True)
    else:
        im.save(out, 'WEBP', quality=84)
    return out.getvalue(), ext


def store_image(data, name, width):
    """Stored as blog-<its own name>_<random>.<ext>, so a file on disk says which picture it is."""
    from werkzeug.datastructures import FileStorage
    from app.services import storage
    data, ext = prepare_image(data, name, width)
    stem = slugify(name.rsplit('.', 1)[0], max_length=30) or 'picture'
    url = storage.save_public_image(FileStorage(stream=io.BytesIO(data), filename='%s.%s' % (stem, ext)),
                                    prefix=('blog-%s' % stem)[:40])
    if not url:
        raise ImageError('%s could not be stored.' % name)
    from flask_login import current_user
    from app.services.blog_posts import record_media
    record_media(url, name, data, current_user if getattr(current_user, 'is_authenticated', False) else None)
    return url


_MISSING_RE = re.compile(r'<figure class="blog-img blog-img-missing" data-file="([^"]*)" data-alt="([^"]*)">(.*?)</figure>', re.S)
_IMG_FILE_RE = re.compile(r'<img src="([^"]*)"[^>]*?data-file="([^"]*)"')


def known_pictures(html):
    """{file key: address} of the pictures a post already shows, so a document imported again
    without its zip keeps them."""
    return {image_key(unescape(f)): unescape(src) for src, f in _IMG_FILE_RE.findall(html or '')}


def attach_images(html, find):
    """Fill the missing-picture boxes `find(name)` has an address for. Returns (html, names still missing)."""
    missing = []

    def fill(m):
        name, alt, caption = unescape(m.group(1)), unescape(m.group(2)), m.group(3)
        url = find(name)
        if not url:
            missing.append(name)
            return m.group(0)
        return '<figure class="blog-img"><img src="%s" alt="%s" data-file="%s" loading="lazy"/>%s</figure>' % (
            escape(url), escape(alt), escape(name), caption)
    return _MISSING_RE.sub(fill, html or ''), missing


# ============================================================================== clean HTML

_KEEP = {
    'p': ('class',), 'h2': (), 'h3': (), 'strong': (), 'em': (), 'u': (), 'br': (), 'hr': (),
    'a': ('href', 'title', 'target', 'class'), 'ul': (), 'ol': (), 'li': (),
    'blockquote': (), 'aside': ('class',), 'figure': ('class', 'data-file', 'data-alt'),
    'img': ('src', 'alt', 'data-file', 'width', 'height', 'loading'), 'figcaption': (),
    'table': (), 'thead': (), 'tbody': (), 'tr': (), 'th': ('colspan', 'rowspan'), 'td': ('colspan', 'rowspan'),
}
_RENAME = {'b': 'strong', 'i': 'em', 'h1': 'h2', 'h4': 'h3', 'h5': 'h3', 'h6': 'h3',
           'div': 'p', 'section': 'p', 'article': 'p', 'header': 'p', 'footer': 'p'}
_DROP = {'script', 'style', 'iframe', 'object', 'embed', 'noscript', 'template', 'svg', 'math', 'head',
         'title', 'form', 'button', 'select', 'textarea', 'video', 'audio', 'canvas'}
_VOID = {'br', 'hr', 'img'}
_CLASSES = {'p': {'blog-cta-wrap'}, 'a': {'blog-cta'}, 'aside': {'blog-note'},
            'figure': {'blog-img', 'blog-img-missing'}}
_BLOCKS = {'p', 'h2', 'h3', 'ul', 'ol', 'blockquote', 'aside', 'figure', 'table', 'hr'}
_TEXT_BLOCKS = ('p', 'h2', 'h3')
_INLINE = {'strong', 'em', 'u', 'a', 'br', 'img'}


def _safe_url(v, image=False):
    v = (v or '').strip()
    squashed = re.sub(r'[\s\x00-\x1f]+', '', v).lower()
    if squashed.startswith(('https://', 'http://')) or (v.startswith('/') and not v.startswith('//')):
        return v
    if not image and squashed.startswith(('mailto:', 'tel:', '#')):
        return v
    return None


class _Clean(HTMLParser):
    def __init__(self, fix_url=None, public=False):
        super().__init__(convert_charrefs=True)
        self.out, self.stack, self.fix, self.public = [], [], fix_url, public
        self.skip, self.skip_depth = None, 0

    def handle_starttag(self, tag, attrs):
        if self.skip:
            if tag == self.skip:
                self.skip_depth += 1
            return
        if tag in _DROP:
            self.skip, self.skip_depth = tag, 1
            return
        tag = _RENAME.get(tag, tag)
        if tag not in _KEEP:
            return
        attrs = dict(attrs)
        if tag == 'figure' and self.public and 'blog-img-missing' in (attrs.get('class') or ''):
            self.skip, self.skip_depth = 'figure', 1         # a picture nobody uploaded is not shown
            return
        if tag == 'li' and not any(t in ('ul', 'ol') for t in self.stack):
            tag = 'p'
        a = self._attrs(tag, attrs)
        if a is None:
            return
        if tag in _BLOCKS:
            self._close_text_block()
        elif tag in _INLINE and not self.stack:
            self._open('p', '')                               # loose text in the body goes in a paragraph
        self._open(tag, a)

    def _open(self, tag, a):
        self.out.append('<%s%s%s>' % (tag, a, '/' if tag in _VOID else ''))
        if tag not in _VOID:
            self.stack.append(tag)

    def _close_text_block(self):
        for t in _TEXT_BLOCKS:
            if t in self.stack:
                self._close(t)
                return

    def _close(self, tag):
        while self.stack:
            t = self.stack.pop()
            self.out.append('</%s>' % t)
            if t == tag:
                return

    def handle_endtag(self, tag):
        if self.skip:
            if tag == self.skip:
                self.skip_depth -= 1
                if not self.skip_depth:
                    self.skip = None
            return
        tag = _RENAME.get(tag, tag)
        if tag in self.stack:
            self._close(tag)

    def handle_data(self, data):
        if self.skip or not data:
            return
        if not self.stack:
            if not data.strip():
                return
            self._open('p', '')
        self.out.append(escape(data, quote=False))

    def _attrs(self, tag, attrs):
        keep = []
        for name in _KEEP[tag]:
            v = attrs.get(name)
            if v is None:
                continue
            v = v.strip()
            if name in ('href', 'src'):
                v = _safe_url(v, image=name == 'src')
                if v is None:
                    continue
                if self.fix:
                    v = self.fix(v)
            elif name == 'class':
                v = ' '.join(c for c in v.split() if c in _CLASSES.get(tag, ()))
            elif name == 'target':
                v = v if v == '_blank' else ''
            elif name == 'loading':
                v = v if v == 'lazy' else ''
            elif name in ('width', 'height', 'colspan', 'rowspan'):
                v = v if v.isdigit() and len(v) <= 4 else ''
            else:
                v = v[:300]
            if v:
                keep.append((name, v))
        names = {n for n, _ in keep}
        if (tag == 'img' and 'src' not in names) or (tag == 'a' and 'href' not in names):
            return None
        if 'target' in names:
            keep.append(('rel', 'noopener noreferrer'))
        return ''.join(' %s="%s"' % (n, escape(v, quote=True)) for n, v in keep)

    def result(self):
        self.close()
        while self.stack:
            self.out.append('</%s>' % self.stack.pop())
        html = ''.join(self.out)
        return re.sub(r'<p>(\s|<br/>)*</p>', '', html)      # empty paragraphs the editor leaves behind


def sanitize(html, fix_url=None, public=False):
    """Only the tags, attributes and addresses a blog post uses; everything else is dropped (a
    script with its content), renamed (b -> strong, div -> p) or unwrapped (span, font)."""
    c = _Clean(fix_url, public)
    c.feed(html or '')
    return c.result()


def site_url(v):
    """A root-relative address as the browser needs it: inside the app's prefix, except the pages
    that answer beside it (/travel-insurance, /sahayak ...)."""
    if not v.startswith('/') or v.startswith('//'):
        return v
    for alias in current_app.config.get('APP_ALIAS_PATHS') or ():
        a = '/' + alias.strip('/')
        if v == a or v.startswith((a + '/', a + '?', a + '#')):
            return v
    from app.services.urls import app_url
    return app_url(v)


def render(html):
    """A post's content for its public page."""
    return sanitize(html, fix_url=site_url, public=True)


def for_editor(html):
    return sanitize(html, fix_url=site_url)


# ============================================================================== the rules

def plain_text(html):
    return re.sub(r'\s+', ' ', unescape(re.sub(r'<[^>]+>', ' ', html or ''))).strip()


def word_count(html):
    return len(plain_text(html).split())


def checks(title, slug, summary, html, cover, cover_alt, post_id=None, keyword=None, seo_title=None):
    """What the post breaks: [{'level': 'error' | 'warn' | 'ok', 'text'}]. An error stops publishing.
    `seo_title`: the title Google shows instead of the title, when one is given; `keyword`: the words the
    post should be found by -- where they are missing is a tip, never an error."""
    from app.models import Blog
    out = []

    def add(level, text):
        out.append({'level': level, 'text': text})
    title = (title or '').strip()
    words = word_count(html)
    if not title:
        add('error', 'Add a title.')
    elif len(title) > TITLE_GOOD[1]:
        add('warn', 'The title is %d characters; Google cuts it after about %d.' % (len(title), TITLE_GOOD[1]))
    elif len(title) < TITLE_GOOD[0]:
        add('warn', 'The title is short (%d characters); %d–%d reads best in search results.' % ((len(title),) + TITLE_GOOD))
    else:
        add('ok', 'Title length is good (%d characters).' % len(title))
    seo = (seo_title or '').strip()
    if seo and len(seo) > TITLE_GOOD[1]:
        add('warn', 'The SEO title is %d characters; Google cuts it after about %d.' % (len(seo), TITLE_GOOD[1]))
    s = slugify(slug or '', max_length=80, word_boundary=True)
    if not s:
        add('error', 'Add the address (slug).')
    elif Blog.query.filter(Blog.slug == s, Blog.id != (post_id or 0)).first() is not None:
        add('error', 'Another post already uses /blog/%s.' % s)
    if not words:
        add('error', 'The post is empty.')
    for name, _alt, _cap in _MISSING_RE.findall(html or ''):
        add('error', 'The picture %s is missing. Click its box in the post to upload it, or delete the box.' % unescape(name))
    sm = (summary or '').strip()
    if not sm:
        add('warn', 'No summary: Google and shares will use the first lines. Write %d–%d characters.' % SUMMARY_GOOD)
    elif not SUMMARY_GOOD[0] <= len(sm) <= SUMMARY_GOOD[1]:
        add('warn', 'The summary is %d characters; %d–%d shows in full in search results.' % ((len(sm),) + SUMMARY_GOOD))
    else:
        add('ok', 'Summary length is good (%d characters).' % len(sm))
    if not cover:
        add('warn', 'No cover picture: a stock picture will be shown. 1200 × 630 px works best.')
    elif not (cover_alt or '').strip():
        add('warn', 'Describe the cover picture (its alt text).')
    no_alt = len(re.findall(r'<img(?![^>]*\balt="[^"]+")[^>]*>', html or ''))
    if no_alt:
        add('warn', '%d picture%s in the post %s no description.' % (no_alt, '' if no_alt == 1 else 's',
                                                                      'has' if no_alt == 1 else 'have'))
    if words and words < MIN_WORDS:
        add('warn', 'Only %d words; posts under %d words rarely rank.' % (words, MIN_WORDS))
    h2 = len(re.findall(r'<h2\b', html or ''))
    if words >= MIN_WORDS and not h2:
        add('warn', 'No section headings: add an H2 every 300 words or so.')
    elif h2 and words / (h2 + 1) > WORDS_PER_H2:
        add('warn', 'Long stretches without a heading: add an H2 every 300 words or so.')
    first = re.search(r'<(h2|h3)\b', html or '')
    if first and first.group(1) == 'h3':
        add('warn', 'The first heading is an H3; start sections with an H2.')
    long_ones = sum(1 for p in re.findall(r'<p\b[^>]*>(.*?)</p>', html or '', re.S)
                    if len(plain_text(p).split()) > LONG_PARAGRAPH)
    if long_ones:
        add('warn', '%d paragraph%s longer than %d words; split %s for phone screens.' % (
            long_ones, '' if long_ones == 1 else 's', LONG_PARAGRAPH, 'it' if long_ones == 1 else 'them'))
    if re.search(r'href="http://', html or ''):
        add('warn', 'A link starts with http:// -- use https:// where the site has it.')
    out += keyword_checks(keyword, seo or title, s, summary, html)
    if words:
        add('ok', '%d words · about %d min read.' % (words, max(1, round(words / 200))))
    return out


def keyword_checks(keyword, title, slug, summary, html):
    """Where the focus keyword is, the way Yoast checks it: the title Google shows, the summary, the
    address, the opening, a section heading -- and not too often."""
    kw = re.sub(r'\s+', ' ', (keyword or '').strip().lower())
    if not kw:
        return []
    out = []

    def has(text):
        return kw in re.sub(r'\s+', ' ', (text or '').lower())
    text = plain_text(html)
    opening = ' '.join(text.split()[:100])
    found = {'the title': has(title), 'the summary': has(summary),
             'the address': slugify(kw) in (slug or ''), 'the first paragraph': has(opening),
             'a section heading': any(has(plain_text(h)) for h in re.findall(r'<h[23]\b[^>]*>(.*?)</h[23]>', html or '', re.S))}
    missing = [k for k, ok in found.items() if not ok]
    if missing:
        out.append({'level': 'warn', 'text': 'The focus keyword "%s" is not in %s.' % (keyword.strip(), ', '.join(missing))})
    else:
        out.append({'level': 'ok', 'text': 'The focus keyword is in the title, summary, address, opening and a heading.'})
    times = len(re.findall(r'(?<!\w)%s(?!\w)' % re.escape(kw), text.lower()))
    words = len(text.split())
    if words >= 100 and times / max(words, 1) > 0.03:
        out.append({'level': 'warn', 'text': 'The focus keyword is used %d times in %d words: it reads as stuffed. '
                                             'Use it less, or say it other ways.' % (times, words)})
    elif words >= MIN_WORDS and times < 2:
        out.append({'level': 'warn', 'text': 'The focus keyword is used %d time%s: use it a few times in the text.' % (
            times, '' if times == 1 else 's')})
    return out


def has_errors(found):
    return any(c['level'] == 'error' for c in found)


# ============================================================================== importing

def unique_slug(base, post_id=None):
    from app.models import Blog
    base = base or 'post'
    slug, n = base, 1
    while Blog.query.filter(Blog.slug == slug, Blog.id != (post_id or 0)).first() is not None:
        n += 1
        slug = '%s-%d' % (base, n)
    return slug


def import_upload(doc_files, picture_files, user):
    """Every Word document a draft post. Returns (one result per document, notes about the pictures).

    The same file uploaded again updates the draft it made last time -- writers fix the document and
    upload it again -- and keeps the pictures that draft already shows. Anything else that lands on
    an address already taken (a published post, another document with the same title, two documents
    in one upload) becomes a new draft beside it: an import never overwrites somebody else's post."""
    from app import db
    from app.models import Blog
    pics = Pictures(picture_files)
    results, touched = [], set()          # touched: drafts this upload already wrote
    for f in doc_files:
        name = f.filename or 'document'
        res = {'file': name, 'error': None, 'notes': [], 'missing': [], 'post': None, 'status': None}
        results.append(res)
        if not name.lower().endswith('.docx'):
            res['error'] = ('This is an old Word file (.doc): open it in Word and save it as .docx.'
                            if name.lower().endswith('.doc') else 'Only Word documents (.docx) can be imported.')
            continue
        try:
            parsed = parse_docx(f.read())
        except DocxError as e:
            res['error'] = str(e)
            continue
        if not parsed['title']:
            res['error'] = 'No title: fill in the Title box at the top (or start the document with the title).'
            continue
        res['notes'] = list(parsed['notes'])
        slug = parsed['slug'] or 'post'
        existing = Blog.query.filter_by(slug=slug).first()
        # the same file uploaded again updates its draft; another document with the same title never does
        if (existing is not None and not existing.is_published and existing.source_file == name[:255]
                and existing.id not in touched):
            post, res['status'] = existing, 'updated'
            had = known_pictures(existing.content)
            res['notes'].append('The draft from the last upload of this file was updated: changes made in the '
                                'editor since were replaced.')
        else:
            post = Blog(author_id=user.id, slug=unique_slug(slug), is_published=False, send_notification=True)
            db.session.add(post)
            res['status'], had = 'created', {}
            if existing is not None:
                res['notes'].append('%s already uses /blog/%s, so this one is a new draft beside it at /blog/%s.' % (
                    'A published post' if existing.is_published else 'Another draft', slug, post.slug))

        html, cover_url = _assemble(parsed, pics, had, res, post.cover_image_url)
        if cover_url:
            post.cover_image_url = cover_url
        res['pictures'] = len(re.findall(r'<img\b', html)) + (1 if post.cover_image_url else 0)
        post.title = parsed['title']
        post.content = sanitize(html)
        post.summary = parsed['summary'] or post.summary
        post.cover_alt = parsed['cover_alt'] or post.cover_alt
        post.source_file = name[:255]
        db.session.flush()
        res['post'] = post
        touched.add(post.id)
        res['words'] = parsed['words']
        res['checks'] = checks(post.title, post.slug, post.summary, post.content, post.cover_image_url,
                               post.cover_alt, post.id, post.focus_keyword, post.seo_title)
        from app.services.blog_posts import remember
        remember(post, user, 'Imported from Word: %s' % name)
    db.session.commit()
    notes = list(pics.notes)
    unused = pics.unused()
    if unused:
        notes.append('Not used by any document: %s.' % ', '.join(unused[:12]) + (' …' if len(unused) > 12 else ''))
    return results, notes


def _assemble(parsed, pics, had, res, cover_now=None):
    """One parsed document's pictures stored (each once per size) and put in its HTML: (html, the cover's
    address or None). A picture comes from inside the document, else from the uploaded ones (`pics`),
    else stays as the post already had it (`had`); what is found nowhere goes in res['missing']."""
    inside, stored = parsed['embedded'], {}

    def take(n, width):
        if n not in inside:
            return pics.url(n, width)
        if (n, width) not in stored:
            try:
                stored[(n, width)] = store_image(inside[n], n, width)
            except ImageError as e:
                res['notes'].append(str(e))
                stored[(n, width)] = None
        return stored[(n, width)]

    html, res['missing'] = attach_images(parsed['html'], lambda n: take(n, BODY_WIDTH) or had.get(image_key(n)))
    cover, url = parsed['cover'], None
    if cover:
        url = take(cover, COVER_WIDTH)
        if not url and not cover_now and cover not in inside:
            res['missing'].append(cover)
            res['notes'].append('The cover %s was not in the zip.' % cover)
    return html, url


def read_word(data, post=None):
    """One Word document for the editor's "Replace from Word": its parts, with its pictures stored, for
    the editor to show. Nothing is saved to the post -- the writer looks, then saves (or does not).
    Raises DocxError."""
    parsed = parse_docx(data)
    if not parsed['title']:
        raise DocxError('No title: fill in the Title box at the top (or start the document with the title).')
    res = {'notes': list(parsed['notes']), 'missing': []}
    html, cover = _assemble(parsed, Pictures(), known_pictures(post.content) if post else {}, res,
                            post.cover_image_url if post else None)
    return {'title': parsed['title'], 'summary': parsed['summary'] or '', 'cover_alt': parsed['cover_alt'] or '',
            'content': for_editor(sanitize(html)), 'cover': cover, 'cover_src': site_url(cover) if cover else '',
            'notes': res['notes'], 'missing': res['missing'], 'words': parsed['words']}


# ============================================================================== the template

@lru_cache(maxsize=1)
def sample_pictures():
    """The template's two sample pictures (a cover and one in the post). A writer who leaves one in
    gets it left out of the post, recognised by its bytes -- so they are made the same way every time."""
    from PIL import Image, ImageDraw, ImageFont

    def make(w, h, top, bottom, line1, line2):
        im = Image.new('RGB', (w, h), top)
        d = ImageDraw.Draw(im)
        for y in range(h):
            t = y / (h - 1)
            d.line([(0, y), (w, y)], fill=tuple(round(top[i] * (1 - t) + bottom[i] * t) for i in range(3)))
        try:
            big, small = ImageFont.load_default(size=64), ImageFont.load_default(size=34)
        except (TypeError, OSError):
            big = small = ImageFont.load_default()
        d.text((w / 2, h / 2 - 30), line1, fill=(255, 255, 255), font=big, anchor='mm')
        d.text((w / 2, h / 2 + 45), line2, fill=(235, 242, 252), font=small, anchor='mm')
        buf = io.BytesIO()
        im.save(buf, 'PNG')
        return buf.getvalue()
    return {'cover': make(1200, 630, (31, 95, 192), (245, 166, 35), 'Your cover picture',
                          'Right-click → Change Picture · landscape, 1200 × 630'),
            'body': make(1200, 675, (22, 70, 110), (90, 180, 190), 'Your picture',
                         'Right-click → Change Picture, or delete it')}


@lru_cache(maxsize=1)
def _sample_digests():
    return frozenset(hashlib.sha1(v).hexdigest() for v in sample_pictures().values())


def _x(text):
    return escape(text, quote=False)


def _runs(runs):
    """[(text, {'b', 'i', 'link', 'color', 'size'})] or a plain string -> <w:r>s (a link: <w:hyperlink>)."""
    runs = [(runs, {})] if isinstance(runs, str) else runs
    out = []
    for text, f in runs:
        rpr = ('<w:rStyle w:val="Hyperlink"/>' if f.get('link') else '') + ('<w:b/>' if f.get('b') else '') \
            + ('<w:i/>' if f.get('i') else '') + ('<w:color w:val="%s"/>' % f['color'] if f.get('color') else '') \
            + ('<w:sz w:val="%d"/>' % f['size'] if f.get('size') else '')
        run = '<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r>' % ('<w:rPr>%s</w:rPr>' % rpr if rpr else '', _x(text))
        out.append('<w:hyperlink r:id="%s">%s</w:hyperlink>' % (f['link'], run) if f.get('link') else run)
    return ''.join(out)


_PPR = {'note': '<w:pStyle w:val="WriterNote"/>', 'h2': '<w:pStyle w:val="Heading2"/>',
        'h3': '<w:pStyle w:val="Heading3"/>', 'title': '<w:pStyle w:val="Title"/>',
        'bullet': '<w:pStyle w:val="ListParagraph"/><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>',
        'number': '<w:pStyle w:val="ListParagraph"/><w:numPr><w:ilvl w:val="0"/><w:numId w:val="2"/></w:numPr>'}


def _p(runs, kind='p'):
    if kind == 'caption':
        runs = [(t, dict(f, i=True)) for t, f in ([(runs, {})] if isinstance(runs, str) else runs)]
    ppr = _PPR.get(kind, '')
    return '<w:p>%s%s</w:p>' % ('<w:pPr>%s</w:pPr>' % ppr if ppr else '', _runs(runs))


def build_docx(items, links=None):
    """A small .docx. items:
      (kind, runs)  kind 'p' | 'title' | 'h2' | 'h3' | 'bullet' | 'number' | 'caption' (italic) | 'note' (// line);
                    runs a string or [(text, {'b': True, 'i': True, 'link': rid})]
      ('picture', {'data': bytes, 'alt': str})
      ('box', [runs, ...])                       a shaded one-cell table (the instructions)
      ('guide', (title, intro, head, rows, bullets))  a shaded two-column table of the writing guide:
                                                 head (col 1, col 2) or None, rows [(col 1, col 2)], bullets [text]
      ('pagebreak', None)
      ('details', [(label, hint, value), ...])   the Post details table; value a string or a picture dict
      ('table', [[cell text, ...], ...])
    `links`: {rid: url}."""
    links = dict(links or {})
    media = []

    def picture(p, width_in=5.6):
        from PIL import Image
        data = p['data']
        w, h = Image.open(io.BytesIO(data)).size
        n = len(media) + 1
        ext = 'png' if data[:8] == b'\x89PNG\r\n\x1a\n' else 'jpeg'
        rid = 'rIdImg%d' % n
        media.append((rid, 'image%d.%s' % (n, ext), data))
        cx = int(width_in * 914400)
        cy = int(cx * h / w)
        alt = escape(p.get('alt') or '')
        return ('<w:p><w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="%d" cy="%d"/>'
                '<wp:docPr id="%d" name="Picture %d" descr="%s"/><wp:cNvGraphicFramePr>'
                '<a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr><a:graphic>'
                '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic>'
                '<pic:nvPicPr><pic:cNvPr id="%d" name="Picture %d" descr="%s"/><pic:cNvPicPr/></pic:nvPicPr>'
                '<pic:blipFill><a:blip r:embed="%s"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
                '<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="%d" cy="%d"/></a:xfrm><a:prstGeom prst="rect">'
                '<a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>'
                % (cx, cy, n, n, alt, n, n, alt, rid, cx, cy))

    def cell(content, width, fill=None, span=1):
        tcpr = ('<w:tcW w:w="%d" w:type="dxa"/>' % width + ('<w:gridSpan w:val="%d"/>' % span if span > 1 else '')
                + ('<w:shd w:val="clear" w:color="auto" w:fill="%s"/>' % fill if fill else '')
                + '<w:tcMar><w:top w:w="110" w:type="dxa"/><w:left w:w="150" w:type="dxa"/>'
                  '<w:bottom w:w="110" w:type="dxa"/><w:right w:w="150" w:type="dxa"/></w:tcMar>')
        return '<w:tc><w:tcPr>%s</w:tcPr>%s</w:tc>' % (tcpr, content or '<w:p/>')

    def table(rows, grid, color='C9D8EA'):
        borders = ''.join('<w:%s w:val="single" w:sz="6" w:space="0" w:color="%s"/>' % (s, color)
                          for s in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'))
        return ('<w:tbl><w:tblPr><w:tblW w:w="%d" w:type="dxa"/><w:tblBorders>%s</w:tblBorders>'
                '<w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid>%s</w:tblGrid>%s</w:tbl><w:p/>'
                % (sum(grid), borders, ''.join('<w:gridCol w:w="%d"/>' % g for g in grid),
                   ''.join('<w:tr>%s</w:tr>' % r for r in rows)))

    body = []
    for item in items:
        kind, value = item
        if kind == 'picture':
            body.append(picture(value))
        elif kind == 'box':
            body.append(table([cell(''.join(_p(r) for r in value), 9500, fill='FFF4D6')], [9500], color='F0D58C'))
        elif kind == 'guide':
            title, intro, head, lines, bullets = value
            grid = [3700, 5800]
            rows = [cell(_p([(title, {'b': True, 'color': '7A5A00'}),
                             ('   — never published', {'i': True, 'color': '7A5A00'})])
                         + (_p([(intro, {'i': True, 'color': '6B5A2A'})]) if intro else ''), 9500, fill='FCE7B2', span=2)]
            if head:
                rows.append(''.join(cell(_p([(h, {'b': True})]), w, fill='FFF4D6') for h, w in zip(head, grid)))
            for a, b in lines:
                rows.append(cell(_p(a if head else [(a, {'b': True})]), grid[0], fill='FFFBEE')
                            + cell(_p(b), grid[1], fill='FFFBEE'))
            if bullets:
                rows.append(cell(''.join(_p(t, 'bullet') for t in bullets), 9500, fill='FFFBEE', span=2))
            body.append(table(rows, grid, color='F0D58C'))
        elif kind == 'pagebreak':
            body.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
        elif kind == 'details':
            rows = [cell(_p([('POST DETAILS', {'b': True, 'color': '1F4E8C'})]), 9500, fill='DCE9F7', span=2)]
            for label, hint, val in value:
                left = _p([(label, {'b': True})]) + (_p([(hint, {'i': True, 'color': '6B7A90', 'size': 17})]) if hint else '')
                right = picture(val, width_in=3.6) if isinstance(val, dict) else _p(val)
                rows.append(cell(left, 2900, fill='EEF4FB') + cell(right, 6600))
            body.append(table(rows, [2900, 6600]))
        elif kind == 'table':
            width = 9500 // max(1, len(value[0]))
            body.append(table([''.join(cell(_p(c), width) for c in row) for row in value], [width] * len(value[0])))
        else:
            body.append(_p(value, kind))

    ns = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
          'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
          'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
          'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"')
    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document %s><w:body>%s'
                '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1200" w:right="1200" w:bottom="1200" '
                'w:left="1200" w:header="708" w:footer="708" w:gutter="0"/></w:sectPr></w:body></w:document>'
                % (ns, ''.join(body)))

    def style(sid, name, ppr='', rpr=''):
        return ('<w:style w:type="paragraph" w:styleId="%s"><w:name w:val="%s"/><w:basedOn w:val="Normal"/>'
                '<w:next w:val="Normal"/><w:qFormat/><w:pPr>%s</w:pPr><w:rPr>%s</w:rPr></w:style>' % (sid, name, ppr, rpr))
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles %s>'
              '<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/>'
              '<w:sz w:val="22"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="160" w:line="276" '
              'w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>'
              '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>'
              % ns
              + style('Title', 'Title', '<w:spacing w:after="240"/>', '<w:b/><w:sz w:val="40"/>')
              + style('Heading2', 'heading 2', '<w:keepNext/><w:spacing w:before="320" w:after="120"/><w:outlineLvl w:val="1"/>',
                      '<w:b/><w:color w:val="1F4E8C"/><w:sz w:val="30"/>')
              + style('Heading3', 'heading 3', '<w:keepNext/><w:spacing w:before="240" w:after="80"/><w:outlineLvl w:val="2"/>',
                      '<w:b/><w:color w:val="1F4E8C"/><w:sz w:val="25"/>')
              + style('ListParagraph', 'List Paragraph', '<w:spacing w:after="60"/><w:ind w:left="720"/>')
              + style('WriterNote', 'Writer note', '<w:shd w:val="clear" w:color="auto" w:fill="FFF4D6"/>'
                      '<w:spacing w:after="60"/>', '<w:i/><w:color w:val="7A5A00"/><w:sz w:val="19"/>')
              + '<w:style w:type="character" w:styleId="Hyperlink"><w:name w:val="Hyperlink"/>'
                '<w:rPr><w:color w:val="0563C1"/><w:u w:val="single"/></w:rPr></w:style></w:styles>')

    def level(fmt, text):
        return ('<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="%s"/><w:lvlText w:val="%s"/>'
                '<w:lvlJc w:val="left"/><w:pPr><w:ind w:left="720" w:hanging="360"/></w:pPr></w:lvl>' % (fmt, text))
    numbering = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:numbering %s>'
                 '<w:abstractNum w:abstractNumId="0">%s</w:abstractNum>'
                 '<w:abstractNum w:abstractNumId="1">%s</w:abstractNum>'
                 '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>'
                 '<w:num w:numId="2"><w:abstractNumId w:val="1"/></w:num></w:numbering>'
                 % (ns, level('bullet', '•'), level('decimal', '%1.')))
    rel = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rIdStyles" Type="%sstyles" Target="styles.xml"/>'
            '<Relationship Id="rIdNumbering" Type="%snumbering" Target="numbering.xml"/>' % (rel, rel)
            + ''.join('<Relationship Id="%s" Type="%shyperlink" Target="%s" TargetMode="External"/>'
                      % (rid, rel, escape(url)) for rid, url in links.items())
            + ''.join('<Relationship Id="%s" Type="%simage" Target="media/%s"/>' % (rid, rel, fname)
                      for rid, fname, _ in media)
            + '</Relationships>')
    types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
             '<Default Extension="xml" ContentType="application/xml"/>'
             '<Default Extension="png" ContentType="image/png"/>'
             '<Default Extension="jpeg" ContentType="image/jpeg"/>'
             '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
             '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
             '<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>'
             '</Types>')
    root_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 '<Relationship Id="rId1" Type="%sofficeDocument" Target="word/document.xml"/></Relationships>' % rel)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', types)
        z.writestr('_rels/.rels', root_rels)
        z.writestr('word/document.xml', document)
        z.writestr('word/styles.xml', styles)
        z.writestr('word/numbering.xml', numbering)
        z.writestr('word/_rels/document.xml.rels', rels)
        for _, fname, data in media:
            z.writestr('word/media/' + fname, data)
    return buf.getvalue()


def template_docx():
    """The writer's template: a "how to use" box (never published), the Post details box, an example
    post written the way the writer will write theirs -- ready to be typed over -- and, on its own
    page at the end, the whole writing guide (never published either): the same lists the import
    page shows."""
    pics = sample_pictures()
    items = [
        ('box', [
            [('HOW TO USE THIS TEMPLATE', {'b': True}), ('   — this yellow box is never published; leave it or delete it', {'i': True})],
            '1.  Fill in the Post details below: the title, a one- or two-sentence summary, and your cover picture '
            '(right-click the sample picture → Change Picture).',
            '2.  Write your post under the details, like any Word document. For a section title choose Heading 2 '
            '(Home → Styles). Bold, italics, bullet points, numbering, links and tables all come through.',
            '3.  Pictures: put them where they belong (Insert → Pictures, or just paste). Right-click a picture → '
            'Edit Alt Text and say what it shows. Type the caption in italics on the line right under it.',
            '4.  Special boxes: start a line with Tip: for a tip box, or Quote: for a big quote. For a button, '
            'start a line with Button: then select the button’s words and press Ctrl+K to link them.',
            '5.  Save, then upload the file in the admin portal: Travel Companion → Website → Import blog posts. '
            'It becomes a draft you can check before anything is published.',
            [('The full writing guide is at the end of this document: ', {'b': True}),
             ('what each thing becomes on the website, picture tips, what is checked before publishing, and the '
              'advanced labels.', {})],
            [('Using Google Docs? ', {'b': True}), ('Write it the same way, then File → Download → Microsoft Word (.docx).', {})],
        ]),
        ('details', [
            ('Title', 'Under 65 characters', 'How to Buy Travel Insurance for Parents Visiting the USA'),
            ('Summary', '1–2 sentences (70–160 characters). Shown on Google and in WhatsApp shares.',
             'A step-by-step guide for NRIs choosing travel medical insurance for parents visiting the USA: '
             'what to compare, pre-existing conditions and deductibles.'),
            ('Cover picture', 'Landscape, about 1200 × 630', {'data': pics['cover'], 'alt': ''}),
            ('Cover description', 'What the cover picture shows', 'Indian parents with their suitcases at a US airport'),
            ('Web address', 'Optional — leave it empty and it is made from the title', ''),
        ]),
        ('p', [('When parents travel from India to the United States, NRIs plan every detail of the journey. '
                'One item belongs on every checklist: ', {}), ('travel medical insurance', {'b': True}), ('.', {})]),
        ('h2', '1. Understand why your parents need travel insurance'),
        ('p', 'Healthcare in the United States is expensive. An emergency room visit, tests or a short hospital '
              'stay can lead to a large bill, and travel insurance can cover eligible expenses under the policy terms.'),
        ('picture', {'data': pics['body'], 'alt': ''}),
        ('caption', 'Your caption goes here, in italics, on the line right under the picture.'),
        ('h2', '2. Collect your parents’ travel details'),
        ('p', 'You will generally need:'),
        ('bullet', 'Full name and date of birth'),
        ('bullet', 'Passport details'),
        ('bullet', 'Dates of arrival and return'),
        ('h3', 'Before you buy'),
        ('number', 'Compare the policy maximum and the deductible.'),
        ('number', 'Read how pre-existing conditions are treated.'),
        ('number', 'Check the exclusions.'),
        ('p', [('Tip: ', {'b': True}), ('Check whether the policy can be extended if your parents decide to stay longer.', {})]),
        ('p', [('Quote: ', {'b': True}), ('The best plan is not necessarily the cheapest one.', {})]),
        ('h2', 'Final thoughts'),
        ('p', [('Compare plans carefully and read the policy before your parents travel. See our ', {}),
               ('travel insurance page', {'link': 'rIdTi'}), (' for plans that fit.', {})]),
        ('p', [('Button: ', {'b': True}), ('Get a free travel insurance quote', {'link': 'rIdTi'})]),
        ('pagebreak', None),
        ('guide', ('WRITING GUIDE · How each thing comes out',
                   'There is nothing special to learn: write in Word the way you always do. This is what each '
                   'part becomes on the website.', ('In Word', 'On the website'), FORMAT_RULES, ())),
        ('guide', ('WRITING GUIDE · Pictures', None, None, (), IMAGE_RULES)),
        ('guide', ('WRITING GUIDE · What is checked before publishing',
                   'The editor checks the post when it is imported. Fix the first kind; the second are suggestions.',
                   None, CHECK_RULES, ())),
        ('guide', ('WRITING GUIDE · Advanced: labels and separate picture files',
                   'Only for writers who keep pictures as separate files: name them with these labels and upload '
                   'the pictures as one .zip next to the document. Both ways can be mixed.',
                   ('Write this in Word', 'It becomes'), ADVANCED_RULES, ADVANCED_IMAGE_RULES)),
    ]
    return build_docx(items, links={'rIdTi': 'https://nriparentservice.com/travel-insurance'})
