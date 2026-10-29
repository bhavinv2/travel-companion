/* The rail beside WhatsApp chats (messaging/_rail.html): our WhatsApp numbers as round icons, small or with their
   names, and "Find a contact" across all of them.

   The WhatsApp CRM's number shows its own inbox (the frame). A Meta-direct number's chats are drawn in the pane laid
   over the frame: its list (messaging.number_chats) and one chat with the lead page's own message box
   (messaging.number_chat), kept fresh every few seconds and never over something half typed (crm.js applyLive). The
   panel on the right follows the open chat (frame.html: CRM_numberMode). The address keeps ?num= and ?chat=, so a
   reload lands on the same chat.

   Live chat ('web': the website's own bubble, 2026-10-30) opens the same way: its chats (messaging.live_chats) and one
   chat (messaging.live_chat), fresher than a number's, and the visitor is told when one of us types. Its own page
   (messaging/live_chat_page.html) has the pane and no rail: the addresses are on the pane then. */
(function () {
  'use strict';
  var rail = document.querySelector('[data-wr]');
  var pane = document.querySelector('[data-num-pane]');
  if (!pane) return;
  var urls = (rail || pane).dataset;
  var frame = document.querySelector('[data-wa-frame]');
  var list = pane.querySelector('[data-num-list]');
  var thread = pane.querySelector('[data-num-thread]');
  var csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
  var STORE = 'wa-rail';
  var PICK = thread.innerHTML;
  var mode = pane.dataset.on || 'crm';
  var open = {};          // the chat open on each number: {number: person id}
  var lists = {};         // each number's search and "whose" tab: {number: {q, who}}
  var threadWant = '';
  if (pane.dataset.chat) open[mode] = pane.dataset.chat;

  function toast(msg, bad) { if (window.CRM && window.CRM.toast) window.CRM.toast(msg, bad); }
  function get(url) {
    return fetch(url, { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.text() : ''; })
      .catch(function () { return ''; });
  }
  function listUrl(key, args) {
    var base = key === 'web' ? urls.webListUrl : urls.listUrl.replace(/\/0\/chats$/, '/' + key + '/chats');
    return base + '?' + new URLSearchParams(args).toString();
  }
  function threadUrl(key, pid) {
    return key === 'web' ? urls.webThreadUrl.replace(/\/0$/, '/' + pid)
                         : urls.threadUrl.replace(/\/0\/chat\/0$/, '/' + key + '/chat/' + pid);
  }
  function state(key) { return lists[key] || (lists[key] = { q: '', who: 'all' }); }
  function address(set) {
    var url = new URL(window.location.href);
    Object.keys(set).forEach(function (k) { if (set[k]) url.searchParams.set(k, set[k]); else url.searchParams.delete(k); });
    window.history.replaceState(null, '', url.pathname + url.search);
  }

  // ------------------------------------------------------------------ small, or with the names
  var toggle = rail && rail.querySelector('[data-wr-toggle]');
  function setOpen(on, remember) {
    rail.classList.toggle('open', on);
    toggle.setAttribute('aria-expanded', on ? 'true' : 'false');
    toggle.title = on ? 'Hide the names' : 'Show the names';
    if (remember) { try { localStorage.setItem(STORE, on ? 'open' : 'shut'); } catch (err) { /* private window */ } }
  }
  if (rail) {
    var saved = null;
    try { saved = localStorage.getItem(STORE); } catch (err) { saved = null; }
    setOpen(saved === 'open', false);
    toggle.addEventListener('click', function () { setOpen(!rail.classList.contains('open'), true); });
  }

  // ------------------------------------------------------------------ picking a number
  function pick(key, pid) {
    mode = key;
    if (pid) open[key] = String(pid);
    if (rail) rail.querySelectorAll('[data-wr-num]').forEach(function (b) {
      var on = b.dataset.wrNum === key;
      b.classList.toggle('on', on);
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    document.querySelectorAll('[data-num-banner]').forEach(function (p) { p.hidden = p.dataset.numBanner !== key; });
    if (key === 'crm') {
      pane.hidden = true;
      address({ num: '', chat: '' });
      if (window.CRM_numberMode) window.CRM_numberMode('crm');
      return;
    }
    pane.hidden = false;
    address({ num: key, chat: open[key] || '' });
    list.innerHTML = '';
    loadList(key);
    if (open[key]) {
      openChat(key, open[key]);
    } else {
      threadWant = '';
      thread.innerHTML = PICK;
      pane.classList.remove('reading');
      if (window.CRM_numberMode) window.CRM_numberMode(key, null);
    }
  }
  if (rail) rail.addEventListener('click', function (e) {
    var b = e.target.closest('[data-wr-num]');
    if (b) pick(b.dataset.wrNum);
  });

  // ------------------------------------------------------------------ a number's chats
  function mark() {
    list.querySelectorAll('[data-num-chat]').forEach(function (r) { r.classList.toggle('on', r.dataset.numChat === open[mode]); });
  }
  function count(key) {
    var holder = list.querySelector('[data-waiting]');
    var badge = rail && rail.querySelector('[data-wr-num="' + key + '"] [data-wr-count]');
    if (!holder || !badge) return;
    var n = +holder.dataset.waiting || 0;
    badge.textContent = n > 99 ? '99+' : String(n);
    badge.hidden = !n;
  }
  function loadList(key, focus) {
    var st = state(key);
    var want = list.dataset.want = key + '|' + st.q + '|' + st.who;
    get(listUrl(key, { q: st.q, who: st.who })).then(function (html) {
      if (list.dataset.want !== want || mode !== key || !html) return;
      var old = list.querySelector('[data-num-rows]'), top = old ? old.scrollTop : 0;
      list.innerHTML = html;
      var rows = list.querySelector('[data-num-rows]');
      if (rows) rows.scrollTop = top;
      mark();
      count(key);
      var input = list.querySelector('[data-num-q]');
      if (focus && input) { input.focus(); input.setSelectionRange(input.value.length, input.value.length); }
    });
  }
  var qTimer = null;
  list.addEventListener('input', function (e) {
    if (!e.target.matches('[data-num-q]')) return;
    clearTimeout(qTimer);
    var v = e.target.value, key = mode;
    qTimer = setTimeout(function () { state(key).q = v.trim(); loadList(key, true); }, 280);
  });
  list.addEventListener('click', function (e) {
    var who = e.target.closest('[data-num-who]');
    if (who) { state(mode).who = who.dataset.numWho; loadList(mode); return; }
    var more = e.target.closest('[data-num-more]');
    if (more) {
      var st = state(mode);
      more.disabled = true;
      get(listUrl(mode, { q: st.q, who: st.who, n: more.dataset.numMore })).then(function (html) {
        var li = more.closest('li');
        if (html) li.insertAdjacentHTML('afterend', html);
        li.remove();
        mark();
      });
      return;
    }
    var row = e.target.closest('[data-num-chat]');
    if (row) openChat(mode, row.dataset.numChat);
    if (e.target.closest('[data-num-new]') && window.CRM_newChat) window.CRM_newChat();
  });

  // ------------------------------------------------------------------ one chat
  function openChat(key, pid) {
    open[key] = String(pid);
    pane.classList.add('reading');
    mark();
    address({ chat: pid });
    var want = threadWant = key + '|' + pid;
    get(threadUrl(key, pid)).then(function (html) {
      if (threadWant !== want) return;
      if (!html) { thread.innerHTML = '<p class="nc-pick">This chat could not be opened.</p>'; return; }
      thread.innerHTML = html;
      var root = thread.querySelector('[data-lead-page]');
      if (root && window.CRM_bindLead) window.CRM_bindLead(root);
      // where the chat scrolls as a whole (a phone), its foot: the newest message over the box and Send
      var nt = thread.querySelector('[data-num-thread-in]');
      if (nt) nt.scrollTop = nt.scrollHeight;
    });
    if (window.CRM_numberMode) window.CRM_numberMode(key, { person: String(pid), num: key });
  }
  thread.addEventListener('click', function (e) {
    if (e.target.closest('[data-num-back]')) pane.classList.remove('reading');
  });
  // a live chat: the visitor sees "... is typing" while one of us writes (told at most every 4 seconds)
  var typedAt = 0;
  thread.addEventListener('input', function (e) {
    if (mode !== 'web' || !e.target.matches('[data-box-input]') || !e.target.value.trim()) return;
    var nt = thread.querySelector('[data-typing-url]');
    if (!nt || Date.now() - typedAt < 4000) return;
    typedAt = Date.now();
    fetch(nt.dataset.typingUrl, { method: 'POST', credentials: 'same-origin', headers: { 'X-CSRFToken': csrf } })
      .catch(function () { /* only a courtesy */ });
  });
  // "New chat" from the panel's start list: their chat on this number, opened (frame.html)
  window.CRM_openNumberChat = function (key, pid) {
    if (mode !== String(key)) { pick(String(key), pid); return; }
    openChat(mode, pid);
    loadList(mode);
  };

  // fresh by itself: the open chat every 8 seconds (a live chat's every 4), the list every 32 (Live chat's every 16)
  // -- never over what is being typed (applyLive leaves a busy region alone), and right after a send (crm.js calls
  // CRM_refreshThread)
  function refreshThread() {
    if (mode === 'crm' || !open[mode] || document.visibilityState !== 'visible') return;
    var want = mode + '|' + open[mode];
    if (threadWant !== want) return;
    get(threadUrl(mode, open[mode])).then(function (html) {
      var root = thread.querySelector('[data-lead-page]');
      if (html && root && threadWant === want && window.CRM_applyLive) window.CRM_applyLive(root, html);
      if (html && threadWant === want && mode === 'web') freshHead(html);
    });
  }
  // a live chat's head says whether they are still on the site: kept fresh with the messages
  function freshHead(html) {
    var doc = new DOMParser().parseFromString(html, 'text/html');
    var where = thread.querySelector('[data-live-where]'), nextWhere = doc.querySelector('[data-live-where]');
    if (where && nextWhere) where.outerHTML = nextWhere.outerHTML;
    var gone = thread.querySelector('[data-live-gone]'), nextGone = doc.querySelector('[data-live-gone]');
    if (gone && !nextGone) gone.remove();
    else if (gone && nextGone) gone.outerHTML = nextGone.outerHTML;
    else if (!gone && nextGone) {
      var tl = thread.querySelector('[data-lead-live="timeline"]');
      if (tl) tl.insertAdjacentHTML('beforebegin', nextGone.outerHTML);
    }
  }
  function refreshList() {
    if (mode === 'crm' || document.visibilityState !== 'visible') return;
    var a = document.activeElement;
    if (a && list.contains(a)) return;
    if (list.querySelectorAll('[data-num-chat]').length > 40) return;      // further down "More chats": left as it is
    loadList(mode);
  }
  window.CRM_refreshThread = function () { setTimeout(refreshThread, 300); setTimeout(refreshList, 900); };
  var ticks = 0;
  setInterval(function () {
    ticks += 1;
    if (mode === 'web' || ticks % 2 === 0) refreshThread();
    if (ticks % (mode === 'web' ? 4 : 8) === 0) refreshList();
  }, 4000);

  // ------------------------------------------------------------------ "Find a contact"
  if (!rail) { pick(mode, open[mode]); return; }
  var q = rail.querySelector('[data-wr-q]'), hits = rail.querySelector('[data-wr-hits]');
  var findTimer = null, asked = '';
  function find() {
    var words = q.value.trim();
    asked = words;
    if (words.length < 2) { hits.hidden = true; hits.innerHTML = ''; return; }
    get(rail.dataset.findUrl + '?q=' + encodeURIComponent(words)).then(function (html) {
      if (asked !== words) return;
      hits.innerHTML = html;
      hits.hidden = !html;
    });
  }
  // while small it opens the rail on the box; on a phone, where it stays in the row, it also closes it
  rail.querySelector('[data-wr-find]').addEventListener('click', function () {
    setOpen(!rail.classList.contains('open'), false);
    if (rail.classList.contains('open')) q.focus();
  });
  q.addEventListener('input', function () { clearTimeout(findTimer); findTimer = setTimeout(find, 250); });
  q.addEventListener('keydown', function (e) { if (e.key === 'Escape') { q.value = ''; find(); } });
  hits.addEventListener('click', function (e) {
    var b = e.target.closest('[data-wr-open]');
    if (!b) return;
    if (b.dataset.wrOpen !== 'crm') { pick(b.dataset.wrOpen, b.dataset.person); return; }
    // the WhatsApp CRM's chat: its inbox opens on it (a fresh hand-off), their lead beside it
    b.disabled = true;
    var fd = new FormData();
    fd.set('person', b.dataset.person);
    fetch(rail.dataset.startUrl, { method: 'POST', body: fd, credentials: 'same-origin', headers: { 'X-CSRFToken': csrf } })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        b.disabled = false;
        if (!d.ok) { toast(d.error || 'The chat could not be opened.', true); return; }
        frame.src = d.src;
        if (window.CRM_numberStarted) window.CRM_numberStarted({ conversation: String(d.conversation), phone: '', name: d.name });
        pick('crm');
      })
      .catch(function () { b.disabled = false; toast('The chat could not be opened. Try again.', true); });
  });

  if (mode !== 'crm') pick(mode, open[mode]);
})();
