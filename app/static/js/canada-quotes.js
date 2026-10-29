/* Canada quotes page (templates/insurance/canada_quotes.html).

   Everything comes from #cqData, which the server built from Secure Travel's calculators a moment ago
   (routes/insurance.py: canada_quotes). Each traveller is priced for both answers to "pre-existing
   condition?", so changing one person's answer, a filter or the search re-draws the page without asking
   the server. A pick is only a key (cover|plan|limit|deductible): the server prices it again when the call
   back is requested, so what reaches our agent is never a number the browser made up. */
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
  const state = {
    product: usable(D.cover) ? D.cover : (PRODUCTS.find(usable) || D.cover || 'super_visa'),
    pre: (D.travellers || []).map(t => (t.pre === 'y' ? 'y' : 'n')),
    limits: new Set(), deds: new Set(), pay: 'once', sort: 'cover', q: '',
    picks: new Map(),
    callback: D.callback || null,
  };
  const key = (product, plan, limit, ded) => [product, plan, limit, ded].join('|');
  (D.picks || []).forEach(p => state.picks.set(key(p.product, p.plan, p.limit, p.deductible),
    { product: p.product, plan: p.plan, limit: String(p.limit), deductible: +p.deductible }));

  /* ------------------------------------------------------------------ prices */
  function row(product, plan, lim, ded) {
    const b = books[product];
    const each = b.people.map((p, i) => {
      const byPre = p.prices[state.pre[i] || 'n'] || {};
      return (((byPre[plan] || {})[lim.code] || {})[String(ded.value)]);
    });
    const ok = each.every(x => x != null);
    const total = ok ? round2(each.reduce((a, x) => a + x, 0)) : null;
    const monthlyOk = !!(b.monthly && b.monthly.limits.indexOf(lim.code) > -1);
    const monthly = ok && monthlyOk ? round2(total / (b.monthly.months || 12)) : null;
    const missing = each.map((x, i) => (x == null ? i : -1)).filter(i => i > -1);
    return { each, total, monthlyOk, monthly, missing };
  }

  function limitOf(product, plan, code) {
    return ((books[product].limits[plan] || []).find(l => l.code === String(code))) || { code: String(code), label: code, amount: 0 };
  }
  function dedOf(product, value) {
    return (books[product].deductibles || []).find(d => d.value === +value) || { value: +value, label: '$' + value };
  }
  const planLabel = plan => (plan === 'e' ? 'Enhanced' : 'Standard');
  const daysText = b => (b.product === 'super_visa' || b.days === 365 ? 'a year' : 'for ' + b.days + ' days');
  const who = i => 'Traveller ' + (i + 1) + ' · ' + people[i].age;

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
    if (r.total != null) nums.push(r.total.toFixed(2), String(Math.floor(r.total)));
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
    const toks = tokens();
    const lims = (b.limits[plan] || []).filter(l => !state.limits.size || state.limits.has(l.code));
    const deds = b.deductibles.filter(d => !state.deds.size || state.deds.has(d.value));
    let cards = lims.map(lim => {
      const rows = deds.map(ded => Object.assign({ lim, ded }, row(state.product, plan, lim, ded)))
        .filter(r => matches(toks, plan, lim, r.ded, r));
      const priced = rows.filter(r => r.total != null).map(r => r.total);
      return { lim, rows, min: priced.length ? Math.min.apply(null, priced) : Infinity };
    }).filter(c => c.rows.length);
    if (state.sort === 'cover-desc') cards.reverse();
    if (state.sort === 'price') cards.sort((a, b2) => a.min - b2.min);
    const low = Math.min.apply(null, cards.map(c => c.min).concat([Infinity]));
    const offered = cards.reduce((n, c) => n + c.rows.filter(r => r.total != null).length, 0);
    count.textContent = offered + (offered === 1 ? ' option' : ' options');
    if (!cards.length) {
      list.innerHTML = '<div class="cq-empty">Nothing matches these filters.<br><button type="button" class="cq-link" data-reset>Clear the filters</button></div>';
      return;
    }
    list.innerHTML = cards.map(c => {
      const hasLow = c.min === low && low !== Infinity;
      return '<article class="cq-card">' +
        '<div class="cq-card-hd"><span class="cq-limit">' + esc(c.lim.label) +
        '<small>Emergency medical · ' + esc(daysText(b)) + '</small></span><span class="cq-badges">' +
        (state.product === 'super_visa' ? '<span class="cq-badge sv">Super visa ready</span>' : '') +
        (hasLow ? '<span class="cq-badge low">Lowest price</span>' : '') + '</span></div>' +
        '<div class="cq-rows">' + c.rows.map(r => rowHtml(b, plan, c.lim, r, r.total != null && r.total === low)).join('') + '</div>' +
        '</article>';
    }).join('');
  }

  function rowHtml(b, plan, lim, r, isLow) {
    const k = key(state.product, plan, lim.code, r.ded.value);
    const picked = state.picks.has(k);
    const na = r.total == null;
    let price, each;
    if (na) {
      price = 'Not offered';
      each = 'Not offered for ' + r.missing.map(i => who(i) + (state.pre[i] === 'y' ? ' with a pre-existing condition' : '')).join(', ') + '.';
    } else {
      if (state.pay === 'monthly') {
        price = r.monthlyOk ? money(r.monthly) + '<small>a month + ' + money(b.monthly.fee).replace('.00', '') + ' once</small>'
                            : money(r.total) + '<small>monthly not offered</small>';
      } else {
        price = money(r.total) + '<small>' + esc(daysText(b)) + (people.length > 1 ? ' · everyone' : '') + '</small>';
      }
      each = people.length > 1
        ? r.each.map((x, i) => esc(who(i)) + ': <b>' + money(x) + '</b>').join(' · ')
        : money(round2(r.total / b.days)) + ' a day';
    }
    return '<button type="button" class="cq-row' + (picked ? ' is-picked' : '') + (na ? ' is-na' : '') + (isLow ? ' is-low' : '') +
      '" data-key="' + esc(k) + '" aria-pressed="' + picked + '"' + (na ? ' aria-disabled="true"' : '') + '>' +
      '<span class="cq-tickbox" aria-hidden="true">' + TICK + '</span>' +
      '<span class="cq-ded">' + esc(r.ded.label) + ' deductible' + (r.ded.value === 0 ? ' <small>· nothing to pay first</small>' : '') + '</span>' +
      '<span class="cq-amt">' + price + '</span>' +
      '<span class="cq-each">' + each + '</span></button>';
  }

  /* ------------------------------------------------------------------ the middle panel */
  function renderProducts() {
    $('#cqProduct').innerHTML = PRODUCTS.map(p => {
      const b = books[p];
      const sub = p === 'super_visa' ? '1 year · $100k+' : (b.days ? b.days + ' days' : '');
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

  function pickRows() {
    return [...state.picks.entries()].map(([k, p]) => {
      const b = books[p.product];
      if (!b || b.error) return { k, p, r: null, b };
      return { k, p, b, r: row(p.product, p.plan, limitOf(p.product, p.plan, p.limit), dedOf(p.product, p.deductible)) };
    });
  }

  function renderPicks() {
    const rows = pickRows();
    $('#cqPickN').textContent = rows.length;
    $('#cqBarN').textContent = rows.length;
    $('#cqBar').hidden = !rows.length;
    $('#cqPickEmpty').hidden = !!rows.length;
    $('#cqPickList').innerHTML = rows.map(({ k, p, r, b }) => {
      const lim = b && !b.error ? limitOf(p.product, p.plan, p.limit) : { label: p.limit };
      const amt = !r || r.total == null ? 'Not offered'
        : (state.pay === 'monthly' && r.monthlyOk ? money(r.monthly) + '/mo' : money(r.total));
      return '<li class="' + p.plan + '"><div><b>' + esc(planLabel(p.plan)) + ' · ' + esc(lim.label) + '</b>' +
        '<span>' + esc(p.product === 'super_visa' ? 'Super visa' : 'Visitor') + ' · ' + esc(dedOf(p.product, p.deductible).label) + ' deductible</span></div>' +
        '<span class="amt">' + amt + '</span><button type="button" data-unpick="' + esc(k) + '" aria-label="Remove">&times;</button></li>';
    }).join('');
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

  function render() {
    renderProducts(); renderPre(); renderFilters();
    renderPlan('s'); renderPlan('e');
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
    if (t.dataset.tab) { setTab(t.dataset.tab); return; }
    if (t.dataset.unpick) { state.picks.delete(t.dataset.unpick); render(); return; }
    if (t.hasAttribute('data-reset') || t.id === 'cqReset') { resetFilters(); return; }
    if (t.classList.contains('cq-row')) { togglePick(t); return; }
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
  function togglePick(btn) {
    if (btn.getAttribute('aria-disabled') === 'true') return;
    const k = btn.dataset.key;
    if (state.picks.has(k)) state.picks.delete(k);
    else {
      if (state.picks.size >= (D.maxPicks || 6)) { flash('You can pick up to ' + (D.maxPicks || 6) + ' options.'); return; }
      const [product, plan, limit, ded] = k.split('|');
      state.picks.set(k, { product, plan, limit, deductible: +ded });
    }
    renderPlan('s'); renderPlan('e'); renderPicks();
  }
  function flash(msg) {
    const el = $('#cqPickEmpty');
    el.hidden = false; el.textContent = msg;
    setTimeout(() => { el.textContent = 'Tap any price on the left or right to add it here. Pick one, or a few to talk through.'; renderPicks(); }, 2600);
  }

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
    $('#cqFormWhat').textContent = n ? (n === 1 ? 'the option you picked' : 'the ' + n + ' options you picked') : 'your quotes';
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
    const picks = [...state.picks.values()].map(p => ({
      product: p.product, plan: p.plan, limit: p.limit, deductible: p.deductible,
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

  renderBenefits();
  render();
  setTab('s');
})();
