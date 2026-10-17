/* Find a person: the header box on staff pages (E25).
   Asks the Sales CRM's /find as you type (after a short pause, from 2 characters) and lists up to 8 people with
   their enquiries as chips. Up/Down move, Enter on a highlighted person opens them, Enter otherwise opens
   Contacts filtered by what was typed, Esc closes. It only shows people: it never links or merges anyone. */
(function () {
  'use strict';
  var form = document.querySelector('form.find-person');
  if (!form) return;
  var input = form.querySelector('input[name=q]');
  var list = form.querySelector('.fp-list');
  var openBtn = form.querySelector('.fp-open');
  var findUrl = form.dataset.find, addUrl = form.dataset.add, allText = form.dataset.all;
  var timer = null, seq = 0, items = [], at = -1;

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function close() { list.hidden = true; list.innerHTML = ''; items = []; at = -1; }

  function looksLikeNumber(q) { return /^[+\d][\d\s().-]{5,}$/.test(q); }

  function addLink(q) {
    var key = q.indexOf('@') > 0 ? 'email' : looksLikeNumber(q) ? 'phone' : 'name';
    return addUrl + (addUrl.indexOf('?') < 0 ? '?' : '&') + key + '=' + encodeURIComponent(q);
  }

  function render(data, q) {
    list.innerHTML = '';
    items = [];
    at = -1;
    (data.items || []).forEach(function (it) {
      var a = el('a', 'fp-item');
      a.href = it.url;
      a.setAttribute('role', 'option');
      a.appendChild(el('b', '', it.name));
      if (it.kind === 'person') {
        var sub = [it.phone, it.email].filter(Boolean).join(' · ');
        if (sub) a.appendChild(el('small', '', sub));
        var chips = el('div');
        (it.chips || []).forEach(function (c) {
          var s = el('span', 'fp-chip ' + (c.state || ''), c.text);
          chips.appendChild(s);
        });
        a.appendChild(chips);
      } else {
        a.appendChild(el('small', '', (it.label || '') + (it.what ? ' · ' + it.what : '')));
      }
      list.appendChild(a);
      items.push(a);
    });
    if (!items.length) {
      var none = el('div', 'fp-none', 'No one found.');
      if (addUrl) {
        none.appendChild(document.createTextNode(' '));
        var add = el('a', '', '+ Add a lead');
        add.href = addLink(q);
        none.appendChild(add);
      }
      list.appendChild(none);
    } else {
      var all = el('a', 'fp-item', allText);
      var u = new URL(form.action, location.href);
      new FormData(form).forEach(function (v, k) { u.searchParams.set(k, k === 'q' ? q : v); });
      all.href = u.toString();
      list.appendChild(all);
    }
    list.hidden = false;
  }

  function ask() {
    var q = input.value.replace(/\s+/g, ' ').trim();
    if (q.length < 2) { close(); return; }
    var mine = ++seq;
    fetch(findUrl + (findUrl.indexOf('?') < 0 ? '?' : '&') + 'q=' + encodeURIComponent(q), { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (r) { return r.ok ? r.json() : { items: [] }; })
      .then(function (d) { if (mine === seq) render(d, q); })
      .catch(function () { if (mine === seq) close(); });
  }

  function mark(i) {
    items.forEach(function (n) { n.classList.remove('on'); });
    at = i;
    if (at >= 0 && items[at]) { items[at].classList.add('on'); items[at].scrollIntoView({ block: 'nearest' }); }
  }

  input.addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(ask, 250); });
  input.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { close(); input.blur(); form.classList.remove('open'); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); if (items.length) mark((at + 1) % items.length); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); if (items.length) mark((at - 1 + items.length) % items.length); }
    else if (e.key === 'Enter' && at >= 0 && items[at]) { e.preventDefault(); location.href = items[at].href; }
  });
  document.addEventListener('click', function (e) { if (!form.contains(e.target)) close(); });
  if (openBtn) openBtn.addEventListener('click', function () {
    form.classList.toggle('open');
    if (form.classList.contains('open')) input.focus(); else close();
  });
})();
