/* Canada quotes page (templates/insurance/canada_quotes.html).

   Everything comes from #cqData, which the server built from Secure Travel's calculators a moment ago
   (routes/insurance.py: canada_quotes). Each traveller is priced for both answers to "pre-existing
   condition?", so changing one person's answer, a filter or the search re-draws the page without asking
   the server. Each traveller gets their own pick (one may want Standard, the other Enhanced): the tables show
   the price of the traveller being picked for. A pick is only a key (cover|plan|limit|deductible): the server
   prices it again for that traveller when the call back is requested, so what reaches our agent is never a
   number the browser made up. */
(function () {
  const dataEl = document.getElementById('cqData');
  if (!dataEl) return;
  const D = JSON.parse(dataEl.textContent || '{}');
  const $ = (s, root) => (root || document).querySelector(s);
  const $$ = (s, root) => [...(root || document).querySelectorAll(s)];
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const money = n => (n == null ? '—' : '$' + Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
  const round2 = n => Math.round(n * 100 + 1e-9) / 100;
  const csrf = () => ($('meta[name="csrf-token"]') || {}).content || '';
  const TICK = '<svg viewBox="0 0 24 24"><path d="M5 12l4 4 10-10"/></svg>';

  const books = D.books || {};
  const PRODUCTS = ['super_visa', 'visitors'].filter(p => books[p]);
  const usable = p => books[p] && !books[p].error;
  const people = (D.travellers || []).map(t => ({ age: +t.age }));
  const many = people.length > 1;
  // Table (a price grid per plan) on a desk, Cards on a phone; the visitor's own choice is remembered
  let savedView = null;
  try { savedView = window.localStorage.getItem('cq.view'); } catch (e) { savedView = null; }
  let picksInView = false;          // the picks box is on screen: the bar at the bottom is not needed
  const state = {
    view: savedView === 'table' || savedView === 'cards' ? savedView : (window.innerWidth >= 1100 ? 'table' : 'cards'),
    product: usable(D.cover) ? D.cover : (PRODUCTS.find(usable) || D.cover || 'super_visa'),
    pre: (D.travellers || []).map(t => (t.pre === 'y' ? 'y' : 'n')),
    limits: new Set(), deds: new Set(), pay: 'once', sort: 'cover', q: '',
    picks: new Map(),               // traveller (0, 1, ...) -> {product, plan, limit, deductible}
    who: 0,                         // the traveller being picked for: the tables show their prices
    callback: D.callback || null,
  };
  const key = (product, plan, limit, ded) => [product, plan, limit, ded].join('|');
  const pickKey = p => key(p.product, p.plan, p.limit, p.deductible);
  (D.picks || []).forEach(p => {
    const pick = { product: p.product, plan: p.plan, limit: String(p.limit), deductible: +p.deductible };
    // a pick saved before each traveller had their own was for everybody together
    (p.traveller == null ? people.map((_, i) => i) : [+p.traveller])
      .forEach(i => { if (i < people.length) state.picks.set(i, Object.assign({}, pick)); });
  });
  const firstOpen = () => people.findIndex((_, i) => !state.picks.has(i));
  state.who = Math.max(firstOpen(), 0);
  const isMine = k => state.picks.has(state.who) && pickKey(state.picks.get(state.who)) === k;
  const pickedBy = k => [...state.picks.entries()].filter(([, p]) => pickKey(p) === k).map(([i]) => i);

  /* ------------------------------------------------------------------ prices */
  /* `total` is everybody on this option together; `price` and `monthly` are traveller i's own. */
  function row(product, plan, lim, ded, i) {
    const b = books[product];
    const each = b.people.map((p, j) => {
      const byPre = p.prices[state.pre[j] || 'n'] || {};
      return (((byPre[plan] || {})[lim.code] || {})[String(ded.value)]);
    });
    const ok = each.every(x => x != null);
    const total = ok ? round2(each.reduce((a, x) => a + x, 0)) : null;
    const price = each[i == null ? state.who : i];
    const monthlyOk = !!(b.monthly && b.monthly.limits.indexOf(lim.code) > -1);
    const monthly = price != null && monthlyOk ? round2(price / (b.monthly.months || 12)) : null;
    return { each, total, price: price == null ? null : price, monthlyOk, monthly };
  }

  function limitOf(product, plan, code) {
    return ((books[product].limits[plan] || []).find(l => l.code === String(code))) || { code: String(code), label: code, amount: 0 };
  }
  function dedOf(product, value) {
    return (books[product].deductibles || []).find(d => d.value === +value) || { value: +value, label: '$' + value };
  }
  const planLabel = plan => (plan === 'e' ? 'Enhanced' : 'Standard');
  const dayWord = n => n + (n === 1 ? ' day' : ' days');
  const daysText = b => (b.product === 'super_visa' || b.days === 365 ? 'a year' : 'for ' + dayWord(b.days));
  const who = i => 'Traveller ' + (i + 1) + ' · ' + people[i].age;
  const allOn = people.length === 2 ? 'Both on this' : 'All ' + people.length + ' on this';
  $('#cqPickHint').textContent = many
    ? 'One pick for each traveller, and each can have a different plan. Choose a traveller, then tap a price in either plan.'
    : 'Tap any price in either plan to pick it.';

  /* ------------------------------------------------------------------ search */
  function tokens() {
    return state.q.toLowerCase().replace(/[$,]/g, '').split(/\s+/).filter(Boolean).map(t => {
      const m = t.match(/^(\d+(?:\.\d+)?)(k|m)$/);
      return m ? String(Math.round(parseFloat(m[1]) * (m[2] === 'k' ? 1e3 : 1e6))) : t;
    });
  }
  function matches(toks, plan, lim, ded, r) {
    if (!toks.length) return true;
    const nums = [String(lim.amount), String(ded.value)];
    if (r.price != null) nums.push(r.price.toFixed(2), String(Math.floor(r.price)));
    if (r.monthly != null) nums.push(r.monthly.toFixed(2));
    const words = [planLabel(plan), books[state.product].label, 'deductible', r.monthlyOk ? 'monthly' : '',
      lim.label, ded.label].join(' ').toLowerCase().replace(/[$,]/g, '');
    return toks.every(t => (/^\d+(\.\d+)?$/.test(t) ? nums.some(n => n.indexOf(t) === 0) : words.indexOf(t) > -1));
  }

  /* ------------------------------------------------------------------ the two columns */
  function renderPlan(plan) {
    const list = $('.cq-list[data-plan="' + plan + '"]');
    const count = $('[data-count="' + plan + '"]');
    const b = books[state.product];
    if (!b || b.error) {
      list.innerHTML = '<div class="cq-error">' + esc((b && b.error) || 'This cover could not be priced just now.') +
        '<br>Ask for a call back and our agent will give you the prices.</div>';
      count.textContent = '';
      return;
    }
    if (state.view === 'table') { renderTable(plan, list, count, b); return; }
    const toks = tokens();
    const lims = (b.limits[plan] || []).filter(l => !state.limits.size || state.limits.has(l.code));
    const deds = b.deductibles.filter(d => !state.deds.size || state.deds.has(d.value));
    let cards = lims.map(lim => {
      const rows = deds.map(ded => Object.assign({ lim, ded }, row(state.product, plan, lim, ded)))
        .filter(r => matches(toks, plan, lim, r.ded, r));
      const priced = rows.filter(r => r.price != null).map(r => r.price);
      return { lim, rows, min: priced.length ? Math.min.apply(null, priced) : Infinity };
    }).filter(c => c.rows.length);
    if (state.sort === 'cover-desc') cards.reverse();
    if (state.sort === 'price') cards.sort((a, b2) => a.min - b2.min);
    const low = Math.min.apply(null, cards.map(c => c.min).concat([Infinity]));
    const offered = cards.reduce((n, c) => n + c.rows.filter(r => r.price != null).length, 0);
    count.textContent = offered + (offered === 1 ? ' option' : ' options');
    if (!cards.length) {
      list.innerHTML = '<div class="cq-empty">Nothing matches these filters.<br><button type="button" class="cq-link" data-reset>Clear the filters</button></div>';
      return;
    }
    list.innerHTML = forWhom() + cards.map(c => {
      const hasLow = c.min === low && low !== Infinity;
      return '<article class="cq-card">' +
        '<div class="cq-card-hd"><span class="cq-limit">' + esc(c.lim.label) +
        '<small>Emergency medical · ' + esc(daysText(b)) + '</small></span><span class="cq-badges">' +
        (state.product === 'super_visa' ? '<span class="cq-badge sv">Super visa ready</span>' : '') +
        (hasLow ? '<span class="cq-badge low">Lowest price</span>' : '') + '</span></div>' +
        '<div class="cq-rows">' + c.rows.map(r => rowHtml(b, plan, c.lim, r, r.price != null && r.price === low)).join('') + '</div>' +
        '</article>';
    }).join('');
  }

  /* Over each plan's prices: whose they are. With several travellers, the price a pick costs is that
     traveller's own, so the page says whose prices these are where the eye is. */
  function forWhom() {
    if (!many) return '';
    return '<p class="cq-for' + (whoMoved ? ' is-new' : '') + '"><span>Prices for</span><b>' + esc(who(state.who)) +
      (state.pre[state.who] === 'y' ? ' · pre-existing' : '') + '</b><span class="cq-for-n">' +
      'picking ' + (state.who + 1) + ' of ' + people.length + '</span></p>';
  }

  /* The travellers who picked this price, as small numbered marks on it (the one being picked for shows a tick). */
  function tags(k) {
    const by = many ? pickedBy(k).filter(i => i !== state.who) : [];
    return by.length ? '<span class="cq-tags" aria-hidden="true">' + by.map(i => '<i>' + (i + 1) + '</i>').join('') + '</span>' : '';
  }

  /* The table: one row per policy limit, one column per deductible, every price at a glance. Filters take
     rows and columns away; the search dims what does not match, so the grid keeps its shape. */
  function renderTable(plan, list, count, b) {
    const toks = tokens();
    const lims = (b.limits[plan] || []).filter(l => !state.limits.size || state.limits.has(l.code));
    const deds = b.deductibles.filter(d => !state.deds.size || state.deds.has(d.value));
    let rows = lims.map(lim => {
      const cells = deds.map(ded => {
        const c = Object.assign({ lim, ded }, row(state.product, plan, lim, ded));
        c.hit = matches(toks, plan, lim, ded, c);
        return c;
      });
      const priced = cells.filter(c => c.price != null && c.hit).map(c => c.price);
      return { lim, cells, min: priced.length ? Math.min.apply(null, priced) : Infinity, any: cells.some(c => c.hit) };
    }).filter(r => r.any);
    if (state.sort === 'cover-desc') rows.reverse();
    if (state.sort === 'price') rows.sort((a, z) => a.min - z.min);
    const low = Math.min.apply(null, rows.map(r => r.min).concat([Infinity]));
    const offered = rows.reduce((n, r) => n + r.cells.filter(c => c.price != null && c.hit).length, 0);
    count.textContent = offered + (offered === 1 ? ' option' : ' options');
    if (!rows.length || !deds.length) {
      list.innerHTML = '<div class="cq-empty">Nothing matches these filters.<br><button type="button" class="cq-link" data-reset>Clear the filters</button></div>';
      return;
    }
    const unit = state.pay === 'monthly' ? 'a month' : (b.product === 'super_visa' || b.days === 365 ? 'a year' : dayWord(b.days));
    list.innerHTML = forWhom() + '<div class="cq-tbl"><div class="cq-tbl-scroll"><table>' +
      '<caption class="cq-tbl-cap">' + esc(planLabel(plan)) + ' plan prices, ' + esc(unit) + (many ? ', ' + esc(who(state.who)) : '') + '</caption>' +
      '<thead><tr><th scope="col" class="cq-tbl-corner"><span>Deductible</span><b>Cover</b></th>' +
      deds.map(d => '<th scope="col">' + esc(d.label) + '</th>').join('') + '</tr></thead><tbody>' +
      rows.map(r => '<tr><th scope="row"><b>' + esc(r.lim.label) + '</b>' +
        (state.product === 'super_visa' ? '<small>Super visa ready</small>' : '') + '</th>' +
        r.cells.map(c => cellHtml(b, plan, r.lim, c, c.price != null && c.price === low && c.hit)).join('') + '</tr>').join('') +
      '</tbody></table></div><p class="cq-tbl-detail" data-detail="' + plan + '"></p></div>';
    showDetail(plan, null);
  }

  function cellHtml(b, plan, lim, c, isLow) {
    const k = key(state.product, plan, lim.code, c.ded.value);
    if (c.price == null) {
      return '<td><span class="cq-cell is-na" title="Not offered for ' + esc(who(state.who)) + '">—</span></td>';
    }
    const picked = isMine(k);
    const monthly = state.pay === 'monthly';
    const main = monthly ? (c.monthlyOk ? money(c.monthly) : money(c.price)) : money(c.price);
    const sub = monthly ? (c.monthlyOk ? 'a month' : 'full price') : money(round2(c.price / b.days)) + '/day';
    return '<td><button type="button" class="cq-cell' + (picked ? ' is-picked' : '') + (isLow ? ' is-low' : '') +
      (c.hit ? '' : ' is-dim') + '" data-key="' + esc(k) + '" aria-pressed="' + picked + '" aria-label="' +
      esc(planLabel(plan) + ', ' + lim.label + ' cover, ' + c.ded.label + ' deductible: ' + money(c.price) +
        (many ? ' for ' + who(state.who) : '')) + '">' +
      (isLow ? '<i class="cq-low">Lowest</i>' : '') + tags(k) + '<b>' + main + '</b><small>' + esc(sub) + '</small></button></td>';
  }

  /* Under each table: the price under the pointer (or this traveller's pick), and with several travellers
     what everybody on that same option would come to. */
  function showDetail(plan, k) {
    const el = $('[data-detail="' + plan + '"]');
    if (!el) return;
    if (!k) {
      const mine = state.picks.get(state.who);
      k = mine && mine.product === state.product && mine.plan === plan ? pickKey(mine) : '';
    }
    if (!k) {
      el.innerHTML = '<span class="cq-tbl-hint">Tap a price to pick it' + (many ? ' for ' + esc(who(state.who)) : '') +
        '. Point at one to see it in full.</span>';
      return;
    }
    const [product, p, limit, ded] = k.split('|');
    const b = books[product];
    const r = row(product, p, limitOf(product, p, limit), dedOf(product, ded));
    if (r.price == null) { el.textContent = ''; return; }
    const head = '<b>' + esc(planLabel(p) + ' · ' + limitOf(product, p, limit).label + ' · ' + dedOf(product, ded).label + ' deductible') + '</b>';
    const each = many
      ? '<span>' + esc(who(state.who)) + '</span>' + (r.total != null ? '<span>' + allOn + ': <b>' + money(r.total) + '</b></span>' : '')
      : '<span>' + money(round2(r.price / b.days)) + ' a day</span>';
    const monthly = r.monthlyOk ? '<span>or ' + money(r.monthly) + ' a month + ' + money(b.monthly.fee).replace('.00', '') + ' once</span>' : '';
    el.innerHTML = head + '<span class="cq-tbl-total">' + money(r.price) + '</span>' + each + monthly;
  }

  function rowHtml(b, plan, lim, r, isLow) {
    const k = key(state.product, plan, lim.code, r.ded.value);
    const picked = isMine(k);
    const na = r.price == null;
    let price, each;
    if (na) {
      price = 'Not offered';
      each = 'Not offered for ' + who(state.who) + (state.pre[state.who] === 'y' ? ' with a pre-existing condition' : '') + '.';
    } else {
      if (state.pay === 'monthly') {
        price = r.monthlyOk ? money(r.monthly) + '<small>a month + ' + money(b.monthly.fee).replace('.00', '') + ' once</small>'
                            : money(r.price) + '<small>monthly not offered</small>';
      } else {
        price = money(r.price) + '<small>' + esc(daysText(b)) + (many ? ' · traveller ' + (state.who + 1) : '') + '</small>';
      }
      each = many
        ? esc(who(state.who)) + (r.total != null ? ' · ' + allOn + ': <b>' + money(r.total) + '</b>' : '')
        : money(round2(r.price / b.days)) + ' a day';
    }
    return '<button type="button" class="cq-row' + (picked ? ' is-picked' : '') + (na ? ' is-na' : '') + (isLow ? ' is-low' : '') +
      '" data-key="' + esc(k) + '" aria-pressed="' + picked + '"' + (na ? ' aria-disabled="true"' : '') + '>' +
      '<span class="cq-tickbox" aria-hidden="true">' + TICK + '</span>' +
      '<span class="cq-ded">' + esc(r.ded.label) + ' deductible' + (r.ded.value === 0 ? ' <small>· nothing to pay first</small>' : '') + tags(k) + '</span>' +
      '<span class="cq-amt">' + price + '</span>' +
      '<span class="cq-each">' + each + '</span></button>';
  }

  /* ------------------------------------------------------------------ the middle panel */
  function renderProducts() {
    $('#cqProduct').innerHTML = PRODUCTS.map(p => {
      const b = books[p];
      const sub = p === 'super_visa' ? '1 year · $100k+' : (b.days ? dayWord(b.days) : '');
      return '<button type="button" role="radio" data-product="' + p + '" aria-pressed="' + (state.product === p) + '"' +
        ' aria-checked="' + (state.product === p) + '">' + (p === 'super_visa' ? 'Super visa' : 'Visitor') +
        '<small>' + esc(sub) + '</small></button>';
    }).join('');
  }

  function renderPre() {
    const box = $('#cqPre');
    box.innerHTML = people.map((p, i) =>
      '<div class="cq-pre-row"><span>' + esc(who(i)) + '</span><div class="cq-seg" role="radiogroup" aria-label="' + esc(who(i)) + ' pre-existing condition">' +
      ['n', 'y'].map(v => '<button type="button" data-pre="' + i + '" data-v="' + v + '" aria-pressed="' + (state.pre[i] === v) + '">' +
        (v === 'y' ? 'Yes' : 'No') + '</button>').join('') + '</div></div>').join('');
    const yes = state.pre.map((v, i) => (v === 'y' ? i + 1 : 0)).filter(Boolean);
    const fact = $('[data-pre-fact]');
    if (fact) fact.textContent = yes.length ? 'Yes, traveller ' + yes.join(', ') : 'No';
  }

  function chips(el, items, set, attr) {
    el.innerHTML = '<button type="button" class="cq-chip" data-' + attr + '="" aria-pressed="' + !set.size + '">All</button>' +
      items.map(it => '<button type="button" class="cq-chip" data-' + attr + '="' + esc(it.v) + '" aria-pressed="' + set.has(it.k) + '">' + esc(it.label) + '</button>').join('');
  }
  function renderFilters() {
    const b = books[state.product];
    if (!b || b.error) { $('#cqLimits').innerHTML = ''; $('#cqDeds').innerHTML = ''; return; }
    const seen = new Map();
    Object.keys(b.limits).forEach(p => b.limits[p].forEach(l => seen.set(l.code, l)));
    chips($('#cqLimits'), [...seen.values()].map(l => ({ v: l.code, k: l.code, label: l.label.replace(',000,000', 'M').replace(',000', 'k') })), state.limits, 'limit');
    chips($('#cqDeds'), b.deductibles.map(d => ({ v: d.value, k: d.value, label: d.label })), state.deds, 'ded');
    const monthlyBtn = $('#cqPay [data-pay="monthly"]');
    monthlyBtn.disabled = !(b.monthly && b.monthly.limits.length);
    if (monthlyBtn.disabled && state.pay === 'monthly') state.pay = 'once';
    $$('#cqPay button').forEach(x => x.setAttribute('aria-pressed', String(x.dataset.pay === state.pay)));
  }

  /* Traveller i's pick, priced for them now: null when they have none. */
  function pickOf(i) {
    const p = state.picks.get(i);
    if (!p) return null;
    const b = books[p.product];
    const r = b && !b.error ? row(p.product, p.plan, limitOf(p.product, p.plan, p.limit), dedOf(p.product, p.deductible), i) : null;
    return { p, b, r, ok: !!(r && r.price != null) };
  }
  const amtOf = x => (state.pay === 'monthly' && x.r.monthlyOk ? money(x.r.monthly) + '<small>/mo</small>' : money(x.r.price));

  /* One slot per traveller: who they are, what was picked for them and its price. The slot being picked for
     is lit; choosing another slot moves the tables to that traveller's prices. */
  function slotHtml(i) {
    const x = pickOf(i);
    const on = i === state.who;
    const head = '<span class="n">' + (i + 1) + '</span><span class="who"><b>Traveller ' + (i + 1) + '</b><small>Age ' +
      people[i].age + (state.pre[i] === 'y' ? ' · pre-existing' : '') + '</small></span>';
    if (!x) {
      return '<li class="cq-slot is-open' + (on ? ' is-on' : '') + '"><button type="button" class="cq-slot-pick" data-who="' + i +
        '" aria-pressed="' + on + '">' + head + '<span class="what"><span>' +
        (on ? 'Picking now: tap a price in either plan' : 'Not picked yet · choose to pick') + '</span></span></button></li>';
    }
    const { p, b } = x;
    const lim = b && !b.error ? limitOf(p.product, p.plan, p.limit) : { label: p.limit };
    return '<li class="cq-slot ' + p.plan + (on ? ' is-on' : '') + '"><button type="button" class="cq-slot-pick" data-who="' + i +
      '" aria-pressed="' + on + '">' + head +
      '<span class="what"><b>' + esc(planLabel(p.plan)) + ' · ' + esc(lim.label) + '</b><span>' +
      esc(p.product === 'super_visa' ? 'Super visa' : 'Visitor') + ' · ' + esc(dedOf(p.product, p.deductible).label) + ' deductible</span></span>' +
      '<span class="amt">' + (x.ok ? amtOf(x) : 'Not offered') + '</span></button>' +
      (many ? '<button type="button" class="cq-slot-all" data-all="' + i + '">Same for everyone</button>' : '') +
      '<button type="button" class="cq-slot-x" data-unpick="' + i + '" aria-label="Remove the pick for Traveller ' + (i + 1) + '">&times;</button></li>';
  }

  function renderPicks() {
    const n = state.picks.size;
    const got = people.map((_, i) => pickOf(i)).filter(Boolean);
    $('#cqPickN').textContent = many ? n + ' of ' + people.length : String(n);
    $('#cqBarN').textContent = many ? n + ' of ' + people.length : String(n);
    $('#cqBarWho').innerHTML = many ? people.map((_, i) => '<button type="button" data-who="' + i + '" aria-pressed="' + (i === state.who) +
      '" class="' + (state.picks.has(i) ? 'has' : '') + '" aria-label="Pick for ' + esc(who(i)) + '">' + (i + 1) + '</button>').join('') : '';
    $('#cqBar').hidden = (!n && !many) || picksInView;
    $('#cqBar').classList.toggle('many', many);
    $('#cqPickList').classList.toggle('one', !many);
    $('#cqPickList').innerHTML = people.map((_, i) => slotHtml(i)).join('');
    // the picks together, once there are two or more to add up
    const tot = $('#cqPickTotal');
    const priced = got.filter(x => x.ok);
    tot.hidden = priced.length < 2;
    if (priced.length > 1) {
      const sum = round2(priced.reduce((a, x) => a + x.r.price, 0));
      const left = people.length - n;
      tot.innerHTML = '<span>Together</span><b>' + money(sum) + '</b>' +
        (left ? '<small>' + left + ' traveller' + (left === 1 ? '' : 's') + ' still to pick</small>' : '<small>' + (n === 2 ? 'both' : 'all ' + n) + ' travellers</small>');
    }
    $('#cqCall').firstChild.textContent = state.callback ? 'Update my request ' : 'Request a call back ';
    renderDone();
  }

  function renderDone() {
    const box = $('#cqDone');
    if (!state.callback) { box.hidden = true; return; }
    const at = new Date(state.callback.at + (state.callback.at.endsWith('Z') ? '' : 'Z'));
    box.hidden = false;
    box.innerHTML = '<div class="cq-status"><i>✓</i><span>Request received ' + esc(at.toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })) +
      '. It is in progress: our agent will contact you' + (state.callback.how === 'WhatsApp' ? ' on WhatsApp' : ' by phone') + '.</span></div>' +
      '<span>Want something else? Change your picks above and press <b>Update my request</b>.</span>';
  }

  function renderCheck() {
    const el = $('#cqCheck');
    const b = books[state.product];
    if (!b) { el.textContent = ''; return; }
    if (b.error) {
      el.className = 'cq-check bad';
      el.innerHTML = '<i>!</i>Secure Travel’s prices could not be read just now. Our agent can still call you with them.';
      return;
    }
    const at = new Date(b.checked_at);
    const mins = Math.max(0, Math.round((Date.now() - at.getTime()) / 60000));
    const ago = mins < 1 ? 'just now' : mins === 1 ? 'a minute ago' : mins < 60 ? mins + ' minutes ago' : at.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    if (b.stale) {
      el.className = 'cq-check stale';
      el.innerHTML = '<i>!</i>Showing prices read ' + esc(ago) + ': Secure Travel’s page is not answering right now.';
    } else if (b.same === false) {
      el.className = 'cq-check changed';
      el.innerHTML = '<i>↻</i>Checked live with Secure Travel ' + esc(ago) + '. Their prices changed since the check before, so these are the new ones.';
    } else {
      el.className = 'cq-check ok';
      el.innerHTML = '<i>✓</i>Checked live with Secure Travel ' + esc(ago) + (b.same === true ? ' · same as the check before' : '');
    }
  }

  function renderBenefits() {
    const rows = (books.visitors && books.visitors.benefits && books.visitors.benefits.length ? books.visitors.benefits
      : (books.super_visa && books.super_visa.benefits) || []);
    if (!rows.length) return;
    $('#cqBenefits').hidden = false;
    $('#cqBenRows').innerHTML = rows.map(([name, std, enh]) =>
      '<div class="cq-ben-row" role="row"><span role="cell">' + esc(name) + '</span>' +
      '<span role="cell" class="' + (std ? '' : 'none') + '">' + esc(std || '—') + '</span>' +
      '<span role="cell" class="' + (enh && enh !== std ? 'more' : '') + '">' + esc(enh || '—') + '</span></div>').join('');
  }

  function renderView() {
    $('#cqBoard').dataset.view = state.view;
    $$('#cqView [data-view]').forEach(x => x.setAttribute('aria-pressed', String(x.dataset.view === state.view)));
  }

  let drawnWho = null, whoMoved = false;
  function render() {
    renderView(); renderProducts(); renderPre(); renderFilters();
    whoMoved = drawnWho !== null && drawnWho !== state.who;
    drawnWho = state.who;
    renderPlan('s'); renderPlan('e');
    whoMoved = false;
    renderPicks(); renderCheck();
  }

  /* ------------------------------------------------------------------ events */
  document.addEventListener('click', e => {
    const t = e.target.closest('button');
    if (!t || !t.closest('#cq')) return;
    if (t.dataset.product) { state.product = t.dataset.product; state.limits.clear(); state.deds.clear(); render(); return; }
    if (t.dataset.pre !== undefined) { state.pre[+t.dataset.pre] = t.dataset.v; render(); return; }
    if (t.dataset.limit !== undefined) { toggle(state.limits, t.dataset.limit); render(); return; }
    if (t.dataset.ded !== undefined) { toggle(state.deds, t.dataset.ded === '' ? '' : +t.dataset.ded); render(); return; }
    if (t.dataset.pay) { if (!t.disabled) { state.pay = t.dataset.pay; render(); } return; }
    if (t.dataset.view) {
      state.view = t.dataset.view;
      try { window.localStorage.setItem('cq.view', state.view); } catch (e) { /* private window: not remembered */ }
      render();
      return;
    }
    if (t.dataset.tab) { setTab(t.dataset.tab); return; }
    if (t.dataset.who !== undefined) { pickFor(+t.dataset.who); return; }
    if (t.dataset.all !== undefined) { sameForAll(+t.dataset.all); return; }
    if (t.dataset.unpick !== undefined) { state.picks.delete(+t.dataset.unpick); state.who = +t.dataset.unpick; render(); return; }
    if (t.hasAttribute('data-reset') || t.id === 'cqReset') { resetFilters(); return; }
    if (t.classList.contains('cq-row') || t.classList.contains('cq-cell')) { togglePick(t); return; }
    if (t.id === 'cqCall' || t.hasAttribute('data-open-call')) { openCall(); return; }
    if (t.hasAttribute('data-close')) { closeCall(); return; }
  });

  function toggle(set, v) {
    if (v === '') { set.clear(); return; }
    if (set.has(v)) set.delete(v); else set.add(v);
  }
  function resetFilters() {
    state.limits.clear(); state.deds.clear(); state.q = ''; state.sort = 'cover'; state.pay = 'once';
    $('#cqSearch').value = ''; $('#cqSort').value = 'cover';
    render();
  }
  function setTab(tab) {
    $('#cqBoard').dataset.show = tab;
    $$('#cqTabs [data-tab]').forEach(b => b.setAttribute('aria-selected', String(b.dataset.tab === tab)));
  }
  /* A price tapped: it becomes the pick of the traveller being picked for (tapping their pick again takes it
     away), and the tables move on to the next traveller still without one. */
  function togglePick(btn) {
    if (btn.getAttribute('aria-disabled') === 'true') return;
    const k = btn.dataset.key;
    const i = state.who;
    if (isMine(k)) { state.picks.delete(i); render(); return; }
    const [product, plan, limit, ded] = k.split('|');
    state.picks.set(i, { product, plan, limit, deductible: +ded });
    const next = people.map((_, j) => (i + 1 + j) % people.length).find(j => !state.picks.has(j));
    if (next != null) {
      state.who = next;
      say('Picked for ' + who(i) + '. Now picking for ' + who(next) + '.');
    } else {
      say(many ? 'Picked for ' + who(i) + '. Every traveller has a pick.' : '');
    }
    render();
  }
  function pickFor(i) {
    if (i < 0 || i >= people.length) return;
    state.who = i;
    render();
    say('');
  }
  /* "Same for everyone": traveller i's pick for every other traveller it is offered to. */
  function sameForAll(i) {
    const p = state.picks.get(i);
    if (!p) return;
    const b = books[p.product];
    const not = [];
    people.forEach((_, j) => {
      if (j === i) return;
      const r = b && !b.error ? row(p.product, p.plan, limitOf(p.product, p.plan, p.limit), dedOf(p.product, p.deductible), j) : null;
      if (r && r.price != null) state.picks.set(j, Object.assign({}, p)); else not.push(who(j));
    });
    render();
    say(not.length ? 'Not offered for ' + not.join(', ') + ': pick something else for them.' : 'The same pick for every traveller.');
  }
  /* A short note at the foot of the screen (and read out) about what just happened: the picks may be off screen. */
  let sayTimer;
  function say(text) {
    const el = $('#cqSay');
    clearTimeout(sayTimer);
    el.textContent = text;
    el.hidden = !text;
    if (text) sayTimer = setTimeout(() => { el.hidden = true; }, 4500);
  }

  ['mouseover', 'focusin'].forEach(ev => document.addEventListener(ev, e => {
    const cell = e.target.closest && e.target.closest('button.cq-cell');
    if (cell) showDetail(cell.dataset.key.split('|')[1], cell.dataset.key);
  }));
  document.addEventListener('mouseout', e => {
    const cell = e.target.closest && e.target.closest('button.cq-cell');
    if (cell && !(e.relatedTarget && e.relatedTarget.closest && e.relatedTarget.closest('button.cq-cell'))) {
      showDetail(cell.dataset.key.split('|')[1], null);
    }
  });

  let typing;
  $('#cqSearch').addEventListener('input', e => {
    clearTimeout(typing);
    typing = setTimeout(() => { state.q = e.target.value.trim(); renderPlan('s'); renderPlan('e'); }, 120);
  });
  $('#cqSort').addEventListener('change', e => { state.sort = e.target.value; renderPlan('s'); renderPlan('e'); });

  /* ------------------------------------------------------------------ call back */
  const ov = $('#cqOv'), form = $('#cqForm'), okBox = $('#cqOk'), err = $('#cqErr');
  const pickOne = (el, list, chosen, attr) => {
    el.innerHTML = list.map(v => '<button type="button" class="cq-chip" data-' + attr + '="' + esc(v) + '" aria-pressed="' + (v === chosen) + '">' + esc(v) + '</button>').join('');
  };
  let callTime = (state.callback && state.callback.best_time) || (D.callTimes || ['Any time'])[0];
  let callHow = (state.callback && state.callback.how) || (D.callHow || ['Phone call'])[0];
  function drawCallChips() {
    pickOne($('#cqTimes'), D.callTimes || [], callTime, 'time');
    pickOne($('#cqHow'), D.callHow || [], callHow, 'how');
  }
  ov.addEventListener('click', e => {
    const t = e.target.closest('button');
    if (e.target === ov) { closeCall(); return; }
    if (t && t.dataset.time) { callTime = t.dataset.time; drawCallChips(); }
    if (t && t.dataset.how) { callHow = t.dataset.how; drawCallChips(); }
  });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && !ov.hidden) closeCall(); });

  let lastFocus = null;
  function openCall() {
    lastFocus = document.activeElement;
    const n = state.picks.size;
    $('#cqFormWhat').textContent = !n ? 'your quotes'
      : !many ? 'the option you picked'
      : n === people.length ? 'the plan you picked for each traveller'
      : 'the plan you picked for ' + n + ' of your ' + people.length + ' travellers';
    form.hidden = false; okBox.hidden = true; err.hidden = true;
    drawCallChips();
    ov.hidden = false;
    document.body.style.overflow = 'hidden';
    setTimeout(() => $('#cqName').focus(), 30);
  }
  function closeCall() {
    ov.hidden = true;
    document.body.style.overflow = '';
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }

  form.addEventListener('submit', async e => {
    e.preventDefault();
    const name = $('#cqName').value.trim();
    if (!name) { err.textContent = 'Please tell us your name, so our agent knows who to ask for.'; err.hidden = false; $('#cqName').focus(); return; }
    const btn = $('#cqSend');
    btn.disabled = true; btn.textContent = 'Sending…'; err.hidden = true;
    const picks = [...state.picks.entries()].sort((a, z) => a[0] - z[0]).map(([i, p]) => ({
      traveller: i, product: p.product, plan: p.plan, limit: p.limit, deductible: p.deductible,
      pay: state.pay === 'monthly' ? 'monthly' : 'once',
    }));
    try {
      const r = await fetch(D.callbackUrl, {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
        body: JSON.stringify({ picks, pre: state.pre, name, best_time: callTime, how: callHow,
          note: $('#cqNote').value.trim(), wa_consent: $('#cqWa').checked }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok || !d.success) throw new Error(d.error || 'We could not send that just now. Please try again.');
      state.callback = { at: new Date().toISOString(), name, best_time: callTime, how: callHow };
      form.hidden = true; okBox.hidden = false;
      renderPicks();
      $('[data-close]', okBox).focus();
    } catch (ex) {
      err.textContent = ex.message || 'We could not send that just now. Please try again.';
      err.hidden = false;
    } finally {
      btn.disabled = false; btn.textContent = 'Send my request';
    }
  });

  /* ------------------------------------------------------------------ change the trip, here */
  const trip = $('#cqTrip');
  const tripState = { cover: D.cover || 'super_visa', people: (D.travellers || []).map(t => ({ age: String(t.age), pre: t.pre === 'y' ? 'y' : 'n' })) };
  const fmtDay = d => d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });

  function drawTrip() {
    $$('#cqTripCover [data-cover]').forEach(b => b.setAttribute('aria-checked', String(b.dataset.cover === tripState.cover)));
    const sv = tripState.cover === 'super_visa';
    $('#cqTripEndF').hidden = sv;
    $('#cqTripYear').hidden = !sv;
    const start = $('#cqTripStart').value;
    if (sv) {
      const d = start ? new Date(start + 'T00:00:00') : null;
      if (d) d.setDate(d.getDate() + 364);
      $('#cqTripYear .cq-trip-year').textContent = d && !isNaN(d) ? fmtDay(d) + ' · one full year' : 'One full year';
    }
    $('#cqTripEnd').min = start || D.today;
    $('#cqTripPeople').innerHTML = tripState.people.map((p, i) =>
      '<div class="cq-trip-person"><span class="n">' + (i + 1) + '</span>' +
      '<input type="number" min="0" max="120" inputmode="numeric" data-age="' + i + '" value="' + esc(p.age) + '" aria-label="Traveller ' + (i + 1) + ' age" placeholder="Age">' +
      '<div class="cq-trip-pre" role="radiogroup" aria-label="Traveller ' + (i + 1) + ' pre-existing condition">' +
      ['n', 'y'].map(v => '<button type="button" role="radio" data-tpre="' + i + '" data-v="' + v + '" aria-checked="' + (p.pre === v) + '"><i aria-hidden="true"></i>' +
        (v === 'y' ? 'Pre-existing' : 'None') + '</button>').join('') + '</div>' +
      (tripState.people.length > 1 ? '<button type="button" class="rm" data-trm="' + i + '" aria-label="Remove traveller ' + (i + 1) + '">&times;</button>' : '') +
      '</div>').join('');
    $('#cqTripAdd').hidden = tripState.people.length >= 8;
  }

  function openTrip(open) {
    trip.hidden = !open;
    $('#cqEditBtn').setAttribute('aria-expanded', String(open));
    if (open) {
      $('#cqTripStart').min = D.today;
      $('#cqTripStart').value = D.start && D.start >= D.today ? D.start : D.today;
      $('#cqTripEnd').value = D.cover === 'visitors' ? D.end : '';
      tripState.cover = D.cover || 'super_visa';
      tripState.people = (D.travellers || []).map((t, i) => ({ age: String(t.age), pre: state.pre[i] || 'n' }));
      $('#cqTripErr').hidden = true;
      drawTrip();
      $('#cqTripStart').focus();
    } else {
      $('#cqEditBtn').focus();
    }
  }

  $('#cqEditBtn').addEventListener('click', () => openTrip(trip.hidden));
  $('#cqTripCancel').addEventListener('click', () => openTrip(false));
  $('#cqTripAdd').addEventListener('click', () => {
    if (tripState.people.length < 8) tripState.people.push({ age: '', pre: 'n' });
    drawTrip();
    const ages = $$('#cqTripPeople [data-age]');
    ages[ages.length - 1].focus();
  });
  $('#cqTripStart').addEventListener('change', drawTrip);
  trip.addEventListener('input', e => {
    if (e.target.dataset.age !== undefined) tripState.people[+e.target.dataset.age].age = e.target.value.trim();
  });
  trip.addEventListener('click', e => {
    const b = e.target.closest('button');
    if (!b) return;
    if (b.dataset.cover) { tripState.cover = b.dataset.cover; drawTrip(); }
    if (b.dataset.tpre !== undefined) { tripState.people[+b.dataset.tpre].pre = b.dataset.v; drawTrip(); }
    if (b.dataset.trm !== undefined) { tripState.people.splice(+b.dataset.trm, 1); drawTrip(); }
  });
  trip.addEventListener('submit', async e => {
    e.preventDefault();
    const err = $('#cqTripErr'), go = $('#cqTripGo');
    const fail = m => { err.textContent = m; err.hidden = false; };
    err.hidden = true;
    const start = $('#cqTripStart').value, end = $('#cqTripEnd').value;
    if (!start) return fail('Pick the date the cover starts.');
    if (tripState.cover === 'visitors' && (!end || end < start)) return fail('Pick an end date on or after the start date.');
    const people = tripState.people.filter(p => p.age !== '');
    if (!people.length) return fail('Enter at least one traveller’s age.');
    if (people.some(p => !/^\d{1,3}$/.test(p.age))) return fail('Ages must be whole numbers (years).');
    go.disabled = true; go.textContent = 'Updating…';
    try {
      const r = await fetch(D.tripUrl, {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
        body: JSON.stringify({ cover: tripState.cover, start_date: start, end_date: tripState.cover === 'visitors' ? end : '',
          travellers: people.map(p => ({ age: p.age, pre: p.pre })) }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok || !d.success) throw new Error(d.error || 'We could not update that just now. Please try again.');
      // the same page, priced for the new trip; the picks come along where they still exist
      try {
        window.sessionStorage.setItem('cq.picks.' + D.ref,
          JSON.stringify([...state.picks.entries()].map(([i, p]) => Object.assign({ traveller: i }, p))));
      } catch (ex) { /* not kept */ }
      window.location.reload();
    } catch (ex) {
      fail(ex.message);
      go.disabled = false; go.textContent = 'Update my quotes';
    }
  });

  // picks carried over a "Change the trip" reload: each stays with the traveller in the same place
  try {
    const kept = JSON.parse(window.sessionStorage.getItem('cq.picks.' + D.ref) || 'null');
    window.sessionStorage.removeItem('cq.picks.' + D.ref);
    (kept || []).forEach(p => {
      const b = books[p.product];
      const i = +p.traveller;
      if (i >= 0 && i < people.length && b && !b.error && (b.limits[p.plan] || []).some(l => l.code === String(p.limit))) {
        state.picks.set(i, { product: p.product, plan: p.plan, limit: String(p.limit), deductible: +p.deductible });
      }
    });
    if (kept && kept.length) state.who = Math.max(firstOpen(), 0);
  } catch (ex) { /* nothing kept */ }

  // the bar at the bottom stands in for the picks box while that box is off screen, on any screen size
  if ('IntersectionObserver' in window) {
    new IntersectionObserver(entries => {
      picksInView = entries[0].isIntersecting;
      $('#cqBar').hidden = (!state.picks.size && !many) || picksInView;
    }, { threshold: 0.25 }).observe($('.cq-picks-box'));
  }
  $('#cqBar [data-see-picks]').addEventListener('click', () => $('.cq-picks-box').scrollIntoView({ behavior: 'smooth', block: 'center' }));

  renderBenefits();
  render();
  setTab('s');
})();
