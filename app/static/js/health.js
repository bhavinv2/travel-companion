/* Overview › Health and Help › Screen guide.
   - The hover read-out on a chart's columns and bars ([data-tip]): one tooltip that follows the pointer. The same
     numbers are in each chart's table and at each bar's tip, so nothing is only on hover.
   - The Screen guide's search box: hides the screens whose name, words or place do not match. */
(function () {
  'use strict';

  var tip = document.getElementById('hl-tip');
  if (tip) {
    var show = function (el, x, y) {
      tip.textContent = el.getAttribute('data-tip');      // text, never html: names come from the database
      tip.hidden = false;
      var w = tip.offsetWidth, h = tip.offsetHeight;
      var left = Math.min(Math.max(8, x - w / 2), window.innerWidth - w - 8);
      tip.style.left = left + 'px';
      tip.style.top = Math.max(8, y - h - 12) + 'px';
    };
    document.addEventListener('pointermove', function (e) {
      var el = e.target.closest ? e.target.closest('[data-tip]') : null;
      if (el) {
        show(el, e.clientX, e.clientY);
      } else if (!tip.hidden) {
        tip.hidden = true;
      }
    });
    document.addEventListener('scroll', function () { tip.hidden = true; }, true);
  }

  var find = document.getElementById('sgFind');
  if (find) {
    var items = Array.prototype.slice.call(document.querySelectorAll('.sg-item'));
    var areas = Array.prototype.slice.call(document.querySelectorAll('.sg-area'));
    var none = document.getElementById('sgNone');
    find.addEventListener('input', function () {
      var words = find.value.toLowerCase().split(/\s+/).filter(Boolean);
      items.forEach(function (it) {
        var text = it.textContent.toLowerCase();
        it.hidden = !words.every(function (w) { return text.indexOf(w) !== -1; });
      });
      var shown = 0;
      areas.forEach(function (a) {
        var any = a.querySelector('.sg-item:not([hidden])');
        a.hidden = !any;
        if (any) { shown += 1; }
      });
      if (none) { none.hidden = shown > 0; }
    });
  }
})();
