// Admin scraper console: run polling, editor preview, mapping preview, row selection / bulk actions.
// Uses apiFetch() and showToast() from main.js.

function pollRun(runId, { onTick, onDone } = {}) {
  let elapsed = 0;
  const tick = async () => {
    try {
      const res = await apiFetch(`/cs/scraper/api/runs/${runId}/status`);
      const d = await res.json();
      if (onTick) onTick(d);
      if (d.done) { if (onDone) onDone(d); return; }
    } catch (e) { /* keep polling */ }
    elapsed += 2;
    setTimeout(tick, elapsed > 60 ? 5000 : 2000);
  };
  tick();
}

function renderProgress(el, d) {
  if (!el) return;
  const chip = el.querySelector('[data-run-status]');
  if (chip) { chip.textContent = d.status; chip.className = 'chip ' + statusChipClass(d.status); }
  const pages = el.querySelector('[data-run-pages]'); if (pages) pages.textContent = d.progress.pages;
  const items = el.querySelector('[data-run-items]'); if (items) items.textContent = d.progress.items;
  const rows = el.querySelector('[data-run-rows]'); if (rows) rows.textContent = d.progress.rows_new;
  const log = el.querySelector('[data-run-log]');
  if (log) { log.textContent = (d.log_tail || []).join('\n'); log.scrollTop = log.scrollHeight; }
  const err = el.querySelector('[data-run-error]');
  if (err) { err.textContent = d.error || ''; err.style.display = d.error ? '' : 'none'; }
  const cancel = el.querySelector('[data-run-cancel]');
  if (cancel) cancel.style.display = d.done ? 'none' : '';
}

function statusChipClass(status) {
  return { done: 'chip-open', running: 'chip-matched', queued: 'chip-src', failed: 'chip-closed', cancelled: 'chip-unconfirmed' }[status] || 'chip-src';
}

// ----- run page -----------------------------------------------------------
const runPanel = document.getElementById('runProgress');
if (runPanel && runPanel.dataset.active === '1') {
  pollRun(+runPanel.dataset.runId, {
    onTick: (d) => renderProgress(runPanel, d),
    onDone: () => { showToast('Job finished — refreshing…', 'success'); setTimeout(() => location.reload(), 700); },
  });
}

// ----- detect page --------------------------------------------------------
const detectPanel = document.getElementById('detectProgress');
if (detectPanel && detectPanel.dataset.active === '1') {
  pollRun(+detectPanel.dataset.runId, {
    onTick: (d) => renderProgress(detectPanel, d),
    onDone: () => location.reload(),
  });
}

// ----- editor: file load, validate & preview, teach polling ---------------
const recipeFile = document.getElementById('recipeFile');
recipeFile?.addEventListener('change', function () {
  const f = this.files[0];
  if (!f) return;
  const reader = new FileReader();
  reader.onload = (e) => {
    const ta = document.getElementById('recipeJson');
    try { ta.value = JSON.stringify(JSON.parse(e.target.result), null, 2); showToast('Recipe loaded from file', 'success'); }
    catch (err) { ta.value = e.target.result; showToast('File is not valid JSON: ' + err.message, 'danger'); }
  };
  reader.readAsText(f);
});

document.getElementById('formatJson')?.addEventListener('click', () => {
  const ta = document.getElementById('recipeJson');
  try { ta.value = JSON.stringify(JSON.parse(ta.value), null, 2); } catch (err) { showToast('Not valid JSON: ' + err.message, 'danger'); }
});

document.getElementById('previewBtn')?.addEventListener('click', async () => {
  const ta = document.getElementById('recipeJson');
  const out = document.getElementById('previewResult');
  let recipe;
  try { recipe = JSON.parse(ta.value); } catch (err) { return showToast('Not valid JSON: ' + err.message, 'danger'); }
  out.innerHTML = '<div class="loading-spinner"><i class="fa-solid fa-spinner fa-spin"></i> Replaying the first page (up to 5 items)…</div>';
  const res = await apiFetch('/cs/scraper/api/recipes/preview', { method: 'POST', body: JSON.stringify({ recipe }) });
  const d = await res.json();
  if (!res.ok) { out.innerHTML = ''; return showToast(d.error || 'Preview failed', 'danger'); }
  pollRun(d.run_id, {
    onTick: (s) => { const t = out.querySelector('.log-tail'); if (t) t.textContent = (s.log_tail || []).join('\n'); },
    onDone: (s) => renderPreview(out, s),
  });
});

