/* Targets page: the totals row follows what is typed. Nothing is saved until Save targets is pressed. */
(function () {
  'use strict';
  var form = document.querySelector('[data-targets]');
  if (!form) return;
  var money = function (n) {
    var s = String(Math.round(n)), out = '';
    if (s.length > 3) {
      var head = s.slice(0, -3), tail = s.slice(-3), parts = [];
      while (head.length > 2) { parts.unshift(head.slice(-2)); head = head.slice(0, -2); }
      if (head) parts.unshift(head);
      out = parts.join(',') + ',' + tail;
    } else { out = s; }
    return out;
  };
  function total() {
    ['amount', 'deals', 'leads'].forEach(function (k) {
      var sum = 0;
      form.querySelectorAll('[data-sum="' + k + '"]').forEach(function (i) {
        var v = parseFloat(String(i.value).replace(/,/g, ''));
        if (!isNaN(v) && v > 0) sum += v;
      });
      var out = form.querySelector('[data-total="' + k + '"]');
      if (!out) return;
      var cur = out.textContent.trim().charAt(0);
      out.textContent = k === 'amount' ? (/[0-9]/.test(cur) ? '' : cur) + money(sum) : money(sum);
    });
  }
  form.addEventListener('input', total);
})();
