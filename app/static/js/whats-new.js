/* The floating "what's new" button on staff pages. Markup: templates/_whats_new.html.
 *
 * Opens and closes the dial, and keeps the numbers current without a reload. It never builds an
 * item: the server drew all of them with the page, and this only rewrites the figures and words
 * inside them -- so the dial cannot look one way on load and another after a refresh.
 *
 * Refreshes once a minute while the tab is in front, and straight away when you come back to a
 * tab you left. A tab in the background asks for nothing: a console left open over a weekend
 * should not hold a query a minute against the database for nobody.
 */
(function () {
  'use strict';
  var root = document.getElementById('whatsNew');
  if (!root) return;
  var fab = document.getElementById('wnFab');
  var dial = document.getElementById('wnDial');
  var EVERY = 60 * 1000;
  var KEY = 'wn_open';                      // remembers "I keep it open" per browser, nothing more
  var lastTotal = +root.dataset.total || 0;

  function remember(open) {
    try { localStorage.setItem(KEY, open ? '1' : '0'); } catch (e) { /* private window: fine */ }
  }
  function remembered() {
    try { return localStorage.getItem(KEY) === '1'; } catch (e) { return false; }
  }

  function setOpen(open, focusFirst) {
    root.classList.toggle('is-open', open);
    dial.hidden = !open;
    fab.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (open && focusFirst) {
      var first = dial.querySelector('.wn-item');
      if (first) first.focus();
    }
  }

  fab.addEventListener('click', function () {
    var open = !root.classList.contains('is-open');
    // from the keyboard, move into the dial so Tab goes through the five links next; a mouse
    // click leaves focus where it is
    setOpen(open, open && fab.matches(':focus-visible'));
    remember(open);
  });

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && root.classList.contains('is-open')) {
      setOpen(false);
      remember(false);
      fab.focus();
    }
  });

  // A click anywhere else closes it -- but only for this visit; the remembered preference is for
  // the next page, and somebody who clicked into a table to read it did not mean "never again".
  document.addEventListener('click', function (e) {
    if (root.classList.contains('is-open') && !root.contains(e.target)) setOpen(false);
  });

  function shown(n) { return n < 100 ? String(n) : '99+'; }

  function paint(data) {
    if (!data || !data.items) return;
    data.items.forEach(function (it) {
      var a = root.querySelector('.wn-item[data-key="' + it.key + '"]');
      if (!a) return;                        // a list the server stopped offering: leave it be
      a.classList.toggle('is-zero', !it.count);
      a.setAttribute('aria-label', it.label + ': ' + it.hint);
      if (it.url) a.setAttribute('href', it.url);
      var n = a.querySelector('.wn-n');
      n.hidden = !it.count;
      n.textContent = shown(it.count);
      var hint = a.querySelector('.wn-hint');
      if (hint) hint.textContent = it.hint;
    });
    var total = data.total || 0;
    var badge = root.querySelector('.wn-total');
    badge.hidden = !total;
    badge.textContent = shown(total);
    fab.classList.toggle('has-new', total > 0);
    fab.setAttribute('aria-label', total ? "What's new: " + total + ' waiting' : "What's new");
    if (total > lastTotal) {
      // something arrived while you were on the page: one small bounce, not a siren
      fab.classList.remove('wn-bump');
      void fab.offsetWidth;                  // restart the animation if it is mid-play
      fab.classList.add('wn-bump');
    }
    lastTotal = total;
    root.dataset.total = String(total);
  }

  function refresh() {
    if (document.hidden) return;
    fetch(root.dataset.url, { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
      .then(function (r) {
        // signed out in another tab, or a redirect to the login page: keep what is showing
        var type = r.headers.get('Content-Type') || '';
        if (!r.ok || type.indexOf('application/json') === -1) return null;
        return r.json();
      })
      .then(paint)
      .catch(function () { /* offline for a moment: try again next minute */ });
  }

  setInterval(refresh, EVERY);
  document.addEventListener('visibilitychange', function () { if (!document.hidden) refresh(); });

  if (remembered()) setOpen(true, false);
})();
