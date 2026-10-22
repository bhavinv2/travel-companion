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
   save. Work that is not saved yet is kept in this browser and offered back after a crash. */
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
    editor.querySelectorAll('figure, p.blog-cta-wrap').forEach(f => f.setAttribute('contenteditable', 'false'));
  }
  // there is always a line to type on: at the start of an empty post, and after a picture, a table ...
  function lines() {
    if (!editor.firstElementChild) editor.appendChild(para());
    Array.from(editor.childNodes).forEach(n => {           // loose text the browser left at the top
      if (n.nodeType === 3 && n.textContent.trim()) { const p = document.createElement('p'); n.replaceWith(p); p.appendChild(n); }
      else if (n.nodeType === 1 && n.tagName === 'DIV') { const p = document.createElement('p'); while (n.firstChild) p.appendChild(n.firstChild); n.replaceWith(p); }
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
  function place(node, target) {
    if (target && editor.contains(target) && isEmpty(target)) target.replaceWith(node);   // the empty line becomes it
    else if (target && editor.contains(target)) target.after(node);
    else editor.appendChild(node);
  }
  function serialise() {
    const c = editor.cloneNode(true);
    c.querySelectorAll('.bs-uploading').forEach(e => e.remove());
    c.querySelectorAll('[contenteditable]').forEach(e => e.removeAttribute('contenteditable'));
    c.querySelectorAll('.is-picked, .bs-ph').forEach(e => { e.classList.remove('is-picked', 'bs-ph'); });
    c.querySelectorAll('[class=""]').forEach(e => e.removeAttribute('class'));
    hidden.value = c.innerHTML.trim();
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
  function plainHtml() {                     // without the hint and the picked outline, which come and go
    const c = editor.cloneNode(true);
    c.querySelectorAll('.bs-ph, .is-picked').forEach(e => e.classList.remove('bs-ph', 'is-picked'));
    c.querySelectorAll('[class=""]').forEach(e => e.removeAttribute('class'));
    return c.innerHTML;
  }
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
    { key: 'p', label: 'Paragraph', icon: 'fa-paragraph', hint: 'Plain text', words: 'text normal' },
    { key: 'h2', label: 'Heading', icon: 'fa-heading', hint: 'A section heading (H2)', words: 'h2 title section' },
    { key: 'h3', label: 'Sub-heading', icon: 'fa-heading', hint: 'A smaller heading inside a section (H3)', words: 'h3 subheading small' },
    { key: 'ul', label: 'Bulleted list', icon: 'fa-list-ul', hint: 'A list with dots', words: 'list bullets points ul' },
    { key: 'ol', label: 'Numbered list', icon: 'fa-list-ol', hint: 'Steps: 1, 2, 3 …', words: 'list numbers steps ol' },
    { key: 'quote', label: 'Quote', icon: 'fa-quote-left', hint: 'A large pull quote', words: 'blockquote pull' },
    { key: 'tip', label: 'Tip box', icon: 'fa-lightbulb', hint: 'A highlighted tip', words: 'note callout important' },
    { key: 'image', label: 'Picture', icon: 'fa-image', hint: 'Upload one (or drag it in, or paste it)', words: 'image photo upload' },
    { key: 'button', label: 'Button', icon: 'fa-hand-pointer', hint: 'A button to a page', words: 'cta link call to action' },
    { key: 'table', label: 'Table', icon: 'fa-table', hint: 'Rows and columns: add more from its bar', words: 'grid columns rows compare' },
    { key: 'divider', label: 'Line across', icon: 'fa-minus', hint: 'Separates two parts', words: 'divider separator hr' },
  ];
  const NAMES = { P: 'Paragraph', H2: 'Heading', H3: 'Sub-heading', UL: 'Bulleted list', OL: 'Numbered list',
                  BLOCKQUOTE: 'Quote', ASIDE: 'Tip box', FIGURE: 'Picture', TABLE: 'Table', HR: 'Line across' };

  function insertBlock(key, target) {
    target = target && editor.contains(target) ? target : (savedBlock() || editor.lastElementChild);
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
      place(node, target);
      if (!isText(node)) { const line = after(node); focus = focus || line; }   // somewhere to go on writing
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
      '" role="option"><i class="fa-solid ' + b.icon + (b.key === 'h3' ? ' is-small' : '') + '"></i><span><b>' + esc(b.label) +
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
  plus.addEventListener('click', () => { const b = caretBlock() || savedBlock(); openMenu('insert', b, b); });

  // ---------------------------------------------------------------- the bar over a block
  let typing = false;
  function setActive(b) {
    active = b && b.parentNode === editor ? b : null;
    floating();
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
    bbar.querySelector('.bs-bb-name').textContent = isCta(active) ? 'Button' : (NAMES[active.tagName] || 'Block');
    bbar.querySelector('.bs-bb-table').hidden = active.tagName !== 'TABLE';
    bbar.hidden = false;
    const r = rectIn(active);
    show(bbar, Math.max(r.top - bbar.offsetHeight - 6, -bbar.offsetHeight - 2), r.right - bbar.offsetWidth);
  }
  bbar.addEventListener('mousedown', e => e.preventDefault());
  bbar.addEventListener('click', e => {
    const b = e.target.closest('[data-bb]');
    if (!b || !active || !editor.contains(active)) return;
    const what = b.dataset.bb, blk = active;
    const s = window.getSelection();
    const spot = s.rangeCount && blk.contains(s.anchorNode) ? [s.anchorNode, s.anchorOffset] : null;
    const back = () => {                                   // the caret stays where it was in the block
      if (!spot) return;
      const r = document.createRange();
      try { r.setStart(spot[0], spot[1]); r.collapse(true); s.removeAllRanges(); s.addRange(r); } catch (err) { /* moved away */ }
    };
    const next = blk.nextElementSibling;
    if (what === 'up' && blk.previousElementSibling) structural(() => blk.previousElementSibling.before(blk));
    else if (what === 'down' && next && !(isEmpty(next) && next === editor.lastElementChild)) structural(() => next.after(blk));
    else if (what === 'copy') structural(() => { const c = blk.cloneNode(true); c.classList.remove('is-picked'); blk.after(c); });
    else if (what === 'remove') {
      const near = next || blk.previousElementSibling;
      if (blk === current) closePanel();
      structural(() => blk.remove());
      setActive(null);
      caretIn(near && editor.contains(near) ? near : editor.firstElementChild);
      return;
    } else if (/^(row|col|delrow|delcol)$/.test(what)) return tableOp(what, blk);
    else return;
    editor.focus();
    back();
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

  // ---------------------------------------------------------------- the toolbar
  const toolbar = document.getElementById('bsToolbar');
  toolbar.addEventListener('mousedown', e => { if (e.target.closest('button')) e.preventDefault(); });   // keep the selection
  toolbar.addEventListener('click', e => {
    const b = e.target.closest('button');
    if (!b) return;
    const what = b.dataset.do;
    if (what === 'menu') { const t = savedBlock() || editor.lastElementChild; openMenu('insert', t, b); return; }
    if (what === 'undo' || what === 'redo') { travel(what === 'undo' ? -1 : 1); return; }
    if (what === 'insert') { insertBlock(b.dataset.block, savedBlock()); return; }
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
    const fn = popDo.apply;
    closePop();
    fn(url, popText.value.trim());
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
      openPop({ url: a.getAttribute('href'), remove: true, anchor: a,
        apply: url => structural(() => a.setAttribute('href', url)),
        remove: () => structural(() => { a.replaceWith(...a.childNodes); }) });
    } else if (range.collapsed) {
      openPop({ text: true, anchor: anchorEl, apply: (url, text) => {
        restore();
        document.execCommand('insertHTML', false, '<a href="' + esc(url) + '">' + esc(text) + '</a>&nbsp;');
        changed();
      } });
    } else {
      openPop({ anchor: anchorEl, apply: url => { restore(); document.execCommand('createLink', false, url); changed(); } });
    }
  }
  function openButton(cta, target) {
    const a = cta && cta.querySelector('a');
    openPop({ button: true, text: true, textValue: a ? a.textContent : '', url: a ? a.getAttribute('href') : '',
      remove: !!cta, anchor: cta || target || editor.lastElementChild,
      apply: (url, text) => structural(() => {
        if (a) { a.setAttribute('href', url); a.textContent = text; return; }
        const p = document.createElement('p');
        p.className = 'blog-cta-wrap';
        p.innerHTML = '<a class="blog-cta" href="' + esc(url) + '">' + esc(text) + '</a>';
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
    const files = Array.from(cd.files || []).filter(f => /^image\/(jpeg|png|webp)$/.test(f.type));
    if (files.length) { e.preventDefault(); insertPictures(files, caretBlock()); return; }
    e.preventDefault();
    const html = cd.getData('text/html');
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
    const paras = text.replace(/\r/g, '').split(/\n{2,}/).map(p => p.trim()).filter(Boolean);
    if (paras.length <= 1) document.execCommand('insertText', false, text);
    else document.execCommand('insertHTML', false, paras.map(p => '<p>' + esc(p).replace(/\n/g, '<br>') + '</p>').join(''));
    changed();
  });

  // ---------------------------------------------------------------- typing
  editor.addEventListener('keydown', e => {
    const mod = e.ctrlKey || e.metaKey, k = e.key;
    if (!/^(Control|Shift|Alt|Meta|Escape)$/.test(k)) picked = null;
    if (mod && k.toLowerCase() === 'z') { e.preventDefault(); travel(e.shiftKey ? 1 : -1); return; }
    if (mod && k.toLowerCase() === 'y') { e.preventDefault(); travel(1); return; }
    if (mod && k.toLowerCase() === 'k') { e.preventDefault(); openLink(); return; }
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
    if (fig && editor.contains(fig)) { e.preventDefault(); closePop(); picked = fig; openPanel(fig); setActive(fig); return; }
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
    fileInput.multiple = purpose === 'body' && !figure;
    fileInput.value = '';
    fileInput.click();
  }
  fileInput.addEventListener('change', async () => {
    const files = Array.from(fileInput.files);
    if (!files.length || !picking) return;
    const { purpose, figure, target } = picking;
    picking = null;
    if (purpose === 'cover') return coverUpload(files[0]);
    if (!figure) return insertPictures(files, target);
    let d;
    try { d = await upload(files[0], 'body'); } catch (err) { toast(err.message, 'danger'); return; }
    const alt = figure.querySelector('img')?.alt || figure.dataset.alt || '';
    const cap = figure.querySelector('figcaption');
    structural(() => {
      figure.className = 'blog-img';
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
  }
  async function coverUpload(file) {
    coverBox.classList.add('is-busy');
    try { const d = await upload(file, 'cover'); setCover(d.url, d.src); } catch (err) { toast(err.message, 'danger'); }
    coverBox.classList.remove('is-busy');
  }
  form.querySelectorAll('[data-cover]').forEach(b => b.addEventListener('click', () => {
    if (b.dataset.cover === 'upload') pick('cover', null); else setCover('', '');
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
  form.querySelectorAll('input[type=text], textarea[name=summary], textarea[name=title], input[type=checkbox]').forEach(i => {
    if (!editor.contains(i) && !pop.contains(i) && !panel.contains(i) && !menu.contains(i)) i.addEventListener('input', changed);
  });

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
    document.getElementById('bsBlocked').hidden = !d.checks.some(c => c.level === 'error');
    if (slugAuto && slugAuto.value === '1' && d.slug && document.activeElement !== slug) slug.value = d.slug;
    count(d.words);
  }
  function count(words) {
    if (words == null) words = (editor.innerText.trim().match(/\S+/g) || []).length;
    document.getElementById('bsCount').textContent = words + ' word' + (words === 1 ? '' : 's') + ' · ' + Math.max(1, Math.round(words / 200)) + ' min read';
  }
  function outline() {
    const box = document.getElementById('bsOutline');
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
  }

  // ---------------------------------------------------------------- kept in this browser until saved
  let keepT = null;
  function state() {
    serialise();
    return { title: title.value, slug: slug.value, summary: summary.value, content: hidden.value,
             cover: coverInput.value, coverSrc: coverBox.querySelector('img').getAttribute('src') || '',
             coverAlt: form.querySelector('[name=cover_alt]').value };
  }
  function backup() { try { localStorage.setItem(KEY, JSON.stringify({ base: form.dataset.saved, at: Date.now(), s: state() })); } catch (e) { /* private mode */ } }
  function dropBackup() { try { localStorage.removeItem(KEY); } catch (e) { /* ignore */ } }
  function scheduleKeep() { clearTimeout(keepT); keepT = setTimeout(backup, 1200); }

  // ---------------------------------------------------------------- saving
  form.addEventListener('submit', e => {
    const b = e.submitter;
    if (b && b.dataset.confirm && !confirm(b.dataset.confirm)) { e.preventDefault(); return; }
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
  form.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.matches('input[type=text]')) e.preventDefault(); });
  document.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
      e.preventDefault();
      (document.getElementById('bsSave') || document.getElementById('bsGoLive')).click();
    } else if (e.key === 'Escape') { closePop(); closeMenu(); if (!panel.hidden) closePanel(); }
  });

  // ---------------------------------------------------------------- start
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
      const s = kept.s;
      title.value = s.title; fit();
      slug.value = s.slug;
      summary.value = s.summary;
      form.querySelector('[name=cover_alt]').value = s.coverAlt;
      editor.innerHTML = s.content;
      lines(); lockBlocks(); snap();
      setCover(s.cover, s.coverSrc);
      changed();
    });
  } else if (kept) dropBackup();
  if (!form.dataset.saved && !title.value) title.focus();
})();
