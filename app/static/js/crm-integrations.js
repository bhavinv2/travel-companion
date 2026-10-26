/* Set-up > Integrations: the search box hides the cards whose name and words do not match. */
(function () {
  'use strict';
  var box = document.querySelector('[data-ig-search]');
  if (!box) return;
  var cards = Array.prototype.slice.call(document.querySelectorAll('[data-ig-card]'));
  var none = document.querySelector('[data-ig-none]');
  box.addEventListener('input', function () {
    var words = box.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    var shown = 0;
    cards.forEach(function (c) {
      var text = c.getAttribute('data-words') || '';
      var hit = words.every(function (w) { return text.indexOf(w) !== -1; });
      c.hidden = !hit;
      if (hit) shown += 1;
    });
    if (none) none.hidden = shown > 0;
  });
})();
