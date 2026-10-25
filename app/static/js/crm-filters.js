/* Leads' filter bar (_lead_filters.html): a pill per filter, each a <details> with a short menu. One menu open at a
   time; a click elsewhere or Escape closes it. A choice (an option, a tick, a dropdown) shows the leads at once;
   typed things (the search, picked dates) wait for Enter or Apply. The server checks every word again; this only
   opens, closes and sends. */
(function () {
  'use strict';
  var form = document.querySelector('[data-lf-form]');
  if (!form) return;
  var dates = form.querySelector('[data-lf-dates]');
  var pills = Array.prototype.slice.call(form.querySelectorAll('[data-fp] > details'));

  function qa(sel) { return Array.prototype.slice.call(form.querySelectorAll(sel)); }

  /* ------------------------------------------------------------------ the menus */
  function closeAll(except) {
    pills.forEach(function (d) { if (d !== except) d.open = false; });
  }
  pills.forEach(function (d) {
    d.addEventListener('toggle', function () {
      if (!d.open) return;
      closeAll(d);
      // a menu near the right edge opens leftwards, so it stays on the screen
      var pop = d.querySelector('.fp-pop');
      pop.classList.remove('to-left');
      if (pop.getBoundingClientRect().right > window.innerWidth - 8) pop.classList.add('to-left');
      var on = d.querySelector('input:checked') || d.querySelector('input, select');
      if (on && on.type !== 'date') on.focus({ preventScroll: true });
    });
  });
  document.addEventListener('click', function (e) {
    if (!e.target.closest('[data-fp]')) closeAll(null);
  });
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    var open = pills.filter(function (d) { return d.open; })[0];
    if (open) { open.open = false; open.querySelector('summary').focus(); }
  });

  /* ------------------------------------------------------------------ More filters: the second row */
  // open while one of its filters is on (the server says so); otherwise as this person last left it
  var moreBtn = form.querySelector('[data-lf-more]'), moreRow = form.querySelector('[data-lf-more-row]');
  function showMore(on) {
    moreRow.hidden = !on;
    moreBtn.setAttribute('aria-expanded', on ? 'true' : 'false');
  }
  if (moreBtn && moreRow) {
    if (!moreBtn.classList.contains('on')) {
      try { showMore(localStorage.getItem('crm-lf-more') === '1'); } catch (e) { /* private window: closed */ }
    }
    moreBtn.addEventListener('click', function () {
      closeAll(null);
      showMore(moreRow.hidden);
      try { localStorage.setItem('crm-lf-more', moreRow.hidden ? '' : '1'); } catch (e) { /* not remembered */ }
    });
  }

  /* ------------------------------------------------------------------ sending */
  function send() {
    // empty words stay out of the address; chat's "Any" goes (an empty chat beats the remembered one)
    qa('input[name], select[name]').forEach(function (el) {
      if (el.disabled || ((el.type === 'radio' || el.type === 'checkbox') && !el.checked)) return;
      var empty = el.value === '' || (el.name === 'dt' && el.value === 'created');
      if (empty && !el.hasAttribute('data-lf-keep')) { el.disabled = true; el.setAttribute('data-lf-off', ''); }
    });
    form.classList.add('is-sending');
    form.submit();
  }
  form.addEventListener('submit', function (e) { e.preventDefault(); send(); });
  // back to this page from the browser's memory: the fields as they were
  window.addEventListener('pageshow', function (e) {
    if (!e.persisted) return;
    qa('[data-lf-off]').forEach(function (el) { el.disabled = false; el.removeAttribute('data-lf-off'); });
    form.classList.remove('is-sending');
  });

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
      return;
    }
    if (el.hasAttribute('data-lf-dt')) { swapRanges(el.value); return; }
    if (el.name === 'dr') {
      if (el.value === 'custom') {
        dates.hidden = false;
        dates.querySelector('input').focus();
        return;
      }
      dates.hidden = true;
      qa('[data-lf-dates] input').forEach(function (i) { i.value = ''; });
    }
    send();
  });
})();
