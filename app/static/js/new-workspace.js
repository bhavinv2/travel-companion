/* + New workspace (workspace/new.html): five steps on one page. What is picked lives here until Create, which sends
   it all as one JSON plan (workspace._create_from_plan checks it again and makes it in one go). A plan that came
   back with errors is put back on screen. Names and e-mails are only ever set as text, never as HTML. */
(function () {
  'use strict';
  var form = document.querySelector('[data-nw-form]');
  if (!form) return;
  var data = JSON.parse(document.getElementById('nw-data').textContent);
  var ROLES = data.roles;                      // [[key, label], ...]
  var state = { people: [], invites: [], teams: [] };
  var step = 1, LAST = 5;
  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  var $$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };
  var msg = $('[data-nw-msg]');

  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'text') n.textContent = attrs[k];
      else if (k === 'cls') n.className = attrs[k];
      else n.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (c) { if (c) n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  }
  function roleSelect(value, onChange, withNone) {
    var s = el('select', { cls: 'nw-role', 'aria-label': 'Role', 'data-no-search': '' });
    ROLES.forEach(function (r) {
      if (!withNone && r[0] === '') return;
      var o = el('option', { value: r[0], text: r[1] });
      if (r[0] === value) o.selected = true;
      s.appendChild(o);
    });
    s.addEventListener('change', function () { onChange(s.value); });
    return s;
  }
  function everyone() {                        // the people a team can hold: you, picked accounts, invitations
    return [{ ref: 'me', name: data.me.name + ' (you)' }]
      .concat(state.people.map(function (p) { return { ref: 'u' + p.id, name: p.name }; }))
      .concat(state.invites.map(function (i) { return { ref: 'e' + i.email, name: i.first_name || i.email }; }));
  }
  function roleName(key) { var r = ROLES.filter(function (x) { return x[0] === key; })[0]; return r ? r[1] : ''; }

  /* --------------------------------------------------------------- step 2: people */
  var tbody = $('[data-people]');
  function drawPeople() {
    $$('tr:not(.me)', tbody).forEach(function (tr) { tr.remove(); });
    state.people.forEach(function (p, n) {
      tbody.appendChild(el('tr', {}, [
        el('td', {}, [el('b', { text: p.name }), el('small', { text: p.email })]),
        el('td', {}, [roleSelect(p.role, function (v) { p.role = v; }, true)]),
        el('td', {}, [rmBtn(function () { state.people.splice(n, 1); forget('u' + p.id); drawPeople(); })])
      ]));
    });
    state.invites.forEach(function (i, n) {
      tbody.appendChild(el('tr', {}, [
        el('td', {}, [el('b', { text: i.first_name || i.email }), el('small', { text: i.email + ' · new, will be invited' })]),
        el('td', {}, [roleSelect(i.role, function (v) { i.role = v; }, true)]),
        el('td', {}, [rmBtn(function () { state.invites.splice(n, 1); forget('e' + i.email); drawPeople(); })])
      ]));
    });
    drawTeams();
  }
  function rmBtn(fn) {
    var b = el('button', { type: 'button', cls: 'nw-rm', 'aria-label': 'Remove', title: 'Remove', text: '×' });
    b.addEventListener('click', fn);
    return b;
  }
  function forget(ref) { state.teams.forEach(function (t) { t.members = t.members.filter(function (r) { return r !== ref; }); }); }

  var box = $('[data-pick]'), input = $('input', box), list = $('[data-pick-results]', box), timer = null, seq = 0;
  function closeList() { list.hidden = true; list.innerHTML = ''; }
  function ask() {
    var q = input.value.replace(/\s+/g, ' ').trim();
    if (q.length < 2) { closeList(); return; }
    var mine = ++seq;
    fetch(box.dataset.find + '&q=' + encodeURIComponent(q), { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (r) { return r.ok ? r.json() : { items: [] }; })
      .then(function (d) {
        if (mine !== seq) return;
        list.innerHTML = '';
        var taken = state.people.map(function (p) { return p.id; }).concat([data.me.id]);
        var items = (d.items || []).filter(function (p) { return taken.indexOf(p.id) < 0; });
        if (!items.length) list.appendChild(el('div', { cls: 'ws-pick-none', text: 'No one else found.' }));
        items.forEach(function (p) {
          var b = el('button', { type: 'button', cls: 'ws-pick-item' }, [
            el('b', { text: p.name }), el('small', { text: p.email }),
            el('span', { cls: 'ws-pill' + (p.staff ? ' team' : ''), text: p.staff ? 'Staff' : 'Traveller' })]);
          b.addEventListener('click', function () {
            state.people.push({ id: p.id, name: p.name, email: p.email, role: 'cs' });
            input.value = ''; closeList(); drawPeople(); input.focus();
          });
          list.appendChild(b);
        });
        list.hidden = false;
      }).catch(closeList);
  }
  input.addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(ask, 250); });
  input.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') { e.preventDefault(); var f = $('.ws-pick-item', list); if (f) f.click(); }
    else if (e.key === 'Escape') closeList();
  });
  document.addEventListener('click', function (e) { if (!box.contains(e.target)) closeList(); });

  $('[data-invite]').addEventListener('click', function () {
    var email = $('#nwEmail').value.trim().toLowerCase(), first = $('#nwFirst').value.trim();
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) { say('Enter the e-mail address of the person to invite.'); return; }
    if (state.invites.some(function (i) { return i.email === email; })
        || state.people.some(function (p) { return (p.email || '').toLowerCase() === email; })) { say('They are on the list already.'); return; }
    state.invites.push({ email: email, first_name: first, role: 'cs' });
    $('#nwEmail').value = ''; $('#nwFirst').value = ''; say('');
    drawPeople();
  });

  /* --------------------------------------------------------------- step 3: teams */
  var teamsBox = $('[data-teams]');
  function drawTeams() {
    teamsBox.innerHTML = '';
    var people = everyone();
    state.teams.forEach(function (t, n) {
      var nameIn = el('input', { type: 'text', maxlength: '80', placeholder: 'Team name, e.g. North', 'aria-label': 'Team name' });
      nameIn.value = t.name;
      nameIn.addEventListener('input', function () { t.name = nameIn.value; });
      var who = el('div', { cls: 'ws-checks' });
      people.forEach(function (p) {
        var c = el('input', { type: 'checkbox' });
        c.checked = t.members.indexOf(p.ref) > -1;
        c.addEventListener('change', function () {
          t.members = t.members.filter(function (r) { return r !== p.ref; });
          if (c.checked) t.members.push(p.ref);
        });
        who.appendChild(el('label', { cls: 'ws-check' }, [c, ' ' + p.name]));
      });
      teamsBox.appendChild(el('div', { cls: 'nw-team' }, [
        el('div', { cls: 'nw-team-head' }, [nameIn,
          el('label', { cls: 'nw-team-role' }, ['Gives its people ', roleSelect(t.role, function (v) { t.role = v; }, true)]),
          rmBtn(function () { state.teams.splice(n, 1); drawTeams(); })]),
        who]));
    });
    if (!state.teams.length) teamsBox.appendChild(el('p', { cls: 'ws-muted', text: 'No teams yet. Teams are optional; you can add them later in Teams.' }));
  }
  $('[data-add-team]').addEventListener('click', function () {
    state.teams.push({ name: '', role: '', members: [] });
    drawTeams();
    var all = $$('.nw-team input[type=text]', teamsBox);
    if (all.length) all[all.length - 1].focus();
  });

  /* --------------------------------------------------------------- the plan, the review, the steps */
  function plan() {
    return {
      name: $('[data-f=name]').value.trim(),
      description: $('[data-f=description]').value.trim(),
      modules: $$('[data-module]').filter(function (c) { return c.checked; }).map(function (c) { return c.value; }),
      phone: $('[data-f=phone]').value.trim(),
      send_links: $('[data-f=send_links]').checked,
      people: state.people.map(function (p) { return { id: p.id, role: p.role }; }),
      invites: state.invites.map(function (i) { return { email: i.email, first_name: i.first_name, role: i.role }; }),
      teams: state.teams.map(function (t) { return { name: t.name.trim(), role: t.role, members: t.members.slice() }; })
    };
  }
  function drawReview() {
    var p = plan(), r = $('[data-review]');
    r.innerHTML = '';
    var mods = $$('[data-module]').filter(function (c) { return c.checked; })
      .map(function (c) { return c.closest('label').querySelector('span').childNodes[0].textContent.trim(); });
    var rows = [
      ['Name', p.name + (p.description ? ' — ' + p.description : '')],
      ['Areas', mods.join(', ')],
      ['People', [data.me.name + ' (owner)'].concat(state.people.map(function (x) { return x.name + ' (' + roleName(x.role) + ')'; }))
        .concat(state.invites.map(function (x) { return (x.first_name || x.email) + ' (' + roleName(x.role) + ', invited)'; })).join(', ')],
      ['Teams', state.teams.length ? state.teams.map(function (t) {
        return (t.name || '(no name)') + ': ' + t.members.length + ' ' + (t.members.length === 1 ? 'person' : 'people');
      }).join(' · ') : 'None yet'],
      ['WhatsApp number', p.phone ? p.phone + ' · to be connected' : 'None yet']
    ];
    rows.forEach(function (row) { r.appendChild(el('div', { cls: 'nw-rv' }, [el('dt', { text: row[0] }), el('dd', { text: row[1] })])); });
  }
  function say(text) { msg.textContent = text || ''; }
  function check(n) {
    if (n === 1 && !$('[data-f=name]').value.trim()) { say('Give the workspace a name.'); $('[data-f=name]').focus(); return false; }
    if (n === 3 && state.teams.some(function (t) { return !t.name.trim(); })) { say('Every team needs a name, or remove it.'); return false; }
    say('');
    return true;
  }
  function go(n) {
    step = n;
    $$('[data-panel]').forEach(function (p) { p.hidden = +p.dataset.panel !== step; });
    $$('[data-nw-steps] li').forEach(function (li) {
      li.classList.toggle('on', +li.dataset.step === step);
      li.classList.toggle('done', +li.dataset.step < step);
    });
    $('[data-back]').hidden = step === 1;
    $('[data-next]').hidden = step === LAST;
    $('[data-create]').hidden = step !== LAST;
    if (step === LAST) drawReview();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }
  $('[data-next]').addEventListener('click', function () { if (check(step)) go(step + 1); });
  $('[data-back]').addEventListener('click', function () { go(step - 1); });
  $$('[data-nw-steps] li').forEach(function (li) {
    li.addEventListener('click', function () {
      var to = +li.dataset.step;
      for (var n = step; n < to; n++) { if (!check(n)) return; }
      go(to);
    });
  });
  form.addEventListener('submit', function (e) {
    if (!check(1) || !check(3)) { e.preventDefault(); return; }
    $('[data-nw-plan]').value = JSON.stringify(plan());
  });

  /* a plan that came back with errors goes back on screen */
  if (data.plan) {
    var p = data.plan;
    $('[data-f=name]').value = p.name || '';
    $('[data-f=description]').value = p.description || '';
    $('[data-f=phone]').value = p.phone || '';
    $('[data-f=send_links]').checked = p.send_links !== false;
    $$('[data-module]').forEach(function (c) { if (!c.disabled) c.checked = (p.modules || []).indexOf(c.value) > -1; });
    state.invites = (p.invites || []).map(function (i) { return { email: i.email, first_name: i.first_name || '', role: i.role || 'cs' }; });
    state.teams = (p.teams || []).map(function (t) { return { name: t.name || '', role: t.role || '', members: t.members || [] }; });
    state.people = (p.people || []).map(function (x) { return { id: x.id, name: x.name || 'Account #' + x.id, email: x.email || '', role: x.role || 'cs' }; });
  }
  drawPeople();
  go(1);
})();
