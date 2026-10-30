/* The website's live chat bubble (services/livechat.py, routes/livechat.py; 2026-10-30) -- ours, in place of
   tawk.to's. Served at /live-chat.js with its words first (window.__liveChat); any page of ours, or a website listed
   under Set-up › Integrations › Website lead forms, carries it with one tag:

     <script src="https://nriparentservice.com/travel-companions/live-chat.js" async></script>

   Drawn in its own shadow root, so a page's styles never reach it. The visitor gives a name, an e-mail or WhatsApp
   number and a question; the chat's secret stays in this browser (localStorage), so the chat carries on from page to
   page and on coming back. It asks for news every few seconds while open (less often when shut or in another tab),
   shows "... is typing", counts what came while shut, and never plays a sound. */
(function () {
  'use strict';
  if (window.__liveChatLoaded || !window.__liveChat) return;
  window.__liveChatLoaded = true;
  var CFG = window.__liveChat;
  var me = document.currentScript;
  var BASE = (me && me.src ? me.src : '').replace(/\/live-chat\.js(\?.*)?$/, '');
  var API = BASE + '/api/live-chat';
  var STORE = 'lc.v1', OPEN = 'lc.open', TEASED = 'lc.teased';

  // ------------------------------------------------------------------------------------------------ small helpers
  function load(key, where) {
    try { return JSON.parse((where || localStorage).getItem(key) || 'null'); } catch (e) { return null; }
  }
  function keep(key, value, where) {
    try {
      if (value == null) (where || localStorage).removeItem(key);
      else (where || localStorage).setItem(key, JSON.stringify(value));
    } catch (e) { /* a private window: the chat lasts as long as the page */ }
  }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function initials(name) {
    var p = String(name || '').trim().split(/\s+/);
    return ((p[0] || '?').charAt(0) + (p.length > 1 ? p[p.length - 1].charAt(0) : '')).toUpperCase();
  }
  function call(method, path, body) {
    var opts = { method: method, credentials: 'omit', cache: 'no-store' };
    if (body) { opts.body = JSON.stringify(body); opts.headers = { 'Content-Type': 'text/plain;charset=UTF-8' }; }
    return fetch(API + path, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) { d._status = r.status; return d; });
    });
  }
  // ------------------------------------------------------------------------------------------------ the visit
  // Which pages this browser reads (services/visitors.py, Inbox › Visitors): a random id kept here, a word when a page
  // opens, every 30 s while it shows (90 s in the background) and when it closes -- to the app's own address
  // (CFG.here), so the address that reaches us is the visitor's and not a proxy's. Nothing else about them: the page,
  // the page that linked to it, the browser's language and time zone.
  var visit = null;
  function visitorId() {
    var v = load('lc.vid');
    if (typeof v === 'string' && /^[A-Za-z0-9_-]{16,40}$/.test(v)) return v;
    var c = window.crypto || window.msCrypto;
    if (!c || !c.getRandomValues) return null;
    var a = new Uint8Array(18), s = '';
    c.getRandomValues(a);
    for (var i = 0; i < a.length; i++) s += ('0' + a[i].toString(16)).slice(-2);
    keep('lc.vid', s);
    return s;
  }
  function tell(kind) {
    if (!visit) return;
    var body = { vid: visit.vid, kind: kind };
    if (kind === 'view') {
      body.page = location.href.split('#')[0];
      body.title = document.title.replace(/^\(\d+\+?\) /, '');
      body.ref = document.referrer || '';
      body.lang = navigator.language || '';
      try { body.tz = Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (e) { /* an old browser */ }
      body.touch = (navigator.maxTouchPoints || 0) > 1 ? 1 : 0;
    }
    var text = JSON.stringify(body);
    try {
      if (navigator.sendBeacon && navigator.sendBeacon(visit.url, new Blob([text], { type: 'text/plain;charset=UTF-8' }))) return;
    } catch (e) { /* try fetch */ }
    try {
      fetch(visit.url, { method: 'POST', body: text, mode: 'no-cors', credentials: 'omit', keepalive: true,
                         headers: { 'Content-Type': 'text/plain;charset=UTF-8' } }).catch(function () {});
    } catch (e) { /* the next word tries again */ }
  }
  function beatLater() {
    if (!visit) return;
    clearTimeout(visit.timer);
    visit.timer = setTimeout(function () { tell('beat'); beatLater(); },
                             document.visibilityState === 'visible' ? 30000 : 90000);
  }
  function startVisit() {
    var vid = CFG.track ? visitorId() : null;
    if (!vid) return;
    visit = { vid: vid, url: CFG.here || (API + '/here'), timer: null };
    tell('view');
    beatLater();
    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'visible') tell('beat');
      beatLater();
    });
    window.addEventListener('pagehide', function () { tell('leave'); });
    window.addEventListener('pageshow', function (e) { if (e.persisted) { tell('view'); beatLater(); } });
  }

  var URL_RE = /(https?:\/\/[^\s<>"')]+)/g;
  function fill(node, text) {               // the words, with web addresses as links -- never as HTML
    String(text || '').split(URL_RE).forEach(function (part, i) {
      if (i % 2) {
        var a = el('a', null, part);
        a.href = part; a.target = '_blank'; a.rel = 'noopener noreferrer nofollow';
        node.appendChild(a);
      } else if (part) {
        node.appendChild(document.createTextNode(part));
      }
    });
  }
  function hhmm(d) { return ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2); }
  function dayWords(d) {
    var today = new Date(); today.setHours(0, 0, 0, 0);
    var that = new Date(d); that.setHours(0, 0, 0, 0);
    var diff = Math.round((today - that) / 86400000);
    if (diff === 0) return 'Today';
    if (diff === 1) return 'Yesterday';
    return that.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' });
  }

  var ICON = {
    chat: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 3h14a3 3 0 0 1 3 3v9a3 3 0 0 1-3 3h-8.2l-4.6 3.7A.75.75 0 0 1 5 21.1V18a3 3 0 0 1-3-3V6a3 3 0 0 1 3-3z" fill="currentColor"/></svg>',
    down: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9l6 6 6-6" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    close: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>',
    send: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3.4 20.4l17.5-7.5a1 1 0 0 0 0-1.8L3.4 3.6a.9.9 0 0 0-1.3 1l2 6.4 9 1-9 1-2 6.4a.9.9 0 0 0 1.3 1z" fill="currentColor"/></svg>',
    arrow: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    lock: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 10V7a5 5 0 0 1 10 0v3h1a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1h1zm2 0h6V7a3 3 0 0 0-6 0v3z" fill="currentColor"/></svg>'
  };

  var CSS = [
    ':host{all:initial}',
    '*{box-sizing:border-box}',
    '.lc{--brand:' + CFG.color + ';--amber:#F5A623;--amber-2:#E8961A;--ink:#1B2438;--muted:#5B6579;--line:#E6E1D8;--soft:#F7F5F0;',
    '  font-family:"Plus Jakarta Sans",system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;font-size:15px;line-height:1.45;color:var(--ink);',
    '  position:fixed;right:20px;bottom:20px;z-index:2147483000;display:flex;flex-direction:column;align-items:flex-end;gap:14px}',
    '.lc.raised{bottom:92px}',
    'button{font:inherit;cursor:pointer}',
    'svg{width:100%;height:100%;display:block}',
    /* the round button */
    '.launch{position:relative;width:60px;height:60px;border:0;border-radius:50%;background:var(--brand);color:#fff;padding:17px;',
    '  box-shadow:0 10px 28px rgba(15,31,61,.32),0 2px 6px rgba(15,31,61,.18);transition:transform .18s ease,box-shadow .18s ease}',
    '.launch:hover{transform:translateY(-2px) scale(1.03);box-shadow:0 14px 34px rgba(15,31,61,.36)}',
    '.launch:focus-visible{outline:3px solid var(--amber);outline-offset:3px}',
    '.launch .i{position:absolute;inset:17px;transition:transform .22s ease,opacity .18s ease}',
    '.launch .i.x{transform:rotate(-90deg) scale(.6);opacity:0}',
    '.lc.open .launch .i.c{transform:rotate(90deg) scale(.6);opacity:0}',
    '.lc.open .launch .i.x{transform:none;opacity:1}',
    '.launch::after{content:"";position:absolute;right:13px;top:14px;width:9px;height:9px;border-radius:50%;background:var(--amber);box-shadow:0 0 0 2px var(--brand)}',
    '.lc.open .launch::after{display:none}',
    '.badge{position:absolute;top:-4px;right:-4px;min-width:22px;height:22px;padding:0 6px;border-radius:11px;background:var(--amber);color:#0F1F3D;',
    '  font-size:12px;font-weight:800;line-height:22px;text-align:center;box-shadow:0 0 0 2px #fff}',
    '.badge[hidden]{display:none}',
    /* the hello above the button */
    '.teaser{position:relative;max-width:290px;background:#fff;border-radius:16px 16px 4px 16px;padding:14px 38px 14px 16px;',
    '  box-shadow:0 12px 32px rgba(15,31,61,.18);border:1px solid var(--line);cursor:pointer;animation:rise .3s ease both}',
    '.teaser b{display:block;font-size:14px;margin-bottom:2px}',
    '.teaser p{margin:0;font-size:13.5px;color:var(--muted)}',
    '.teaser .x{position:absolute;top:8px;right:8px;width:24px;height:24px;border:0;border-radius:50%;background:var(--soft);color:var(--muted);padding:6px}',
    '.teaser .x:hover{color:var(--ink)}',
    /* the window */
    '.panel{width:380px;height:min(640px,calc(100vh - 120px));background:#fff;border-radius:20px;overflow:hidden;display:flex;flex-direction:column;',
    '  box-shadow:0 24px 60px rgba(15,31,61,.26),0 4px 14px rgba(15,31,61,.12);border:1px solid rgba(15,31,61,.06);transform-origin:bottom right;animation:pop .22s ease both}',
    '.panel[hidden]{display:none}',
    '.lc.raised .panel{height:min(640px,calc(100vh - 192px))}',
    '@keyframes pop{from{opacity:0;transform:translateY(12px) scale(.97)}to{opacity:1;transform:none}}',
    '@keyframes rise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}',
    '.head{position:relative;padding:18px 18px 16px;color:#fff;background:linear-gradient(135deg,var(--brand) 0%,var(--brand) 55%,#22396a 100%)}',
    '.head::after{content:"";position:absolute;left:0;right:0;bottom:0;height:3px;background:linear-gradient(90deg,var(--amber),#E4632A)}',
    '.top{display:flex;align-items:center;gap:10px}',
    '.top h2{flex:1;margin:0;font-size:17px;font-weight:800;letter-spacing:-.01em;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}',
    '.hbtn{flex:none;width:34px;height:34px;border:0;border-radius:10px;background:rgba(255,255,255,.12);color:#fff;padding:7px}',
    '.hbtn:hover{background:rgba(255,255,255,.22)}',
    '.hbtn:focus-visible,.end:focus-visible{outline:2px solid var(--amber);outline-offset:2px}',
    '.end{flex:none;border:0;border-radius:10px;background:rgba(255,255,255,.12);color:#fff;padding:7px 11px;font-size:12.5px;font-weight:700}',
    '.end:hover{background:rgba(255,255,255,.22)}',
    '.end[hidden]{display:none}',
    '.who{display:flex;align-items:center;gap:10px;margin-top:12px;font-size:13px;color:rgba(255,255,255,.86)}',
    '.faces{display:flex}',
    '.face{width:30px;height:30px;border-radius:50%;background:var(--amber);color:#0F1F3D;font-size:12px;font-weight:800;display:flex;',
    '  align-items:center;justify-content:center;box-shadow:0 0 0 2px var(--brand);margin-left:-8px}',
    '.face:first-child{margin-left:0}',
    '.face.team{background:#fff}',
    '.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#3ddc97;margin-right:6px;box-shadow:0 0 0 3px rgba(61,220,151,.22)}',
    '.dot.away{background:#c3cad6;box-shadow:none}',
    /* the middle */
    '.body{flex:1;min-height:0;overflow-y:auto;background:var(--soft);padding:16px 14px 8px;scroll-behavior:smooth}',
    '.hello{display:flex;gap:8px;align-items:flex-end;margin-bottom:14px}',
    '.bubble{max-width:82%;padding:10px 13px;border-radius:16px;font-size:14.5px;white-space:pre-wrap;word-wrap:break-word;overflow-wrap:anywhere}',
    '.bubble a{color:inherit;text-decoration:underline}',
    '.them .bubble{background:#fff;border:1px solid var(--line);border-bottom-left-radius:5px}',
    '.mine .bubble{background:var(--brand);color:#fff;border-bottom-right-radius:5px}',
    '.av{flex:none;width:28px;height:28px;border-radius:50%;background:var(--amber);color:#0F1F3D;font-size:11px;font-weight:800;display:flex;align-items:center;justify-content:center}',
    '.av.blank{visibility:hidden}',
    '.form{background:#fff;border:1px solid var(--line);border-radius:16px;padding:14px;display:flex;flex-direction:column;gap:10px}',
    '.form h3{margin:0;font-size:14px;font-weight:800}',
    '.topics{display:flex;flex-wrap:wrap;gap:6px}',
    '.topic{border:1px solid var(--line);background:#fff;border-radius:999px;padding:6px 12px;font-size:13px;font-weight:600;color:var(--ink)}',
    '.topic:hover{border-color:var(--brand)}',
    '.topic[aria-pressed="true"]{background:var(--brand);border-color:var(--brand);color:#fff}',
    '.topic:focus-visible,.field input:focus-visible,.field textarea:focus-visible{outline:2px solid var(--amber);outline-offset:1px}',
    '.field{display:flex;flex-direction:column;gap:4px}',
    '.field span{font-size:12.5px;font-weight:700;color:var(--muted)}',
    '.field input,.field textarea{width:100%;border:1px solid #d9d3c8;border-radius:10px;padding:10px 12px;font:inherit;font-size:14.5px;color:var(--ink);background:#fff}',
    '.field textarea{resize:none;min-height:76px}',
    '.field input:focus,.field textarea:focus{border-color:var(--brand)}',
    '.go{display:flex;align-items:center;justify-content:center;gap:8px;border:0;border-radius:12px;padding:12px 16px;background:var(--amber);',
    '  color:#0F1F3D;font-weight:800;font-size:15px;transition:background .15s ease}',
    '.go:hover{background:var(--amber-2)}',
    '.go:disabled{opacity:.6;cursor:default}',
    '.go:focus-visible{outline:3px solid var(--brand);outline-offset:2px}',
    '.go i{width:18px;height:18px;display:inline-block}',
    '.err{margin:0;padding:8px 10px;border-radius:10px;background:#fdecea;color:#8a1c12;font-size:13px}',
    '.err[hidden]{display:none}',
    '.small{display:flex;align-items:center;gap:6px;margin:0;font-size:12px;color:var(--muted)}',
    '.small i{width:12px;height:12px;display:inline-block;flex:none}',
    '.note{margin:2px auto 14px;max-width:92%;text-align:center;font-size:12.5px;color:var(--muted)}',
    '.day{display:flex;justify-content:center;margin:10px 0}',
    '.day span{background:rgba(15,31,61,.07);color:var(--muted);font-size:11.5px;font-weight:700;padding:3px 10px;border-radius:999px}',
    '.msg{display:flex;gap:8px;align-items:flex-end;margin:2px 0}',
    '.msg.mine{justify-content:flex-end}',
    '.msg.first{margin-top:10px}',
    '.name{font-size:11.5px;font-weight:700;color:var(--muted);margin:10px 0 2px 36px}',
    '.time{font-size:11px;color:var(--muted);margin:3px 2px 0}',
    '.msg.mine + .time{text-align:right}',
    '.them + .time{margin-left:38px}',
    '.msg.sending .bubble{opacity:.6}',
    '.msg.failed .bubble{background:#fdecea;color:#8a1c12;border:1px solid #f3c4bd}',
    '.retry{display:block;margin:2px 2px 0 auto;border:0;background:none;color:#8a1c12;font-size:12px;font-weight:700;text-decoration:underline}',
    '.typing{display:flex;gap:8px;align-items:flex-end;margin:10px 0 4px}',
    '.typing[hidden]{display:none}',
    '.dots{display:inline-flex;gap:4px;padding:12px 14px;background:#fff;border:1px solid var(--line);border-radius:16px;border-bottom-left-radius:5px}',
    '.dots b{width:7px;height:7px;border-radius:50%;background:#9aa3b2;animation:blink 1.2s infinite ease-in-out}',
    '.dots b:nth-child(2){animation-delay:.15s}.dots b:nth-child(3){animation-delay:.3s}',
    '@keyframes blink{0%,60%,100%{transform:translateY(0);opacity:.5}30%{transform:translateY(-4px);opacity:1}}',
    '.typing small{font-size:11.5px;color:var(--muted);margin-bottom:6px}',
    /* the foot */
    '.foot{flex:none;display:flex;align-items:flex-end;gap:8px;padding:10px 12px 12px;border-top:1px solid var(--line);background:#fff}',
    '.foot[hidden]{display:none}',
    '.foot textarea{flex:1;resize:none;border:1px solid #d9d3c8;border-radius:14px;padding:10px 12px;font:inherit;font-size:14.5px;line-height:1.4;',
    '  max-height:120px;min-height:42px;color:var(--ink);background:var(--soft)}',
    '.foot textarea:focus{outline:none;border-color:var(--brand);background:#fff}',
    '.send{flex:none;width:42px;height:42px;border:0;border-radius:50%;background:var(--amber);color:#0F1F3D;padding:11px;transition:background .15s ease}',
    '.send:hover{background:var(--amber-2)}',
    '.send:disabled{background:#efe9df;color:#a7a197;cursor:default}',
    '.send:focus-visible{outline:3px solid var(--brand);outline-offset:2px}',
    '.ask{flex:none;display:flex;flex-direction:column;gap:8px;padding:12px 14px;border-top:1px solid var(--line);background:#fff8ec;font-size:13.5px}',
    '.ask[hidden]{display:none}',
    '.ask div{display:flex;gap:8px}',
    '.ask button{border:1px solid var(--line);background:#fff;border-radius:10px;padding:7px 12px;font-weight:700;font-size:13px}',
    '.ask button.yes{background:var(--brand);border-color:var(--brand);color:#fff}',
    '.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}',
    '@media (max-width:520px){',
    '  .lc{right:14px;bottom:14px}',
    '  .lc.raised{bottom:150px}',
    '  .lc.open{inset:0;right:0;bottom:0;gap:0}',
    '  .lc.open .launch,.lc.open .teaser{display:none}',
    '  .panel,.lc.raised .panel{width:100vw;height:100%;max-height:none;border-radius:0;border:0}',
    '}',
    '@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}.body{scroll-behavior:auto}}'
  ].join('\n');

  // ------------------------------------------------------------------------------------------------ the parts
  var host = el('div');
  host.id = 'nps-live-chat';
  var root = host.attachShadow ? host.attachShadow({ mode: 'open' }) : host;
  var style = el('style');
  style.textContent = CSS;
  root.appendChild(style);

  var wrap = el('div', 'lc');
  wrap.setAttribute('data-lc', '');
  var panel = el('section', 'panel');
  panel.hidden = true;
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-label', CFG.title + ': chat with us');

  var head = el('header', 'head');
  var top = el('div', 'top');
  var h2 = el('h2', null, CFG.title);
  var endBtn = el('button', 'end', 'End chat');
  endBtn.type = 'button'; endBtn.hidden = true;
  var hide = el('button', 'hbtn');
  hide.type = 'button'; hide.innerHTML = ICON.down; hide.setAttribute('aria-label', 'Close the chat window');
  top.appendChild(h2); top.appendChild(endBtn); top.appendChild(hide);
  var who = el('div', 'who');
  who.setAttribute('aria-live', 'polite');
  head.appendChild(top); head.appendChild(who);

  var body = el('div', 'body');
  var log = el('div');
  log.setAttribute('role', 'log');
  log.setAttribute('aria-live', 'polite');
  log.setAttribute('aria-label', 'Messages');
  var typing = el('div', 'typing');
  typing.hidden = true;
  body.appendChild(log); body.appendChild(typing);

  var ask = el('div', 'ask');
  ask.hidden = true;
  ask.appendChild(el('span', null, 'End this chat? You can start a new one any time.'));
  var askRow = el('div');
  var askYes = el('button', 'yes', 'End chat'); askYes.type = 'button';
  var askNo = el('button', null, 'Keep chatting'); askNo.type = 'button';
  askRow.appendChild(askYes); askRow.appendChild(askNo); ask.appendChild(askRow);

  var foot = el('div', 'foot');
  foot.hidden = true;
  var input = el('textarea');
  input.rows = 1; input.maxLength = 2000; input.placeholder = 'Write a message…';
  input.setAttribute('aria-label', 'Your message');
  var send = el('button', 'send');
  send.type = 'button'; send.innerHTML = ICON.send; send.setAttribute('aria-label', 'Send'); send.disabled = true;
  foot.appendChild(input); foot.appendChild(send);

  panel.appendChild(head); panel.appendChild(body); panel.appendChild(ask); panel.appendChild(foot);

  var launch = el('button', 'launch');
  launch.type = 'button';
  launch.setAttribute('aria-label', 'Chat with us');
  launch.setAttribute('aria-expanded', 'false');
  launch.innerHTML = '<span class="i c">' + ICON.chat + '</span><span class="i x">' + ICON.close + '</span>';
  var badge = el('span', 'badge');
  badge.hidden = true;
  launch.appendChild(badge);

  wrap.appendChild(panel);
  wrap.appendChild(launch);
  root.appendChild(wrap);

  // ------------------------------------------------------------------------------------------------ the state
  var saved = load(STORE) || {};
  var state = { token: saved.token || null, name: saved.name || '', after: 0, unread: saved.unread || 0,
                online: [], typing: null, open: false, topic: '' };
  var seenIds = {};
  var lastDay = null, lastSide = null, lastWho = null;
  var timer = null, quietSince = Date.now(), asking = false;

  function save() { keep(STORE, state.token ? { token: state.token, name: state.name, unread: state.unread } : null); }

  function setBadge() {
    badge.textContent = state.unread > 9 ? '9+' : String(state.unread);
    badge.hidden = !state.unread;
    launch.setAttribute('aria-label', state.unread ? 'Chat with us: ' + state.unread + ' new' : 'Chat with us');
    var t = document.title.replace(/^\(\d+\+?\) /, '');
    document.title = state.unread && document.visibilityState !== 'visible' ? '(' + state.unread + ') ' + t : t;
  }

  function drawWho() {
    who.textContent = '';
    var faces = el('span', 'faces');
    var names = state.online || [];
    if (names.length) {
      names.slice(0, 3).forEach(function (n) { faces.appendChild(el('span', 'face', initials(n))); });
    } else {
      faces.appendChild(el('span', 'face team', initials(CFG.title)));
    }
    who.appendChild(faces);
    var line = el('span');
    var dot = el('i', 'dot' + (names.length ? '' : ' away'));
    line.appendChild(dot);
    if (state.typing) line.appendChild(document.createTextNode(state.typing + ' is typing…'));
    else if (names.length) line.appendChild(document.createTextNode(
      (names.length === 1 ? names[0] + ' is' : names.slice(0, -1).join(', ') + ' and ' + names[names.length - 1] + ' are') +
      ' online · we reply in minutes'));
    else line.appendChild(document.createTextNode('Away just now · we will reply soon'));
    who.appendChild(line);
  }

  // ------------------------------------------------------------------------------------------------ before a chat
  function drawStart(prefill) {
    log.textContent = '';
    typing.hidden = true; foot.hidden = true; endBtn.hidden = true;
    lastDay = lastSide = lastWho = null;
    var hello = el('div', 'hello them');
    hello.appendChild(el('span', 'av', initials(CFG.title)));
    var b = el('div', 'bubble');
    fill(b, CFG.greeting);
    hello.appendChild(b);
    log.appendChild(hello);
    if (!(state.online || []).length) {
      var away = el('div', 'hello them awaynote');
      away.appendChild(el('span', 'av blank'));
      var ab = el('div', 'bubble');
      fill(ab, CFG.away);
      away.appendChild(ab);
      log.appendChild(away);
    }
    var form = el('form', 'form');
    form.noValidate = true;
    form.appendChild(el('h3', null, 'What is it about?'));
    var topics = el('div', 'topics');
    topics.setAttribute('role', 'group');
    topics.setAttribute('aria-label', 'What is it about?');
    (CFG.topics || []).forEach(function (t) {
      var c = el('button', 'topic', t.label);
      c.type = 'button';
      c.setAttribute('aria-pressed', state.topic === t.key && state.topicPicked ? 'true' : 'false');
      c.addEventListener('click', function () {
        state.topic = t.key; state.topicPicked = true;
        topics.querySelectorAll('.topic').forEach(function (x) { x.setAttribute('aria-pressed', x === c ? 'true' : 'false'); });
      });
      topics.appendChild(c);
    });
    form.appendChild(topics);
    function field(label, tag, attrs) {
      var f = el('label', 'field');
      f.appendChild(el('span', null, label));
      var i = el(tag);
      Object.keys(attrs).forEach(function (k) { i.setAttribute(k, attrs[k]); });
      f.appendChild(i);
      form.appendChild(f);
      return i;
    }
    var name = field('Your name', 'input', { type: 'text', autocomplete: 'name', maxlength: '80', required: '' });
    var contact = field('E-mail or WhatsApp number', 'input', { type: 'text', autocomplete: 'email', maxlength: '120',
                                                               placeholder: 'you@example.com or +1 555 123 4567', required: '' });
    var msg = field('Your question', 'textarea', { maxlength: '2000', rows: '3', required: '' });
    var trap = el('input');                  // only a bot fills this in
    trap.type = 'text'; trap.name = 'website'; trap.tabIndex = -1; trap.autocomplete = 'off';
    trap.setAttribute('aria-hidden', 'true'); trap.style.cssText = 'position:absolute;left:-9999px;width:1px;height:1px';
    form.appendChild(trap);
    if (prefill) { name.value = prefill.name || ''; contact.value = prefill.contact || ''; msg.value = prefill.message || ''; }
    else if (state.name) name.value = state.name;
    var err = el('p', 'err');
    err.hidden = true;
    err.setAttribute('role', 'alert');
    form.appendChild(err);
    var go = el('button', 'go');
    go.type = 'submit';
    go.appendChild(document.createTextNode('Start the chat'));
    var gi = el('i'); gi.innerHTML = ICON.arrow; go.appendChild(gi);
    form.appendChild(go);
    var small = el('p', 'small');
    var li = el('i'); li.innerHTML = ICON.lock; small.appendChild(li);
    small.appendChild(document.createTextNode('We use these only to answer you.'));
    form.appendChild(small);
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var said = { name: name.value.trim(), contact: contact.value.trim(), message: msg.value.trim() };
      var badMail = said.contact.indexOf('@') >= 0 && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(said.contact);
      var miss = !said.name ? name : (!said.contact || badMail) ? contact : !said.message ? msg : null;
      if (miss) {
        err.textContent = miss === name ? 'Please tell us your name.' : badMail ? 'That e-mail address does not look right.'
          : miss === contact ? 'Please give an e-mail or a WhatsApp number, so we can answer if you leave.'
          : 'Write your question first.';
        err.hidden = false; miss.focus(); return;
      }
      err.hidden = true; go.disabled = true; go.firstChild.textContent = 'Starting…';
      call('POST', '/start', { name: said.name, contact: said.contact, message: said.message, topic: state.topic,
                               page: location.href.split('#')[0], title: document.title.replace(/^\(\d+\+?\) /, ''),
                               website: trap.value, vid: visit ? visit.vid : null })
        .then(function (d) {
          if (!d.ok || !d.token) {
            go.disabled = false; go.firstChild.textContent = 'Start the chat';
            err.textContent = d.error || 'Sorry, the chat could not start. Please try again.';
            err.hidden = false; return;
          }
          state.token = d.token; state.name = said.name; state.unread = 0; state.after = 0; seenIds = {};
          save();
          drawChat();
          news(d);
          input.focus();
          schedule();
        })
        .catch(function () {
          go.disabled = false; go.firstChild.textContent = 'Start the chat';
          err.textContent = 'You seem to be offline. Please try again.'; err.hidden = false;
        });
    });
    log.appendChild(form);
    body.scrollTop = 0;
    if (state.open) (name.value ? msg : name).focus();
  }

  // ------------------------------------------------------------------------------------------------ the chat
  function drawChat() {
    log.textContent = '';
    lastDay = lastSide = lastWho = null;
    foot.hidden = false; endBtn.hidden = false;
    var note = el('p', 'note', 'You are chatting with ' + CFG.title + '. We answer here; if you leave, we will reply by e-mail or WhatsApp.');
    log.appendChild(note);
  }

  function addMessage(m, pending) {
    var at = m.at ? new Date(m.at) : new Date();
    var day = at.toDateString();
    if (day !== lastDay) {
      var d = el('div', 'day'); d.appendChild(el('span', null, dayWords(at)));
      log.appendChild(d);
      lastDay = day; lastSide = null;
    }
    var side = m.me ? 'mine' : 'them';
    var first = side !== lastSide || (!m.me && m.who !== lastWho);
    if (first && !m.me) log.appendChild(el('div', 'name', m.who || CFG.title));
    var row = el('div', 'msg ' + side + (first ? ' first' : '') + (pending ? ' sending' : ''));
    if (!m.me) row.appendChild(el('span', 'av', initials(m.who || CFG.title)));
    var b = el('div', 'bubble');
    fill(b, m.text);
    row.appendChild(b);
    log.appendChild(row);
    var t = el('div', 'time', hhmm(at));
    log.appendChild(t);
    // only the last of a run keeps its time
    var prev = row.previousElementSibling;
    if (!first && prev && prev.classList.contains('time')) prev.remove();
    lastSide = side; lastWho = m.who;
    return row;
  }

  function scrollDown() { body.scrollTop = body.scrollHeight; }

  function news(d) {
    if (!d) return;
    state.online = d.online || [];
    state.typing = d.typing || null;
    var nearBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 80;
    var fresh = 0;
    (d.messages || []).forEach(function (m) {
      if (m.id > state.after) state.after = m.id;
      if (seenIds[m.id]) return;
      seenIds[m.id] = true;
      addMessage(m);
      if (!m.me) { fresh += 1; quietSince = Date.now(); }
    });
    typing.textContent = '';
    if (state.typing) {
      typing.appendChild(el('span', 'av', initials(state.typing)));
      var col = el('div');
      var dots = el('span', 'dots'); dots.innerHTML = '<b></b><b></b><b></b>';
      col.appendChild(dots);
      typing.appendChild(col);
      typing.appendChild(el('span', 'sr', state.typing + ' is typing'));
    }
    typing.hidden = !state.typing;
    if (fresh && (!state.open || document.visibilityState !== 'visible')) { state.unread += fresh; save(); }
    setBadge();
    drawWho();
    if (fresh || nearBottom || state.typing) scrollDown();
  }

  function ask4news() {
    if (!state.token) return Promise.resolve();
    var reading = state.open && document.visibilityState === 'visible';
    return call('GET', '/' + encodeURIComponent(state.token) + '?after=' + state.after + (reading ? '&open=1' : ''))
      .then(function (d) {
        if (d.gone || d._status === 404) { forget(); return; }
        if (d.ok) news(d);
      })
      .catch(function () { /* offline a moment: asked again soon */ });
  }

  function every() {
    var quiet = Date.now() - quietSince > 10 * 60 * 1000;
    var shown = document.visibilityState === 'visible';
    if (state.open && shown) return quiet ? 8000 : 3000;
    if (shown) return quiet ? 30000 : 12000;
    return quiet ? 90000 : 30000;
  }
  function schedule(now) {
    clearTimeout(timer);
    if (!state.token) return;
    timer = setTimeout(function () { ask4news().then(function () { schedule(); }); }, now ? 0 : every());
  }

  function forget() {
    state.token = null; state.after = 0; state.unread = 0; seenIds = {};
    save(); setBadge();
    clearTimeout(timer);
    drawStart();
  }

  function sendNow(text, row) {
    var r = row || addMessage({ me: true, text: text, at: new Date().toISOString() }, true);
    r.classList.add('sending'); r.classList.remove('failed');
    var retry = r.nextElementSibling && r.nextElementSibling.classList.contains('retry') ? r.nextElementSibling : null;
    if (retry) retry.remove();
    scrollDown();
    quietSince = Date.now();
    call('POST', '/' + encodeURIComponent(state.token) + '/send', { text: text })
      .then(function (d) {
        if (d.ok) {
          r.classList.remove('sending');
          seenIds[d.id] = true;
          schedule(true);
          return;
        }
        if (d.gone) { forget(); return; }
        throw new Error(d.error || 'Not sent');
      })
      .catch(function () {
        r.classList.remove('sending'); r.classList.add('failed');
        var again = el('button', 'retry', 'Not sent. Tap to try again');
        again.type = 'button';
        again.addEventListener('click', function () { sendNow(text, r); });
        r.insertAdjacentElement('afterend', again);
      });
  }

  function grow() {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 120) + 'px';
    send.disabled = !input.value.trim();
  }
  input.addEventListener('input', grow);
  input.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); go(); }
  });
  send.addEventListener('click', go);
  function go() {
    var text = input.value.trim();
    if (!text || !state.token) return;
    input.value = ''; grow();
    sendNow(text);
    input.focus();
  }

  // ------------------------------------------------------------------------------------------------ open and shut
  var teaser = null;
  function dropTeaser(remember) {
    if (teaser) { teaser.remove(); teaser = null; }
    if (remember) keep(TEASED, 1, sessionStorage);
  }
  function setOpen(on, focus) {
    state.open = on;
    wrap.classList.toggle('open', on);
    panel.hidden = !on;
    launch.setAttribute('aria-expanded', on ? 'true' : 'false');
    keep(OPEN, on ? 1 : null, sessionStorage);
    if (on) {
      dropTeaser(true);
      if (!state.token) hello();
      state.unread = 0; save(); setBadge();
      if (state.token) { scrollDown(); schedule(true); if (focus) input.focus(); }
      else if (focus) {
        var f = log.querySelector('.field input, .field textarea');
        if (f) f.focus();
      }
    } else {
      ask.hidden = true; asking = false;
      if (focus) launch.focus();
      schedule();
    }
  }
  launch.addEventListener('click', function () { setOpen(!state.open, true); });
  hide.addEventListener('click', function () { setOpen(false, true); });
  wrap.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && state.open) { e.stopPropagation(); setOpen(false, true); }
  });
  endBtn.addEventListener('click', function () { asking = !asking; ask.hidden = !asking; if (asking) askYes.focus(); });
  askNo.addEventListener('click', function () { asking = false; ask.hidden = true; input.focus(); });
  askYes.addEventListener('click', function () {
    var token = state.token;
    ask.hidden = true; asking = false;
    if (token) call('POST', '/' + encodeURIComponent(token) + '/end', {}).catch(function () { /* ended here anyway */ });
    forget();
  });
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible' && state.open) { state.unread = 0; save(); }
    setBadge();
    schedule(document.visibilityState === 'visible');
  });

  function showTeaser() {
    if (state.token || state.open || load(TEASED, sessionStorage)) return;
    teaser = el('div', 'teaser');
    teaser.setAttribute('role', 'button');
    teaser.tabIndex = 0;
    teaser.appendChild(el('b', null, CFG.title));
    var p = el('p'); fill(p, CFG.greeting); teaser.appendChild(p);
    var x = el('button', 'x'); x.type = 'button'; x.innerHTML = ICON.close; x.setAttribute('aria-label', 'Hide this');
    x.addEventListener('click', function (e) { e.stopPropagation(); dropTeaser(true); });
    teaser.appendChild(x);
    teaser.addEventListener('click', function () { setOpen(true, true); });
    teaser.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setOpen(true, true); } });
    wrap.insertBefore(teaser, launch);
  }

  // before a chat: who of us is here, for the window's head
  function hello() {
    return call('GET', '/hello').then(function (d) {
      if (!d.ok || state.token) return;
      state.online = d.online || [];
      drawWho();
      var away = log.querySelector('.awaynote');          // somebody is here after all: no "we are away"
      if (away && state.online.length) away.remove();
    }).catch(function () { /* the head says "away" */ });
  }

  // ------------------------------------------------------------------------------------------------ go
  function begin() {
    if (document.querySelector('.wa-float')) wrap.classList.add('raised');     // the portal's own WhatsApp button
    document.body.appendChild(host);
    startVisit();
    drawWho();
    if (state.token) { drawChat(); ask4news().then(function () { setBadge(); schedule(); }); }
    else { drawStart(); hello(); }
    setBadge();
    if (load(OPEN, sessionStorage)) setOpen(true, false);
    else setTimeout(showTeaser, 6000);
  }
  // a page's own "Talk to us" button opens this window instead of leaving the page (the home page)
  window.liveChat = { open: function () { setOpen(true, true); } };
  if (document.body) begin();
  else document.addEventListener('DOMContentLoaded', begin);
})();
