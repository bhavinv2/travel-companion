/* Contacts, the contact page, Add a lead's owner picker, Where leads come from's editors and the one-off
   WhatsApp imports (U7). Every word comes from the page or the server's answer; the server checks everything
   again, so this only draws, collects and asks. */
(function () {
  'use strict';
  var C = window.CRM || {};
  var toast = C.toast || function (m) { window.alert(m); };
  var csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';

  function q(sel, ctx) { return (ctx || document).querySelector(sel); }
  function qa(sel, ctx) { return Array.prototype.slice.call((ctx || document).querySelectorAll(sel)); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function getJSON(url) {
    return fetch(url, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (d) { d._ok = r.ok; return d; }); })
      .catch(function () { return { _ok: false, error: 'No connection. Please try again.' }; });
  }
  function postJSON(url, body) {
    return fetch(url, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf, Accept: 'application/json' },
      body: JSON.stringify(body || {})
    }).then(function (r) { return r.json().catch(function () { return {}; }).then(function (d) { d._ok = r.ok; d._status = r.status; return d; }); })
      .catch(function () { return { _ok: false, error: 'No connection. Please try again.' }; });
  }

  /* ------------------------------------------------------------ one person's tags: the contact page and the lead card */
  // The Sales tags are drawn by the page; the free ones load from WhatsApp here. The lead card beside the inbox is
  // drawn later: crm.js binds it with CRM_bindTags. A box already bound is left alone.
  function bindTags(tags) {
    if (tags.dataset.bound) return;
    tags.dataset.bound = '1';
    var url = tags.dataset.url, freeBox = q('[data-free]', tags), addBtn = q('[data-act="tag-add"]', tags), noteEl = q('[data-note]', tags);
    var state = { writes: false, canCreate: false, free: null };

    var draw = function () {
      freeBox.innerHTML = '';
      (state.free || []).forEach(function (name) {
        var chip = el('span', 'ui-chip tag');
        chip.appendChild(document.createTextNode(name + ' '));
        if (state.writes) {
          var x = el('button', '', '×');
          x.type = 'button';
          x.setAttribute('aria-label', 'Take off ' + name);
          x.addEventListener('click', function () { change({ remove: name }); });
          chip.appendChild(x);
        }
        freeBox.appendChild(chip);
      });
      addBtn.hidden = !(state.writes && state.free !== null);
    };
    var change = function (body) {
      postJSON(url, body).then(function (d) {
        if (!d._ok) { toast(d.error || 'Could not save.', true); return; }
        state.free = d.free || [];
        draw();
        toast('Saved');
      });
    };
    var pick = function (choices) {
      var name = window.prompt('Add a tag' + (choices.length ? ' (for example: ' + choices.slice(0, 5).map(function (c) { return c.name; }).join(', ') + ')' : ''));
      if (name && name.trim()) change({ add: name.trim() });
    };

    getJSON(url).then(function (d) {
      state.writes = !!d.writes; state.canCreate = !!d.can_create; state.free = d.free;
      noteEl.textContent = d.note || '';
      draw();
      if (d.free === null || d.free === undefined) freeBox.innerHTML = '';
    });

    addBtn.addEventListener('click', function () {
      getJSON(url + '?all=1').then(function (d) {
        var choices = d.choices || [];
        var dlg = C.choose ? C.choose('Add a tag', state.canCreate ? 'Pick one, or type a new name.' : 'Pick one.',
          choices.slice(0, 30).map(function (c) { return { label: c.name, value: c.name }; }).concat(
            state.canCreate ? [{ label: '+ New tag…', value: '__new' }] : [])) : null;
        if (!dlg) { pick(choices); return; }
        dlg.then(function (v) {
          if (!v) return;
          if (v === '__new') {
            var name = window.prompt('The new tag\'s name');
            if (name && name.trim()) change({ add: name.trim() });
          } else {
            change({ add: v });
          }
        });
      });
    });
  }
  qa('[data-tags]').forEach(bindTags);
  window.CRM_bindTags = bindTags;

  /* ------------------------------------------------------------ Erase this person */
  var erase = q('[data-erase-form]');
  if (erase) {
    var typed = q('[data-erase-name]', erase), btn = q('[data-erase-btn]', erase);
    var norm = function (s) { return String(s || '').replace(/\s+/g, ' ').trim().toLowerCase(); };
    typed.addEventListener('input', function () { btn.disabled = norm(typed.value) !== norm(typed.dataset.eraseName); });
  }

  /* ------------------------------------------------------------ Add a lead: choosing a person ticks "This person" */
  qa('[data-owner-pick]').forEach(function (sel) {
    sel.addEventListener('change', function () {
      var radio = sel.closest('label').querySelector('input[type=radio]');
      if (radio) radio.checked = true;
    });
  });

  /* ------------------------------------------------------------ Sources: the tag picker with its check */
  qa('[data-tag-picker]').forEach(function (box) {
    var hidden = q('[data-tags-value]', box), chips = q('[data-tag-chips]', box), input = q('[data-tag-new]', box);
    var err = q('[data-tag-error]', box), take = q('[data-tag-takeover]', box), checkUrl = box.dataset.check;
    var list = (hidden.value || '').split(',').map(function (t) { return t.trim().toLowerCase(); }).filter(Boolean);
    var sync = function () {
      hidden.value = list.join(', ');
      chips.innerHTML = '';
      list.forEach(function (t) {
        var chip = el('span', 'ui-chip tag', t + ' ');
        var x = el('button', '', '×');
        x.type = 'button';
        x.setAttribute('aria-label', 'Remove ' + t);
        x.addEventListener('click', function () { list = list.filter(function (y) { return y !== t; }); sync(); });
        chip.appendChild(x);
        chips.appendChild(chip);
      });
    };
    var add = function () {
      var t = input.value.trim().toLowerCase();
      if (!t || list.indexOf(t) >= 0) { input.value = ''; return; }
      if (list.length >= 8) { err.textContent = 'At most 8 tags.'; return; }
      getJSON(checkUrl + (checkUrl.indexOf('?') < 0 ? '?' : '&') + 'name=' + encodeURIComponent(t)).then(function (d) {
        if (d.error && !d.clash) { err.textContent = d.error; return; }
        err.textContent = d.error || '';
        if (d.clash) {
          // kept, but only saved when the take-over tick is ticked (the server refuses it otherwise)
          take.hidden = false;
          take.innerHTML = '';
          var label = el('label', 'check');
          var cb = el('input');
          cb.type = 'checkbox'; cb.name = 'take_over'; cb.value = t;
          label.appendChild(cb);
          label.appendChild(document.createTextNode(' ' + (d.take_over || 'Take over this tag')));
          take.appendChild(label);
        }
        list.push(t);
        input.value = '';
        sync();
      });
    };
    q('[data-tag-add]', box).addEventListener('click', add);
    input.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); add(); } });
    sync();
  });

  /* ------------------------------------------------------------ Inboxes to check and Marketing activities */
  var inbox = q('[data-inbox-form]');
  if (inbox) {
    var waKey = inbox.dataset.waKey, rows = q('[data-inbox-rows]', inbox), tpl = q('[data-inbox-template]', inbox);
    var n = qa('[data-inbox-row]', inbox).length;
    var wire = function (row) {
      var src = q('[data-inbox-source]', row), auto = q('[data-inbox-auto]', row);
      var sync = function () { auto.disabled = src.value !== waKey; if (auto.disabled) auto.checked = false; };
      src.addEventListener('change', sync);
      q('[data-inbox-remove]', row).addEventListener('click', function () { row.remove(); });
    };
    qa('[data-inbox-row]', inbox).forEach(wire);
    q('[data-inbox-add]', inbox).addEventListener('click', function () {
      n += 1;
      var holder = document.createElement('tbody');
      holder.innerHTML = tpl.innerHTML.replace(/__K__/g, 'n' + n);
      var row = holder.firstElementChild;
      rows.appendChild(row);
      wire(row);
      q('input[type=text]', row).focus();
    });
  }
  var acts = q('[data-act-form]');
  if (acts) {
    // each activity is a <tbody> of two lines (the activity, and its campaign details)
    var wireAct = function (row) { q('[data-act-remove]', row).addEventListener('click', function () { row.remove(); }); };
    qa('[data-act-row]', acts).forEach(wireAct);
    q('[data-act-add]', acts).addEventListener('click', function () {
      var all = qa('[data-act-row]', acts), last = all[all.length - 1];
      var row = last.cloneNode(true);
      qa('input', row).forEach(function (i) { i.value = ''; });
      qa('select[name="source"]', row).forEach(function (s) { s.value = ''; });
      last.parentNode.insertBefore(row, last.nextSibling);
      wireAct(row);
      q('input[type=text]', row).focus();
    });
  }

  /* ------------------------------------------------------------ From WhatsApp (one-off) */
  var WORDS = {
    contacts: [['brought_in', 'brought in'], ['linked', 'matched to a contact here'], ['already', 'already here'],
               ['no_number', 'had no number'], ['dnc', 'on the do-not-contact list'],
               ['ambiguous', 'could be two people here (skipped)'],
               ['other_contact', 'matched someone with another WhatsApp contact (skipped)']],
    notes: [['copied', 'notes copied'], ['already', 'already copied'], ['not_here', 'on contacts not here'],
            ['no_lead', 'on contacts with no enquiry yet (run it again later)']]
  };
  qa('[data-wa-import]').forEach(function (button) {
    var kind = button.dataset.waImport, card = button.closest('[data-wa-import-card]');
    var out = q('[data-wa-progress="' + kind + '"]', card) || q('[data-wa-progress]', card);
    var since = null, totals = {};
    var say = function (prefix) {
      var parts = (WORDS[kind] || []).filter(function (w) { return totals[w[0]]; })
        .map(function (w) { return totals[w[0]] + ' ' + w[1]; });
      out.textContent = prefix + (parts.length ? parts.join(', ') : 'nothing new');
    };
    var step = function () {
      postJSON(button.dataset.url, { since: since }).then(function (d) {
        if (d._status === 404 && d.missing) {
          card.innerHTML = '<h2>From WhatsApp (one-off)</h2><p class="muted">' + (d.error || 'Needs the WhatsApp CRM update') + '</p>';
          return;
        }
        if (!d._ok) {
          if (d.since) since = d.since;
          button.disabled = false;
          toast(d.error || 'Could not bring them in.', true);
          return;
        }
        Object.keys(d.counts || {}).forEach(function (k) { totals[k] = (totals[k] || 0) + d.counts[k]; });
        since = d.since;
        if (d.done) { button.disabled = false; say('Done: '); since = null; totals = {}; return; }
        say('Working… ');
        step();
      });
    };
    button.addEventListener('click', function () {
      button.disabled = true;
      out.textContent = 'Working…';
      step();
    });
  });
})();
