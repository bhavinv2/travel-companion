/* "Get our apps" (2026-11-01): a tab on the left edge of the public pages, and the box it opens with the group's two
   phone apps -- Preventia for families, Preventia Provider for doctors and care partners -- each with its Google Play
   and App Store buttons (services/store_apps.py, _get_app.html).

   The box opens by itself 10 seconds into a visit (counted from the visit's first page, so moving on to another page
   does not start the count again), once a visit, and not again for three days after somebody closes it, nor for a
   month after somebody taps a store. A phone sees only its own store; a computer also gets a QR code per app, which
   opens the right store on whichever phone scans it (/get-app/<key>). Drawn in its own shadow root, so a page's
   styles never reach it. */
(function () {
  'use strict';
  if (window.__getAppLoaded) return;
  var src = document.getElementById('getAppData');
  if (!src) return;
  var CFG;
  try { CFG = JSON.parse(src.textContent); } catch (e) { return; }
  if (!CFG.apps || !CFG.apps.length) return;
  window.__getAppLoaded = true;

  var WAIT = 10000, LATER = 3 * 864e5, GOT = 30 * 864e5;
  var ua = navigator.userAgent || '';
  var IOS = /iPhone|iPad|iPod/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  var ANDROID = /Android/i.test(ua);

  // ------------------------------------------------------------------------------------------------ small helpers
  function load(key, where) {
    try { return JSON.parse((where || localStorage).getItem(key) || 'null'); } catch (e) { return null; }
  }
  function keep(key, value, where) {
    try { (where || localStorage).setItem(key, JSON.stringify(value)); } catch (e) { /* a private window */ }
  }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function svg(markup) {
    var t = document.createElement('template');
    t.innerHTML = markup.trim();
    return t.content.firstChild;
  }
  var ICON = {
    phone: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="6" y="2" width="12" height="20" rx="2.6"/><path d="M11 18h2"/></svg>',
    close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>',
    user: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 20s-7-4.3-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.7-7 10-7 10z"/></svg>',
    provider: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 2v2M5 2v2"/><path d="M5 3H4a2 2 0 0 0-2 2v4a6 6 0 0 0 12 0V5a2 2 0 0 0-2-2h-1"/><path d="M8 15a6 6 0 0 0 12 0v-3"/><circle cx="20" cy="10" r="2"/></svg>',
    play: '<svg viewBox="0 0 24 24" aria-hidden="true" stroke-linejoin="round" stroke-width="1.2">' +
      '<path d="M3.6 1.6 13.6 12 3.6 22.4z" fill="#4285F4" stroke="#4285F4"/>' +
      '<path d="M3.6 1.6 17.2 9.7 13.6 12z" fill="#34A853" stroke="#34A853"/>' +
      '<path d="M3.6 22.4 13.6 12 17.2 14.3z" fill="#EA4335" stroke="#EA4335"/>' +
      '<path d="M17.2 9.7 21 12 17.2 14.3 13.6 12z" fill="#FBBC04" stroke="#FBBC04"/></svg>',
    apple: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12.152 6.896c-.948 0-2.415-1.078-3.96-1.04-2.04.027-3.91 1.183-4.961 3.014-2.117 3.675-.546 9.103 1.519 12.09 1.013 1.454 2.208 3.09 3.792 3.039 1.52-.065 2.09-.987 3.935-.987 1.831 0 2.35.987 3.96.948 1.637-.026 2.676-1.48 3.676-2.948 1.156-1.688 1.636-3.325 1.662-3.415-.039-.013-3.182-1.221-3.22-4.857-.026-3.04 2.48-4.494 2.597-4.559-1.429-2.09-3.623-2.324-4.39-2.376-2-.156-3.675 1.09-4.61 1.09zM15.53 3.83c.843-1.012 1.4-2.427 1.245-3.83-1.207.052-2.662.805-3.532 1.818-.78.896-1.454 2.338-1.273 3.714 1.338.104 2.715-.688 3.559-1.701"/></svg>'
  };

  // ------------------------------------------------------------------------------------------------ the look
  var CSS = [
    ':host{all:initial}',
    '*{box-sizing:border-box}',
    '.root{font-family:"Plus Jakarta Sans",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:#15192B;-webkit-font-smoothing:antialiased}',
    /* the tab */
    '.tab{position:fixed;left:0;top:50%;z-index:900;display:flex;flex-direction:column;align-items:center;gap:8px;padding:14px 7px 13px;',
    'border:0;border-radius:0 14px 14px 0;background:linear-gradient(180deg,#2D55D6,#16297A);color:#fff;cursor:pointer;font:inherit;',
    'box-shadow:6px 12px 30px -10px rgba(15,28,85,.6);transform:translate(0,-50%);transition:transform .35s cubic-bezier(.2,.9,.3,1.3),opacity .25s}',
    '.tab:hover{transform:translate(3px,-50%)}',
    '.tab:focus-visible{outline:3px solid #FFB547;outline-offset:2px}',
    '.tab svg{width:17px;height:17px;flex:none}',
    '.tab span{writing-mode:vertical-rl;transform:rotate(180deg);font-size:12.5px;line-height:1;font-weight:700;letter-spacing:.03em;white-space:nowrap}',
    '.tab i{position:absolute;top:7px;right:6px;width:8px;height:8px;border-radius:50%;background:#FFB547;box-shadow:0 0 0 0 rgba(255,181,71,.7);animation:ping 2.2s infinite}',
    '.root.seen .tab i{display:none}',
    '.root.open .tab{transform:translate(-110%,-50%);opacity:0;pointer-events:none}',
    '@keyframes ping{70%{box-shadow:0 0 0 8px rgba(255,181,71,0)}100%{box-shadow:0 0 0 0 rgba(255,181,71,0)}}',
    /* the box */
    '.box{position:fixed;left:18px;top:50%;z-index:2147483001;width:460px;max-width:calc(100vw - 28px);max-height:calc(100vh - 28px);overflow:auto;',
    'background:#fff;border-radius:24px;box-shadow:0 34px 90px -24px rgba(15,28,85,.55),0 0 0 1px rgba(15,28,85,.07);',
    'transform:translate(calc(-100% - 40px),-50%);opacity:0;visibility:hidden;transition:transform .55s cubic-bezier(.2,.9,.3,1.12),opacity .3s,visibility 0s .55s}',
    '.root.open .box{transform:translate(0,-50%);opacity:1;visibility:visible;transition:transform .55s cubic-bezier(.2,.9,.3,1.12),opacity .3s}',
    '.head{position:relative;overflow:hidden;padding:24px 58px 22px 24px;color:#fff;border-radius:24px 24px 0 0;',
    'background:radial-gradient(240px 160px at 92% -10%,rgba(255,181,71,.35),transparent 70%),radial-gradient(260px 200px at -10% 120%,rgba(15,157,140,.35),transparent 70%),linear-gradient(135deg,#2446B8,#0F1C55)}',
    '.head::after{content:"";position:absolute;right:-30px;bottom:-46px;width:150px;height:150px;border-radius:50%;border:2px dashed rgba(255,255,255,.16)}',
    '.eyebrow{display:inline-flex;align-items:center;gap:7px;font-size:11px;font-weight:800;letter-spacing:.14em;text-transform:uppercase;color:#FFCB7A}',
    '.eyebrow svg{width:14px;height:14px}',
    'h2{margin:8px 0 6px;font:600 24px/1.15 Fraunces,Georgia,"Times New Roman",serif;letter-spacing:-.01em}',
    '.head p{margin:0;font-size:13.5px;line-height:1.5;color:rgba(255,255,255,.82)}',
    '.x{position:absolute;top:14px;right:14px;z-index:1;width:34px;height:34px;display:grid;place-items:center;border:0;border-radius:50%;',
    'background:rgba(255,255,255,.14);color:#fff;cursor:pointer;transition:background .2s}',
    '.x:hover{background:rgba(255,255,255,.26)}',
    '.x:focus-visible,.store:focus-visible{outline:3px solid #FFB547;outline-offset:2px}',
    '.x svg{width:16px;height:16px}',
    '.apps{padding:8px 22px 18px}',
    '.app{display:grid;grid-template-columns:54px 1fr auto;column-gap:14px;row-gap:12px;align-items:start;padding:16px 0}',
    '.app+.app{border-top:1px dashed #E2E6EF}',
    '.ico{position:relative;width:54px;height:54px}',
    '.ico img{width:54px;height:54px;border-radius:15px;display:block;box-shadow:0 8px 18px -8px rgba(15,28,85,.45),0 0 0 1px rgba(15,28,85,.06)}',
    '.ico b{position:absolute;right:-6px;bottom:-6px;width:24px;height:24px;border-radius:50%;display:grid;place-items:center;color:#fff;border:2.5px solid #fff}',
    '.ico b svg{width:12px;height:12px}',
    '.app.user .ico b{background:#E4613F}',
    '.app.provider .ico b{background:#0F9D8C}',
    '.words{min-width:0}',
    '.name{display:block;font-size:16.5px;font-weight:800;color:#0F1C55;line-height:1.2}',
    '.who{display:inline-block;margin:5px 0 6px;padding:3px 9px;border-radius:999px;font-size:10.5px;font-weight:800;letter-spacing:.08em;text-transform:uppercase}',
    '.app.user .who{background:#FDECE6;color:#C2412A}',
    '.app.provider .who{background:#E3F1EC;color:#1F6B57}',
    '.words p{margin:0;font-size:13px;line-height:1.5;color:#535B70}',
    '.qr{grid-row:span 2;margin:0;width:92px;text-align:center}',
    '.qr div{width:92px;height:92px;padding:7px;border-radius:14px;background:#fff;border:1px solid #E2E6EF;box-shadow:0 6px 16px -10px rgba(15,28,85,.4)}',
    '.qr svg{width:100%;height:100%;display:block}',
    '.qr figcaption{margin-top:6px;font-size:10.5px;font-weight:700;color:#535B70;line-height:1.3}',
    '.stores{grid-column:1 / 3;display:flex;flex-wrap:wrap;gap:9px}',
    '.store{flex:1 1 0;min-width:0;display:flex;align-items:center;gap:8px;height:46px;padding:0 11px;border-radius:12px;background:#0B0D14;color:#fff;',
    'text-decoration:none;box-shadow:0 8px 18px -10px rgba(0,0,0,.6);transition:transform .25s cubic-bezier(.2,.9,.3,1.3),background .2s}',
    '.store:hover{transform:translateY(-2px);background:#1B1F2E}',
    '.store svg{width:22px;height:22px;flex:none}',
    '.store span{display:flex;flex-direction:column;line-height:1.05;white-space:nowrap}',
    '.store small{font-size:8.5px;font-weight:600;letter-spacing:.03em;text-transform:uppercase;opacity:.85}',
    '.store strong{font-size:15px;font-weight:700;letter-spacing:-.01em}',
    '.foot{margin:0;text-align:center;padding:12px 22px 16px;border-top:1px solid #EEF1F6;font-size:12px;color:#535B70}',
    '.foot a{color:#2446B8;font-weight:800;text-decoration:none}.foot a:hover{text-decoration:underline}',
    /* a phone: only its own store, no QR code, the box along the bottom */
    '.root.phone .qr{display:none}',
    '.root.phone .app{grid-template-columns:50px 1fr}',
    '.root.ios .store.play,.root.android .store.apple{display:none}',
    '@media (max-width:560px){',
    '.tab{padding:11px 5px 10px;gap:6px}.tab span{font-size:11px}.tab svg{width:15px;height:15px}',
    '.box{left:10px;right:10px;top:auto;bottom:10px;width:auto;max-width:none;max-height:calc(100vh - 80px);border-radius:22px;',
    'transform:translateY(calc(100% + 30px))}',
    '.root.open .box{transform:none}',
    '.head{padding:20px 54px 18px 20px;border-radius:22px 22px 0 0}h2{font-size:21px}',
    '.apps{padding:2px 18px 10px}.app{padding:13px 0;column-gap:12px;row-gap:10px}',
    '.qr{display:none}.app{grid-template-columns:50px 1fr}.ico,.ico img{width:50px;height:50px}',
    '.foot{padding:10px 18px 14px}',
    '}',
    '@media (prefers-reduced-motion:reduce){.tab,.box,.root.open .box,.store{transition:none}.tab i{animation:none}}'
  ].join('');

  // ------------------------------------------------------------------------------------------------ the parts
  var host = el('div');
  host.id = 'get-app';
  var shadow = host.attachShadow ? host.attachShadow({ mode: 'open' }) : host;
  var style = el('style');
  style.textContent = CSS;
  var root = el('div', 'root' + (IOS ? ' phone ios' : ANDROID ? ' phone android' : ''));
  if (load('gapp.opened')) root.classList.add('seen');

  var tab = el('button', 'tab');
  tab.type = 'button';
  tab.setAttribute('aria-expanded', 'false');
  tab.setAttribute('aria-controls', 'gappBox');
  tab.appendChild(svg(ICON.phone));
  tab.appendChild(el('span', null, 'Get our apps'));
  tab.appendChild(el('i'));

  var box = el('section', 'box');
  box.id = 'gappBox';
  box.setAttribute('role', 'dialog');
  box.setAttribute('aria-labelledby', 'gappTitle');
  var head = el('div', 'head');
  var eyebrow = el('span', 'eyebrow');
  eyebrow.appendChild(svg(ICON.phone));
  eyebrow.appendChild(document.createTextNode(IOS ? 'Free on the App Store' : ANDROID ? 'Free on Google Play' : 'Free on Android and iPhone'));
  var title = el('h2', null, 'Get the Preventia apps');
  title.id = 'gappTitle';
  head.appendChild(eyebrow);
  head.appendChild(title);
  head.appendChild(el('p', null, 'Book doctors, lab tests and home visits for your parents in a few taps, wherever you live.'));
  var x = el('button', 'x');
  x.type = 'button';
  x.setAttribute('aria-label', 'Close');
  x.appendChild(svg(ICON.close));
  head.appendChild(x);
  box.appendChild(head);

  var list = el('div', 'apps');
  CFG.apps.forEach(function (a) {
    var row = el('article', 'app ' + a.key);
    var ico = el('div', 'ico');
    var img = el('img');
    img.src = a.icon;
    img.alt = '';
    img.width = img.height = 54;
    ico.appendChild(img);
    var badge = el('b');
    badge.appendChild(svg(ICON[a.key] || ICON.user));
    ico.appendChild(badge);
    var words = el('div', 'words');
    words.appendChild(el('strong', 'name', a.name));
    words.appendChild(el('span', 'who', a.who));
    words.appendChild(el('p', null, a.text));
    row.appendChild(ico);
    row.appendChild(words);
    if (!IOS && !ANDROID && a.qr) {
      var qr = el('figure', 'qr');
      var code = el('div');
      code.appendChild(svg(a.qr));
      code.firstChild.setAttribute('role', 'img');
      code.firstChild.setAttribute('aria-label', 'QR code: ' + a.name + ' in your phone\'s store');
      qr.appendChild(code);
      qr.appendChild(el('figcaption', null, 'Scan with your phone'));
      row.appendChild(qr);
    }
    var stores = el('div', 'stores');
    stores.appendChild(store('play', a, a.play, 'Get it on', 'Google Play'));
    stores.appendChild(store('apple', a, a.apple, 'Download on the', 'App Store'));
    row.appendChild(stores);
    list.appendChild(row);
  });
  box.appendChild(list);
  var foot = el('p', 'foot');
  foot.appendChild(document.createTextNode('From '));
  var group = el('a', null, 'Preventia360');
  group.href = CFG.group;
  group.target = '_blank';
  group.rel = 'noopener';
  foot.appendChild(group);
  foot.appendChild(document.createTextNode(', which powers NRI Parent Service'));
  box.appendChild(foot);

  // a store's button: its own app on a phone (the store opens), its web page in a new tab on a computer
  function store(kind, app, href, small, big) {
    var a = el('a', 'store ' + kind);
    a.href = href;
    a.target = '_blank';
    a.rel = 'noopener';
    a.setAttribute('aria-label', big + ': ' + app.name);
    var mark = svg(ICON[kind]);
    a.appendChild(mark);
    var s = el('span');
    s.appendChild(el('small', null, small));
    s.appendChild(el('strong', null, big));
    a.appendChild(s);
    a.addEventListener('click', function () {
      keep('gapp.got', Date.now());
      if (typeof window.gtag === 'function') window.gtag('event', 'app_store_click', { app_name: app.name, store: kind });
    });
    return a;
  }

  // ------------------------------------------------------------------------------------------------ open and shut
  var auto = false;
  function isOpen() { return root.classList.contains('open'); }
  function setOpen(on, byItself) {
    if (on === isOpen()) return;
    root.classList.toggle('open', on);
    tab.setAttribute('aria-expanded', on ? 'true' : 'false');
    if (on) {
      auto = !!byItself;
      root.classList.add('seen');
      keep('gapp.opened', true);
      if (!byItself) x.focus({ preventScroll: true });     // opened on purpose: straight to it; by itself: never steal the keys
    } else if (auto) {
      keep('gapp.later', Date.now());                      // shut after it opened by itself: leave them be for a while
    }
  }
  tab.addEventListener('click', function () { setOpen(true, false); });
  x.addEventListener('click', function () { setOpen(false); tab.focus({ preventScroll: true }); });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && isOpen()) { setOpen(false); tab.focus({ preventScroll: true }); }
  });
  // a tap anywhere else on the page puts it away
  document.addEventListener('pointerdown', function (e) {
    if (isOpen() && (e.composedPath ? e.composedPath().indexOf(host) < 0 : !host.contains(e.target))) setOpen(false);
  }, true);

  // 10 seconds into the visit -- unless it opened already this visit, was shut lately, or a store was tapped
  function schedule() {
    var now = Date.now();
    var t0 = load('gapp.t0', sessionStorage);
    if (typeof t0 !== 'number' || t0 > now) {
      t0 = Math.min(now, Math.round((window.performance && performance.timeOrigin) || now));   // when the page began to open
      keep('gapp.t0', t0, sessionStorage);
    }
    if (load('gapp.shown', sessionStorage)) return;
    var later = load('gapp.later'), got = load('gapp.got');
    if ((typeof later === 'number' && now - later < LATER) || (typeof got === 'number' && now - got < GOT)) return;
    setTimeout(tryOpen, Math.max(800, WAIT - (now - t0)));
  }
  function tryOpen() {
    var typing = document.activeElement && /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
    var modal = document.querySelector('dialog[open], #contactModal.open');
    if (document.hidden || typing || modal) { setTimeout(tryOpen, 4000); return; }     // not over somebody's form
    if (isOpen() || load('gapp.shown', sessionStorage)) return;
    keep('gapp.shown', true, sessionStorage);
    setOpen(true, true);
  }

  function begin() {
    root.appendChild(tab);
    root.appendChild(box);
    shadow.appendChild(style);
    shadow.appendChild(root);
    document.body.appendChild(host);
    schedule();
  }
  if (document.body) begin();
  else document.addEventListener('DOMContentLoaded', begin);
})();
