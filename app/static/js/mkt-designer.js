/* The Dashboard designer (2026-10-29): templates/marketing/designer.html.

   The dashboard is a list of boxes on a 12-column grid ({x, y, w, h} in columns and 64px rows). A box is dragged by
   its title and resized by its corner; clicking it opens its settings on the right: what to count (one or more
   numbers, each from any source, narrowed by any of its dimensions), what to split it by (time or a dimension, then
   a second dimension), the dates, how it is drawn and how it looks. Every change asks /promotion/designer/preview for
   the box's numbers and draws them with MK.render (mkt-charts.js), exactly as the published dashboard will.

   Save sends the boxes; the server checks every choice again (services/mkt_engine.clean_box) and answers the cleaned
   boxes, which replace ours. Publish is Save, then the draft becomes what everybody sees. */
(function () {
  'use strict';

  var root = document.getElementById('dz');
  if (!root || !window.MK) return;
  var DATA = JSON.parse(document.getElementById('dz-data').textContent);
  var CAT = DATA.catalogue, URLS = DATA.urls;
  var CSRF = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
  var grid = document.getElementById('dz-grid'), panel = document.getElementById('dz-panel');
  var rangeSel = document.getElementById('dz-range');
  var esc = MK.esc;
  var ROW = 64, GAP = 16, MAX_H = 10;
  var GRAINS = ['auto', 'day', 'week', 'month', 'quarter', 'year'];
  var SRC = {}, CH = {};
  CAT.sources.forEach(function (s) { SRC[s.key] = s; });
  CAT.charts.forEach(function (c) { CH[c.key] = c; });
  var S = { boxes: DATA.boxes || [], sel: null, dirty: false, published: DATA.published, changes: DATA.changes };
  var optionCache = {};

  // ------------------------------------------------------------------------------------------- small things

  function clamp(n, lo, hi) { n = parseInt(n, 10); if (isNaN(n)) n = lo; return Math.max(lo, Math.min(hi, n)); }
  function clone(o) { return JSON.parse(JSON.stringify(o)); }
  function uid() { return 'b' + Date.now().toString(36).slice(-4) + Math.random().toString(36).slice(2, 5); }
  function byId(id) { return S.boxes.filter(function (b) { return b.id === id; })[0] || null; }
  function wire(b) { return JSON.parse(JSON.stringify(b, function (k, v) { return k.charAt(0) === '_' ? undefined : v; })); }
  function isGrain(g) { return GRAINS.indexOf(g) >= 0; }
  function srcOf(b) { return b.metrics && b.metrics[0] ? SRC[b.metrics[0].source] : null; }
  function kindOf(b) { return !b.group ? '' : (isGrain(b.group) ? 'time' : 'cat'); }
  function noData(chart) { return CAT.no_data.indexOf(chart) >= 0; }
  function title(b) { return b.title || b._title || (CH[b.chart] || {}).label || 'A box'; }
  function bottom() { return S.boxes.reduce(function (m, b) { return Math.max(m, b.y + b.h); }, 0); }

  function post(url, body) {
    return fetch(url, { method: 'POST', credentials: 'same-origin', body: JSON.stringify(body),
      headers: { 'Content-Type': 'application/json', Accept: 'application/json', 'X-CSRFToken': CSRF } })
      .then(function (r) { return r.json().catch(function () { return { ok: false, error: 'The server did not answer. Try again.' }; }); })
      .catch(function () { return { ok: false, error: 'No connection. Your changes are still here; try again.' }; });
  }

  function say(text, bad) {
    var el = document.getElementById('dz-saved');
    el.textContent = text || '';
    el.style.color = bad ? '#b91c1c' : '';
  }

  function stateChip() {
    var el = document.getElementById('dz-state');
    if (!S.published) { el.className = 'dz-state'; el.textContent = 'Draft · not on the Promotion dashboard'; }
    else if (S.changes || S.dirty) { el.className = 'dz-state changed'; el.textContent = 'Published · changes not published yet'; }
    else { el.className = 'dz-state live'; el.textContent = 'Published'; }
  }

  function touch() {
    S.dirty = true;
    S.changes = true;
    stateChip();
    say('Not saved yet');
  }

  // ------------------------------------------------------------------------------------------- the layout

  function overlaps(a, b) { return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h; }

  // the box just moved keeps its place; the others move down out of its way, top to bottom
  function pack(firstId) {
    var first = byId(firstId);
    var rest = S.boxes.filter(function (b) { return b !== first; })
      .sort(function (a, b) { return a.y - b.y || a.x - b.x; });
    var placed = first ? [first] : [];
    rest.forEach(function (b) {
      while (placed.some(function (p) { return overlaps(b, p); })) b.y += 1;
      placed.push(b);
    });
    S.boxes = placed.sort(function (a, b) { return a.y - b.y || a.x - b.x; });
  }

  function place(el, b) {
    el.style.setProperty('--x', b.x); el.style.setProperty('--y', b.y);
    el.style.setProperty('--w', b.w); el.style.setProperty('--h', b.h);
  }

  function frame(b) {
    var el = document.createElement('section');
    el.className = 'mk-box k-' + b.chart + ' c-' + (b.colour || 'brand') + (S.sel === b.id ? ' sel' : '');
    el.setAttribute('data-id', b.id);
    el.tabIndex = 0;
    el.setAttribute('aria-label', title(b) + ' — arrow keys move it, Shift and arrows resize it');
    place(el, b);
    el.innerHTML = (b.chart === 'text' ? '' : '<header class="mk-box-h"><h2>' + esc(title(b)) + '</h2></header>') +
      '<div class="dz-tools"><button type="button" data-act="copy" title="Copy this box"><i class="fa-regular fa-copy"></i></button>' +
      '<button type="button" data-act="del" title="Delete this box"><i class="fa-solid fa-xmark"></i></button></div>' +
      '<div class="mk-box-b"></div><span class="dz-resize" title="Drag to resize" aria-hidden="true"></span>';
    return el;
  }

  function drawAll() {
    grid.innerHTML = '';
    if (!S.boxes.length) {
      grid.innerHTML = '<div class="dz-empty"><i class="fa-solid fa-table-cells-large fa-2x" aria-hidden="true"></i>' +
        '<p><b>An empty dashboard.</b> Add a box from the left: an empty one, or a ready-made one to change.</p></div>';
      return;
    }
    S.boxes.forEach(function (b) { var el = frame(b); grid.appendChild(el); preview(b, el, true); });
  }

  function placeAll() {
    S.boxes.forEach(function (b) { var el = grid.querySelector('[data-id="' + b.id + '"]'); if (el) place(el, b); });
  }

  function redrawBox(b) {
    var old = grid.querySelector('[data-id="' + b.id + '"]');
    var el = frame(b);
    if (old) grid.replaceChild(el, old); else grid.appendChild(el);
    preview(b, el, true);
  }

  // ------------------------------------------------------------------------------------------- the previews

  var timers = {}, seq = {};

  function textHtml(body) {
    var lines = String(body || '').split('\n');
    return '<div class="mk-text"><h2>' + esc(lines[0] || '') + '</h2>' +
      lines.slice(1).filter(function (l) { return l.trim(); }).map(function (l) { return '<p>' + esc(l) + '</p>'; }).join('') + '</div>';
  }

  function quotesHtml(list) {
    if (!list || !list.length) return '<p class="mk-empty">No published reviews yet.</p>';
    return '<div class="mk-quotes">' + list.map(function (q) {
      return '<figure class="mk-quote"><span class="mk-q-stars">' + new Array(q.rating + 1).join('★') +
        '</span><blockquote>' + esc(q.text) + '</blockquote><figcaption>' + esc(q.who) + ' · ' + esc(q.site) + '</figcaption></figure>';
    }).join('') + '</div>';
  }

  function linksHtml(list) {
    return '<ul class="mk-links">' + (list || []).map(function (l) {
      return '<li><a href="' + esc(l.url) + '" target="_blank" rel="noopener"><b>' + esc(l.label) + '</b><span>' + esc(l.url) + '</span></a></li>';
    }).join('') + '</ul>';
  }

  function preview(b, el, now) {
    el = el || grid.querySelector('[data-id="' + b.id + '"]');
    if (!el) return;
    clearTimeout(timers[b.id]);
    timers[b.id] = setTimeout(function () {
      var body = el.querySelector('.mk-box-b');
      if (b.chart === 'text') { body.innerHTML = textHtml(b.body); return; }
      var n = (seq[b.id] = (seq[b.id] || 0) + 1);
      if (!body.innerHTML) body.innerHTML = MK.bodyHtml({ chart: b.chart }, null);
      post(URLS.preview, { box: wire(b), range: rangeSel.value }).then(function (r) {
        if (seq[b.id] !== n || !el.isConnected) return;
        if (r.title) {
          b._title = r.title;
          var h = el.querySelector('.mk-box-h h2');
          if (h && !b.title) h.textContent = r.title;
        }
        if (S.sel === b.id) showErr(r.ok === false && !r.hidden ? (r.error || r.message) : '');
        if (b.chart === 'quotes') { body.innerHTML = quotesHtml(r.quotes); return; }
        if (b.chart === 'links') { body.innerHTML = linksHtml(r.links); return; }
        if (r.ok === false && r.error && !r.message) r.message = r.error;
        MK.render(el, { chart: b.chart, colour: b.colour, empty: b.empty, title: title(b) }, r, { noCount: true });
      });
    }, now ? 0 : 380);
  }

  function showErr(text) {
    var e = document.getElementById('dz-err');
    if (!e) return;
    e.hidden = !text;
    e.textContent = text || '';
  }

  // ------------------------------------------------------------------------------------------- the settings

  function opt(value, label, on, disabled) {
    return '<option value="' + esc(value) + '"' + (on ? ' selected' : '') + (disabled ? ' disabled' : '') + '>' + esc(label) + '</option>';
  }

  function field(label, control, hint) {
    return '<label>' + esc(label) + control + (hint ? '<span class="hint">' + esc(hint) + '</span>' : '') + '</label>';
  }

  function sourceSelect(m, i) {
    var groups = {}, order = [];
    CAT.sources.forEach(function (s) { if (!groups[s.group]) { groups[s.group] = []; order.push(s.group); } groups[s.group].push(s); });
    var h = '<select data-m="' + i + '" data-mk="source">';
    order.forEach(function (g) {
      h += '<optgroup label="' + esc(g) + '">' + groups[g].map(function (s) {
        return opt(s.key, s.label + (s.kind === 'ga' && !CAT.ga_connected ? ' (not connected)' : ''), s.key === m.source);
      }).join('') + '</optgroup>';
    });
    return h + '</select>';
  }

  function common(b, what) {
    // the grains or dimensions every number of the box has
    var lists = b.metrics.map(function (m) { return (SRC[m.source] || {})[what] || []; });
    var keys = lists[0].map(function (x) { return x.key; });
    lists.slice(1).forEach(function (l) {
      var ks = l.map(function (x) { return x.key; });
      keys = keys.filter(function (k) { return ks.indexOf(k) >= 0; });
    });
    return lists[0].filter(function (x) { return keys.indexOf(x.key) >= 0; });
  }

  function groupSelect(b) {
    var kinds = {};
    b.metrics.forEach(function (m) { kinds[(SRC[m.source] || {}).kind] = 1; });
    var h = '<select data-k="group">' + opt('', 'Nothing — one total', !b.group);
    var grains = common(b, 'grains');
    if (grains.length) h += '<optgroup label="Over time">' + grains.map(function (g) { return opt(g.key, g.label, b.group === g.key); }).join('') + '</optgroup>';
    if (Object.keys(kinds).length === 1) {
      var dims = common(b, 'dims');
      if (dims.length) h += '<optgroup label="Into groups">' + dims.map(function (d) { return opt(d.key, d.label, b.group === d.key); }).join('') + '</optgroup>';
    }
    return h + '</select>';
  }

  function splitSelect(b) {
    var src = srcOf(b);
    var h = '<select data-k="split"' + (b.metrics.length > 1 ? ' disabled title="A box with several numbers is not split again"' : '') + '>' +
      opt('', 'No — one colour', !b.split);
    (src ? src.dims : []).forEach(function (d) { if (d.key !== b.group) h += opt(d.key, d.label, b.split === d.key); });
    return h + '</select>';
  }

  function rangeSelect(b) {
    return '<select data-k="range">' + CAT.ranges.map(function (r) { return opt(r.key, r.label, b.range === r.key); }).join('') + '</select>';
  }

  function allowed(b) {
    var src = srcOf(b), kind = kindOf(b);
    if (!src) return Object.keys(CH);
    var base = kind === 'time' ? CAT.time_charts.slice() : (kind === 'cat' ? CAT.cat_charts.slice() : ['number', 'bar', 'table']);
    if (src.live) base = ['live', 'number'].concat(kind === 'cat' ? CAT.cat_charts : []);
    return base.concat(CAT.no_data);
  }

  function metricHtml(b, m, i) {
    var src = SRC[m.source];
    var h = '<div class="dz-metric" data-mi="' + i + '"><div class="dz-metric-h"><span>Number ' + (i + 1) + '</span>' +
      (b.metrics.length > 1 ? '<button type="button" data-act="rm-metric" data-m="' + i + '" title="Remove this number"><i class="fa-solid fa-xmark"></i></button>' : '') + '</div>';
    h += field('From', sourceSelect(m, i), src ? src.says : '');
    h += field('Count', '<select data-m="' + i + '" data-mk="measure">' + src.measures.map(function (x) { return opt(x.key, x.label, x.key === m.measure); }).join('') + '</select>');
    if (src.dates.length > 1) {
      h += field('By the date it was', '<select data-m="' + i + '" data-mk="date">' + src.dates.map(function (x) { return opt(x.key, x.label, x.key === m.date); }).join('') + '</select>');
    }
    if (b.metrics.length > 1) {
      h += field('Its name on the chart', '<input type="text" data-m="' + i + '" data-mk="label" maxlength="60" value="' + esc(m.label || '') + '" placeholder="' + esc(measureLabel(m)) + '"/>');
    }
    h += '<div class="dz-filters">';
    Object.keys(m.filters || {}).forEach(function (dk) {
      var d = src.dims.filter(function (x) { return x.key === dk; })[0];
      h += '<div class="dz-filter" data-m="' + i + '" data-dim="' + esc(dk) + '"><div class="dz-filter-h"><span>Only ' + esc(d ? d.label.toLowerCase() : dk) + ':</span>' +
        '<button type="button" data-act="rm-filter" title="Remove"><i class="fa-solid fa-xmark"></i></button></div><div class="dz-vals">Loading…</div></div>';
    });
    h += '</div>';
    var free = src.dims.filter(function (d) { return !(m.filters || {})[d.key]; });
    if (free.length) {
      h += '<select data-act="add-filter" data-m="' + i + '" aria-label="Narrow it down">' + opt('', '+ Only some of them, by …', true) +
        free.map(function (d) { return opt(d.key, d.label); }).join('') + '</select>';
    }
    return h + '</div>';
  }

  function measureLabel(m) {
    var src = SRC[m.source];
    var x = src && src.measures.filter(function (y) { return y.key === m.measure; })[0];
    return x ? x.label : '';
  }

  function drawPanel() {
    var b = byId(S.sel);
    if (!b) {
      panel.innerHTML = '<h3>Box settings</h3><p class="dz-none">Click a box to change it, or add one from the left.</p>' +
        '<h3>Ideas</h3><ul class="dz-none"><li>Trips, filtered to "India → abroad", grouped by "Flying to (country)".</li>' +
        '<li>Insurance quotes by month, split by plan.</li><li>Website visitors over time, with sign-ups as a second line.</li>' +
        '<li>Visitors right now, by country, as a live counter.</li></ul>';
      return;
    }
    var h = '<div class="dz-err" id="dz-err" hidden></div>';
    h += field('Title', '<input type="text" data-k="title" maxlength="90" value="' + esc(b.title || '') + '" placeholder="' + esc(b._title || 'Its title') + '"/>',
      b.chart === 'text' ? '' : 'Empty: a title made from what it counts.');
    var ok = allowed(b);
    h += '<h3>Draw it as</h3><div class="dz-charts">' + CAT.charts.map(function (c) {
      if (c.key === 'live' && !(srcOf(b) && srcOf(b).live) && !noData(b.chart)) return '';
      return '<button type="button" data-chart="' + c.key + '" class="' + (b.chart === c.key ? 'on' : '') + '" title="' + esc(c.label) +
        (ok.indexOf(c.key) < 0 ? ' (changes how it is grouped)' : '') + '"><i class="fa-solid ' + c.icon + '"></i>' + esc(c.label.split(' (')[0]) + '</button>';
    }).join('') + '</div>';
    if (b.chart === 'text') {
      h += field('Words', '<textarea data-k="body" maxlength="2000">' + esc(b.body || '') + '</textarea>', 'The first line is the heading; the rest are lines under it.');
    } else if (b.chart === 'quotes') {
      h += field('How many reviews', '<input type="number" data-k="top" min="1" max="20" value="' + (b.top || 6) + '"/>', 'The newest published reviews with words in them.');
    } else if (b.chart === 'links') {
      h += '<p class="dz-none">The public address of each service, to put in a post or under a video.</p>';
    } else {
      var src = srcOf(b);
      h += '<h3>Count</h3>' + b.metrics.map(function (m, i) { return metricHtml(b, m, i); }).join('');
      if (b.metrics.length < CAT.max_metrics && !b.split && !(src && src.live)) {
        h += '<button type="button" class="dz-link" data-act="add-metric">+ Add another number (another line or bar)</button>';
      }
      h += '<h3>Split it</h3>' + field('Group by', groupSelect(b), b.group === 'auto' ? 'Days for a month, weeks for a quarter, months for a year.' : '');
      h += field('Then split by', splitSelect(b), 'One colour per group: trips a month, one colour per direction.');
      if (kindOf(b) === 'cat') h += field('Show the top', '<input type="number" data-k="top" min="0" max="50" value="' + (b.top || 0) + '"/>', '0 shows every group.');
      if (!(src && src.live)) {
        h += field('Dates', rangeSelect(b), 'The dashboard\'s dates follow the date picker; any other choice is fixed.');
        h += '<label class="dz-check"><input type="checkbox" data-k="compare"' + (b.compare !== false ? ' checked' : '') + '/> Compare with the days before</label>';
      }
      h += field('When there is nothing to show', '<input type="text" data-k="empty" maxlength="120" value="' + esc(b.empty || '') + '" placeholder="Nothing in these dates yet."/>');
    }
    if (b.chart !== 'text') {
      h += '<h3>Look</h3>' + field('Colours', '<select data-k="colour">' + CAT.colours.map(function (c) {
        return opt(c, { brand: 'Ours (blue)', ocean: 'Ocean', sunset: 'Sunset', forest: 'Forest', berry: 'Berry', mono: 'Grey' }[c] || c, b.colour === c);
      }).join('') + '</select>');
      h += field('A note (the ⓘ beside the title)', '<input type="text" data-k="note" maxlength="200" value="' + esc(b.note || '') + '"/>');
    }
    h += '<h3>Size and place</h3><div class="dz-row4">' +
      ['x', 'y', 'w', 'h'].map(function (k) {
        var lbl = { x: 'Column', y: 'Row', w: 'Width', h: 'Height' }[k];
        return '<label>' + lbl + '<input type="number" data-k="' + k + '" value="' + (k === 'x' || k === 'y' ? b[k] + 1 : b[k]) + '" min="1"/></label>';
      }).join('') + '</div><p class="hint dz-none">12 columns across; a row is a finger tall.</p>';
    h += '<div class="dzl-acts"><button type="button" class="mk-btn sm" data-act="copy"><i class="fa-regular fa-copy"></i> Copy</button>' +
      '<button type="button" class="mk-btn sm quiet danger" data-act="del"><i class="fa-regular fa-trash-can"></i> Delete</button></div>';
    panel.innerHTML = h;
    loadFilters(b);
  }

  function loadFilters(b) {
    panel.querySelectorAll('.dz-filter').forEach(function (f) {
      var i = +f.getAttribute('data-m'), dim = f.getAttribute('data-dim'), m = b.metrics[i];
      var key = m.source + '|' + dim;
      var paint = function (values) {
        var chosen = m.filters[dim] || [];
        var all = values.slice();
        chosen.forEach(function (v) { if (all.indexOf(v) < 0) all.unshift(v); });
        f.querySelector('.dz-vals').innerHTML = all.length ? all.map(function (v) {
          return '<label><input type="checkbox" value="' + esc(v) + '"' + (chosen.indexOf(v) >= 0 ? ' checked' : '') + '/>' + esc(v) + '</label>';
        }).join('') : '<span class="hint">Nothing to choose from yet.</span>';
      };
      if (optionCache[key]) { paint(optionCache[key]); return; }
      fetch(URLS.options + '?' + new URLSearchParams({ source: m.source, dim: dim }), { credentials: 'same-origin', headers: { Accept: 'application/json' } })
        .then(function (r) { return r.json(); })
        .then(function (r) {
          if (!r.ok) { f.querySelector('.dz-vals').innerHTML = '<span class="hint">' + esc(r.error || 'Could not be listed.') + '</span>'; return; }
          optionCache[key] = r.values; paint(r.values);
        }).catch(function () { f.querySelector('.dz-vals').textContent = 'Could not be listed.'; });
    });
  }

  // ------------------------------------------------------------------------------------------- changing a box

  function defaultMetric(sourceKey) {
    var s = SRC[sourceKey] || CAT.sources[0];
    return { source: s.key, measure: s.measures[0].key, date: s.dates[0].key, filters: {}, label: '' };
  }

  function fitGroup(b) {
    // after the numbers change: keep a grouping all of them still have
    var grains = common(b, 'grains').map(function (g) { return g.key; });
    var dims = common(b, 'dims').map(function (d) { return d.key; });
    if (b.group && isGrain(b.group) && grains.indexOf(b.group) < 0) b.group = grains.length ? 'auto' : '';
    if (b.group && !isGrain(b.group) && dims.indexOf(b.group) < 0) b.group = '';
    if (b.split && (b.metrics.length > 1 || (srcOf(b).dims.map(function (d) { return d.key; }).indexOf(b.split) < 0))) b.split = '';
  }

  function setChart(b, chart) {
    var src = srcOf(b);
    if (noData(chart)) { b.chart = chart; if (chart === 'text' && !b.body) b.body = b.title || 'A heading'; return; }
    if (!b.metrics || !b.metrics.length) b.metrics = [defaultMetric('trips')];
    src = srcOf(b);
    if (chart === 'live' && !src.live) { b.metrics = [defaultMetric('website_now')]; b.group = 'device'; b.split = ''; src = srcOf(b); }
    if (src.live && chart !== 'live' && isGrain(b.group)) b.group = '';
    var kind = kindOf(b);
    if ((chart === 'line' || chart === 'area') && kind !== 'time') b.group = src.grains.length ? 'auto' : b.group;
    if ((chart === 'pie' || chart === 'donut' || chart === 'hbar') && kind !== 'cat') {
      var d = common(b, 'dims')[0];
      b.group = d ? d.key : '';
      if (chart !== 'hbar') b.split = '';
    }
    if (chart === 'stacked') {
      if (!b.group) b.group = src.grains.length ? 'auto' : (src.dims[0] || {}).key || '';
      if (!b.split && b.metrics.length === 1) {
        var other = src.dims.filter(function (x) { return x.key !== b.group; })[0];
        b.split = other ? other.key : '';
      }
    }
    if ((chart === 'pie' || chart === 'donut') && b.metrics.length > 1) b.metrics = b.metrics.slice(0, 1);
    if (chart === 'number' && b.h > 3 && b.w <= 4) b.h = 2;
    b.chart = chart;
  }

  function changed(b, structural) {
    touch();
    if (structural) { redrawBox(b); drawPanel(); }
    else {
      var el = grid.querySelector('[data-id="' + b.id + '"]');
      var h = el && el.querySelector('.mk-box-h h2');
      if (h) h.textContent = title(b);
      preview(b, el);
    }
  }

  panel.addEventListener('input', function (e) {
    var b = byId(S.sel), t = e.target;
    if (!b) return;
    var k = t.getAttribute('data-k'), mk = t.getAttribute('data-mk');
    if (k === 'title' || k === 'note' || k === 'empty' || k === 'body') { b[k] = t.value; changed(b, false); }
    else if (mk === 'label') { b.metrics[+t.getAttribute('data-m')].label = t.value; changed(b, false); }
  });

  panel.addEventListener('change', function (e) {
    var b = byId(S.sel), t = e.target;
    if (!b) return;
    var k = t.getAttribute('data-k'), mk = t.getAttribute('data-mk');
    if (t.closest('.dz-vals')) {
      var f = t.closest('.dz-filter'), m = b.metrics[+f.getAttribute('data-m')], dim = f.getAttribute('data-dim');
      m.filters[dim] = Array.prototype.map.call(f.querySelectorAll('input:checked'), function (i) { return i.value; });
      changed(b, false);
      return;
    }
    if (t.getAttribute('data-act') === 'add-filter') {
      var mi = +t.getAttribute('data-m');
      if (t.value) { b.metrics[mi].filters[t.value] = []; changed(b, true); }
      return;
    }
    if (mk) {
      var m2 = b.metrics[+t.getAttribute('data-m')];
      if (mk === 'source') {
        var fresh = defaultMetric(t.value);
        fresh.label = m2.label;
        b.metrics[+t.getAttribute('data-m')] = fresh;
        if (SRC[t.value].live) { b.metrics = [fresh]; b.group = 'device'; b.split = ''; b.chart = 'live'; b.range = 'page'; }
        else if (b.chart === 'live') b.chart = 'number';
        fitGroup(b);
        if (allowed(b).indexOf(b.chart) < 0) setChart(b, allowed(b)[0]);
      } else if (mk === 'measure' || mk === 'date') {
        m2[mk] = t.value;
      }
      changed(b, true);
      return;
    }
    if (k === 'group') {
      b.group = t.value;
      if (b.split === b.group) b.split = '';
      if (allowed(b).indexOf(b.chart) < 0) b.chart = kindOf(b) === 'time' ? 'line' : (kindOf(b) === 'cat' ? 'hbar' : 'number');
      changed(b, true);
    } else if (k === 'split') {
      b.split = t.value;
      if (b.split && (b.chart === 'pie' || b.chart === 'donut')) b.chart = 'stacked';
      changed(b, true);
    } else if (k === 'range' || k === 'colour') {
      b[k] = t.value;
      changed(b, k === 'colour');
    } else if (k === 'compare') {
      b.compare = t.checked; changed(b, false);
    } else if (k === 'top') {
      b.top = clamp(t.value, b.chart === 'quotes' ? 1 : 0, b.chart === 'quotes' ? 20 : 50); changed(b, false);
    } else if (k === 'x' || k === 'y' || k === 'w' || k === 'h') {
      if (k === 'x') b.x = clamp(t.value - 1, 0, 11);
      if (k === 'y') b.y = clamp(t.value - 1, 0, 400);
      if (k === 'w') b.w = clamp(t.value, 1, 12);
      if (k === 'h') b.h = clamp(t.value, 1, MAX_H);
      b.w = Math.min(b.w, 12 - b.x);
      pack(b.id); placeAll(); touch(); drawPanel();
    }
  });

  panel.addEventListener('click', function (e) {
    var b = byId(S.sel), t = e.target.closest('button');
    if (!b || !t) return;
    var chart = t.getAttribute('data-chart'), act = t.getAttribute('data-act');
    if (chart) { setChart(b, chart); fitGroup(b); changed(b, true); return; }
    if (act === 'add-metric') {
      var src = srcOf(b), next = CAT.sources.filter(function (s) { return s.kind === src.kind && !s.live && s.key !== src.key; })[0] || src;
      b.metrics.push(defaultMetric(next.key));
      b.split = '';
      if (!isGrain(b.group)) b.group = 'auto';
      if (b.chart === 'pie' || b.chart === 'donut' || b.chart === 'number') b.chart = 'line';
      fitGroup(b); changed(b, true);
    } else if (act === 'rm-metric') {
      b.metrics.splice(+t.getAttribute('data-m'), 1); fitGroup(b); changed(b, true);
    } else if (act === 'rm-filter') {
      var f = t.closest('.dz-filter');
      delete b.metrics[+f.getAttribute('data-m')].filters[f.getAttribute('data-dim')];
      changed(b, true);
    } else if (act === 'copy') copyBox(b);
    else if (act === 'del') deleteBox(b);
  });

  // ------------------------------------------------------------------------------------------- boxes in and out

  function select(id) {
    S.sel = id;
    grid.querySelectorAll('.mk-box').forEach(function (el) { el.classList.toggle('sel', el.getAttribute('data-id') === id); });
    drawPanel();
  }

  function addBox(b) {
    b = clone(b);
    b.id = uid();
    b.x = 0;
    b.y = bottom();
    b.w = Math.min(b.w || 4, 12);
    if (!S.boxes.length) grid.innerHTML = '';
    S.boxes.push(b);
    pack(b.id);
    var el = frame(b);
    grid.appendChild(el);
    preview(b, el, true);
    select(b.id);
    touch();
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  function copyBox(b) {
    var c = clone(wire(b));
    c.title = c.title ? (c.title + ' (copy)').slice(0, 90) : '';
    addBox(c);
  }

  function deleteBox(b) {
    if (!confirm('Delete the box "' + title(b) + '"?')) return;
    S.boxes = S.boxes.filter(function (x) { return x !== b; });
    var el = grid.querySelector('[data-id="' + b.id + '"]');
    if (el) el.remove();
    if (!S.boxes.length) drawAll();
    select(null);
    touch();
  }

  // the "Add a box" list
  (function () {
    var holder = document.getElementById('dz-sugs'), groups = {}, order = [];
    DATA.suggestions.forEach(function (s, i) { if (!groups[s.group]) { groups[s.group] = []; order.push(s.group); } groups[s.group].push(i); });
    holder.innerHTML = order.map(function (g) {
      return '<h3>' + esc(g) + '</h3><div class="dz-sugs">' + groups[g].map(function (i) {
        var s = DATA.suggestions[i], src = s.box.metrics && s.box.metrics[0] ? SRC[s.box.metrics[0].source] : null;
        var icon = src ? src.icon : (CH[s.box.chart] || {}).icon || 'fa-square';
        return '<button type="button" class="dz-sug" data-sug="' + i + '"><i class="fa-solid ' + icon + '" aria-hidden="true"></i>' + esc(s.name) + '</button>';
      }).join('') + '</div>';
    }).join('');
    root.querySelector('.dz-side').addEventListener('click', function (e) {
      var t = e.target.closest('.dz-sug');
      if (!t) return;
      if (t.hasAttribute('data-blank')) {
        addBox({ chart: 'number', title: '', metrics: [defaultMetric('trips')], group: 'auto', split: '', range: 'page', top: 10,
          compare: true, colour: 'brand', note: '', empty: '', w: 3, h: 2 });
      } else addBox(DATA.suggestions[+t.getAttribute('data-sug')].box);
    });
  })();

  // ------------------------------------------------------------------------------------------- drag, resize, keys

  var drag = null;
  grid.addEventListener('pointerdown', function (e) {
    var el = e.target.closest('.mk-box');
    if (!el) return;
    var b = byId(el.getAttribute('data-id'));
    if (e.target.closest('.dz-tools button')) {
      var act = e.target.closest('button').getAttribute('data-act');
      e.preventDefault();
      if (act === 'copy') copyBox(b); else if (act === 'del') deleteBox(b);
      return;
    }
    if (S.sel !== b.id) select(b.id);
    var resize = !!e.target.closest('.dz-resize');
    var handle = e.target.closest('.mk-box-h') || (b.chart === 'text' && e.target.closest('.mk-box-b'));
    if (!resize && !handle) return;
    e.preventDefault();
    var rect = grid.getBoundingClientRect();
    drag = { b: b, el: el, resize: resize, x0: e.clientX, y0: e.clientY, bx: b.x, by: b.y, bw: b.w, bh: b.h,
      col: (rect.width - 11 * GAP) / 12 };
    el.setPointerCapture(e.pointerId);
    el.classList.add('dragging');
  });
  grid.addEventListener('pointermove', function (e) {
    if (!drag) return;
    var dx = Math.round((e.clientX - drag.x0) / (drag.col + GAP)), dy = Math.round((e.clientY - drag.y0) / (ROW + GAP));
    var b = drag.b;
    if (drag.resize) { b.w = clamp(drag.bw + dx, 1, 12 - b.x); b.h = clamp(drag.bh + dy, 1, MAX_H); }
    else { b.x = clamp(drag.bx + dx, 0, 12 - b.w); b.y = Math.max(0, drag.by + dy); }
    place(drag.el, b);
  });
  function endDrag() {
    if (!drag) return;
    var d = drag, b = d.b;
    drag = null;
    d.el.classList.remove('dragging');
    if (b.x !== d.bx || b.y !== d.by || b.w !== d.bw || b.h !== d.bh) { pack(b.id); placeAll(); touch(); drawPanel(); }
  }
  grid.addEventListener('pointerup', endDrag);
  grid.addEventListener('pointercancel', endDrag);
  grid.addEventListener('keydown', function (e) {
    var el = e.target;
    if (!el.classList || !el.classList.contains('mk-box')) return;
    var b = byId(el.getAttribute('data-id'));
    var step = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key];
    if (e.key === 'Enter') { select(b.id); return; }
    if (!step) return;
    e.preventDefault();
    if (e.shiftKey) { b.w = clamp(b.w + step[0], 1, 12 - b.x); b.h = clamp(b.h + step[1], 1, MAX_H); }
    else { b.x = clamp(b.x + step[0], 0, 12 - b.w); b.y = Math.max(0, b.y + step[1]); }
    pack(b.id); placeAll(); touch(); if (S.sel === b.id) drawPanel();
    el.focus();
  });

  // ------------------------------------------------------------------------------------------- save, publish

  function save(publish) {
    say(publish ? 'Publishing…' : 'Saving…');
    var body = { name: document.getElementById('dz-name').value, audience: document.getElementById('dz-aud').value,
      range_key: document.getElementById('dz-opens').value, boxes: S.boxes.map(wire), publish: !!publish };
    return post(URLS.save, body).then(function (r) {
      if (!r.ok) { say(r.error || 'Not saved.', true); return false; }
      var mine = JSON.stringify(S.boxes.map(wire));
      if (JSON.stringify(r.boxes) !== mine) {
        var titles = {};
        S.boxes.forEach(function (b) { titles[b.id] = b._title; });
        S.boxes = r.boxes;
        S.boxes.forEach(function (b) { b._title = titles[b.id]; });
        drawAll();
        if (S.sel && !byId(S.sel)) select(null); else drawPanel();
      }
      S.dirty = false;
      S.published = r.published;
      S.changes = r.changes;
      stateChip();
      say((publish ? 'Published at ' : 'Saved at ') + r.saved);
      return true;
    });
  }

  document.getElementById('dz-save').addEventListener('click', function () { save(false); });
  document.getElementById('dz-publish').addEventListener('click', function () {
    if (!S.boxes.length) { say('Add at least one box before publishing.', true); return; }
    save(true);
  });
  document.getElementById('dz-view').addEventListener('click', function (e) {
    if (!S.dirty) return;
    e.preventDefault();
    var w = window.open('', '_blank');
    var href = this.href;
    save(false).then(function (ok) { if (ok && w) w.location = href; else if (w) w.close(); });
  });
  ['dz-name', 'dz-aud', 'dz-opens'].forEach(function (id) {
    document.getElementById(id).addEventListener('change', touch);
  });
  rangeSel.addEventListener('change', function () { S.boxes.forEach(function (b) { preview(b, null, true); }); });
  window.addEventListener('beforeunload', function (e) {
    if (S.dirty) { e.preventDefault(); e.returnValue = ''; }
  });
  document.addEventListener('keydown', function (e) {
    if ((e.ctrlKey || e.metaKey) && e.key === 's') { e.preventDefault(); save(false); }
  });

  stateChip();
  drawAll();
  drawPanel();
})();
