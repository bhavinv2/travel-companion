// fetchall teach overlay — injected into every page during `fetchall teach`.
//
// Turns clicks into a recipe:
//   1. click a field in one item, then the same field in another item  -> finds the list
//   2. click more fields in any item                                    -> list columns
//   3. click an item to open its details, then click fields in there    -> detail columns
//      (press the "Show more" button first when part of the details is hidden behind one)
//   4. click the control that closes the details                        -> close action
//   5. click "next page" / "load more"                                  -> pagination
//   6. save                                                              -> recipes/<site>.json
//
// State lives in sessionStorage so it survives a navigation to a detail page and back.
(() => {
  if (window.__fetchallTeach) return;

  const KEY = 'fetchall.teach.v1';
  const MAX_BOXES = 300;

  // ------------------------------------------------------------ selector helpers
  const GENERATED = /\d{3,}|^(sc|css|jss|emotion|svelte|ng|mui|chakra)-|__[A-Za-z0-9]{5,}$|_[A-Za-z0-9]{5,}$|^(active|selected|hover|focus|focused|open|hidden|visible|current|highlighted)$/i;
  const cssEsc = (s) => (window.CSS && CSS.escape) ? CSS.escape(s) : String(s).replace(/([^\w-])/g, '\\$1');
  const stableClasses = (el) => Array.from(el.classList || []).filter((c) => !GENERATED.test(c));
  const stableId = (el) => (el.id && !/\d{3,}/.test(el.id) && /^[A-Za-z_][\w-]*$/.test(el.id)) ? '#' + cssEsc(el.id) : null;
  const tagOf = (el) => el.tagName.toLowerCase();
  const levelSel = (el, classes) => tagOf(el) + (classes || stableClasses(el)).map((c) => '.' + cssEsc(c)).join('');
  const nthOfType = (el) => { let i = 1; for (let s = el.previousElementSibling; s; s = s.previousElementSibling) if (s.tagName === el.tagName) i++; return i; };
  const q = (root, sel) => { try { return root.querySelector(sel); } catch (e) { return null; } };
  const qa = (root, sel) => { try { return Array.from(root.querySelectorAll(sel)); } catch (e) { return []; } };
  const MAX_CHAIN = 4;      // how many ancestor levels a descendant selector may use
  const MAX_COMBOS = 400;

  // Ways to write one level of a selector, cheapest first. The target level tries each class on its
  // own so a state class (.selected, .traveler, .past) is only used when nothing else pins the element.
  function levelOptions(el, isTarget) {
    const id = stableId(el);
    if (id) return [{ sel: id, n: 0 }];
    const tag = tagOf(el);
    const cls = stableClasses(el);
    // One semantic class beats a bare tag ("td" works today but says nothing); a bare tag beats a pile of classes.
    const opts = [{ sel: tag, n: cls.length ? 1.5 : 0 }];
    if (isTarget) cls.forEach((c) => opts.push({ sel: tag + '.' + cssEsc(c), n: 1 }));
    else if (cls.length) opts.push({ sel: tag + '.' + cssEsc(cls[0]), n: 1 });
    if (cls.length > 1) opts.push({ sel: levelSel(el, cls), n: cls.length });
    return opts;
  }

  // Cheapest descendant selector (fewest levels, then fewest classes) whose FIRST match under root is target.
  function searchSelector(chain, root, target) {
    for (let start = chain.length - 1; start >= Math.max(0, chain.length - MAX_CHAIN); start--) {
      const levels = chain.slice(start);
      let combos = [[]];
      levels.forEach((l, i) => {
        const opts = levelOptions(l, i === levels.length - 1);
        const next = [];
        combos.forEach((c) => opts.forEach((o) => next.push(c.concat([o]))));
        combos = next.slice(0, MAX_COMBOS);
      });
      const cost = (c) => c.reduce((s, o) => s + o.n, 0);
      combos.sort((a, b) => cost(a) - cost(b));
      // Among equally cheap selectors that hit the target, the one matching fewest elements is the
      // most specific ("span.modal-start" over "span.detail-value"): it survives reordering better.
      let best = null, bestCost = 0, bestCount = 0;
      for (const combo of combos) {
        if (best !== null && cost(combo) > bestCost) break;
        const sel = combo.map((o) => o.sel).join(' ');
        if (q(root, sel) !== target) continue;
        const count = qa(root, sel).length;
        if (best === null || count < bestCount) { best = sel; bestCost = cost(combo); bestCount = count; }
        if (count === 1) break;
      }
      if (best !== null) return best;
    }
    return null;
  }

  // Selector relative to `root` (a list item or a popup). Falls back to an exact nth-of-type path.
  function relSelector(target, root) {
    if (target === root) return '';
    const chain = [];
    for (let el = target; el && el !== root; el = el.parentElement) chain.unshift(el);
    if (!chain.length || chain[0].parentElement !== root) return null;
    const found = searchSelector(chain, root, target);
    if (found !== null) return found;
    return ':scope > ' + chain.map((l) => levelSel(l) + ':nth-of-type(' + nthOfType(l) + ')').join(' > ');
  }

  // Document-level selector whose first match is `el`; anchors on the nearest stable id when there is one.
  function absSelector(el) {
    const id = stableId(el);
    if (id) return id;
    const chain = [];
    let anchor = null;
    for (let e = el; e && e !== document.documentElement; e = e.parentElement) {
      if (e !== el && stableId(e)) { anchor = e; break; }
      chain.unshift(e);
    }
    const root = anchor || document;
    const found = searchSelector(chain, root, el);
    const prefix = anchor ? stableId(anchor) + ' ' : '';
    if (found !== null) return prefix + found;
    return prefix + chain.map((l) => levelSel(l) + ':nth-of-type(' + nthOfType(l) + ')').join(' > ');
  }

  function lca(a, b) {
    const anc = new Set();
    for (let e = a; e; e = e.parentElement) anc.add(e);
    for (let e = b; e; e = e.parentElement) if (anc.has(e)) return e;
    return document.body;
  }
  function childToward(container, el) {
    let e = el;
    while (e && e.parentElement !== container) e = e.parentElement;
    return e;
  }

  // Two clicks on the same field in two items -> the repeating row selector.
  function deriveList(a, b) {
    const container = lca(a, b);
    if (container === a || container === b) return { error: 'Both clicks landed on the same item. Click the same field in a DIFFERENT item.' };
    const rowA = childToward(container, a), rowB = childToward(container, b);
    if (!rowA || !rowB || rowA.tagName !== rowB.tagName) return { error: 'Those two items are not the same kind of element. Try clicking the same field in two similar items.' };
    const tag = tagOf(rowA);
    const shared = stableClasses(rowA).filter((c) => rowB.classList.contains(c));
    const matchesIn = (cls) => qa(container, ':scope > ' + tag + cls.map((c) => '.' + cssEsc(c)).join(''));
    // A class can go if dropping it only adds siblings shaped like the clicked items: that makes it
    // either redundant (.fc-event-end) or a state class (.past, .selected) that other items lack.
    const shape = (el) => tagOf(el) + '>' + Array.from(el.children).map(tagOf).join(',');
    const rowShape = shape(rowA);
    let keep = shared.slice();
    let changed = true;
    while (changed) {
      changed = false;
      for (let i = keep.length - 1; i >= 0 && keep.length > 1; i--) {
        const trial = keep.filter((_, j) => j !== i);
        const before = new Set(matchesIn(keep));
        const extra = matchesIn(trial).filter((e) => !before.has(e));
        if (extra.every((e) => shape(e) === rowShape)) { keep = trial; changed = true; }
      }
    }
    const full = matchesIn(keep).length;
    let rowSel = tag + keep.map((c) => '.' + cssEsc(c)).join('');
    const containerSel = absSelector(container);
    if (qa(document, rowSel).length !== full) rowSel = containerSel + ' > ' + rowSel;
    const rows = qa(document, rowSel);
    if (rows.length < 2) return { error: 'Only one item matched. Try clicking a different field.' };
    return { containerSel, rowSel, rows, rowA, rowB };
  }

  function fieldSelector(a, rowA, b, rowB) {
    const sel = relSelector(a, rowA);
    if (sel !== null && (!b || q(rowB, sel) === b)) return { sel, verified: !!b };
    if (b) {
      const alt = relSelector(b, rowB);
      if (alt !== null && q(rowA, alt) === a) return { sel: alt, verified: true };
    }
    return { sel: sel === null ? '' : sel, verified: false };
  }

  function valueOf(el, attr) {
    if (!el) return '';
    if (!attr || attr === 'text') return (el.innerText || el.textContent || '').trim();
    if (attr === 'href') { const a = el.closest('a[href]') || el.querySelector('a[href]'); return a ? a.href : (el.getAttribute('href') || ''); }
    if (attr === 'src') { const img = el.tagName === 'IMG' ? el : el.querySelector('img'); return img ? (img.currentSrc || img.src) : (el.getAttribute('src') || ''); }
    return el.getAttribute(attr) || '';
  }

  function attrOptions(el) {
    const opts = [['text', 'text']];
    if (el.closest('a[href]') || el.querySelector('a[href]')) opts.push(['href', 'link (href)']);
    if (el.tagName === 'IMG' || el.querySelector('img')) opts.push(['src', 'image (src)']);
    return opts;
  }

  function suggestName(el, fallback) {
    const cls = stableClasses(el)[0] || '';
    let name = cls.split(/[-_]/).filter(Boolean).pop() || '';
    if (!name) name = { a: 'link', img: 'image', time: 'time', h1: 'title', h2: 'title', h3: 'title' }[tagOf(el)] || '';
    name = name.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
    return name || fallback;
  }

  function snapshotVisible() {
    const s = new WeakSet();
    document.querySelectorAll('*').forEach((el) => { if (el.getClientRects().length) s.add(el); });
    return s;
  }

  // ------------------------------------------------------------ state
  const fresh = () => ({
    step: 'first', startUrl: location.href,
    rowSel: null, containerSel: null, rowCount: 0,
    fields: [], detail: null, paginate: null, panel: null,
  });
  function load() { try { const raw = sessionStorage.getItem(KEY); return raw ? JSON.parse(raw) : null; } catch (e) { return null; } }
  function persist() { try { sessionStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {} }

  let state = load() || fresh();
  let firstEl = null;        // volatile: first click of the pair
  let visibleBefore = null;  // volatile: what was visible before the "open" click
  let pending = null;        // {el, sel, attrs, scope, matched, total}
  let hoverEl = null;
  let statusMsg = '';

  // Came back on a different URL while waiting for detail fields -> details are a separate page.
  if (['detail', 'expand'].includes(state.step) && state.detail && !state.detail.mode && location.href !== state.detail.openUrl) {
    state.detail.mode = 'page';
    persist();
  }

  const rows = () => (state.rowSel ? qa(document, state.rowSel) : []);
  const rowOf = (el) => rows().find((r) => r.contains(el)) || null;
  const containerEl = () => (state.detail && state.detail.container ? q(document, state.detail.container) : null);
  const allNames = () => state.fields.map((f) => f.name).concat(state.detail ? state.detail.fields.map((f) => f.name) : []);
  function uniqueName(name) {
    const taken = new Set(allNames());
    if (!taken.has(name)) return name;
    let n = 2;
    while (taken.has(name + '_' + n)) n++;
    return name + '_' + n;
  }

  // ------------------------------------------------------------ UI
  const host = document.createElement('div');
  host.id = 'fetchall-teach-host';
  host.style.cssText = 'position:fixed;inset:0;z-index:2147483647;pointer-events:none;';
  const shadow = host.attachShadow({ mode: 'open' });
  shadow.innerHTML = `
<style>
  :host { all: initial; }
  .layer { position: fixed; inset: 0; pointer-events: none; }
  .box { position: fixed; box-sizing: border-box; pointer-events: none; }
  .box.row { outline: 2px dashed rgba(15,106,106,.8); background: rgba(15,106,106,.06); }
  .box.hover { outline: 2px solid #0F6A6A; background: rgba(15,106,106,.12); }
  .box.pick { background: rgba(255,235,122,.55); outline: 2px solid #b08900; }
  .panel { position: fixed; top: 16px; right: 16px; width: 460px; max-width: calc(100vw - 32px); max-height: calc(100vh - 32px); overflow: auto;
           pointer-events: auto; background: #1B2126; color: #E4E8E3; border: 1px solid #3a444b; border-radius: 6px;
           font: 13px/1.45 "Segoe UI", system-ui, sans-serif; box-shadow: 0 8px 28px rgba(0,0,0,.35); }
  .head { display: flex; justify-content: space-between; align-items: center; padding: 10px 14px; border-bottom: 1px solid #3a444b; cursor: move; user-select: none;
          font-family: Consolas, ui-monospace, monospace; font-size: 11px; letter-spacing: .12em; text-transform: uppercase; color: #9AA5AD; }
  .head b { color: #52C7B8; }
  .body { padding: 12px 14px; display: grid; gap: 10px; }
  .step { font-size: 14px; font-weight: 600; color: #fff; }
  .status { font-size: 12px; color: #9AA5AD; min-height: 1em; }
  .status.err { color: #F28B82; }
  ul { margin: 0; padding: 0; list-style: none; display: grid; gap: 4px; }
  li { display: flex; gap: 8px; align-items: baseline; font-family: Consolas, ui-monospace, monospace; font-size: 12px; }
  li .n { color: #52C7B8; min-width: 70px; }
  li .s { color: #9AA5AD; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; }
  li .x { color: #9AA5AD; cursor: pointer; padding: 0 4px; }
  li .x:hover { color: #F28B82; }
  .preview-wrap { overflow-x: auto; max-width: 100%; padding-bottom: 2px; }
  .preview-wrap::-webkit-scrollbar { height: 8px; }
  .preview-wrap::-webkit-scrollbar-track { background: #0F1315; border-radius: 4px; }
  .preview-wrap::-webkit-scrollbar-thumb { background: #52C7B8; border-radius: 4px; }
  table.preview { border-collapse: collapse; font: 12px/1.3 Consolas, ui-monospace, monospace; }
  table.preview th, table.preview td { border: 1px solid #3a444b; padding: 3px 6px; text-align: left; white-space: nowrap;
                                       max-width: 150px; overflow: hidden; text-overflow: ellipsis; vertical-align: top; }
  table.preview th { background: #0F1315; padding: 2px 4px; }
  table.preview th .scope { display: block; font-size: 9px; letter-spacing: .1em; text-transform: uppercase; color: #52C7B8; }
  table.preview th input { width: 84px; font: 600 12px "Segoe UI", system-ui, sans-serif; padding: 2px 4px;
                           background: transparent; border: 1px solid transparent; color: #fff; }
  table.preview th input:hover, table.preview th input:focus { border-color: #52C7B8; background: #1B2126; }
  table.preview th .x { color: #9AA5AD; cursor: pointer; padding: 0 3px; }
  table.preview th .x:hover { color: #F28B82; }
  table.preview td { color: #E4E8E3; }
  table.preview td.empty { color: #9AA5AD; font-style: italic; }
  .preview-hint { font-size: 11px; color: #9AA5AD; }
  .prompt { display: none; grid-template-columns: 1fr; gap: 6px; padding: 10px; background: #0F1315; border-radius: 4px; }
  .prompt.on { display: grid; }
  .prompt label { font-size: 11px; color: #9AA5AD; text-transform: uppercase; letter-spacing: .1em; }
  .prompt .sample { font-size: 12px; color: #E4E8E3; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  input, select { font: 13px "Segoe UI", system-ui, sans-serif; padding: 6px 8px; border: 1px solid #3a444b; border-radius: 4px; background: #1B2126; color: #fff; }
  input:focus, select:focus, button:focus-visible { outline: 2px solid #52C7B8; outline-offset: 1px; }
  .row2 { display: flex; gap: 6px; }
  button { font: 600 13px "Segoe UI", system-ui, sans-serif; padding: 7px 12px; border-radius: 4px; border: 1px solid #3a444b; background: #2A3237; color: #fff; cursor: pointer; }
  button.primary { background: #0F6A6A; border-color: #0F6A6A; }
  button.primary:hover { background: #12807f; }
  button:hover { border-color: #52C7B8; }
  .actions { display: flex; gap: 6px; flex-wrap: wrap; }
  .hint { font-size: 11px; color: #9AA5AD; }
  pre { margin: 0; font: 11px/1.4 Consolas, ui-monospace, monospace; color: #9AA5AD; white-space: pre-wrap; word-break: break-all; max-height: 160px; overflow: auto; }
</style>
<div class="layer"></div>
<div class="panel" role="dialog" aria-label="fetchall teach">
  <div class="head" title="Drag me out of the way"><span><b>fetchall</b> · teach</span><span class="count"></span></div>
  <div class="body">
    <div class="step"></div>
    <div class="status"></div>
    <div class="preview-wrap"><table class="preview" hidden><thead><tr></tr></thead><tbody><tr></tr></tbody></table></div>
    <div class="preview-hint" hidden>Result preview: top row = column names (click one to rename), second row = values from the item you clicked.</div>
    <ul class="fields"></ul>
    <div class="prompt">
      <div class="sample"></div>
      <label>Column name</label>
      <input class="fname" type="text" spellcheck="false">
      <div class="row2"><select class="fattr"></select><button class="add primary">Add</button><button class="cancel">Cancel</button></div>
      <div class="hint prompt-hint"></div>
    </div>
    <div class="actions"></div>
    <pre class="summary" hidden></pre>
  </div>
</div>`;
  const $ = (s) => shadow.querySelector(s);
  const layer = $('.layer');

  // The panel can be dragged by its title bar so it never sits on top of what you need to click.
  const panel = $('.panel');
  function placePanel(pos) {
    if (!pos) return;
    const x = Math.max(0, Math.min(window.innerWidth - 120, pos.x));
    const y = Math.max(0, Math.min(window.innerHeight - 48, pos.y));
    panel.style.left = x + 'px'; panel.style.top = y + 'px'; panel.style.right = 'auto';
  }
  (() => {
    const head = $('.head');
    let drag = null;
    head.addEventListener('pointerdown', (e) => {
      const r = panel.getBoundingClientRect();
      drag = { dx: e.clientX - r.left, dy: e.clientY - r.top };
      try { head.setPointerCapture(e.pointerId); } catch (err) {}
      e.preventDefault();
    });
    head.addEventListener('pointermove', (e) => {
      if (!drag) return;
      state.panel = { x: e.clientX - drag.dx, y: e.clientY - drag.dy };
      placePanel(state.panel);
    });
    const end = () => { if (drag) { drag = null; persist(); } };
    head.addEventListener('pointerup', end);
    head.addEventListener('pointercancel', end);
  })();

  const STEP_TEXT = {
    first: 'Click a field (for example the title) in the FIRST item of the list. Clicks only select for now — nothing will open yet.',
    second: 'Now click the SAME field in a DIFFERENT item.',
    fields: 'Click other fields in any item to add them. Nothing opens yet — when you are ready for the popup, press "Next: open an item".',
    open: 'Your clicks now reach the page. Click an item to open its details — or Skip if the list already has everything you need.',
    detail: 'Click the fields you want from the details (drag this panel by its title bar if it covers them). Is some text hidden behind a "Show more"? Press that button below first. Then press Next.',
    expand: 'Click the "Show more" / expand control inside the details. This click reaches the page.',
    close: 'Click the control that closes (or collapses) the details - drag this panel away first if it covers it.',
    paginate: 'Click the control that shows more items: "Next page", "Load more", the next month… — or pick a button below.',
    save: 'Review and save the recipe.',
    done: 'Saved. You can close this window.',
  };

  function setStatus(msg, isError) { statusMsg = msg || ''; const s = $('.status'); s.textContent = statusMsg; s.className = 'status' + (isError ? ' err' : ''); }

  function button(label, cls, onClick) {
    const b = document.createElement('button');
    b.textContent = label;
    if (cls) b.className = cls;
    b.addEventListener('click', (e) => { e.preventDefault(); onClick(); });
    return b;
  }

  // ------------------------------------------------------------ result preview (header row + sample row)
  // The value a field has right now: from the first list item, or from the open details.
  function liveValue(f, scope) {
    try {
      if (scope === 'list') { const first = rows()[0]; return first ? valueOf(f.sel ? q(first, f.sel) : first, f.attr) : ''; }
      const mode = state.detail && state.detail.mode;
      const root = mode === 'popup' ? containerEl() : mode === 'inline' ? rows()[0] : mode === 'page' ? document : null;
      return root ? valueOf(q(root, f.sel), f.attr) : '';
    } catch (e) { return ''; }
  }

  // Rename in place; a clash with another column gets a _2 suffix instead of silently merging.
  function renameField(f, raw) {
    const clean = (raw || '').trim().replace(/[^\w]+/g, '_').replace(/^_+|_+$/g, '');
    if (!clean || clean === f.name) return false;
    const taken = new Set(allNames());
    taken.delete(f.name);
    let name = clean, n = 2;
    while (taken.has(name)) name = clean + '_' + (n++);
    const old = f.name;
    f.name = name;
    persist();
    setStatus('Renamed ' + old + ' to ' + name + '.');
    return true;
  }

  function renderPreview() {
    const table = $('table.preview'), hint = $('.preview-hint');
    const cols = state.fields.map((f, i) => ({ f, scope: 'list', i }))
      .concat(state.detail ? state.detail.fields.map((f, i) => ({ f, scope: 'detail', i })) : []);
    table.hidden = hint.hidden = !cols.length;
    const head = table.querySelector('thead tr'), body = table.querySelector('tbody tr');
    head.innerHTML = '';
    body.innerHTML = '';
    cols.forEach((col) => {
      const th = document.createElement('th');
      th.innerHTML = '<span class="scope"></span><input type="text" spellcheck="false" title="Column name — edit to rename"><span class="x" title="Remove column">✕</span>';
      th.querySelector('.scope').textContent = col.scope === 'detail' ? '↳ details' : 'list';
      const input = th.querySelector('input');
      input.value = col.f.name;
      input.addEventListener('change', () => { if (!renameField(col.f, input.value)) input.value = col.f.name; render(); });
      input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); input.blur(); }
        if (e.key === 'Escape') { input.value = col.f.name; input.blur(); }
      });
      th.querySelector('.x').addEventListener('click', () => {
        if (col.scope === 'detail') state.detail.fields.splice(col.i, 1); else state.fields.splice(col.i, 1);
        persist(); render();
      });
      head.appendChild(th);

      const td = document.createElement('td');
      const live = liveValue(col.f, col.scope);
      if (live) col.f.sample = live;        // remembered so the preview still shows it once the popup is closed
      const v = live || col.f.sample || '';
      td.textContent = v ? (v.length > 40 ? v.slice(0, 40) + '…' : v) : '(empty)';
      td.title = v || (col.scope === 'detail' ? 'Open an item to see this value' : '');
      if (!v) td.className = 'empty';
      body.appendChild(td);
    });
  }

  function render() {
    $('.step').textContent = STEP_TEXT[state.step] || '';
    $('.count').textContent = state.rowCount ? state.rowCount + ' items' : '';
    const ul = $('.fields');
    ul.innerHTML = '';
    renderPreview();
    if (state.detail && state.detail.expand) state.detail.expand.forEach((x, i) => {
      const li = document.createElement('li');
      li.innerHTML = `<span class="n"></span><span class="s"></span><span class="x" title="Remove">✕</span>`;
      li.querySelector('.n').textContent = '↳ show more';
      li.querySelector('.s').textContent = x.sel;
      li.querySelector('.x').addEventListener('click', () => { state.detail.expand.splice(i, 1); persist(); render(); });
      ul.appendChild(li);
    });

    const actions = $('.actions');
    actions.innerHTML = '';
    const restart = () => { try { sessionStorage.removeItem(KEY); } catch (e) {} location.href = state.startUrl; };
    switch (state.step) {
      case 'first':
      case 'second':
        break;
      case 'fields':
        actions.appendChild(button('Next: open an item ▸', 'primary', () => { if (!state.fields.length) { setStatus('Add at least one field first.', true); return; } state.step = 'open'; persist(); render(); }));
        actions.appendChild(button('Skip to pagination', '', () => { if (!state.fields.length) { setStatus('Add at least one field first.', true); return; } state.step = 'paginate'; persist(); render(); }));
        break;
      case 'open':
        actions.appendChild(button('Skip details', '', () => { state.detail = null; state.step = 'paginate'; persist(); render(); }));
        break;
      case 'detail':
        actions.appendChild(button('"Show more" control…', '', () => { state.step = 'expand'; persist(); setStatus(''); render(); }));
        actions.appendChild(button('Next ▸', 'primary', () => {
          if (!state.detail.fields.length) { state.detail = null; state.step = 'paginate'; persist(); if (location.href !== state.startUrl) history.back(); else render(); return; }
          if (state.detail.mode === 'page') { state.step = 'paginate'; persist(); history.back(); return; }
          state.step = 'close'; persist(); render();
        }));
        break;
      case 'expand':
        actions.appendChild(button('Cancel', '', () => { state.step = 'detail'; persist(); render(); }));
        break;
      case 'close':
        actions.appendChild(button('No close control (skip)', '', () => { state.detail.close = null; state.step = 'paginate'; persist(); render(); }));
        break;
      case 'paginate':
        actions.appendChild(button('No next button: it loads as I scroll', '', () => { state.paginate = { mode: 'scroll' }; state.step = 'save'; persist(); render(); }));
        actions.appendChild(button('Skip (single page)', '', () => { state.paginate = null; state.step = 'save'; persist(); render(); }));
        break;
      case 'save':
        actions.appendChild(button('Save recipe', 'primary', saveRecipe));
        break;
      default:
        break;
    }
    if (state.step !== 'done') actions.appendChild(button('Restart', '', restart));

    const summary = $('.summary');
    if (state.step === 'save') { summary.hidden = false; summary.textContent = JSON.stringify(buildRecipe(), null, 1); }
    else summary.hidden = true;
    draw();
  }

  function draw() {
    layer.innerHTML = '';
    const add = (el, cls) => {
      if (!el || !el.getBoundingClientRect) return;
      const r = el.getBoundingClientRect();
      if (!r.width && !r.height) return;
      const d = document.createElement('div');
      d.className = 'box ' + cls;
      d.style.cssText = 'left:' + r.left + 'px;top:' + r.top + 'px;width:' + r.width + 'px;height:' + r.height + 'px';
      layer.appendChild(d);
    };
    if (state.rowSel && ['fields', 'open', 'paginate', 'save'].includes(state.step)) rows().slice(0, MAX_BOXES).forEach((r) => add(r, 'row'));
    if (firstEl && state.step === 'second') add(firstEl, 'pick');
    const first = rows()[0];
    if (first && ['fields', 'open'].includes(state.step)) state.fields.forEach((f) => add(f.sel ? q(first, f.sel) : first, 'pick'));
    const c = containerEl();
    if (c && ['detail', 'expand', 'close'].includes(state.step)) state.detail.fields.forEach((f) => add(q(c, f.sel), 'pick'));
    if (pending && pending.el) add(pending.el, 'pick');
    if (hoverEl) add(hoverEl, 'hover');
  }

  let rafPending = false;
  const redraw = () => { if (rafPending) return; rafPending = true; requestAnimationFrame(() => { rafPending = false; draw(); }); };

  // ------------------------------------------------------------ prompt (name a field)
  function openPrompt(p, suggested) {
    pending = p;
    const box = $('.prompt');
    box.classList.add('on');
    const sample = valueOf(p.el, 'text');
    $('.sample').textContent = 'Sample: ' + (sample.length > 60 ? sample.slice(0, 60) + '…' : sample || '(empty)');
    const sel = $('.fattr');
    sel.innerHTML = '';
    p.attrs.forEach(([v, label]) => { const o = document.createElement('option'); o.value = v; o.textContent = label; sel.appendChild(o); });
    $('.prompt-hint').textContent = p.total ? ('Found in ' + p.matched + ' of ' + p.total + ' items' + (p.verified === false ? ' — check the sample' : '')) : '';
    const input = $('.fname');
    input.value = uniqueName(suggested);
    setTimeout(() => { input.focus(); input.select(); }, 0);
    draw();
  }
  function closePrompt() { pending = null; $('.prompt').classList.remove('on'); draw(); }
  function commitPrompt() {
    if (!pending) return;
    const name = uniqueName(($('.fname').value || '').trim().replace(/[^\w]+/g, '_').replace(/^_+|_+$/g, '') || 'field');
    const attr = $('.fattr').value || 'text';
    const field = { name, sel: pending.sel, attr };
    if (pending.scope === 'detail') state.detail.fields.push(field); else state.fields.push(field);
    persist();
    setStatus('Added ' + name + '.');
    closePrompt();
    render();
    const wrap = $('.preview-wrap');
    if (wrap) wrap.scrollLeft = wrap.scrollWidth;   // show the column that was just added
  }
  $('.add').addEventListener('click', (e) => { e.preventDefault(); commitPrompt(); });
  $('.cancel').addEventListener('click', (e) => { e.preventDefault(); closePrompt(); });
  $('.fname').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); commitPrompt(); } if (e.key === 'Escape') closePrompt(); });

  // ------------------------------------------------------------ click handling
  // First click after "open": work out where the details went. False (with a message) if nothing appeared.
  function detectDetailMode(target) {
    if (location.href !== state.detail.openUrl) { state.detail.mode = 'page'; persist(); return true; }
    let found = null;   // highest ancestor that was not visible before the open click
    for (let e = target; e && e !== document.body; e = e.parentElement) if (!visibleBefore || !visibleBefore.has(e)) found = e;
    const row = rowOf(target);
    if (row && (!found || row.contains(found))) {
      state.detail.mode = 'inline';   // the details expanded inside the item itself
      if (window.fetchallLog) window.fetchallLog('details expand inline inside each item');
    } else if (!found) {
      setStatus('Nothing new appeared on the page. If the details open in a new page, click a field there; otherwise this site may not be supported.', true);
      return false;
    } else {
      state.detail.mode = 'popup';
      state.detail.container = absSelector(found);
      if (window.fetchallLog) window.fetchallLog('details open in a popup: ' + state.detail.container);
    }
    persist();
    return true;
  }

  function handleClick(target) {
    switch (state.step) {
      case 'first': {
        firstEl = target;
        state.step = 'second';
        setStatus('');
        render();
        return;
      }
      case 'second': {
        if (!firstEl) { state.step = 'first'; render(); return; }
        const res = deriveList(firstEl, target);
        if (res.error) { setStatus(res.error, true); return; }
        state.rowSel = res.rowSel; state.containerSel = res.containerSel; state.rowCount = res.rows.length;
        state.step = 'fields';
        persist();
        const fs = fieldSelector(firstEl, res.rowA, target, res.rowB);
        const matched = res.rows.filter((r) => q(r, fs.sel)).length;
        setStatus('Found ' + res.rows.length + ' items (' + res.rowSel + ').');
        if (window.fetchallLog) window.fetchallLog('list: ' + res.rows.length + ' items match ' + res.rowSel);
        render();
        openPrompt({ el: firstEl, sel: fs.sel, attrs: attrOptions(firstEl), scope: 'list', matched, total: res.rows.length, verified: fs.verified }, 'title');
        firstEl = null;
        return;
      }
      case 'fields': {
        const row = rowOf(target);
        if (!row) { setStatus('That is not inside one of the items. Click within a highlighted item.', true); return; }
        const sel = relSelector(target, row);
        const all = rows();
        const matched = all.filter((r) => q(r, sel)).length;
        openPrompt({ el: target, sel, attrs: attrOptions(target), scope: 'list', matched, total: all.length }, suggestName(target, 'field_' + (state.fields.length + 1)));
        return;
      }
      case 'open': {
        const row = rowOf(target);
        if (!row) { setStatus('Click inside one of the highlighted items to open it.', true); return; }
        state.detail = { mode: null, open: { sel: relSelector(target, row) }, openUrl: location.href, container: null, fields: [], expand: [], close: null };
        state.step = 'detail';
        persist();
        visibleBefore = snapshotVisible();
        setStatus('Opening… now click the fields you want from the details.');
        render();
        return;  // click passes through to the page
      }
      case 'detail': {
        if (!state.detail.mode && !detectDetailMode(target)) return;
        let sel;
        if (state.detail.mode === 'popup') {
          const c = containerEl();
          if (!c || !c.contains(target)) { setStatus('Click inside the details popup.', true); return; }
          sel = relSelector(target, c);
        } else if (state.detail.mode === 'inline') {
          const row = rowOf(target);
          if (!row) { setStatus('Click inside the expanded item.', true); return; }
          sel = relSelector(target, row);
        } else {
          sel = absSelector(target);
        }
        openPrompt({ el: target, sel, attrs: attrOptions(target), scope: 'detail', matched: 0, total: 0 }, suggestName(target, 'detail_' + (state.detail.fields.length + 1)));
        return;
      }
      case 'expand': {
        if (!state.detail.mode && !detectDetailMode(target)) return;
        const ctl = target.closest('button, a, [role="button"]') || target;
        let x;
        if (state.detail.mode === 'popup') {
          const c = containerEl();
          if (!c || !c.contains(ctl)) { setStatus('Click a control inside the details popup.', true); return; }
          x = { sel: relSelector(ctl, c), scope: 'container' };
        } else if (state.detail.mode === 'inline') {
          const row = rowOf(ctl);
          if (!row) { setStatus('Click a control inside the expanded item.', true); return; }
          x = { sel: relSelector(ctl, row), scope: 'row' };
        } else {
          x = { sel: absSelector(ctl), scope: 'document' };
        }
        if (!state.detail.expand) state.detail.expand = [];
        state.detail.expand.push(x);
        state.step = 'detail';
        persist();
        setStatus('"Show more" control recorded: ' + x.sel + '. Now click the fields you want.');
        if (window.fetchallLog) window.fetchallLog('details: click ' + x.sel + ' before reading the fields');
        render();
        return;  // click passes through so the page expands
      }
      case 'close': {
        const c = containerEl();
        const ctl = target.closest('button, a, [role="button"]') || target;
        const row = state.detail.mode === 'inline' ? rowOf(ctl) : null;
        state.detail.close = row
          ? { sel: relSelector(ctl, row), scope: 'row' }
          : (c && c.contains(ctl))
            ? { sel: relSelector(ctl, c), scope: 'container' }
            : { sel: absSelector(ctl), scope: 'document' };
        state.step = 'paginate';
        persist();
        setStatus('Close control recorded: ' + state.detail.close.sel);
        render();
        // The click passes through. If the popup is still showing afterwards, that was not the close control.
        if (state.detail.mode === 'popup' && c) {
          setTimeout(() => {
            if (c.getClientRects().length > 0 && state.step === 'paginate') {
              state.detail.close = null;
              state.step = 'close';
              persist();
              setStatus('That click did not close the popup - it is still open. Click the control that closes it (usually the ×), or use the skip button.', true);
              render();
            }
          }, 800);
        }
        return;
      }
      case 'paginate': {
        const ctl = target.closest('button, a, [role="button"], input[type="button"], input[type="submit"]') || target;
        const before = rows();
        const firstRow = before[0] || null;
        state.paginate = { mode: 'click', click: absSelector(ctl) };
        state.step = 'save';
        persist();
        setStatus('Pagination control recorded: ' + state.paginate.click);
        render();
        // The click passes through. If the same first item is still there and the list grew, it appends.
        setTimeout(() => {
          const after = rows();
          if (firstRow && after.length > before.length && after[0] === firstRow) {
            state.paginate.mode = 'load_more';
            persist();
            setStatus('"Load more" recorded: items are appended to the same list.');
            if (window.fetchallLog) window.fetchallLog('pagination: load more (appends to the list)');
            render();
          }
        }, 1500);
        return;
      }
      default:
        return;
    }
  }

  const PASSTHROUGH = new Set(['open', 'expand', 'close', 'paginate', 'save', 'done']);
  function onPointer(e) {
    if (e.composedPath().includes(host)) return;
    if (!PASSTHROUGH.has(state.step)) { e.preventDefault(); e.stopImmediatePropagation(); }
    if (e.type !== 'click') return;
    const target = e.target && e.target.nodeType === 1 ? e.target : null;
    if (target) handleClick(target);
  }
  ['pointerdown', 'mousedown', 'mouseup', 'click'].forEach((t) => document.addEventListener(t, onPointer, true));
  document.addEventListener('mousemove', (e) => {
    if (e.composedPath().includes(host)) { if (hoverEl) { hoverEl = null; redraw(); } return; }
    const t = e.target && e.target.nodeType === 1 ? e.target : null;
    if (t !== hoverEl) { hoverEl = t; redraw(); }
  }, true);
  window.addEventListener('scroll', redraw, true);
  window.addEventListener('resize', redraw);

  // ------------------------------------------------------------ recipe
  function buildRecipe() {
    const toMap = (list) => { const m = {}; list.forEach((f) => { m[f.name] = { sel: f.sel, attr: f.attr }; }); return m; };
    let site = location.host;
    try { site = new URL(state.startUrl).host; } catch (e) {}
    const recipe = {
      version: 1, site, start_url: state.startUrl, wait_for: state.rowSel,
      list: { row: state.rowSel, container: state.containerSel },
      fields: toMap(state.fields), detail: null, paginate: null,
    };
    if (state.detail && state.detail.fields.length) {
      const mode = state.detail.mode || 'popup';
      recipe.detail = {
        mode, open: state.detail.open, container: state.detail.container,
        fields: toMap(state.detail.fields), close: state.detail.close,
      };
      if (state.detail.expand && state.detail.expand.length) recipe.detail.expand = state.detail.expand.slice();
      if (mode === 'popup') recipe.detail.wait_for = state.detail.container;
      else if (mode === 'page') recipe.detail.wait_for = state.detail.fields[0].sel;
      else recipe.detail.wait_ms = 600;
    }
    if (state.paginate) {
      recipe.paginate = { mode: state.paginate.mode || 'click', max_pages: 50, stop_after_empty: 3 };
      if (state.paginate.click) recipe.paginate.click = state.paginate.click;
    }
    return recipe;
  }

  async function saveRecipe() {
    const recipe = buildRecipe();
    if (!window.fetchallSave) { setStatus('Not connected to fetchall (open this page with `fetchall teach`).', true); return; }
    try {
      await window.fetchallSave(JSON.stringify(recipe));
      state.step = 'done';
      try { sessionStorage.removeItem(KEY); } catch (e) {}
      render();
    } catch (e) {
      setStatus('Save failed: ' + e, true);
    }
  }

  window.__fetchallTeach = { getState: () => state, buildRecipe, reset: () => { state = fresh(); persist(); render(); } };

  function mount() {
    (document.documentElement || document.body).appendChild(host);
    placePanel(state.panel);
    render();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount); else mount();
})();
