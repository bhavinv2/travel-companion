/* The Promotion dashboard's boxes, drawn (2026-10-29): a box's numbers (services/mkt_engine.run) as a big number, a
   line, columns, bars, a pie, a donut, a table or a live counter, with Chart.js. The page has the numbers of most
   boxes already (a <script class="mk-json"> in each); the website's it asks /promotion/box for, after it has drawn,
   and a live box asks again every 30 seconds. The designer (mkt-designer.js) draws its previews with the same
   MK.render, so a box looks the same while it is made and once it is published. */
(function () {
  'use strict';

  var PALETTES = {
    // the site's own: Travel Companion blue, Insurance green, the amber accent, then the rest
    brand: ['#2f80ed', '#16a34a', '#f5a623', '#ef4444', '#8b5cf6', '#06b6d4', '#ec4899', '#84cc16', '#64748b'],
    ocean: ['#0369a1', '#0ea5e9', '#14b8a6', '#38bdf8', '#0f766e', '#1e40af', '#5eead4', '#93c5fd', '#155e75'],
    sunset: ['#ea580c', '#f59e0b', '#dc2626', '#fb923c', '#f43f5e', '#facc15', '#c2410c', '#fda4af', '#b45309'],
    forest: ['#15803d', '#65a30d', '#0f766e', '#22c55e', '#84cc16', '#14b8a6', '#166534', '#a3e635', '#4d7c0f'],
    berry: ['#7c3aed', '#db2777', '#6366f1', '#a855f7', '#ec4899', '#818cf8', '#c084fc', '#f472b6', '#4c1d95'],
    mono: ['#0f2340', '#475569', '#94a3b8', '#334155', '#64748b', '#cbd5e1', '#1e293b', '#e2e8f0', '#0b1220']
  };
  var REFRESH_MS = 30000;
  var charts = new WeakMap();

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function fmt(v, unit, short) {
    if (v === null || v === undefined || v === '') return '—';
    var n = Number(v);
    if (isNaN(n)) return String(v);
    if (unit === 'pct') return (n * 100).toFixed(1) + '%';
    if (unit === 'seconds') { var m = Math.floor(n / 60); return m + 'm ' + String(Math.round(n % 60)).padStart(2, '0') + 's'; }
    if (unit === 'rating' || unit === 'position') return n.toFixed(1);
    if (short && Math.abs(n) >= 10000) {
      return (Math.abs(n) >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : (n / 1e3).toFixed(Math.abs(n) >= 1e5 ? 0 : 1) + 'k');
    }
    return Number.isInteger(n) ? n.toLocaleString('en-IN') : n.toLocaleString('en-IN', { maximumFractionDigits: 1 });
  }

  function palette(cfg) { return PALETTES[(cfg && cfg.colour) || 'brand'] || PALETTES.brand; }

  function alpha(hex, a) {
    var h = hex.replace('#', '');
    var r = parseInt(h.substr(0, 2), 16), g = parseInt(h.substr(2, 2), 16), b = parseInt(h.substr(4, 2), 16);
    return 'rgba(' + r + ',' + g + ',' + b + ',' + a + ')';
  }

  function inkOf(el) {
    var c = getComputedStyle(el).color || '#0f2340';
    return { text: c, grid: c.replace('rgb(', 'rgba(').replace(')', ', .09)') };
  }

  // ------------------------------------------------------------------------------------------- the HTML of a box

  function changeHtml(r) {
    if (r.change !== null && r.change !== undefined) {
      // green is the good news: more of something, or less of a thing where less is better (a position)
      var good = (r.change > 0) !== !!r.lower_better;
      var dir = r.change === 0 ? 'flat' : (good ? 'up' : 'down');
      var icon = r.change > 0 ? 'fa-arrow-trend-up' : (r.change < 0 ? 'fa-arrow-trend-down' : 'fa-minus');
      return '<span class="mk-chg ' + dir + '"><i class="fa-solid ' + icon + '" aria-hidden="true"></i> ' +
        (r.change > 0 ? '+' : '') + r.change + '% <small>vs the ' + r.period.days + ' days before</small></span>';
    }
    if (r.prev === 0 && r.total) {
      return '<span class="mk-chg up"><i class="fa-solid fa-star" aria-hidden="true"></i> New <small>none in the ' +
        r.period.days + ' days before</small></span>';
    }
    return '';
  }

  function tableHtml(r, hidden) {
    var h = '<div class="mk-tablewrap' + (hidden ? ' sr-only' : '') + '"><table class="mk-table"><thead><tr><th scope="col"></th>';
    (r.series || []).forEach(function (s) { h += '<th scope="col">' + esc(s.name) + '</th>'; });
    h += '</tr></thead><tbody>';
    (r.rows || []).forEach(function (row) {
      h += '<tr><th scope="row">' + esc(row.label) + '</th>';
      row.values.forEach(function (v, i) { h += '<td>' + fmt(v, (r.series[i] && r.series[i].unit) || r.unit) + '</td>'; });
      h += '</tr>';
    });
    return h + '</tbody></table></div>';
  }

  function bodyHtml(cfg, r) {
    if (!r) return '<div class="mk-wait"><i class="fa-solid fa-circle-notch fa-spin" aria-hidden="true"></i> Fetching the numbers…</div>';
    if (r.hidden || !r.ok) {
      return '<p class="mk-msg"><i class="fa-solid ' + (r.hidden ? 'fa-lock' : 'fa-circle-exclamation') +
        '" aria-hidden="true"></i> ' + esc(r.message || r.error || 'These numbers could not be fetched.') + '</p>';
    }
    if (cfg.chart === 'live') {
      var h = '<div class="mk-live"><div class="mk-live-n"><span class="mk-pulse" aria-hidden="true"></span>' +
        '<b class="mk-n" data-n="' + (r.total || 0) + '">' + fmt(r.total, r.unit) + '</b><small>' +
        esc((r.series[0] && r.series[0].name) || 'people') + ' in the last 30 minutes</small></div>';
      if (r.labels && r.labels.length && r.labels[0] !== 'All') {
        h += '<ul class="mk-live-list">';
        r.labels.slice(0, 5).forEach(function (lb, i) {
          h += '<li><span>' + esc(lb) + '</span><b>' + fmt(r.series[0].data[i], r.unit) + '</b></li>';
        });
        h += '</ul>';
      }
      return h + '<div class="mk-live-min" aria-hidden="true"></div></div>';
    }
    if (cfg.chart === 'number') {
      return '<div class="mk-num"><b class="mk-n" data-n="' + (r.total == null ? '' : r.total) + '">' + fmt(r.total, r.unit) +
        '</b>' + changeHtml(r) + (r.time ? '<div class="mk-spark"><canvas aria-hidden="true"></canvas></div>' : '') + '</div>';
    }
    if (r.empty) {
      return '<p class="mk-empty"><i class="fa-regular fa-folder-open" aria-hidden="true"></i> ' +
        esc(cfg.empty || 'Nothing in these dates yet.') + '</p>';
    }
    var out = cfg.chart === 'table' ? '' : '<div class="mk-chart"><canvas role="img" aria-label="' + esc(cfg.title || '') + '"></canvas></div>';
    return out + tableHtml(r, cfg.chart !== 'table') + (r.notes && r.notes.length ? '<p class="mk-notes">' + esc(r.notes.join(' ')) + '</p>' : '');
  }

  // ------------------------------------------------------------------------------------------- the charts

  function destroy(canvas) {
    var c = charts.get(canvas);
    if (c) { c.destroy(); charts.delete(canvas); }
  }

  function chart(canvas, cfg, r) {
    if (!window.Chart || !canvas) return;
    destroy(canvas);
    var pal = palette(cfg), ink = inkOf(canvas.closest('.mk-box') || document.body);
    var kind = cfg.chart, many = (r.series || []).length > 1;
    var round = kind === 'pie' || kind === 'donut';
    var type = round ? (kind === 'pie' ? 'pie' : 'doughnut') : ((kind === 'line' || kind === 'area') ? 'line' : 'bar');
    var dense = (r.labels || []).length > 40;
    var datasets = (r.series || []).map(function (s, i) {
      var c = pal[i % pal.length];
      if (round) {
        return { label: s.name, data: s.data, borderWidth: 2, borderColor: getComputedStyle(canvas).backgroundColor || '#fff',
          backgroundColor: s.data.map(function (_, j) { return pal[j % pal.length]; }) };
      }
      if (type === 'line') {
        return { label: s.name, data: s.data, borderColor: c, backgroundColor: kind === 'area' ? alpha(c, many ? 0.12 : 0.22) : c,
          fill: kind === 'area' ? 'origin' : false, cubicInterpolationMode: 'monotone', borderWidth: 2.2,
          pointRadius: dense ? 0 : 2.5,
          pointHoverRadius: 5 };
      }
      return { label: s.name, data: s.data, backgroundColor: many || kind === 'hbar' ? c : (kind === 'bar' ? c : c),
        borderRadius: 6, maxBarThickness: kind === 'hbar' ? 22 : 40 };
    });
    if (round && datasets.length > 1) datasets = datasets.slice(0, 1);
    var unit = r.unit;
    var options = {
      responsive: true, maintainAspectRatio: false, animation: { duration: 700 },
      interaction: { mode: round ? 'nearest' : 'index', intersect: round },
      plugins: {
        legend: { display: round || many, position: round && canvas.parentNode.clientWidth > 380 ? 'right' : 'bottom',
          labels: { color: ink.text, boxWidth: 12, boxHeight: 12, usePointStyle: true, padding: 12, font: { size: 12 } } },
        tooltip: { callbacks: { label: function (c) {
          var v = round ? c.parsed : (kind === 'hbar' ? c.parsed.x : c.parsed.y);
          var su = r.series[c.datasetIndex] && r.series[c.datasetIndex].unit;
          return ' ' + (c.dataset.label && !round ? c.dataset.label + ': ' : (round ? c.label + ': ' : '')) + fmt(v, su || unit);
        } } }
      }
    };
    if (!round) {
      var stacked = kind === 'stacked';
      var valueAxis = { beginAtZero: true, stacked: stacked, grid: { color: ink.grid }, border: { display: false },
        ticks: { color: ink.text, maxTicksLimit: 6, precision: unit === 'count' ? 0 : undefined,
          callback: function (v) { return fmt(v, unit, true); } } };
      var labelAxis = { stacked: stacked, grid: { display: false }, border: { display: false },
        ticks: { color: ink.text, autoSkip: true, maxRotation: 0, maxTicksLimit: kind === 'hbar' ? 50 : 8,
          callback: function (v) { var s = this.getLabelForValue(v); return s && s.length > 26 ? s.slice(0, 25) + '…' : s; } } };
      if (kind === 'hbar') { options.indexAxis = 'y'; options.scales = { x: valueAxis, y: labelAxis }; }
      else options.scales = { x: labelAxis, y: valueAxis };
    } else if (kind === 'donut') {
      options.cutout = '62%';
    }
    charts.set(canvas, new window.Chart(canvas, { type: type, data: { labels: r.labels, datasets: datasets }, options: options }));
  }

  function spark(canvas, cfg, r) {
    if (!window.Chart || !canvas || !r.series || !r.series[0]) return;
    destroy(canvas);
    var c = palette(cfg)[0];
    charts.set(canvas, new window.Chart(canvas, {
      type: 'line',
      data: { labels: r.labels, datasets: [{ data: r.series[0].data, borderColor: c, backgroundColor: alpha(c, 0.16),
        fill: 'origin', cubicInterpolationMode: 'monotone', borderWidth: 2, pointRadius: 0 }] },
      options: { responsive: true, maintainAspectRatio: false, animation: { duration: 600 },
        plugins: { legend: { display: false }, tooltip: { enabled: false } },
        scales: { x: { display: false }, y: { display: false, beginAtZero: true } } }
    }));
  }

  // a number counts up to its value, the way a scoreboard turns over
  function countUp(el, from) {
    var to = Number(el.getAttribute('data-n'));
    if (el.getAttribute('data-n') === '' || isNaN(to) || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    var unit = el.getAttribute('data-unit') || '';
    var start = from || 0, t0 = performance.now(), ms = 900;
    if (unit && unit !== 'count') return;
    (function step(t) {
      var k = Math.min(1, (t - t0) / ms), e = 1 - Math.pow(1 - k, 3);
      el.textContent = fmt(Math.round(start + (to - start) * e), 'count');
      if (k < 1) requestAnimationFrame(step);
    })(t0);
  }

  function render(boxEl, cfg, r, opts) {
    var body = boxEl.querySelector('.mk-box-b');
    opts = opts || {};
    if (!opts.keepHtml) body.innerHTML = bodyHtml(cfg, r);
    if (!r || !r.ok) return;
    var n = body.querySelector('.mk-n');
    if (n) { n.setAttribute('data-unit', r.unit || 'count'); if (!opts.noCount) countUp(n, opts.from); }
    if (cfg.chart === 'number') { spark(body.querySelector('.mk-spark canvas'), cfg, r); return; }
    if (cfg.chart === 'live' || cfg.chart === 'table' || r.empty) return;
    chart(body.querySelector('.mk-chart canvas'), cfg, r);
  }

  function readJson(el, cls) {
    var s = el.querySelector('script.' + cls);
    if (!s) return null;
    try { return JSON.parse(s.textContent); } catch (e) { return null; }
  }

  window.MK = { render: render, bodyHtml: bodyHtml, fmt: fmt, palettes: PALETTES, esc: esc };

  // ------------------------------------------------------------------------------------------- the page

  var root = document.querySelector('.mk[data-box-url]');
  if (!root) return;

  function query(extra) {
    var q = new URLSearchParams({ d: root.getAttribute('data-page'), range: root.getAttribute('data-range'),
      from: root.getAttribute('data-from'), to: root.getAttribute('data-to') });
    if (root.getAttribute('data-draft')) q.set('draft', '1');
    Object.keys(extra || {}).forEach(function (k) { q.set(k, extra[k]); });
    return q.toString();
  }

  function fetchBox(boxEl, cfg, quiet) {
    var old = boxEl.querySelector('.mk-n');
    var from = old ? Number(old.getAttribute('data-n')) : 0;
    return fetch(root.getAttribute('data-box-url') + '?' + query({ b: boxEl.getAttribute('data-box') }),
      { headers: { Accept: 'application/json' }, credentials: 'same-origin' })
      .then(function (res) { return res.json(); })
      .then(function (r) {
        render(boxEl, cfg, r, { from: quiet ? from : 0 });
        if (quiet && old && r.ok && Number(r.total) !== from) boxEl.classList.add('bump');
        setTimeout(function () { boxEl.classList.remove('bump'); }, 900);
        return r;
      })
      .catch(function () { if (!quiet) render(boxEl, cfg, { ok: false, message: 'The numbers could not be fetched. Reload the page to try again.' }); });
  }

  // the last 30 minutes, minute by minute, under every live counter
  function liveMinutes() {
    var holders = root.querySelectorAll('.mk-live-min');
    if (!holders.length) return;
    fetch(root.getAttribute('data-live-url'), { headers: { Accept: 'application/json' }, credentials: 'same-origin' })
      .then(function (res) { return res.json(); })
      .then(function (d) {
        if (!d.ok) return;
        var max = Math.max.apply(null, d.minutes.concat([1]));
        var bars = d.minutes.map(function (n, i) {
          return '<i style="height:' + Math.max(6, Math.round(100 * n / max)) + '%" title="' + n + ' · ' + (29 - i) + ' min ago"></i>';
        }).join('');
        holders.forEach(function (h) { h.innerHTML = bars; });
      }).catch(function () {});
  }

  var lives = [];
  root.querySelectorAll('.mk-box').forEach(function (boxEl) {
    var cfg = readJson(boxEl, 'mk-cfg');
    if (!cfg) return;
    if (boxEl.hasAttribute('data-async')) {
      fetchBox(boxEl, cfg).then(function () { if (cfg.chart === 'live') liveMinutes(); });
      if (cfg.chart === 'live') lives.push([boxEl, cfg]);
      return;
    }
    var r = readJson(boxEl, 'mk-json');
    if (r) render(boxEl, cfg, r, { keepHtml: true });
  });
  if (lives.length) {
    setInterval(function () {
      if (document.hidden) return;
      lives.forEach(function (l) { fetchBox(l[0], l[1], true); });
      setTimeout(liveMinutes, 400);
    }, REFRESH_MS);
  }

  // the date picker: "Choose dates" shows the two dates; any other choice is applied at once
  var pick = root.querySelector('[data-range-pick]');
  if (pick) {
    pick.addEventListener('change', function () {
      var custom = root.querySelector('[data-custom]');
      if (pick.value === 'custom') { custom.hidden = false; custom.querySelector('input').focus(); return; }
      pick.form.querySelectorAll('[data-custom] input').forEach(function (i) { i.disabled = true; });
      pick.form.submit();
    });
  }
})();
