/* Set-up -> Pipelines: the switches, the product form, the new-pipeline wizard and the pipeline editor.

   Every word comes from the page (templates, data-* attributes and the #pe-data words); the server checks
   everything again, so this only copies, orders and collects. Nothing here is saved until Save changes. */
(function () {
  'use strict';
  var C = window.CRM;
  if (!C) return;
  var post = C.post, toast = C.toast, choose = C.choose, esc = C.esc, BASE = C.base || '/';

  function fmt(s) {
    var a = Array.prototype.slice.call(arguments, 1), i = 0;
    return String(s).replace(/%[ds]/g, function () { return a[i++]; });
  }
  function q(sel, ctx) { return (ctx || document).querySelector(sel); }
  function qa(sel, ctx) { return Array.prototype.slice.call((ctx || document).querySelectorAll(sel)); }
  function plural(n) { return +n === 1 ? '' : 's'; }
  function debounce(fn, ms) {
    var t;
    return function () { var a = arguments, self = this; clearTimeout(t); t = setTimeout(function () { fn.apply(self, a); }, ms); };
  }
  function getJSON(url) {
    return fetch(url, { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
      .then(function (r) { return r.json().catch(function () { return {}; }); })
      .catch(function () { return {}; });
  }

  /* -------------------------------------------------------------- switches that save at once */
  document.addEventListener('change', function (e) {
    var el = e.target;
    if (!el.matches || !el.matches('[data-act="pipe-active"], [data-act="product-offered"]')) return;
    var on = el.checked;
    post(el.dataset.url, { on: on }).then(function (d) {
      if (!d._ok) { el.checked = !on; toast(d.error || 'Could not save.', true); return; }
      var label = el.parentNode.querySelector('span');
      if (label && el.dataset.on) label.textContent = on ? el.dataset.on : el.dataset.off;
      toast(d.message || 'Saved');
    });
  });

  /* -------------------------------------------------------------- product code and tag checks */
  function example(code, name) {
    var w = String(name || '').match(/[A-Za-z0-9]+/g) || [];
    var last = w.length ? w[w.length - 1].toLowerCase() : 'renewals';
    if (last === code.toLowerCase()) last = '2';
    return (code + ' ' + last).slice(0, 30);
  }

  function bindName(input) {
    var isCode = input.hasAttribute('data-code-input');
    var scope = isCode ? input.closest('div') : input.closest('fieldset');
    if (!scope) return;
    var prev = q('[data-preview]', scope), err = q('[data-check-err]', scope), take = q('[data-take-over]', scope);
    var seq = 0;
    function productCode() {
      var form = input.closest('form'), sel = form && q('[data-wiz-product]', form);
      if (!sel) return '';
      if (sel.value === '__new') { var np = q('[name="np_code"]', form); return np ? np.value.trim().toUpperCase() : ''; }
      return sel.value;
    }
    function draw() {
      if (!prev) return;
      var v = input.value.trim();
      if (isCode) {
        var c = v.toUpperCase() || 'XX';
        prev.textContent = "appears as '" + c + "' and '" + c + ": New'";
      } else {
        var p = productCode() || 'XX';
        prev.textContent = v ? "appears as '" + p + "' and '" + v + ": New'" : '';
      }
    }
    var ask = debounce(function () {
      var v = input.value.trim(), mine = ++seq;
      if (!v) { if (err) err.textContent = ''; if (take) take.hidden = true; return; }
      var url = BASE + input.dataset.check + '?' + (isCode
        ? 'code=' + encodeURIComponent(v) + '&product_id=' + encodeURIComponent(input.dataset.product || '')
        : 'label=' + encodeURIComponent(v));
      getJSON(url).then(function (d) {
        if (mine !== seq) return;
        if (err) err.textContent = d.error || d.said || '';
        if (take) take.hidden = !d.clash;
        if (prev && d.preview && isCode) prev.textContent = d.preview;
      });
    }, 400);
    if (input.readOnly) return;
    input.addEventListener('input', function () { draw(); ask(); });
    draw();
  }
  qa('[data-code-input], [data-label-input]').forEach(bindName);

  /* -------------------------------------------------------------- the new-pipeline wizard */
  qa('[data-wizard]').forEach(function (form) {
    var taken = {};
    try { taken = JSON.parse(form.dataset.taken || '{}'); } catch (e) { taken = {}; }
    var words = form.dataset.takenWords || '';
    var product = q('[data-wiz-product]', form), newBox = q('[data-new-product]', form);
    var modes = qa('[name="tag_mode"]', form), takenNote = q('[data-tag-taken]', form), plain = q('[data-tag-product]', form);
    var nameInput = q('[name="name"]', form);
    function sync() {
      if (newBox) newBox.hidden = product.value !== '__new';
      var start = (q('[name="start"]:checked', form) || {}).value;
      var copy = q('[name="copy_from"]', form);
      if (copy) copy.disabled = start !== 'copy';
      var arrive = (q('[name="arrive"]:checked', form) || {}).value;
      var src = q('[name="source_id"]', form);
      if (src) src.disabled = arrive !== 'source';
      var t = product.value !== '__new' ? taken[product.value] : null;
      if (takenNote) {
        takenNote.hidden = !t;
        if (t) takenNote.textContent = fmt(words, t.pipeline, product.value, example(product.value, nameInput ? nameInput.value : ''));
      }
      if (plain) plain.hidden = !!t;
      modes.forEach(function (m) {
        if (m.value === 'product') m.disabled = !!t;
        if (t && m.value === 'own') m.checked = true;
      });
      qa('[data-label-input]', form).forEach(function (i) { i.dispatchEvent(new Event('input')); });
    }
    form.addEventListener('change', sync);
    if (nameInput) nameInput.addEventListener('input', sync);
    var np = q('[name="np_code"]', form);
    if (np) np.addEventListener('input', function () { qa('[data-label-input]', form).forEach(function (i) { i.dispatchEvent(new Event('input')); }); });
    sync();
  });

  /* -------------------------------------------------------------- the pipeline editor */
  var form = q('[data-pipe-editor]');
  if (!form) return;
  var dataEl = document.getElementById('pe-data');
  var data = JSON.parse(dataEl.textContent || '{}');
  var W = data.words || {};
  var stagesEl = q('[data-stages]', form);
  var drawer = q('[data-drawer]');
  var dirty = false, seq = 0;
  var ICONS = { whatsapp: 'fa-brands fa-whatsapp', call: 'fa-solid fa-phone', email: 'fa-solid fa-envelope', todo: 'fa-solid fa-list-check' };

  function newRef() { return 'n' + (++seq); }
  function setDirty() { dirty = true; }
  function clone(name) {
    var t = q('template[data-clone="' + name + '"]');
    return t.content.firstElementChild.cloneNode(true);
  }
  function stageItems() { return qa(':scope > li.pe-stage', stagesEl); }
  function stageName(li) { return (q('[data-k="name"]', li).value || '').trim() || W.new_stage; }
  function kOf(li, k) { return q('[data-k="' + k + '"]', li); }

  /* ---- errors beside the field */
  function clearErrors() {
    qa('[data-err]', form).forEach(function (x) { x.textContent = ''; });
    qa('.has-err', form).forEach(function (x) { x.classList.remove('has-err'); });
    qa('[data-d-err], [data-f-err]').forEach(function (x) { x.textContent = ''; });
  }
  function showErrors(errors) {
    var first = null;
    Object.keys(errors).forEach(function (key) {
      var slot = q('[data-err="' + key + '"]', form), msg = errors[key], mark = null;
      if (!slot) {
        var chip = q('[data-ref="' + key + '"]', form);
        if (chip && chip.matches('[data-field]')) { slot = q('[data-err="fields"]', form); mark = chip; }
        else slot = q('[data-err="_"]', form);
      }
      if (slot) slot.textContent = slot.textContent ? slot.textContent + ' ' + msg : msg;
      mark = mark || (slot && (slot.closest('.pe-step') || slot.closest('.pe-stage')));
      if (mark) mark.classList.add('has-err');
      first = first || slot;
    });
    if (first && first.scrollIntoView) first.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  /* ---- the dates a follow-up or a move can count from */
  var ownAtLoad = {};
  qa('button.pe-chip[data-field]', form).forEach(function (b) { var f = JSON.parse(b.dataset.field); ownAtLoad[f.key] = true; });
  function fieldChips() { return qa('button.pe-chip[data-field]', form); }
  function dateList() {
    var out = (data.dates || []).filter(function (d) { return !ownAtLoad[d.key]; });
    fieldChips().forEach(function (b) {
      var f = JSON.parse(b.dataset.field);
      if (f.type !== 'date') return;
      var key = f.id ? f.key : 'new:' + f.ref;
      out.push({ key: key, label: f.label, before: 'before ' + f.label, after: 'after ' + f.label, on: 'on ' + f.label });
    });
    return out;
  }
  function dateInfo(key) {
    var d = dateList().filter(function (x) { return x.key === key; })[0];
    return d || { key: key, label: key, before: 'before ' + key, after: 'after ' + key, on: 'on ' + key };
  }
  function reasons() { return qa('[data-reasons] [data-reason]', form).map(function (x) { return x.dataset.reason; }); }

  function refreshTargets() {
    var items = stageItems(), dates = dateList(), rs = reasons();
    items.forEach(function (li) {
      var to = kOf(li, 'auto_to'), keep = to.value;
      to.innerHTML = items.filter(function (o) { return o !== li; }).map(function (o) {
        return '<option value="' + esc(o.dataset.ref) + '">' + esc(stageName(o)) + '</option>';
      }).join('');
      if (keep) to.value = keep;
      var rsel = kOf(li, 'auto_reason'), rkeep = rsel.value;
      rsel.innerHTML = '<option value="">' + esc(W.reason_none) + '</option>' + rs.map(function (r) {
        return '<option value="' + esc(r) + '">' + esc(r) + '</option>';
      }).join('');
      if (rkeep && rs.indexOf(rkeep) < 0) rsel.insertAdjacentHTML('beforeend', '<option value="' + esc(rkeep) + '">' + esc(rkeep) + '</option>');
      rsel.value = rkeep;
      var ak = kOf(li, 'auto_kind'), akeep = ak.value;
      qa('option', ak).forEach(function (o) { if (o.value.indexOf('after_date:') === 0) o.remove(); });
      dates.forEach(function (d) { ak.insertAdjacentHTML('beforeend', '<option value="after_date:' + esc(d.key) + '">after ' + esc(d.label) + '</option>'); });
      if (akeep && !qa('option', ak).some(function (o) { return o.value === akeep; })) {
        ak.insertAdjacentHTML('beforeend', '<option value="' + esc(akeep) + '">' + esc(akeep.replace('after_date:', 'after ')) + '</option>');
      }
      ak.value = akeep;
    });
  }
  function renumber() {
    stageItems().forEach(function (li, i) {
      q('.pe-stage-head .pe-n', li).textContent = i + 1;
      qa('li.pe-step', li).forEach(function (r, j) { q('.pe-n', r).textContent = j + 1; });
    });
  }

  /* ---- the stages */
  function setRef(li, ref, cls) {
    li.dataset.ref = ref;
    qa('[data-err]', li).forEach(function (x) {
      if (cls === 'stage' && x.closest('li.pe-step')) return;
      x.dataset.err = ref + x.dataset.err;
    });
  }
  function syncStage(li) {
    var means = kOf(li, 'means').value;
    li.className = li.className.replace(/\bm-\w+/g, '') + ' m-' + means;
    var ak = kOf(li, 'auto_kind').value;
    q('[data-auto-rest]', li).hidden = !ak;
    var pick = kOf(li, 'button_pick').value, label = kOf(li, 'button_label');
    label.hidden = pick !== '__other';
    q('[data-code-wrap]', li).hidden = !(pick && (pick !== '__other' || label.value.trim()));
  }
  function addStage() {
    var li = clone('stage');
    setRef(li, newRef(), 'stage');
    // new stages go before the finish lines (Won / Lost), like the old form
    var items = stageItems(), at = null;
    for (var i = 0; i < items.length; i++) {
      var m = kOf(items[i], 'means').value;
      if (m === 'won' || m === 'lost') { at = items[i]; break; }
    }
    stagesEl.insertBefore(li, at);
    syncStage(li); renumber(); refreshTargets(); setDirty();
    kOf(li, 'name').focus();
  }
  function moveSibling(li, dir) {
    var other = dir < 0 ? li.previousElementSibling : li.nextElementSibling;
    if (!other) return;
    if (dir < 0) li.parentNode.insertBefore(li, other); else li.parentNode.insertBefore(other, li);
    renumber(); refreshTargets(); setDirty();
  }
  function removeStage(li) {
    var open = +li.dataset.open || 0, closed = +li.dataset.closed || 0, msg = null;
    if (open > 0) msg = fmt(W.remove_open, open, plural(open));
    else if (closed > 0) msg = fmt(W.remove_closed, closed, plural(closed));
    else {
      var users = stageItems().filter(function (o) {
        return o !== li && kOf(o, 'auto_kind').value && kOf(o, 'auto_to').value === li.dataset.ref;
      });
      if (users.length) msg = fmt(W.remove_used, stageName(users[0]));
    }
    if (msg) {
      var slot = q('[data-err$=".name"]', li);
      if (slot) slot.textContent = msg;
      toast(msg, true);
      return;
    }
    li.remove(); renumber(); refreshTargets(); setDirty();
  }

  /* drag a stage by its grip */
  var dragged = null;
  stagesEl.addEventListener('dragstart', function (e) {
    var g = e.target.closest && e.target.closest('.pe-grip');
    if (!g) return;
    dragged = g.closest('li.pe-stage');
    dragged.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
    try { e.dataTransfer.setData('text/plain', 'stage'); e.dataTransfer.setDragImage(dragged, 20, 20); } catch (x) { /* old browsers */ }
  });
  stagesEl.addEventListener('dragover', function (e) {
    if (!dragged) return;
    e.preventDefault();
    var over = e.target.closest('li.pe-stage');
    if (!over || over === dragged) return;
    var r = over.getBoundingClientRect();
    if (e.clientY < r.top + r.height / 2) stagesEl.insertBefore(dragged, over);
    else stagesEl.insertBefore(dragged, over.nextElementSibling);
  });
  stagesEl.addEventListener('dragend', function () {
    if (!dragged) return;
    dragged.classList.remove('dragging');
    dragged = null;
    renumber(); refreshTargets(); setDirty();
  });
  stagesEl.addEventListener('drop', function (e) { e.preventDefault(); });

  stagesEl.addEventListener('change', function (e) {
    var el = e.target, li = el.closest('li.pe-stage');
    if (!li || el.closest('li.pe-step')) return;
    var k = el.dataset.k;
    if (k === 'on_reply' && el.checked) {
      stageItems().forEach(function (o) { if (o !== li) kOf(o, 'on_reply').checked = false; });
    }
    if (k === 'button_pick') kOf(li, 'button_code').value = '';
    if (k === 'name') refreshTargets();
    syncStage(li);
  });
  stagesEl.addEventListener('input', function (e) {
    var li = e.target.closest('li.pe-stage');
    if (li && e.target.dataset.k === 'button_label') syncStage(li);
  });

  /* ---- reasons and details asked */
  function addReason() {
    var inp = q('[data-reason-new]', form), v = inp.value.trim().slice(0, 80);
    if (!v) return;
    if (reasons().some(function (r) { return r.toLowerCase() === v.toLowerCase(); })) { inp.value = ''; return; }
    var chip = document.createElement('span');
    chip.className = 'pe-chip';
    chip.dataset.reason = v;
    chip.innerHTML = esc(v) + ' <button type="button" data-act="reason-remove" aria-label="Remove ' + esc(v) + '">×</button>';
    q('[data-reasons]', form).appendChild(chip);
    inp.value = '';
    refreshTargets(); setDirty();
  }
  q('[data-reason-new]', form).addEventListener('keydown', function (e) {
    if (e.key === 'Enter') { e.preventDefault(); addReason(); }
  });

  var panel = q('[data-field-panel]', form), editingChip = null, editingNew = null;
  function fq(n) { return q('[data-f="' + n + '"]', panel); }
  function fieldChipText(f) { return f.label + ' · ' + (data.field_types[f.type] || f.type); }
  function openField(chip) {
    var f = chip ? JSON.parse(chip.dataset.field)
      : { id: null, ref: newRef(), label: '', type: 'text', options: [], on_card: false, on_add: false, required: false };
    editingChip = chip; editingNew = chip ? null : f;
    panel.dataset.field = JSON.stringify(f);
    fq('label').value = f.label; fq('type').value = f.type; fq('type').disabled = !!f.id;
    fq('options').value = (f.options || []).join('\n');
    fq('on_card').checked = !!f.on_card; fq('on_add').checked = !!f.on_add; fq('required').checked = !!f.required;
    syncField();
    panel.hidden = false;
    fq('label').focus();
  }
  function syncField() {
    q('[data-f-choices]', panel).hidden = fq('type').value !== 'choice';
    fq('required').disabled = !fq('on_add').checked;
    if (!fq('on_add').checked) fq('required').checked = false;
  }
  function readField() {
    var f = JSON.parse(panel.dataset.field);
    f.label = fq('label').value.trim(); f.type = fq('type').value;
    f.options = f.type === 'choice' ? fq('options').value.split('\n').map(function (x) { return x.trim(); }).filter(Boolean) : [];
    f.on_card = fq('on_card').checked; f.on_add = fq('on_add').checked; f.required = fq('required').checked;
    return f;
  }
  function closeField() { panel.hidden = true; editingChip = editingNew = null; q('[data-f-err]', panel).textContent = ''; }

  /* ---- follow-ups */
  function whenText(w) {
    if (!w || w.type === 'now') return W.now;
    if (w.type === 'after') {
      var v = +w.value || 0;
      return w.unit === 'days' ? fmt(W.after_days, v, plural(v)) : fmt(W.after_hours, v, plural(v));
    }
    var d = dateInfo(w.field), n = +w.value || 0;
    return n === 0 ? d.on : n + ' day' + plural(n) + ' ' + (w.sign === 'before' ? d.before : d.after);
  }
  function summary(j) {
    var bits = [data.channel_short[j.channel] || j.channel, '“' + (j.title || W.unnamed) + '”', whenText(j.when)];
    if (j.channel === 'whatsapp') {
      if (j.auto) bits.push(W.by_itself);
      var t = j.wa_template ? data.templates[j.wa_template] : null;
      bits.push(t && t.status === 'APPROVED' ? '✓ ' + W.approved : (t ? t.status_text : W.no_template));
    }
    return bits.join(' · ');
  }
  function paintRow(row) {
    var j = JSON.parse(row.dataset.fu);
    q('[data-sum]', row).textContent = summary(j);
    q('.pe-ch', row).innerHTML = '<i class="' + (ICONS[j.channel] || ICONS.todo) + '" aria-hidden="true"></i>';
  }
  function addStep(stageLi) {
    var means = kOf(stageLi, 'means').value;
    var kind = { 'new': 'first', won: 'care', lost: 'after_lost' }[means] || 'reminder';
    var j = { id: null, ref: newRef(), channel: 'whatsapp', title: '', kind: kind, code: '', when: { type: 'now' },
              body: '', wa_template: null, wa_params: null, auto: false };
    var row = clone('step');
    row.dataset.ref = j.ref; row.dataset.fu = JSON.stringify(j); row.dataset.saved = ''; row.dataset.fresh = '1';
    q('[data-err]', row).dataset.err = j.ref;
    q('[data-steps]', stageLi).appendChild(row);
    paintRow(row); renumber();
    openDrawer(row);
  }

  /* ---- the drawer */
  var curRow = null, curJ = null, workTpl = null, workParams = null, lastOn = null;
  function d(n) { return q('[data-d="' + n + '"]', drawer); }
  function radio(n) { var r = q('[data-d="' + n + '"]:checked', drawer); return r ? r.value : ''; }
  function setRadio(n, v) { qa('[data-d="' + n + '"]', drawer).forEach(function (r) { r.checked = r.value === v; }); }

  function fillDates(selected) {
    var sel = d('date_field');
    sel.innerHTML = dateList().map(function (x) { return '<option value="' + esc(x.key) + '">' + esc(x.label) + '</option>'; }).join('');
    if (selected && !qa('option', sel).some(function (o) { return o.value === selected; })) {
      sel.insertAdjacentHTML('beforeend', '<option value="' + esc(selected) + '">' + esc(selected) + '</option>');
    }
    if (selected) sel.value = selected;
  }
  function bodyTokens() {
    var out = [], re = /\{([a-z_]+)\}/g, m;
    while ((m = re.exec(d('body').value))) {
      if ((data.variable_tokens || []).indexOf(m[1]) >= 0 && out.indexOf(m[1]) < 0) out.push(m[1]);
    }
    return out;
  }
  function wordsHtml(text) {
    return esc(text).replace(/\{\{(\d+)\}\}/g, '<span class="ui-chip fill">$1</span>');
  }
  function renderFills(tpl) {
    var holder = q('[data-tpl-fills]', drawer);
    var n = tpl && tpl.variables != null ? tpl.variables : ((tpl && tpl.body ? tpl.body.match(/\{\{\d+\}\}/g) || [] : bodyTokens()).length);
    var shown = workParams || bodyTokens();
    holder.innerHTML = '';
    for (var i = 0; i < n; i++) {
      var label = document.createElement('label');
      var opts = '<option value="">' + esc(W.choose) + '</option>' + data.fills.map(function (f) {
        return '<option value="' + esc(f.key) + '">' + esc(f.label) + '</option>';
      }).join('');
      label.innerHTML = esc(fmt(W.fill_n, i + 1)) + ' = <select data-fill="' + i + '">' + opts + '</select>';
      q('select', label).value = shown[i] || '';
      holder.appendChild(label);
    }
  }
  function mode() {
    var ch = radio('channel'), wa = ch === 'whatsapp';
    qa('[data-wa-only]', drawer).forEach(function (x) { x.hidden = !wa; });
    q('[data-words-label]', drawer).textContent = W.words_label[ch] || W.words_label.whatsapp;
    var tpl = wa && workTpl ? data.templates[workTpl] : null;
    var on = wa && !!workTpl;
    var words = q('[data-words]', drawer);
    q('[data-tpl-on]', drawer).hidden = !on;
    qa('[data-no-tpl]', drawer).forEach(function (x) { x.hidden = on || !wa; });
    if (on) {
      var st = q('[data-tpl-status]', drawer);
      st.textContent = tpl ? tpl.status_text : W.no_template;
      st.className = 'tpl-st ' + (tpl ? tpl.css : 'tpl-missing');
      q('[data-tpl-words]', drawer).innerHTML = wordsHtml(tpl ? tpl.body : d('body').value.replace(/\{([a-z_]+)\}/g, function (all, t) {
        var i = bodyTokens().indexOf(t); return i < 0 ? all : '{{' + (i + 1) + '}}';
      }));
      renderFills(tpl);
      q('[data-tpl-promo]', drawer).hidden = !(tpl && tpl.category === 'MARKETING');
      q('[data-tpl-wait]', drawer).hidden = !!(tpl && tpl.approved);
      var open = q('[data-tpl-open]', drawer);
      open.hidden = !(data.urls.templates && tpl);
      if (!open.hidden) open.href = data.urls.templates.replace('__NAME__', encodeURIComponent(workTpl));
      q('[data-words-label]', drawer).textContent = W.open_chat_words;
    }
    if (on !== lastOn) { words.open = !on; lastOn = on; }       // folded away once, never while somebody types
    q('[data-pick-label]', drawer).textContent = workTpl ? W.use_another : W.use_one;
    var le = q('[data-lib-err]', drawer);
    le.hidden = !data.lib_error; le.textContent = data.lib_error ? W.lib_error : '';
    // the template picker
    var pick = d('tpl_pick'), names = data.approved.slice();
    if (workTpl && names.indexOf(workTpl) < 0) names.unshift(workTpl);
    pick.innerHTML = '<option value="">' + esc(W.no_tpl_option) + '</option>' + names.map(function (n) {
      var t = data.templates[n];
      return '<option value="' + esc(n) + '">' + esc(t ? t.label : n.replace(/_/g, ' ')) + '</option>';
    }).join('');
    pick.value = workTpl || '';
    // goes by itself: only for WhatsApp with an approved template (or one already on, unchanged)
    var auto = d('auto'), allowed = wa && ((tpl && tpl.approved) || (curJ.auto && workTpl && workTpl === curJ.wa_template));
    auto.disabled = !allowed;
    if (!allowed) auto.checked = false;
    // make it a template
    var make = q('[data-act="make-template"]', drawer), hint = q('[data-make-hint]', drawer);
    var saved = sameAsSaved();
    make.disabled = !(curJ.id && saved && data.writes_on);
    hint.textContent = !data.writes_on ? W.not_connected : (!curJ.id || !saved ? W.save_first : '');
    q('[data-tpl-name]', drawer).textContent = workTpl ? workTpl : '';
  }
  function sameAsSaved() {
    var s;
    try { s = JSON.parse(curRow.dataset.saved || '{}'); } catch (e) { s = {}; }
    var j = collectDrawer();
    function whenKey(w) { w = w || { type: 'now' }; return [w.type, +w.value || 0, w.unit || '', w.sign || '', w.field || ''].join('|'); }
    return ['title', 'channel', 'kind', 'body'].every(function (k) { return (j[k] || '') === (s[k] || ''); })
      && whenKey(j.when) === whenKey(s.when) && (j.wa_template || null) === (s.wa_template || null);
  }
  function collectDrawer() {
    var j = Object.assign({}, curJ), wt = radio('when_type');
    j.title = d('title').value.trim(); j.channel = radio('channel'); j.kind = d('kind').value;
    j.code = d('code').value.trim(); j.body = d('body').value;
    j.when = wt === 'after' ? { type: 'after', value: d('after_value').value, unit: d('after_unit').value }
      : wt === 'date' ? { type: 'date', value: d('date_value').value, sign: d('date_sign').value, field: d('date_field').value }
      : { type: 'now' };
    if (j.when.value !== undefined && j.when.value !== '') j.when.value = +j.when.value;
    var wa = j.channel === 'whatsapp';
    j.wa_template = wa ? workTpl : null;
    j.wa_params = wa && workTpl ? workParams : null;
    j.auto = wa && d('auto').checked;
    return j;
  }
  function openDrawer(row) {
    curRow = row; curJ = JSON.parse(row.dataset.fu); lastOn = null;
    workTpl = curJ.wa_template || null; workParams = curJ.wa_params ? curJ.wa_params.slice() : null;
    d('title').value = curJ.title || ''; setRadio('channel', curJ.channel); d('kind').value = curJ.kind || 'other';
    d('code').value = curJ.code || ''; d('body').value = curJ.body || ''; d('auto').checked = !!curJ.auto;
    var w = curJ.when || { type: 'now' };
    setRadio('when_type', w.type);
    d('after_value').value = w.type === 'after' ? w.value : ''; d('after_unit').value = w.unit || 'hours';
    d('date_value').value = w.type === 'date' ? w.value : ''; d('date_sign').value = w.sign || 'before';
    fillDates(w.field);
    q('[data-d-err]', drawer).textContent = '';
    drawer.hidden = false;
    mode();
    d('title').focus();
  }
  function closeDrawer(cancel) {
    if (cancel && curRow && curRow.dataset.fresh === '1') { curRow.remove(); renumber(); }
    drawer.hidden = true; curRow = curJ = null;
  }
  drawer.addEventListener('change', function (e) {
    var el = e.target;
    if (el.matches('[data-d="channel"]')) { mode(); return; }
    if (el.matches('[data-d="tpl_pick"]')) {
      workTpl = el.value || null;
      workParams = workTpl && workTpl === curJ.wa_template ? (curJ.wa_params ? curJ.wa_params.slice() : null) : null;
      if (workTpl && workTpl !== curJ.wa_template) {
        var t = data.templates[workTpl], n = t && t.variables != null ? t.variables : 1;
        workParams = ['name'];
        for (var i = 1; i < n; i++) workParams.push('');
      }
      mode();
      return;
    }
    if (el.matches('[data-fill]')) {
      var vals = qa('[data-fill]', drawer).map(function (s) { return s.value; });
      workParams = vals;
      return;
    }
    if (el.matches('[data-d="when_type"]')) return;
    if (el.matches('[data-d="body"], [data-d="title"], [data-d="kind"]')) mode();
  });
  drawer.addEventListener('input', function (e) {
    if (e.target.matches('[data-d="body"], [data-d="title"]')) mode();
    if (e.target.matches('[data-d="after_value"], [data-d="after_unit"]')) setRadio('when_type', 'after');
    if (e.target.matches('[data-d="date_value"], [data-d="date_sign"], [data-d="date_field"]')) setRadio('when_type', 'date');
  });
  drawer.addEventListener('change', function (e) {
    if (e.target.matches('[data-d="after_unit"]')) setRadio('when_type', 'after');
    if (e.target.matches('[data-d="date_sign"], [data-d="date_field"]')) setRadio('when_type', 'date');
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && !drawer.hidden && !document.querySelector('dialog[open]')) closeDrawer(true);
  });

  /* ---- "Make it a WhatsApp template" */
  function makeTemplate(btn) {
    var id = curJ.id;
    btn.disabled = true;
    post(data.urls.draft, { step_id: id, stamp: data.stamp }).then(function (r) {
      if (!r._ok) {
        q('[data-d-err]', drawer).textContent = r.error || '';
        toast(r.error || 'Could not make it.', true);
        mode();
        return;
      }
      var params = r.params && r.params.length ? r.params : null;
      data.templates[r.name] = { status: 'DRAFT', status_text: r.status_text, css: r.css, body: r.body, variables: r.variables,
                                 category: r.category, label: curJ.title || r.name, approved: false };
      Object.keys(r.steps || {}).forEach(function (sid) {
        var row = q('li.pe-step[data-id="' + sid + '"]', form);
        if (!row) return;
        var j = JSON.parse(row.dataset.fu), s = JSON.parse(row.dataset.saved || '{}');
        j.wa_template = r.steps[sid]; j.wa_params = params;
        s.wa_template = r.steps[sid]; s.wa_params = params;
        row.dataset.fu = JSON.stringify(j); row.dataset.saved = JSON.stringify(s);
        paintRow(row);
      });
      curJ.wa_template = r.name; curJ.wa_params = params; workTpl = r.name; workParams = params ? params.slice() : null;
      data.stamp = r.stamp;
      mode();
      toast(r.message);
    });
  }

  /* ---- Save changes */
  function collect(moveLeads) {
    var h = function (n) { return q('[data-h="' + n + '"]', form); };
    var out = {
      stamp: data.stamp, name: h('name').value, is_active: h('is_active').checked, product: h('product').value,
      catch_all: h('catch_all').checked, reasons: reasons(),
      fields: fieldChips().map(function (b) { return JSON.parse(b.dataset.field); }),
      stages: stageItems().map(function (li) {
        var ak = kOf(li, 'auto_kind').value, kind = ak, field = null;
        if (ak.indexOf('after_date:') === 0) { kind = 'after_date'; field = ak.slice(11); }
        var pick = kOf(li, 'button_pick').value;
        var label = pick === '__other' ? kOf(li, 'button_label').value.trim() : pick;
        return {
          id: li.dataset.id ? +li.dataset.id : null, ref: li.dataset.ref, name: kOf(li, 'name').value.trim(),
          means: kOf(li, 'means').value, on_reply: kOf(li, 'on_reply').checked, sla_hours: kOf(li, 'sla_hours').value.trim(),
          auto: kind ? { kind: kind, field: field, days: kOf(li, 'auto_days').value, to: kOf(li, 'auto_to').value,
                         reason: kOf(li, 'auto_reason').value } : {},
          button: { label: label, code: label ? kOf(li, 'button_code').value.trim() : '' },
          steps: qa('li.pe-step', li).map(function (r) { return JSON.parse(r.dataset.fu); })
        };
      })
    };
    if (moveLeads !== undefined) out.move_leads = moveLeads;
    return out;
  }
  function save(moveLeads) {
    clearErrors();
    var btn = q('[data-act="save"]', form), prod = q('[data-h="product"]', form).value;
    if (prod !== data.product && data.product_leads > 0 && moveLeads === undefined) {
      choose(fmt(W.move_q, data.product_leads, data.products[prod]),
             fmt(W.move_line, data.product.toLowerCase(), prod.toLowerCase()),
             [{ label: W.move_yes, value: true }, { label: W.move_no, value: false }]).then(function (v) {
        if (v === null) return;
        save(v);
      });
      return;
    }
    btn.disabled = true;
    post(data.urls.save, collect(moveLeads)).then(function (r) {
      btn.disabled = false;
      if (r._ok) {
        dirty = false;
        toast(r.message || 'Saved');
        setTimeout(function () { location.reload(); }, 900);
        return;
      }
      if (r.errors) { showErrors(r.errors); toast(r.error || W.fix, true); return; }
      var top = q('[data-err="_"]', form);
      if (top) top.textContent = r.error || '';
      toast(r.error || W.fix, true);
    });
  }

  /* ---- the tag dialog */
  function tagDialog() {
    var dlg = document.getElementById('crm-dialog'), box = q('.in', dlg);
    box.innerHTML = '';
    box.appendChild(q('template[data-clone="tag-dialog"]').content.cloneNode(true));
    var modes = qa('[name="tag-mode"]', box), label = q('[data-tag-label]', box), take = q('[data-tag-take]', box);
    var go = q('[data-tag-go]', box), err = q('[data-tag-err]', box);
    var own = data.tag_mode === 'own';
    modes.forEach(function (m) { m.checked = m.value === (own ? 'own' : 'product'); });
    label.value = own ? data.tag_label : '';
    function mode() { return (modes.filter(function (m) { return m.checked; })[0] || {}).value || 'product'; }
    var seq = 0;
    var ask = debounce(function () {
      var mine = ++seq, m = mode();
      getJSON(BASE + data.urls.tag + '?mode=' + m + '&label=' + encodeURIComponent(label.value.trim())).then(function (r) {
        if (mine !== seq) return;
        q('[data-tag-preview]', box).textContent = r.preview || '';
        q('[data-tag-said]', box).textContent = r.said || '';
        err.textContent = r.error || r.clash_said || (r.same ? W.tag_same : '');
        take.hidden = !r.clash;
        go.disabled = !!r.error || !!r.same;
      });
    }, 300);
    box.oninput = ask;                 // the dialog box is reused: one listener, not one per opening
    box.onchange = ask;
    q('[data-close]', box).addEventListener('click', function () { dlg.close(); });
    go.addEventListener('click', function () {
      var m = mode(), l = label.value.trim();
      if (m === 'own' && !l) { err.textContent = W.tag_none; return; }
      go.disabled = true;
      post(data.urls.tag, { mode: m, label: l, take_over: !!q('input', take).checked && !take.hidden, stamp: data.stamp }).then(function (r) {
        go.disabled = false;
        if (!r._ok) { err.textContent = r.error || ''; take.hidden = !r.clash; return; }
        q('[data-tag-text]', form).textContent = r.tag_text;
        data.stamp = r.stamp; data.tag_mode = m; data.tag_label = m === 'own' ? l : '';
        toast(r.message || W.tag_changed);
        dlg.close();
      });
    });
    ask();
    dlg.showModal();
  }

  /* ---- one click handler for the editor */
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-act]');
    if (!b) return;
    var act = b.dataset.act, stageLi = b.closest('li.pe-stage'), row = b.closest('li.pe-step');
    if (!form.contains(b) && !drawer.contains(b)) return;
    switch (act) {
      case 'save': save(); break;
      case 'tag': tagDialog(); break;
      case 'add-stage': addStage(); break;
      case 'stage-up': moveSibling(stageLi, -1); break;
      case 'stage-down': moveSibling(stageLi, 1); break;
      case 'stage-remove': removeStage(stageLi); break;
      case 'add-step': addStep(stageLi); break;
      case 'step-up': moveSibling(row, -1); break;
      case 'step-down': moveSibling(row, 1); break;
      case 'step-edit': openDrawer(row); break;
      case 'reason-add': addReason(); break;
      case 'reason-remove': b.closest('.pe-chip').remove(); refreshTargets(); setDirty(); break;
      case 'field-add': openField(null); break;
      case 'field-cancel': closeField(); break;
      case 'field-remove':
        if (editingChip) editingChip.remove();
        closeField(); refreshTargets(); setDirty();
        break;
      case 'field-done': {
        var f = readField();
        if (!f.label) { q('[data-f-err]', panel).textContent = W.field_label || ''; break; }
        if (editingChip) {
          editingChip.dataset.field = JSON.stringify(f); editingChip.textContent = fieldChipText(f);
        } else {
          var chip = document.createElement('button');
          chip.type = 'button'; chip.className = 'pe-chip'; chip.dataset.ref = f.ref;
          chip.dataset.field = JSON.stringify(f); chip.textContent = fieldChipText(f);
          q('[data-fields]', form).appendChild(chip);
        }
        closeField(); refreshTargets(); setDirty();
        break;
      }
      case 'drawer-cancel': closeDrawer(true); break;
      case 'drawer-done':
        curRow.dataset.fu = JSON.stringify(collectDrawer());
        delete curRow.dataset.fresh;
        paintRow(curRow); setDirty(); closeDrawer(false);
        break;
      case 'make-template': makeTemplate(b); break;
      case 'step-remove':
        choose(W.remove_step_q, W.remove_step_line, [{ label: W.remove, value: 1 }]).then(function (v) {
          if (!v) return;
          curRow.remove(); renumber(); setDirty(); closeDrawer(false);
        });
        break;
      default: break;
    }
  });
  // a detail chip opens its panel
  form.addEventListener('click', function (e) {
    var chip = e.target.closest('button.pe-chip[data-field]');
    if (chip) openField(chip);
  });
  panel.addEventListener('input', syncField);
  panel.addEventListener('change', syncField);
  var swText = q('[data-switch-text]', form);
  form.addEventListener('change', function (e) {
    if (e.target.matches('[data-h="is_active"]') && swText) swText.textContent = e.target.checked ? swText.dataset.on : swText.dataset.off;
  });

  /* ---- leaving with unsaved changes */
  form.addEventListener('input', setDirty);
  form.addEventListener('change', setDirty);
  form.addEventListener('submit', function (e) { e.preventDefault(); });
  window.addEventListener('beforeunload', function (e) {
    if (dirty) { e.preventDefault(); e.returnValue = ''; }
  });
  document.addEventListener('click', function (e) {
    if (!dirty) return;
    var a = e.target.closest('a[href]');
    if (!a || drawer.contains(a) || a.target === '_blank' || /^(#|javascript:)/.test(a.getAttribute('href') || '')) return;
    e.preventDefault();
    choose(form.dataset.leaveTitle, form.dataset.leaveLine, [{ label: W.leave, value: 'go' }]).then(function (v) {
      if (v !== 'go') return;
      dirty = false;
      location.href = a.href;
    });
  });

  /* ---- start */
  qa('li.pe-stage', stagesEl).forEach(syncStage);
  refreshTargets();
  if (data.open_step) {
    var target = q('li.pe-step[data-id="' + data.open_step + '"]', form);
    if (target) { target.scrollIntoView({ block: 'center' }); openDrawer(target); }
  }
})();
