/* The browser half of the phone field (templates/_phone_field.html).
 *
 * It says early what services/phone.py would say on submit. It is NOT the check that counts:
 * the server normalises and validates every number whatever arrives, because a form can be
 * posted without ever running this file. Here it only saves somebody a round trip.
 *
 * The rules are deliberately the same two the server applies, and the dialling code comes from
 * the selected <option>, so there is no second copy of the country table in JavaScript.
 */
(function () {
  var MIN_NATIONAL = 6;     // digits after the country code
  var MAX_E164 = 15;        // digits in total, code included

  /* How each country writes its own national number, keyed by dialling code. The same three
   * groupings services/phone.py uses for display, so a number reads identically while it is
   * being typed, on the page afterwards, and in the admin lists -- only without the country
   * code in front, which the select beside the box is already showing.
   *
   * A country not named here is left exactly as typed. Guessing a grouping is worse than
   * none: it tells somebody their own number looks wrong.
   */
  var GROUPS = {
    '1': [3, 3, 4],         // (815) 555-1234
    '91': [5, 5],           // 98480 00000
    '971': [2, 3, 4]        // 50 123 4567
  };
  var PUNCT = {
    '1': function (p) {
      if (p.length === 1) return '(' + p[0] + (p[0].length === 3 ? ') ' : '');
      return '(' + p[0] + ') ' + p.slice(1).join('-');
    }
  };
  // Shown in the empty box so the shape is clear before anything is typed. Deliberately
  // fictional ranges, so nobody reads a placeholder as a number worth ringing.
  var EXAMPLE = { '1': '(555) 123-4567', '91': '98480 00000', '971': '50 123 4567' };

  function dialOf(select) {
    var opt = select.options[select.selectedIndex];
    return (opt && opt.getAttribute('data-dial')) || '';
  }

  /* A value typed in full, with its own + and country code, is left exactly alone: it is
     already unambiguous, and regrouping it as a national number would mangle it. */
  function typedInFull(value) {
    return (value || '').trim().charAt(0) === '+';
  }

  /* The national digits, spaced the way that country spaces them. */
  function group(digits, dial) {
    var sizes = GROUPS[dial];
    if (!sizes || !digits) return digits;
    var parts = [];
    var at = 0;
    for (var i = 0; i < sizes.length && at < digits.length; i++) {
      parts.push(digits.substr(at, sizes[i]));
      at += sizes[i];
    }
    // More digits than the country's pattern holds: they stay, running on to the end of the
    // last group rather than inventing a group of their own -- "(810) 555-5123-4" reads like a
    // shape somebody uses somewhere, and this is not the place to decide a number is wrong.
    // The check below says that in words.
    if (at < digits.length && parts.length) parts[parts.length - 1] += digits.slice(at);
    return (PUNCT[dial] || function (p) { return p.join(' '); })(parts);
  }

  /* Reformat as they type, keeping the caret where they left it.
     The caret is tracked by how many digits precede it rather than by offset, because the
     separators this adds and removes shift every offset after them. A caret at the end -- which
     is where it is nearly always -- just stays at the end. */
  function reformat(num, dial) {
    var before = num.value;
    if (!before || typedInFull(before)) return;
    var end = num.selectionStart === before.length;
    var digitsBefore = before.slice(0, num.selectionStart).replace(/[^0-9]/g, '').length;
    var after = group(before.replace(/[^0-9]/g, ''), dial);
    if (after === before) return;
    num.value = after;
    if (end) return;                                     // the browser leaves it at the end
    var seen = 0, pos = 0;
    while (pos < after.length && seen < digitsBefore) {
      if (after.charAt(pos) >= '0' && after.charAt(pos) <= '9') seen++;
      pos++;
    }
    try { num.setSelectionRange(pos, pos); } catch (e) { /* not a field with a caret */ }
  }

  /* Mirrors services/phone.normalise: a leading 00 is a +, a single leading 0 is a national
     trunk prefix and is dropped, anything else gets the chosen country's code in front. */
  function e164(value, dial) {
    var digits = (value || '').replace(/[^0-9]/g, '');
    if (!digits) return '';
    if ((value || '').trim().charAt(0) === '+') return digits;
    if (digits.indexOf('00') === 0) return digits.slice(2);
    if (digits.indexOf(dial) === 0 && digits.length > dial.length + MIN_NATIONAL - 1) return digits;
    return dial + digits.replace(/^0+/, '');
  }

  function problem(field) {
    var num = field.querySelector('.pf-num');
    var cc = field.querySelector('.pf-cc');
    if (!num || !cc) return '';
    var raw = (num.value || '').trim();
    if (!raw) return num.required ? 'Enter a phone number.' : '';
    var dial = dialOf(cc);
    var full = e164(raw, dial);
    if (full.length > MAX_E164) return 'That number has too many digits to be dialled.';
    if (full.length - dial.length < MIN_NATIONAL) {
      return 'That number looks too short. Check the digits after the country code.';
    }
    return '';
  }

  function show(field, message) {
    var err = field.querySelector('.pf-err');
    var num = field.querySelector('.pf-num');
    if (err) { err.textContent = message; err.hidden = !message; }
    if (num) {
      field.classList.toggle('is-bad', !!message);
      // so the browser's own validation stops a submit too, without a second message
      num.setCustomValidity(message || '');
    }
  }

  function check(field) {
    var message = problem(field);
    show(field, message);
    return !message;
  }

  document.addEventListener('blur', function (e) {
    var field = e.target.closest && e.target.closest('[data-phone-field]');
    if (field && e.target.classList.contains('pf-num')) check(field);
  }, true);

  // space it as they type, and clear any complaint as soon as they start fixing it
  document.addEventListener('input', function (e) {
    var field = e.target.closest && e.target.closest('[data-phone-field]');
    if (!field) return;
    if (e.target.classList.contains('pf-num')) {
      var cc = field.querySelector('.pf-cc');
      if (cc) reformat(e.target, dialOf(cc));
    }
    if (field.classList.contains('is-bad')) show(field, '');
  });

  /* Respace the box for the country it now belongs to, and show that country's example.
     The same digits are grouped differently from one country to the next, so a number left
     spaced for the old one reads as a typo. */
  function dress(field) {
    var num = field.querySelector('.pf-num');
    var cc = field.querySelector('.pf-cc');
    if (!num || !cc) return;
    var dial = dialOf(cc);
    // Cleared, not left behind, for a country whose shape we do not know: an example in the
    // wrong shape is worse than none.
    num.placeholder = EXAMPLE[dial] || '';
    if (num.value && !typedInFull(num.value)) {
      num.value = group(num.value.replace(/[^0-9]/g, ''), dial);
    }
  }

  document.addEventListener('change', function (e) {
    var field = e.target.closest && e.target.closest('[data-phone-field]');
    if (!field || !e.target.classList.contains('pf-cc')) return;
    dress(field);
    show(field, '');
  });

  /* On load, so a value the server sent back -- or one the browser autofilled -- is spaced the
     way the field would have spaced it, and the empty box already shows the right example. */
  function dressAll() {
    document.querySelectorAll('[data-phone-field]').forEach(dress);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', dressAll);
  } else {
    dressAll();
  }
  // Fields that arrive later: the sign-up popup, the contact dialog, anything in a drawer.
  if (window.MutationObserver) {
    new MutationObserver(function (records) {
      for (var i = 0; i < records.length; i++) {
        for (var j = 0; j < records[i].addedNodes.length; j++) {
          var n = records[i].addedNodes[j];
          if (n.nodeType !== 1) continue;
          if (n.matches && n.matches('[data-phone-field]')) dress(n);
          if (n.querySelectorAll) n.querySelectorAll('[data-phone-field]').forEach(dress);
        }
      }
    }).observe(document.documentElement, { childList: true, subtree: true });
  }

  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (!form.querySelectorAll) return;
    var bad = null;
    form.querySelectorAll('[data-phone-field]').forEach(function (field) {
      if (!check(field) && !bad) bad = field;
    });
    if (bad) {
      e.preventDefault();
      var num = bad.querySelector('.pf-num');
      if (num) num.focus();
    }
  }, true);
})();
