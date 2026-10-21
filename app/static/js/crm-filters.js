/* Leads' filter panel (board.html): a column on the right of a wide screen, a drawer on a narrow one.
   A choice (a dropdown, an option, a tick) shows the leads at once; typed things (the search, picked dates)
   wait for Enter or "Show leads". The server checks every word again; this only opens, closes and sends. */
(function () {
  'use strict';
  var wrap = document.querySelector('[data-lf-wrap]');
  var form = wrap && wrap.querySelector('[data-lf-form]');
  if (!form) return;
  var side = wrap.querySelector('[data-lf]');
  var body = form.querySelector('[data-lf-body]');
  var scrim = document.querySelector('[data-lf-scrim]');
  var dates = form.querySelector('[data-lf-dates]');
  var apply = form.querySelector('[data-lf-apply]');
  var toggles = Array.prototype.slice.call(document.querySelectorAll('[data-lf-toggle]'));
  var wide = window.matchMedia('(min-width: 1200px)');
  var SIDE = 'crm-leads-side', SCROLL = 'crm-leads-side-scroll';

  function qa(sel) { return Array.prototype.slice.call(form.querySelectorAll(sel)); }
  function remember(store, key, value) {
    try { if (value == null) store.removeItem(key); else store.setItem(key, value); } catch (e) { /* private window */ }
  }
  function recall(store, key) {
    try { return store.getItem(key); } catch (e) { return null; }
  }

  /* ------------------------------------------------------------------ open and close */
  function isOpen() {
    return wide.matches ? !wrap.classList.contains('side-off') : wrap.classList.contains('side-open');
  }
  function paint() {
    var open = isOpen();
    toggles.forEach(function (b) { b.setAttribute('aria-expanded', open ? 'true' : 'false'); });
    if (scrim) scrim.hidden = wide.matches || !open;
    document.body.classList.toggle('lf-locked', !wide.matches && open);
  }
  function setOpen(open, focus) {
    if (wide.matches) {
      wrap.classList.toggle('side-off', !open);
      remember(localStorage, SIDE, open ? null : 'off');
    } else {
      wrap.classList.toggle('side-open', open);
    }
    paint();
    if (open && focus) {
      var first = form.querySelector('.lf-x');
      if (first) first.focus();
    } else if (!open && focus && toggles[0]) {
      toggles[0].focus();
    }
  }
  toggles.forEach(function (b) {
    b.addEventListener('click', function () { setOpen(!isOpen(), true); });
  });
  form.querySelector('[data-lf-close]').addEventListener('click', function () { setOpen(false, true); });
  if (scrim) scrim.addEventListener('click', function () { setOpen(false, true); });
  // before searchselect.js shuts an open dropdown on the same key: Escape closes the dropdown, not the drawer
  window.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && !wide.matches && isOpen() && !document.querySelector('dialog[open]')
        && !document.querySelector('.ss.is-open')) {
      setOpen(false, true);
    }
  }, true);
  function onWidth() {
    wrap.classList.remove('side-open');
    wrap.classList.toggle('side-off', recall(localStorage, SIDE) === 'off');
    paint();
  }
  if (wide.addEventListener) wide.addEventListener('change', onWidth); else wide.addListener(onWidth);
  paint();

  /* ------------------------------------------------------------------ sending */
  function send() {
    // empty words stay out of the address; chat's "Any" goes (an empty chat beats the remembered one)
    qa('input[name], select[name]').forEach(function (el) {
      if (el.disabled || ((el.type === 'radio' || el.type === 'checkbox') && !el.checked)) return;
      var empty = el.value === '' || (el.name === 'dt' && el.value === 'created');
      if (empty && !el.hasAttribute('data-lf-keep')) { el.disabled = true; el.setAttribute('data-lf-off', ''); }
    });
    remember(sessionStorage, SCROLL, String(body.scrollTop));
    if (apply) { apply.disabled = true; apply.textContent = 'Showing…'; }
    form.submit();
  }
  form.addEventListener('submit', function (e) { e.preventDefault(); send(); });
  // back to this page from the browser's memory: the fields as they were
  window.addEventListener('pageshow', function (e) {
    if (!e.persisted) return;
    qa('[data-lf-off]').forEach(function (el) { el.disabled = false; el.removeAttribute('data-lf-off'); });
    if (apply) { apply.disabled = false; apply.textContent = 'Show leads'; }
  });
  // the panel stays where it was scrolled to when the page comes back with the new leads
  var was = recall(sessionStorage, SCROLL);
  if (was != null) {
    body.scrollTop = +was || 0;
    remember(sessionStorage, SCROLL, null);
  }

  function due() { if (apply) apply.classList.add('is-due'); }

  function anyDate() {
    return qa('[data-lf-dates] input').some(function (i) { return i.value; });
  }

  // the ready-made ranges that suit the date: looking back (came in, last activity) or ahead (closes, travels)
  function swapRanges(field) {
    var set = (field === 'close' || field === 'travel') ? 'ahead' : 'past';
    var chosen = form.querySelector('input[name="dr"]:checked');
    var active = chosen && chosen.value !== '' && (chosen.value !== 'custom' || anyDate());
    qa('[data-sets]').forEach(function (label) {
      var on = label.getAttribute('data-sets').split(' ').indexOf(set) >= 0;
      var input = label.querySelector('input');
      label.hidden = !on;
      input.disabled = !on;
      if (!on && input.checked) {
        input.checked = false;
        form.querySelector('input[name="dr"][value=""]').checked = true;
      }
    });
    if (active) send();
  }

  form.addEventListener('change', function (e) {
    var el = e.target;
    if (el.hasAttribute('data-lf-typed')) {
      if (el.name === 'd1' || el.name === 'd2') form.querySelector('[data-lf-custom]').checked = true;
      due();
      return;
    }
    if (el.hasAttribute('data-lf-dt')) { swapRanges(el.value); return; }
    if (el.name === 'dr') {
      if (el.value === 'custom') {
        dates.hidden = false;
        dates.querySelector('input').focus();
        due();
        return;
      }
      dates.hidden = true;
      qa('[data-lf-dates] input').forEach(function (i) { i.value = ''; });
    }
    send();
  });
  form.addEventListener('input', function (e) {
    if (e.target.hasAttribute('data-lf-typed')) due();
  });
})();
