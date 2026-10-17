/* Visual Flow (E26): the "Tracking" card's add-person search and remove buttons. Adding or removing
   just changes the page's person_id query params and reloads -- the map itself is drawn server-side
   (services/crm_people.flow_data), so there is no client-side state to keep in sync. */
(function () {
  'use strict';
  var box = document.querySelector('[data-flow-add]');
  if (!box) return;
  var input = box.querySelector('input'), results = box.querySelector('[data-flow-results]');
  var findUrl = input.dataset.flowFind, base = box.dataset.base;
  var timer = null, seq = 0, items = [];

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function addUrl(id) { return base + (base.indexOf('?') < 0 ? '?' : '&') + 'person_id=' + id; }

  function close() { results.hidden = true; results.innerHTML = ''; items = []; }

  function render(data) {
    results.innerHTML = '';
    items = [];
    (data.items || []).forEach(function (p) {
      var a = el('a', 'fp-item');
      a.href = addUrl(p.id);
      a.appendChild(el('b', '', p.name));
      var sub = [p.phone, p.email].filter(Boolean).join(' · ');
      if (sub) a.appendChild(el('small', '', sub));
      results.appendChild(a);
      items.push(a);
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
  input.addEventListener('keydown', function (e) { if (e.key === 'Escape') close(); });
  document.addEventListener('click', function (e) { if (!box.contains(e.target)) close(); });

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
})();
