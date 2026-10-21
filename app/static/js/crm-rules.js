/* Set-up > Automation > Rules: the When / If / Then editor. Shows only the boxes the choices need. Without this
   script every box shows and the form still works (the server checks every value against its lists). */
(function () {
  'use strict';
  var form = document.querySelector('[data-rule-form]');
  if (!form) return;
  var CHOICE = ['pipeline', 'stage', 'product', 'source', 'owner', 'country', 'rating', 'status'];
  var OPS = { choice: ['is', 'is_not', 'empty'], number: ['is', 'is_not', 'gt', 'lt', 'empty'],
              text: ['is', 'is_not', 'contains', 'gt', 'lt', 'empty'] };
  function qa(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  // the site wraps every <select> in its searchable dropdown (searchselect.js, after this file runs): a hidden
  // select hides that box too, or every value list of every condition would show at once
  function show(el, on) {
    if (!el) return;
    el.hidden = !on;
    var box = el.parentElement;
    if (box && box.classList.contains('ss')) box.hidden = !on;
  }
  var syncs = [];
  function kind(field) {
    if (CHOICE.indexOf(field) >= 0) return 'choice';
    return field === 'amount' ? 'number' : 'text';
  }

  var trig = form.querySelector('[data-rule-trigger]');
  function when() { qa('[data-when]', form).forEach(function (s) { show(s, s.dataset.when === trig.value); }); }
  if (trig) { trig.addEventListener('change', when); when(); syncs.push(when); }

  function condRow(row) {
    var f = row.querySelector('[data-cond-field]'), op = row.querySelector('[data-cond-op]');
    var text = row.querySelector('[data-cond-text]');
    function sync() {
      var field = f.value, k = kind(field);
      qa('option', op).forEach(function (o) { o.hidden = !field || OPS[k].indexOf(o.value) < 0; });
      if (field && OPS[k].indexOf(op.value) < 0) op.value = OPS[k][0];
      var none = !field || op.value === 'empty';
      show(op, !!field);
      show(text, !none && k !== 'choice');
      qa('[data-cond-choice]', row).forEach(function (s) { show(s, !none && s.dataset.condChoice === field); });
    }
    f.addEventListener('change', sync);
    op.addEventListener('change', sync);
    sync();
    syncs.push(sync);
  }
  qa('[data-cond-row]', form).forEach(condRow);

  function actRow(row) {
    var t = row.querySelector('[data-act-type]');
    var setField = row.querySelector('[data-set-field]');
    var to = row.querySelector('[name^="a_to_"]'), via = row.querySelector('[name^="a_via_"]');
    function sync() {
      qa('[data-act]', row).forEach(function (s) { show(s, s.dataset.act === t.value); });
      if (setField) {
        var f = setField.value;
        qa('[data-set-value]', row).forEach(function (el) {
          var want = (f === 'rating' || f === 'forecast') ? f : 'text';
          show(el, el.dataset.setValue === want);
        });
      }
      if (to && via) show(via, to.value === 'round_robin');
    }
    t.addEventListener('change', sync);
    if (setField) setField.addEventListener('change', sync);
    if (to) to.addEventListener('change', sync);
    sync();
    syncs.push(sync);
  }
  qa('[data-act-row]', form).forEach(actRow);

  // once the dropdowns are built (DOMContentLoaded), hide the boxes of the hidden selects
  function again() { syncs.forEach(function (f) { f(); }); }
  document.addEventListener('DOMContentLoaded', again);
  window.addEventListener('load', again);

  qa('[data-rule-add]', form).forEach(function (btn) {
    btn.addEventListener('click', function () {
      var sel = btn.dataset.ruleAdd === 'cond' ? '[data-cond-row]' : '[data-act-row]';
      var next = qa(sel, form).filter(function (r) { return r.hidden; })[0];
      if (next) { next.hidden = false; var first = next.querySelector('select'); if (first) first.focus(); }
      if (!qa(sel, form).some(function (r) { return r.hidden; })) btn.hidden = true;
    });
  });
})();
