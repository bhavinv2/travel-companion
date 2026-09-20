/* Travel-insurance quote form (templates/_insurance_form.html), shared by the public landing and
   the signed-in home. Our fields -> POST /api/insurance-quote -> the partner's live quote page,
   opened in a new tab (the "View my quotes" link stays in case the popup was blocked).
   Date inputs are either the landing's read-only pickers (value in data-iso) or native
   <input type="date"> (value is already ISO), so both are read the same way.

   Everything is scoped to one form element: the macro renders three times on the site (landing
   widget tab, landing drawer, signed-in home) and the copies must not read each other's state. */
(function () {
  const MAX_TRAVELLERS = 8;          // matches MAX_TRAVELLERS in routes/main.py
  const TYPE_LABELS = { visitors: 'Visitors Medical', health: 'Travel Medical', schengen: 'Schengen Visa' };
  // Only Travel Medical takes a destination — visitors is the USA and schengen is the Schengen
  // area, so for those the country is implied (mirrors INSURANCE_TYPES in routes/main.py).
  const NEEDS_DESTINATION = { health: true };

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

  const selectedType = form => (form.querySelector('.ins-type.is-on') || {}).dataset?.insType || 'visitors';

  function renumber(form) {
    const rows = [...form.querySelectorAll('.ins-trav-row')];
    rows.forEach((row, i) => {
      row.querySelector('.ins-trav-n').textContent = i + 1;
      const nm = row.querySelector('.ins-tname'), age = row.querySelector('.ins-age');
      nm.setAttribute('aria-label', 'Traveller ' + (i + 1) + ' name');
      nm.placeholder = i === 0 ? 'e.g. Ramesh Kumar' : 'Full name';
      age.setAttribute('aria-label', 'Traveller ' + (i + 1) + ' age');
      age.placeholder = i === 0 ? '65' : 'Age';
      // one traveller is a valid quote, so the last remaining row cannot be removed
      row.querySelector('.ins-trav-rm').disabled = rows.length === 1;
    });
    form.querySelector('.ins-add').disabled = rows.length >= MAX_TRAVELLERS;
    form.querySelector('.ins-trav-hint').textContent =
      rows.length >= MAX_TRAVELLERS ? 'That is the most we can quote in one go.'
                                    : 'Add everyone travelling — each age is priced separately.';
  }

  function addRow(form, focus) {
    const rows = form.querySelector('.ins-trav-rows');
    if (rows.querySelectorAll('.ins-trav-row').length >= MAX_TRAVELLERS) return;
    const row = document.createElement('div');
    row.className = 'ins-trav-row';
    row.innerHTML = '<span class="ins-trav-n"></span>'
      + '<input class="ins-tname" type="text" maxlength="120" autocomplete="off">'
      + '<input class="ins-age" type="text" inputmode="numeric" pattern="[0-9]*" maxlength="3">'
      + '<button type="button" class="ins-trav-rm" aria-label="Remove traveller">'
      + '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" width="14" height="14"><path d="M6 6l12 12M18 6L6 18"/></svg></button>';
    row.querySelector('.ins-trav-rm').addEventListener('click', () => {
      if (form.querySelectorAll('.ins-trav-row').length === 1) return;
      row.remove();
      renumber(form);
    });
    rows.appendChild(row);
    renumber(form);
    if (focus) row.querySelector('.ins-tname').focus();
  }

  function bind(form) {
    if (form.dataset.insBound) return;
    form.dataset.insBound = '1';
    const q = s => form.querySelector(s);

    // product chips — selection is per form, read back at submit time
    const syncDestination = () => {
      const f = form.querySelector('.ins-dest-f');
      if (f) f.hidden = !NEEDS_DESTINATION[selectedType(form)];
    };
    form.querySelectorAll('.ins-type').forEach(chip => {
      chip.addEventListener('click', () => {
        form.querySelectorAll('.ins-type').forEach(c => {
          const on = c === chip;
          c.classList.toggle('is-on', on);
          c.setAttribute('aria-selected', on ? 'true' : 'false');
        });
        syncDestination();
      });
    });
    syncDestination();

    addRow(form); addRow(form);          // a visiting couple is the common case
    q('.ins-add').addEventListener('click', () => addRow(form, true));

    q('.ins-edit')?.addEventListener('click', () => { form.classList.remove('done'); q('.ins-ok').hidden = true; q('.ins-start').focus(); });

    form.addEventListener('submit', async e => {
      e.preventDefault();
      const err = q('.ins-err'), ok = q('.ins-ok'), btn = q('.ins-go');
      const start = isoOf(q('.ins-start')), end = isoOf(q('.ins-end'));
      const fail = (m, el) => { err.querySelector('span').textContent = m; err.hidden = false; ok.hidden = true; form.classList.remove('done'); el?.focus(); };
      err.hidden = true;

      if (!start) return fail('Pick the date your cover should start.', q('.ins-start'));
      if (!end || end < start) return fail('Pick an end date on or after the start date.', q('.ins-end'));

      const travellers = [];
      for (const row of form.querySelectorAll('.ins-trav-row')) {
        const nmEl = row.querySelector('.ins-tname'), ageEl = row.querySelector('.ins-age');
        const nm = nmEl.value.trim(), age = ageEl.value.trim();
        if (!nm) return fail('Enter a name for every traveller, or remove the empty row.', nmEl);
        if (!age) return fail('Enter an age for every traveller.', ageEl);
        if (!/^\d{1,3}$/.test(age)) return fail('Traveller ages must be whole numbers (years).', ageEl);
        travellers.push({ name: nm, age });
      }
      if (!travellers.length) return fail("Enter at least one traveller's name and age.");

      const email = q('.ins-email').value.trim();
      if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return fail('Please enter a valid email address.', q('.ins-email'));

      const insType = selectedType(form);
      const body = {
        start_date: start, end_date: end, travellers, citizenship: q('.ins-cit').value,
        insurance_type: insType, email, phone: q('.ins-phone').value.trim(),
      };
      if (NEEDS_DESTINATION[insType]) body.destination = q('.ins-dest').value;

      btn.disabled = true; btn.querySelector('span').textContent = 'Getting quotes…';
      try {
        const r = await fetch('/api/insurance-quote', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() }, body: JSON.stringify(body) });
        const d = await r.json();
        if (!d.success) return fail(d.error || 'Could not get quotes right now.');
        q('.ins-ok-link').href = d.url; err.hidden = true;
        q('.ins-ok-sum').innerHTML = [
          TYPE_LABELS[insType] || 'Travel insurance',
          body.destination ? 'To ' + q('.ins-dest').selectedOptions[0].textContent : null,
          `${pretty(q('.ins-start'))} → ${pretty(q('.ins-end'))}`,
          travellers.map(t => `${t.name} (${t.age})`).join(', '),
          q('.ins-cit').selectedOptions[0].textContent,
        ].filter(Boolean).map(s => `<span>${esc(s)}</span>`).join('');
        form.classList.add('done'); ok.hidden = false;
        ok.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        window.open(d.url, '_blank', 'noopener');
      } catch (ex) {
        fail('Could not reach our insurance partner right now. Please try again in a moment.');
      } finally {
        btn.disabled = false; btn.querySelector('span').textContent = 'Get free quotes';
      }
    });
  }

  window.insBindAll = () => document.querySelectorAll('form.ins-form').forEach(bind);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', window.insBindAll);
  else window.insBindAll();
})();
