"""Blog studio: Word documents in, blog posts out.

The writer downloads the template (template_docx) and writes the post in Word (or Google Docs,
downloaded as .docx); an admin uploads one or several documents (import_upload). Every document
becomes a DRAFT post, and the editor (routes/admin_blog.py) lists the rules it breaks (checks)
until somebody publishes it.

Writers are not technical, so the format is Word itself -- nothing to learn but three words:

  Post details box (a table at the top)      Title / Summary / Web address / Cover picture / Cover
                                             description / Thumbnail picture / Category / Tags / Focus
                                             keyword / Google title (DETAIL_RULES). "Title:", "Summary:",
                                             "Category:" ... lines at the top work too; without a title,
                                             the first line is the title. Categories and tags are only
                                             ever matched to the blog's own, never made from a document.
  Word's Heading 2 / Heading 3 styles        section headings (a short all-bold line also is one --
                                             a guess, and the import report says so)
  a picture pasted or inserted               a picture right there: its Word "Alt Text" says what it
                                             shows, an italic line right under it is its caption. A
                                             picture before the post starts is the cover.
  a table of two cells: a picture | words    the "Picture and text" block, the picture on its side
  Slideshow: then pictures                   the picture carousel (until the next line of text)
  Video: <YouTube or Vimeo link>             the video, played in the post (a line of only the link too)
  --- / Divider, or Word's own line          a line across the page
  Tip: ...   Quote: ...   Button: <linked words>   a tip box, a pull quote, a button (Big button: and
                                             Outline button: for its other looks)
  everything else                            as written: bold, italics, underline, links, lists, tables

The template's writer boxes (the band and the "how to use" and "new" boxes at the top, the writing guide at
the end) are for the writer and never published: a table whose first words are in GUIDE_MARKS is skipped. So
are its sample pictures and sample video, recognised by their bytes and address.

The older label format still reads, for anyone who keeps pictures as separate files (a zip):
@title: @slug: @summary: @cover: @cover-alt: @thumbnail: @category: @tags: @keyword: @google-title: @h2 @h3
@image: file | alt | caption, @video: @quote: @note: @cta: text | link, @divider, and // writer notes.

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
THUMB_WIDTH = 800                    # the blog's cards, 16:9: twice the widest card on a sharp screen
SIDE_WIDTH = 800                     # a sidebar card: twice the widest sidebar (blog_sidebars.WIDTH_MAX)
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
    'thumbnail': 'thumb', 'thumb': 'thumb', 'category': 'category', 'categories': 'category',
    'tags': 'tags', 'tag': 'tags', 'keyword': 'keyword', 'focus-keyword': 'keyword',
    'google-title': 'seo-title', 'seo-title': 'seo-title',
    'h1': 'h2', 'h2': 'h2', 'heading': 'h2', 'h3': 'h3', 'h4': 'h3', 'subheading': 'h3', 'sub-heading': 'h3',
    'image': 'image', 'img': 'image', 'picture': 'image', 'photo': 'image', 'video': 'video', 'youtube': 'video',
    'quote': 'quote', 'note': 'note', 'tip': 'note', 'cta': 'cta', 'button': 'cta',
    'divider': 'divider', 'line': 'divider',
}
DETAILS = ('title', 'slug', 'summary', 'cover', 'cover-alt', 'thumb', 'category', 'tags', 'keyword', 'seo-title')

# What the guide shows -- on the import page and at the end of the Word template, from these same
# lists, so the two never differ. The Post details box, row by row: (row, what it is for)
DETAIL_RULES = (
    ('Title', 'The post’s title, under 65 characters. Or simply make it the first line of the document.'),
    ('Summary', '1–2 sentences, 70–160 characters: what Google, WhatsApp shares and the blog list show.'),
    ('Web address', 'Optional: the words after /blog/. Left empty, it is made from the title.'),
    ('Cover picture', 'Landscape, 1200 × 630 px: the top of the post, and the picture WhatsApp and Facebook show.'),
    ('Cover description', 'What the cover shows, in a few words, for Google and screen readers.'),
    ('Thumbnail picture', 'Optional, 16:9, 800 × 450 px: the blog list, Read next and More stories. Left empty, the cover is used.'),
    ('Category', 'One of the blog’s categories, as it is named on the blog (several: separate them with commas). '
                 'It also decides which sidebar cards show beside the post.'),
    ('Tags', 'Small subjects, separated by commas. Only tags the blog already has are used: new ones are added in the editor.'),
    ('Focus keyword', 'Optional: the words people search for. The editor checks they are in the title, summary, '
                      'address, opening and a heading.'),
    ('Google title', 'Optional: the title Google shows instead of the post’s title, under 65 characters.'),
)
# (what you do in Word, what it becomes)
FORMAT_RULES = (
    ('The Title box — or simply the first line', 'The post title.'),
    ('The Summary box', 'What Google, WhatsApp shares and the blog list show. 1–2 sentences, 70–160 characters.'),
    ('A picture in the Cover picture box — or a picture above the first paragraph', 'The cover picture at the top of the post.'),
    ('Word’s Heading 2 (Home → Styles), or a short line in bold', 'A section heading.'),
    ('Word’s Heading 3', 'A smaller heading inside a section.'),
    ('Bold, italics, underline, links (Ctrl+K), bullet points, numbering, tables', 'Kept just as they are.'),
    ('A picture pasted or inserted anywhere (Insert → Pictures)', 'A picture in that place. Right-click it → Edit Alt Text to say what it shows.'),
    ('An italic line right under a picture', 'That picture’s caption.'),
    ('A table of two cells: a picture in one, your words in the other', 'A picture beside the words, on the same side as in Word.'),
    ('A line Slideshow: — then pictures one under another, each with an italic caption if you like',
     'A picture slideshow readers swipe through. It ends at the next line of text; words after Slideshow: are its heading.'),
    ('A line that starts with Video: and a YouTube or Vimeo link — or a line that is only that link',
     'The video, playing inside the post.'),
    ('A line that starts with Tip:', 'A highlighted tip box.'),
    ('A line that starts with Quote:', 'A large pull quote.'),
    ('A line that starts with Button: — with the words linked (Ctrl+K)',
     'A button to that page. Start the line with Big button: or Outline button: for the other two looks.'),
    ('Type --- and press Enter (Word draws a line), or a line that says only Divider', 'A line across the page.'),
    ('A line that starts with //', 'A note for you. Never published.'),
)
# What a Word document does not say: done in the editor once the post is a draft (what, where)
EDITOR_RULES = (
    ('Two or three columns, your own HTML / CSS / JS, empty space', 'The editor: Add a block (the + on the left).'),
    ('A block’s look: space above and below, padding, background, width', 'Click the block → the Block tab.'),
    ('A slideshow’s speed, sliding cards of text, the picture’s width beside text', 'Click the block → the Block tab.'),
    ('The post’s width, text size and spacing', 'The Post tab → Layout.'),
    ('Video files (MP4 or WebM) instead of YouTube or Vimeo', 'Add a block → Video.'),
    ('The same box in many posts', 'Add a block → Reusable (Blog → Reusable blocks).'),
    ('Flyers, ads and links beside the post', 'Blog → Sidebars. Cards show by category, so choose the category in the details box.'),
    ('The post’s place on the blog: first, second …', 'Blog → Posts → Order on the blog.'),
    ('Publishing on a later date and time', 'The Post tab → Publish on.'),
    ('New categories and tags', 'Blog → Posts → Categories / Tags, or the editor’s Tags box.'),
)
# The older label format: for pictures kept as separate files and sent as a zip
ADVANCED_RULES = (
    ('@title: How to buy travel insurance for parents', 'The post title. Required (or make it the first line).'),
    ('@slug: travel-insurance-for-parents', 'The address: /blog/travel-insurance-for-parents. Optional, made from the title.'),
    ('@summary: One or two sentences, 70–160 characters', 'Shown in Google results, shares and the blog list.'),
    ('@cover: parents-insurance-cover.jpg', 'The cover picture, from the zip.'),
    ('@cover-alt: Indian parents at a US airport', 'What the cover shows, for Google and screen readers.'),
    ('@thumbnail: parents-insurance-card.jpg', 'The thumbnail for the blog list, from the zip (16:9, 800 × 450).'),
    ('@category: Travel insurance', 'The category, as it is named on the blog.'),
    ('@tags: parents, health insurance', 'Tags the blog already has, separated by commas.'),
    ('@keyword: travel insurance for parents', 'The focus keyword.'),
    ('@google-title: Travel Insurance for Parents: a 2026 Guide', 'The title Google shows.'),
    ('@h2 Compare the plans', 'A section heading (or Word’s Heading 2 style).'),
    ('@h3 Policy maximum', 'A smaller heading inside a section (or Heading 3).'),
    ('@image: parents-insurance-1.jpg | A doctor with an elderly patient | Optional caption',
     'A picture from the zip: file name | what it shows | caption.'),
    ('@video: https://youtu.be/…', 'A YouTube or Vimeo video, playing in the post.'),
    ('@quote: The best plan is not the cheapest one.', 'A pull quote.'),
    ('@note: Check whether the policy can be extended.', 'A highlighted tip box.'),
    ('@cta: Get a free quote | /travel-insurance', 'A button: its text | where it goes (a site path or https:// link).'),
    ('@divider', 'A line across the page.'),
    ('// anything', 'A note for the writer. Never published.'),
)
IMAGE_RULES = (
    'Paste or insert pictures straight into the document, where they belong. Nothing else to send.',
    'Cover: landscape, 1200 × 630 px — it is also the picture WhatsApp and Facebook show.',
    'Thumbnail: 16:9, 800 × 450 px, for the blog list. Leave it empty and the cover is used.',
    'Pictures in the post look best at least 1200 px wide. Big ones are made smaller for you.',
    'A slideshow looks best with pictures all the same shape, for example all 1200 × 675 px.',
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
GUIDE_MARKS = ('how to use this template', 'writing guide', 'blog template', 'new in this template')
# The template's sample video: a YouTube address no real video has (their ids are 11 characters), left out like
# the sample pictures when a writer leaves it in
SAMPLE_VIDEO = 'https://www.youtube.com/watch?v=YOUR-VIDEO'
SAMPLE_VIDEO_ID = 'YOUR-VIDEO'


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
        """{'style', 'num', 'segs': [[text, bold, italic, underline, href]], 'pics': [picture refs], 'rule'}.
        rule: the paragraph draws a line across the page -- Word's border under it (what typing --- and Enter
        makes) or Insert -> Horizontal line."""
        ppr = p.find(W + 'pPr')
        sid = num = None
        rule = False
        if ppr is not None:
            st = ppr.find(W + 'pStyle')
            sid = st.get(W + 'val') if st is not None else None
            num = _num_of(ppr.find(W + 'numPr'))
            bdr = ppr.find(W + 'pBdr')        # a line above or below -- not a box (sides too) around lines
            sides = {b.tag[len(W):] for b in (bdr if bdr is not None else ())
                     if (b.get(W + 'val') or 'none') not in ('none', 'nil')}
            rule = bool(sides & {'top', 'bottom'}) and not sides & {'left', 'right'}
        if num is None and sid:
            num = self.style_num(sid)
        segs, pics, state = [], [], {'field': None, 'instr': '', 'href': None, 'rule': rule}

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
                    elif any(x.get(O + 'hr') in ('t', 'true') for x in ch.iter()):
                        state['rule'] = True          # Insert -> Horizontal line

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
        return {'style': sid, 'num': num, 'segs': segs, 'pics': pics, 'rule': state['rule']}


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


def missing_figure(name, alt='', caption='', kind='blog-img'):
    """The box a picture waits in until it is stored (attach_images): a picture of its own (blog-img), a slide of a
    slideshow (blog-slide) or the picture beside text (blog-mt-media)."""
    cap = '<figcaption>%s</figcaption>' % escape(caption) if caption else ''
    return '<figure class="%s blog-img-missing" data-file="%s" data-alt="%s">%s</figure>' % (
        kind, escape(name), escape(alt), cap)


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
    if words.startswith(('thumbnail', 'thumb', 'card picture', 'list picture')):
        return 'thumb'
    if words in ('google title', 'seo title', 'title on google', 'search title'):
        return 'seo-title'
    if words in ('title', 'post title', 'blog title', 'headline'):
        return 'title'
    if words.startswith('summary') or words in ('short summary', 'description', 'excerpt'):
        return 'summary'
    if words in ('web address', 'address', 'slug', 'url', 'link', 'page address'):
        return 'slug'
    if words in ('category', 'categories', 'section'):
        return 'category'
    if words in ('tags', 'tag'):
        return 'tags'
    if words in ('focus keyword', 'keyword', 'keywords', 'focus keywords'):
        return 'keyword'
    return None


# Plain words at the start of a line. Title / Summary / Web address / Cover description / Category / Tags /
# Focus keyword / Google title only count above the post (where a writer puts details); later on they are
# ordinary sentences.
_PLAIN = re.compile(r'(tip|note|important|remember|quote|big button|outline button|button|caption|video|slideshow|'
                    r'post title|google title|title|summary|web address|cover description|categories|category|tags|'
                    r'focus keyword)\s*[:：]\s*', re.I)
_PLAIN_KEYS = {'tip': 'note', 'note': 'note', 'important': 'note', 'remember': 'note', 'quote': 'quote',
               'button': 'cta', 'big button': 'cta-big', 'outline button': 'cta-outline', 'caption': 'caption',
               'video': 'video', 'slideshow': 'slideshow', 'title': 'title', 'post title': 'title',
               'google title': 'seo-title', 'summary': 'summary', 'web address': 'slug', 'cover description': 'cover-alt',
               'category': 'category', 'categories': 'category', 'tags': 'tags', 'focus keyword': 'keyword'}
_TOP_ONLY = ('title', 'summary', 'slug', 'cover-alt', 'category', 'tags', 'keyword', 'seo-title')
# a line that is only a line: --- (or *** / ___ / ===), dashes Word turned into — , or the word Divider
_DIVIDER = re.compile(r'(?:[-_*=]{3,}|[-–—]{2,}|divider)', re.I)


def names_in(text):
    """'Visas, parents; OCI' -> ['Visas', 'parents', 'OCI']: each once, as written."""
    out, seen = [], set()
    for raw in re.split(r'[,;\n]', text or ''):
        name = ' '.join(raw.split())[:80]
        if name and name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
    return out


class _Builder:
    def __init__(self, doc):
        self.doc = doc
        self.meta, self.out, self.items = {}, [], []    # out: HTML strings, and {'name', 'alt', 'caption'} pictures
        self.images, self.notes = [], []                # images: file names the post asks the zip for
        self.embedded, self._seen = {}, {}              # pictures inside the document, by the name the post uses
        self.guessed = 0
        self.title_from_first = self.started = self.after_sample = False
        self.cover_alt_from_picture = ''
        self.slides = None                              # the slideshow being read ("Slideshow:" ... pictures)

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
        if self.slides is not None:
            self.end_slideshow()
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
                'thumb': (self.meta.get('thumb') or '').strip(),
                'categories': names_in(self.meta.get('category')), 'tags': names_in(self.meta.get('tags')),
                'keyword': ' '.join((self.meta.get('keyword') or '').split())[:100],
                'seo_title': ' '.join((self.meta.get('seo-title') or '').split())[:300],
                'html': html, 'images': self.images, 'embedded': self.embedded, 'notes': self.notes,
                'words': word_count(html)}

    # ---- paragraphs
    def paragraph(self, para, titled):
        segs = _clean(para['segs'])
        plain = ''.join(s[0] for s in segs)
        if self.slides is not None:
            if self._in_slideshow(para, segs, plain):
                return
            self.end_slideshow()
        after_sample, self.after_sample = self.after_sample, False
        if plain.startswith('//'):
            return
        if not plain.strip() and para.get('rule') and not para['pics']:
            return self.divider()
        if plain.strip() and not (after_sample and self._captionish(para, segs, plain)):
            self.text(para, segs, plain, titled)       # (a sample picture's caption goes with it)
        if self.slides is not None:                    # "Slideshow:" with its pictures on the same line
            return self._slides(para['pics'])
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
        if para['num'] is None and _DIVIDER.fullmatch(plain.strip()):
            return self.divider()
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
            elif key in ('cta', 'cta-big', 'cta-outline'):
                return self.button(rest, rsegs, segs, '' if key == 'cta' else key[4:], m.group(1))
            elif key == 'video':
                return self.video(rest, rsegs, segs)
            elif key == 'slideshow':
                return self.slideshow(rest)
            elif key == 'caption' and self.caption(rest):
                return
        if para['num'] is None and ' ' not in plain.strip() and embed_of(plain.strip()):
            return self.video(plain.strip(), segs, segs)          # a line that is only a YouTube or Vimeo link
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

    def button(self, rest, segs, line, look='', said='Button'):
        """Button: words -- the link is the one on the words (Ctrl+K), or a site page / https:// address
        typed after them ("Button: Get a quote → /travel-insurance", or "text | link"). Without a link
        the line stays as it was written. look: 'big' or 'outline' (Big button: / Outline button:)."""
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
            self.note('A "%s:" line needs a link: select the button’s words and press Ctrl+K. '
                      '"%s" was kept as text.' % (' '.join(said.split()).capitalize(), rest[:60]))
            return self.add('<p>%s</p>' % _inline(line))
        self.add('<p class="blog-cta-wrap"><a class="blog-cta%s" href="%s">%s</a></p>' % (
            ' cta-' + look if look else '', escape(href.strip()), escape(text)))

    def video(self, rest, segs, line):
        """Video: a YouTube or Vimeo address (typed, or the link on the words) -- the video, played in the post,
        the same block the editor makes from a pasted link."""
        typed = re.search(r'(?:https?://)?(?:www\.|m\.|player\.)?(?:youtube\.com|youtu\.be|vimeo\.com)/\S+', rest)
        href = next((s[4] for s in segs if s[4] and embed_of(s[4])), None) or (typed.group(0) if typed else '')
        got = embed_of(href)
        if got is None:
            self.note('A "Video:" line needs a YouTube or Vimeo link (youtube.com, youtu.be or vimeo.com): "%s" was '
                      'kept as text. Video files are added in the editor.' % rest[:60])
            return self.add('<p>%s</p>' % _inline(line))
        provider, vid, start = got
        if vid == SAMPLE_VIDEO_ID:
            self.note('The template’s sample video is still in the post, so it was left out: put your own YouTube '
                      'or Vimeo link after Video:.')
            return
        self.add('<figure class="blog-embed" data-provider="%s" data-vid="%s"%s></figure>' % (
            provider, escape(vid), ' data-start="%d"' % start if 0 < start < 100000 else ''))

    def divider(self):
        if not (self.out and self.out[-1] == '<hr/>' and not self.items):
            self.add('<hr/>')

    # ---- a slideshow: "Slideshow:" (a heading after it if the writer gives one), then pictures one under
    # another, each with an italic caption if wanted, until the next line of text
    def slideshow(self, heading):
        if self.slides is not None:
            self.end_slideshow()
        self._flush()
        self.slides = {'heading': heading.strip()[:200], 'items': [], 'last': None, 'samples': 0}
        self.started = True

    def _slides(self, pics):
        show = self.slides
        for pic in pics:
            got = self._take(pic)
            if got == 'sample':
                show['samples'] += 1
                show['last'] = 'sample'
            elif got:
                show['items'].append({'name': got[0], 'alt': got[1], 'caption': ''})
                show['last'] = 'slide'

    def _in_slideshow(self, para, segs, plain):
        """True when the paragraph still belongs to the slideshow: a picture, its caption, a writer note or an
        empty line. Anything else -- words, a heading, a divider -- ends it."""
        show, text = self.slides, plain.strip()
        if text.startswith('//'):
            return True
        if not text:
            if para.get('rule') and not para['pics']:
                return False
            self._slides(para['pics'])
            return True
        if not para['pics'] and show['last'] and self._captionish(para, segs, plain):
            if show['last'] == 'slide':
                show['items'][-1]['caption'] = re.sub(r'^caption\s*[:：]\s*', '', text, flags=re.I)[:300]
            show['last'] = None                        # (a sample picture's caption goes with it)
            return True
        return False

    def end_slideshow(self):
        show, self.slides = self.slides, None
        items = show['items']
        if not items:
            if not show['samples']:
                self.note('A "Slideshow:" line had no pictures under it, so there is no slideshow.')
            return
        if show['heading']:
            self.add('<h3>%s</h3>' % escape(show['heading']))
        if len(items) == 1:
            self.note('A slideshow needs two pictures or more, so its one picture is shown on its own.')
            self._flush()
            self.out.append(dict(items[0]))
            self.started = True
            return
        self.add('<div class="blog-carousel" data-show="1" data-interval="5">%s</div>' % ''.join(
            missing_figure(x['name'], x['alt'], x['caption'], 'blog-slide') for x in items))

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

    def _take(self, pic, slot=None):
        """A picture inside the document as (name, alt) -- or 'sample' for one of the template's, or None when it
        cannot be had, each with a note saying why. slot: 'cover' / 'thumb' for the details box's pictures."""
        if pic['link'] or not pic['rid']:
            self.note('A picture linked from outside the document was left out: insert the picture itself '
                      '(Insert → Pictures → This Device).')
            return None
        got = self.doc.picture_data(pic['rid'])
        if got is None:
            self.note('A picture in the document could not be read, so it was left out.')
            return None
        data, ext = got
        digest = hashlib.sha1(data).hexdigest()
        if digest in _sample_digests():
            self.note({'cover': 'The cover is still the template’s sample picture, so the post has no cover yet.',
                       'thumb': 'The thumbnail is still the template’s sample picture, so the blog list shows the '
                                'cover instead.'}.get(slot, 'A sample picture from the template is still in the '
                                                            'post, so it was left out.'))
            return 'sample'
        name = self._seen.get(digest)
        if name is None:
            name = self._seen[digest] = 'picture-%d.%s' % (len(self._seen) + 1, ext)
            self.embedded[name] = data
        return name, _clean_alt(pic['alt'])

    def picture(self, pic, slot=None):
        """A picture inside the document: the cover when it comes before the post (or sits in the Cover
        box), the thumbnail from its box, otherwise a picture right where it is."""
        got = self._take(pic, slot)
        if got == 'sample':
            self.after_sample = slot is None
            return
        if got is None:
            return
        name, alt = got
        if slot == 'thumb':
            self.meta['thumb'] = name
            return
        if slot == 'cover' or (not self.started and 'cover' not in self.meta):
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
        elif key == 'video':
            if value:
                self.video(value, segs, segs)
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
            self.divider()

    # ---- tables: the writer's boxes, the Post details box, a picture beside words, or a table in the post
    def table(self, rows):
        if self.slides is not None:
            self.end_slideshow()
        if not rows or not rows[0]:
            return
        if _cell_text(rows[0][0]).lower().startswith(GUIDE_MARKS):
            return
        details = [(k, row) for row in rows if len(row) >= 2 for k in [_detail_key(_first_line(row[0]))] if k]
        if len(details) >= 2:
            for key, row in details:
                cells = [p for cell in row[1:] for p in cell]
                if key in ('cover', 'thumb'):
                    pics = [pic for p in cells for pic in p['pics']]
                    if pics:
                        self.picture(pics[0], slot=key)
                else:
                    sep = ', ' if key in ('category', 'tags') else ' '
                    text = sep.join(t for t in (_para_text(p).strip() for p in cells) if t)
                    if text:
                        self.meta[key] = text
            return
        if len(rows) == 1 and len(rows[0]) == 2 and self.beside(rows[0]):
            return
        out = []
        for row in rows:
            cells = ['<br/>'.join(_inline(s) for s in (_clean(p['segs']) for p in paras) if s) for paras in row]
            if any(p['pics'] for paras in row for p in paras):
                self.note('Pictures inside a table were left out: put them on their own line under it. (For a picture '
                          'beside words, use a table of two cells: the picture in one, the words in the other.)')
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

    def beside(self, row):
        """A table of two cells, one picture in one and words in the other: the editor's "Picture and text" block,
        the picture on the side it has in Word. False when the table is not that."""
        def pics(cell):
            return [pic for p in cell for pic in p['pics']]

        def words(cell):
            return ' '.join(t for t in (_para_text(p).strip() for p in cell) if t and not t.startswith('//'))
        sides = [i for i in (0, 1) if pics(row[i]) and not words(row[i])]
        if len(sides) != 1:
            return False
        side = sides[0]
        if len(pics(row[side])) != 1 or pics(row[1 - side]) or not words(row[1 - side]):
            return False
        body = self._cell_html(row[1 - side])
        got = self._take(pics(row[side])[0])
        if not got or got == 'sample':
            if body:
                self.add(body)                         # the words stay; the note says why the picture did not
            return True
        self.add('<div class="blog-mt" data-pos="%s" data-ratio="50">%s<div class="blog-mt-body">%s</div></div>' % (
            'left' if side == 0 else 'right', missing_figure(got[0], got[1], '', 'blog-mt-media'), body))
        return True

    def _cell_html(self, cell):
        """A table cell's words as blocks, read like the post itself (Tip:, Button:, lists ...). Its headings are
        H3s: the cell sits inside a section."""
        sub = _Builder(self.doc)
        sub.started, sub.meta = True, {'title': ''}
        for para in cell:
            sub.paragraph(para, True)
        if sub.slides is not None:
            sub.end_slideshow()
        sub._flush()
        for n in sub.notes:
            self.note(n)
        self.guessed += sub.guessed
        return re.sub(r'<(/?)h2>', r'<\1h3>', ''.join(x for x in sub.out if isinstance(x, str)))


