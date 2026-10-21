/* Lead capture for any landing page -- the two-line way to put a new page into the Sales CRM.

     <form data-lead-source="diwali-insurance" data-product="TI">
       <input name="name"> <input name="phone"> <input name="email"> <textarea name="message"></textarea>
       <button>Send</button>
     </form>
     <script src="https://<this site>/static/js/lead-capture.js" defer></script>

   name, phone (and phone_cc, an ISO country such as IN or US), email, message, consent (the WhatsApp tick) and
   offers_consent (a separate "OK to send offers" tick) are
   read by name; every other field is kept with the lead as it is. The campaign the visitor came
   from (utm_*, gclid, fbclid) goes with it. A source code nobody has set up yet still works: its
   leads wait in the CRM until an admin chooses their pipeline once.

   Optional on the form: data-success="text to show afterwards", data-redirect="/thank-you".
   Pages on another website must be listed in the server's CRM_INTAKE_ORIGINS. */
(function () {
  'use strict';
  var me = document.currentScript;
  var ORIGIN = me && me.src ? new URL(me.src).origin : location.origin;
  var KNOWN = ['name', 'phone', 'phone_cc', 'email', 'message', 'consent', 'offers_consent', 'website', 'csrf_token'];
  var UTM = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content', 'gclid', 'fbclid'];

  function firstVisit() {
    try {
      var c = document.cookie.split('; ').find(function (x) { return x.indexOf('nps_src=') === 0; });
      return c ? JSON.parse(decodeURIComponent(c.slice(8))) : {};
    } catch (e) { return {}; }
  }

  function note(form, text, bad) {
    var n = form.querySelector('.lc-note');
    if (!n) {
      n = document.createElement('p');
      n.className = 'lc-note';
      n.setAttribute('role', 'status');
      form.appendChild(n);
    }
    n.textContent = text;
    n.style.color = bad ? '#dc2626' : '';
  }

  function wire(form) {
    if (form.dataset.lcReady) return;
    form.dataset.lcReady = '1';
    // a field people cannot see: only a bot fills it in
    var trap = document.createElement('input');
    trap.type = 'text'; trap.name = 'website'; trap.tabIndex = -1; trap.autocomplete = 'off';
    trap.setAttribute('aria-hidden', 'true');
    trap.style.cssText = 'position:absolute;left:-9999px;width:1px;height:1px;opacity:0';
    form.appendChild(trap);

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var data = new FormData(form), body = { source: form.dataset.leadSource, fields: {} };
      if (form.dataset.product) body.product = form.dataset.product;
      data.forEach(function (v, k) {
        if (typeof v !== 'string') return;
        if (KNOWN.indexOf(k) >= 0) body[k] = (k === 'consent' || k === 'offers_consent') ? true : v;
        else if (v.trim()) body.fields[k] = body.fields[k] ? body.fields[k] + ', ' + v : v;
      });
      if (!(body.phone || '').trim() && !(body.email || '').trim()) {
        note(form, 'Please give a phone number or an e-mail so we can reach you.', true);
        return;
      }
      var p = new URLSearchParams(location.search), src = firstVisit();
      UTM.forEach(function (k) { var v = p.get(k) || src[k]; if (v) body[k] = String(v).slice(0, 200); });
      body.landing = src.landing || location.pathname;
      if (src.referrer) body.referrer = src.referrer;
      var btn = form.querySelector('[type=submit], button:not([type])');
      if (btn) btn.disabled = true;
      fetch(ORIGIN + '/api/leads', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
        credentials: ORIGIN === location.origin ? 'same-origin' : 'omit'
      }).then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (d) { d._ok = r.ok; return d; });
      }).then(function (d) {
        if (btn) btn.disabled = false;
        if (!d._ok || !d.success) { note(form, d.error || 'Sorry, that did not go through. Please try again.', true); return; }
        if (form.dataset.redirect) { location.href = form.dataset.redirect; return; }
        form.reset();
        note(form, form.dataset.success || 'Thank you! We will be in touch shortly.');
        form.dispatchEvent(new CustomEvent('lead:sent', { bubbles: true }));
      }).catch(function () {
        if (btn) btn.disabled = false;
        note(form, 'No connection. Please try again.', true);
      });
    });
  }

  function init() { document.querySelectorAll('form[data-lead-source]').forEach(wire); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