function renderPreview(out, s) {
  out.innerHTML = '';
  if (s.status !== 'done') {
    const p = document.createElement('p'); p.className = 'urgent'; p.textContent = `Preview ${s.status}: ${s.error || ''}`;
    out.appendChild(p);
    const pre = document.createElement('pre'); pre.className = 'log-tail'; pre.textContent = (s.log_tail || []).join('\n'); out.appendChild(pre);
    return;
  }
  const r = s.result || {};
  const rep = r.report || {};
  const head = document.createElement('div'); head.className = 'card-head';
  const chip = document.createElement('span');
  chip.className = 'chip ' + ({ ok: 'chip-open', warning: 'chip-unconfirmed', critical: 'chip-closed' }[rep.status] || 'chip-src');
  chip.textContent = rep.headline || rep.status || '';
  const info = document.createElement('span'); info.className = 'muted'; info.textContent = `${(r.rows || []).length} row(s) from the first page`;
  head.append(chip, info); out.appendChild(head);
  (rep.messages || []).forEach(m => { const p = document.createElement('p'); p.className = 'muted'; p.textContent = m; out.appendChild(p); });
  const cols = (r.columns || []).filter(c => !c.startsWith('_'));
  const wrap = document.createElement('div'); wrap.className = 'table-wrap';
  const table = document.createElement('table'); table.className = 'admin-table';
  const thead = document.createElement('thead'); const trh = document.createElement('tr');
  cols.forEach(c => { const th = document.createElement('th'); th.textContent = c; trh.appendChild(th); });
  thead.appendChild(trh); table.appendChild(thead);
  const tbody = document.createElement('tbody');
  (r.rows || []).forEach(row => {
    const tr = document.createElement('tr');
    cols.forEach(c => { const td = document.createElement('td'); td.textContent = String(row[c] ?? '').slice(0, 120); tr.appendChild(td); });
    tbody.appendChild(tr);
  });
  if (!(r.rows || []).length) { const tr = document.createElement('tr'); const td = document.createElement('td'); td.colSpan = cols.length || 1; td.className = 'muted'; td.textContent = 'No rows found — the selectors may need a re-teach.'; tr.appendChild(td); tbody.appendChild(tr); }
  table.appendChild(tbody); wrap.appendChild(table); out.appendChild(wrap);
}

const teachPanel = document.getElementById('teachProgress');
if (teachPanel && teachPanel.dataset.active === '1') {
  pollRun(+teachPanel.dataset.runId, {
    onTick: (d) => renderProgress(teachPanel, d),
    onDone: (d) => {
      if (d.status === 'done' && d.result && d.result.recipe) {
        document.getElementById('recipeJson').value = JSON.stringify(d.result.recipe, null, 2);
        const site = d.result.recipe.site || '';
        const nameEl = document.getElementById('recipeName');
        if (nameEl && !nameEl.value) nameEl.value = site;
        showToast('Recipe received from the teaching window — review, preview and save it.', 'success');
      } else {
        showToast(d.error || 'Teaching did not produce a recipe.', 'danger');
      }
      renderProgress(teachPanel, d);
    },
  });
}

// ----- mapping page: live preview ----------------------------------------
const mappingForm = document.getElementById('mappingForm');
if (mappingForm) {
  let timer = null;
  const refresh = async () => {
    const mapping = {};
    mappingForm.querySelectorAll('select[data-col]').forEach(s => { mapping[s.dataset.col] = s.value; });
    // warn on the same target chosen twice (title/message are allowed to merge)
    const seen = {};
    mappingForm.querySelectorAll('select[data-col]').forEach(s => {
      const t = s.value; s.classList.remove('dup-target');
      if (t === 'ignore' || t === 'title' || t === 'message') return;
      if (seen[t]) { s.classList.add('dup-target'); seen[t].classList.add('dup-target'); } else seen[t] = s;
    });
    const res = await apiFetch(`/cs/scraper/api/recipes/${mappingForm.dataset.recipeId}/mapping/preview`, {
      method: 'POST', body: JSON.stringify({ mapping, row_id: mappingForm.dataset.rowId || null }),
    });
    const d = await res.json();
    renderMappedPreview(document.getElementById('mappingPreview'), d.preview, d.message);
  };
  mappingForm.querySelectorAll('select[data-col]').forEach(s => s.addEventListener('change', () => { clearTimeout(timer); timer = setTimeout(refresh, 300); }));
}

