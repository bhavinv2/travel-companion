/* Blog studio editor (admin/blog_edit.html): a new post and a saved one, written the way WordPress
   does it.

   The post is edited in place, in the public page's own styles, as a column of blocks: paragraphs,
   headings, lists, a quote, a tip box, pictures, a button, a table, a line across. A block is added
   with "Add block", with the + on an empty line, or by typing / on an empty line; the small bar over
   the block the caret is in moves, copies or removes it (and adds rows and columns to a table).
   Pictures and buttons are objects, not text: one click opens their panel. Pictures can also be
   dragged in or pasted. Pasted text keeps its headings, bold, italics, lists, links and tables, and
   nothing else.

   The checks beside the post come from the server (blog_engine.checks), so the rules live in one
   place; this file only asks for them. Whatever the editor produces, the server cleans it again on
   save. Work that is not saved yet is kept in this browser and offered back after a crash.

   The page is full screen, the way WordPress's editor is: the settings beside the post are three tabs
   (Post: status, schedule, author, categories, tags, featured image, summary, Word document; SEO: the
   Google and share previews; Checks), the list view lists every block, Publish opens a last look first,
   pictures can come from the media library, and "Replace from Word" brings a document's words and
   pictures into the editor (unsaved, undoable). */
(function () {
  const form = document.getElementById('bsForm');
  if (!form) return;
  const editor = document.getElementById('bsEditor');
  const wrap = document.getElementById('bsWrap');
  const hidden = form.querySelector('textarea[name=content]');
  const fileInput = document.getElementById('bsFile');
  const panel = document.getElementById('bsFigPanel');
  const menu = document.getElementById('bsMenu');
  const plus = document.getElementById('bsPlus');
  const bbar = document.getElementById('bsBlockBar');
  const pop = document.getElementById('bsPop');
  const title = form.querySelector('[name=title]');
  const slug = form.querySelector('[name=slug]');
  const slugAuto = form.querySelector('[name=slug_auto]');
  const summary = form.querySelector('[name=summary]');
  const CSRF = document.querySelector('meta[name="csrf-token"]')?.content || '';
  const KEY = form.dataset.key;
  let dirty = false, saved = null, picking = null, current = null, active = null, picked = null;

  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  const toast = (m, t) => (window.showToast ? window.showToast(m, t) : alert(m));
  document.execCommand('defaultParagraphSeparator', false, 'p');

  // ---------------------------------------------------------------- the blocks
  const BB = () => window.BlogBlocks || null;       // the blocks beyond text (blog-blocks.js), when it is on the page
  const isCta = n => n && n.tagName === 'P' && n.classList.contains('blog-cta-wrap');
  const isText = n => n && /^(P|H2|H3)$/.test(n.tagName) && !isCta(n);
  const isEmpty = n => isText(n) && n.tagName === 'P' && !n.textContent.trim() && !n.querySelector('img');
  function para() { const p = document.createElement('p'); p.innerHTML = '<br>'; return p; }
  function topBlock(n) {
    while (n && n.parentNode !== editor) n = n.parentNode;
    return n && n.parentNode === editor ? n : null;
  }
  function caretBlock() {
    const s = window.getSelection();
    return s.rangeCount && editor.contains(s.anchorNode) ? topBlock(s.anchorNode) : null;
  }
  function caretIn(el, atEnd) {
    if (!el) return;
    editor.focus();
    const r = document.createRange();
    r.selectNodeContents(el);
    r.collapse(!atEnd);
    const s = window.getSelection();
    s.removeAllRanges();
    s.addRange(r);
    keep();
  }
  function lockBlocks() {
    editor.querySelectorAll('figure, p.blog-cta-wrap, .blog-code, .blog-spacer, .blog-carousel')
      .forEach(f => f.setAttribute('contenteditable', 'false'));
    editor.querySelectorAll('.blog-carousel > div.blog-slide').forEach(f => f.setAttribute('contenteditable', 'true'));
    editor.querySelectorAll('.blog-ref').forEach(r => {        // a reusable block: changed only after Edit (its Block tab)
      if (r.classList.contains('is-editing')) { r.removeAttribute('contenteditable'); return; }
      r.setAttribute('contenteditable', 'false');
      r.querySelectorAll('[contenteditable=true]').forEach(x => x.setAttribute('contenteditable', 'false'));
    });
    if (BB()) BB().decorate(editor);                  // the previews (a video's picture, the code running): never saved
  }
  // there is always a line to type on: at the start of an empty post, and after a picture, a table ...
  function lines() {
    if (!editor.firstElementChild) editor.appendChild(para());
    Array.from(editor.childNodes).forEach(n => {           // loose text the browser left at the top
      if (n.nodeType === 3 && n.textContent.trim()) { const p = document.createElement('p'); n.replaceWith(p); p.appendChild(n); }
      else if (n.nodeType === 1 && n.tagName === 'DIV' && !/(^|\s)blog-/.test(n.className)) { const p = document.createElement('p'); while (n.firstChild) p.appendChild(n.firstChild); n.replaceWith(p); }
    });
    if (!isText(editor.lastElementChild)) editor.appendChild(para());
  }
  function after(node) {
    const next = node.nextElementSibling;
    if (isEmpty(next)) return next;
    const p = para();
    node.after(p);
    return p;
  }
  function place(node, target, before) {
    if (target && editor.contains(target) && isEmpty(target)) target.replaceWith(node);   // the empty line becomes it
    else if (target && editor.contains(target)) target[before ? 'before' : 'after'](node);
    else editor.appendChild(node);
  }
  // the editor's own marks (the hint on an empty line, the picked picture, a block flashed from the list view):
  // never part of the post, nor of its undo history, nor of copied blocks
  const MARKS = ['is-picked', 'bs-ph', 'ge-flash', 'is-dragging'];
  function unmark(root) {
    root.querySelectorAll('bs-live').forEach(e => e.remove());       // previews (blog-blocks.js): never saved
    root.querySelectorAll('[contenteditable]').forEach(e => e.removeAttribute('contenteditable'));
    root.querySelectorAll('.' + MARKS.join(', .')).forEach(e => e.classList.remove(...MARKS));
    root.querySelectorAll('[class=""]').forEach(e => e.removeAttribute('class'));
    return root;
  }
  function serialise() {
    const c = editor.cloneNode(true);
    c.querySelectorAll('.bs-uploading').forEach(e => e.remove());
    hidden.value = unmark(c).innerHTML.trim();
  }
  function changed() {
    dirty = true;
    document.getElementById('bsDirty').textContent = 'Unsaved changes';
    scheduleCheck();
    scheduleKeep();
    scheduleSnap();
  }

  // ---------------------------------------------------------------- undo and redo
  // the editor's own history: moving, copying and removing blocks is not something the browser can undo
  const hist = [];
  let at = -1, snapT = null;
  function caretPath() {
    const s = window.getSelection();
    if (!s.rangeCount || !editor.contains(s.anchorNode)) return null;
    const path = [];
    for (let n = s.anchorNode; n && n !== editor; n = n.parentNode) path.unshift(Array.prototype.indexOf.call(n.parentNode.childNodes, n));
    return { path, offset: s.anchorOffset };
  }
  function toCaret(c) {
    if (!c) return caretIn(editor.lastElementChild, true);
    let n = editor;
    for (const i of c.path) { if (!n.childNodes[i]) return caretIn(n, true); n = n.childNodes[i]; }
    const r = document.createRange();
    try { r.setStart(n, Math.min(c.offset, n.nodeType === 3 ? n.length : n.childNodes.length)); } catch (e) { return; }
    r.collapse(true);
    const s = window.getSelection();
    s.removeAllRanges();
    s.addRange(r);
  }
  function plainHtml() { return unmark(editor.cloneNode(true)).innerHTML; }    // the marks come and go: not a change
  function snap() {
    clearTimeout(snapT);
    const html = plainHtml();
    if (at >= 0 && hist[at].html === html) { hist[at].caret = caretPath(); return; }
    hist.splice(at + 1);
    hist.push({ html, caret: caretPath() });
    if (hist.length > 150) hist.shift();
    at = hist.length - 1;
  }
  function scheduleSnap() { clearTimeout(snapT); snapT = setTimeout(snap, 450); }
  function travel(step) {
    snap();
    const to = at + step;
    if (to < 0 || to >= hist.length) return;
    at = to;
    if (current) closePanel();
    editor.innerHTML = hist[at].html;
    lockBlocks();
    editor.focus();
    toCaret(hist[at].caret);
    floating();
    blockList();
    dirty = true;
    document.getElementById('bsDirty').textContent = 'Unsaved changes';
    scheduleCheck();
    scheduleKeep();
  }
  // a change made with buttons (not typing): one step of its own
  function structural(fn) {
    snap();
    fn();
    lines();
    lockBlocks();
    snap();
    changed();
    floating();
    blockList();
  }

  // ---------------------------------------------------------------- selection
  function keep() {
    const s = window.getSelection();
    if (s.rangeCount && editor.contains(s.anchorNode)) saved = s.getRangeAt(0).cloneRange();
  }
  function restore() {
    editor.focus();
    if (!saved || !editor.contains(saved.startContainer)) return;
    const s = window.getSelection();
    s.removeAllRanges();
    s.addRange(saved);
  }
  function savedBlock() { return saved && editor.contains(saved.startContainer) ? topBlock(saved.startContainer) : null; }
  function currentBlock() {
    const s = window.getSelection();
    let n = s.rangeCount ? s.anchorNode : null;
    while (n && n !== editor && !(n.nodeType === 1 && /^(P|H2|H3|BLOCKQUOTE|ASIDE|LI)$/.test(n.tagName))) n = n.parentNode;
    return n && n !== editor ? n : null;
  }
  function swapBlock(b, tag, cls) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    while (b.firstChild) n.appendChild(b.firstChild);
    if (!n.firstChild) n.innerHTML = '<br>';
    b.replaceWith(n);
    caretIn(n, true);
    return n;
  }
  function caretAtEnd(b) {
    const s = window.getSelection();
    if (!s.rangeCount) return false;
    const r = document.createRange();
    r.selectNodeContents(b);
    r.setStart(s.getRangeAt(0).endContainer, s.getRangeAt(0).endOffset);
    return !r.toString().trim();
  }
  function rectIn(el) {
    const w = wrap.getBoundingClientRect(), r = el.getBoundingClientRect();
    return { top: r.top - w.top, left: r.left - w.left, bottom: r.bottom - w.top, right: r.right - w.left };
  }
  function show(box, top, left) {
    box.hidden = false;
    box.style.top = top + 'px';
    box.style.left = Math.max(0, Math.min(left, wrap.clientWidth - box.offsetWidth)) + 'px';
  }

  // ---------------------------------------------------------------- adding blocks
  const BLOCKS = [
    { key: 'p', label: 'Paragraph', icon: 'fa-paragraph', hint: 'Plain text', words: 'text normal', group: 'text' },
    { key: 'h2', label: 'Heading', icon: 'fa-heading', hint: 'A section heading (H2)', words: 'h2 title section', group: 'text' },
    { key: 'h3', label: 'Sub-heading', icon: 'fa-heading', hint: 'A smaller heading inside a section (H3)', words: 'h3 subheading small', group: 'text' },
    { key: 'ul', label: 'Bulleted list', icon: 'fa-list-ul', hint: 'A list with dots', words: 'list bullets points ul', group: 'text' },
    { key: 'ol', label: 'Numbered list', icon: 'fa-list-ol', hint: 'Steps: 1, 2, 3 …', words: 'list numbers steps ol', group: 'text' },
    { key: 'quote', label: 'Quote', icon: 'fa-quote-left', hint: 'A large pull quote', words: 'blockquote pull', group: 'text' },
    { key: 'tip', label: 'Tip box', icon: 'fa-lightbulb', hint: 'A highlighted tip', words: 'note callout important', group: 'text' },
    { key: 'table', label: 'Table', icon: 'fa-table', hint: 'Rows and columns: add more from its bar', words: 'grid columns rows compare', group: 'text' },
    { key: 'image', label: 'Picture', icon: 'fa-image', hint: 'Upload one (or drag it in, or paste it)', words: 'image photo upload', group: 'media' },
    { key: 'library', label: 'From the library', icon: 'fa-photo-film', hint: 'A picture already uploaded', words: 'media library picture image photo', group: 'media' },
    { key: 'button', label: 'Button', icon: 'fa-hand-pointer', hint: 'A button to a page', words: 'cta link call to action', group: 'design' },
    { key: 'divider', label: 'Line across', icon: 'fa-minus', hint: 'Separates two parts', words: 'divider separator hr', group: 'layout' },
  ];
  const NAMES = { P: 'Paragraph', H2: 'Heading', H3: 'Sub-heading', UL: 'Bulleted list', OL: 'Numbered list',
                  BLOCKQUOTE: 'Quote', ASIDE: 'Tip box', FIGURE: 'Picture', TABLE: 'Table', HR: 'Line across' };
  if (BB()) BLOCKS.push(...BB().items);
  // what a block is called (the bar over it, the list view): the blocks of blog-blocks.js name themselves
  function nameOf(b) { return (BB() && BB().name(b)) || (isCta(b) ? 'Button' : (NAMES[b.tagName] || 'Block')); }

  function insertBlock(key, target, before) {
    target = target && editor.contains(target) ? target : (savedBlock() || editor.lastElementChild);
    if (BB() && BB().insert(key, target, before)) return;
    if (key === 'library') { openLib({ purpose: 'body', target }); return; }
    if (key === 'image') { pick('body', null, target); return; }
    if (key === 'button') { openButton(null, target); return; }
    let node, focus;
    const make = (tag, cls, html) => { const n = document.createElement(tag); if (cls) n.className = cls; n.innerHTML = html || '<br>'; return n; };
    if (key === 'p' || key === 'h2' || key === 'h3') node = focus = make(key);
    else if (key === 'ul' || key === 'ol') { node = make(key, null, '<li><br></li>'); focus = node.firstChild; }
    else if (key === 'quote') node = focus = make('blockquote');
    else if (key === 'tip') node = focus = make('aside', 'blog-note');
    else if (key === 'table') {
      const row = t => '<tr>' + ('<' + t + '><br></' + t + '>').repeat(3) + '</tr>';
      node = make('table', null, '<thead>' + row('th') + '</thead><tbody>' + row('td') + row('td') + '</tbody>');
      focus = node.querySelector('th');
    } else if (key === 'divider') node = document.createElement('hr');
    else return;
    structural(() => {
      place(node, target, before);
      if (!isText(node) && !before) { const line = after(node); focus = focus || line; }   // somewhere to go on writing
    });
    caretIn(focus);
    floating();
  }

  // the menu of blocks: from "Add block", the + on an empty line, or "/" typed on an empty line
  const list = menu.querySelector('.bs-menu-list');
  const search = menu.querySelector('.bs-menu-q');
  let menuMode = null, menuTarget = null, menuItems = [], menuSel = 0;
  function openMenu(mode, target, anchor) {
    menuMode = mode;
    menuTarget = target;
    search.hidden = mode === 'slash';
    search.value = '';
    renderMenu('');
    const r = rectIn(anchor || target || editor);
    show(menu, r.bottom + 6, anchor ? r.left : r.left + 4);
    if (mode !== 'slash') search.focus();
  }
  function renderMenu(q) {
    q = q.toLowerCase().trim();
    menuItems = BLOCKS.filter(b => !q || (b.label + ' ' + b.words).toLowerCase().includes(q));
    menuSel = 0;
    list.innerHTML = menuItems.map((b, i) => '<button type="button" class="bs-mi' + (i ? '' : ' is-on') + '" data-key="' + b.key +
      '" role="option"><i class="' + (b.icon.startsWith('fa-brands') ? b.icon : 'fa-solid ' + b.icon) + (b.key === 'h3' ? ' is-small' : '') + '"></i><span><b>' + esc(b.label) +
      '</b><small>' + esc(b.hint) + '</small></span></button>').join('');
    menu.querySelector('.bs-menu-none').hidden = menuItems.length > 0;
  }
  function moveSel(step) {
    if (!menuItems.length) return;
    menuSel = (menuSel + step + menuItems.length) % menuItems.length;
    list.querySelectorAll('.bs-mi').forEach((b, i) => b.classList.toggle('is-on', i === menuSel));
    list.children[menuSel].scrollIntoView({ block: 'nearest' });
  }
  function closeMenu() { menu.hidden = true; menuMode = null; }
  function pickMenu(key) {
    const mode = menuMode, target = menuTarget;
    closeMenu();
    if (mode === 'slash' && target && editor.contains(target)) target.innerHTML = '<br>';     // the "/head" that was typed
    insertBlock(key, target);
  }
  menu.addEventListener('mousedown', e => { if (e.target.closest('.bs-mi')) e.preventDefault(); });
  menu.addEventListener('click', e => { const b = e.target.closest('.bs-mi'); if (b) pickMenu(b.dataset.key); });
  search.addEventListener('input', () => renderMenu(search.value));
  search.addEventListener('keydown', e => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); moveSel(e.key === 'ArrowDown' ? 1 : -1); }
    else if (e.key === 'Enter') { e.preventDefault(); if (menuItems.length) pickMenu(menuItems[menuSel].key); }
    else if (e.key === 'Escape') { e.preventDefault(); closeMenu(); restore(); }
  });
  plus.addEventListener('mousedown', e => e.preventDefault());
  plus.addEventListener('click', () => { inserter(true, caretBlock() || savedBlock()); document.getElementById('geInsFind').focus(); });

  // ---------------------------------------------------------------- the bar over a block
  let typing = false;
  function setActive(b) {
    const was = active;
    active = b && b.parentNode === editor ? b : null;
    floating();
    lvHere();
    // the Block tab follows the block being worked on
    const pane = document.querySelector('#geSide [data-spane=block]');
    if (BB() && pane && active && active !== was && !pane.hidden) { picked = active; BB().pane(active); }
  }
  function floating() {
    // the + on an empty line, the "Type / ..." hint, and the bar over the block the caret is in
    // (hidden while typing, back when the mouse moves)
    const only = editor.children.length === 1 && isEmpty(editor.firstElementChild) ? editor.firstElementChild : null;
    const empty = active && isEmpty(active);
    editor.querySelectorAll('.bs-ph').forEach(p => { if (p !== only && !(empty && p === active)) p.classList.remove('bs-ph'); });
    if (only) only.classList.add('bs-ph');
    if (empty && editor.contains(active)) {
      active.classList.add('bs-ph');
      const r = rectIn(active);
      show(plus, r.top + (active.offsetHeight - 30) / 2, r.right - 34);
    } else plus.hidden = true;
    if (!active || empty || typing || !editor.contains(active)) { bbar.hidden = true; return; }
    bbar.querySelector('.bs-bb-name').textContent = nameOf(active);
    bbar.querySelector('.bs-bb-table').hidden = active.tagName !== 'TABLE';
    bbar.hidden = false;
    const r = rectIn(active);
    show(bbar, Math.max(r.top - bbar.offsetHeight - 6, -bbar.offsetHeight - 2), r.right - bbar.offsetWidth);
  }
  bbar.addEventListener('mousedown', e => { if (!e.target.closest('.bs-bb-grip')) e.preventDefault(); });   // the caret stays (the grip drags)
  bbar.addEventListener('click', e => {
    const b = e.target.closest('[data-bb]');
    if (!b || !active || !editor.contains(active)) return;
    const what = b.dataset.bb, blk = active;
    if (what === 'settings') { blockSettings(blk); return; }
    if (what === 'reuse') { if (BB()) BB().createFrom([blk]); return; }
    if (/^(row|col|delrow|delcol)$/.test(what)) return tableOp(what, blk);
    if (what === 'remove') { caretIn(removeBlocks([blk])); return; }
    if (!/^(up|down|copy)$/.test(what)) return;
    caretStays(() => what === 'copy' ? duplicateBlocks([blk]) : moveBlocks([blk], what === 'up' ? -1 : 1));
    editor.focus();
    keep();
    floating();
  });

  function tableOp(what, table) {
    const s = window.getSelection();
    let cell = s.rangeCount && table.contains(s.anchorNode) ? s.anchorNode : null;
    while (cell && !(cell.nodeType === 1 && /^(TD|TH)$/.test(cell.tagName))) cell = cell.parentNode;
    const rows = Array.from(table.querySelectorAll('tr'));
    const row = cell ? cell.parentNode : rows[rows.length - 1];
    const idx = cell ? cell.cellIndex : row.cells.length - 1;
    const body = table.querySelector('tbody') || table;
    if (what === 'row') {
      structural(() => {
        const tr = document.createElement('tr');
        tr.innerHTML = '<td><br></td>'.repeat(row.cells.length);
        if (row.parentNode.tagName === 'THEAD') body.prepend(tr); else row.after(tr);
        caretIn(tr.cells[Math.min(idx, tr.cells.length - 1)]);
      });
    } else if (what === 'col') {
      structural(() => rows.forEach(tr => {
        const c = document.createElement(tr.parentNode.tagName === 'THEAD' ? 'th' : 'td');
        c.innerHTML = '<br>';
        const ref = tr.cells[idx];
        if (ref) ref.after(c); else tr.appendChild(c);
      }));
    } else if (what === 'delrow') {
      if (row.parentNode.tagName === 'THEAD') { toast('The first row is the table’s heading row: type over it instead.', 'warning'); return; }
      if (body.querySelectorAll('tr').length < 2) { toast('A table keeps at least one row. Remove the table from its bar instead.', 'warning'); return; }
      structural(() => { const next = row.nextElementSibling || row.previousElementSibling; row.remove(); caretIn(next.cells[0]); });
    } else if (what === 'delcol') {
      if (row.cells.length < 2) { toast('A table keeps at least one column.', 'warning'); return; }
      structural(() => { rows.forEach(tr => { if (tr.cells[idx]) tr.cells[idx].remove(); }); caretIn(row.cells[Math.max(0, idx - 1)]); });
    }
  }

  // ---------------------------------------------------------------- whole blocks: move, duplicate, delete, copy, paste
  // The bar over a block, the list view and the shortcuts all come here; each change is one step of undo.
  // Copied blocks are kept in this browser, not only this page, so they can be pasted into another post.
  const inOrder = bs => Array.from(editor.children).filter(b => bs.includes(b));
  const trailing = b => !!b && b === editor.lastElementChild && isEmpty(b);   // the line always there to type on
  const plural = (n, w) => n + ' ' + w + (n === 1 ? '' : 's');
  function caretStays(fn) {                        // moving a block must not lose the caret inside it
    const s = window.getSelection();
    const spot = s.rangeCount && editor.contains(s.anchorNode) ? [s.anchorNode, s.anchorOffset] : null;
    const out = fn();
    if (spot && editor.contains(spot[0])) {
      try { const r = document.createRange(); r.setStart(spot[0], spot[1]); r.collapse(true); s.removeAllRanges(); s.addRange(r); } catch (err) { /* moved away */ }
    }
    return out;
  }
  function moveBlocks(bs, step) {
    bs = inOrder(bs);
    if (!bs.length) return false;
    const prev = bs[0].previousElementSibling, next = bs[bs.length - 1].nextElementSibling;
    if (step < 0 ? !prev : (!next || trailing(next))) return false;
    structural(() => {
      if (step < 0) bs.forEach(b => prev.before(b));
      else bs.slice().reverse().forEach(b => next.after(b));
    });
    return true;
  }
  function clean(b) {                              // a block as it is saved: without the editor's marks
    const box = document.createElement('div');
    box.appendChild(b.cloneNode(true));
    return unmark(box).firstElementChild;
  }
  function duplicateBlocks(bs) {
    bs = inOrder(bs).filter(b => !isEmpty(b));
    if (!bs.length) return [];
    const copies = bs.map(clean);
    structural(() => { let ref = bs[bs.length - 1]; copies.forEach(c => { ref.after(c); ref = c; }); });
    return copies;
  }
  function removeBlocks(bs) {                      // returns the block next to them, for the caret
    bs = inOrder(bs);
    if (!bs.length) return null;
    const near = bs[bs.length - 1].nextElementSibling || bs[0].previousElementSibling;
    if (bs.includes(current)) closePanel();
    structural(() => bs.forEach(b => b.remove()));
    setActive(null);
    return near && editor.contains(near) ? near : editor.firstElementChild;
  }
  function addLine(b, before) {                    // an empty line before or after a block: type, or "/" or + for a block
    const p = para();
    structural(() => { if (before) b.before(p); else b.after(p); });
    caretIn(p);
    setActive(p);
    return p;
  }
  // "Turn into": a paragraph, heading, quote or tip box into another of those or into a list; a list into the
  // other kind of list, or each of its points into a paragraph, heading ...
  const KINDS = [['p', 'Paragraph'], ['h2', 'Heading'], ['h3', 'Sub-heading'], ['quote', 'Quote'], ['tip', 'Tip box'],
                 ['ul', 'Bulleted list'], ['ol', 'Numbered list']];
  const turnable = b => !!b && !isCta(b) && /^(P|H2|H3|BLOCKQUOTE|ASIDE|UL|OL)$/.test(b.tagName);
  const kindOf = b => ({ BLOCKQUOTE: 'quote', ASIDE: 'tip' })[b.tagName] || b.tagName.toLowerCase();
  function turnInto(bs, kind) {
    bs = inOrder(bs).filter(turnable);
    if (!bs.length) return;
    const tag = ({ quote: 'blockquote', tip: 'aside' })[kind] || kind;
    const make = html => { const n = document.createElement(tag); if (kind === 'tip') n.className = 'blog-note'; n.innerHTML = html || '<br>'; return n; };
    structural(() => bs.forEach(b => {
      if (/^(UL|OL)$/.test(b.tagName)) {
        if (kind === 'ul' || kind === 'ol') { const n = document.createElement(tag); while (b.firstChild) n.appendChild(b.firstChild); b.replaceWith(n); }
        else b.replaceWith(...Array.from(b.children).map(li => make(li.innerHTML)));
        return;
      }
      // a quote or tip box can hold paragraphs: their lines join
      const inner = b.querySelector('p, h2, h3, ul, ol') ? Array.from(b.children).map(c => c.innerHTML).join('<br>') : b.innerHTML;
      b.replaceWith(kind === 'ul' || kind === 'ol' ? Object.assign(document.createElement(tag), { innerHTML: '<li>' + (inner || '<br>') + '</li>' }) : make(inner));
    }));
  }
  const CLIP = 'bs.clip';
  let memClip = null;
  function clip() {
    try {
      const c = JSON.parse(localStorage.getItem(CLIP) || 'null');
      if (c && c.v === 1 && Array.isArray(c.blocks) && c.blocks.length) return c;
    } catch (e) { /* private mode */ }
    return memClip;
  }
  function copyBlocks(bs, e) {                     // e: the copy or cut event, when there is one
    bs = inOrder(bs).filter(b => !isEmpty(b));
    if (!bs.length) return 0;
    const c = { v: 1, id: Date.now().toString(36), blocks: bs.map(b => clean(b).outerHTML) };
    memClip = c;
    try { localStorage.setItem(CLIP, JSON.stringify(c)); } catch (err) { /* this page only */ }
    // other programs get the words; this editor knows its own copy by the mark and takes the blocks whole
    const html = '<div data-bs-clip="' + c.id + '">' + c.blocks.join('') + '</div>';
    const text = bs.map(b => b.innerText.trim()).filter(Boolean).join('\n\n');
    if (e && e.clipboardData) { e.preventDefault(); e.clipboardData.setData('text/html', html); e.clipboardData.setData('text/plain', text); }
    else if (navigator.clipboard && window.ClipboardItem) {
      navigator.clipboard.write([new ClipboardItem({ 'text/html': new Blob([html], { type: 'text/html' }),
                                                     'text/plain': new Blob([text], { type: 'text/plain' }) })]).catch(() => {});
    }
    return bs.length;
  }
  const ourClip = html => { const m = html && /data-bs-clip="(\w+)"/.exec(html), c = m && clip(); return c && c.id === m[1] ? c : null; };
  const textHtml = text => text.replace(/\r/g, '').split(/\n{2,}/).map(p => p.trim()).filter(Boolean)
    .map(p => '<p>' + esc(p).replace(/\n/g, '<br>') + '</p>').join('');
  const blocky = html => /^\s*<(p|h2|h3|ul|ol|blockquote|aside|table|hr|figure)[\s>]/i.test(html) ? html : '<p>' + html + '</p>';
  // blocks (as html) into the post after `ref` -- an empty line there is filled -- or at the end
  function insertBlocks(html, ref, before) {
    const box = document.createElement('div');
    box.innerHTML = html;
    box.querySelectorAll('script, style, iframe, object, embed').forEach(n => n.remove());
    box.querySelectorAll('*').forEach(n => Array.from(n.attributes).forEach(a => { if (/^on/i.test(a.name)) n.removeAttribute(a.name); }));
    const nodes = Array.from(box.children);
    if (!nodes.length) return [];
    ref = ref && editor.contains(ref) ? ref : (trailing(editor.lastElementChild) ? editor.lastElementChild : null);
    structural(() => nodes.forEach((n, i) => {
      if (i === 0 && ref && isEmpty(ref)) ref.replaceWith(n);
      else if (i === 0 && ref && before) ref.before(n);
      else if (ref) ref.after(n);
      else editor.appendChild(n);
      ref = n;
    }));
    return nodes;
  }
  function pasteBlocks(ref) {
    const c = clip();
    if (!c) { toast('Nothing copied yet: copy or cut blocks in the list view first.', 'warning'); return []; }
    return insertBlocks(c.blocks.join(''), ref);
  }

  // ---------------------------------------------------------------- the toolbar
  const toolbar = document.getElementById('bsToolbar');
  toolbar.addEventListener('mousedown', e => { if (e.target.closest('button')) e.preventDefault(); });   // keep the selection
  toolbar.addEventListener('click', e => {
    const b = e.target.closest('button');
    if (!b || !b.dataset.do) return;
    const what = b.dataset.do;
    if (what === 'undo' || what === 'redo') { travel(what === 'undo' ? -1 : 1); return; }
    if (what === 'link') { restore(); openLink(); return; }
    restore();
    snap();
    if (what === 'cmd') {
      document.execCommand(b.dataset.cmd, false, null);
    } else if (what === 'block') {
      // H2, H3, the paragraph mark and the quote turn the line the caret is in into that; a second click undoes it
      let cur = currentBlock();
      if (cur && cur.tagName === 'ASIDE') cur = swapBlock(cur, 'p');
      const q = cur && cur.closest('blockquote');
      if (b.dataset.tag === 'blockquote') {
        if (q && q.querySelector('p, h2, h3, ul, ol')) { const first = q.firstElementChild; q.replaceWith(...q.childNodes); caretIn(first, true); }
        else if (q) swapBlock(q, 'p');
        else if (cur && cur.tagName !== 'LI') swapBlock(cur, 'blockquote');
      } else {
        if (q && q === cur) cur = swapBlock(q, 'p');
        const tag = cur && cur.tagName.toLowerCase() === b.dataset.tag ? 'p' : b.dataset.tag;
        document.execCommand('formatBlock', false, '<' + tag + '>');
      }
    } else if (what === 'note') {
      const cur = currentBlock();
      if (!cur) return;
      if (cur.tagName === 'ASIDE') swapBlock(cur, 'p');
      else if (cur.tagName !== 'LI') swapBlock(cur, 'aside', 'blog-note');
    } else if (what === 'clear') {
      document.execCommand('removeFormat', false, null);
      document.execCommand('formatBlock', false, '<p>');
    }
    lines();
    changed();
    keep();
    setActive(caretBlock());
  });

  // ---------------------------------------------------------------- links and buttons
  const popText = pop.querySelector('[data-k=text]'), popUrl = pop.querySelector('[data-k=url]');
  const popLook = pop.querySelector('[data-k=look]'), popTab = pop.querySelector('[data-k=tab]');
  const LOOKS = ['lk-btn', 'lk-outline', 'lk-arrow'];
  const popErr = pop.querySelector('.bs-pop-err');
  let popDo = null;
  function address(v, button) {
    v = (v || '').trim();
    if (/^www\.|^[a-z0-9-]+(\.[a-z0-9-]+)+(\/|$)/i.test(v)) v = 'https://' + v;
    const ok = button ? /^(https?:\/\/|\/(?!\/))/i : /^(https?:\/\/|mailto:|tel:|\/(?!\/))/i;
    return ok.test(v) ? v : null;
  }
  function openPop(opts) {
    popDo = opts;
    pop.querySelector('[data-for=text]').hidden = !opts.text;
    pop.querySelector('[data-for=text]').firstChild.textContent = opts.button ? 'Button text' : 'Text to show';
    pop.querySelector('[data-for=url] span').textContent = opts.button ? 'Goes to' : 'Link to';
    pop.querySelector('[data-pop=remove]').hidden = !opts.remove;
    // a link in the text can look like a button or an arrow link; links and buttons can open in a new tab
    pop.querySelector('[data-for=look]').hidden = !!opts.button;
    popLook.value = opts.look || '';
    popTab.checked = !!opts.newTab;
    popText.value = opts.textValue || '';
    popUrl.value = opts.url || '';
    popErr.hidden = true;
    const r = opts.anchor ? rectIn(opts.anchor) : null;
    show(pop, r ? r.bottom + 8 : 0, r ? r.left : 0);
    (opts.text && !popText.value ? popText : popUrl).focus();
  }
  function closePop() { pop.hidden = true; popDo = null; }
  function applyPop() {
    if (!popDo) return;
    const url = address(popUrl.value, popDo.button);
    if (popDo.text && !popText.value.trim()) { popErr.textContent = popDo.button ? 'Write the button’s words.' : 'Write the words to show.'; popErr.hidden = false; return; }
    if (!url) {
      popErr.textContent = popDo.button ? 'Use a page of this site like /travel-insurance, or an https:// address.'
        : 'Use an https:// address, or a page of this site starting with /.';
      popErr.hidden = false;
      return;
    }
    const fn = popDo.apply, look = popLook.value, newTab = popTab.checked;
    closePop();
    fn(url, popText.value.trim(), look, newTab);
  }
  // how a link looks and where it opens: the classes and target blog_engine keeps
  function dressLink(a, look, newTab) {
    LOOKS.forEach(c => a.classList.remove(c));
    if (look) a.classList.add(look);
    if (!a.className) a.removeAttribute('class');
    if (newTab) { a.setAttribute('target', '_blank'); a.setAttribute('rel', 'noopener noreferrer'); }
    else { a.removeAttribute('target'); a.removeAttribute('rel'); }
  }
  pop.addEventListener('click', e => {
    const b = e.target.closest('[data-pop]');
    if (!b) return;
    if (b.dataset.pop === 'apply') applyPop();
    else if (b.dataset.pop === 'remove') { const fn = popDo && popDo.remove; closePop(); if (fn) fn(); }
    else { closePop(); restore(); }
  });
  pop.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); applyPop(); }
    else if (e.key === 'Escape') { e.preventDefault(); closePop(); restore(); }
  });

  function openLink() {
    keep();
    const range = saved;
    if (!range) { toast('Click in the post first, where the link goes.', 'warning'); return; }
    let a = range.startContainer;
    while (a && a !== editor && !(a.nodeType === 1 && a.tagName === 'A')) a = a.parentNode;
    if (a === editor) a = null;
    const anchorEl = a || (range.startContainer.nodeType === 1 ? range.startContainer : range.startContainer.parentNode);
    if (a) {
      openPop({ url: a.getAttribute('href'), remove: true, anchor: a, look: LOOKS.find(c => a.classList.contains(c)) || '',
        newTab: a.getAttribute('target') === '_blank',
        apply: (url, _t, look, newTab) => structural(() => { a.setAttribute('href', url); dressLink(a, look, newTab); }),
        remove: () => structural(() => { a.replaceWith(...a.childNodes); }) });
    } else if (range.collapsed) {
      openPop({ text: true, anchor: anchorEl, apply: (url, text, look, newTab) => {
        restore();
        document.execCommand('insertHTML', false, '<a href="' + esc(url) + '"' + (look ? ' class="' + look + '"' : '') +
          (newTab ? ' target="_blank" rel="noopener noreferrer"' : '') + '>' + esc(text) + '</a>&nbsp;');
        changed();
      } });
    } else {
      openPop({ anchor: anchorEl, apply: (url, _t, look, newTab) => {
        restore();
        document.execCommand('createLink', false, url);
        const s = window.getSelection();
        let n = s.rangeCount ? s.getRangeAt(0).commonAncestorContainer : null;
        while (n && n !== editor && !(n.nodeType === 1 && n.tagName === 'A')) n = n.parentNode;
        if (n && n !== editor) dressLink(n, look, newTab);
        else editor.querySelectorAll('a[href="' + CSS.escape(url) + '"]').forEach(x => dressLink(x, look, newTab));
        changed();
      } });
    }
  }
  function openButton(cta, target) {
    const a = cta && cta.querySelector('a');
    openPop({ button: true, text: true, textValue: a ? a.textContent : '', url: a ? a.getAttribute('href') : '',
      remove: !!cta, anchor: cta || target || editor.lastElementChild, newTab: a && a.getAttribute('target') === '_blank',
      apply: (url, text, _look, newTab) => structural(() => {
        if (a) {
          a.setAttribute('href', url); a.textContent = text;
          if (newTab) { a.setAttribute('target', '_blank'); a.setAttribute('rel', 'noopener noreferrer'); } else { a.removeAttribute('target'); a.removeAttribute('rel'); }
          return;
        }
        const p = document.createElement('p');
        p.className = 'blog-cta-wrap';
        p.innerHTML = '<a class="blog-cta" href="' + esc(url) + '"' + (newTab ? ' target="_blank" rel="noopener noreferrer"' : '') + '>' + esc(text) + '</a>';
        place(p, target);
        caretIn(after(p));
      }),
      remove: () => structural(() => cta.remove()) });
  }

  // ---------------------------------------------------------------- pasting
  // text from Word, Google Docs or a web page keeps what a post has (headings, bold, italics,
  // underline, lists, links, tables) and loses the rest; pictures come as files, not inside text
  const MAP = { P: 'p', DIV: 'p', H1: 'h2', H2: 'h2', H3: 'h3', H4: 'h3', H5: 'h3', H6: 'h3', UL: 'ul', OL: 'ol', LI: 'li',
                BLOCKQUOTE: 'blockquote', TABLE: 'table', THEAD: 'thead', TBODY: 'tbody', TR: 'tr', TH: 'th', TD: 'td',
                STRONG: 'strong', B: 'strong', EM: 'em', I: 'em', U: 'u', A: 'a', BR: 'br', HR: 'hr' };
  const SKIP = /^(SCRIPT|STYLE|META|LINK|TITLE|HEAD|NOSCRIPT|TEMPLATE|SVG|IFRAME|OBJECT|BUTTON|INPUT|SELECT|TEXTAREA|O:P)$/;
  const CONTAINERS = /^(BODY|UL|OL|TABLE|THEAD|TBODY|TR)$/;
  function cleanPaste(html) {
    const doc = new DOMParser().parseFromString(html, 'text/html');
    let pictures = 0;
    function walk(n, inHeading) {
      if (n.nodeType === 3) {
        if (!/\S/.test(n.textContent) && CONTAINERS.test(n.parentNode.tagName)) return '';
        return esc(n.textContent.replace(/\s+/g, ' '));
      }
      if (n.nodeType !== 1) return '';
      const tag = n.tagName.toUpperCase();
      const style = (n.getAttribute('style') || '').toLowerCase();
      if (SKIP.test(tag) || /mso-list\s*:\s*ignore/.test(style)) return '';
      if (tag === 'IMG') { pictures++; return ''; }
      let t = MAP[tag] || null;
      if (tag === 'B' && /font-weight\s*:\s*(normal|400)/.test(style)) t = null;      // Google Docs wraps a paste in one
      const heading = inHeading || t === 'h2' || t === 'h3';
      let inner = Array.from(n.childNodes).map(c => walk(c, heading)).join('');
      if (!t || /^(p|li|td|th|a)$/.test(t)) {
        if (!heading && t !== 'strong' && /font-weight\s*:\s*(bold|[6-9]00)/.test(style)) inner = '<strong>' + inner + '</strong>';
        if (t !== 'em' && /font-style\s*:\s*italic/.test(style)) inner = '<em>' + inner + '</em>';
        if (t !== 'u' && t !== 'a' && /text-decoration[^;]*underline/.test(style)) inner = '<u>' + inner + '</u>';
      }
      if (!t) return inner;
      if (t === 'br' || t === 'hr') return '<' + t + '>';
      if (t === 'a') {
        const h = (n.getAttribute('href') || '').trim();
        return /^(https?:\/\/|mailto:|tel:|\/(?!\/))/i.test(h) ? '<a href="' + esc(h) + '">' + inner + '</a>' : inner;
      }
      if (/^(p|h2|h3|li)$/.test(t) && !inner.replace(/<br>|&nbsp;|\s/g, '')) return '';
      return '<' + t + '>' + inner + '</' + t + '>';
    }
    const out = walk(doc.body, false);
    return { html: out, pictures };
  }
  editor.addEventListener('paste', e => {
    const cd = e.clipboardData || window.clipboardData;
    if (!cd) return;
    const url = (cd.getData('text/plain') || '').trim();
    if (BB() && /^https?:\/\/\S+$/.test(url) && BB().pasteUrl(url, caretBlock())) { e.preventDefault(); return; }
    const files = Array.from(cd.files || []).filter(f => /^image\/(jpeg|png|webp)$/.test(f.type));
    if (files.length) { e.preventDefault(); insertPictures(files, caretBlock()); return; }
    e.preventDefault();
    const html = cd.getData('text/html');
    if (ourClip(html)) { pasteBlocks(caretBlock()); return; }         // blocks copied in this editor: whole, pictures and all
    if (html) {
      const got = cleanPaste(html);
      if (got.pictures) toast('Pictures do not come with copied text: add each one with Picture, or paste it on its own.', 'warning');
      if (got.html.trim()) {
        document.execCommand('insertHTML', false, got.html);
        lines(); lockBlocks(); changed();
        return;
      }
    }
    const text = cd.getData('text/plain');
    if (!text) return;
    if (!/\n\s*\n/.test(text.replace(/\r/g, '').trim())) document.execCommand('insertText', false, text);
    else document.execCommand('insertHTML', false, textHtml(text));
    changed();
  });

  // ---------------------------------------------------------------- typing
  editor.addEventListener('keydown', e => {
    const mod = e.ctrlKey || e.metaKey, k = e.key;
    if (!/^(Control|Shift|Alt|Meta|Escape)$/.test(k)) picked = null;
    if (mod && k.toLowerCase() === 'z') { e.preventDefault(); travel(e.shiftKey ? 1 : -1); return; }
    if (mod && k.toLowerCase() === 'y') { e.preventDefault(); travel(1); return; }
    if (mod && k.toLowerCase() === 'k') { e.preventDefault(); openLink(); return; }
    // the block the caret is in, as WordPress has it: duplicate, a line before / after, move, delete
    const here = caretBlock();
    if (here && mod && e.shiftKey && !e.altKey && k.toLowerCase() === 'd') { e.preventDefault(); caretStays(() => duplicateBlocks([here])); return; }
    if (here && mod && e.altKey && /^[ty]$/i.test(k)) { e.preventDefault(); addLine(here, k.toLowerCase() === 't'); return; }
    if (here && e.altKey && e.shiftKey && !mod && (k === 'ArrowUp' || k === 'ArrowDown')) { e.preventDefault(); caretStays(() => moveBlocks([here], k === 'ArrowUp' ? -1 : 1)); return; }
    if (here && e.altKey && e.shiftKey && !mod && k.toLowerCase() === 'z') { e.preventDefault(); caretIn(removeBlocks([here])); return; }
    if (menuMode === 'slash' && !menu.hidden) {
      if (k === 'ArrowDown' || k === 'ArrowUp') { e.preventDefault(); moveSel(k === 'ArrowDown' ? 1 : -1); return; }
      if ((k === 'Enter' || k === 'Tab') && menuItems.length) { e.preventDefault(); pickMenu(menuItems[menuSel].key); return; }
      if (k === 'Escape') { e.preventDefault(); closeMenu(); return; }
    }
    const b = caretBlock();
    if (k === 'Enter' && !e.shiftKey && b && (b.tagName === 'BLOCKQUOTE' || b.tagName === 'ASIDE')) {
      e.preventDefault();                 // Enter at the end of a quote or tip goes on below it, not into another one
      if (caretAtEnd(b)) structural(() => caretIn(after(b)));
      else document.execCommand('insertLineBreak');
      return;
    }
    if (k === 'Tab' && b && b.tagName === 'TABLE') {
      const cells = Array.from(b.querySelectorAll('th, td'));
      let cell = window.getSelection().anchorNode;
      while (cell && !(cell.nodeType === 1 && /^(TD|TH)$/.test(cell.tagName))) cell = cell.parentNode;
      const i = cells.indexOf(cell);
      if (i >= 0) {
        e.preventDefault();
        if (!e.shiftKey && i === cells.length - 1) { active = b; tableOp('row', b); return; }   // Tab in the last cell: a new row
        caretIn(cells[Math.max(0, i + (e.shiftKey ? -1 : 1))], true);
        return;
      }
    }
    if (!mod && k.length === 1) { typing = true; bbar.hidden = true; }     // typing: the block bar steps out of the way
  });
  editor.addEventListener('beforeinput', e => {
    if (e.inputType === 'historyUndo') { e.preventDefault(); travel(-1); }
    else if (e.inputType === 'historyRedo') { e.preventDefault(); travel(1); }
  });
  editor.addEventListener('input', () => {
    if (!editor.firstElementChild || editor.childNodes.length === 1 && editor.firstChild.nodeType === 3) { lines(); caretIn(editor.firstElementChild, true); }
    changed();
    const b = caretBlock();
    const t = b && b.tagName === 'P' && !isCta(b) ? b.textContent : '';
    if (/^\/[\w -]{0,24}$/.test(t)) {
      if (menuMode !== 'slash' || menuTarget !== b) openMenu('slash', b);
      renderMenu(t.slice(1));
    } else if (menuMode === 'slash') closeMenu();
    floating();                                    // the hint goes with the first letter
  });
  let rafId = 0;
  document.addEventListener('selectionchange', () => {
    cancelAnimationFrame(rafId);
    rafId = requestAnimationFrame(() => {
      const s = window.getSelection();
      if (!s.rangeCount || !editor.contains(s.anchorNode)) return;
      keep();
      if (picked && editor.contains(picked)) return;        // a picture or button was clicked: its bar stays
      const b = caretBlock();
      if (menuMode === 'slash' && b !== menuTarget) closeMenu();
      setActive(b);
    });
  });
  wrap.addEventListener('mousemove', () => { if (typing) { typing = false; floating(); } });
  editor.addEventListener('mousedown', () => { typing = false; picked = null; });
  editor.addEventListener('click', e => {
    const fig = e.target.closest('figure');
    const cta = e.target.closest('p.blog-cta-wrap');
    const obj = e.target.closest('.blog-ref:not(.is-editing), .blog-code, .blog-spacer, .blog-carousel, figure.blog-embed, figure.blog-video');
    if (obj && editor.contains(obj) && !e.target.closest('.blog-carousel > div.blog-slide')) {
      e.preventDefault(); closePop(); if (!panel.hidden) closePanel();
      const top = topBlock(obj); picked = top; setActive(top); blockSettings(top); return;
    }
    if (fig && editor.contains(fig)) { e.preventDefault(); closePop(); picked = fig; openPanel(fig); setActive(topBlock(fig)); return; }
    if (!panel.hidden) closePanel();
    if (cta && editor.contains(cta)) { e.preventDefault(); picked = cta; setActive(cta); openButton(cta, cta); return; }
    if (e.target.tagName === 'HR') { picked = e.target; setActive(e.target); return; }
  });
  document.addEventListener('mousedown', e => {
    if (!menu.hidden && !menu.contains(e.target) && !e.target.closest('[data-do=menu]') && e.target !== plus && !plus.contains(e.target)) closeMenu();
    if (!pop.hidden && !pop.contains(e.target)) closePop();
  });
  window.addEventListener('resize', floating);

  // ---------------------------------------------------------------- pictures
  async function upload(file, purpose) {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('purpose', purpose);
    const r = await fetch(form.dataset.imageUrl, { method: 'POST', headers: { 'X-CSRFToken': CSRF }, body: fd, credentials: 'same-origin' });
    const d = await r.json().catch(() => ({}));
    if (!r.ok || !d.url) throw new Error(d.error || 'The picture could not be uploaded.');
    return d;
  }
  function pick(purpose, figure, target) {
    picking = { purpose, figure, target };
    fileInput.multiple = (purpose === 'body' && !figure) || purpose === 'library';
    fileInput.value = '';
    fileInput.click();
  }
  fileInput.addEventListener('change', async () => {
    const files = Array.from(fileInput.files);
    if (!files.length || !picking) return;
    const { purpose, figure, target } = picking;
    picking = null;
    if (purpose === 'cover') return coverUpload(files[0]);
    if (purpose === 'thumb') return thumbUpload(files[0]);
    if (purpose === 'library') return libUpload(files);
    if (!figure) return insertPictures(files, target);
    let d;
    try { d = await upload(files[0], 'body'); } catch (err) { toast(err.message, 'danger'); return; }
    const alt = figure.querySelector('img')?.alt || figure.dataset.alt || '';
    const cap = figure.querySelector('figcaption');
    structural(() => {
      keepKind(figure);
      figure.removeAttribute('data-file');
      figure.removeAttribute('data-alt');
      figure.innerHTML = '<img src="' + esc(d.src) + '" alt="' + esc(alt) + '" data-file="' + esc(d.name) + '" loading="lazy">' + (cap ? cap.outerHTML : '');
    });
    openPanel(figure);
  });
  // each picture goes in as a box saying it is uploading, then becomes the picture, its panel open
  async function insertPictures(files, target) {
    files = files.filter(f => /\.(jpe?g|png|webp)$/i.test(f.name) || /^image\/(jpeg|png|webp)$/.test(f.type));
    if (!files.length) { toast('Use a JPG, PNG or WebP picture.', 'danger'); return; }
    snap();
    let spot = target && editor.contains(target) ? target : (savedBlock() || editor.lastElementChild);
    let last = null;
    for (const file of files) {
      const fig = document.createElement('figure');
      fig.className = 'blog-img bs-uploading';
      fig.setAttribute('contenteditable', 'false');
      fig.innerHTML = '<span><i class="fa-solid fa-spinner fa-spin"></i> Uploading ' + esc(file.name || 'the picture') + '…</span>';
      place(fig, spot);
      spot = fig;
      after(fig);
      try {
        const d = await upload(file, 'body');
        fig.className = 'blog-img';
        fig.innerHTML = '<img src="' + esc(d.src) + '" alt="" data-file="' + esc(d.name) + '" loading="lazy">';
        last = fig;
      } catch (err) {
        fig.remove();
        toast(err.message, 'danger');
      }
    }
    lines();
    lockBlocks();
    snap();
    changed();
    if (last) { openPanel(last); setActive(last); panel.querySelector('[data-k=alt]').focus(); }
  }
  editor.addEventListener('dragover', e => {
    if (!Array.from(e.dataTransfer.types || []).includes('Files')) return;
    e.preventDefault();
    wrap.classList.add('is-drop');
  });
  editor.addEventListener('dragleave', e => { if (!editor.contains(e.relatedTarget)) wrap.classList.remove('is-drop'); });
  editor.addEventListener('drop', e => {
    wrap.classList.remove('is-drop');
    const files = Array.from(e.dataTransfer.files || []);
    if (!files.length) return;
    e.preventDefault();
    let node = null;
    if (document.caretRangeFromPoint) node = document.caretRangeFromPoint(e.clientX, e.clientY)?.startContainer;
    else if (document.caretPositionFromPoint) node = document.caretPositionFromPoint(e.clientX, e.clientY)?.offsetNode;
    insertPictures(files, node && editor.contains(node) ? topBlock(node) : null);
  });

  // a picture that is replaced stays the kind it was: a picture of its own, a slide, the picture beside text
  function keepKind(fig) {
    fig.classList.remove('blog-img-missing');
    if (!fig.classList.contains('blog-slide') && !fig.classList.contains('blog-mt-media')) fig.classList.add('blog-img');
  }
  function openPanel(fig) {
    if (current) current.classList.remove('is-picked');
    current = fig;
    fig.classList.add('is-picked');
    const missing = fig.classList.contains('blog-img-missing');
    const img = fig.querySelector('img');
    panel.querySelector('.bs-fp-missing').hidden = !missing;
    panel.querySelector('.bs-fp-missing b').textContent = fig.dataset.file || '';
    panel.querySelector('[data-k=alt]').value = missing ? (fig.dataset.alt || '') : (img ? img.alt : '');
    panel.querySelector('[data-k=cap]').value = fig.querySelector('figcaption')?.textContent || '';
    panel.querySelector('[data-fp=replace] span').textContent = missing ? 'Upload ' + (fig.dataset.file || 'picture') : 'Replace picture';
    const r = rectIn(fig);
    show(panel, r.bottom + 8, Math.max(0, r.left + 12));
    panel.style.right = 'auto';
  }
  function closePanel() {
    panel.hidden = true;
    if (current) current.classList.remove('is-picked');
    current = null;
    setActive(picked && editor.contains(picked) ? picked : caretBlock());
  }
  panel.addEventListener('input', e => {
    if (!current) return;
    const k = e.target.dataset.k;
    if (k === 'alt') {
      if (current.classList.contains('blog-img-missing')) current.dataset.alt = e.target.value;
      else if (current.querySelector('img')) current.querySelector('img').alt = e.target.value;
    } else if (k === 'cap') {
      let cap = current.querySelector('figcaption');
      if (!e.target.value.trim()) { if (cap) cap.remove(); }
      else { if (!cap) { cap = document.createElement('figcaption'); current.appendChild(cap); } cap.textContent = e.target.value; }
    }
    changed();
  });
  panel.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === 'Escape') { e.preventDefault(); closePanel(); } });
  panel.addEventListener('click', e => {
    const b = e.target.closest('[data-fp]');
    if (!b || !current) return;
    if (b.dataset.fp === 'replace') pick('body', current);
    else if (b.dataset.fp === 'library') openLib({ purpose: 'body', figure: current });
    else if (b.dataset.fp === 'remove') { const f = current; closePanel(); structural(() => f.remove()); setActive(null); }
    else closePanel();
  });

  // ---------------------------------------------------------------- cover
  const coverInput = form.querySelector('input[name=cover_image_url]');
  const coverBox = document.getElementById('bsCover');
  function setCover(url, src) {
    coverInput.value = url || '';
    const img = coverBox.querySelector('img');
    img.hidden = !url;
    if (url) img.src = src || url; else img.removeAttribute('src');
    coverBox.querySelector('p').hidden = !!url;
    form.querySelector('[data-cover=remove]').hidden = !url;
    form.querySelector('[data-cover=upload]').lastChild.textContent = url ? ' Replace' : ' Upload';
    changed();
    seo();
  }
  async function coverUpload(file) {
    coverBox.classList.add('is-busy');
    try { const d = await upload(file, 'cover'); setCover(d.url, d.src); } catch (err) { toast(err.message, 'danger'); }
    coverBox.classList.remove('is-busy');
  }
  form.querySelectorAll('[data-cover]').forEach(b => b.addEventListener('click', () => {
    if (b.dataset.cover === 'upload') pick('cover', null);
    else if (b.dataset.cover === 'library') openLib({ purpose: 'cover' });
    else setCover('', '');
  }));
  coverBox.addEventListener('click', () => pick('cover', null));
  coverBox.addEventListener('dragover', e => { e.preventDefault(); coverBox.classList.add('is-drop'); });
  coverBox.addEventListener('dragleave', () => coverBox.classList.remove('is-drop'));
  coverBox.addEventListener('drop', e => {
    e.preventDefault();
    coverBox.classList.remove('is-drop');
    const f = e.dataTransfer.files && e.dataTransfer.files[0];
    if (f) coverUpload(f);
  });

  // ---------------------------------------------------------------- thumbnail (the blog's list; empty: the cover)
  const thumbInput = form.querySelector('input[name=thumb_url]');
  const thumbBox = document.getElementById('bsThumb');
  function setThumb(url, src) {
    if (!thumbBox) return;
    thumbInput.value = url || '';
    const img = thumbBox.querySelector('img');
    img.hidden = !url;
    if (url) img.src = src || url; else img.removeAttribute('src');
    thumbBox.querySelector('p').hidden = !!url;
    form.querySelector('[data-thumb=remove]').hidden = !url;
    form.querySelector('[data-thumb=upload]').lastChild.textContent = url ? ' Replace' : ' Upload';
    changed();
  }
  async function thumbUpload(file) {
    thumbBox.classList.add('is-busy');
    try { const d = await upload(file, 'thumb'); setThumb(d.url, d.src); } catch (err) { toast(err.message, 'danger'); }
    thumbBox.classList.remove('is-busy');
  }
  if (thumbBox) {
    form.querySelectorAll('[data-thumb]').forEach(b => b.addEventListener('click', () => {
      if (b.dataset.thumb === 'upload') pick('thumb', null);
      else if (b.dataset.thumb === 'library') openLib({ purpose: 'thumb' });
      else setThumb('', '');
    }));
    thumbBox.addEventListener('click', () => pick('thumb', null));
    thumbBox.addEventListener('dragover', e => { e.preventDefault(); thumbBox.classList.add('is-drop'); });
    thumbBox.addEventListener('dragleave', () => thumbBox.classList.remove('is-drop'));
    thumbBox.addEventListener('drop', e => {
      e.preventDefault();
      thumbBox.classList.remove('is-drop');
      const f = e.dataTransfer.files && e.dataTransfer.files[0];
      if (f) thumbUpload(f);
    });
  }

  // ---------------------------------------------------------------- the other fields
  // the title is one line of text that wraps: as tall as it needs; Enter goes on to the post
  const fit = () => { title.style.height = 'auto'; title.style.height = title.scrollHeight + 'px'; };
  const slugOf = t => (t || '').toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 80);
  title.addEventListener('input', () => {
    if (/\n/.test(title.value)) title.value = title.value.replace(/\s*\n\s*/g, ' ');   // a pasted line break
    fit();
    if (slugAuto && slugAuto.value === '1') slug.value = slugOf(title.value);
  });
  title.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); caretIn(editor.firstElementChild); } });
  fit();
  summary.addEventListener('input', () => { document.getElementById('bsSumCount').textContent = summary.value.trim().length; });
  slug.addEventListener('input', () => { if (slugAuto) slugAuto.value = slug.value.trim() ? '0' : '1'; });
  slug.addEventListener('change', () => {
    slug.value = slugOf(slug.value);
    if (slugAuto && !slug.value) { slugAuto.value = '1'; slug.value = slugOf(title.value); }
  });
  // every setting marks the post changed -- not the editor (it has its own), its panels, or the boxes that
  // only add something (a new category's name, a tag being typed, the library's search)
  ['input', 'change'].forEach(ev => form.addEventListener(ev, e => {
    const t = e.target;
    if (!t.matches || !t.matches('input, textarea, select') || t === hidden || t.hasAttribute('data-nodirty')) return;
    if (editor.contains(t) || pop.contains(t) || panel.contains(t) || menu.contains(t) || (lib && lib.contains(t))) return;
    changed();
    if (ev === 'input') seo();
  }));

  // ---------------------------------------------------------------- checks, from the server; the outline
  const ICON = { error: 'fa-circle-xmark', warn: 'fa-lightbulb', ok: 'fa-circle-check' };
  let timer = null, seq = 0;
  function scheduleCheck() { clearTimeout(timer); timer = setTimeout(check, 700); }
  async function check() {
    serialise();
    outline();
    const mine = ++seq;
    let d;
    try {
      const r = await fetch(form.dataset.checkUrl, { method: 'POST', headers: { 'X-CSRFToken': CSRF }, body: new FormData(form), credentials: 'same-origin' });
      if (!r.ok) return;
      d = await r.json();
    } catch (err) { return; }
    if (mine !== seq) return;            // an older answer arriving late
    const box = document.getElementById('bsChecks');
    box.innerHTML = '';
    d.checks.forEach(c => {
      const li = document.createElement('li');
      li.className = 'bs-c-' + c.level;
      li.innerHTML = '<i class="fa-solid ' + ICON[c.level] + '"></i> ';
      li.appendChild(document.createTextNode(c.text));
      box.appendChild(li);
    });
    const red = d.checks.filter(c => c.level === 'error').length;
    document.getElementById('bsBlocked').hidden = !red;
    const badge = document.getElementById('geRed');
    if (badge) { badge.textContent = red; badge.hidden = !red; }
    if (slugAuto && slugAuto.value === '1' && d.slug && document.activeElement !== slug) slug.value = d.slug;
    count(d.words);
  }
  function count(words) {
    if (words == null) words = (editor.innerText.trim().match(/\S+/g) || []).length;
    document.getElementById('bsCount').textContent = words + ' word' + (words === 1 ? '' : 's') + ' · ' + Math.max(1, Math.round(words / 200)) + ' min read';
  }
  function outline() {
    const box = document.getElementById('bsOutline');
    if (!box) { blockList(); return; }          // the structure on the left is the outline now ("Headings")
    const heads = Array.from(editor.querySelectorAll('h2, h3')).filter(h => h.textContent.trim());
    box.innerHTML = '';
    heads.forEach(h => {
      const li = document.createElement('li');
      li.className = 'is-' + h.tagName.toLowerCase();
      const a = document.createElement('a');
      a.href = '#';
      a.textContent = h.textContent.trim();
      a.addEventListener('click', e => { e.preventDefault(); h.scrollIntoView({ block: 'center', behavior: 'smooth' }); caretIn(h, true); });
      li.appendChild(a);
      box.appendChild(li);
    });
    document.getElementById('bsOutlineNone').hidden = heads.length > 0;
    blockList();
  }

  // ---------------------------------------------------------------- kept in this browser until saved
  let keepT = null;
  function state() {
    serialise();
    const val = n => { const i = form.querySelector('[name=' + n + ']'); return i ? i.value : ''; };
    return { title: title.value, slug: slug.value, summary: summary.value, content: hidden.value,
             cover: coverInput.value, coverSrc: coverBox.querySelector('img').getAttribute('src') || '',
             thumb: thumbInput ? thumbInput.value : '', thumbSrc: thumbBox ? thumbBox.querySelector('img').getAttribute('src') || '' : '',
             coverAlt: form.querySelector('[name=cover_alt]').value,
             seoTitle: val('seo_title'), keyword: val('focus_keyword'), tags: val('tags'), when: val('publish_at'),
             cats: Array.from(form.querySelectorAll('[name=categories]:checked')).map(i => i.value) };
  }
  // a state() put back: after a crash, or "Undo" after a Word document was brought in
  function putBack(s) {
    title.value = s.title; fit();
    slug.value = s.slug;
    summary.value = s.summary;
    document.getElementById('bsSumCount').textContent = summary.value.trim().length;
    form.querySelector('[name=cover_alt]').value = s.coverAlt;
    const set = (n, v) => { const i = form.querySelector('[name=' + n + ']'); if (i && v != null) i.value = v; };
    set('seo_title', s.seoTitle); set('focus_keyword', s.keyword); set('publish_at', s.when);
    if (s.tags != null) { tagList = splitTags(s.tags); drawTags(); }
    if (s.cats) form.querySelectorAll('[name=categories]').forEach(i => { i.checked = s.cats.includes(i.value); });
    structural(() => { editor.innerHTML = s.content; });
    setCover(s.cover, s.coverSrc);
    if (s.thumb !== undefined) setThumb(s.thumb, s.thumbSrc);
    when();
    changed();
  }
  function backup() { try { localStorage.setItem(KEY, JSON.stringify({ base: form.dataset.saved, at: Date.now(), s: state() })); } catch (e) { /* private mode */ } }
  function dropBackup() { try { localStorage.removeItem(KEY); } catch (e) { /* ignore */ } }
  function scheduleKeep() { clearTimeout(keepT); keepT = setTimeout(backup, 1200); }

  // ---------------------------------------------------------------- saving
  form.addEventListener('submit', e => {
    const b = e.submitter;
    if (b && b.dataset.confirm && !confirm(b.dataset.confirm)) { e.preventDefault(); return; }
    document.getElementById('gePatternEdits').value = Array.from(editor.querySelectorAll('.blog-ref.is-changed')).map(r => r.dataset.ref).join(',');
    serialise();
    if (b && b.getAttribute('formtarget') === '_blank') return;      // a preview: still unsaved here
    if (!title.value.trim()) { e.preventDefault(); toast('Add a title first.', 'danger'); title.focus(); return; }
    dirty = false;
    clearTimeout(keepT);
    dropBackup();
  });
  window.addEventListener('beforeunload', e => { if (dirty) { e.preventDefault(); e.returnValue = ''; } });
  window.addEventListener('pagehide', () => { if (dirty) { clearTimeout(keepT); backup(); } });   // closed or reloaded before the timer
  // Enter in a one-line field is not "submit": the first button in the form is Preview
  form.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.matches('input[type=text], input[type=search]')) e.preventDefault(); });
  document.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
      e.preventDefault();
      (document.getElementById('bsSave') || document.getElementById('bsGoLive')).click();
    } else if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === '\\' || e.code === 'Backslash')) {
      e.preventDefault(); zen();
    } else if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === ',' || e.key === '<' || e.code === 'Comma')) {
      e.preventDefault(); side();
    } else if (e.key === 'Escape') {
      closePop(); closeMenu(); if (!panel.hidden) closePanel();
      more(false); prepub(false); lvMenuClose();
    }
  });

  // ---------------------------------------------------------------- the page around the post
  const body = document.body;
  const drawer = document.getElementById('geDrawer');
  const sideEl = document.getElementById('geSide');
  const store = (k, v) => { try { if (v == null) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } return null; };
  function side(on) {
    if (on == null) on = body.classList.contains('ge-noside');
    body.classList.toggle('ge-noside', !on);
    document.querySelectorAll('[data-ge=side].ge-ib').forEach(b => b.setAttribute('aria-pressed', on ? 'true' : 'false'));
    if (window.innerWidth > 900) store('ge.side', on ? '1' : '0');
  }
  function zen(on) {
    if (on == null) on = !body.classList.contains('ge-zen');
    body.classList.toggle('ge-zen', on);
    store('ge.zen', on ? '1' : '0');
    if (on) toast('Distraction free: Ctrl+Shift+\\ (or the ⋮ menu) brings the bars back.', 'info');
  }
  function listView(on) {
    if (on == null) on = drawer.hidden;
    if (on && ins && !ins.hidden) inserter(false);            // one panel on the left at a time
    drawer.hidden = !on;
    document.getElementById('geListBtn').setAttribute('aria-pressed', on ? 'true' : 'false');
    if (window.innerWidth > 900) store('ge.list', on ? '1' : '0');
    if (on) blockList(); else lvMenuClose();
  }
  function more(on) {
    const m = document.getElementById('geMore');
    if (on == null) on = m.hidden;
    m.hidden = !on;
    document.querySelector('[data-ge=more]').setAttribute('aria-expanded', on ? 'true' : 'false');
  }
  // the Block tab: the settings of the block picked (blog-blocks.js draws them) -- space, padding, background,
  // width, alignment, and what each kind of block has of its own
  function blockSettings(b) {
    if (!b || !editor.contains(b)) return;
    picked = b;
    tab('block');
  }
  function tab(which) {
    side(true);
    sideEl.querySelectorAll('[data-stab]').forEach(b => b.setAttribute('aria-selected', b.dataset.stab === which ? 'true' : 'false'));
    sideEl.querySelectorAll('[data-spane]').forEach(p => { p.hidden = p.dataset.spane !== which; });
    if (which === 'seo') seo();
    if (which === 'block' && BB()) BB().pane(picked && editor.contains(picked) ? picked : active);
  }
  sideEl.addEventListener('click', e => { const b = e.target.closest('[data-stab]'); if (b) tab(b.dataset.stab); });

  // the list view, on the left: every block of the post in order, the one the caret is in marked. A click goes
  // to a block; the boxes, Ctrl+click and Shift+click pick several; ⋮ or a right-click opens what can be done
  // to them (the bar at the top does the same to the picked ones); a row drags to move its blocks.
  const ICONS = { P: 'fa-paragraph', H2: 'fa-heading', H3: 'fa-heading', UL: 'fa-list-ul', OL: 'fa-list-ol', BLOCKQUOTE: 'fa-quote-left',
                  ASIDE: 'fa-lightbulb', FIGURE: 'fa-image', TABLE: 'fa-table', HR: 'fa-minus' };
  const lvList = document.getElementById('geBlocks');
  const lvMenu = document.getElementById('geLvMenu');
  let lvRows = [], lvSel = new Set(), lvAnchor = null, lvFocus = 0, lvDrag = null, lvMenuFor = null;
  const lvPicked = () => inOrder(Array.from(lvSel));
  const iconOf = b => (BB() && BB().icon(b)) || (isCta(b) ? 'fa-hand-pointer' : (ICONS[b.tagName] || 'fa-square'));
  // the colour family of a block in the structure: words, headings, pictures, video, layout, code, buttons
  function familyOf(b) {
    const k = BB() ? BB().kindOf(b) : null;
    if (/^H[23]$/.test(b.tagName)) return 'head';
    if (k === 'embed' || k === 'video') return 'video';
    if (k === 'code') return 'code';
    if (k === 'ref') return 'reuse';
    if (k === 'cols' || k === 'mt' || k === 'carousel' || k === 'slider' || k === 'spacer') return 'layout';
    if (b.tagName === 'FIGURE') return 'media';
    if (isCta(b)) return 'button';
    return 'text';
  }
  let stMode = 'all';
  const stFolded = new Set();                      // the headings (H2) whose sections are folded
  function blockList() {
    if (!lvList || drawer.hidden || lvDrag) return;
    const had = lvList.contains(document.activeElement) && document.activeElement !== lvList ? lvFocus : null;
    lvRows = Array.from(editor.children).filter(b => !trailing(b));
    lvSel = new Set(Array.from(lvSel).filter(b => lvRows.includes(b)));
    Array.from(stFolded).forEach(h => { if (!lvRows.includes(h)) stFolded.delete(h); });
    lvList.innerHTML = '';
    let h2 = null, h3 = null, n2 = 0, n3 = 0;
    const words = t => (t.match(/\S+/g) || []).length;
    const count = { blocks: lvRows.length, heads: 0, media: 0 };
    lvRows.forEach((b, i) => {
      const own = BB() ? BB().text(b) : null;
      const text = own != null ? own : b.tagName === 'FIGURE' ? (b.querySelector('img') ? b.querySelector('img').alt || 'no description' : 'missing: ' + (b.dataset.file || ''))
        : b.tagName === 'HR' ? '— a line across —' : isEmpty(b) ? 'empty line' : b.textContent.trim();
      let depth = 0, number = '';
      if (b.tagName === 'H2') { h2 = b; h3 = null; n2 += 1; n3 = 0; number = String(n2); count.heads += 1; }
      else if (b.tagName === 'H3') { h3 = b; depth = h2 ? 1 : 0; n3 += 1; number = h2 ? n2 + '.' + n3 : String(n3); count.heads += 1; }
      else depth = (h2 ? 1 : 0) + (h3 ? 1 : 0);
      const fam = familyOf(b);
      if (fam === 'media' || fam === 'video') count.media += 1;
      const on = lvSel.has(b);
      const li = document.createElement('li');
      li.className = 'ge-lv is-' + b.tagName.toLowerCase() + ' f-' + fam + ' d' + depth + (on ? ' is-sel' : '') + (b === active ? ' is-here' : '') + (isEmpty(b) ? ' is-empty' : '');
      li.dataset.i = i;
      if (b.tagName !== 'H2' && h2) li.dataset.sec = lvRows.indexOf(h2);
      li.tabIndex = -1;
      li.draggable = true;
      li.setAttribute('role', 'option');
      li.setAttribute('aria-selected', on ? 'true' : 'false');
      const ic = iconOf(b);
      li.innerHTML = '<input type="checkbox" data-nodirty tabindex="-1" aria-label="Pick this block"' + (on ? ' checked' : '') + '>' +
        (b.tagName === 'H2' ? '<button type="button" class="ge-lv-fold" data-lv="fold" tabindex="-1" aria-label="Fold this section"><i class="fa-solid fa-chevron-down"></i></button>' : '<span class="ge-lv-fold-sp"></span>') +
        '<i class="ge-lv-ic ' + (ic.startsWith('fa-brands') ? ic : 'fa-solid ' + ic) + '" aria-hidden="true"></i>' +
        '<span class="ge-lv-txt"><span class="ge-lv-main"></span><small></small></span>' +
        '<button type="button" class="ge-lv-opt" data-lv="menu" tabindex="-1" aria-label="What to do with this block"><i class="fa-solid fa-ellipsis-vertical"></i></button>';
      const main = li.querySelector('.ge-lv-main');
      if (number) { const no = document.createElement('em'); no.className = 'ge-lv-no'; no.textContent = number; main.append(no, ' '); }
      main.append(text.length > 70 ? text.slice(0, 70) + '…' : text || nameOf(b));
      li.querySelector('small').textContent = nameOf(b) + (/^(P|BLOCKQUOTE|ASIDE|UL|OL)$/.test(b.tagName) ? ' · ' + plural(words(b.textContent), 'word') : '');
      lvList.appendChild(li);
    });
    // a heading says how many blocks its section has
    Array.from(lvList.children).forEach(li => {
      if (!li.classList.contains('is-h2')) return;
      const n = lvList.querySelectorAll('[data-sec="' + li.dataset.i + '"]').length;
      li.querySelector('small').textContent = 'Heading · ' + plural(n, 'block');
      li.classList.toggle('is-folded', stFolded.has(lvRows[+li.dataset.i]));
    });
    if (!lvRows.length) lvList.innerHTML = '<li class="ge-dim ge-lv-none">The post is empty: start writing on the right.</li>';
    const total = (editor.innerText.trim().match(/\S+/g) || []).length;
    const stats = document.getElementById('geStStats');
    if (stats) stats.innerHTML = '<span><b>' + total + '</b> words</span><span><b>' + Math.max(1, Math.round(total / 200)) + '</b> min read</span>' +
      '<span><b>' + count.blocks + '</b> blocks</span><span><b>' + count.heads + '</b> headings</span><span><b>' + count.media + '</b> media</span>';
    stFilter();
    lvBar();
    if (had != null) lvFocusRow(had);
  }
  // what the structure shows: everything or the headings only, folded sections shut, and only the blocks that have
  // the words looked for (their headings stay, to say where they are)
  function stFilter() {
    const q = (document.getElementById('geStFind')?.value || '').trim().toLowerCase();
    let shown = 0;
    Array.from(lvList.children).forEach(li => {
      if (li.dataset.i == null) return;
      const b = lvRows[+li.dataset.i];
      const head = li.classList.contains('is-h2') || li.classList.contains('is-h3');
      const sec = li.dataset.sec != null ? lvRows[+li.dataset.sec] : null;
      let show = stMode === 'all' || head;
      if (show && !head && sec && stFolded.has(sec) && !q) show = false;
      if (show && li.classList.contains('is-h3') && sec && stFolded.has(sec) && !q) show = false;
      if (show && q) show = b.textContent.toLowerCase().includes(q) || nameOf(b).toLowerCase().includes(q);
      li.hidden = !show;
      li.classList.remove('is-ctx');
      if (show) shown += 1;
    });
    if (q) Array.from(lvList.children).forEach(li => {
      if (li.hidden || li.dataset.sec == null) return;
      const h = lvList.children[+li.dataset.sec];
      if (h && h.hidden) { h.hidden = false; h.classList.add('is-ctx'); }
    });
    const none = document.getElementById('geStNone');
    if (none) none.hidden = !(q && !shown);
    drawer.classList.toggle('is-heads', stMode === 'heads');
  }
  function lvBar() {
    const n = lvSel.size, all = document.getElementById('geLvAll');
    document.getElementById('geLvCount').textContent = n ? n + ' picked' : plural(lvRows.length, 'block');
    all.checked = n > 0 && n === lvRows.length;
    all.indeterminate = n > 0 && n < lvRows.length;
    document.getElementById('geLvActs').hidden = !n;
    lvList.classList.toggle('is-picking', n > 0);
    const paste = document.getElementById('geLvPaste'), c = clip();
    paste.hidden = !c;
    if (c) paste.querySelector('span').textContent = 'Paste ' + plural(c.blocks.length, 'copied block') + (n ? ' after the picked ones' : ' at the end');
  }
  function lvPaint() {
    Array.from(lvList.children).forEach((li, i) => {
      const on = lvSel.has(lvRows[i]);
      li.classList.toggle('is-sel', on);
      li.setAttribute('aria-selected', on ? 'true' : 'false');
      const box = li.querySelector('input');
      if (box) box.checked = on;
    });
    lvBar();
  }
  function lvHere() {                              // the row of the block the caret is in
    if (!lvList || drawer.hidden) return;
    lvList.querySelectorAll('.is-here, .is-here-in').forEach(li => li.classList.remove('is-here', 'is-here-in'));
    let li = lvList.children[lvRows.indexOf(active)];
    if (li && active) {
      li.classList.add('is-here');
      if (li.hidden && li.dataset.sec != null) { li = lvList.children[+li.dataset.sec]; li.classList.add('is-here-in'); }
      if (!lvList.contains(document.activeElement)) li.scrollIntoView({ block: 'nearest' });
    }
  }
  function lvPick(i, how) {                        // how: 'only', 'toggle', or 'range' (from the last one picked)
    const b = lvRows[i];
    if (!b) return;
    if (how === 'toggle') { if (lvSel.has(b)) lvSel.delete(b); else lvSel.add(b); lvAnchor = i; }
    else if (how === 'range' && lvAnchor != null) lvSel = new Set(lvRows.slice(Math.min(lvAnchor, i), Math.max(lvAnchor, i) + 1));
    else { lvSel = new Set([b]); lvAnchor = i; }
    lvFocus = i;
    lvPaint();
  }
  function lvStep(i, by) {                         // the next row that shows (a folded section or a find hides some)
    const seen = Array.from(lvList.children).filter(li => li.dataset.i != null && !li.hidden).map(li => +li.dataset.i);
    if (!seen.length) return i;
    if (by === 'first') return seen[0];
    if (by === 'last') return seen[seen.length - 1];
    const next = by > 0 ? seen.find(x => x > i) : seen.slice().reverse().find(x => x < i);
    return next == null ? i : next;
  }
  function lvFocusRow(x) {                         // a row, by its number or its block
    const i = typeof x === 'number' ? x : lvRows.indexOf(x);
    const li = lvList.children[Math.max(0, Math.min(i, lvRows.length - 1))];
    if (li && li.dataset.i != null) { lvFocus = +li.dataset.i; li.focus(); }
  }
  function goTo(b, edit) {
    b.scrollIntoView({ block: 'center', behavior: 'smooth' });
    const kind = BB() ? BB().kindOf(b) : null;
    if (isText(b) || /^(UL|OL|BLOCKQUOTE|ASIDE|TABLE)$/.test(b.tagName)) caretIn(b.querySelector('li, th, td') || b, true);
    else if (kind === 'cols' || kind === 'mt') { caretIn(b.querySelector('.blog-col p, .blog-col h3, .blog-mt-body p, .blog-mt-body h3') || b, true); if (edit) blockSettings(b); }
    else {
      picked = b;
      setActive(b);
      if (edit && kind && !/^(picture|text|button)$/.test(kind)) blockSettings(b);
      else if (edit && b.tagName === 'FIGURE') openPanel(b);
      else if (edit && isCta(b)) openButton(b, b);
    }
    b.classList.add('ge-flash');
    setTimeout(() => b.classList.remove('ge-flash'), 900);
  }
  // what an action is done to: the row it was asked on (with the others picked, when it is one of them), or the
  // picked ones, or the block the caret is in
  function lvTargets(b) {
    if (b && !lvSel.has(b)) return [b];
    const sel = lvPicked();
    return sel.length ? sel : (b ? [b] : (active && editor.contains(active) ? [active] : []));
  }
  function lvDo(what, b, e) {
    const bs = lvTargets(b);
    const keepFocus = lvList.contains(document.activeElement) || lvMenu.contains(document.activeElement);
    lvMenuClose();
    if (what === 'paste') {
      const got = pasteBlocks(b || lvPicked().pop() || null);
      if (got.length) { lvSel = new Set(got); blockList(); toast('Pasted ' + plural(got.length, 'block') + '.', 'success'); }
    } else if (!bs.length) {
      toast('Pick a block first.', 'warning');
      return;
    } else if (what === 'edit') {
      goTo(bs[0], true);
      return;
    } else if (what === 'reuse') {
      if (BB()) BB().createFrom(bs);
      return;
    } else if (what === 'copy' || what === 'cut') {
      const n = copyBlocks(bs, e);
      if (!n) { toast('Empty lines are not copied.', 'warning'); return; }
      if (what === 'cut') { removeBlocks(bs); lvSel.clear(); blockList(); } else lvBar();
      toast(plural(n, 'block') + (what === 'cut' ? ' cut' : ' copied') + ': paste ' + (n === 1 ? 'it' : 'them') + ' here or in another post.', 'success');
    } else if (what === 'duplicate') {
      const c = duplicateBlocks(bs);
      if (c.length) { lvSel = new Set(c); blockList(); }
    } else if (what === 'up' || what === 'down') {
      if (moveBlocks(bs, what === 'up' ? -1 : 1)) blockList();
      else toast(what === 'up' ? 'Already at the top.' : 'Already at the bottom.', 'info');
    } else if (what === 'before' || what === 'after') {
      const list = inOrder(bs);
      lvSel.clear();
      addLine(what === 'before' ? list[0] : list[list.length - 1], what === 'before');
      return;                                      // the caret is on the new line, ready to type
    } else if (what === 'delete') {
      removeBlocks(bs);
      lvSel.clear();
      blockList();
      toast(plural(bs.length, 'block') + ' deleted. Ctrl+Z brings ' + (bs.length === 1 ? 'it' : 'them') + ' back.', 'info');
    } else if (what.startsWith('turn:')) {
      turnInto(bs, what.slice(5));
      lvSel.clear();
      blockList();
    }
    if (keepFocus) lvFocusRow(lvSel.size ? lvPicked()[0] : lvFocus);
  }
  function lvMenuOpen(b, x, y) {
    if (!lvSel.has(b)) { lvSel = new Set([b]); lvAnchor = lvRows.indexOf(b); lvPaint(); }
    lvMenuFor = b;
    const bs = lvTargets(b), n = bs.length, c = clip();
    const first = bs[0], next = bs[n - 1].nextElementSibling;
    const kinds = bs.every(turnable) ? KINDS.filter(([k]) => !bs.every(x => kindOf(x) === k)) : [];
    const item = (what, icon, label, key, off, cls) => '<button type="button" role="menuitem" data-lv="' + what + '"' + (off ? ' disabled' : '') +
      (cls ? ' class="' + cls + '"' : '') + '><i class="fa-solid ' + icon + '"></i><span>' + esc(label) + '</span>' + (key ? '<kbd>' + key + '</kbd>' : '') + '</button>';
    lvMenu.innerHTML = '<div class="ge-lv-mh">' + esc(n > 1 ? plural(n, 'block') : nameOf(b)) + '</div>' +
      item('edit', 'fa-pen', n > 1 ? 'Go to the first' : 'Edit', 'Enter') +
      '<hr>' + item('copy', 'fa-copy', 'Copy', 'Ctrl+C') + item('cut', 'fa-scissors', 'Cut', 'Ctrl+X') +
      item('paste', 'fa-paste', c ? 'Paste ' + plural(c.blocks.length, 'block') + ' after' : 'Paste after (nothing copied)', 'Ctrl+V', !c) +
      item('duplicate', 'fa-clone', 'Duplicate', 'Ctrl+Shift+D') +
      item('reuse', 'fa-recycle', 'Create reusable block') +
      '<hr>' + item('before', 'fa-arrow-turn-up', 'Add a block before', 'Ctrl+Alt+T') + item('after', 'fa-arrow-turn-down', 'Add a block after', 'Ctrl+Alt+Y') +
      item('up', 'fa-arrow-up', 'Move up', 'Alt+Shift+↑', !first.previousElementSibling) +
      item('down', 'fa-arrow-down', 'Move down', 'Alt+Shift+↓', !next || trailing(next)) +
      (kinds.length ? '<hr><div class="ge-lv-mh">Turn into</div><div class="ge-lv-kinds">' +
        kinds.map(([k, l]) => '<button type="button" role="menuitem" data-lv="turn:' + k + '">' + esc(l) + '</button>').join('') + '</div>' : '') +
      '<hr>' + item('delete', 'fa-trash', n > 1 ? 'Delete ' + plural(n, 'block') : 'Delete', 'Del', false, 'is-bad');
    lvMenu.hidden = false;
    lvMenu.style.left = Math.max(8, Math.min(x, window.innerWidth - lvMenu.offsetWidth - 8)) + 'px';
    lvMenu.style.top = Math.max(8, Math.min(y, window.innerHeight - lvMenu.offsetHeight - 8)) + 'px';
    lvMenu.querySelector('button:not([disabled])').focus();
  }
  function lvMenuClose() { if (lvMenu && !lvMenu.hidden) { lvMenu.hidden = true; lvMenuFor = null; } }
  if (lvList) {
    lvList.addEventListener('click', e => {
      const li = e.target.closest('li[data-i]');
      if (!li) return;
      const i = +li.dataset.i, b = lvRows[i];
      if (e.target.closest('[data-lv=fold]')) { if (stFolded.has(b)) stFolded.delete(b); else stFolded.add(b); li.classList.toggle('is-folded', stFolded.has(b)); stFilter(); return; }
      if (e.target.closest('[data-lv=menu]')) { const r = e.target.closest('button').getBoundingClientRect(); lvMenuOpen(b, r.left, r.bottom + 4); return; }
      if (e.target.matches('input[type=checkbox]') || e.ctrlKey || e.metaKey) { lvPick(i, 'toggle'); return; }
      if (e.shiftKey) { lvPick(i, 'range'); return; }
      lvPick(i, 'only');
      goTo(b);
      if (window.innerWidth <= 900) listView(false);   // on a phone the list covers the post: get out of the way
    });
    lvList.addEventListener('contextmenu', e => {
      const li = e.target.closest('li[data-i]');
      if (!li) return;
      e.preventDefault();
      lvMenuOpen(lvRows[+li.dataset.i], e.clientX, e.clientY);
    });
    lvList.addEventListener('focus', e => { if (e.target === lvList && lvRows.length) lvFocusRow(lvFocus); });
    lvList.addEventListener('keydown', e => {
      const li = e.target.closest('li[data-i]');
      const i = li ? +li.dataset.i : lvFocus, b = lvRows[i];
      const mod = e.ctrlKey || e.metaKey, k = e.key, low = k.toLowerCase();
      const tgt = lvSel.size ? null : b;           // from the keys: the picked blocks, or else the row with the focus
      if (k === 'ArrowDown' || k === 'ArrowUp') {
        e.preventDefault();
        if (e.altKey && e.shiftKey) { lvDo(k === 'ArrowUp' ? 'up' : 'down', tgt); return; }
        const to = lvStep(i, k === 'ArrowDown' ? 1 : -1);
        if (e.shiftKey) { if (lvAnchor == null) lvAnchor = i; lvPick(to, 'range'); }
        lvFocusRow(to);
      } else if (k === 'Home' || k === 'End') { e.preventDefault(); lvFocusRow(lvStep(i, k === 'Home' ? 'first' : 'last')); }
      else if (k === ' ' && b) { e.preventDefault(); lvPick(i, 'toggle'); }
      else if (k === 'Enter' && b) { e.preventDefault(); lvPick(i, 'only'); goTo(b); }
      else if ((k === 'Delete' || k === 'Backspace') && b) { e.preventDefault(); lvDo('delete', tgt); }
      else if (mod && low === 'a') { e.preventDefault(); lvSel = new Set(lvRows); lvPaint(); }
      else if (mod && e.shiftKey && low === 'd') { e.preventDefault(); lvDo('duplicate', tgt); }
      else if (mod && e.altKey && (low === 't' || low === 'y')) { e.preventDefault(); lvDo(low === 't' ? 'before' : 'after', tgt); }
      else if (mod && !e.shiftKey && low === 'z') { e.preventDefault(); travel(-1); }
      else if (mod && (low === 'y' || (e.shiftKey && low === 'z'))) { e.preventDefault(); travel(1); }
      else if (k === 'Escape' && lvSel.size) { e.preventDefault(); e.stopPropagation(); lvSel.clear(); lvPaint(); }
      else if ((k === 'ContextMenu' || (e.shiftKey && k === 'F10')) && b) { e.preventDefault(); const r = li.getBoundingClientRect(); lvMenuOpen(b, r.left + 40, r.bottom); }
    });
    // rows drag: the picked blocks move together, before or after the row they are dropped on
    const dropMarks = () => lvList.querySelectorAll('.is-drop-before, .is-drop-after').forEach(li => li.classList.remove('is-drop-before', 'is-drop-after'));
    const dropSpot = e => {
      const li = e.target.closest('li[data-i]');
      if (!li) return null;
      const r = li.getBoundingClientRect();
      return { li, b: lvRows[+li.dataset.i], before: e.clientY < r.top + r.height / 2 };
    };
    lvList.addEventListener('dragstart', e => {
      const li = e.target.closest('li[data-i]');
      if (!li) return;
      const b = lvRows[+li.dataset.i];
      lvDrag = lvSel.has(b) ? lvPicked() : [b];
      dnd = { kind: 'move', blocks: lvDrag.slice() };          // the post takes them too (drag and drop, below)
      body.classList.add('ge-dragging');
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('application/x-blog-blocks', String(lvDrag.length));   // not text: the post itself takes none of it
      lvDrag.forEach(x => { const r = lvList.children[lvRows.indexOf(x)]; if (r) r.classList.add('is-dragging'); });
    });
    lvList.addEventListener('dragover', e => {
      if (!lvDrag) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      dropMarks();
      const s = dropSpot(e);
      if (s && !lvDrag.includes(s.b)) s.li.classList.add(s.before ? 'is-drop-before' : 'is-drop-after');
    });
    lvList.addEventListener('dragleave', e => { if (!lvList.contains(e.relatedTarget)) dropMarks(); });
    lvList.addEventListener('drop', e => {
      if (!lvDrag) return;
      e.preventDefault();
      const s = dropSpot(e), moving = lvDrag;
      dropMarks();
      lvDrag = null;
      if (s && !moving.includes(s.b)) {
        structural(() => {
          if (s.before) moving.forEach(x => s.b.before(x));
          else { let ref = s.b; moving.forEach(x => { ref.after(x); ref = x; }); }
        });
        lvSel = new Set(moving);
      }
      blockList();
    });
    lvList.addEventListener('dragend', () => { lvDrag = null; dropMarks(); dragDone(); blockList(); });
    document.getElementById('geLvAll').addEventListener('change', e => { lvSel = e.target.checked ? new Set(lvRows) : new Set(); lvPaint(); });
    // the structure's own tools: find, everything or headings, fold every section
    const stFind = document.getElementById('geStFind');
    if (stFind) stFind.addEventListener('input', stFilter);
    drawer.addEventListener('click', e => {
      const m = e.target.closest('[data-st-mode]');
      if (m) {
        stMode = m.dataset.stMode;
        drawer.querySelectorAll('[data-st-mode]').forEach(x => x.setAttribute('aria-pressed', x === m ? 'true' : 'false'));
        stFilter();
        return;
      }
      if (e.target.closest('[data-st-fold]')) {
        const heads = lvRows.filter(x => x.tagName === 'H2');
        const fold = heads.some(h => !stFolded.has(h));
        heads.forEach(h => (fold ? stFolded.add(h) : stFolded.delete(h)));
        drawer.querySelector('[data-st-fold] i').className = 'fa-solid ' + (fold ? 'fa-angles-down' : 'fa-angles-up');
        blockList();
      }
    });
    drawer.addEventListener('click', e => { const b = e.target.closest('.ge-lv-bar [data-lv], #geLvPaste'); if (b) lvDo(b.dataset.lv, null); });
    lvMenu.addEventListener('mousedown', e => e.preventDefault());       // the post keeps its caret
    lvMenu.addEventListener('click', e => { const b = e.target.closest('[data-lv]'); if (b && !b.disabled) lvDo(b.dataset.lv, lvMenuFor); });
    lvMenu.addEventListener('keydown', e => {
      const items = Array.from(lvMenu.querySelectorAll('button:not([disabled])'));
      const i = items.indexOf(document.activeElement);
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); items[(i + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length].focus(); }
      else if (e.key === 'Escape' || e.key === 'Tab') { e.preventDefault(); e.stopPropagation(); const f = lvMenuFor; lvMenuClose(); lvFocusRow(f); }
    });
    document.addEventListener('mousedown', e => { if (!lvMenu.hidden && !lvMenu.contains(e.target) && !e.target.closest('[data-lv=menu]')) lvMenuClose(); });
    // Ctrl+C, X and V with the list in hand: the blocks (and their words for other programs)
    const inList = () => lvList.contains(document.activeElement);
    document.addEventListener('copy', e => { if (inList()) lvDo('copy', lvSel.size ? null : lvRows[lvFocus], e); });
    document.addEventListener('cut', e => { if (inList()) lvDo('cut', lvSel.size ? null : lvRows[lvFocus], e); });
    document.addEventListener('paste', e => {
      if (!inList()) return;
      e.preventDefault();
      const cd = e.clipboardData, html = cd ? cd.getData('text/html') : '', text = cd ? cd.getData('text/plain') : '';
      const ref = lvPicked().pop() || lvRows[lvFocus] || null;
      let got;
      if (ourClip(html) || (!html && !text)) got = pasteBlocks(ref);
      else got = insertBlocks(html ? blocky(cleanPaste(html).html) : textHtml(text), ref);
      if (got.length) { lvSel = new Set(got); blockList(); lvFocusRow(got[0]); toast('Pasted ' + plural(got.length, 'block') + '.', 'success'); }
    });
    window.addEventListener('storage', e => { if (e.key === CLIP) lvBar(); });   // copied in another tab
  }

  // publish: now, or a time to come (scheduled)
  const whenIn = form.querySelector('[name=publish_at]');
  const live = !document.getElementById('gePublish');
  function later() {
    const v = whenIn && whenIn.value;
    if (!v) return false;
    const t = new Date(v + ':00+05:30');
    return !isNaN(t) && t.getTime() > Date.now() + 30000;
  }
  function whenLabel() {
    const v = whenIn && whenIn.value;
    if (!v) return live ? 'As it is' : 'Immediately';
    const t = new Date(v + ':00+05:30');
    const shown = isNaN(t) ? v.replace('T', ' ') : t.toLocaleString(undefined, { timeZone: 'Asia/Kolkata', day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
    return (later() ? 'Scheduled · ' : '') + shown;
  }
  function when() {
    if (!whenIn) return;
    const btn = document.getElementById('geWhenBtn');
    btn.textContent = whenLabel();
    const pub = document.getElementById('gePublish');
    if (pub) pub.textContent = later() ? 'Schedule…' : 'Publish';
  }
  if (whenIn) {
    whenIn.addEventListener('change', when);
    document.getElementById('geWhen').addEventListener('click', e => {
      const b = e.target.closest('[data-when]');
      if (!b) return;
      if (b.dataset.when === 'clear') whenIn.value = whenIn.defaultValue && live ? whenIn.defaultValue : '';
      else {
        const t = new Date(Date.now() + 330 * 60000);          // India time, as the field shows it
        whenIn.value = t.toISOString().slice(0, 16);
      }
      when();
      changed();
    });
  }

  // the last look before Publish
  const pp = document.getElementById('gePrepub');
  async function prepub(open) {
    if (!pp) return;
    if (!open) { pp.hidden = true; return; }
    more(false);
    pp.hidden = false;
    const go = document.getElementById('bsGoLive');
    go.disabled = true;
    await check();
    const sched = later();
    document.getElementById('gePpTitle').textContent = sched ? 'Are you ready to schedule?' : 'Are you ready to publish?';
    go.textContent = sched ? 'Schedule' : 'Publish';
    document.getElementById('gePpWhen').textContent = whenLabel();
    const cats = Array.from(form.querySelectorAll('[name=categories]:checked')).map(i => i.parentNode.textContent.trim());
    document.getElementById('gePpCats').textContent = cats.length ? cats.join(', ') : 'None';
    document.getElementById('gePpTags').textContent = tagList.length ? tagList.join(', ') : 'None';
    document.getElementById('gePpCover').textContent = coverInput.value ? 'Set' : 'None: a stock picture is shown';
    const sm = summary.value.trim();
    document.getElementById('gePpSum').textContent = sm ? (sm.length > 70 ? sm.slice(0, 70) + '…' : sm) : 'None: the first lines are used';
    const tell = form.querySelector('[name=send_notification]');
    document.getElementById('gePpTell').textContent = !tell ? 'Already told' : tell.checked ? (sched ? 'Everybody, when it goes live' : 'Everybody') : 'Nobody';
    const red = document.querySelectorAll('#bsChecks .bs-c-error').length;
    const warn = document.querySelectorAll('#bsChecks .bs-c-warn').length;
    const r = document.getElementById('gePpRed'), w = document.getElementById('gePpWarn');
    r.hidden = !red;
    r.querySelector('span').textContent = red + ' red check' + (red === 1 ? '' : 's') + ' to fix first.';
    w.hidden = !warn || red > 0;
    w.querySelector('span').textContent = warn + ' tip' + (warn === 1 ? '' : 's') + ' to make it better: it can go live without.';
    go.disabled = red > 0;
    if (!red) go.focus();
  }

  // the Google and share previews; the address beside "Address"
  const seoIn = form.querySelector('[name=seo_title]');
  function seo() {
    if (!seoIn) return;
    const t = seoIn.value.trim() || title.value.trim() || 'Add title';
    const words = editor.innerText.replace(/\s+/g, ' ').trim();
    const desc = summary.value.trim() || words.slice(0, 155) + (words.length > 155 ? ' …' : '');
    const serp = document.getElementById('geSerp');
    serp.querySelector('.ge-serp-title').textContent = t.length > 60 ? t.slice(0, 58) + ' …' : t;
    const site = serp.querySelector('.ge-serp-site small');
    site.textContent = site.dataset.site + ' › blog › ' + (slug.value || '…');
    serp.querySelector('.ge-serp-desc').textContent = desc.length > 160 ? desc.slice(0, 158) + ' …' : desc;
    document.getElementById('geSeoCount').textContent = seoIn.value.trim().length;
    const share = document.getElementById('geShare');
    const src = coverBox.querySelector('img').getAttribute('src');
    share.querySelector('img').hidden = !src;
    if (src) share.querySelector('img').src = src;
    share.querySelector('b').textContent = t;
    share.querySelector('p').textContent = desc;
    const addr = document.getElementById('geAddr');
    if (addr) addr.querySelector('b').textContent = slug.value || '…';
  }
  [title, slug, summary].forEach(i => i.addEventListener('input', seo));

  // tags: typed, picked from the ones there are, removed with their ×
  const tagsHidden = form.querySelector('[name=tags]');
  const tagBox = document.getElementById('geTags');
  const tagIn = document.getElementById('geTagIn');
  const splitTags = v => (v || '').split(',').map(t => t.trim()).filter(Boolean);
  let tagList = splitTags(tagsHidden ? tagsHidden.value : '');
  function drawTags() {
    if (!tagBox) return;
    tagBox.querySelector('.ge-tag-list').innerHTML = tagList.map((t, i) => '<span class="ge-tag">' + esc(t) +
      '<button type="button" data-tag-x="' + i + '" aria-label="Remove ' + esc(t) + '">×</button></span>').join('');
    tagsHidden.value = tagList.join(', ');
  }
  function addTags(text) {
    let added = false;
    splitTags(text).forEach(t => {
      if (!tagList.some(x => x.toLowerCase() === t.toLowerCase())) { tagList.push(t.slice(0, 80)); added = true; }
    });
    drawTags();
    if (added) changed();
  }
  if (tagIn) {
    tagIn.setAttribute('data-nodirty', '');
    tagIn.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); addTags(tagIn.value); tagIn.value = ''; }
      else if (e.key === 'Backspace' && !tagIn.value && tagList.length) { tagList.pop(); drawTags(); changed(); }
    });
    tagIn.addEventListener('input', e => {
      if (e.inputType === 'insertReplacementText' || (!e.inputType && tagIn.value)) { addTags(tagIn.value); tagIn.value = ''; }
    });
    tagIn.addEventListener('blur', () => { if (tagIn.value.trim()) { addTags(tagIn.value); tagIn.value = ''; } });
    tagBox.addEventListener('click', e => {
      const x = e.target.closest('[data-tag-x]');
      if (x) { tagList.splice(+x.dataset.tagX, 1); drawTags(); changed(); return; }
      tagIn.focus();
    });
    drawTags();
  }

  // a new category, made without leaving the post
  const catName = document.getElementById('geCatName');
  if (catName) catName.setAttribute('data-nodirty', '');
  async function addCategory() {
    const name = catName.value.trim();
    if (!name) { catName.focus(); return; }
    const fd = new FormData();
    fd.append('name', name);
    fd.append('kind', 'category');
    let d;
    try {
      const r = await fetch(form.dataset.termUrl, { method: 'POST', headers: { 'X-CSRFToken': CSRF }, body: fd, credentials: 'same-origin' });
      d = await r.json();
      if (!r.ok) throw new Error(d.error || 'The category could not be added.');
    } catch (err) { toast(err.message, 'danger'); return; }
    const box = document.getElementById('geCats');
    let input = box.querySelector('[name=categories][value="' + d.id + '"]');
    if (!input) {
      const none = box.querySelector('.ge-cats-none');
      if (none) none.remove();
      const l = document.createElement('label');
      l.innerHTML = '<input type="checkbox" name="categories" value="' + d.id + '"/> ';
      l.appendChild(document.createTextNode(d.name));
      box.appendChild(l);
      input = l.querySelector('input');
    }
    input.checked = true;
    catName.value = '';
    document.getElementById('geCatNew').hidden = true;
    changed();
  }
  if (catName) catName.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); addCategory(); } });

  // the media library: a picture already uploaded, for the post or the cover
  const lib = document.getElementById('geLib');
  const libQ = document.getElementById('geLibQ');
  let libFor = null, libItems = [], libPick = null, libT = null;
  if (libQ) libQ.setAttribute('data-nodirty', '');
  async function loadLib(selectUrl) {
    const grid = document.getElementById('geLibGrid');
    try {
      const u = new URL(form.dataset.mediaUrl, location.href);
      if (libQ.value.trim()) u.searchParams.set('q', libQ.value.trim());
      const r = await fetch(u, { credentials: 'same-origin' });
      libItems = (await r.json()).items || [];
    } catch (err) { libItems = []; }
    grid.innerHTML = libItems.length ? libItems.map((m, i) => '<button type="button" class="ge-lib-tile" data-i="' + i + '" title="' + esc(m.name) +
      '"><img src="' + esc(m.src) + '" alt="" loading="lazy"/></button>').join('')
      : '<p class="ge-dim">' + (libQ.value.trim() ? 'No picture matches.' : 'No pictures yet: upload one.') + '</p>';
    libPick = null;
    const at = selectUrl ? libItems.findIndex(m => m.url === selectUrl) : -1;
    if (at >= 0) choose(at);
    else libFoot();
  }
  function libFoot() {
    const use = lib.querySelector('[data-ge=lib-use]');
    use.disabled = !libPick;
    document.getElementById('geLibPicked').textContent = libPick ? libPick.name + (libPick.width ? ' · ' + libPick.width + ' × ' + libPick.height : '') : 'Pick a picture.';
  }
  function choose(i) {
    libPick = libItems[i] || null;
    lib.querySelectorAll('.ge-lib-tile').forEach(t => t.classList.toggle('is-on', +t.dataset.i === i));
    libFoot();
  }
  function openLib(opts) {
    if (!lib) return;
    libFor = opts;
    keep();
    if (lib.showModal) lib.showModal(); else lib.setAttribute('open', '');
    loadLib();
  }
  function closeLib() { if (lib.close) lib.close(); else lib.removeAttribute('open'); }
  function useLib() {
    const m = libPick, f = libFor;
    if (!m || !f) return;
    closeLib();
    if (f.onPick) { f.onPick(m); return; }            // a carousel, the picture beside text (blog-blocks.js)
    if (f.purpose === 'thumb') { setThumb(m.url, m.src); return; }
    if (f.purpose === 'cover') {
      setCover(m.url, m.src);
      const alt = form.querySelector('[name=cover_alt]');
      if (!alt.value.trim() && m.alt) alt.value = m.alt;
      return;
    }
    const img = '<img src="' + esc(m.src) + '" alt="' + esc(m.alt || '') + '" data-file="' + esc(m.name) + '" loading="lazy">';
    if (f.figure && editor.contains(f.figure)) {
      const fig = f.figure, cap = fig.querySelector('figcaption');
      const alt = (fig.querySelector('img') && fig.querySelector('img').alt) || fig.dataset.alt || m.alt || '';
      structural(() => {
        keepKind(fig);
        fig.removeAttribute('data-file');
        fig.removeAttribute('data-alt');
        fig.innerHTML = '<img src="' + esc(m.src) + '" alt="' + esc(alt) + '" data-file="' + esc(m.name) + '" loading="lazy">' + (cap ? cap.outerHTML : '');
      });
      openPanel(fig);
      return;
    }
    const fig = document.createElement('figure');
    fig.className = 'blog-img';
    fig.innerHTML = img;
    structural(() => { place(fig, f.target && editor.contains(f.target) ? f.target : (savedBlock() || editor.lastElementChild)); after(fig); });
    picked = fig;
    openPanel(fig);
    setActive(fig);
    if (!m.alt) panel.querySelector('[data-k=alt]').focus();
  }
  async function libUpload(files) {
    files = files.filter(f => /\.(jpe?g|png|webp)$/i.test(f.name) || /^image\/(jpeg|png|webp)$/.test(f.type));
    if (!files.length) { toast('Use a JPG, PNG or WebP picture.', 'danger'); return; }
    document.getElementById('geLibPicked').textContent = 'Uploading ' + files.length + ' picture' + (files.length === 1 ? '' : 's') + '…';
    let last = null;
    for (const file of files) {
      try { last = (await upload(file, 'body')).url; } catch (err) { toast(err.message, 'danger'); }
    }
    libQ.value = '';
    loadLib(last);
  }
  if (lib) {
    lib.addEventListener('click', e => {
      const t = e.target.closest('.ge-lib-tile');
      if (t) choose(+t.dataset.i);
      else if (e.target === lib) closeLib();             // the dark backdrop
    });
    lib.addEventListener('dblclick', e => { if (e.target.closest('.ge-lib-tile')) useLib(); });
    libQ.addEventListener('input', () => { clearTimeout(libT); libT = setTimeout(() => loadLib(), 300); });
    libQ.addEventListener('keydown', e => { if (e.key === 'Enter') e.preventDefault(); });
  }

  // "Replace from Word": the document's title, summary, words and pictures, in the editor -- not saved
  const wordFile = document.getElementById('geWordFile');
  const wordNote = document.getElementById('geWordNote');
  let beforeWord = null;
  async function bringWord(file) {
    if (!/\.docx$/i.test(file.name)) { toast('Use a Word document (.docx): open it in Word and save it as .docx.', 'danger'); return; }
    const busy = wordNote;
    busy.hidden = false;
    busy.querySelector('span').textContent = 'Reading ' + file.name + '…';
    busy.querySelector('[data-ge=word-undo]').hidden = true;
    const fd = new FormData();
    fd.append('document', file);
    let d;
    try {
      const r = await fetch(form.dataset.wordUrl, { method: 'POST', headers: { 'X-CSRFToken': CSRF }, body: fd, credentials: 'same-origin' });
      d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.error || 'The document could not be read.');
    } catch (err) { busy.hidden = true; toast(err.message, 'danger'); return; }
    beforeWord = state();
    title.value = d.title; fit();
    if (slugAuto && slugAuto.value === '1') slug.value = slugOf(d.title);
    if (d.summary) { summary.value = d.summary; document.getElementById('bsSumCount').textContent = d.summary.length; }
    if (d.cover_alt) form.querySelector('[name=cover_alt]').value = d.cover_alt;
    structural(() => { editor.innerHTML = d.content; });
    if (d.cover) setCover(d.cover, d.cover_src);
    // what the document's Post details box says beyond that: only what it gives replaces what is here
    if (d.thumb) setThumb(d.thumb, d.thumb_src);
    const cats = (d.categories || []).map(String);
    if (cats.length) form.querySelectorAll('[name=categories]').forEach(i => { i.checked = cats.includes(i.value); });
    if (d.tags) { tagList = splitTags(d.tags); drawTags(); }
    const put = (n, v) => { const i = form.querySelector('[name=' + n + ']'); if (i && v) i.value = v; };
    put('focus_keyword', d.keyword); put('seo_title', d.seo_title);
    const missing = (d.missing || []).length;
    busy.querySelector('span').textContent = 'Brought in from ' + (d.file || file.name) + ': ' + d.words + ' words' +
      (missing ? ', ' + missing + ' picture' + (missing === 1 ? '' : 's') + ' missing (the red boxes)' : '') +
      '. Look it over, then ' + (document.getElementById('bsSave') ? 'Save draft' : 'Update') + '.' +
      ((d.notes || []).length ? ' ' + d.notes.slice(0, 3).join(' ') : '');
    busy.querySelector('[data-ge=word-undo]').hidden = false;
    changed();
    seo();
  }
  if (wordFile) wordFile.addEventListener('change', () => { const f = wordFile.files[0]; wordFile.value = ''; if (f) bringWord(f); });

  // ---------------------------------------------------------------- Add a block: the blocks, on the left
  // Every block by group, and the reusable ones (blog-blocks.js keeps their list). A click adds one after the
  // block the caret is in (or the empty line whose + was pressed); dragged into the post, it goes where the blue
  // line shows. One panel on the left at a time: this or Structure.
  const ins = document.getElementById('geIns');
  const insFind = document.getElementById('geInsFind');
  const GROUPS = [['text', 'Text'], ['media', 'Pictures and video'], ['layout', 'Layout'], ['design', 'Buttons and code']];
  let insTab = 'blocks', insTarget = null;
  function inserter(on, target) {
    if (!ins) return;
    if (on == null) on = ins.hidden;
    if (on && !drawer.hidden) { drawer.hidden = true; document.getElementById('geListBtn').setAttribute('aria-pressed', 'false'); lvMenuClose(); }
    ins.hidden = !on;
    document.getElementById('geInsBtn').setAttribute('aria-pressed', on ? 'true' : 'false');
    insTarget = on ? (target || null) : null;
    if (on) insDraw();
  }
  function insDraw() {
    const q = (insFind.value || '').trim().toLowerCase();
    const boxB = document.getElementById('geInsBlocks'), boxR = document.getElementById('geInsReuse');
    boxB.hidden = insTab !== 'blocks';
    boxR.hidden = insTab !== 'reuse';
    let shown = 0;
    if (insTab === 'blocks') {
      boxB.innerHTML = GROUPS.map(([g, label]) => {
        const got = BLOCKS.filter(b => (b.group || 'text') === g && (!q || (b.label + ' ' + b.words + ' ' + b.hint).toLowerCase().includes(q)));
        shown += got.length;
        return got.length ? '<h4 class="ge-ins-h">' + esc(label) + '</h4><div class="ge-ins-grid">' + got.map(b =>
          '<button type="button" class="ge-ins-tile" draggable="true" data-ins-key="' + b.key + '" title="' + esc(b.hint) + '">' +
          '<i class="' + (b.icon.startsWith('fa-brands') ? b.icon : 'fa-solid ' + b.icon) + (b.key === 'h3' ? ' is-small' : '') + '" aria-hidden="true"></i>' +
          '<span>' + esc(b.label) + '</span></button>').join('') + '</div>' : '';
      }).join('');
    } else {
      const list = BB() ? BB().patternList() : [];
      const got = (list || []).filter(p => !q || p.name.toLowerCase().includes(q));
      shown = got.length || (q ? 0 : 1);
      boxR.innerHTML = (list == null ? '<p class="ge-ins-msg">Loading…</p>' : got.length ? '<div class="ge-ins-pats">' + got.map(p =>
        '<button type="button" class="ge-ins-pat" draggable="true" data-ins-pat="' + p.id + '">' +
        '<i class="fa-solid ' + (p.synced ? 'fa-recycle' : 'fa-shapes') + '" aria-hidden="true"></i>' +
        '<span><b>' + esc(p.name) + '</b><small>' + (p.synced ? 'Synced · in ' + plural(p.uses, 'post') : 'Not synced: a copy to change') + '</small></span></button>').join('') + '</div>'
        : q ? '' : '<p class="ge-ins-msg">No reusable blocks yet. Pick blocks in the post, then <b>Create reusable block</b>: on the block’s bar, or ⋮ in Structure.</p>') +
        '<p class="ge-ins-msg"><a href="' + esc(form.dataset.patternsPage) + '" target="_blank" rel="noopener">Manage reusable blocks <i class="fa-solid fa-arrow-up-right-from-square" aria-hidden="true"></i></a></p>';
    }
    document.getElementById('geInsNone').hidden = shown > 0;
  }
  if (ins) {
    insFind.addEventListener('input', insDraw);
    insFind.addEventListener('keydown', e => {                // Enter: the first block found; Escape: back to the post
      if (e.key === 'Enter') { const first = ins.querySelector('.ge-ins-pane:not([hidden]) [data-ins-key], .ge-ins-pane:not([hidden]) [data-ins-pat]'); if (first) first.click(); }
      else if (e.key === 'Escape') { e.stopPropagation(); inserter(false); restore(); }
    });
    ins.addEventListener('click', e => {
      const t = e.target.closest('[data-ins-tab]');
      if (t) {
        insTab = t.dataset.insTab;
        ins.querySelectorAll('[data-ins-tab]').forEach(x => x.setAttribute('aria-pressed', x === t ? 'true' : 'false'));
        insDraw();
        if (insTab === 'reuse' && BB()) BB().patterns(true).then(insDraw);
        return;
      }
      const k = e.target.closest('[data-ins-key]'), p = e.target.closest('[data-ins-pat]');
      if (!k && !p) return;
      const target = insTarget && editor.contains(insTarget) ? insTarget : (savedBlock() || active || editor.lastElementChild);
      insTarget = null;
      if (k) insertBlock(k.dataset.insKey, target);
      else if (BB()) BB().insertPattern(+p.dataset.insPat, target);
      if (insFind.value) { insFind.value = ''; insDraw(); }    // found and added: every block again
      if (window.innerWidth <= 900) inserter(false);
    });
    ins.addEventListener('dragstart', e => {
      const k = e.target.closest('[data-ins-key]'), p = e.target.closest('[data-ins-pat]');
      if (k) dragging({ kind: 'new', key: k.dataset.insKey }, e, 'copy');
      else if (p) dragging({ kind: 'pattern', id: +p.dataset.insPat }, e, 'copy');
    });
    ins.addEventListener('dragend', dragDone);
  }

  // ---------------------------------------------------------------- drag and drop into the post
  // A block from Add a block, a reusable block, a block by the grip on its bar, rows of Structure: each drops
  // between two blocks of the post, at the blue line, as one step of undo. (Pictures from the computer: above.)
  let dnd = null;
  const dropLine = document.createElement('div');
  dropLine.className = 'ge-dropline';
  dropLine.hidden = true;
  wrap.appendChild(dropLine);
  function dragging(what, e, effect) {
    dnd = what;
    e.dataTransfer.effectAllowed = effect;
    e.dataTransfer.setData('application/x-blog-' + what.kind, '1');      // not text: the post itself takes none of it
    body.classList.add('ge-dragging');
  }
  function dragDone() {
    dnd = null;
    dropLine.hidden = true;
    body.classList.remove('ge-dragging');
    editor.querySelectorAll('.is-dragging').forEach(x => x.classList.remove('is-dragging'));
  }
  function dropSpot(y) {                           // the block the line goes above (or below the last)
    const kids = Array.from(editor.children);
    const b = kids.find(x => y < x.getBoundingClientRect().top + x.offsetHeight / 2);
    if (b) return { b, before: true };
    const last = kids[kids.length - 1];
    return last ? (trailing(last) ? { b: last, before: true } : { b: last, before: false }) : null;
  }
  wrap.addEventListener('dragover', e => {
    if (!dnd) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = dnd.kind === 'move' ? 'move' : 'copy';
    const s = dropSpot(e.clientY);
    if (!s || (dnd.kind === 'move' && dnd.blocks.includes(s.b))) { dropLine.hidden = true; return; }
    const r = rectIn(s.b), ed = rectIn(editor);
    dropLine.hidden = false;
    dropLine.style.top = Math.round(s.before ? r.top - 6 : r.bottom + 4) + 'px';
    dropLine.style.left = Math.round(ed.left) + 'px';
    dropLine.style.width = Math.round(ed.right - ed.left) + 'px';
  });
  wrap.addEventListener('dragleave', e => { if (dnd && !wrap.contains(e.relatedTarget)) dropLine.hidden = true; });
  wrap.addEventListener('drop', e => {
    if (!dnd) return;
    e.preventDefault();
    const what = dnd, s = dropSpot(e.clientY);
    dragDone();
    if (!s) return;
    if (what.kind === 'new') insertBlock(what.key, s.b, s.before);
    else if (what.kind === 'pattern') { if (BB()) BB().insertPattern(what.id, s.b, s.before); }
    else {
      const moving = inOrder(what.blocks);
      if (!moving.length || moving.includes(s.b)) return;
      structural(() => {
        if (s.before) moving.forEach(x => s.b.before(x));
        else { let ref = s.b; moving.forEach(x => { ref.after(x); ref = x; }); }
      });
      setActive(moving[0]);
      moving.forEach(x => { x.classList.add('ge-flash'); setTimeout(() => x.classList.remove('ge-flash'), 900); });
    }
  });
  const grip = bbar.querySelector('.bs-bb-grip');
  grip.addEventListener('dragstart', e => {
    if (!active || !editor.contains(active)) { e.preventDefault(); return; }
    dragging({ kind: 'move', blocks: [active] }, e, 'move');
    try { e.dataTransfer.setDragImage(active, 24, 16); } catch (err) { /* the grip's own picture, then */ }
    active.classList.add('is-dragging');
  });
  grip.addEventListener('dragend', dragDone);

  // every button of the page around the post
  document.addEventListener('click', e => {
    const b = e.target.closest('[data-ge]');
    const m = document.getElementById('geMore');
    if (m && !m.hidden && !e.target.closest('.ge-more')) more(false);
    if (!b) return;
    const what = b.dataset.ge;
    if (what === 'side') side();
    else if (what === 'list') listView();
    else if (what === 'inserter') inserter();
    else if (what === 'reuse-save') { if (BB()) BB().saveNew(); }
    else if (what === 'reuse-cancel') document.getElementById('geReuse').close();
    else if (what === 'more') more();
    else if (what === 'zen') { more(false); zen(); }
    else if (what === 'keys') { more(false); document.getElementById('geKeys').showModal(); }
    else if (what === 'keys-close') document.getElementById('geKeys').close();
    else if (what === 'prepub') prepub(true);
    else if (what === 'prepub-close') prepub(false);
    else if (what === 'when') { const w = document.getElementById('geWhen'); w.hidden = !w.hidden; b.setAttribute('aria-expanded', w.hidden ? 'false' : 'true'); if (!w.hidden) whenIn.focus(); }
    else if (what === 'cat-new') { const n = document.getElementById('geCatNew'); n.hidden = !n.hidden; if (!n.hidden) catName.focus(); }
    else if (what === 'cat-save') addCategory();
    else if (what === 'word') wordFile.click();
    else if (what === 'word-undo') { if (beforeWord) { putBack(beforeWord); beforeWord = null; } wordNote.hidden = true; }
    else if (what === 'word-hide') wordNote.hidden = true;
    else if (what === 'goto-summary') { tab('post'); const sec = document.getElementById('geSumSec'); sec.open = true; summary.focus(); }
    else if (what === 'goto-checks') { prepub(false); tab('checks'); }
    else if (what === 'lib-upload') pick('library', null);
    else if (what === 'lib-close') closeLib();
    else if (what === 'lib-use') useLib();
  });

  // ---------------------------------------------------------------- what blog-blocks.js works with
  window.BlogStudio = {
    editor, wrap, form, esc, toast, CSRF, upload, openLib, structural, changed, snap, place, after, caretIn, lines,
    lockBlocks, floating, blockList, topBlock, savedBlock, isEmpty, plural, insertBlocks, clean, inOrder,
    setActive: b => setActive(b), active: () => active, tab, blockSettings, insDraw: () => { if (ins && !ins.hidden) insDraw(); }
  };

  // ---------------------------------------------------------------- start
  if (BB()) BB().init(window.BlogStudio);
  lines();
  lockBlocks();
  snap();
  count();
  outline();
  floating();
  let kept = null;
  try { kept = JSON.parse(localStorage.getItem(KEY) || 'null'); } catch (e) { /* ignore */ }
  if (kept && kept.s && kept.base === form.dataset.saved && JSON.stringify(kept.s) !== JSON.stringify(state())) {
    const bar = document.getElementById('bsRestore');
    bar.querySelector('b').textContent = new Date(kept.at).toLocaleString();
    bar.hidden = false;
    bar.addEventListener('click', e => {
      const b = e.target.closest('[data-restore]');
      if (!b) return;
      bar.hidden = true;
      if (b.dataset.restore === 'no') { dropBackup(); return; }
      putBack(kept.s);
    });
  } else if (kept) dropBackup();
  if (!form.dataset.saved && !title.value) title.focus();
  if (form.dataset.dirty) changed();                      // an earlier version, brought back: not saved yet
  if (store('ge.zen') === '1') body.classList.add('ge-zen');
  if (window.innerWidth <= 900 || store('ge.side') === '0') side(false);
  if (window.innerWidth > 1100 && store('ge.list') !== '0') listView(true);    // the list view is open on a wide screen
  when();
  seo();
})();
