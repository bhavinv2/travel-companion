/* Inbox › Visitors (templates/messaging/visitors.html): "On the site now" fetched again every 10 seconds while the tab
   shows (messaging.visitors_now), a visitor opened in the sheet on the right (messaging.visitor), and the filters'
   selects searching as soon as one changes. */
(function () {
  'use strict';
  var main = document.querySelector('.vz[data-now-url]');
  if (!main) return;
  var list = main.querySelector('[data-now-list]');
  var sheet = document.getElementById('vz-sheet');
  var inner = sheet && sheet.querySelector('[data-visitor-in]');
  var EVERY = 10000;
  var timer = null, openId = null;

  function get(url) {
    return fetch(url, { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); });
  }

  // ------------------------------------------------------------------------------------------------ on the site now
  function refresh() {
    if (document.visibilityState !== 'visible') return later();
    get(main.dataset.nowUrl).then(function (html) {
      list.innerHTML = html;
      var n = (list.firstElementChild && list.firstElementChild.dataset.n) || '0';
      main.querySelectorAll('[data-now-count]').forEach(function (b) { b.textContent = n; });
      var stamp = main.querySelector('[data-now-stamp]');
      if (stamp) {
        var d = new Date();
        stamp.textContent = 'Updated ' + ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2) + ':' +
          ('0' + d.getSeconds()).slice(-2) + ' · every 10 seconds';
      }
    }).catch(function () { /* the next round tries again */ }).then(later);
  }
  function later() { clearTimeout(timer); timer = setTimeout(refresh, EVERY); }
  document.addEventListener('visibilitychange', function () { if (document.visibilityState === 'visible') refresh(); });
  later();

  // ------------------------------------------------------------------------------------------------ one visitor
  function show(id) {
    if (!sheet || !id) return;
    openId = id;
    inner.classList.add('loading');
    if (!sheet.open) { inner.innerHTML = '<p class="muted">Opening…</p>'; sheet.showModal(); }
    get(main.dataset.visitorUrl.replace(/\/0$/, '/' + encodeURIComponent(id))).then(function (html) {
      if (openId !== id) return;
      inner.innerHTML = html;
      inner.classList.remove('loading');
      var close = inner.querySelector('[data-sheet-close]');
      if (close) close.focus();
      try { history.replaceState(null, '', setParam(location.href, 'v', id)); } catch (e) { /* the address stays */ }
    }).catch(function () {
      inner.classList.remove('loading');
      inner.innerHTML = '<p class="muted">This visitor could not be opened. They may have been deleted after 90 days.</p>' +
        '<button type="button" class="cb sm" data-sheet-close>Close</button>';
    });
  }
  function setParam(href, key, value) {
    var u = new URL(href);
    if (value == null) u.searchParams.delete(key); else u.searchParams.set(key, value);
    return u.toString();
  }
  function hide() {
    if (sheet && sheet.open) sheet.close();
  }
  if (sheet) {
    sheet.addEventListener('close', function () {
      openId = null;
      try { history.replaceState(null, '', setParam(location.href, 'v', null)); } catch (e) { /* the address stays */ }
    });
    sheet.addEventListener('click', function (e) {
      if (e.target === sheet) hide();                       // the shade around the sheet
      if (e.target.closest('[data-sheet-close]')) hide();
    });
  }
  main.addEventListener('click', function (e) {
    var row = e.target.closest('[data-visitor]');
    if (row && !e.target.closest('a')) show(row.dataset.visitor);
  });
  main.addEventListener('keydown', function (e) {
    var row = e.target.closest('tr[data-visitor]');
    if (row && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); show(row.dataset.visitor); }
  });
  if (main.dataset.open) show(main.dataset.open);

  // ------------------------------------------------------------------------------------------------ the filters
  main.querySelectorAll('[data-autosubmit]').forEach(function (sel) {
    sel.addEventListener('change', function () { sel.form.submit(); });
  });
})();