function renderMappedPreview(el, p, message) {
  if (!el) return;
  el.innerHTML = '';
  if (!p) { el.innerHTML = `<p class="muted">${message || 'No scraped row to preview yet.'}</p>`; return; }
  const add = (label, value) => {
    if (value === null || value === undefined || value === '' || (Array.isArray(value) && !value.length)) return;
    const dt = document.createElement('dt'); dt.textContent = label;
    const dd = document.createElement('dd'); dd.textContent = Array.isArray(value) ? value.join(', ') : String(value);
    el.append(dt, dd);
  };
  el.className = 'dl';
  add('Person', [p.poster_name, p.traveler_name && `for ${p.traveler_name}`].filter(Boolean).join(' '));
  add('Route', `${p.flying_from || '?'} → ${p.destination || '?'}`);
  add('Dates', [p.from_date, p.to_date].filter(Boolean).join(' → '));
  add('Flight', [p.airline, p.flight_number].filter(Boolean).join(' '));
  add('Role', p.role);
  add('Languages', p.languages);
  add('Needs', p.needs);
  add('Contacts', (p.contacts || []).map(c => `${c.type}: ${c.value}`));
  add('Comments', [p.title, p.message].filter(Boolean).join(' — '));
  add('Source', `${p.source} ${p.source_url || ''}`);
  if ((p.errors || []).length) { const dt = document.createElement('dt'); dt.textContent = 'Errors'; const dd = document.createElement('dd'); dd.className = 'urgent'; dd.textContent = p.errors.join(' '); el.append(dt, dd); }
  if ((p.warnings || []).length) { const dt = document.createElement('dt'); dt.textContent = 'Warnings'; const dd = document.createElement('dd'); dd.className = 'muted'; dd.textContent = p.warnings.join(' '); el.append(dt, dd); }
}

// ----- rows table: selection & bulk bar ----------------------------------
const rowsForm = document.getElementById('rowsForm');
if (rowsForm) {
  const master = document.getElementById('selectAllRows');
  const boxes = () => [...rowsForm.querySelectorAll('input.inc:not(:disabled)')];
  const count = document.getElementById('selectedCount');
  const update = () => {
    const n = boxes().filter(b => b.checked).length;
    if (count) count.textContent = n;
    rowsForm.querySelectorAll('[data-needs-selection]').forEach(b => { b.disabled = n === 0 && !rowsForm.querySelector('input[name=select]:checked'); });
  };
  master?.addEventListener('change', () => { boxes().forEach(b => { b.checked = master.checked; }); update(); });
  boxes().forEach(b => b.addEventListener('change', update));
  rowsForm.querySelector('input[name=select]')?.addEventListener('change', update);
  update();
  rowsForm.querySelectorAll('[data-action]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const action = btn.dataset.action;
      if (action === 'export-selected') {
        e.preventDefault();
        const ids = boxes().filter(b => b.checked).map(b => b.value).join(',');
        const mapped = btn.dataset.mapped || '0';
        window.location = `${btn.dataset.base}?mapped=${mapped}` + (ids ? `&ids=${ids}` : '');
        return;
      }
      rowsForm.action = btn.dataset.url;
      if (action === 'create' && !confirm(`Create posts for the selected rows?`)) e.preventDefault();
      if (action === 'skip' && !confirm('Skip the selected rows?')) e.preventDefault();
    });
  });
}

let _rowModal = null;   // last-loaded row payload

async function viewRow(rowId, tab) {
  const res = await apiFetch(`/cs/scraper/api/rows/${rowId}`);
  _rowModal = await res.json();
  const modal = document.getElementById('rowModal');
  if (!modal) return;
  renderRowModal();
  showRowTab(tab === 'edit' && !_rowModal.editable ? 'view' : (tab || 'view'));
  modal.style.display = 'flex';
}

function showRowTab(tab) {
  ['view', 'edit', 'raw'].forEach(t => {
    document.getElementById(`rowPane-${t}`).style.display = t === tab ? '' : 'none';
    document.getElementById(`rowTab-${t}`).classList.toggle('green', t === tab);
  });
}

