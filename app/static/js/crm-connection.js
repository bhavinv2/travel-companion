/* WhatsApp connection: the live checks are asked for after the page has drawn, so the page itself never waits on
   the WhatsApp CRM (routes/crm_wa.py connection_checks). */
(function () {
  var box = document.querySelector('[data-conn-checks]');
  if (!box) return;
  var rules = document.querySelector('[data-conn-rules]');
  fetch(box.getAttribute('data-src'), { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
    .then(function (r) { return r.json(); })
    .then(function (d) { box.innerHTML = d.cards || ''; if (rules) rules.innerHTML = d.rules || ''; })
    .catch(function () { box.innerHTML = '<p class="hint">Could not check just now. Press Check again.</p>'; });
})();
