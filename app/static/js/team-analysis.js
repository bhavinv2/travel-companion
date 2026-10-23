/* Team analysis (cs/crm/team_analysis.html): who is compared is ticked on the left, without a reload.

   The page holds everybody the viewer may see; ticking hides and shows their columns and rows, adds up
   "Together", marks the best and the weakest in each row of the scorecard, and draws "Day by day" for the
   measure picked. The people ticked and the tab stay in the address (?p=, ?tab=), so a link or a reload
   shows the same comparison, and the period buttons and the download carry them. */
(function () {
  const root = document.getElementById('ta');
  if (!root) return;
  const side = document.getElementById('taSide');
  const form = document.getElementById('taPeriod');
  const people = () => Array.from(side.querySelectorAll('input[type=checkbox][value]'));
  const all = Array.from(new Set(people().map(i => i.value)));
  let picked = new Set(people().filter(i => i.checked).map(i => i.value));

  // ---------------------------------------------------------------- the address
  function address() {
    const u = new URL(location.href);
    const p = picked.size === all.length ? '' : Array.from(picked).join(',');
    if (p) u.searchParams.set('p', p); else u.searchParams.delete('p');
    u.searchParams.set('tab', tab);
    history.replaceState(null, '', u);
    form.querySelector('[name=p]').value = p;
    form.querySelector('[name=tab]').value = tab;
    document.querySelectorAll('a[data-keep]').forEach(a => {
      const l = new URL(a.href, location.href);
      if (p) l.searchParams.set('p', p); else l.searchParams.delete('p');
      a.href = l.pathname + l.search;
    });
  }

  // ---------------------------------------------------------------- who is ticked
  function sync() {
    people().forEach(i => { i.checked = picked.has(i.value); });
    side.querySelectorAll('input[data-team]').forEach(t => {
      const mine = people().filter(i => i.dataset.in === t.dataset.team);
      const on = mine.filter(i => i.checked).length;
      t.checked = on > 0 && on === mine.length;
      t.indeterminate = on > 0 && on < mine.length;
    });
    document.getElementById('taCount').textContent = picked.size + ' of ' + all.length + ' ticked';
    root.querySelectorAll('[data-u]').forEach(el => el.classList.toggle('ta-off', !picked.has(el.dataset.u)));
    document.getElementById('taNone').hidden = picked.size > 0;
    score();
    sums();
    daily();
    address();
  }
  side.addEventListener('change', e => {
    const i = e.target;
    if (i.dataset.team) {
      people().filter(x => x.dataset.in === i.dataset.team).forEach(x => { if (i.checked) picked.add(x.value); else picked.delete(x.value); });
    } else if (i.value) {
      if (i.checked) picked.add(i.value); else picked.delete(i.value);
    }
    sync();
  });
  side.addEventListener('click', e => {
    const b = e.target.closest('[data-pick]');
    if (!b) return;
    picked = b.dataset.pick === 'all' ? new Set(all) : new Set();
    sync();
  });
  document.getElementById('taFind').addEventListener('input', e => {
    const q = e.target.value.trim().toLowerCase();
    side.querySelectorAll('.ta-person').forEach(l => { l.hidden = !!q && !l.dataset.name.includes(q); });
  });

  // ---------------------------------------------------------------- tabs
  let tab = new URL(location.href).searchParams.get('tab') || 'scorecard';
  function showTab(t) {
    if (!root.querySelector('[data-pane="' + t + '"]')) t = 'scorecard';
    tab = t;
    root.querySelectorAll('.ta-tabs [data-tab]').forEach(b => b.setAttribute('aria-selected', b.dataset.tab === t ? 'true' : 'false'));
    root.querySelectorAll('.ta-pane').forEach(p => { p.hidden = p.dataset.pane !== t; });
  }
  root.querySelector('.ta-tabs').addEventListener('click', e => {
    const b = e.target.closest('[data-tab]');
    if (!b) return;
    showTab(b.dataset.tab);
    address();
  });

  // ---------------------------------------------------------------- numbers as the page writes them
  const table = document.getElementById('taScore');
  const currency = table ? table.dataset.currency : '';
  function clock(m) { m = Math.round(m) % 1440; return String(Math.floor(m / 60)).padStart(2, '0') + ':' + String(m % 60).padStart(2, '0'); }
  function minutes(m) { m = Math.round(m); return m < 60 ? m + ' min' : Math.floor(m / 60) + ' h ' + (m % 60) + ' min'; }
  function money(v) {
    try { return new Intl.NumberFormat(undefined, { style: 'currency', currency: currency || 'USD', maximumFractionDigits: 0 }).format(v); }
    catch (e) { return (currency ? currency + ' ' : '') + Math.round(v).toLocaleString(); }
  }
  function show(v, unit) {
    if (v == null || Number.isNaN(v)) return '—';
    if (unit === 'percent') return Math.round(v) + '%';
    if (unit === 'minutes') return minutes(v);
    if (unit === 'money') return money(v);
    if (unit === 'hours') return (Math.round(v * 10) / 10) + ' h';
    if (unit === 'time') return clock(v);
    return String(Math.round(v * 100) / 100);
  }
  function rowValues(key) {
    const tr = table && table.querySelector('tr[data-key="' + key + '"]');
    if (!tr) return [];
    return Array.from(tr.querySelectorAll('td[data-u]')).filter(td => picked.has(td.dataset.u) && td.dataset.v !== '')
      .map(td => parseFloat(td.dataset.v));
  }
  const add = xs => xs.reduce((a, b) => a + b, 0);

  // ---------------------------------------------------------------- the scorecard: together, best and weakest
  function score() {
    if (!table) return;
    table.querySelectorAll('tr[data-key]').forEach(tr => {
      const unit = tr.dataset.unit, better = tr.dataset.better;
      const cells = Array.from(tr.querySelectorAll('td[data-u]')).filter(td => picked.has(td.dataset.u));
      cells.forEach(td => td.classList.remove('best', 'worst'));
      Array.from(tr.querySelectorAll('td[data-u]')).forEach(td => td.classList.remove('best', 'worst'));
      const vals = cells.filter(td => td.dataset.v !== '').map(td => [td, parseFloat(td.dataset.v)]);
      let together = null;
      if (tr.dataset.key === 'done_rate') {
        const due = add(rowValues('followups_due')), done = add(rowValues('followups_done'));
        together = due ? 100 * Math.min(done, due) / due : null;
      } else if (unit === 'count' || unit === 'money') {
        together = add(vals.map(v => v[1]));
      } else if (vals.length) {
        together = add(vals.map(v => v[1])) / vals.length;           // an average: hours, times, waits
      }
      const tot = tr.querySelector('td.tot');
      tot.textContent = cells.length ? show(together, unit) : '';
      tot.title = (unit === 'count' || unit === 'money' || tr.dataset.key === 'done_rate') ? 'The people ticked, added up' : 'The average of the people ticked';
      if (!better || vals.length < 2) return;
      const nums = vals.map(v => v[1]);
      const hi = Math.max(...nums), lo = Math.min(...nums);
      if (hi === lo) return;
      vals.forEach(([td, v]) => {
        if (v === (better === 'high' ? hi : lo)) td.classList.add('best');
        else if (v === (better === 'high' ? lo : hi)) td.classList.add('worst');
      });
    });
  }

  // the cards over the inbox checks: the people ticked, added up
  function sums() {
    root.querySelectorAll('[data-sum]').forEach(b => { b.textContent = add(rowValues(b.dataset.sum)); });
  }

  // ---------------------------------------------------------------- day by day
  const dataEl = document.getElementById('taDailyData');
  const data = dataEl ? JSON.parse(dataEl.textContent) : { days: [], people: [] };
  const metric = document.getElementById('taMetric');
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
  function daily() {
    const out = document.getElementById('taDaily');
    if (!out || !metric) return;
    const key = metric.value, label = metric.options[metric.selectedIndex].text;
    const rows = data.people.filter(p => picked.has(String(p.id)));
    const val = (p, d) => (p.daily[key] || {})[d] || 0;
    let top = 0;
    rows.forEach(p => data.days.forEach(d => { top = Math.max(top, val(p, d)); }));
    const together = data.days.map(d => add(rows.map(p => val(p, d))));
    const day = d => { const x = new Date(d + 'T00:00:00'); return { wd: x.toLocaleDateString(undefined, { weekday: 'short' }).slice(0, 2), n: x.getDate(), we: x.getDay() === 0 || x.getDay() === 6 }; };
    const fmt = v => (Math.round(v * 10) / 10).toString();
    let h = '<thead><tr><th class="who">' + esc(label) + '</th>' + data.days.map(d => { const x = day(d); return '<th class="' + (x.we ? 'we' : '') + '">' + x.wd + '<b>' + x.n + '</b></th>'; }).join('') + '<th class="sum">All</th></tr></thead><tbody>';
    rows.forEach(p => {
      h += '<tr><td class="who">' + esc(p.name) + '</td>' + data.days.map(d => {
        const v = val(p, d);
        return '<td class="l' + (v && top ? Math.ceil(4 * v / top) : 0) + '" title="' + esc(p.name + ', ' + d + ': ' + fmt(v)) + '">' + (v ? fmt(v) : '') + '</td>';
      }).join('') + '<td class="sum">' + fmt(add(data.days.map(d => val(p, d)))) + '</td></tr>';
    });
    const most = Math.max(1, ...together);
    h += '<tr class="team"><td class="who">Together</td>' + together.map(v => '<td>' + (v ? fmt(v) : '') + '</td>').join('') + '<td class="sum">' + fmt(add(together)) + '</td></tr>';
    // the same, as a bar a day, lined up under the days
    h += '<tr class="bars" aria-hidden="true"><td class="who"></td>' + together.map((v, i) =>
      '<td title="' + esc(data.days[i] + ': ' + fmt(v)) + '"><i style="height:' + Math.round(100 * v / most) + '%"></i></td>').join('') + '<td class="sum"></td></tr></tbody>';
    out.innerHTML = rows.length ? h : '';
  }
  if (metric) metric.addEventListener('change', daily);

  showTab(tab);
  sync();
})();
