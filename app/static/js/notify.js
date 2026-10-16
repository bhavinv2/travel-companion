/* Desktop alerts for staff, turned on from My day ("Get a desktop alert when a customer writes?"):
   while the browser allows it and the page is visible, the bell is read every 60 seconds
   (/api/notifications?unread=1) and a new "customer waiting", "new lead" or "yours now" bell shows
   as a desktop notification. Off until the person turns it on; never inside a frame. The first read
   only notes what is there, so old bells never pop up. */
(function () {
  'use strict';
  if (window.self !== window.top || !('Notification' in window)) return;
  var script = document.currentScript;
  var api = script && script.dataset.api;
  if (!api) return;
  var KEY = 'crm-alerts';            // '1' (on) or 'no' (asked not to be asked again)
  var SEEN = 'crm-alerts-seen';      // the largest bell id already told
  var TYPES = { crm_waiting: 1, crm_lead: 1, crm_assigned: 1 };

  function get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private window */ } }

  function poll(baseline) {
    if (get(KEY) !== '1' || Notification.permission !== 'granted' || document.visibilityState !== 'visible') return;
    fetch(api + '?unread=1&limit=20', { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || !d.notifications) return;
        var items = d.notifications, seen = parseInt(get(SEEN), 10);
        var max = items.reduce(function (m, n) { return Math.max(m, n.id); }, isNaN(seen) ? 0 : seen);
        if (isNaN(seen) || baseline) { set(SEEN, String(max)); return; }
        var fresh = items.filter(function (n) { return n.id > seen && TYPES[n.type]; })
          .sort(function (a, b) { return a.id - b.id; });
        fresh.slice(0, 3).forEach(function (n) {
          var note = new Notification(n.title, { body: n.body || '', tag: 'crm-' + n.id });
          note.onclick = function () { window.focus(); if (n.link) location.href = n.link; };
        });
        if (fresh.length > 3) new Notification((fresh.length - 3) + ' more updates in the portal', { tag: 'crm-more' });
        set(SEEN, String(max));
      })
      .catch(function () { /* offline: try again in a minute */ });
  }

  function ready() {
    var ask = document.querySelector('[data-alerts-ask]');
    if (ask && get(KEY) !== 'no' && (Notification.permission === 'default' ||
        (Notification.permission === 'granted' && get(KEY) !== '1'))) {
      ask.hidden = false;
      var on = ask.querySelector('[data-alerts-on]'), no = ask.querySelector('[data-alerts-no]');
      if (on) on.addEventListener('click', function () {
        // asked from the top window, in this click, so the browser shows its own question
        Notification.requestPermission().then(function (p) {
          if (p === 'granted') { set(KEY, '1'); ask.hidden = true; poll(true); }
        });
      });
      if (no) no.addEventListener('click', function () { set(KEY, 'no'); ask.hidden = true; });
    }
    poll();
    setInterval(poll, 60000);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ready); else ready();
})();
