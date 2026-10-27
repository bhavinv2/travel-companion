/* The tour guide (services/tours.py, routes/favourites.py; base.html loads it on staff pages).
 *
 *   The button   the round "Tour guide" button at the bottom left opens the guide: topics down its left side (For you,
 *                Common places, More tours, Find a screen) and a search over all of them. Each tour and each screen
 *                can be started from there.
 *   The question ten seconds after somebody lands in the console (data-after; counted from the first staff page of
 *                this browser tab, so moving between pages does not start the count again) the guide asks once
 *                whether to show them round, when the server says to ask (data-ask). The answer goes back to the
 *                server: "Not now" asks again at the next sign-in, "Don't ask again" never.
 *   A tour       a spotlight on one part of the screen and a card with a few words, Back / Next. A step on another
 *                screen opens that screen and carries on there (the tour in progress is kept in sessionStorage).
 *                A part that is not on the screen (a phone has no rail) shows its words in the middle instead.
 *                Escape ends it; the arrow keys move through it. A finished tour is marked done on the server.
 *
 * Nothing a tour does changes anything: it opens screens and points. Text from the server goes in with
 * textContent, never as HTML. */
(function () {
  const me = document.currentScript;
  const btn = document.getElementById('tgBtn');
  const panel = document.getElementById('tgPanel');
  if (!me || !btn || !panel) return;
  const API = me.dataset.api, ANSWER = me.dataset.answer, DONE = me.dataset.done;
  const ASK = me.dataset.ask === '1';
  const AFTER = (parseInt(me.dataset.after, 10) || 10) * 1000;
  const CSRF = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
  const RUN = 'tg-run', LANDED = 'tg-landed', FRESH = 15 * 60 * 1000;
  let data = null, cur = null, dir = 1, topic = null;

  // ------------------------------------------------------------------------------------------------ small helpers
  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function icon(name) {
    const i = el('i', (name.indexOf(' ') === -1 ? 'fa-solid ' : '') + name);
    i.setAttribute('aria-hidden', 'true');
    return i;
  }
  function store(key, value) {
    try {
      if (value == null) sessionStorage.removeItem(key);
      else sessionStorage.setItem(key, typeof value === 'string' ? value : JSON.stringify(value));
    } catch (e) { /* a private window: the tour simply does not carry over */ }
  }
  function read(key) {
    try { return sessionStorage.getItem(key); } catch (e) { return null; }
  }
  function load() {
    if (data) return Promise.resolve(data);
    return fetch(API, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { data = d; return d; });
  }
  function post(url, body) {
    return fetch(url, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF, Accept: 'application/json' },
      body: JSON.stringify(body),
    }).catch(function () { /* nothing to undo */ });
  }

  // ------------------------------------------------------------------------------------------------ the guide
  const TOPICS = [
    { key: 'you', label: 'For you', icon: 'fa-user-check' },
    { key: 'common', label: 'Common places', icon: 'fa-compass' },
    { key: 'more', label: 'More tours', icon: 'fa-layer-group' },
    { key: 'screens', label: 'Find a screen', icon: 'fa-magnifying-glass-location' },
  ];
  let list, find, topicsNav, askBox;

  function buildPanel() {
    panel.textContent = '';
    const top = el('div', 'tg-top');
    const h = el('h2', 'tg-title');
    h.id = 'tgTitle';
    h.append(icon('fa-route'), document.createTextNode(' Tour guide'));
    const x = el('button', 'tg-x');
    x.type = 'button';
    x.setAttribute('aria-label', 'Close the tour guide');
    x.append(icon('fa-xmark'));
    x.addEventListener('click', function () { openPanel(false); });
    top.append(h, x);
    panel.setAttribute('aria-labelledby', 'tgTitle');

    const hello = el('p', 'tg-hello', data.profile
      ? 'Tours made for your role, ' + data.profile + ', the places every screen shares, and every screen you can open.'
      : 'Tours of the places every screen shares, and every screen you can open, with what it does.');

    const label = el('label', 'tg-find');
    label.append(icon('fa-magnifying-glass'));
    find = el('input');
    find.type = 'search';
    find.placeholder = 'Find a screen or a tour…';
    find.setAttribute('aria-label', 'Find a screen or a tour');
    find.autocomplete = 'off';
    find.addEventListener('input', draw);
    label.append(find);

    const body = el('div', 'tg-body');
    topicsNav = el('nav', 'tg-topics');
    topicsNav.setAttribute('aria-label', 'Topics');
    TOPICS.forEach(function (t) {
      if (t.key !== 'screens' && !data.tours.some(function (x) { return x.group === t.key; })) return;
      if (t.key === 'screens' && !data.screens.length) return;
      const b = el('button', 'tg-topic');
      b.type = 'button';
      b.dataset.topic = t.key;
      b.append(icon(t.icon), el('span', '', t.label));
      b.addEventListener('click', function () {
        topic = t.key;
        find.value = '';
        draw();
      });
      topicsNav.append(b);
    });
    list = el('div', 'tg-list');
    list.setAttribute('aria-live', 'polite');
    body.append(topicsNav, list);

    const foot = el('div', 'tg-foot');
    const ask = el('label', 'tg-askme');
    askBox = el('input');
    askBox.type = 'checkbox';
    askBox.checked = !!data.ask;
    askBox.addEventListener('change', function () {
      data.ask = askBox.checked;
      post(ANSWER, { answer: askBox.checked ? 'again' : 'never' });
    });
    ask.append(askBox, document.createTextNode(' Offer a tour when I sign in'));
    foot.append(ask);

    panel.append(top, hello, label, body, foot);
    if (!topic) topic = data.tours.some(function (t) { return t.group === 'you'; }) ? 'you' : 'common';
  }

  function tourCard(t) {
    const card = el('div', 'tg-card' + (t.done ? ' is-done' : ''));
    const ic = el('span', 'tg-card-ic');
    ic.append(icon(t.icon));
    const words = el('div', 'tg-card-w');
    words.append(el('b', '', t.title), el('p', '', t.says));
    const meta = el('small', '', t.steps.length + ' step' + (t.steps.length === 1 ? '' : 's'));
    if (t.done) {
      const d = el('span', 'tg-done');
      d.append(icon('fa-circle-check'), document.createTextNode(' Done'));
      meta.append(document.createTextNode(' · '), d);
    }
    words.append(meta);
    const go = el('button', 'cb sm ' + (t.done ? '' : 'primary'), t.done ? 'Again' : 'Start');
    go.type = 'button';
    go.setAttribute('aria-label', (t.done ? 'Take again: ' : 'Start the tour: ') + t.title);
    go.addEventListener('click', function () { start(t); });
    card.append(ic, words, go);
    return card;
  }

  function screenTour(p) {
    return {
      key: 'screen:' + p.label, title: p.label, steps: [
        { url: p.url, spot: ['.ui-head .ui-title', '.ui-head', '.wpb-head', 'main h1', 'h1'], title: p.label,
          text: p.says || 'What this screen is for.' },
        { url: p.url, spot: ['.staff-nav .sn-group.current a[aria-current="page"]', '.staff-nav .sn-group.current a.active',
          '.staff-nav .sn-tab.on'], title: 'Where it is', text: 'In the menu: ' + p.where + '.', optional: true },
        { url: p.url, spot: ['.ui-head .help-pop'], title: 'How it works',
          text: 'The ? beside the heading tells you more about this screen.', optional: true },
        { url: p.url, spot: ['#favDD'], title: 'Keep it close',
          text: 'Star it to keep it in your favourites, with the filters it has.', optional: true },
      ],
    };
  }

  function screenRow(p) {
    const row = el('div', 'tg-screen');
    const ic = el('span', 'tg-card-ic');
    ic.append(icon(p.icon));
    const words = el('div', 'tg-card-w');
    words.append(el('b', '', p.label));
    if (p.says) words.append(el('p', '', p.says));
    words.append(el('small', '', p.where));
    const acts = el('div', 'tg-screen-acts');
    const show = el('button', 'cb sm primary', 'Show me');
    show.type = 'button';
    show.setAttribute('aria-label', 'Show me ' + p.label);
    show.addEventListener('click', function () { start(screenTour(p)); });
    const open = el('a', 'cb sm', 'Open');
    open.href = p.url;
    open.setAttribute('aria-label', 'Open ' + p.label);
    acts.append(show, open);
    row.append(ic, words, acts);
    return row;
  }

  function draw() {
    const q = (find.value || '').trim().toLowerCase();
    list.textContent = '';
    topicsNav.querySelectorAll('.tg-topic').forEach(function (b) {
      const on = !q && b.dataset.topic === topic;
      b.classList.toggle('on', on);
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    const has = function (s) { return (s || '').toLowerCase().indexOf(q) !== -1; };
    if (q) {
      const tours = data.tours.filter(function (t) { return has(t.title) || has(t.says); });
      const screens = [];
      data.screens.forEach(function (a) {
        a.pages.forEach(function (p) { if (has(p.label) || has(p.says) || has(p.where) || has(a.label)) screens.push(p); });
      });
      if (tours.length) list.append(el('p', 'tg-h', 'Tours'));
      tours.forEach(function (t) { list.append(tourCard(t)); });
      if (screens.length) list.append(el('p', 'tg-h', 'Screens'));
      screens.slice(0, 40).forEach(function (p) { list.append(screenRow(p)); });
      if (!tours.length && !screens.length) list.append(el('p', 'tg-none', 'Nothing by that name. Try another word.'));
      return;
    }
    if (topic === 'screens') {
      list.append(el('p', 'tg-intro', 'Every screen you can open: what it is for and where it is. “Show me” walks you to it.'));
      data.screens.forEach(function (a) {
        const h = el('p', 'tg-h');
        h.append(icon(a.icon), document.createTextNode(' ' + a.label));
        list.append(h);
        a.pages.forEach(function (p) { list.append(screenRow(p)); });
      });
      return;
    }
    const intro = {
      you: data.profile ? 'Made for your role: ' + data.profile + '.' : 'Made for what your role opens.',
      common: 'The places every screen shares, for everybody.',
      more: 'Other roles’ tours you can follow too.',
    }[topic];
    if (intro) list.append(el('p', 'tg-intro', intro));
    data.tours.filter(function (t) { return t.group === topic; }).forEach(function (t) { list.append(tourCard(t)); });
  }

  function openPanel(on) {
    if (on) {
      load().then(function () {
        buildPanel();
        draw();
        panel.hidden = false;
        btn.setAttribute('aria-expanded', 'true');
        document.body.classList.add('tg-open');
        closeAsk();
        find.focus({ preventScroll: true });
      }).catch(function () {
        panel.hidden = false;
        panel.textContent = 'The tour guide could not load. Please try again.';
      });
      return;
    }
    panel.hidden = true;
    btn.setAttribute('aria-expanded', 'false');
    document.body.classList.remove('tg-open');
  }
  btn.addEventListener('click', function () { openPanel(panel.hidden); });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && !panel.hidden && !cur) {
      openPanel(false);
      btn.focus();
    }
  });
  document.addEventListener('click', function (e) {
    if (!panel.hidden && !panel.contains(e.target) && !btn.contains(e.target) && !cur) openPanel(false);
  });

  // ------------------------------------------------------------------------------------------------ a tour
  let shade, spot, tip;

  function visible(n) {
    if (!n || !n.getClientRects().length) return false;
    const r = n.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    const s = getComputedStyle(n);
    return s.visibility !== 'hidden' && s.display !== 'none';
  }
  function findSpot(spots) {
    // the first selector with something on the screen wins; of its matches, the first one showing (a folded part's
    // copy is skipped)
    for (let i = 0; i < (spots || []).length; i++) {
      let all = [];
      try { all = document.querySelectorAll(spots[i]); } catch (e) { all = []; }
      for (let j = 0; j < all.length; j++) if (visible(all[j])) return all[j];
    }
    return null;
  }
  function samePage(url) {
    const want = new URL(url, location.href);
    const strip = function (p) { return p.replace(/\/+$/, ''); };
    if (strip(want.pathname) !== strip(location.pathname)) return false;
    const now = new URLSearchParams(location.search);
    let ok = true;
    want.searchParams.forEach(function (v, k) { if (now.get(k) !== v) ok = false; });
    return ok;
  }

  function start(t) {
    openPanel(false);
    closeAsk();
    cur = { key: t.key, title: t.title, steps: t.steps, i: 0, at: Date.now() };
    dir = 1;
    show();
  }

  function overlay() {
    if (shade) return;
    shade = el('div', 'tg-shade');
    spot = el('div', 'tg-spot');
    tip = el('div', 'tg-tip');
    tip.setAttribute('role', 'dialog');
    tip.setAttribute('aria-modal', 'true');
    tip.tabIndex = -1;
    shade.addEventListener('click', function (e) { e.preventDefault(); });
    document.body.append(shade, spot, tip);
    document.body.classList.add('tg-touring');
    window.addEventListener('resize', place);
    window.addEventListener('scroll', place, true);
    document.addEventListener('keydown', keys, true);
  }
  function teardown() {
    if (!shade) return;
    shade.remove(); spot.remove(); tip.remove();
    shade = spot = tip = null;
    document.body.classList.remove('tg-touring');
    window.removeEventListener('resize', place);
    window.removeEventListener('scroll', place, true);
    document.removeEventListener('keydown', keys, true);
  }
  function keys(e) {
    if (!cur) return;
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); end(); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); step(1); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); step(-1); }
  }

  let target = null;
  function show() {
    if (!cur) return;
    if (cur.i < 0) cur.i = 0;
    const st = cur.steps[cur.i];
    if (!st) { finish(); return; }
    cur.at = Date.now();
    // another screen: open it, once -- if the server sends us on elsewhere (a site admin's copy of a screen), the
    // step is shown where we landed rather than going round again
    if (st.url && !samePage(st.url) && cur.went !== cur.i) {
      cur.went = cur.i;
      store(RUN, cur);
      teardown();
      location.href = st.url;
      return;
    }
    store(RUN, cur);
    target = findSpot(st.spot);
    if (!target && st.optional) {
      // a part this screen does not have: on to the next one (or back, when going back)
      if ((dir > 0 && cur.i < cur.steps.length - 1) || (dir < 0 && cur.i > 0)) { cur.i += dir; show(); return; }
    }
    overlay();
    card(st);
    if (target) {
      const r = target.getBoundingClientRect();
      if (r.top < 70 || r.bottom > window.innerHeight - 20) target.scrollIntoView({ block: 'center', inline: 'nearest' });
    }
    place();
    tip.focus({ preventScroll: true });
  }

  function card(st) {
    tip.textContent = '';
    const n = cur.steps.length;
    const head = el('p', 'tg-tip-k', cur.title + ' · ' + (cur.i + 1) + ' of ' + n);
    const t = el('h3', 'tg-tip-t', st.title);
    t.id = 'tgTipT';
    tip.setAttribute('aria-labelledby', 'tgTipT');
    const p = el('p', 'tg-tip-p', st.text);
    const dots = el('div', 'tg-dots');
    dots.setAttribute('aria-hidden', 'true');
    for (let i = 0; i < n; i++) dots.append(el('span', i === cur.i ? 'on' : ''));
    const bar = el('div', 'tg-tip-b');
    const endB = el('button', 'tg-end', 'End tour');
    endB.type = 'button';
    endB.addEventListener('click', end);
    const back = el('button', 'cb sm', 'Back');
    back.type = 'button';
    back.disabled = cur.i === 0;
    back.addEventListener('click', function () { step(-1); });
    const next = el('button', 'cb sm primary', cur.i === n - 1 ? 'Finish' : 'Next');
    next.type = 'button';
    next.addEventListener('click', function () { step(1); });
    bar.append(endB, back, next);
    tip.append(head, t, p, dots, bar);
    if (!target) {
      const note = el('p', 'tg-tip-note', st.url || !st.spot.length ? '' : 'This part is not on your screen right now.');
      if (note.textContent) tip.insertBefore(note, dots);
    }
    setTimeout(function () { if (next.isConnected) next.focus({ preventScroll: true }); }, 0);
  }

  let raf = 0;
  function place() {
    if (raf) return;
    raf = requestAnimationFrame(function () {
      raf = 0;
      if (!tip) return;
      const W = window.innerWidth, H = window.innerHeight, M = 12;
      if (!target || !target.isConnected || !visible(target)) {
        spot.hidden = true;
        shade.classList.add('dim');
        tip.classList.add('mid');
        tip.style.left = tip.style.top = '';
        return;
      }
      shade.classList.remove('dim');
      tip.classList.remove('mid');
      spot.hidden = false;
      const r = target.getBoundingClientRect(), pad = 6;
      const top = Math.max(r.top - pad, 2), left = Math.max(r.left - pad, 2);
      const bottom = Math.min(r.bottom + pad, H - 2), right = Math.min(r.right + pad, W - 2);
      spot.style.top = top + 'px';
      spot.style.left = left + 'px';
      spot.style.width = Math.max(right - left, 8) + 'px';
      spot.style.height = Math.max(bottom - top, 8) + 'px';
      const tw = tip.offsetWidth, th = tip.offsetHeight;
      let x, y;
      if (W <= 600) {                                   // a phone: the card sits at the bottom, or the top
        x = M;
        y = bottom + th + M < H ? H - th - M : M;
        if (top < th + 2 * M && bottom + th + M >= H) y = H - th - M;
      } else if (bottom + th + M < H) {                 // under it
        y = bottom + 10; x = r.left;
      } else if (top - th - M > 0) {                    // over it
        y = top - th - 10; x = r.left;
      } else if (right + tw + M < W) {                  // beside it, right (the rail)
        x = right + 12; y = r.top;
      } else {                                          // beside it, left
        x = left - tw - 12; y = r.top;
      }
      x = Math.min(Math.max(x, M), W - tw - M);
      y = Math.min(Math.max(y, M), H - th - M);
      tip.style.left = x + 'px';
      tip.style.top = y + 'px';
    });
  }

  function step(d) {
    if (!cur) return;
    dir = d;
    if (d > 0 && cur.i >= cur.steps.length - 1) { finish(); return; }
    cur.i = Math.max(0, cur.i + d);
    show();
  }
  function end() {
    cur = null;
    store(RUN, null);
    teardown();
    btn.focus({ preventScroll: true });
  }
  function finish() {
    const key = cur && cur.key;
    end();
    if (key) {
      post(DONE, { key: key });
      if (data) data.tours.forEach(function (t) { if (t.key === key) t.done = true; });
      toast('Tour done. The guide is here whenever you want it.');
    }
  }
  function toast(text) {
    const t = el('div', 'tg-toast');
    t.setAttribute('role', 'status');
    t.append(icon('fa-circle-check'), document.createTextNode(' ' + text));
    document.body.append(t);
    setTimeout(function () { t.classList.add('out'); }, 3200);
    setTimeout(function () { t.remove(); }, 3800);
  }

  // ------------------------------------------------------------------------------------------------ the question
  let askEl = null;
  function closeAsk() {
    if (askEl) { askEl.remove(); askEl = null; }
  }
  function answer(what) {
    post(ANSWER, { answer: what });
    closeAsk();
    if (what === 'never' && data) data.ask = false;
  }
  function ask() {
    if (cur || !panel.hidden || askEl) return;
    if (document.hidden) {
      document.addEventListener('visibilitychange', function again() {
        if (!document.hidden) { document.removeEventListener('visibilitychange', again); ask(); }
      });
      return;
    }
    load().then(function (d) {
      if (cur || !panel.hidden) return;
      post(ANSWER, { answer: 'shown' });
      const rec = d.tours.filter(function (t) { return t.key === d.recommended; })[0] || d.tours[0];
      askEl = el('div', 'tg-ask');
      askEl.setAttribute('role', 'dialog');
      askEl.setAttribute('aria-labelledby', 'tgAskT');
      const ic = el('span', 'tg-ask-ic');
      ic.append(icon('fa-route'));
      const w = el('div', 'tg-ask-w');
      const t = el('b', '', 'Would you like a quick tour?');
      t.id = 'tgAskT';
      w.append(t, el('p', '', (rec ? '“' + rec.title + '”: ' + rec.steps.length + ' short steps'
        + (d.profile ? ', made for your role as ' + d.profile : '') + '. ' : '')
        + 'The Tour guide button down here has every tour, any time.'));
      const b = el('div', 'tg-ask-b');
      const yes = el('button', 'cb sm primary', 'Yes, show me');
      yes.type = 'button';
      yes.addEventListener('click', function () { answer('yes'); if (rec) start(rec); });
      const later = el('button', 'cb sm', 'Not now');
      later.type = 'button';
      later.addEventListener('click', function () { answer('later'); });
      const never = el('button', 'tg-end', 'Don’t ask again');
      never.type = 'button';
      never.addEventListener('click', function () { answer('never'); });
      b.append(yes, later, never);
      w.append(b);
      const x = el('button', 'tg-x');
      x.type = 'button';
      x.setAttribute('aria-label', 'Close');
      x.setAttribute('title', 'Not now');
      x.append(icon('fa-xmark'));
      x.addEventListener('click', function () { answer('later'); });
      askEl.append(ic, w, x);
      document.body.append(askEl);
    }).catch(function () { /* no guide today: nothing to ask */ });
  }

  // ------------------------------------------------------------------------------------------------ on load
  let run = null;
  try { run = JSON.parse(read(RUN) || 'null'); } catch (e) { run = null; }
  if (run && run.steps && Date.now() - (run.at || 0) < FRESH) {
    cur = run;
    // carry on once the screen is there (a moment for its own scripts); pictures and fonts arriving later only move
    // the spotlight, so 'load' re-places it rather than waiting for it (a slow outside file must not stop the tour)
    const resume = function () { setTimeout(show, 250); };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', resume);
    else resume();
    window.addEventListener('load', function () { if (cur && tip) place(); });
  } else {
    store(RUN, null);
    if (ASK) {
      let landed = parseInt(read(LANDED), 10) || 0;
      if (!landed) { landed = Date.now(); store(LANDED, String(landed)); }
      setTimeout(ask, Math.max(0, landed + AFTER - Date.now()));
    }
  }
  window.TourGuide = { open: function () { openPanel(true); }, start: function (key) {
    load().then(function (d) { const t = d.tours.filter(function (x) { return x.key === key; })[0]; if (t) start(t); });
  } };
})();