def parse_docx(data):
    """A .docx as {'title', 'slug', 'summary', 'cover', 'cover_alt', 'thumb', 'categories', 'tags', 'keyword',
    'seo_title', 'html', 'images', 'embedded', 'notes', 'words'} (categories and tags: the names as written).
    Pictures are left as missing-picture boxes named after the file they need: one inside the document
    ('picture-1.png', its bytes in 'embedded') or one from the zip ('images'); import_upload stores them and
    attach_images() puts them in."""
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


_MISSING_RE = re.compile(r'<figure class="(?:blog-img|blog-slide|blog-mt-media) blog-img-missing" data-file="([^"]*)" '
                         r'data-alt="([^"]*)">(.*?)</figure>', re.S)
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
        kind = m.group(0)[len('<figure class="'):].split(' ', 1)[0]
        return '<figure class="%s"><img src="%s" alt="%s" data-file="%s" loading="lazy"/>%s</figure>' % (
            kind, escape(url), escape(alt), escape(name), caption)
    return _MISSING_RE.sub(fill, html or ''), missing


# ============================================================================== clean HTML

# what a block may carry, beyond its text: how it looks (the block's settings -- space above and below, padding,
# background, width, text alignment), on any block
_STYLE_RE = re.compile(r'^(sp-[tb][0-5]|pd-[0-3]|bg-(soft|blue|warm|dark)|wd-(wide|full)|ta-(left|center|right))$')
_KEEP = {
    'p': ('class',), 'h2': ('class',), 'h3': ('class',), 'strong': (), 'em': (), 'u': (), 'br': (), 'hr': ('class',),
    'a': ('href', 'title', 'target', 'class'), 'ul': ('class',), 'ol': ('class',), 'li': (),
    'blockquote': ('class',), 'aside': ('class',),
    'figure': ('class', 'data-file', 'data-alt', 'data-provider', 'data-vid', 'data-start'),
    'img': ('src', 'alt', 'data-file', 'width', 'height', 'loading'), 'figcaption': (),
    'table': ('class',), 'thead': (), 'tbody': (), 'tr': (), 'th': ('colspan', 'rowspan'), 'td': ('colspan', 'rowspan'),
    # the blocks beyond text (2026-10-24): each a <div> or <figure> whose class says what it is
    'div': ('class', 'data-cols', 'data-pos', 'data-ratio', 'data-h', 'data-interval', 'data-show', 'data-title',
            'data-ref'),
    'video': ('src', 'poster'), 'pre': (),
}
_RENAME = {'b': 'strong', 'i': 'em', 'h1': 'h2', 'h4': 'h3', 'h5': 'h3', 'h6': 'h3',
           'div': 'p', 'section': 'p', 'article': 'p', 'header': 'p', 'footer': 'p'}