function renderRowModal() {
  const d = _rowModal;
  document.getElementById('rowModalId').textContent = `#${d.row.id}`;
  const hasEdits = Object.keys(d.edits || {}).length > 0;
  document.getElementById('rowModalEdited').style.display = hasEdits ? '' : 'none';
  document.getElementById('rowEditReset').style.display = hasEdits ? '' : 'none';
  document.getElementById('rowTab-edit').style.display = d.editable ? '' : 'none';
  renderMappedPreview(document.getElementById('rowModalMapped'), d.mapped);

  // --- edit grid: one input per canonical field, prefilled with the effective value ---
  const grid = document.getElementById('rowEditGrid');
  grid.innerHTML = '';
  (d.fields || []).forEach(f => {
    const wrap = document.createElement('div');
    if (f.key === 'title' || f.key === 'message') wrap.className = 'wide';
    const lab = document.createElement('label');
    lab.textContent = f.label;
    let inp;
    if (f.key === 'message' || f.key === 'title') { inp = document.createElement('textarea'); inp.rows = 2; }
    else if (f.key === 'role') {
      inp = document.createElement('select');
      [['', '(auto-detect)'], ['seeking_help', 'seeking help'], ['offering_help', 'offering help'], ['open', 'open']]
        .forEach(([v, t]) => { const o = document.createElement('option'); o.value = v; o.textContent = t; inp.appendChild(o); });
    } else if (f.key === 'source') {
      inp = document.createElement('select');
      [['', '(recipe default)'], ['website', 'website'], ['facebook', 'facebook']]
        .forEach(([v, t]) => { const o = document.createElement('option'); o.value = v; o.textContent = t; inp.appendChild(o); });
    } else {
      inp = document.createElement('input');
      inp.type = 'text';
      if (f.key === 'start' || f.key === 'end') inp.placeholder = 'YYYY-MM-DD';
    }
    inp.value = d.canon[f.key] || '';
    inp.dataset.key = f.key;
    inp.dataset.base = d.base[f.key] || '';
    if ((d.edits || {})[f.key] !== undefined) inp.classList.add('edited-input');
    if (!d.editable) inp.disabled = true;
    wrap.append(lab, inp);
    grid.appendChild(wrap);
  });

  // --- raw scraped values with what they map to ---
  const tb = document.querySelector('#rowRawTable tbody');
  tb.innerHTML = '';
  Object.entries(d.row.data || {}).filter(([k]) => k !== '_edits').forEach(([k, v]) => {
    const tr = document.createElement('tr');
    const tdK = document.createElement('td'); const strong = document.createElement('strong'); strong.textContent = k; tdK.appendChild(strong);
    const tdV = document.createElement('td'); tdV.textContent = v === null || v === undefined ? '' : String(v); tdV.style.wordBreak = 'break-word';
    const tdM = document.createElement('td'); const target = (d.mapping || {})[k];
    tdM.textContent = target && target !== 'ignore' ? target : '—';
    if (!target || target === 'ignore') tdM.className = 'muted';
    tr.append(tdK, tdV, tdM); tb.appendChild(tr);
  });
}

function updateRowCells(id, p, hasEdits) {
  const tr = document.getElementById(`srow-${id}`);
  if (!tr) return;
  const set = (label, text) => { const td = tr.querySelector(`td[data-label="${label}"]`); if (td) td.textContent = text; };
  set('Person', p.poster_name || '—');
  set('Route', `${p.flying_from || '?'} → ${p.destination || '?'}`);
  set('Departs', [p.from_date, p.to_date].filter(Boolean).join(' → ') || '—');
  set('Flight', [p.airline, p.flight_number].filter(Boolean).join(' '));
  set('Role', (p.role || '').replace('_', ' '));
  set('Languages', (p.languages || []).join(', '));
  tr.classList.toggle('row-edited', !!hasEdits);
}

document.getElementById('rowEditSave')?.addEventListener('click', async () => {
  const edits = {};
  document.querySelectorAll('#rowEditGrid [data-key]').forEach(el => {
    const v = el.value.trim();
    if (v !== (el.dataset.base || '').trim()) edits[el.dataset.key] = v;
  });
  const res = await apiFetch(`/cs/scraper/api/rows/${_rowModal.row.id}/edit`, { method: 'POST', body: JSON.stringify({ edits }) });
  const d = await res.json();
  if (d.error) return showToast(d.error, 'danger');
  _rowModal.edits = d.edits; _rowModal.mapped = d.mapped;
  _rowModal.canon = Object.assign({}, _rowModal.base, d.edits);
  Object.keys(d.edits).forEach(k => { if (d.edits[k] === '') delete _rowModal.canon[k]; });
  renderRowModal();
  updateRowCells(_rowModal.row.id, d.mapped, Object.keys(d.edits).length > 0);
  showRowTab('view');
  showToast(Object.keys(d.edits).length ? 'Corrections saved - they will be used when the post is created.' : 'No differences from the scraped values - nothing to save.', 'success');
});

document.getElementById('rowEditReset')?.addEventListener('click', async () => {
  if (!confirm('Remove all corrections and go back to the scraped values?')) return;
  const res = await apiFetch(`/cs/scraper/api/rows/${_rowModal.row.id}/edit`, { method: 'POST', body: JSON.stringify({ edits: {} }) });
  const d = await res.json();
  if (d.error) return showToast(d.error, 'danger');
  _rowModal.edits = {}; _rowModal.mapped = d.mapped; _rowModal.canon = Object.assign({}, _rowModal.base);
  renderRowModal();
  updateRowCells(_rowModal.row.id, d.mapped, false);
  showToast('Corrections removed.', 'info');
});

document.getElementById('closeRowModal')?.addEventListener('click', () => { document.getElementById('rowModal').style.display = 'none'; });
