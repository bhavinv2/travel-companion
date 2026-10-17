/* Visual Flow (E26). Following a customer, or no longer, only changes the page's person_id query params and
   reloads: the page is drawn server-side (services/crm_people.flow_data), so there is no state to keep here.
   A stage on a strip (data-flow-jump) opens its step in the step-by-step guide and flashes it. */
(function () {
  'use strict';

  function jump(hash) {
    var target = hash && document.getElementById(hash.slice(1));
    if (!target) return false;
    var fold = target.closest('details');
    if (fold) fold.open = true;
    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    var lit = target.classList.contains('fg') || target.classList.contains('flow-who') ? target : null;
    if (lit) {
      lit.classList.add('flash');
      setTimeout(function () { lit.classList.remove('flash'); }, 1600);
    }
    return true;
  }

  document.querySelectorAll('[data-flow-jump]').forEach(function (a) {
    a.addEventListener('click', function (e) {
      if (jump(a.getAttribute('href'))) { e.preventDefault(); history.replaceState(null, '', a.getAttribute('href')); }
    });
  });
  if (location.hash) jump(location.hash);

  document.querySelectorAll('[data-flow-remove]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var id = btn.getAttribute('data-flow-remove');
      var params = new URLSearchParams(location.search);
      var kept = params.getAll('person_id').filter(function (v) { return v !== id; });
      params.delete('person_id');
      kept.forEach(function (v) { params.append('person_id', v); });
      var qs = params.toString();
      location.href = location.pathname + (qs ? '?' + qs : '');
    });
  });

  var box = document.querySelector('[data-flow-add]');
  if (!box) return;
  var input = box.querySelector('input'), results = box.querySelector('[data-flow-results]');
  var findUrl = input.dataset.flowFind, base = box.dataset.base;
  var timer = null, seq = 0;

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function addUrl(id) { return base + (base.indexOf('?') < 0 ? '?' : '&') + 'person_id=' + id; }

  function close() { results.hidden = true; results.innerHTML = ''; }

  function render(data) {
    results.innerHTML = '';
    var items = data.items || [];
    items.forEach(function (p) {
      var a = el('a', 'fp-item');
      a.href = addUrl(p.id);
      a.appendChild(el('b', '', p.name));
      var sub = [p.phone, p.email].filter(Boolean).join(' · ');
      if (sub) a.appendChild(el('small', '', sub));
      results.appendChild(a);
    });
    if (!items.length) results.appendChild(el('div', 'fp-none', 'No one found.'));
    results.hidden = false;
  }

  function ask() {
    var q = input.value.replace(/\s+/g, ' ').trim();
    if (q.length < 2) { close(); return; }
    var mine = ++seq;
    fetch(findUrl + (findUrl.indexOf('?') < 0 ? '?' : '&') + 'q=' + encodeURIComponent(q),
          { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (r) { return r.ok ? r.json() : { items: [] }; })
      .then(function (d) { if (mine === seq) render(d); })
      .catch(function () { if (mine === seq) close(); });
  }

  input.addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(ask, 250); });
  input.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') close();
    else if (e.key === 'Enter') {
      var first = results.querySelector('a.fp-item');
      if (first) { e.preventDefault(); location.href = first.href; }
    }
  });
  document.addEventListener('click', function (e) { if (!box.contains(e.target)) close(); });
})();