_DROP = {'script', 'style', 'iframe', 'object', 'embed', 'noscript', 'template', 'svg', 'math', 'head', 'bs-live',
         'title', 'form', 'button', 'select', 'textarea', 'audio', 'canvas'}
_VOID = {'br', 'hr', 'img'}
#   blog-cols / blog-col          two or three columns of blocks
#   blog-mt / blog-mt-body        a picture (or video) beside text: figure.blog-mt-media, then the text
#   blog-carousel / blog-slide    pictures (figure.blog-slide) or content (div.blog-slide) one after another
#   blog-code                     the post's own HTML, CSS and JS, run in a sandboxed frame on the public page
#   blog-spacer                   empty space of a chosen height
#   blog-ref                      a synced reusable block (models.BlogPattern, data-ref = its id): a copy of its
#                                 blocks inside, kept the same in every post (blog_posts.fresh_refs)
_DIVS = {'blog-cols', 'blog-col', 'blog-mt', 'blog-mt-body', 'blog-carousel', 'blog-slide', 'blog-code', 'blog-spacer',
         'blog-ref'}
_CLASSES = {'p': {'blog-cta-wrap'}, 'a': {'blog-cta', 'cta-outline', 'cta-big', 'lk-btn', 'lk-outline', 'lk-arrow'},
            'aside': {'blog-note'}, 'div': _DIVS,
            'figure': {'blog-img', 'blog-img-missing', 'blog-embed', 'blog-video', 'blog-mt-media', 'blog-slide'}}
