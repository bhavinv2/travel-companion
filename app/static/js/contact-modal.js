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
    document.querySelectorAll('[data-open-contact], #matchTalkBtn, #humanTalkBtn').forEach(el =>
      el.addEventListener('click', e => { e.preventDefault(); openContactModal(); }));
    $('#contactModalClose')?.addEventListener('click', closeContactModal);
    modal.addEventListener('click', e => { if (e.target === modal) closeContactModal(); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeContactModal(); });
    $('#contactModalForm')?.addEventListener('submit', async e => {
      e.preventDefault();
      const f = e.target; if (!f.checkValidity()) { f.reportValidity(); return; }
      const via = (f.querySelector('[name=cm-via]:checked') || {}).value || '';
      // The endpoint stores name/email/phone/message; the extra preferences ride along in the
      // message so CS sees them in the console and in the notification e-mail.
      const details = [`Topic: ${$('#cm-topic').value}`, `Preferred contact: ${via}`,
        `Preferred language: ${$('#cm-lang').value}`, `Best time: ${$('#cm-time').value} (${$('#cm-tz').value})`].join('\n');
      const payload = { name: $('#cm-name').value, email: $('#cm-email').value, phone: $('#cm-phone').value,
        message: `${details}\n\n${$('#cm-msg').value}` };
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
