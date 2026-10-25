/* Overview › Health and Help › Screen guide.
   - The hover read-out on a chart's columns and bars ([data-tip]): one tooltip that follows the pointer. The same
     numbers are in each chart's table and at each bar's tip, so nothing is only on hover.
   - Health's parts fold, like an accordion (remembered on this browser).
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

  /* Health's parts fold (an accordion): a part's head opens and closes it; "Close all" / "Open all" does every
     one; the closed ones are remembered on this browser; a jump link (#hl-sales) opens the part it goes to. */
  var folds = Array.prototype.slice.call(document.querySelectorAll('[data-hl-fold]'));
  if (folds.length) {
    var KEY = 'hl-closed', all = document.querySelector('[data-hl-all]');
    var partOf = function (b) { return b.closest('[data-hl-part]'); };
    var isOpen = function (b) { return b.getAttribute('aria-expanded') !== 'false'; };
    var save = function () {
      var keys = folds.filter(function (b) { return !isOpen(b); }).map(function (b) { return partOf(b).getAttribute('data-hl-part'); });
      try { localStorage.setItem(KEY, JSON.stringify(keys)); } catch (e) { /* not remembered */ }
      if (all) {
        var anyOpen = folds.some(isOpen);
        all.querySelector('span').textContent = anyOpen ? 'Close all' : 'Open all';
        all.querySelector('i').className = 'fa-solid ' + (anyOpen ? 'fa-angles-up' : 'fa-angles-down');
      }
    };
    var set = function (b, open) {
      b.setAttribute('aria-expanded', open ? 'true' : 'false');
      document.getElementById(b.getAttribute('aria-controls')).hidden = !open;
      partOf(b).classList.toggle('is-closed', !open);
    };
    var closed = [];
    try { closed = JSON.parse(localStorage.getItem(KEY) || '[]') || []; } catch (e) { closed = []; }
    folds.forEach(function (b) {
      if (closed.indexOf(partOf(b).getAttribute('data-hl-part')) !== -1) set(b, false);
      b.addEventListener('click', function () { set(b, !isOpen(b)); save(); });
    });
    if (all) {
      all.addEventListener('click', function () {
        var open = !folds.some(isOpen);
        folds.forEach(function (b) { set(b, open); });
        save();
      });
    }
    var openPart = function (id) {
      var part = id && document.getElementById(id);
      var b = part && part.querySelector('[data-hl-fold]');
      if (b && !isOpen(b)) { set(b, true); save(); }
    };
    document.addEventListener('click', function (e) {
      var a = e.target.closest ? e.target.closest('.hl-jump a') : null;
      if (a) openPart(a.getAttribute('href').slice(1));
    });
    openPart(location.hash.slice(1));
    save();
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