_STYLED = {'p', 'h2', 'h3', 'ul', 'ol', 'blockquote', 'aside', 'figure', 'table', 'hr', 'div'}
_DATA = {'data-cols': r'[23]', 'data-pos': r'left|right', 'data-ratio': r'33|40|50|60|67', 'data-h': r'auto|\d{2,4}',
         'data-interval': r'0|[2-9]|1[0-5]', 'data-show': r'[1-3]', 'data-provider': r'youtube|vimeo',
         'data-vid': r'[A-Za-z0-9_-]{6,20}', 'data-start': r'\d{1,5}', 'data-title': r'[^<>]{1,120}',
         'data-ref': r'[1-9]\d{0,8}'}
_BLOCKS = {'p', 'h2', 'h3', 'ul', 'ol', 'blockquote', 'aside', 'figure', 'table', 'hr', 'div', 'pre'}
_TEXT_BLOCKS = ('p', 'h2', 'h3')
_INLINE = {'strong', 'em', 'u', 'a', 'br', 'img'}
# a YouTube or Vimeo video as the public page plays it, and where it opens on its own site
EMBED = {'youtube': ('https://www.youtube-nocookie.com/embed/%s?rel=0%s', 'https://www.youtube.com/watch?v=%s%s',
                     'Watch on YouTube'),
         'vimeo': ('https://player.vimeo.com/video/%s%s', 'https://vimeo.com/%s%s', 'Watch on Vimeo')}
# the post's own code runs here: a frame of its own, apart from the site (no cookies, no reach into the page)
CODE_SANDBOX = 'allow-scripts allow-popups allow-popups-to-escape-sandbox allow-forms allow-modals'
_CODE_HEIGHT = ('<script>(function(){var f=%d;function h(){parent.postMessage({blogFrame:f,height:'
                'Math.ceil(document.documentElement.getBoundingClientRect().height)},"*")}addEventListener("load",h);'
                'if(window.ResizeObserver)new ResizeObserver(h).observe(document.documentElement);setTimeout(h,400)})()'
                '</script>')


def _safe_url(v, image=False):
    v = (v or '').strip()
    squashed = re.sub(r'[\s\x00-\x1f]+', '', v).lower()
    if squashed.startswith(('https://', 'http://')) or (v.startswith('/') and not v.startswith('//')):
        return v
    if not image and squashed.startswith(('mailto:', 'tel:', '#')):
        return v
    return None


def embed_of(url):
    """('youtube' | 'vimeo', id, start seconds) for a video's address, else None: youtu.be/ID, youtube.com/watch?v=ID,
    /shorts/ID, /embed/ID, vimeo.com/123456; ?t=90 or ?t=1m30s or &start=90 is where it starts."""
    url = (url or '').strip()
    m = re.match(r'^(?:https?://)?(?:www\.|m\.)?(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|embed/|live/)|youtu\.be/)'
                 r'([A-Za-z0-9_-]{6,20})', url)
    provider = 'youtube'
    if not m:
        m = re.match(r'^(?:https?://)?(?:www\.|player\.)?vimeo\.com/(?:video/)?(\d{5,12})', url)
        provider = 'vimeo'
    if not m:
        return None
    t = re.search(r'[?&#](?:t|start)=(?:(\d+)h)?(?:(\d+)m)?(\d+)?s?', url)
    start = 0
    if t and any(t.groups()):
        start = int(t.group(1) or 0) * 3600 + int(t.group(2) or 0) * 60 + int(t.group(3) or 0)
    return provider, m.group(1), start


