/* "Summarise" on the lead page (Sales CRM 2.0, run 5b). Shows the AI's summary and a suggested next message; the
   message only goes into the message box (the data-qp-box button, crm-quotes.js) -- the agent reads it, changes it
   and presses Send. Nothing here sends anything. */
(function () {
  'use strict';
  var card = document.querySelector('[data-ai]');
  if (!card) return;
  var out = card.querySelector('[data-ai-out]');
  var btn = card.querySelector('[data-ai-go]');
  var UNAVAILABLE = 'AI is not available right now';
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function show(d) {
    out.innerHTML = '';
    var ul = el('ul', 'ai-sum');
    (d.summary || []).forEach(function (line) { ul.appendChild(el('li', '', line)); });
    out.appendChild(ul);
    if (d.next) {
      var box = el('div', 'ai-next');
      box.appendChild(el('b', '', 'Suggested next message'));
      box.appendChild(el('p', '', d.next));
      var row = el('div', 'row');
      var put = el('button', 'cb sm primary', 'Put in the message box');
      put.type = 'button'; put.setAttribute('data-qp-box', ''); put.setAttribute('data-text', d.next);
      var cp = el('button', 'cb sm', 'Copy text');
      cp.type = 'button'; cp.setAttribute('data-qp-copy', ''); cp.setAttribute('data-text', d.next);
      row.appendChild(put); row.appendChild(cp);
      box.appendChild(row);
      out.appendChild(box);
    }
  }
  btn.addEventListener('click', function () {
    if (!window.CRM || !window.CRM.post) return;
    btn.disabled = true;
    out.textContent = 'Reading their messages…';
    window.CRM.post('lead/' + card.dataset.leadId + '/ai', {}).then(function (d) {
      btn.disabled = false;
      if (!d._ok || !d.summary) { out.textContent = d.error || UNAVAILABLE; return; }
      show(d);
      btn.textContent = 'Summarise again';
    });
  });
})();
