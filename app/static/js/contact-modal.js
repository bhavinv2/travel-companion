/* "Customer help" contact popup (templates/_contact_modal.html), shared by the public landing and
   the app pages. Opens from any [data-open-contact] element (plus the landing's legacy ids),
   posts to /api/landing-contact, and closes on the X, the backdrop or Escape. */
(function () {
  const $ = s => document.querySelector(s);
  const csrf = () => (document.querySelector('meta[name="csrf-token"]') || {}).content || window.CSRF_TOKEN || '';
  const say = (msg, kind) => {
    if (window.showToast) return showToast(msg, kind === 'error' ? 'danger' : 'success');   // app shell
    if (window.cdToast) return cdToast(msg);                                                  // public landing
    alert(msg);
  };
  function openContactModal() { const m = $('#contactModal'); if (!m) return; m.classList.add('open'); setTimeout(() => $('#cm-name')?.focus(), 50); }
  function closeContactModal() { $('#contactModal')?.classList.remove('open'); }
  window.openContactModal = openContactModal;
  window.closeContactModal = closeContactModal;

  function init() {
    const modal = $('#contactModal'); if (!modal) return;
    // Anything that asks for help opens this: the header Support pill, any [data-open-contact],
    // and every plain link to /contact. They all keep their href, so without JavaScript they
    // still reach a real page instead of doing nothing.
    const selector = '[data-open-contact], #matchTalkBtn, #humanTalkBtn, #navSupport';
    document.addEventListener('click', e => {
      const el = e.target.closest(selector);
      if (!el || el.target === '_blank') return;
      e.preventDefault();
      openContactModal();
    });
    $('#contactModalClose')?.addEventListener('click', closeContactModal);
    modal.addEventListener('click', e => { if (e.target === modal) closeContactModal(); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeContactModal(); });
    $('#contactModalForm')?.addEventListener('submit', async e => {
      e.preventDefault();
      const f = e.target; if (!f.checkValidity()) { f.reportValidity(); return; }
      // The preferences are sent as fields. The server folds them into the message, so this
      // popup and the /contact page produce the same thing in the CS console -- they used to be
      // assembled here, which is exactly why the page version never had them.
      const payload = {
        name: $('#cm-name').value, email: $('#cm-email').value, phone: $('#cm-phone').value,
        // the country the visitor picked; the server normalises the pair into E.164, so what
        // reaches CS is dialable rather than nine digits with no code
        phone_cc: (f.querySelector('[name=phone_cc]') || {}).value || '',
        message: $('#cm-msg').value, topic: $('#cm-topic').value,
        via: (f.querySelector('[name=cm-via]:checked') || {}).value || '',
        language: $('#cm-lang').value, time: $('#cm-time').value, zone: $('#cm-tz').value,
      };
      const btn = f.querySelector('button[type=submit]'); btn.disabled = true;
      try {
        const r = await fetch('/api/landing-contact', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() }, body: JSON.stringify(payload) });
        const d = await r.json();
        if (d.success) { say(d.message || 'Thanks — we will get back to you shortly.'); f.reset(); closeContactModal(); }
        else say(d.error || 'Please check the form and try again.', 'error');
      } catch (err) { say('Network error — please try again.', 'error'); }
      finally { btn.disabled = false; }
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