class _Clean(HTMLParser):
    def __init__(self, fix_url=None, public=False):
        super().__init__(convert_charrefs=True)
        self.out, self.stack, self.fix, self.public = [], [], fix_url, public
        self.skip, self.skip_depth = None, 0
        self.code, self.frames = None, 0                 # the post's own code being read (public page), frames so far
        self.divs = []                                    # each open <div>: 'block' (one of the post's) or 'plain' (a <p>)

    def handle_starttag(self, tag, attrs):
        if self.skip:
            if tag == self.skip:
                self.skip_depth += 1
            return
        if self.code is not None:                         # inside the post's own code: only its text counts
            return
        if tag in _DROP:
            self.skip, self.skip_depth = tag, 1
            return
        attrs = dict(attrs)
        was_div = tag == 'div'
        block_div = was_div and bool(set((attrs.get('class') or '').split()) & _DIVS)
        if not block_div:
            tag = _RENAME.get(tag, tag)                   # a <div> that is one of the post's blocks stays a <div>
        if tag not in _KEEP:
            return
        if tag == 'figure' and self.public and 'blog-img-missing' in (attrs.get('class') or ''):
            self.skip, self.skip_depth = 'figure', 1         # a picture nobody uploaded is not shown
            return
        if tag == 'li' and not any(t in ('ul', 'ol') for t in self.stack):
            tag = 'p'
        pairs = self._pairs(tag, attrs)
        if pairs is None:
            return
        if was_div:
            self.divs.append('block' if tag == 'div' else 'plain')
        if tag in _BLOCKS:
            self._close_text_block()
        elif tag in _INLINE and not self.stack:
            self._open('p', '')                               # loose text in the body goes in a paragraph
        got = dict(pairs)
        if tag == 'video':
            pairs.append(('controls', 'controls'))
            pairs += [('playsinline', 'playsinline'), ('preload', 'metadata')]
        self._open(tag, ''.join(' %s="%s"' % (n, escape(v, quote=True)) for n, v in pairs))
        classes = got.get('class', '').split()
        if self.public and tag == 'figure' and 'blog-embed' in classes:
            self.out.append(self._embed(got))
        elif self.public and tag == 'div' and 'blog-code' in classes:
            self.code = {'depth': len(self.stack), 'buf': [], 'h': got.get('data-h', 'auto'),
                         'title': got.get('data-title') or 'Embedded content'}

    def _embed(self, got):
        """A YouTube or Vimeo video, played in the post, with fullscreen; and a link to watch it on its own site."""
        kind, vid, start = got.get('data-provider'), got.get('data-vid'), int(got.get('data-start') or 0)
        if kind not in EMBED or not vid:
            return ''
        play, page, words = EMBED[kind]
        at = ('&start=%d' % start if kind == 'youtube' else '#t=%ds' % start) if start else ''
        on = ('&t=%ds' % start if kind == 'youtube' else '#t=%ds' % start) if start else ''
        return ('<div class="blog-embed-frame"><iframe src="%s" title="%s" loading="lazy" '
                'allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" '
                'allowfullscreen referrerpolicy="strict-origin-when-cross-origin"></iframe></div>'
                '<p class="blog-embed-open"><a href="%s" target="_blank" rel="noopener noreferrer">%s '
                '<span aria-hidden="true">&#8599;</span></a></p>') % (
            escape(play % (vid, at)), escape(words), escape(page % (vid, on)), escape(words))

    def _code_frame(self):
        """The post's own code, as a sandboxed frame: it runs, but apart from the site (srcdoc, no same origin)."""
        code, self.code = self.code, None
        self.frames += 1
        doc = ('<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,'
               'initial-scale=1"><base target="_blank"><style>html,body{margin:0}</style></head><body>%s%s</body></html>'
               % (''.join(code['buf']), _CODE_HEIGHT % self.frames))
        height = code['h'] if code['h'] != 'auto' else '320'
        self.out.append('<iframe class="blog-code-frame" sandbox="%s" srcdoc="%s" title="%s" loading="lazy" '
                        'data-frame="%d" data-auto="%s" style="height:%spx"></iframe>' % (
                            CODE_SANDBOX, escape(doc, quote=True), escape(code['title']), self.frames,
                            1 if code['h'] == 'auto' else 0, height))

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
        if self.code is not None:
            if tag == 'div' and len(self.stack) == self.code['depth']:
                self._code_frame()
                self._close('div')
                if self.divs:
                    self.divs.pop()
            return
        if tag == 'div':                                  # the post's own block, or a <div> that became a <p>
            kind = self.divs.pop() if self.divs else 'plain'
            if kind == 'block' and 'div' in self.stack:
                self._close('div')
            elif kind == 'plain' and self.stack and self.stack[-1] == 'p':
                self._close('p')
            return
        tag = _RENAME.get(tag, tag)
        if tag in self.stack:
            self._close(tag)

    def handle_data(self, data):
        if self.skip or not data:
            return
        if self.code is not None:
            self.code['buf'].append(data)
            return
        if not self.stack:
            if not data.strip():
                return
            self._open('p', '')
        self.out.append(escape(data, quote=False))

    def _pairs(self, tag, attrs):
        keep = []
        for name in _KEEP[tag]:
            v = attrs.get(name)
            if v is None:
                continue
            v = v.strip()
            if name in ('href', 'src', 'poster'):
                v = _safe_url(v, image=name != 'href')
                if v is None:
                    continue
                if self.fix:
                    v = self.fix(v)
            elif name == 'class':
                v = ' '.join(c for c in v.split() if c in _CLASSES.get(tag, ()) or (tag in _STYLED and _STYLE_RE.match(c)))
            elif name == 'target':
                v = v if v == '_blank' else ''
            elif name == 'loading':
                v = v if v == 'lazy' else ''
            elif name in ('width', 'height', 'colspan', 'rowspan'):
                v = v if v.isdigit() and len(v) <= 4 else ''
            elif name in _DATA:
                v = v if re.fullmatch(_DATA[name], v) else ''
            else:
                v = v[:300]
            if v:
                keep.append((name, v))
        names = {n for n, _ in keep}
        if (tag == 'img' and 'src' not in names) or (tag == 'a' and 'href' not in names):
            return None
        if tag == 'div' and not (set(dict(keep).get('class', '').split()) & _DIVS):
            return None
        if 'target' in names:
            keep.append(('rel', 'noopener noreferrer'))
        return keep

    def result(self):
        self.close()
        if self.code is not None:
            self._code_frame()
        while self.stack:
            self.out.append('</%s>' % self.stack.pop())
        html = ''.join(self.out)
        return re.sub(r'<p>(\s|<br/>)*</p>', '', html)      # empty paragraphs the editor leaves behind


class _Refs(HTMLParser):
    """Walks a post's clean HTML (what sanitize gives) for its reusable blocks, <div class="blog-ref" data-ref="7">:
    what each one holds, and the post with each one's inside replaced (contents[id] = HTML) or unwrapped (None)."""

    def __init__(self, contents=None):
        super().__init__(convert_charrefs=False)
        self.contents = contents or {}
        self.out, self.found = [], {}
        self.ref = None                        # [id, open <div>s, where its opening tag is in out, what is inside]

    def _put(self, s):
        (self.ref[3] if self.ref else self.out).append(s)

    def handle_starttag(self, tag, attrs):
        raw = self.get_starttag_text()
        if self.ref:
            self.ref[1] += tag == 'div'
            self.ref[3].append(raw)
            return
        a = dict(attrs)
        ref = a.get('data-ref') or ''
        if tag == 'div' and ref.isdigit() and 'blog-ref' in (a.get('class') or '').split():
            self.ref = [int(ref), 1, len(self.out), []]
        self.out.append(raw)

    def handle_startendtag(self, tag, attrs):
        self._put(self.get_starttag_text())

    def handle_endtag(self, tag):
        if self.ref and tag == 'div':
            self.ref[1] -= 1
            if not self.ref[1]:
                rid, _n, at, inner = self.ref
                self.ref, inner = None, ''.join(inner)
                self.found.setdefault(rid, inner)
                if rid in self.contents and self.contents[rid] is None:
                    del self.out[at]               # unwrapped: the blocks stay, as the post's own
                    self.out.append(inner)
                else:
                    self.out += [self.contents.get(rid, inner), '</div>']
                return
        self._put('</%s>' % tag)

    def handle_data(self, data):
        self._put(data)

    def handle_entityref(self, name):
        self._put('&%s;' % name)

    def handle_charref(self, name):
        self._put('&#%s;' % name)


def refs_in(html):
    """The reusable blocks a post holds: {id: what the post has inside it} (the first of each)."""
    if 'blog-ref' not in (html or ''):
        return {}
    p = _Refs()
    p.feed(html)
    p.close()
    return p.found


def with_refs(html, contents):
    """The post with its reusable blocks' insides replaced: contents = {id: HTML, or None to unwrap it}."""
    if 'blog-ref' not in (html or ''):
        return html or ''
    p = _Refs(contents)
    p.feed(html)
    p.close()
    if p.ref:                                  # never closed: kept as it was
        p.out.append(''.join(p.ref[3]))
    return ''.join(p.out)


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
    """The post's words: its own code (a blog-code block's <pre>) is not words."""
    html = re.sub(r'<pre>.*?</pre>', ' ', html or '', flags=re.S)
    return re.sub(r'\s+', ' ', unescape(re.sub(r'<[^>]+>', ' ', html))).strip()


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

        html, cover_url, thumb_url = _assemble(parsed, pics, had, res, post.cover_image_url, post.thumb_url)
        if cover_url:
            post.cover_image_url = cover_url
        if thumb_url:
            post.thumb_url = thumb_url
        res['pictures'] = (len(re.findall(r'<img\b', html)) + (1 if post.cover_image_url else 0)
                           + (1 if post.thumb_url else 0))
        post.title = parsed['title']
        post.content = sanitize(html)
        post.summary = parsed['summary'] or post.summary
        post.cover_alt = parsed['cover_alt'] or post.cover_alt
        post.focus_keyword = parsed['keyword'] or post.focus_keyword
        post.seo_title = parsed['seo_title'] or post.seo_title
        cats, tags = _terms(parsed, res['notes'])
        if cats or tags:
            post.terms = (cats or post.categories) + (tags or post.tags)
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


def _terms(parsed, notes):
    """The blog's own categories and tags the document names: ([categories], [tags]), each empty when it names none
    the blog has. A name the blog does not have is never made from a document: a note says so."""
    from app.services.blog_posts import named_terms
    out = []
    for kind, names in (('category', parsed['categories']), ('tag', parsed['tags'])):
        found, unknown = named_terms(kind, names) if names else ([], [])
        if unknown:
            listed = ', '.join('"%s"' % n for n in unknown[:6]) + (' …' if len(unknown) > 6 else '')
            them = len(unknown) > 1
            if kind == 'category':
                notes.append('%s %s %s not on the blog, so %s left out: choose the category in the editor, or add it '
                             'under Blog → Posts → Categories.' % ('The categories' if them else 'The category', listed,
                                                                   'are' if them else 'is',
                                                                   'they were' if them else 'it was'))
            else:
                notes.append('%s %s %s not on the blog yet, so %s left out: type %s in the editor’s Tags box to add '
                             '%s.' % ('The tags' if them else 'The tag', listed, 'are' if them else 'is',
                                      'they were' if them else 'it was', 'them' if them else 'it',
                                      'them' if them else 'it'))
        out.append(found)
    return out


