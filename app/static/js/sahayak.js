/* Sahayak booking form.
 *
 * Nothing here decides anything: the server validates and stores the request. This is the
 * "Book this" shortcut from a service card, showing the date box only when it is relevant, and
 * reporting back what happened.
 */
(function () {
  const form = document.getElementById('skForm');
  if (!form) return;

  const service = document.getElementById('sk-service');
  const when = form.querySelectorAll('input[name="when_type"]');
  const datetime = document.getElementById('sk-datetime');
  const msg = document.getElementById('skMsg');
  const submit = form.querySelector('.sk-submit');

  // "Book this" on a card fills the dropdown and scrolls down, so nobody has to find their
  // service a second time in a list of twelve.
  document.querySelectorAll('[data-sk-pick]').forEach(btn => {
    btn.addEventListener('click', () => {
      service.value = btn.getAttribute('data-sk-pick');
      service.dispatchEvent(new Event('change', { bubbles: true }));
      document.getElementById('book').scrollIntoView({ behavior: 'smooth', block: 'start' });
      setTimeout(() => document.getElementById('sk-patient').focus(), 420);
    });
  });

  function syncWhen() {
    const scheduled = form.querySelector('input[name="when_type"]:checked').value === 'scheduled';
    datetime.hidden = !scheduled;
    datetime.required = scheduled;
    if (!scheduled) datetime.value = '';
  }
  when.forEach(r => r.addEventListener('change', syncWhen));
  syncWhen();

  function say(text, ok) {
    msg.textContent = text;
    msg.className = 'sk-msg ' + (ok ? 'ok' : 'bad');
    msg.hidden = false;
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!form.checkValidity()) { form.reportValidity(); return; }

    const body = {};
    new FormData(form).forEach((v, k) => { body[k] = v; });

    submit.disabled = true;
    try {
      const res = window.apiFetch
        ? await window.apiFetch('/api/sahayak-booking', { method: 'POST', body: JSON.stringify(body) })
        : await fetch((window.APP_ROOT || '') + '/api/sahayak-booking', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRFToken': (document.querySelector('meta[name=csrf-token]') || {}).content || ''
            },
            body: JSON.stringify(body)
          });
      const data = await res.json();
      if (data.success) {
        form.reset();
        syncWhen();
        say(data.message || 'Request received. Our team will call to confirm.', true);
      } else {
        say(data.error || 'Could not send that request. Please try again.', false);
      }
    } catch (err) {
      say('Network problem — your request was not sent. Please try again.', false);
    } finally {
      submit.disabled = false;
      msg.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  });
})();
