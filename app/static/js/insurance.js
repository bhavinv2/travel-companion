/* Travel-insurance quote form (templates/_insurance_form.html), shared by the public landing and
   the signed-in home. Our fields -> POST /api/insurance-quote -> the partner's live quote page,
   opened in a new tab (the "View my quotes" link stays in case the popup was blocked).
   Date inputs are either the landing's read-only pickers (value in data-iso) or native
   <input type="date"> (value is already ISO), so both are read the same way. */
(function () {
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const csrf = () => (document.querySelector('meta[name="csrf-token"]') || {}).content || window.CSRF_TOKEN || '';
  const isoOf = inp => (inp.dataset.iso || inp.value || '').trim();
  const pretty = inp => {
    const iso = isoOf(inp);
    if (!iso) return '';
    if (inp.type !== 'date') return inp.value;
    const d = new Date(iso + 'T00:00:00');
    return isNaN(d) ? iso : d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
  };

  function bind(form) {
    if (form.dataset.insBound) return;
    form.dataset.insBound = '1';
    const q = s => form.querySelector(s);
    q('.ins-edit')?.addEventListener('click', () => { form.classList.remove('done'); q('.ins-ok').hidden = true; q('.ins-start').focus(); });
    form.addEventListener('submit', async e => {
      e.preventDefault();
      const err = q('.ins-err'), ok = q('.ins-ok'), btn = q('.ins-go');
      const start = isoOf(q('.ins-start')), end = isoOf(q('.ins-end'));
      const fail = m => { err.querySelector('span').textContent = m; err.hidden = false; ok.hidden = true; form.classList.remove('done'); };
      err.hidden = true;
      if (!start) { q('.ins-start').focus(); return fail('Pick the date your cover should start.'); }
      if (!end || end < start) { q('.ins-end').focus(); return fail('Pick an end date on or after the start date.'); }
      if (!/^\d{1,3}$/.test(q('.ins-age1').value.trim())) { q('.ins-age1').focus(); return fail("Enter traveller 1's age in years."); }
      const body = { start_date: start, end_date: end, age1: q('.ins-age1').value.trim(), age2: q('.ins-age2').value.trim(), citizenship: q('.ins-cit').value };
      btn.disabled = true; btn.querySelector('span').textContent = 'Getting quotes…';
      try {
        const r = await fetch('/api/insurance-quote', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() }, body: JSON.stringify(body) });
        const d = await r.json();
        if (!d.success) return fail(d.error || 'Could not get quotes right now.');
        q('.ins-ok-link').href = d.url; err.hidden = true;
        q('.ins-ok-sum').innerHTML = [`${pretty(q('.ins-start'))} → ${pretty(q('.ins-end'))}`, `Age ${body.age1}${body.age2 ? ' & ' + body.age2 : ''}`, q('.ins-cit').selectedOptions[0].textContent]
          .map(s => `<span>${esc(s)}</span>`).join('');
        form.classList.add('done'); ok.hidden = false;
        ok.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        window.open(d.url, '_blank', 'noopener');
      } catch (ex) {
        fail('Could not reach our insurance partner right now. Please try again in a moment.');
      } finally {
        btn.disabled = false; btn.querySelector('span').textContent = 'Get live quotes';
      }
    });
  }

  window.insBindAll = () => document.querySelectorAll('form.ins-form').forEach(bind);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', window.insBindAll);
  else window.insBindAll();
})();