def _assemble(parsed, pics, had, res, cover_now=None, thumb_now=None):
    """One parsed document's pictures stored (each once per size) and put in its HTML: (html, the cover's
    address or None, the thumbnail's or None). A picture comes from inside the document, else from the uploaded
    ones (`pics`), else stays as the post already had it (`had`); what is found nowhere goes in res['missing']."""
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
    found = []
    for key, width, now, what in (('cover', COVER_WIDTH, cover_now, 'cover'), ('thumb', THUMB_WIDTH, thumb_now, 'thumbnail')):
        n, url = parsed.get(key), None
        if n:
            url = take(n, width)
            if not url and not now and n not in inside:
                res['missing'].append(n)
                res['notes'].append('The %s %s was not in the zip.' % (what, n))
        found.append(url)
    return (html, *found)


def read_word(data, post=None):
    """One Word document for the editor's "Replace from Word": its parts, with its pictures stored, for
    the editor to show. Nothing is saved to the post -- the writer looks, then saves (or does not).
    Raises DocxError."""
    parsed = parse_docx(data)
    if not parsed['title']:
        raise DocxError('No title: fill in the Title box at the top (or start the document with the title).')
    res = {'notes': list(parsed['notes']), 'missing': []}
    html, cover, thumb = _assemble(parsed, Pictures(), known_pictures(post.content) if post else {}, res,
                                   post.cover_image_url if post else None, post.thumb_url if post else None)
    cats, tags = _terms(parsed, res['notes'])
    return {'title': parsed['title'], 'summary': parsed['summary'] or '', 'cover_alt': parsed['cover_alt'] or '',
            'content': for_editor(sanitize(html)), 'cover': cover, 'cover_src': site_url(cover) if cover else '',
            'thumb': thumb, 'thumb_src': site_url(thumb) if thumb else '',
            'categories': [t.id for t in cats], 'tags': ', '.join(t.name for t in tags),
            'keyword': parsed['keyword'], 'seo_title': parsed['seo_title'],
            'notes': res['notes'], 'missing': res['missing'], 'words': parsed['words']}


# ============================================================================== the template

def _sample_png(w, h, top, bottom, line1, line2, scale=1.0):
    """One sample picture: a gradient with two lines of text, made the same way every time."""
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new('RGB', (w, h), top)
    d = ImageDraw.Draw(im)
    for y in range(h):
        t = y / (h - 1)
        d.line([(0, y), (w, y)], fill=tuple(round(top[i] * (1 - t) + bottom[i] * t) for i in range(3)))
    try:
        big, small = ImageFont.load_default(size=round(64 * scale)), ImageFont.load_default(size=round(34 * scale))
    except (TypeError, OSError):
        big = small = ImageFont.load_default()
    d.text((w / 2, h / 2 - 30 * scale), line1, fill=(255, 255, 255), font=big, anchor='mm')
    d.text((w / 2, h / 2 + 45 * scale), line2, fill=(235, 242, 252), font=small, anchor='mm')
    buf = io.BytesIO()
    im.save(buf, 'PNG')
    return buf.getvalue()


@lru_cache(maxsize=1)
def sample_pictures():
    """The template's sample pictures: the cover, the thumbnail, one in the post, the one beside words and the
    slideshow's three. A writer who leaves one in gets it left out of the post, recognised by its bytes -- so
    they are made the same way every time. (Plain letters only: the drawing font has no arrows or times signs.)"""
    change = 'Right-click > Change Picture'
    return {'cover': _sample_png(1200, 630, (31, 95, 192), (245, 166, 35), 'Your cover picture',
                                 change + '  ·  landscape, 1200 x 630'),
            'thumb': _sample_png(800, 450, (16, 92, 96), (122, 196, 160), 'Your thumbnail',
                                 'Optional  ·  16:9, 800 x 450  ·  the blog list', 0.8),
            'body': _sample_png(1200, 675, (22, 70, 110), (90, 180, 190), 'Your picture', change + ', or delete it'),
            'side': _sample_png(900, 675, (88, 52, 140), (236, 112, 99), 'Picture beside text', change, 0.9),
            'slide1': _sample_png(1200, 675, (20, 60, 120), (60, 140, 220), 'Slide 1', change),
            'slide2': _sample_png(1200, 675, (120, 50, 20), (240, 150, 60), 'Slide 2', change),
            'slide3': _sample_png(1200, 675, (20, 100, 70), (90, 200, 140), 'Slide 3', change)}


@lru_cache(maxsize=1)
def _sample_digests():
    """The samples of this template and of the one before (October 2026), which writers may still be using."""
    before = (_sample_png(1200, 630, (31, 95, 192), (245, 166, 35), 'Your cover picture',
                          'Right-click → Change Picture · landscape, 1200 × 630'),
              _sample_png(1200, 675, (22, 70, 110), (90, 180, 190), 'Your picture',
                          'Right-click → Change Picture, or delete it'))
    return frozenset(hashlib.sha1(v).hexdigest() for v in (*sample_pictures().values(), *before))


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
        'number': '<w:pStyle w:val="ListParagraph"/><w:numPr><w:ilvl w:val="0"/><w:numId w:val="2"/></w:numPr>',
        # the template's own boxes: close lines, the band's words in from its edges, a line kept with the next
        'tight': '<w:spacing w:before="0" w:after="40"/>', 'boxline': '<w:spacing w:before="0" w:after="90"/>',
        'band': '<w:spacing w:before="0" w:after="60"/><w:ind w:left="200" w:right="200"/>',
        'keep': '<w:keepNext/>'}


def _sized(runs, size):
    """Runs in a smaller (or larger) size, unless one says its own."""
    return [(t, dict(f, size=f.get('size', size))) for t, f in ([(runs, {})] if isinstance(runs, str) else runs)]


def _p(runs, kind='p'):
    if kind == 'caption':
        runs = [(t, dict(f, i=True)) for t, f in ([(runs, {})] if isinstance(runs, str) else runs)]
    ppr = _PPR.get(kind, '')
    return '<w:p>%s%s</w:p>' % ('<w:pPr>%s</w:pPr>' % ppr if ppr else '', _runs(runs))


