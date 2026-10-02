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

  function dialOf(select) {
    var opt = select.options[select.selectedIndex];
    return (opt && opt.getAttribute('data-dial')) || '';
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

  // clear the complaint as soon as they start fixing it
  document.addEventListener('input', function (e) {
    var field = e.target.closest && e.target.closest('[data-phone-field]');
    if (field && field.classList.contains('is-bad')) show(field, '');
  });

  document.addEventListener('change', function (e) {
    var field = e.target.closest && e.target.closest('[data-phone-field]');
    if (field && e.target.classList.contains('pf-cc')) show(field, '');
  });

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