def build_docx(items, links=None, header=None, title=None):
    """A small .docx. items:
      (kind, runs)  kind 'p' | 'title' | 'h2' | 'h3' | 'bullet' | 'number' | 'caption' (italic) | 'note' (// line);
                    runs a string or [(text, {'b': True, 'i': True, 'link': rid})]
      ('picture', {'data': bytes, 'alt': str, 'width': inches})
      ('band', (kicker, heading, line))          a dark full-width band (the template's top)
      ('box', [runs, ...])                       a shaded one-cell table (the instructions)
      ('news', (title, [(head, text), ...]))     a shaded table of short items, two to a row
      ('guide', (title, intro, head, rows, bullets))  a shaded two-column table of the writing guide:
                                                 head (col 1, col 2) or None, rows [(col 1, col 2)], bullets [text]
      ('pagebreak', None)
      ('rule', None)                             a line across the page (what Word makes of --- and Enter)
      ('details', [(label, hint, value) or 'GROUP', ...])  the Post details table; value a string or a picture
                                                 dict; a plain string is a group's heading row
      ('beside', {'picture': {...}, 'side': 'left' | 'right', 'text': [(kind, runs), ...]})  a two-cell table:
                                                 a picture in one cell, words in the other
      ('table', [[cell text, ...], ...])
    `links`: {rid: url}. `header`: words at the top of every page, with the page number at the bottom. `title`:
    the document's title (File → Info)."""
    links = dict(links or {})
    media = []

    def picture(p, width_in=5.6):
        from PIL import Image
        width_in = p.get('width', width_in)
        data = p['data']
        w, h = Image.open(io.BytesIO(data)).size
        n = len(media) + 1
        ext = 'png' if data[:8] == b'\x89PNG\r\n\x1a\n' else 'jpeg'
        rid = 'rIdImg%d' % n
        media.append((rid, 'image%d.%s' % (n, ext), data))
        cx = int(width_in * 914400)
        cy = int(cx * h / w)
        alt = escape(p.get('alt') or '')
        return ('<w:p><w:pPr><w:keepNext/></w:pPr><w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">'
                '<wp:extent cx="%d" cy="%d"/>'
                '<wp:docPr id="%d" name="Picture %d" descr="%s"/><wp:cNvGraphicFramePr>'
                '<a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr><a:graphic>'
                '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic>'
                '<pic:nvPicPr><pic:cNvPr id="%d" name="Picture %d" descr="%s"/><pic:cNvPicPr/></pic:nvPicPr>'
                '<pic:blipFill><a:blip r:embed="%s"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
                '<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="%d" cy="%d"/></a:xfrm><a:prstGeom prst="rect">'
                '<a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>'
                % (cx, cy, n, n, alt, n, n, alt, rid, cx, cy))

    def cell(content, width, fill=None, span=1, pad=(110, 150), valign=None):
        tcpr = ('<w:tcW w:w="%d" w:type="dxa"/>' % width + ('<w:gridSpan w:val="%d"/>' % span if span > 1 else '')
                + ('<w:shd w:val="clear" w:color="auto" w:fill="%s"/>' % fill if fill else '')
                + '<w:tcMar><w:top w:w="%d" w:type="dxa"/><w:left w:w="%d" w:type="dxa"/>'
                  '<w:bottom w:w="%d" w:type="dxa"/><w:right w:w="%d" w:type="dxa"/></w:tcMar>' % (pad + pad)
                + ('<w:vAlign w:val="%s"/>' % valign if valign else ''))
        return '<w:tc><w:tcPr>%s</w:tcPr>%s</w:tc>' % (tcpr, content or '<w:p/>')

    def table(rows, grid, color='C9D8EA', keep=False):
        """keep: no row is split over two pages."""
        borders = ''.join('<w:%s w:val="single" w:sz="6" w:space="0" w:color="%s"/>' % (s, color)
                          for s in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'))
        trpr = '<w:trPr><w:cantSplit/></w:trPr>' if keep else ''
        return ('<w:tbl><w:tblPr><w:tblW w:w="%d" w:type="dxa"/><w:tblBorders>%s</w:tblBorders>'
                '<w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid>%s</w:tblGrid>%s</w:tbl><w:p/>'
                % (sum(grid), borders, ''.join('<w:gridCol w:w="%d"/>' % g for g in grid),
                   ''.join('<w:tr>%s%s</w:tr>' % (trpr, r) for r in rows)))

    body = []
    for item in items:
        kind, value = item
        if kind == 'picture':
            body.append(picture(value))
        elif kind == 'band':
            kicker, heading, line = value
            body.append(table([cell(_p([(kicker, {'b': True, 'color': 'F5B544', 'size': 17})], 'band')
                                    + _p([(heading, {'b': True, 'color': 'FFFFFF', 'size': 44})], 'band')
                                    + _p([(line, {'color': 'D6E2F3', 'size': 21})], 'band'), 9500, fill='17375E',
                                    pad=(260, 150))], [9500], color='17375E'))
        elif kind == 'box':
            body.append(table([cell(''.join(_p(_sized(r, 20), 'boxline') for r in value), 9500, fill='FFF4D6',
                                    pad=(160, 150))], [9500], color='F0D58C'))
        elif kind == 'news':
            heading, pairs = value
            rows = [cell(_p([(heading, {'b': True, 'color': '7A5A00'}), ('   — never published', {'i': True, 'color': '7A5A00'})]),
                         9500, fill='FCE7B2', span=2)]
            for i in range(0, len(pairs), 2):
                rows.append(''.join(cell(_p([('✦  ', {'color': 'C98A00', 'size': 19}), (h, {'b': True, 'size': 19})], 'tight')
                                         + _p([(t, {'size': 18, 'color': '5B4A1E'})], 'tight'), 4750, fill='FFFBEE',
                                         pad=(80, 150)) for h, t in pairs[i:i + 2]))
            body.append(table(rows, [4750, 4750], color='F0D58C', keep=True))
        elif kind == 'rule':
            body.append('<w:p><w:pPr><w:pBdr><w:bottom w:val="single" w:sz="8" w:space="1" w:color="9AA8BA"/></w:pBdr>'
                        '</w:pPr></w:p>')
        elif kind == 'beside':
            pic = cell(picture(value['picture'], width_in=1.9), 3100, valign='center')
            words = cell(''.join(_p(r, k) for k, r in value['text']), 6400, valign='center')
            left = value.get('side', 'left') == 'left'
            body.append(table([pic + words if left else words + pic], [3100, 6400] if left else [6400, 3100],
                              color='D5DEE9', keep=True))
        elif kind == 'guide':
            title, intro, head, lines, bullets = value
            grid = [3700, 5800]
            rows = [cell(_p([(title, {'b': True, 'color': '7A5A00'}),
                             ('   — never published', {'i': True, 'color': '7A5A00'})], 'tight')
                         + (_p([(intro, {'i': True, 'color': '6B5A2A', 'size': 19})], 'tight') if intro else ''),
                         9500, fill='FCE7B2', span=2)]
            if head:
                rows.append(''.join(cell(_p([(h, {'b': True, 'size': 19})], 'tight'), w, fill='FFF4D6', pad=(70, 150))
                                    for h, w in zip(head, grid)))
            for a, b in lines:
                rows.append(cell(_p(_sized(a if head else [(a, {'b': True})], 19), 'tight'), grid[0], fill='FFFBEE',
                                 pad=(70, 150))
                            + cell(_p(_sized(b, 19), 'tight'), grid[1], fill='FFFBEE', pad=(70, 150)))
            if bullets:
                rows.append(cell(''.join(_p(_sized(t, 19), 'bullet') for t in bullets), 9500, fill='FFFBEE', span=2))
            body.append(table(rows, grid, color='F0D58C', keep=True))
        elif kind == 'pagebreak':
            body.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
        elif kind == 'details':
            rows = [cell(_p([('POST DETAILS', {'b': True, 'color': 'FFFFFF'}),
                             ('   type over the examples · only the title is needed', {'i': True, 'color': 'D6E2F3', 'size': 19})]),
                         9500, fill='1F4E8C', span=2)]
            for entry in value:
                if isinstance(entry, str):
                    rows.append(cell(_p([(entry, {'b': True, 'color': '1F4E8C', 'size': 17})], 'tight'), 9500,
                                     fill='DCE9F7', span=2, pad=(50, 150)))
                    continue
                label, hint, val = entry
                left = (_p([(label, {'b': True})], 'tight')
                        + (_p([(hint, {'i': True, 'color': '6B7A90', 'size': 16})], 'tight') if hint else ''))
                right = picture(val, width_in=3.0) if isinstance(val, dict) else _p(val, 'tight')
                rows.append(cell(left, 2900, fill='EEF4FB', pad=(80, 150)) + cell(right, 6600, valign='center', pad=(80, 150)))
            body.append(table(rows, [2900, 6600], keep=True))
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
    refs = ('<w:headerReference w:type="default" r:id="rIdHeader"/><w:footerReference w:type="default" r:id="rIdFooter"/>'
            if header else '')
    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document %s><w:body>%s'
                '<w:sectPr>%s<w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1200" w:right="1200" w:bottom="1200" '
                'w:left="1200" w:header="560" w:footer="560" w:gutter="0"/></w:sectPr></w:body></w:document>'
                % (ns, ''.join(body), refs))
    small = '<w:rPr><w:color w:val="8A97A8"/><w:sz w:val="16"/></w:rPr>'
    header_xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:hdr %s><w:p><w:pPr><w:jc w:val="right"/></w:pPr>'
                  '<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r></w:p></w:hdr>' % (ns, small, _x(header or '')))
    footer_xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:ftr %s><w:p><w:pPr><w:jc w:val="center"/></w:pPr>'
                  '<w:r>%s<w:t xml:space="preserve">Page </w:t></w:r><w:fldSimple w:instr=" PAGE "><w:r>%s<w:t>1</w:t></w:r>'
                  '</w:fldSimple></w:p></w:ftr>' % (ns, small, small))

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
              + style('WriterNote', 'Writer note', '<w:keepNext/><w:pBdr><w:left w:val="single" w:sz="18" w:space="6" '
                      'w:color="E0B43C"/></w:pBdr><w:shd w:val="clear" w:color="auto" w:fill="FFF4D6"/>'
                      '<w:spacing w:before="200" w:after="80"/>',
                      '<w:i/><w:color w:val="7A5A00"/><w:sz w:val="19"/>')
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
            + ('<Relationship Id="rIdHeader" Type="%sheader" Target="header1.xml"/>'
               '<Relationship Id="rIdFooter" Type="%sfooter" Target="footer1.xml"/>' % (rel, rel) if header else '')
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
             + ('<Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>'
                '<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>'
                if header else '')
             + ('<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
                if title else '')
             + '</Types>')
    root_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 '<Relationship Id="rId1" Type="%sofficeDocument" Target="word/document.xml"/>' % rel
                 + ('<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/'
                    'core-properties" Target="docProps/core.xml"/>' if title else '')
                 + '</Relationships>')
    core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties '
            'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>%s</dc:title><dc:creator>NRI Parent Service</dc:creator>'
            '</cp:coreProperties>' % _x(title or ''))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', types)
        z.writestr('_rels/.rels', root_rels)
        z.writestr('word/document.xml', document)
        z.writestr('word/styles.xml', styles)
        z.writestr('word/numbering.xml', numbering)
        z.writestr('word/_rels/document.xml.rels', rels)
        if header:
            z.writestr('word/header1.xml', header_xml)
            z.writestr('word/footer1.xml', footer_xml)
        if title:
            z.writestr('docProps/core.xml', core)
        for _, fname, data in media:
            z.writestr('word/media/' + fname, data)
    return buf.getvalue()


def template_docx():
    """The writer's template, all of it Word the writer already knows:
      * page 1, for the writer and never published: the band, "How to use this template", "New in this template";
      * the Post details box, its rows grouped (Basics, Pictures, Where it shows, Google);
      * an example post written the way the writer will write theirs -- every block the import knows, each with a
        small // note above it (never published), ready to be typed over. Its sample pictures and sample video are
        left out of the post if the writer leaves them in;
      * on its own pages at the end, the whole writing guide (never published either): the same lists the import
        page shows."""
    pics = sample_pictures()
    ti, tc = {'link': 'rIdTi'}, {'link': 'rIdTc'}
    items = [
        ('band', ('BLOG TEMPLATE  ·  NRI PARENT SERVICE', 'Write your blog post in Word',
                  'Type over the example, upload the file, and it becomes a draft on the blog. '
                  'Nothing is published until you say so.')),
        ('box', [
            [('HOW TO USE THIS TEMPLATE', {'b': True}),
             ('   — the yellow boxes and the dark band are never published; leave them or delete them', {'i': True})],
            '1.  Fill in the Post details box on the next page: the title, a one- or two-sentence summary and the cover '
            'picture — and, if you like, a thumbnail, the category and tags, and what Google should show.',
            '2.  Write the post under the details, like any Word document. For a section title choose Heading 2 '
            '(Home → Styles). Bold, italics, bullet points, numbering, links and tables all come through.',
            '3.  Pictures: put them where they belong (Insert → Pictures, or just paste). To use the sample places, '
            'right-click a sample picture → Change Picture. Right-click → Edit Alt Text to say what it shows, and '
            'type the caption in italics on the line right under it.',
            '4.  Special lines make special blocks: Tip:, Quote:, Button:, Video:, Slideshow: and --- . The example '
            'post shows every one, with a small yellow // note above it (// lines are never published).',
            '5.  Save, then upload the file in the admin portal: Blog → Import from Word. It becomes a draft you '
            'check in the editor before anything is published.',
            [('The full writing guide is at the end of this document: ', {'b': True}),
             ('the Post details box row by row, what each thing becomes, picture sizes, what to do in the editor '
              'afterwards, what is checked before publishing, and the advanced labels.', {})],
            [('Using Google Docs? ', {'b': True}), ('Write it the same way, then File → Download → Microsoft Word (.docx).', {})],
        ]),
        ('news', ('NEW IN THIS TEMPLATE  ·  October 2026', [
            ('Thumbnail picture', 'A 16:9 picture for the blog list, 800 × 450.'),
            ('Category and tags', 'Where the post shows, and which sidebar cards sit beside it.'),
            ('Focus keyword and Google title', 'What the post should be found by.'),
            ('Video:', 'A YouTube or Vimeo link that plays inside the post.'),
            ('Picture beside text', 'A table of two cells: the picture in one, the words in the other.'),
            ('Slideshow:', 'Pictures readers swipe through, each with its caption.'),
            ('Divider', 'Type --- and press Enter for a line across the page.'),
            ('Big button: · Outline button:', 'Two more looks for a button.'),
        ])),
        ('pagebreak', None),
        ('details', [
            'BASICS',
            ('Title', 'Under 65 characters', 'How to Buy Travel Insurance for Parents Visiting the USA'),
            ('Summary', '1–2 sentences, 70–160 characters. Shown on Google and in WhatsApp shares.',
             'A step-by-step guide for NRIs choosing travel insurance for parents visiting the USA: what to compare, '
             'pre-existing conditions and deductibles.'),
            ('Web address', 'Optional — left empty, it is made from the title', ''),
            'PICTURES',
            ('Cover picture', 'Landscape, 1200 × 630 px. Also the picture WhatsApp and Facebook show.',
             {'data': pics['cover'], 'alt': '', 'width': 2.6}),
            ('Cover description', 'What the cover picture shows', 'Indian parents with their suitcases at a US airport'),
            ('Thumbnail picture', 'Optional · 16:9, 800 × 450 px, for the blog list. Left empty, the cover is used.',
             {'data': pics['thumb'], 'alt': '', 'width': 1.7}),
            'WHERE IT SHOWS',
            ('Category', 'As named on the blog. It also picks the sidebar cards beside the post.', 'Travel insurance'),
            ('Tags', 'Separated by commas. Only tags the blog already has.', 'parents, health insurance, USA visit'),
            'GOOGLE',
            ('Focus keyword', 'Optional: the words people search for', 'travel insurance for parents'),
            ('Google title', 'Optional: what Google shows instead of the title', 'Travel Insurance for Parents Visiting the USA: 2026 Guide'),
        ]),
        ('p', [('When parents travel from India to the United States, NRIs plan every detail of the journey. '
                'One item belongs on every checklist: ', {}), ('travel insurance for parents', {'b': True}), ('.', {})]),
        ('h2', '1. Why travel insurance for parents matters'),
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
        ('note', '// PICTURE BESIDE TEXT — a table of two cells: the picture in one, your words in the other. '
                 'Put the picture in the right-hand cell and it shows on the right.'),
        ('beside', {'picture': {'data': pics['side'], 'alt': ''}, 'side': 'left', 'text': [
            ('h3', 'Pre-existing conditions'),
            ('p', 'Many plans cover a sudden flare-up of an existing condition only up to a limit, and some not at '
                  'all. Read this part of the policy twice, and ask before you buy.'),
        ]}),
        ('p', [('Tip: ', {'b': True}), ('Check whether the policy can be extended if your parents decide to stay longer.', {})]),
        ('p', [('Quote: ', {'b': True}), ('The best plan is not necessarily the cheapest one.', {})]),
        ('note', '// VIDEO — write Video: and paste a YouTube or Vimeo link: it plays inside the post. '
                 'A line that is only the link works too.'),
        ('p', [('Video: ', {'b': True}), (SAMPLE_VIDEO, {})]),
        ('note', '// SLIDESHOW — write Slideshow: (and a heading after it if you like), then the pictures one under '
                 'another, each with its caption in italics. The slideshow ends at the next line of text.'),
        ('keep', [('Slideshow: ', {'b': True}), ('A day at the airport', {})]),
        ('picture', {'data': pics['slide1'], 'alt': '', 'width': 2.6}),
        ('caption', 'Check-in: keep the passports and the insurance card together.'),
        ('picture', {'data': pics['slide2'], 'alt': '', 'width': 2.6}),
        ('caption', 'Security: medicines go in the cabin bag.'),
        ('picture', {'data': pics['slide3'], 'alt': '', 'width': 2.6}),
        ('caption', 'Arrival: the insurance card is ready at immigration.'),
        ('note', '// DIVIDER — type --- and press Enter: Word draws a line across the page. '
                 'Or write Divider on a line of its own.'),
        ('rule', None),
        ('h2', 'Final thoughts'),
        ('p', [('Compare plans carefully and read the policy before your parents travel. See our ', {}),
               ('travel insurance page', ti), (' for plans that fit.', {})]),
        ('note', '// BUTTONS — Button: then the words, linked with Ctrl+K. Big button: and Outline button: '
                 'give the other two looks.'),
        ('p', [('Button: ', {'b': True}), ('Get a free travel insurance quote', ti)]),
        ('p', [('Outline button: ', {'b': True}), ('Find a travel companion for your parents', tc)]),
        ('pagebreak', None),
        ('guide', ('WRITING GUIDE · The Post details box',
                   'Only the title is needed; every other row is optional. This is what each one is for.',
                   ('Row', 'What it is for'), DETAIL_RULES, ())),
        ('guide', ('WRITING GUIDE · How each thing comes out',
                   'There is nothing special to learn: write in Word the way you always do. This is what each '
                   'part becomes on the website.', ('In Word', 'On the website'), FORMAT_RULES, ())),
        ('guide', ('WRITING GUIDE · Pictures', None, None, (), IMAGE_RULES)),
        ('guide', ('WRITING GUIDE · Do these in the editor after import',
                   'A Word document does not say these. Open the draft in the editor (Blog → All posts) and:',
                   ('What', 'Where'), EDITOR_RULES, ())),
        ('guide', ('WRITING GUIDE · What is checked before publishing',
                   'The editor checks the post when it is imported. Fix the first kind; the second are suggestions.',
                   None, CHECK_RULES, ())),
        ('guide', ('WRITING GUIDE · Advanced: labels and separate picture files',
                   'Only for writers who keep pictures as separate files: name them with these labels and upload '
                   'the pictures as one .zip next to the document. Both ways can be mixed.',
                   ('Write this in Word', 'It becomes'), ADVANCED_RULES, ADVANCED_IMAGE_RULES)),
    ]
    return build_docx(items, links={'rIdTi': 'https://nriparentservice.com/travel-insurance',
                                    'rIdTc': 'https://nriparentservice.com/travel-companions'},
                      header='NRI Parent Service  ·  Blog template', title='NRI Parent Service blog template')
