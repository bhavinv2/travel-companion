// ===== HELPERS =====
function esc(s) {
  if (s === null || s === undefined) return '';
  return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function truncate(s, n) {
  s = String(s || '');
  return s.length > n ? s.slice(0, n - 1) + '…' : s;
}

function showToast(msg, type = 'success') {
  const container = document.getElementById('toastContainer');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  const span = document.createElement('span');
  span.textContent = msg;
  const btn = document.createElement('button');
  btn.innerHTML = '&times;';
  btn.onclick = () => toast.remove();
  toast.append(span, btn);
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 5000);
}

function apiFetch(url, options = {}) {
  return fetch(url, {
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN, ...options.headers },
    ...options,
  });
}

// ===== SKELETON UI HELPERS =====
function skeletonTripCards(container, n = 4) {
  if (!container) return;
  container.innerHTML = '';
  for (let i = 0; i < n; i++) {
    const c = document.createElement('div');
    c.className = 'sk-card';
    c.innerHTML = `<div class="sk sk-band"></div><div class="sk-pad">
      <div class="sk-row"><div class="sk" style="width:92px;height:20px"></div><div class="sk" style="width:70px;height:20px;margin-left:auto"></div></div>
      <div class="sk-row"><div class="sk" style="width:56px;height:30px"></div><div class="sk" style="flex:1;height:6px"></div><div class="sk" style="width:56px;height:30px"></div></div>
      <div class="sk" style="width:72%;height:10px"></div>
      <div class="sk" style="width:55%;height:10px"></div>
      <div class="sk sk-foot" style="height:36px"></div>
    </div>`;
    container.appendChild(c);
  }
}
function skeletonListRows(container, n = 3) {
  if (!container) return;
  container.innerHTML = '';
  for (let i = 0; i < n; i++) {
    const r = document.createElement('div');
    r.className = 'notif-sk';
    r.innerHTML = `<div class="sk dot"></div><div class="lines"><div class="sk" style="width:70%;height:9px"></div><div class="sk" style="width:45%;height:8px"></div></div>`;
    container.appendChild(r);
  }
}

const CONTACT_ICONS = {
  email: 'fa-solid fa-envelope', mobile: 'fa-solid fa-mobile-screen', whatsapp: 'fa-brands fa-whatsapp',
  facebook: 'fa-brands fa-facebook', instagram: 'fa-brands fa-instagram', inapp_chat: 'fa-solid fa-comments',
  other: 'fa-solid fa-globe',
};
const CONTACT_LABELS = {
  email: 'Email', mobile: 'Mobile', whatsapp: 'WhatsApp', facebook: 'Facebook', instagram: 'Instagram',
  inapp_chat: 'Chat on Connecting Desis', other: 'Other',
};
const ROLE_LABELS = { seeking_help: 'Seeking help', offering_help: 'Offering help', open: 'Open to either' };

// ===== NAVBAR =====
document.getElementById('hamburger')?.addEventListener('click', () => {
  document.getElementById('navLinks')?.classList.toggle('open');
});

// User dropdown
document.getElementById('userMenuBtn')?.addEventListener('click', (e) => {
  e.stopPropagation();
  document.getElementById('userDropdown')?.classList.toggle('open');
  document.getElementById('notifDropdown')?.classList.remove('open');
});
document.addEventListener('click', () => {
  document.getElementById('userDropdown')?.classList.remove('open');
  document.getElementById('notifDropdown')?.classList.remove('open');
});

// ===== NOTIFICATIONS DROPDOWN =====
document.getElementById('notifBtn')?.addEventListener('click', (e) => {
  e.preventDefault();
  e.stopPropagation();
  const dd = document.getElementById('notifDropdown');
  document.getElementById('userDropdown')?.classList.remove('open');
  dd.classList.toggle('open');
  if (dd.classList.contains('open')) loadNotifications();
});
document.getElementById('notifDropdown')?.addEventListener('click', (e) => e.stopPropagation());
document.getElementById('notifReadAll')?.addEventListener('click', async () => {
  await apiFetch('/api/notifications/read-all', { method: 'POST', body: '{}' });
  loadNotifications();
  pollUnread();
});

async function loadNotifications() {
  const list = document.getElementById('notifList');
  if (!list) return;
  skeletonListRows(list, 3);
  try {
    const res = await apiFetch('/api/notifications?limit=15');
    const data = await res.json();
    list.innerHTML = '';
    if (!data.notifications?.length) {
      list.innerHTML = '<div class="notif-empty">No notifications yet.</div>';
      return;
    }
    data.notifications.forEach(n => {
      const a = document.createElement('a');
      a.className = 'notif-item' + (n.is_read ? '' : ' unread');
      a.href = n.link || '#';
      const title = document.createElement('strong'); title.textContent = n.title || '';
      const body = document.createElement('span'); body.textContent = truncate(n.body || '', 120);
      const when = document.createElement('small'); when.textContent = n.created_at ? new Date(n.created_at).toLocaleString() : '';
      a.append(title, body, document.createElement('br'), when);
      a.addEventListener('click', async (e) => {
        if (!n.is_read) {
          e.preventDefault();
          await apiFetch(`/api/notifications/${n.id}/read`, { method: 'POST', body: '{}' });
          window.location = n.link || '/';
        }
      });
      list.appendChild(a);
    });
  } catch (e) {
    list.innerHTML = '<div class="notif-empty">Could not load notifications.</div>';
  }
}

// ===== HERO SLIDER =====
let slideIdx = 0;
const slides = document.querySelectorAll('.slide');
const dots = document.querySelectorAll('.dot');

function goToSlide(idx) {
  slides.forEach(s => s.classList.remove('active'));
  dots.forEach(d => d.classList.remove('active'));
  slideIdx = (idx + slides.length) % slides.length;
  slides[slideIdx]?.classList.add('active');
  dots[slideIdx]?.classList.add('active');
}

dots.forEach(dot => dot.addEventListener('click', () => goToSlide(+dot.dataset.idx)));

if (slides.length > 0) {
  setInterval(() => goToSlide(slideIdx + 1), 5000);
}

// ===== REVIEWS: show 3 at a time; if there are more, rotate through them (owl-style) =====
(function reviewsCarousel() {
  const list = document.querySelector('.tm-list[data-carousel]');
  const dotsEl = document.getElementById('tmDots');
  if (!list) return;
  const cards = Array.from(list.children);
  const VISIBLE = 3;
  if (cards.length <= VISIBLE) return;      // 3 or fewer: a plain stack, nothing to rotate

  let start = 0;
  const pages = cards.length;               // sliding window advances one card at a time
  if (dotsEl) {
    dotsEl.hidden = false;
    cards.forEach((_, i) => {
      const d = document.createElement('span');
      if (i === 0) d.className = 'active';
      d.addEventListener('click', () => { start = i; render(); restart(); });
      dotsEl.appendChild(d);
    });
  }

  function render() {
    cards.forEach((c, i) => {
      const pos = (i - start + pages) % pages;   // 0..pages-1 from the window start
      const on = pos < VISIBLE;
      c.style.display = on ? '' : 'none';
      c.style.order = on ? pos : pages;
    });
    if (dotsEl) dotsEl.querySelectorAll('span').forEach((d, i) => d.classList.toggle('active', i === start));
  }

  let timer = null;
  function restart() { clearInterval(timer); timer = setInterval(() => { start = (start + 1) % pages; render(); }, 5000); }
  render();
  restart();
})();

// ===== TRIP TYPE =====
function applyTripTypeUI(type) {
  const hiddenEl = document.getElementById('tripTypeHidden');
  if (!hiddenEl) return;
  hiddenEl.value = type;
  const isMulti = type === 'multi_destination';
  const isRound = type === 'round_trip';

  document.getElementById('flightRoute').style.display = isMulti ? 'none' : '';
  document.getElementById('fieldReturnDate').style.display = isRound ? '' : 'none';
  document.getElementById('multiDestSection').style.display = isMulti ? '' : 'none';
  const retRow = document.getElementById('returnFlightRow');
  if (retRow) retRow.style.display = isRound ? '' : 'none';
  if (isMulti && document.getElementById('legsContainer').children.length === 0) {
    addLeg(); addLeg();
  }
}

document.querySelectorAll('input[name=trip_type]').forEach(r => {
  r.addEventListener('change', () => applyTripTypeUI(r.value));
});
applyTripTypeUI('one_way');

// ===== MULTI-DESTINATION LEGS =====
let _legCount = 0;
function addLeg() {
  _legCount++;
  const idx = _legCount;
  const container = document.getElementById('legsContainer');
  const leg = document.createElement('div');
  leg.className = 'leg-row';
  leg.id = `leg-${idx}`;
  leg.innerHTML = `
    <div class="leg-num">${idx}</div>
    <div class="leg-fields">
      <div class="field-group">
        <label>From</label>
        <input type="text" class="leg-from autocomplete-airport" placeholder="City or Airport" data-leg="${idx}"/>
      </div>
      <div class="field-group">
        <label>To</label>
        <input type="text" class="leg-to autocomplete-airport" placeholder="City or Airport" data-leg="${idx}"/>
      </div>
      <div class="field-group">
        <label>Date</label>
        <input type="date" class="leg-date" data-leg="${idx}"/>
      </div>
      <div class="field-group">
        <label>Airline <span class="optional">(opt)</span></label>
        <input type="text" class="leg-airline autocomplete-airline" placeholder="Search airline..." data-leg="${idx}"/>
      </div>
      <div class="field-group">
        <label>Flight No <span class="optional">(opt)</span></label>
        <input type="text" class="leg-flightno" placeholder="e.g. AI 101" data-leg="${idx}"/>
      </div>
    </div>
    ${idx > 2 ? `<button type="button" class="leg-remove" onclick="removeLeg(${idx})" title="Remove stop"><i class="fa-solid fa-xmark"></i></button>` : '<div class="leg-remove-placeholder"></div>'}`;
  container.appendChild(leg);
  wireAirportAutocomplete(leg.querySelectorAll('.leg-from, .leg-to'));
  wireAirlineAutocomplete(leg.querySelectorAll('.leg-airline'));
  updateLegNumbers();
}

function removeLeg(idx) {
  document.getElementById(`leg-${idx}`)?.remove();
  updateLegNumbers();
}

function updateLegNumbers() {
  document.querySelectorAll('#legsContainer .leg-row').forEach((row, i) => {
    const numEl = row.querySelector('.leg-num');
    if (numEl) numEl.textContent = i + 1;
  });
}

function collectLegs() {
  const legs = [];
  document.querySelectorAll('#legsContainer .leg-row').forEach(row => {
    legs.push({
      from: row.querySelector('.leg-from')?.value.trim() || '',
      to: row.querySelector('.leg-to')?.value.trim() || '',
      date: row.querySelector('.leg-date')?.value || '',
      airline: row.querySelector('.leg-airline')?.value.trim() || '',
      flight_number: row.querySelector('.leg-flightno')?.value.trim() || '',
    });
  });
  return legs;
}

// ===== MULTI-SELECT DROPDOWNS =====
// Delegated on the document so a dropdown added after load — a new traveller row, say — works
// with no rewiring. A button finds its dropdown by data-target (the static ones) or as the
// sibling inside its .multi-select-wrapper (the cloned ones, which carry no unique id).
function multiDropdownFor(btn) {
  if (btn.dataset.target) return document.getElementById(btn.dataset.target);
  const wrap = btn.closest('.multi-select-wrapper');
  return wrap ? wrap.querySelector('.multi-dropdown') : null;
}
document.addEventListener('click', (e) => {
  const btn = e.target.closest('.multi-select-btn');
  if (btn) {
    e.stopPropagation();
    const dd = multiDropdownFor(btn);
    document.querySelectorAll('.multi-dropdown.open').forEach(d => { if (d !== dd) d.classList.remove('open'); });
    dd?.classList.toggle('open');
    return;
  }
  // A click inside an open dropdown must NOT close it — you're picking several. Anything else does.
  if (e.target.closest('.multi-dropdown')) return;
  document.querySelectorAll('.multi-dropdown.open').forEach(d => d.classList.remove('open'));
});

// Keep a dropdown's button label in step with its ticks — works for any number of dropdowns.
function updateMultiLabelEl(dd) {
  if (!dd) return;
  const wrap = dd.closest('.multi-select-wrapper');
  const label = wrap ? wrap.querySelector('.multi-select-btn .ms-label') : null;
  if (!label) return;
  const checked = [...dd.querySelectorAll('input[type=checkbox]:checked')];
  const ph = label.dataset.placeholder || 'Select...';
  label.textContent = checked.length === 0 ? ph
    : checked.map(c => (c.dataset.label || c.parentElement.textContent).trim()).join(', ');
}
// Back-compat shim: a couple of call sites still pass ids.
function updateMultiLabel(dropdownId) { updateMultiLabelEl(document.getElementById(dropdownId)); }
document.addEventListener('change', (e) => {
  const dd = e.target.closest('.multi-dropdown');
  if (dd) updateMultiLabelEl(dd);
});

// "Open to any companion" is the default: it greys out (and clears) the specific companion
// preferences so the match is never silently narrowed. Unticking it hands those fields back.
(function companionAnyToggle() {
  const master = document.getElementById('companionAny');
  const prefs = document.getElementById('companionPrefs');
  if (!master || !prefs) return;
  function apply() {
    const off = master.checked;                 // "any" on -> specific prefs disabled
    prefs.classList.toggle('is-disabled', off);
    prefs.querySelectorAll('input, select, .multi-select-btn').forEach(el => { el.disabled = off; });
    if (off) {
      prefs.querySelectorAll('input[type=checkbox]:checked').forEach(cb => { cb.checked = false; });
      prefs.querySelectorAll('select').forEach(s => { s.selectedIndex = 0; if (window.syncSearchSelect) syncSearchSelect(s); });
      prefs.querySelectorAll('input[type=number]').forEach(n => { n.value = ''; });
      const dd = document.getElementById('connectTo');
      if (dd) { dd.classList.remove('open'); updateMultiLabelEl(dd); }
    }
  }
  master.addEventListener('change', apply);
  apply();                                        // default checked -> disabled on load
})();

// "Any — no specific language" is a master option inside the languages dropdown, mutually
// exclusive with the specific ones: ticking it clears the specifics, ticking a specific clears
// it, and it re-asserts itself when nothing specific is left so there is never an empty state.
(function langAnyOption() {
  const dd = document.getElementById('langSelect');
  const any = dd && dd.querySelector('.lang-any');
  if (!dd || !any) return;
  const specifics = () => [...dd.querySelectorAll('input[name="preferred_languages"]')];
  any.addEventListener('change', () => {
    if (any.checked) specifics().forEach(cb => { cb.checked = false; });
    else if (!specifics().some(cb => cb.checked)) any.checked = true;   // can't select nothing at all
    updateMultiLabelEl(dd);
  });
  dd.addEventListener('change', (e) => {
    if (e.target.name !== 'preferred_languages') return;
    any.checked = !specifics().some(cb => cb.checked);
    updateMultiLabelEl(dd);
  });
  updateMultiLabelEl(dd);
})();

// ===== TRAVELLERS EDITOR (step 3 of the post form) — one companion for the whole group =====
function collectTravellers() {
  return [...document.querySelectorAll('#travellersRows .tv-card')].map(c => ({
    who: c.querySelector('.tv-who').value,
    age_group: c.querySelector('.tv-age').value,
    gender: c.querySelector('.tv-gender').value,
    needs: [...c.querySelectorAll('.tv-need:checked')].map(n => n.value),
  })).filter(t => t.who);
}
(function travellersEditor() {
  const rows = document.getElementById('travellersRows');
  const tpl = document.getElementById('travellerTpl');
  const addBtn = document.getElementById('addTravellerBtn');
  if (!rows || !tpl || !addBtn) return;
  const renumber = () => [...rows.children].forEach((c, i) => { c.querySelector('.tv-n').textContent = i + 1; });
  function addTraveller(data) {
    const node = tpl.content.firstElementChild.cloneNode(true);
    if (data) {
      node.querySelector('.tv-who').value = data.who || '';
      node.querySelector('.tv-age').value = data.age_group || '';
      node.querySelector('.tv-gender').value = data.gender || '';
      const needs = data.needs || [];
      node.querySelectorAll('.tv-need').forEach(cb => { cb.checked = needs.includes(cb.value); });
      const nd = node.querySelector('.tv-needs .multi-dropdown');
      if (nd) updateMultiLabelEl(nd);
    }
    node.querySelector('.tv-x').addEventListener('click', () => {
      if (rows.children.length <= 1) return;               // always keep at least one
      node.remove(); renumber();
    });
    rows.appendChild(node);
    node.querySelectorAll('select').forEach(s => { if (window.syncSearchSelect) syncSearchSelect(s); });
    renumber();
  }
  addBtn.addEventListener('click', () => addTraveller());
  addTraveller();                                           // start with one traveller
  window.resetTravellersEditor = () => { rows.innerHTML = ''; addTraveller(); };
  window.setTravellers = (list) => { rows.innerHTML = ''; (list && list.length ? list : [null]).forEach(addTraveller); };
})();

// ===== RESULTS CAROUSEL =====
// Two rows of whatever the CSS grid is currently showing, so the page size always
// matches the layout instead of a width guess that leaves a column empty.
function gridColumns(el) {
  if (!el) return 4;
  const raw = (getComputedStyle(el).gridTemplateColumns || '').trim();
  // A grid inside a hidden panel never gets a resolved track list: the computed value comes
  // back as the authored "repeat(4, minmax(0, 1fr))", and splitting that on spaces counts
  // three columns instead of four — which pages the tab to a ragged 6 cards. Read the
  // repeat() count when the browser hands back the unresolved form.
  const repeated = /repeat\(\s*(\d+)/.exec(raw);
  if (repeated) return Math.max(1, +repeated[1]);
  if (!raw || raw === 'none') return 4;
  return Math.max(1, raw.split(' ').filter(Boolean).length);
}
const CAROUSEL_ROWS = 2;
function carouselPageSize() {
  return gridColumns(document.getElementById('resultsGrid')) * CAROUSEL_ROWS;
}
let CAROUSEL_PAGE_SIZE = carouselPageSize();
let _myTripsCols = 0;
window.addEventListener('resize', () => {
  const n = carouselPageSize();
  if (n !== CAROUSEL_PAGE_SIZE) { CAROUSEL_PAGE_SIZE = n; _carouselPage = 0; if (document.getElementById('resultsGrid') && _carouselTrips.length) renderCarouselPage(); }
  // My Trips pages by the same rule, so a column change has to re-page it too
  const c = gridColumns(document.getElementById('myTripsGrid'));
  if (c !== _myTripsCols) { _myTripsCols = c; _myTripsPage = 0; if (_myTrips.length) renderMyTripsPage(); }
});

function updateFilterBar(fd) {
  const bar = document.getElementById('filterBar');
  if (!bar) return;
  const chips = [];
  if (fd.flying_from) chips.push(['plane-departure', `From: ${fd.flying_from}`]);
  if (fd.destination) chips.push(['location-dot', `To: ${fd.destination}`]);
  if (fd.from_date) chips.push(['calendar-days', `Departs: ${fd.from_date}`]);
  if (fd.airline) chips.push(['plane', fd.airline]);
  if (fd.flight_number) chips.push(['ticket', fd.flight_number]);
  if (!chips.length) { bar.style.display = 'none'; bar.innerHTML = ''; return; }
  bar.style.display = 'flex';
  bar.innerHTML = '';
  const lbl = document.createElement('span'); lbl.className = 'fb-lbl'; lbl.innerHTML = '<i class="fa-solid fa-filter"></i> Showing trips matching:';
  bar.appendChild(lbl);
  chips.forEach(([ic, t]) => {
    const sp = document.createElement('span'); sp.className = 'fb-chip';
    sp.innerHTML = `<i class="fa-solid fa-${ic}"></i> `;
    sp.appendChild(document.createTextNode(t));
    bar.appendChild(sp);
  });
  const edit = document.createElement('button'); edit.type = 'button'; edit.className = 'btn-sm';
  edit.innerHTML = '<i class="fa-solid fa-pen"></i> Edit search';
  edit.onclick = () => document.getElementById('search')?.scrollIntoView({ behavior: 'smooth' });
  const clear = document.createElement('button'); clear.type = 'button'; clear.className = 'btn-sm danger';
  clear.innerHTML = '<i class="fa-solid fa-xmark"></i> Clear filters';
  clear.onclick = () => {
    ['flyingFrom', 'destination', 'fromDate', 'toDate', 'airlineSelect', 'qFrom', 'qTo', 'qWhen'].forEach(id => {
      const el = document.getElementById(id);
      if (el) { el.value = ''; if (el.dataset) delete el.dataset.iso; }
    });
    const fn = document.querySelector('#searchForm input[name=flight_number]'); if (fn) fn.value = '';
    loadResults();
    showToast('Filters cleared - showing all trips.', 'info');
  };
  bar.append(edit, clear);
}

let _carouselTrips = [];
let _carouselPage = 0;

async function loadResults() {
  const grid = document.getElementById('resultsGrid');
  const countEl = document.getElementById('resultsCount');
  if (!grid) return;
  skeletonTripCards(grid, 4);

  const form = document.getElementById('searchForm');
  const formData = {};
  if (form) {
    new FormData(form).forEach((v, k) => { if (!k.startsWith('contact_')) formData[k] = v; });
  }
  formData.travel_type = 'air';
  formData.limit = 30;
  // The form's role says who the *searcher* is, not what they want to find. Sent as
  // for_role so the API returns the complement instead of more people like them.
  if (formData.role) { formData.for_role = formData.role; delete formData.role; }
  updateFilterBar(formData);

  try {
    const res = await apiFetch('/api/search', { method: 'POST', body: JSON.stringify(formData) });
    const data = await res.json();
    _carouselTrips = data.results || [];
    _carouselPage = 0;
    if (countEl) countEl.textContent = `${_carouselTrips.length} trip${_carouselTrips.length !== 1 ? 's' : ''}`;
    renderCarouselPage();
  } catch (e) {
    grid.innerHTML = '<div class="loading-spinner">Failed to load trips. Please try again.</div>';
  }
}

function buildNumPager(container, page, pages, go) {
  container.innerHTML = '';
  container.classList.add('pagination');
  if (pages <= 1) return;
  const mk = (label, n, cls, inert) => {
    const el = document.createElement(inert ? 'span' : 'a');
    el.className = ('page ' + cls).trim(); el.innerHTML = label;
    if (!inert) { el.href = 'javascript:void(0)'; el.onclick = (e) => { e.preventDefault(); go(n); }; }
    container.appendChild(el);
  };
  mk('&lsaquo;', page - 1, page <= 1 ? 'pg-arrow disabled' : 'pg-arrow', page <= 1);
  let prev = 0;
  for (let p = 1; p <= pages; p++) {
    if (p <= 2 || p > pages - 2 || Math.abs(p - page) <= 1) {
      if (p - prev > 1) mk('&hellip;', 0, 'pg-ellipsis', true);
      mk(String(p), p, p === page ? 'current' : '', p === page);
      prev = p;
    }
  }
  mk('&rsaquo;', page + 1, page >= pages ? 'pg-arrow disabled' : 'pg-arrow', page >= pages);
}

function renderCarouselPage() {
  const grid = document.getElementById('resultsGrid');
  const dotsEl = document.getElementById('carouselDots');
  const prevBtn = document.getElementById('carouselPrev');
  const nextBtn = document.getElementById('carouselNext');
  if (!grid) return;

  grid.innerHTML = '';
  if (!_carouselTrips.length) {
    grid.innerHTML = '<div class="loading-spinner"><i class="fa-solid fa-map-location-dot"></i> No trips found. Be the first to post one!</div>';
    if (dotsEl) dotsEl.innerHTML = '';
    if (prevBtn) prevBtn.style.display = 'none';
    if (nextBtn) nextBtn.style.display = 'none';
    return;
  }

  const start = _carouselPage * CAROUSEL_PAGE_SIZE;
  const page = _carouselTrips.slice(start, start + CAROUSEL_PAGE_SIZE);
  page.forEach(trip => grid.appendChild(buildTripCard(trip, false)));

  const totalPages = Math.ceil(_carouselTrips.length / CAROUSEL_PAGE_SIZE);
  if (prevBtn) {
    prevBtn.style.display = totalPages > 1 ? '' : 'none';
    prevBtn.disabled = _carouselPage === 0;
  }
  if (nextBtn) {
    nextBtn.style.display = totalPages > 1 ? '' : 'none';
    nextBtn.disabled = _carouselPage >= totalPages - 1;
  }

  if (dotsEl) {
    dotsEl.innerHTML = '';
    dotsEl.classList.remove('pagination');
    if (totalPages > 8) {           // many pages (e.g. one card per page on mobile): numbers, not a dot soup
      buildNumPager(dotsEl, _carouselPage + 1, totalPages, n => { _carouselPage = n - 1; renderCarouselPage(); });
    } else {
      for (let i = 0; i < totalPages; i++) {
        const dot = document.createElement('span');
        dot.className = 'carousel-dot' + (i === _carouselPage ? ' active' : '');
        dot.onclick = () => { _carouselPage = i; renderCarouselPage(); };
        dotsEl.appendChild(dot);
      }
    }
  }
}

// Travels one way: clamped to the ends rather than wrapping, so "next" on the last
// page does nothing instead of silently jumping back to the first.
function carouselNav(dir) {
  const totalPages = Math.ceil(_carouselTrips.length / CAROUSEL_PAGE_SIZE);
  const next = Math.max(0, Math.min(_carouselPage + dir, totalPages - 1));
  if (next === _carouselPage) return;
  _carouselPage = next;
  renderCarouselPage();
}

// ===== TRIP CARD (all user-supplied strings are escaped) =====
function tcPort(text, iata) {
  const t = String(text || '').trim();
  const m = t.match(/\(([A-Za-z0-9]{3})\)/);
  const code = String(iata || (m ? m[1] : '') || '').toUpperCase();
  const city = t.replace(/\s*\([^)]*\)\s*/g, ' ').trim();
  return { code: code || (city ? city.slice(0, 3).toUpperCase() : '???'), city: city || code || '?' };
}

/* A card answers one question -- "my route, my date: can they help me / do they need me?"
   Six things earn a place on it; everything else is decide-later detail and lives in the
   details panel, one tap away. Keeping that set fixed is what gives the grid its rhythm:
   cards stay the same height, so the eye scans down instead of restarting on each one. */

function tcNeedLabel(key) {
  const t = String(key || '').replace(/_/g, ' ').trim();
  return t ? t.charAt(0).toUpperCase() + t.slice(1) : '';
}

function tcDeparture(trip) {
  // "in 5 days", and amber once the trip is a week or less away.
  const d = trip.from_date;
  if (!d) return null;
  let days;
  try {
    const dep = new Date(d + 'T00:00:00');
    const today = new Date(); today.setHours(0, 0, 0, 0);
    days = Math.round((dep - today) / 86400000);
  } catch (e) { return null; }
  if (isNaN(days)) return null;
  if (days < 0) return { text: 'departed', soon: false, past: true };
  if (days === 0) return { text: 'today', soon: true };
  if (days === 1) return { text: 'tomorrow', soon: true };
  return { text: 'in ' + days + ' days', soon: days <= 7 };
}

function tcQuickFacts(trip) {
  /* What the two chips show depends on who is being looked at. Someone offering help is
     judged on whether they can talk to your mother, so show languages; someone seeking
     help is judged on whether you could actually help them, so show their needs. */
  const langs = (trip.preferred_languages || []).filter(Boolean);
  const needs = (trip.traveller_needs || []).filter(Boolean).map(tcNeedLabel);
  if (trip.role === 'offering_help') return { kind: 'lang', items: langs.length ? langs : needs };
  if (needs.length) return { kind: 'need', items: needs };
  return { kind: 'lang', items: langs };
}

function tcFmtDate(d) {
  try { return new Date(d + 'T00:00:00').toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }); }
  catch (e) { return d; }
}

const TC_AGE = { under_18: 'Under 18', '18_30': '18–30', '31_45': '31–45', '46_60': '46–60', '60_plus': '60+' };

/* A one-line "who is actually travelling" descriptor — the thing a would-be companion
   scans for (an elderly parent, a woman travelling alone). For a group it collapses to a
   count ("3 travellers"); the per-person breakdown lives in the details popup. Empty when
   nothing is known. */
function tcTraveller(trip) {
  const group = (trip.travellers || []).filter(t => t && t.who);
  if (group.length > 1) return group.length + ' travellers';
  const one = group[0] || {};
  const g = one.gender || trip.traveler_gender;
  const gender = g && !['other', 'unspecified', 'prefer_not'].includes(g)
    ? g.charAt(0).toUpperCase() + g.slice(1) : '';
  const age = TC_AGE[one.age_group || trip.traveler_age_group] || '';
  return [gender, age].filter(Boolean).join(' · ');
}

/* One compact route line for every trip type — origin ✈ destination — with a small badge
   for the ones that carry more (a round trip, or an N-stop itinerary). The full breakdown
   (each leg, or both directions, with flight numbers and dates) is not shown on the card;
   it appears when you hover the flight symbol (tcWireRouteTip → the floating .rt-tip). */
function tcRouteHtml(trip, fp, tp) {
  const legs = trip.legs || [];
  const isMulti = trip.trip_type === 'multi_destination' && legs.length;
  const isRound = trip.trip_type === 'round_trip';
  const dot = '<span class="tc-dot"></span>', dash = '<span class="tc-dash"></span>';
  const plane = (cls) => '<span class="tc-flight-hot" tabindex="0" aria-label="Flight details">'
    + '<i class="fa-solid fa-plane' + (cls || '') + '"></i></span>';

  // Origin and destination are always the two fixed ends (codes never clipped); the connector
  // between them carries one flight symbol per leg — · ✈ · ✈ · ✈ · — and the dashes shrink so
  // the planes fit however many stops there are (a --dense class tightens them past 4 legs).
  let mid, cls = '';
  if (isMulti) {
    let seq = dot;
    for (let i = 0; i < legs.length; i++) seq += dash + plane('');
    mid = seq + dash + dot;
    if (legs.length >= 4) cls = ' tc-path--dense';
  } else if (isRound) {
    mid = '<div class="tc-rt">' +
            '<div class="tc-rtline">' + dot + dash + plane('') + dash + dot + '</div>' +
            '<div class="tc-rtline tc-back">' + dot + dash + plane(' fa-flip-horizontal') + dash + dot + '</div>' +
          '</div>';
    cls = ' tc-path-round';
  } else {
    mid = dot + dash + plane('') + dash + dot;
  }

  return '<div class="tc-route">' +
    '<div class="tc-port"><strong>' + esc(fp.code) + '</strong><small>' + esc(fp.city) + '</small></div>' +
    '<div class="tc-path' + cls + '">' + mid + '</div>' +
    '<div class="tc-port"><strong>' + esc(tp.code) + '</strong><small>' + esc(tp.city) + '</small></div>' +
  '</div>';
}

/* The line under the route that names the trip's shape and scales to any number of stops:
   "via DOH · JFK · 2 stops" for a multi-stop trip, "Round trip · returns 15 Oct" for a return. */
function tcRouteMeta(trip) {
  const legs = trip.legs || [];
  if (trip.trip_type === 'multi_destination' && legs.length) {
    const stops = legs.slice(0, -1).map(l => tcPort(l.to).code).filter(Boolean);
    const shown = stops.slice(0, 3).join(' · ');
    const extra = stops.length - Math.min(stops.length, 3);
    const via = stops.length ? 'via ' + shown + (extra > 0 ? ' +' + extra : '') : '';
    const n = stops.length;
    return '<div class="tc-via"><i class="fa-solid fa-diagram-project"></i> <span class="tc-via-txt">' + esc(via) + '</span>' +
           '<span class="tc-stops">' + n + ' stop' + (n === 1 ? '' : 's') + '</span></div>';
  }
  if (trip.trip_type === 'round_trip') {
    const ret = trip.to_date ? ' · returns ' + tcFmtDate(trip.to_date) : '';
    return '<div class="tc-via"><i class="fa-solid fa-right-left"></i> Round trip' + esc(ret) + '</div>';
  }
  return '';
}

/* One tooltip per flight symbol, in DOM order — multi-stop = one per leg, round trip =
   [outbound, return], one-way = [the flight]. Each shows just that flight's route, number
   and date. */
function tcRouteTips(trip, fp, tp) {
  const legs = trip.legs || [];
  const card = (icon, title, fromC, toC, airline, flight, dateStr) => {
    const fl = [airline, flight].filter(Boolean).join(' ');
    return '<div class="rt-head"><i class="fa-solid ' + icon + '"></i> ' + esc(title) + '</div>' +
      '<div class="rt-body">' +
        '<div class="rt-route">' + esc(fromC) + ' <i class="fa-solid fa-arrow-right-long"></i> ' + esc(toC) + '</div>' +
        (fl ? '<div class="rt-sub"><i class="fa-solid fa-plane-up"></i> ' + esc(fl) + '</div>' : '') +
        (dateStr ? '<div class="rt-sub"><i class="fa-solid fa-calendar-days"></i> ' + esc(tcFmtDate(dateStr)) + '</div>' : '') +
      '</div>';
  };
  if (trip.trip_type === 'multi_destination' && legs.length) {
    // one plane per leg on the card, so one tooltip per plane — hovering a plane shows that leg
    return legs.map((l, i) => {
      const f = tcPort(l.from), t = tcPort(l.to);
      return card('fa-plane', 'Flight ' + (i + 1) + ' of ' + legs.length, f.code, t.code, l.airline, l.flight_number, l.date);
    });
  }
  if (trip.trip_type === 'round_trip') {
    return [
      card('fa-plane-departure', 'Outbound', fp.code, tp.code, trip.airline, trip.flight_number, trip.from_date),
      card('fa-plane-arrival', 'Return', tp.code, fp.code,
           trip.return_airline || trip.airline, trip.return_flight_number || trip.flight_number, trip.to_date),
    ];
  }
  return [card('fa-plane', 'Direct flight', fp.code, tp.code, trip.airline, trip.flight_number, trip.from_date)];
}

/* A single floating tooltip, shared by every card (the cards clip their own overflow, so it
   cannot live inside one). Shown on hovering the flight symbol; suppresses the card's own
   hover-to-open so the two do not fight. */
let _rtTip = null, _rtHideTimer = null;
function rtEl() {
  if (!_rtTip) {
    _rtTip = document.createElement('div');
    _rtTip.className = 'rt-tip';
    _rtTip.hidden = true;
    _rtTip.addEventListener('mouseenter', () => clearTimeout(_rtHideTimer));
    _rtTip.addEventListener('mouseleave', hideRouteTip);
    document.body.appendChild(_rtTip);
  }
  return _rtTip;
}
function showRouteTip(anchor, html) {
  clearTimeout(_rtHideTimer);
  const t = rtEl();
  t.innerHTML = html;
  t.hidden = false;
  t.style.visibility = 'hidden';
  const r = anchor.getBoundingClientRect();
  const w = t.offsetWidth, h = t.offsetHeight;
  let top = r.top - h - 10;
  if (top < 8) top = r.bottom + 10;                       // no room above → drop below
  let left = r.left + r.width / 2 - w / 2;
  left = Math.max(8, Math.min(left, window.innerWidth - w - 8));
  t.style.top = top + 'px';
  t.style.left = left + 'px';
  t.style.visibility = '';
}
function hideRouteTip() {
  _rtHideTimer = setTimeout(() => { if (_rtTip) _rtTip.hidden = true; }, 120);
}
function tcWireRouteTip(hot, html) {
  if (!html) return;
  hot.addEventListener('mouseenter', () => {
    if (typeof TD !== 'undefined') clearTimeout(TD.openTimer);   // don't also open the big panel
    showRouteTip(hot, html);
  });
  hot.addEventListener('mouseleave', hideRouteTip);
  hot.addEventListener('focus', () => showRouteTip(hot, html));
  hot.addEventListener('blur', hideRouteTip);
}
window.addEventListener('scroll', () => { if (_rtTip && !_rtTip.hidden) _rtTip.hidden = true; }, true);

function buildTripCard(trip, isOwn = false) {
  const card = document.createElement('div');
  card.className = 'trip-card tc-' + (trip.role || 'open');
  card.dataset.tripId = trip.id;

  const ownTrip = isOwn || !!trip.is_own;
  const matchMine = !ownTrip ? trip.match_to_me : null;   // this post matches something the viewer posted
  if (matchMine) card.classList.add('tc-mine-match');
  const anon = trip.is_anonymous;
  const isMulti = trip.trip_type === 'multi_destination';
  let fromText = trip.flying_from, toText = trip.destination;
  if (isMulti && (trip.legs || []).length) {
    fromText = fromText || trip.legs[0].from;
    toText = toText || trip.legs[trip.legs.length - 1].to;
  }
  const fp = tcPort(fromText, trip.origin_iata);
  const tp = tcPort(toText, trip.dest_iata);

  const dep = tcDeparture(trip);
  // The date: a range for a multi-stop (first leg → last leg) or a round trip (out → back),
  // a single day otherwise. "flexible" is a separate tag so it can never widen the date and
  // push the row onto two lines.
  const legList = trip.legs || [];
  let dateChip;
  if (isMulti && legList.length) {
    const first = legList[0].date, last = legList[legList.length - 1].date;
    dateChip = (first ? tcFmtDate(first) : (trip.from_date ? tcFmtDate(trip.from_date) : ''))
      + (last && last !== first ? ' → ' + tcFmtDate(last) : '');
  } else if (trip.from_date) {
    dateChip = tcFmtDate(trip.from_date) + (trip.to_date ? ' → ' + tcFmtDate(trip.to_date) : '');
  } else {
    dateChip = '';
  }
  const flexible = !dateChip && trip.from_date_flexible ? 'Flexible dates'
    : (trip.from_date_flexible ? 'flexible' : '');

  // A single-hop trip names its flight ("Qatar Airways QR574"); a multi-stop shows nothing here
  // because its route already draws one plane per leg (each hoverable for that leg's airline,
  // flight number and date) — no redundant "N flights" pill.
  const flight = isMulti ? '' : [trip.airline, trip.flight_number].filter(Boolean).join(' ');
  const facts = anon ? { kind: 'lang', items: [] } : tcQuickFacts(trip);
  const langs = facts.items.slice(0, 3);
  const restLangs = facts.items.length - langs.length;
  const traveller = anon ? '' : tcTraveller(trip);
  const msg = (!anon && trip.additional_comments) ? String(trip.additional_comments).replace(/\s+/g, ' ').trim() : '';

  const roleLabel = ROLE_LABELS[trip.role] || trip.role || '';
  const statusChip = ownTrip && trip.status && trip.status !== 'open'
    ? '<span class="tc-status chip-' + esc(trip.status) + '">' + esc(trip.status) + '</span>' : '';

  // Read top-to-bottom the way a companion-seeker scans: who + when, the route, its shape,
  // the practical facts (date, flight, languages, who's travelling) in fixed rows, then a
  // line of the poster's own words to make it a person, not a row in a table.
  card.innerHTML =
    '<div class="tc-band"></div>' +
    (matchMine ? '<div class="tc-matchflag"><i class="fa-solid fa-circle-check"></i> ' +
        'Matches your trip' + (matchMine.my_route ? ' ' + esc(matchMine.my_route) : '') +
        '<b>' + matchMine.score + '% match</b></div>' : '') +
    '<div class="tc-body">' +
      '<div class="tc-head">' +
        '<span class="tc-rolechip">' + esc(roleLabel) + '</span>' + statusChip +
        (dep ? '<span class="tc-when' + (dep.soon ? ' is-soon' : '') + (dep.past ? ' is-past' : '') + '">'
               + esc(dep.text) + '</span>' : '') +
      '</div>' +
      tcRouteHtml(trip, fp, tp) +
      tcRouteMeta(trip) +
      '<div class="tc-info">' +
        ((dateChip || flexible) ?
          '<div class="tc-inforow"><span class="tc-metapill"><i class="fa-solid fa-calendar-days"></i> ' +
            esc(dateChip || flexible) + '</span>' +
            (dateChip && flexible ? '<span class="tc-flextag">flexible</span>' : '') +
          '</div>' : '') +
        (flight ?
          '<div class="tc-inforow"><span class="tc-metapill is-flight"><i class="fa-solid fa-plane-up"></i> ' + esc(flight) + '</span></div>' : '') +
      '</div>' +
      ((langs.length || traveller) ?
        '<div class="tc-tags tcf-' + facts.kind + '">' +
          (traveller ? '<span class="tc-who"><i class="fa-solid fa-user"></i> ' + esc(traveller) + '</span>' : '') +
          '<span class="tc-tagicon" title="' + (facts.kind === 'need' ? 'Help wanted' : 'Speaks') + '">' +
            '<i class="fa-solid ' + (facts.kind === 'need' ? 'fa-hands-helping' : 'fa-language') + '"></i></span>' +
          langs.map(x => '<span class="tc-fact">' + esc(x) + '</span>').join('') +
          (restLangs > 0 ? '<span class="tc-fact tc-fact-more">+' + restLangs + '</span>' : '') +
        '</div>' : '') +
      (msg ? '<p class="tc-msg">' + esc(msg) + '</p>' : '') +
    '</div>' +
    '<div class="trip-card-footer"></div>';

  const footer = card.querySelector('.trip-card-footer');
  const author = document.createElement('div');
  author.className = 'trip-author';
  if (anon) {
    author.innerHTML = '<i class="fa-solid fa-user-secret"></i>';
    const s = document.createElement('span'); s.textContent = 'Anonymous'; author.appendChild(s);
  } else {
    if (trip.author && trip.author.photo_url) {
      const img = document.createElement('img'); img.src = trip.author.photo_url; img.alt = trip.author.username || '';
      author.appendChild(img);
    } else {
      author.innerHTML = '<i class="fa-solid fa-circle-user"></i>';
    }
    const s = document.createElement('span');
    s.textContent = (trip.author && trip.author.username) || 'Traveller';
    author.appendChild(s);
  }
  footer.appendChild(author);

  const actions = document.createElement('div');
  actions.className = 'tc-actions';
  // No separate "Details" link — the whole card opens the details popup on click/hover, so
  // the footer stays a single tight row (identity left, one primary action right).

  if (ownTrip) {
    if (trip.status === 'open' || trip.status === 'matched' || !trip.status) {
      // Modify and Close moved into the details panel; one button stays on the card.
      const legs = trip.legs_summary || [];
      const mt = document.createElement('button');
      mt.className = 'btn-sm-outline' + (trip.matches_count ? ' has-matches' : '');
      mt.innerHTML = '<i class="fa-solid fa-handshake"></i> ' + (trip.matches_count || 0)
                   + ' match' + (trip.matches_count === 1 ? '' : 'es');
      mt.onclick = e => { e.stopPropagation(); openMatchesModal(trip); };
      if (legs.length > 1) {
        // A multi-leg post is really several journeys and its matches belong to one leg
        // each, so the caret goes straight to the leg you mean instead of a mixed pile.
        const split = document.createElement('span');
        split.className = 'mt-split';
        mt.classList.add('mt-main');
        const caret = document.createElement('button');
        caret.className = 'btn-sm-outline mt-caret' + (trip.matches_count ? ' has-matches' : '');
        caret.type = 'button';
        caret.setAttribute('aria-label', 'Matches for one leg');
        caret.setAttribute('aria-expanded', 'false');
        caret.innerHTML = '<i class="fa-solid fa-chevron-down"></i>';
        // The card clips its own overflow (rounded header band), so the menu lives on the
        // body in a fixed layer and is positioned against the caret when opened.
        const menu = document.createElement('div');
        menu.className = 'mt-legmenu';
        menu.hidden = true;
        menu.addEventListener('click', e => e.stopPropagation());
        legs.forEach(l => {
          const row = document.createElement('button');
          row.type = 'button';
          row.className = 'mt-legrow' + (l.matches ? '' : ' is-empty');
          row.innerHTML =
            '<span class="mt-leg-name"><span class="mt-leg-label">' + esc(l.label) + '</span>' +
            '<span class="mt-leg-route">' + esc(l.short_route) + '</span></span>' +
            '<span class="mt-leg-n">' + l.matches + ' match' + (l.matches === 1 ? '' : 'es') + '</span>';
          row.onclick = e => { e.stopPropagation(); closeLegMenus(); openMatchesModal(trip, l.id); };
          menu.appendChild(row);
        });
        caret.onclick = e => {
          e.stopPropagation();
          const wasOpen = !menu.hidden;
          closeLegMenus();
          if (wasOpen) return;
          document.body.appendChild(menu);
          menu.hidden = false;
          menu.style.visibility = 'hidden';        // measure before placing
          const r = caret.getBoundingClientRect();
          const h = menu.offsetHeight, w = menu.offsetWidth;
          const below = window.innerHeight - r.bottom;
          menu.style.top = (below < h + 12 && r.top > h + 12 ? r.top - h - 6 : r.bottom + 6) + 'px';
          menu.style.left = Math.max(8, Math.min(r.right - w, window.innerWidth - w - 8)) + 'px';
          menu.style.visibility = '';
          caret.setAttribute('aria-expanded', 'true');
          split.classList.add('is-open');
        };
        split.append(mt, caret);
        actions.appendChild(split);
      } else {
        actions.appendChild(mt);
      }
    }
  } else {
    const btn = document.createElement('button');
    btn.className = 'connect-btn';
    btn.textContent = 'Connect';
    btn.onclick = e => {
      e.stopPropagation();
      if (IS_LOGGED_IN) openConnectModal(trip.id, (trip.author && trip.author.username) || 'this traveller');
      else window.location = '/auth/register';
    };
    actions.appendChild(btn);
  }
  footer.appendChild(actions);

  // The whole card is the door. Tap works for everyone; hover is only a desktop shortcut
  // to the same door (see tdHoverIntent), never the only way in.
  card.tabIndex = 0;
  card.setAttribute('role', 'button');
  card.addEventListener('click', () => openTripDetails(card, trip, ownTrip));
  card.addEventListener('keydown', e => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openTripDetails(card, trip, ownTrip); }
  });
  tdHoverIntent(card, trip, ownTrip);
  const tips = tcRouteTips(trip, fp, tp);
  card.querySelectorAll('.tc-flight-hot').forEach((el, i) => tcWireRouteTip(el, tips[i] || tips[tips.length - 1]));
  return card;
}


function closeLegMenus() {
  document.querySelectorAll('.mt-legmenu').forEach(m => { m.hidden = true; m.remove(); });
  document.querySelectorAll('.mt-split.is-open').forEach(s => s.classList.remove('is-open'));
  document.querySelectorAll('.mt-caret[aria-expanded="true"]')
          .forEach(b => b.setAttribute('aria-expanded', 'false'));
}
document.addEventListener('click', closeLegMenus);
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeLegMenus(); });
// the menu is anchored in viewport coordinates, so it must not outlive a scroll
window.addEventListener('scroll', closeLegMenus, true);
window.addEventListener('resize', closeLegMenus);


// ===== CONTACT ROWS (shared widget from cs/_macros.html) =====
function collectContactRows(container) {
  const rows = [];
  if (!container) return rows;
  container.querySelectorAll('.contact-row').forEach(tr => {
    const type = tr.querySelector('select[name="contact_type"]')?.value || 'auto';
    const value = tr.querySelector('input[name="contact_value"]')?.value.trim() || '';
    const label = tr.querySelector('input[name="contact_label"]')?.value.trim() || '';
    if (value || type === 'inapp_chat') rows.push({ type, value, label });
  });
  return rows;
}

// ===== POST TRIP =====
const TRIP_DRAFT_KEY = 'cd_trip_draft';

// Gather the whole post form into the object the API expects (also used verbatim as the
// draft we stash when a signed-out visitor has to register first).
function buildTripFormData() {
  const form = document.getElementById('searchForm');
  const isMulti = document.getElementById('tripTypeHidden').value === 'multi_destination';
  const formData = {};
  new FormData(form).forEach((v, k) => { if (!k.startsWith('contact_')) formData[k] = v; });
  if (isMulti) {
    formData.legs = collectLegs();
    formData.preferred_languages = [...document.querySelectorAll('#langSelectMulti input:checked')].map(el => el.value);
    formData.ticket_booked = document.querySelector('input[name="ticket_booked_multi"]')?.checked ? 'on' : '';
  } else {
    formData.preferred_languages = [...form.querySelectorAll('input[name="preferred_languages"]:checked')].map(el => el.value);
  }
  formData.connect_me_to = [...form.querySelectorAll('input[name="connect_me_to"]:checked')].map(el => el.value);
  // Per-person travellers → the trip-level summary the matcher and cards already understand:
  // who = joined tags, needs = union of everyone's, age/gender = the first traveller's.
  const travellers = collectTravellers();
  formData.travellers = travellers;
  formData.on_behalf_of = travellers.map(t => t.who).join(',');
  formData.traveller_needs = [...new Set(travellers.flatMap(t => t.needs))];
  formData.traveler_age_group = (travellers[0] || {}).age_group || '';
  formData.traveler_gender = (travellers[0] || {}).gender || '';
  formData.contact_points = collectContactRows(document.getElementById('contactRowsBody'));
  formData.contact_consent = !!document.getElementById('contactConsent')?.checked;
  return formData;
}

// Wipe the post form back to a pristine state after a successful post — native fields via
// reset(), then every custom widget (trip-type sections, travellers, multi-selects, the
// "any" toggles and the step wizard) put back to its default by hand, since reset() is silent.
function resetPostForm() {
  const form = document.getElementById('searchForm');
  if (!form) return;
  form.reset();
  const legs = document.getElementById('legsContainer'); if (legs) legs.innerHTML = '';
  applyTripTypeUI('one_way');
  if (window.setTravellers) setTravellers([]);
  form.querySelectorAll('select').forEach(s => { if (window.syncSearchSelect) syncSearchSelect(s); });
  document.getElementById('companionAny')?.dispatchEvent(new Event('change'));
  document.querySelector('#langSelect .lang-any')?.dispatchEvent(new Event('change'));
  form.querySelectorAll('.multi-dropdown').forEach(dd => updateMultiLabelEl(dd));
  if (window.__resetFormWizard) __resetFormWizard();
}

// Put a saved draft back into the form (after the visitor registers and lands on home again).
function restoreTripDraft(d) {
  const form = document.getElementById('searchForm');
  if (!form || !d) return;
  const attr = v => String(v).replace(/["\\]/g, '\\$&');
  const setVal = (n, v) => { const el = form.querySelector(`[name="${n}"]`);
    if (el && v != null && v !== '') { el.value = v; if (window.syncSearchSelect && el.tagName === 'SELECT') syncSearchSelect(el); } };
  const tt = d.trip_type || 'one_way';
  const r = form.querySelector(`input[name=trip_type][value="${attr(tt)}"]`);
  if (r) r.checked = true;
  applyTripTypeUI(tt);
  ['flying_from', 'destination', 'from_date', 'to_date', 'airline', 'flight_number',
   'return_airline', 'return_flight_number', 'category', 'additional_comments',
   'pref_gender', 'pref_age_min', 'pref_age_max', 'role'].forEach(n => setVal(n, d[n]));
  const setChk = (n, v) => { const el = form.querySelector(`input[name="${n}"]`); if (el) el.checked = _truthyVal(v); };
  setChk('is_anonymous', d.is_anonymous); setChk('ticket_booked', d.ticket_booked);
  (d.connect_me_to || []).forEach(v => { const cb = form.querySelector(`input[name=connect_me_to][value="${attr(v)}"]`); if (cb) cb.checked = true; });
  (d.preferred_languages || []).forEach(v => { const cb = form.querySelector(`input[name=preferred_languages][value="${attr(v)}"]`); if (cb) cb.checked = true; });
  // "any" toggles: keep them on only when the visitor set nothing specific
  const hasCompPrefs = (d.connect_me_to || []).length || (d.pref_gender && d.pref_gender !== 'any') || d.pref_age_min || d.pref_age_max;
  const compAny = document.getElementById('companionAny'); if (compAny) compAny.checked = !hasCompPrefs;
  const langAny = document.querySelector('#langSelect .lang-any'); if (langAny) langAny.checked = !(d.preferred_languages || []).length;
  if (window.setTravellers) setTravellers(d.travellers || []);
  if (tt === 'multi_destination' && (d.legs || []).length) {
    const cont = document.getElementById('legsContainer');
    while (cont && cont.children.length < d.legs.length) addLeg();
    document.querySelectorAll('#legsContainer .leg-row').forEach((row, i) => {
      const l = d.legs[i]; if (!l) return;
      row.querySelector('.leg-from').value = l.from || ''; row.querySelector('.leg-to').value = l.to || '';
      row.querySelector('.leg-date').value = l.date || ''; row.querySelector('.leg-airline').value = l.airline || '';
      row.querySelector('.leg-flightno').value = l.flight_number || '';
    });
  }
  compAny?.dispatchEvent(new Event('change'));
  langAny?.dispatchEvent(new Event('change'));
  form.querySelectorAll('.multi-dropdown').forEach(dd => updateMultiLabelEl(dd));
}
function _truthyVal(v) { return v === true || v === 'on' || v === 'true' || v === 1 || v === '1'; }

// After registering, the visitor lands back on home — repaint their saved trip into the form.
(function restoreDraftOnLoad() {
  if (!document.getElementById('searchForm')) return;
  let raw; try { raw = localStorage.getItem(TRIP_DRAFT_KEY); } catch (e) { return; }
  if (!raw) return;
  try { localStorage.removeItem(TRIP_DRAFT_KEY); } catch (e) {}
  let d; try { d = JSON.parse(raw); } catch (e) { return; }
  if (!d || !(d.flying_from || d.destination || (d.travellers || []).length)) return;
  restoreTripDraft(d);
  if (window.showToast) showToast("Welcome back — we kept your trip details. Review and post whenever you're ready.", 'success');
  document.getElementById('search')?.scrollIntoView({ behavior: 'smooth' });
})();

document.getElementById('postTripBtn')?.addEventListener('click', async () => {
  const formData = buildTripFormData();

  // A signed-out visitor can fill the whole form; rather than lose it at the sign-up wall, we
  // stash it and restore it after they come back logged in.
  if (!IS_LOGGED_IN) {
    try { localStorage.setItem(TRIP_DRAFT_KEY, JSON.stringify(formData)); } catch (e) {}
    if (window.showToast) showToast("Create your free account to post — we've saved your trip details.", 'info');
    setTimeout(() => { window.location = '/auth/register?next=%2F%23search'; }, 400);
    return;
  }

  const btn = document.getElementById('postTripBtn');
  btn.disabled = true;
  btn.classList.add('loading');
  try {
    const res = await apiFetch('/api/post-trip', { method: 'POST', body: JSON.stringify(formData) });
    const data = await res.json();
    if (data.success) {
      showToast(data.matches_count
        ? `Trip posted! We found ${data.matches_count} possible companion${data.matches_count === 1 ? '' : 's'} — see My Trips.`
        : 'Trip posted successfully! We will notify you when a companion on your route appears.', 'success');
      resetPostForm();
      loadResults();
      loadMyTrips();
      document.getElementById('my-trips')?.scrollIntoView({ behavior: 'smooth' });
    } else {
      showToast(data.error || 'Failed to post trip', 'danger');
    }
  } catch (e) {
    showToast('Network error. Please try again.', 'danger');
  } finally {
    btn.disabled = false;
    btn.classList.remove('loading');
  }
});

document.getElementById('findDesisBtn')?.addEventListener('click', () => {
  loadResults();
  document.getElementById('results')?.scrollIntoView({ behavior: 'smooth' });
});

// ===== MY TRIPS =====
// One page is two rows of four. The same data backs the home-page carousel and the
// dashboard's Trips tab, so both stay in step; only the pager chrome differs.
let _myTrips = [];
let _myTripsPage = 0;
let _myTripsFilterValues = null;          // set by the dashboard's My-trips filter panel

function myTripsList() {
  return _myTripsFilterValues
    ? _myTrips.filter(t => tripMatchesFilters(t, _myTripsFilterValues))
    : _myTrips;
}

function setMyTripsFilter(values) {
  _myTripsFilterValues = values && Object.keys(values).length ? values : null;
  _myTripsPage = 0;
  renderMyTripsPage();
}
function myTripsPerPage() {
  return gridColumns(document.getElementById('myTripsGrid')) * CAROUSEL_ROWS;
}

function renderMyTripsPage() {
  const grid = document.getElementById('myTripsGrid');
  if (!grid) return;
  const prev = document.getElementById('myTripsPrev');
  const next = document.getElementById('myTripsNext');
  const dots = document.getElementById('myTripsDots');
  const pager = document.getElementById('myTripsPager');
  const count = document.getElementById('myTripsCount');
  const viewAll = document.getElementById('myTripsViewAll');
  const per = myTripsPerPage();

  const list = myTripsList();
  grid.innerHTML = '';
  if (!list.length) {
    grid.innerHTML = _myTrips.length
      ? '<div class="loading-spinner">No trips match these filters.</div>'
      : '<div class="loading-spinner">You have no trips yet. Post one above!</div>';
    [prev, next].forEach(b => { if (b) b.style.display = 'none'; });
    if (dots) dots.innerHTML = '';
    if (pager) pager.innerHTML = '';
    if (count) count.textContent = '';
    if (viewAll) viewAll.hidden = true;
    return;
  }

  const pages = Math.ceil(list.length / per);
  _myTripsPage = Math.max(0, Math.min(_myTripsPage, pages - 1));
  list.slice(_myTripsPage * per, _myTripsPage * per + per)
      .forEach(t => grid.appendChild(buildTripCard(t, true)));

  if (count) count.textContent = list.length !== _myTrips.length
    ? `${list.length} of ${_myTrips.length} trips`
    : `${list.length} trip${list.length === 1 ? '' : 's'}`;
  // "View All" and the arrows only earn their place once there is a second page
  if (viewAll) viewAll.hidden = pages <= 1;
  [prev, next].forEach(b => { if (b) b.style.display = pages > 1 ? '' : 'none'; });
  if (prev) prev.disabled = _myTripsPage === 0;
  if (next) next.disabled = _myTripsPage >= pages - 1;

  if (dots) {                                  // home page: dots under the carousel
    dots.innerHTML = '';
    dots.classList.remove('pagination');
    if (pages > 8) {
      buildNumPager(dots, _myTripsPage + 1, pages, n => { _myTripsPage = n - 1; renderMyTripsPage(); });
    } else if (pages > 1) {
      for (let i = 0; i < pages; i++) {
        const d = document.createElement('span');
        d.className = 'carousel-dot' + (i === _myTripsPage ? ' active' : '');
        d.onclick = () => { _myTripsPage = i; renderMyTripsPage(); };
        dots.appendChild(d);
      }
    }
  }
  if (pager) {                                 // dashboard: numbered pager
    buildNumPager(pager, _myTripsPage + 1, pages, n => {
      _myTripsPage = n - 1; renderMyTripsPage();
      grid.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }
}

function myTripsNav(dir) {
  const pages = Math.ceil(myTripsList().length / myTripsPerPage());
  if (pages < 2) return;
  const next = Math.max(0, Math.min(_myTripsPage + dir, pages - 1));
  if (next === _myTripsPage) return;
  _myTripsPage = next;
  renderMyTripsPage();
}

async function loadMyTrips() {
  const grid = document.getElementById('myTripsGrid');
  if (!grid || !IS_LOGGED_IN) return;
  if (!grid.dataset.loaded) { skeletonTripCards(grid, 4); grid.dataset.loaded = '1'; }

  const res = await apiFetch('/api/my-trips');
  const data = await res.json();
  _myTrips = data.trips || [];
  _myTripsPage = 0;
  renderMyTripsPage();
}

// ===== TRIP FILTER PANEL (see templates/_trip_filters.html) =====
// Reads the panel with the given id prefix into /api/search parameters. Empty inputs are
// omitted, so the server treats them as "don't filter".
function tripFilterValues(prefix) {
  const el = id => document.getElementById(prefix + id);
  if (!el('Panel')) return {};
  const out = {};
  const from = (el('From') || {}).value || '';
  const to = (el('To') || {}).value || '';
  const when = (el('Date') || {}).value || '';
  if (from.trim()) out.flying_from = from.trim();
  if (to.trim()) out.destination = to.trim();
  if (when) {
    out.from_date = when;
    out.flex_days = parseInt((el('Flex') || {}).value || '0', 10) || 0;
  }
  const tripTypes = Array.from(document.querySelectorAll(`.${prefix}TripType:checked`)).map(c => c.value);
  if (tripTypes.length) out.trip_types = tripTypes;
  const role = document.querySelector(`input[name="${prefix}Role"]:checked`);
  if (role && role.value) out.role = role.value;
  const lang = (el('Lang') || {}).value || '';
  if (lang) out.language = lang;
  const booking = document.querySelector(`input[name="${prefix}Booking"]:checked`);
  if (booking && booking.value) out.booking = booking.value;
  const genders = Array.from(document.querySelectorAll(`.${prefix}Gender:checked`)).map(c => c.value);
  if (genders.length) out.genders = genders;
  const users = document.querySelector(`input[name="${prefix}Users"]:checked`);
  if (users && users.value === 'verified') out.verified_only = true;
  return out;
}

// The same test /api/search applies, for lists that are filtered in the browser (My trips).
function tripMatchesFilters(t, f) {
  const contains = (fields, needle) => {
    needle = needle.toLowerCase();
    return fields.some(x => (x || '').toLowerCase().includes(needle));
  };
  const legs = t.legs || [];
  if (f.flying_from && !contains([t.flying_from, t.origin_iata, ...legs.map(l => l.from)], f.flying_from)) return false;
  if (f.destination && !contains([t.destination, t.dest_iata, ...legs.map(l => l.to)], f.destination)) return false;
  if (f.booking === 'booked' && !t.ticket_booked) return false;
  if (f.booking === 'planned' && t.ticket_booked) return false;
  if (f.trip_types && !f.trip_types.includes(t.trip_type || 'one_way')) return false;
  if (f.genders && !f.genders.includes(t.traveler_gender)) return false;
  if (f.from_date) {
    if (!t.from_date) return false;
    const window = f.flex_days !== undefined ? f.flex_days : 3;
    const days = Math.abs(new Date(t.from_date) - new Date(f.from_date)) / 86400000;
    if (days > window) return false;
  }
  return true;
}

function initTripFilters(prefix, onChange) {
  const panel = document.getElementById(prefix + 'Panel');
  if (!panel) return;
  const el = id => document.getElementById(prefix + id);
  const paint = () => {
    const flex = el('Flex'), label = el('FlexLabel'), hint = el('FlexHint');
    const hasDate = !!(el('Date') && el('Date').value);
    if (flex) flex.disabled = !hasDate;
    if (label) label.textContent = hasDate && +((flex || {}).value || 0)
      ? `±${flex.value} day${flex.value === '1' ? '' : 's'}` : 'exact';
    if (hint) hint.style.display = hasDate ? 'none' : '';
  };
  paint();
  let timer = null;
  const fire = () => { clearTimeout(timer); timer = setTimeout(() => { paint(); onChange(); }, 250); };
  panel.querySelectorAll('input').forEach(inp => {
    inp.addEventListener('change', fire);
    if (inp.type === 'text') inp.addEventListener('input', fire);
    if (inp.type === 'range') inp.addEventListener('input', paint);   // live label while dragging
  });
  panel.querySelectorAll('.tf-clear').forEach(b => b.addEventListener('click', () => {
    const target = document.getElementById(b.dataset.clears);
    if (target && target.value) { target.value = ''; paint(); onChange(); }
  }));
  const reset = el('Reset');
  if (reset) reset.addEventListener('click', () => {
    panel.querySelectorAll('input').forEach(inp => {
      if (inp.type === 'checkbox') inp.checked = false;
      else if (inp.type === 'radio') inp.checked = inp.value === '';
      else if (inp.type === 'range') inp.value = '0';
      else inp.value = '';
    });
    paint(); onChange();
  });
  const search = el('Search');
  if (search) search.addEventListener('click', () => { paint(); onChange(); });
}

async function disableTrip(tripId) {
  showConfirm('Close this trip?', 'It will be removed from search results. You can ask support to reopen it.', async () => {
    const res = await apiFetch(`/api/trip/${tripId}`, { method: 'DELETE', body: JSON.stringify({ reason: 'no_longer_required' }) });
    const data = await res.json();
    if (data.success) {
      showToast('Trip closed.', 'success');
      loadMyTrips();
      loadResults();
    } else {
      showToast(data.error || 'Could not close trip', 'danger');
    }
  });
}

// ===== MODIFY TRIP (in place) =====
async function modifyTrip(tripId) {
  const modal = document.getElementById('editTripModal');
  if (!modal) { window.location = '/dashboard'; return; }
  const res = await apiFetch(`/api/trip/${tripId}`);
  const d = await res.json();
  if (!d.trip) return showToast(d.error || 'Could not load this trip.', 'danger');
  const t = d.trip;
  const f = document.getElementById('editTripForm');
  f.elements.trip_id.value = t.id;
  f.elements.role.value = t.role || 'seeking_help';
  f.elements.flying_from.value = t.flying_from || '';
  f.elements.destination.value = t.destination || '';
  f.elements.from_date.value = t.from_date || '';
  f.elements.to_date.value = t.to_date || '';
  f.elements.airline.value = t.airline || '';
  f.elements.flight_number.value = t.flight_number || '';
  if (f.elements.return_airline) f.elements.return_airline.value = t.return_airline || '';
  if (f.elements.return_flight_number) f.elements.return_flight_number.value = t.return_flight_number || '';
  f.elements.additional_comments.value = t.additional_comments || '';
  f.elements.ticket_booked.checked = !!t.ticket_booked;
  f.elements.is_anonymous.checked = !!t.is_anonymous;
  // multi-selects: set the native options, then tell the searchable wrapper to repaint
  const setMulti = (sel, values) => {
    const el = f.elements[sel];
    if (!el) return;
    [...el.options].forEach(o => { o.selected = (values || []).includes(o.value); });
    if (window.syncSearchSelect) window.syncSearchSelect(el);
  };
  setMulti('preferred_languages', t.preferred_languages);
  setMulti('connect_me_to', t.connect_me_to);
  if (window.syncSearchSelect) window.syncSearchSelect(f.elements.role);
  // Per-person travellers — fall back to the legacy single-traveller columns for posts
  // created before the travellers list existed.
  etRenderTravellers(travellersFromTrip(t));
  // the rest of the fields the modify form now mirrors from the post form
  const setV = (n, v) => { const el = f.elements[n]; if (!el) return; el.value = (v == null ? '' : v); if (window.syncSearchSelect) window.syncSearchSelect(el); };
  setV('pref_gender', t.pref_gender || 'any');
  setV('category', t.category);
  if (f.elements.pref_age_min) f.elements.pref_age_min.value = (t.pref_age_min == null ? '' : t.pref_age_min);
  if (f.elements.pref_age_max) f.elements.pref_age_max.value = (t.pref_age_max == null ? '' : t.pref_age_max);
  ['flying_from_flexible', 'destination_flexible', 'from_date_flexible', 'to_date_flexible']
    .forEach(n => { if (f.elements[n]) f.elements[n].checked = !!t[n]; });
  const routeLabel = document.getElementById('etRoute');
  if (routeLabel) routeLabel.textContent = `${t.flying_from || '?'} → ${t.destination || '?'}`;

  const type = t.trip_type || 'one_way';
  const radio = f.querySelector(`input[name="trip_type"][value="${type}"]`);
  if (radio) radio.checked = true;
  etRenderLegs(type === 'multi_destination' ? (t.legs || []) : []);
  etApplyType(type);
  modal.style.display = 'flex';
}

/* ---- multi-stop legs in the modify form -------------------------------------
 * A post can also change shape here: adding a return date makes a one-way into a round
 * trip, and switching to multi-stop turns its single route into legs you can edit. The
 * server rebuilds trip_legs from whatever shape comes back, so matching follows.
 */
function etApplyType(type) {
  const simple = document.getElementById('etSimpleRoute');
  const legs = document.getElementById('etLegs');
  const ret = document.getElementById('editReturnRow');
  if (!simple || !legs) return;
  const multi = type === 'multi_destination';
  const isRound = type === 'round_trip';
  simple.hidden = multi;
  legs.hidden = !multi;
  if (ret) ret.style.display = isRound ? '' : 'none';
  ['etReturnAirlineField', 'etReturnFlightField'].forEach(id => {
    const el = document.getElementById(id); if (el) el.hidden = !isRound;
  });
  if (multi && !document.querySelectorAll('#etLegRows .et-leg').length) {
    // converting into a multi-stop: seed it from the route already on screen
    const f = document.getElementById('editTripForm');
    etAddLeg({ from: f.elements.flying_from.value, to: f.elements.destination.value,
               date: f.elements.from_date.value, airline: f.elements.airline.value,
               flight_number: f.elements.flight_number.value });
    etAddLeg({ from: f.elements.destination.value });
  }
}

function etNumberLegs() {
  document.querySelectorAll('#etLegRows .et-leg').forEach((row, i) => {
    row.querySelector('.et-leg-n').textContent = i + 1;
    // two hops is the minimum that makes a multi-stop trip
    row.querySelector('.et-leg-x').hidden = document.querySelectorAll('#etLegRows .et-leg').length <= 2;
  });
}

function etAddLeg(leg = {}) {
  const rows = document.getElementById('etLegRows');
  const tpl = document.getElementById('etLegTpl');
  if (!rows || !tpl) return;
  const node = tpl.content.cloneNode(true);
  const row = node.querySelector('.et-leg');
  row.querySelector('.et-leg-from').value = leg.from || '';
  row.querySelector('.et-leg-to').value = leg.to || '';
  row.querySelector('.et-leg-date').value = leg.date || '';
  row.querySelector('.et-leg-air').value = leg.airline || '';
  row.querySelector('.et-leg-fno').value = leg.flight_number || '';
  row.querySelector('.et-leg-x').addEventListener('click', () => {
    if (document.querySelectorAll('#etLegRows .et-leg').length <= 2) return;
    row.remove();
    etNumberLegs();
  });
  rows.appendChild(node);
  etNumberLegs();
  // wireAirportAutocomplete/wireAirlineAutocomplete already exist for exactly this --
  // the one-off pass at load cannot see a row that is added later.
  wireAirportAutocomplete([row.querySelector('.et-leg-from'), row.querySelector('.et-leg-to')]);
  wireAirlineAutocomplete([row.querySelector('.et-leg-air')]);
}

function etRenderLegs(legs) {
  const rows = document.getElementById('etLegRows');
  if (!rows) return;
  rows.innerHTML = '';
  (legs.length ? legs : []).forEach(etAddLeg);
  etNumberLegs();
}

function etCollectLegs() {
  return [...document.querySelectorAll('#etLegRows .et-leg')].map(r => ({
    from: r.querySelector('.et-leg-from').value.trim(),
    to: r.querySelector('.et-leg-to').value.trim(),
    date: r.querySelector('.et-leg-date').value,
    airline: r.querySelector('.et-leg-air').value.trim(),
    flight_number: r.querySelector('.et-leg-fno').value.trim(),
  })).filter(l => l.from || l.to);
}

/* ---- per-person travellers in the modify form ("one companion for the whole group") --- */
function travellersFromTrip(t) {
  if (Array.isArray(t.travellers) && t.travellers.length) return t.travellers;
  // legacy posts: rebuild one row per who-tag, sharing the old single age/gender/needs
  const whos = (t.on_behalf_of || '').split(',').map(s => s.trim()).filter(Boolean);
  if (!whos.length) return [{ who: '', age_group: t.traveler_age_group || '', gender: t.traveler_gender || '', needs: t.traveller_needs || [] }];
  return whos.map((who, i) => ({
    who,
    age_group: i === 0 ? (t.traveler_age_group || '') : '',
    gender: i === 0 ? (t.traveler_gender || '') : '',
    needs: i === 0 ? (t.traveller_needs || []) : [],
  }));
}

function etNumberTravellers() {
  document.querySelectorAll('#etTravellersRows .tv-card').forEach((c, i) => { c.querySelector('.tv-n').textContent = i + 1; });
}

function etAddTraveller(data = {}) {
  const rows = document.getElementById('etTravellersRows');
  const tpl = document.getElementById('etTravellerTpl');
  if (!rows || !tpl) return;
  const node = tpl.content.firstElementChild.cloneNode(true);
  node.querySelector('.tv-who').value = data.who || '';
  node.querySelector('.tv-age').value = data.age_group || '';
  node.querySelector('.tv-gender').value = data.gender || '';
  const needs = data.needs || [];
  node.querySelectorAll('.tv-need').forEach(cb => { cb.checked = needs.includes(cb.value); });
  const nd = node.querySelector('.tv-needs .multi-dropdown');
  if (nd) updateMultiLabelEl(nd);
  node.querySelector('.tv-x').addEventListener('click', () => {
    if (rows.children.length <= 1) return;
    node.remove(); etNumberTravellers();
  });
  rows.appendChild(node);
  etNumberTravellers();
}

function etRenderTravellers(list) {
  const rows = document.getElementById('etTravellersRows');
  if (!rows) return;
  rows.innerHTML = '';
  (list && list.length ? list : [{}]).forEach(etAddTraveller);
}

function etCollectTravellers() {
  return [...document.querySelectorAll('#etTravellersRows .tv-card')].map(c => ({
    who: c.querySelector('.tv-who').value,
    age_group: c.querySelector('.tv-age').value,
    gender: c.querySelector('.tv-gender').value,
    needs: [...c.querySelectorAll('.tv-need:checked')].map(n => n.value),
  })).filter(t => t.who);
}

document.getElementById('etAddTravellerBtn')?.addEventListener('click', () => etAddTraveller());

document.getElementById('etAddLeg')?.addEventListener('click', () => etAddLeg());
document.getElementById('etTypes')?.addEventListener('change', e => {
  if (e.target.name === 'trip_type') etApplyType(e.target.value);
});

document.getElementById('closeEditTripModal')?.addEventListener('click', () => { document.getElementById('editTripModal').style.display = 'none'; });
document.getElementById('cancelEditTrip')?.addEventListener('click', () => { document.getElementById('editTripModal').style.display = 'none'; });

document.getElementById('editTripForm')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const f = e.target;
  const id = f.elements.trip_id.value;
  const type = (f.querySelector('input[name="trip_type"]:checked') || {}).value || 'one_way';
  const legs = type === 'multi_destination' ? etCollectLegs() : [];
  const body = {
    role: f.elements.role.value,
    trip_type: type,
    legs,
    flying_from: f.elements.flying_from.value.trim(),
    destination: f.elements.destination.value.trim(),
    from_date: f.elements.from_date.value,
    to_date: type === 'round_trip' ? f.elements.to_date.value : '',
    airline: f.elements.airline.value.trim(),
    flight_number: f.elements.flight_number.value.trim(),
    return_airline: type === 'round_trip' ? (f.elements.return_airline?.value.trim() || '') : '',
    return_flight_number: type === 'round_trip' ? (f.elements.return_flight_number?.value.trim() || '') : '',
    additional_comments: f.elements.additional_comments.value.trim(),
    ticket_booked: f.elements.ticket_booked.checked,
    is_anonymous: f.elements.is_anonymous.checked,
    preferred_languages: [...(f.elements.preferred_languages?.selectedOptions || [])].map(o => o.value),
    connect_me_to: [...(f.elements.connect_me_to?.selectedOptions || [])].map(o => o.value),
    travellers: etCollectTravellers(),
    pref_gender: f.elements.pref_gender?.value || 'any',
    pref_age_min: f.elements.pref_age_min?.value ? parseInt(f.elements.pref_age_min.value, 10) : null,
    pref_age_max: f.elements.pref_age_max?.value ? parseInt(f.elements.pref_age_max.value, 10) : null,
    category: f.elements.category?.value || '',
    flying_from_flexible: !!f.elements.flying_from_flexible?.checked,
    destination_flexible: !!f.elements.destination_flexible?.checked,
    from_date_flexible: !!f.elements.from_date_flexible?.checked,
    to_date_flexible: !!f.elements.to_date_flexible?.checked,
  };
  if (type === 'multi_destination') {
    if (legs.length < 2) return showToast('A multi-stop trip needs at least two stops.', 'danger');
    if (legs.some(l => !l.from || !l.to || !l.date)) {
      return showToast('Every stop needs a from, a to and a date.', 'danger');
    }
  } else if (!body.flying_from || !body.destination || !body.from_date) {
    return showToast('Route and departure date are required.', 'danger');
  }
  if (!body.travellers.length) return showToast('Add at least one traveller — who is this trip for?', 'danger');
  const res = await apiFetch(`/api/trip/${id}`, { method: 'PUT', body: JSON.stringify(body) });
  const d = await res.json();
  if (d.success) {
    document.getElementById('editTripModal').style.display = 'none';
    showToast('Trip updated. Matches have been refreshed.', 'success');
    loadMyTrips();
    loadResults();
    if (document.getElementById('dashMatches')) setTimeout(() => location.reload(), 600);
  } else {
    showToast(d.error || 'Update failed', 'danger');
  }
});

// ===== MATCHES MODAL (my trips) =====
document.getElementById('closeMatchesModal')?.addEventListener('click', () => {
  document.getElementById('matchesModal').style.display = 'none';
});

function criteriaChips(criteria) {
  const wrap = document.createElement('div'); wrap.className = 'criteria';
  (criteria || []).forEach(c => {
    const s = document.createElement('span'); s.className = 'crit ' + (c.ok ? 'crit-ok' : 'crit-no');
    s.innerHTML = `<i class="fa-solid ${c.ok ? 'fa-check' : 'fa-xmark'}"></i> `;
    s.appendChild(document.createTextNode(`${c.label}: ${c.detail}`));
    wrap.appendChild(s);
  });
  return wrap;
}

const MB = { trips: [], ti: 0, allMatches: [], matches: [], mi: 0, legId: null };

async function openMatchesModal(trip, legId) {
  const modal = document.getElementById('matchesModal');
  if (!modal) return;
  modal.style.display = 'flex';
  try {
    const res = await apiFetch('/api/my-trips');
    const d = await res.json();
    MB.trips = (d.trips || d.results || []).filter(t => t.status !== 'closed');
  } catch (e) { MB.trips = []; }
  if (!MB.trips.length) MB.trips = [trip];
  MB.ti = Math.max(0, MB.trips.findIndex(t => t.id === trip.id));
  MB.legId = legId || null;
  // With no "All trips" chip, a multi-leg post opens on its first leg that has matches (else
  // the first leg), so a chip is always active and the panel is never empty by default.
  const cur = MB.trips[MB.ti];
  const ls = (cur && cur.legs_summary) || [];
  if (!MB.legId && ls.length >= 2) MB.legId = (ls.find(l => l.matches) || ls[0]).id;
  renderMbPost();
  await loadMbMatches();
}

/* Which leg's matches are on screen. The chips stay in the panel so the choice is always
   visible and reversible -- the dropdown that opened it is long gone behind the modal. */
function renderMbLegs() {
  const bar = document.getElementById('mbLegs');
  if (!bar) return;
  const t = MB.trips[MB.ti] || {};
  const legs = t.legs_summary || [];
  bar.innerHTML = '';
  if (legs.length < 2) { bar.hidden = true; return; }
  bar.hidden = false;
  const mk = (label, sub, n, id) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'mb-legchip' + (MB.legId === id ? ' is-on' : '');
    b.setAttribute('aria-pressed', MB.legId === id ? 'true' : 'false');
    b.innerHTML = `<span class="mb-legchip-t">${esc(label)}</span>` +
                  (sub ? `<span class="mb-legchip-s">${esc(sub)}</span>` : '') +
                  `<span class="mb-legchip-n">${n}</span>`;
    b.onclick = () => { MB.legId = id; MB.mi = 0; renderMbLegs(); renderMbPost(); renderMbMatch(); };
    return b;
  };
  // one chip per trip/leg only — no aggregate "All trips" chip
  legs.forEach(l => bar.appendChild(mk(l.label, l.short_route, l.matches, l.id)));
}

function mbVisibleMatches() {
  if (!MB.legId) return MB.allMatches;
  return MB.allMatches.filter(m => m.my_leg && m.my_leg.id === MB.legId);
}

/* The post shown beside the matches is the one the matches are for. When a single trip
   of a multi-stop itinerary is selected, that is the trip to show -- displaying the whole
   HYD -> LHR journey next to matches for DXB -> LHR invites the reader to compare the
   wrong two routes. */
function mbPostView() {
  const t = MB.trips[MB.ti];
  if (!MB.legId) return t;
  const leg = (t.legs_summary || []).find(l => l.id === MB.legId);
  if (!leg) return t;
  return Object.assign({}, t, {
    flying_from: leg.origin_text, destination: leg.dest_text,
    origin_iata: leg.origin_iata, dest_iata: leg.dest_iata,
    from_date: leg.depart_date, to_date: null,
    from_date_flexible: leg.date_flexible,
    airline: leg.airline, flight_number: leg.flight_number,
    trip_type: 'one_way', legs: [], legs_summary: [],
  });
}

function renderMbPost() {
  const t = mbPostView();
  const el = document.getElementById('mbPost');
  el.innerHTML = '';
  const card = buildTripCard(t, true);
  card.querySelector('.tc-actions')?.remove();   // the panel's own post is read-only
  el.appendChild(card);
  document.getElementById('mbPostIdx').textContent = `${MB.ti + 1} / ${MB.trips.length}`;
  document.getElementById('mbPostSwitch').style.display = MB.trips.length > 1 ? '' : 'none';
}

async function loadMbMatches() {
  const t = MB.trips[MB.ti];
  const box = document.getElementById('mbMatch');
  skeletonListRows(box, 4);
  try {
    const res = await apiFetch(`/api/trip/${t.id}/matches?recompute=1`);
    const data = await res.json();
    MB.allMatches = data.matches || [];
  } catch (e) { MB.allMatches = []; }
  // a leg picked from the card's dropdown may since have lost its only match
  if (MB.legId && !MB.allMatches.some(m => m.my_leg && m.my_leg.id === MB.legId)) {
    if (!(t.legs_summary || []).some(l => l.id === MB.legId)) MB.legId = null;
  }
  MB.mi = 0;
  renderMbLegs();
  renderMbPost();
  renderMbMatch();
}

function renderMbMatch() {
  const box = document.getElementById('mbMatch');
  const sw = document.getElementById('mbMatchSwitch');
  MB.matches = mbVisibleMatches();
  if (MB.mi >= MB.matches.length) MB.mi = 0;
  box.innerHTML = '';
  if (!MB.matches.length) {
    sw.style.display = 'none';
    const legName = MB.legId
      ? ((MB.trips[MB.ti].legs_summary || []).find(l => l.id === MB.legId) || {}).short_route
      : null;
    box.innerHTML = `<div class="mb-empty"><i class="fa-solid fa-magnifying-glass"></i>` +
      `<h3>No match yet${legName ? ` on ${esc(legName)}` : ''}</h3>` +
      `<p>We keep scoring every new post on ${legName ? 'this leg' : 'this route'} and will ` +
      `notify you the moment a companion appears.${MB.legId && MB.allMatches.length
        ? ' Your other legs do have matches — pick one above.' : ''}</p></div>`;
    return;
  }
  sw.style.display = MB.matches.length > 1 ? '' : 'none';
  document.getElementById('mbMatchIdx').textContent = `${MB.mi + 1} / ${MB.matches.length}`;
  const m = MB.matches[MB.mi];
  const o = m.other || {};

  const head = document.createElement('div'); head.className = 'mb-profile-head';
  const av = document.createElement('div'); av.className = 'mb-avatar';
  if (o.author?.photo_url) { const img = document.createElement('img'); img.src = o.author.photo_url; av.appendChild(img); }
  else av.innerHTML = o.is_anonymous ? '<i class="fa-solid fa-user-secret"></i>' : '<i class="fa-solid fa-user"></i>';
  const who = document.createElement('div'); who.className = 'who';
  const nm = document.createElement('strong'); nm.textContent = o.is_anonymous ? 'Anonymous traveller' : (o.author?.username || o.poster_name || 'Traveller');
  const role = document.createElement('span'); role.className = `trip-role-badge chip-role-${esc(o.role || '')}`; role.textContent = ROLE_LABELS[o.role] || o.role || '';
  const langs = document.createElement('div'); langs.className = 'muted'; langs.style.fontSize = '12px';
  langs.textContent = (o.preferred_languages || []).length ? `speaks ${o.preferred_languages.join(', ')}` : '';
  who.append(nm, role, langs);
  const score = document.createElement('div');
  score.className = 'score-tab st-' + (m.score >= 75 ? 'high' : m.score >= 55 ? 'mid' : 'low');
  score.innerHTML = `<span>${m.score}%</span><small>match</small>`;
  head.append(av, who, score);
  box.appendChild(head);

  const card = buildTripCard(o, false);
  card.querySelector('.trip-card-footer')?.remove();
  card.querySelector('.tc-tear')?.remove();
  card.classList.add('mb-trip');
  box.appendChild(card);

  box.appendChild(criteriaChips(m.criteria));

  const status = document.createElement('div'); status.className = 'mb-status';
  const mine = m.my_status, theirs = m.their_status;
  status.textContent = mine || theirs
    ? `You: ${(mine || 'not notified').replace(/_/g, ' ')} · Them: ${(theirs || 'not notified').replace(/_/g, ' ')}`
    : 'Nobody\u2019s contact details have been shared yet.';
  box.appendChild(status);

  const actions = document.createElement('div'); actions.className = 'match-actions';
  if (m.status !== 'connected' && m.status !== 'dismissed') {
    const share = document.createElement('button'); share.className = 'btn btn-primary';
    share.style.cssText = 'padding:9px 16px;font-size:13px';
    share.innerHTML = '<i class="fa-solid fa-paper-plane"></i> Share my contact & notify';
    share.onclick = async () => {
      share.disabled = true;
      const r = await apiFetch(`/api/matches/${m.id}/notify`, { method: 'POST', body: '{}' });
      const d = await r.json();
      if (d.success) {
        showToast('Introduction sent. Check the link in your notifications.', 'success');
        if (d.problems?.length) d.problems.forEach(p => showToast(p, 'info'));
        loadMbMatches();
      } else { showToast(d.error || 'Failed', 'danger'); share.disabled = false; }
    };
    actions.appendChild(share);
  }
  if (o.author && m.status !== 'connected' && m.status !== 'dismissed') {
    const req = document.createElement('button'); req.className = 'btn-sm-outline';
    req.innerHTML = '<i class="fa-solid fa-address-card"></i> Request their contact details';
    req.onclick = async () => {
      req.disabled = true;
      const r = await apiFetch(`/api/matches/${m.id}/request-contact`, { method: 'POST', body: '{}' });
      const d = await r.json();
      if (d.success) showToast(d.message || 'Request sent - it will appear in their inbox.', 'success');
      else { showToast(d.error || 'Could not send the request', r.status === 429 ? 'info' : 'danger'); }
      req.disabled = false;
    };
    actions.appendChild(req);
  }
  if (m.my_token) {
    const open = document.createElement('a'); open.className = 'btn-sm-outline'; open.href = `/match/${m.my_token}`;
    open.innerHTML = '<i class="fa-solid fa-address-card"></i> Contact details';
    actions.appendChild(open);
  }
  if (m.status !== 'dismissed') {
    const dis = document.createElement('button'); dis.className = 'btn-sm-outline danger'; dis.textContent = 'Not suitable';
    dis.onclick = async () => {
      const r = await apiFetch(`/api/matches/${m.id}/dismiss`, { method: 'POST', body: JSON.stringify({ reason: 'not_suitable' }) });
      if ((await r.json()).success) { showToast('Match dismissed', 'info'); loadMbMatches(); loadMyTrips(); }
    };
    actions.appendChild(dis);
  }
  box.appendChild(actions);
}

function mbCycleMatch(delta) {
  if (MB.matches.length < 2) return;
  MB.mi = (MB.mi + delta + MB.matches.length) % MB.matches.length;
  renderMbMatch();
}
function mbCyclePost(delta) {
  if (MB.trips.length < 2) return;
  MB.ti = (MB.ti + delta + MB.trips.length) % MB.trips.length;
  renderMbPost();
  loadMbMatches();
}
document.getElementById('mbPrevMatch')?.addEventListener('click', () => mbCycleMatch(-1));
document.getElementById('mbNextMatch')?.addEventListener('click', () => mbCycleMatch(1));
document.getElementById('mbPrevPost')?.addEventListener('click', () => mbCyclePost(-1));
document.getElementById('mbNextPost')?.addEventListener('click', () => mbCyclePost(1));
document.addEventListener('keydown', (e) => {
  const modal = document.getElementById('matchesModal');
  if (!modal || modal.style.display === 'none') return;
  if (e.key === 'ArrowDown') { e.preventDefault(); mbCycleMatch(1); }
  if (e.key === 'ArrowUp') { e.preventDefault(); mbCycleMatch(-1); }
  if (e.key === 'Escape') modal.style.display = 'none';
});

// ===== CONNECTION REQUEST MODAL =====
function openConnectModal(tripId, username) {
  const modal = document.getElementById('connectModal');
  if (!modal) { showToast('Could not open the connection dialog on this page.', 'danger'); return; }
  document.getElementById('connectTripId').value = tripId;
  document.getElementById('connectModalSubtitle').textContent = `Send a connection request to ${username}. They will be notified and can accept or decline.`;
  document.getElementById('connectAnonymous').checked = false;
  modal.style.display = 'flex';
}

document.getElementById('closeConnectModal')?.addEventListener('click', () => {
  document.getElementById('connectModal').style.display = 'none';
});
document.getElementById('cancelConnectBtn')?.addEventListener('click', () => {
  document.getElementById('connectModal').style.display = 'none';
});

document.getElementById('confirmConnectBtn')?.addEventListener('click', async () => {
  const tripId = document.getElementById('connectTripId').value;
  const anonymous = document.getElementById('connectAnonymous').checked;
  try {
    const res = await apiFetch(`/api/connect/${tripId}`, {
      method: 'POST',
      body: JSON.stringify({ anonymous }),
    });
    const data = await res.json();
    document.getElementById('connectModal').style.display = 'none';
    if (res.status === 409) return showToast('You have already sent a request for this trip.', 'info');
    if (data.success) showToast('Connection request sent!', 'success');
    else showToast(data.error || 'Something went wrong.', 'danger');
  } catch {
    showToast('Something went wrong.', 'danger');
  }
});

// ===== RESPOND TO CONNECTION MODAL =====
function openRespondModal(connectionId, body) {
  const modal = document.getElementById('respondModal');
  if (!modal) { window.location = '/connections'; return; }
  document.getElementById('respondConnectionId').value = connectionId;
  document.getElementById('respondModalBody').textContent = body;
  document.getElementById('respondAnonymous').checked = false;
  modal.style.display = 'flex';
}

document.getElementById('closeRespondModal')?.addEventListener('click', () => {
  document.getElementById('respondModal').style.display = 'none';
});

async function respondConnection(action) {
  const connectionId = document.getElementById('respondConnectionId').value;
  const anonymous = document.getElementById('respondAnonymous').checked;
  try {
    const res = await apiFetch(`/api/connect/${connectionId}/respond`, {
      method: 'POST',
      body: JSON.stringify({ action, anonymous }),
    });
    const data = await res.json();
    document.getElementById('respondModal').style.display = 'none';
    if (data.success) {
      showToast(action === 'accept' ? 'Connection accepted!' : 'Request declined.', 'success');
      pollUnread();
    } else {
      showToast(data.error || 'Something went wrong.', 'danger');
    }
  } catch {
    showToast('Something went wrong.', 'danger');
  }
}

document.getElementById('acceptConnectionBtn')?.addEventListener('click', () => respondConnection('accept'));
document.getElementById('denyConnectionBtn')?.addEventListener('click', () => respondConnection('deny'));

// ===== CONFIRM MODAL =====
let confirmCallback = null;
function showConfirm(title, msg, callback) {
  const modal = document.getElementById('confirmModal');
  if (!modal) { if (confirm(`${title}\n${msg}`)) callback(); return; }
  document.getElementById('confirmTitle').textContent = title;
  document.getElementById('confirmMsg').textContent = msg;
  confirmCallback = callback;
  modal.style.display = 'flex';
}
document.getElementById('confirmYes')?.addEventListener('click', () => {
  document.getElementById('confirmModal').style.display = 'none';
  if (confirmCallback) confirmCallback();
});
document.getElementById('confirmNo')?.addEventListener('click', () => {
  document.getElementById('confirmModal').style.display = 'none';
});

// ===== REVIEW FORM =====
let selectedRating = 0;
const RATE_LABELS = ['Tap to rate', 'Poor', 'Okay', 'Good', 'Very good', 'Excellent!'];
function paintStars(n, hovering) {
  document.querySelectorAll('.star-rating i').forEach((s, i) => {
    const on = i < n;
    s.classList.toggle('active', on);
    s.classList.toggle('fa-solid', on);
    s.classList.toggle('fa-regular', !on);
  });
  const lbl = document.getElementById('rateLabel');
  if (lbl) {
    lbl.textContent = RATE_LABELS[n] || RATE_LABELS[0];
    lbl.classList.toggle('picked', n > 0 && !hovering);
  }
}
document.querySelectorAll('.star-rating i').forEach(star => {
  star.addEventListener('mouseenter', () => paintStars(+star.dataset.val, true));
  star.addEventListener('mouseleave', () => paintStars(selectedRating, false));
  star.addEventListener('click', () => {
    selectedRating = +star.dataset.val;
    document.getElementById('ratingValue').value = selectedRating;
    paintStars(selectedRating, false);
    star.classList.add('pop');
    setTimeout(() => star.classList.remove('pop'), 260);
  });
});
if (document.querySelector('.star-rating i')) paintStars(0, false);

document.getElementById('reviewForm')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const rating = document.getElementById('ratingValue').value;
  const comment = document.getElementById('reviewComment').value.trim();
  if (!rating || rating === '0') return showToast('Please select a star rating.', 'danger');
  const res = await apiFetch('/api/feedback', { method: 'POST', body: JSON.stringify({ rating: +rating, comment }) });
  const data = await res.json();
  if (data.success) {
    showToast(data.message, 'success');
    selectedRating = 0;
    document.getElementById('ratingValue').value = 0;
    document.getElementById('reviewComment').value = '';
    paintStars(0, false);
  } else showToast(data.error || 'Failed', 'danger');
});

// ===== CHAT SIDEBAR =====
let activeChatRoomId = null;
let chatPollInterval = null;
let chatLastMsgId = 0;
let _chatRooms = [];

document.getElementById('chatToggle')?.addEventListener('click', () => {
  const panel = document.getElementById('chatPanel');
  const win = document.getElementById('chatWindow');
  if (win && win.style.display !== 'none') {          // a conversation is open: the bubble closes everything
    win.style.display = 'none';
    if (chatPollInterval) clearInterval(chatPollInterval);
    panel.style.display = 'none';
    return;
  }
  panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
  if (panel.style.display === 'block') loadChatRooms();
});

document.getElementById('chatBackBtn')?.addEventListener('click', () => {  // conversation -> list
  document.getElementById('chatWindow').style.display = 'none';
  if (chatPollInterval) clearInterval(chatPollInterval);
  const panel = document.getElementById('chatPanel');
  panel.style.display = 'block';
  loadChatRooms();
});

document.getElementById('closeChatPanel')?.addEventListener('click', () => {
  document.getElementById('chatPanel').style.display = 'none';
});

document.getElementById('closeChatWindow')?.addEventListener('click', () => {
  document.getElementById('chatWindow').style.display = 'none';
  if (chatPollInterval) clearInterval(chatPollInterval);
});

document.getElementById('chatSearch')?.addEventListener('input', (e) => renderChatRooms(e.target.value.trim().toLowerCase()));

function renderChatRooms(filter = '') {
  const list = document.getElementById('chatRoomsList');
  if (!list) return;
  list.innerHTML = '';
  const rooms = _chatRooms.filter(r => !filter || (r.other_user.username || '').toLowerCase().includes(filter));
  if (!rooms.length) {
    list.innerHTML = '<div class="chat-loading">No conversations yet.</div>';
    return;
  }
  rooms.forEach(room => {
    const item = document.createElement('div');
    item.className = 'chat-room-item';
    const avatar = document.createElement('div'); avatar.className = 'chat-room-avatar';
    if (room.other_user.photo_url) {
      const img = document.createElement('img'); img.src = room.other_user.photo_url;
      img.style.cssText = 'width:38px;height:38px;border-radius:50%;object-fit:cover'; avatar.appendChild(img);
    } else avatar.innerHTML = '<i class="fa-solid fa-circle-user"></i>';
    const info = document.createElement('div'); info.className = 'chat-room-info';
    const name = document.createElement('strong'); name.textContent = room.other_user.username;
    const last = document.createElement('span');
    last.textContent = room.last_message ? (room.last_message.message || 'Sent a file') : 'Start chatting';
    info.append(name, last);
    item.append(avatar, info);
    if (room.unread_count > 0) {
      const b = document.createElement('span'); b.className = 'badge'; b.textContent = room.unread_count; item.appendChild(b);
    }
    item.onclick = () => openChatWindow(room.room_id, room.other_user.username);
    list.appendChild(item);
  });
}

async function loadChatRooms() {
  if (!IS_LOGGED_IN) return;
  const _crl = document.getElementById('chatRoomsList');
  if (_crl && !_crl.dataset.loaded) { skeletonListRows(_crl, 3); _crl.dataset.loaded = '1'; }
  const res = await apiFetch('/api/rooms');
  const data = await res.json();
  _chatRooms = data.rooms || [];
  renderChatRooms(document.getElementById('chatSearch')?.value.trim().toLowerCase() || '');
}

function openChatWindow(roomId, username) {
  activeChatRoomId = roomId;
  chatLastMsgId = 0;
  document.getElementById('chatWindowTitle').textContent = username;
  const win = document.getElementById('chatWindow');
  win.style.display = 'flex';
  document.getElementById('chatMessages').innerHTML = '';
  document.getElementById('chatPanel').style.display = 'none';
  fetchChatMessages();
  if (chatPollInterval) clearInterval(chatPollInterval);
  chatPollInterval = setInterval(fetchChatMessages, 3000);
}

function renderMessageBubble(m) {
  const div = document.createElement('div');
  div.className = `msg-bubble ${m.sender_id === CURRENT_USER_ID ? 'sent' : 'received'}`;
  if (m.message_type === 'image' && m.file_url) {
    const img = document.createElement('img'); img.src = m.file_url; img.style.cssText = 'max-width:180px;border-radius:8px'; div.appendChild(img);
  } else if ((m.message_type === 'file' || m.message_type === 'video') && m.file_url) {
    const a = document.createElement('a'); a.href = m.file_url; a.target = '_blank'; a.rel = 'noopener';
    a.textContent = m.message_type === 'video' ? '▶ Video' : '📄 File'; div.appendChild(a);
  }
  if (m.message) {
    const span = document.createElement('span'); span.textContent = m.message; div.appendChild(span);
  }
  return div;
}

async function fetchChatMessages() {
  if (!activeChatRoomId) return;
  const res = await apiFetch(`/api/messages/${activeChatRoomId}?since_id=${chatLastMsgId}`);
  const data = await res.json();
  if (!data.messages?.length) return;
  const container = document.getElementById('chatMessages');
  data.messages.forEach(m => {
    container.appendChild(renderMessageBubble(m));
    chatLastMsgId = Math.max(chatLastMsgId, m.id);
  });
  container.scrollTop = container.scrollHeight;
}

document.getElementById('chatSendBtn')?.addEventListener('click', sendChatMessage);
document.getElementById('chatInput')?.addEventListener('keydown', e => { if (e.key === 'Enter') sendChatMessage(); });
document.getElementById('chatFileInput')?.addEventListener('change', async (e) => {
  const file = e.target.files[0];
  if (!file || !activeChatRoomId) return;
  const fd = new FormData();
  fd.append('file', file);
  fd.append('message', document.getElementById('chatInput').value.trim());
  const res = await fetch(`/api/messages/${activeChatRoomId}`, { method: 'POST', headers: { 'X-CSRFToken': CSRF_TOKEN }, body: fd });
  const data = await res.json();
  e.target.value = '';
  if (data.success) { document.getElementById('chatInput').value = ''; fetchChatMessages(); }
  else showToast(data.error || 'Upload failed', 'danger');
});

async function sendChatMessage() {
  const input = document.getElementById('chatInput');
  const msg = input.value.trim();
  if (!msg || !activeChatRoomId) return;
  input.value = '';
  await apiFetch(`/api/messages/${activeChatRoomId}`, { method: 'POST', body: JSON.stringify({ message: msg }) });
  fetchChatMessages();
}

// ===== UNREAD POLLING =====
async function pollUnread() {
  if (!IS_LOGGED_IN) return;
  try {
    const res = await apiFetch('/api/unread-count');
    const data = await res.json();
    const msgBadge = document.getElementById('unreadBadge');
    const chatBadge = document.getElementById('chatBadge');
    const pending = data.pending_connections || [];
    const total = (data.unread_messages || 0) + pending.length + (data.unread_notifications || 0);
    const chatTotal = (data.unread_messages || 0);
    if (msgBadge) { msgBadge.textContent = total; msgBadge.style.display = total > 0 ? 'flex' : 'none'; }
    if (chatBadge) { chatBadge.textContent = chatTotal; chatBadge.style.display = chatTotal > 0 ? 'flex' : 'none'; }

    pending.forEach(c => {
      const key = `conn_notified_${c.id}`;
      if (sessionStorage.getItem(key)) return;
      sessionStorage.setItem(key, '1');
      const container = document.getElementById('toastContainer');
      if (!container) return;
      const toast = document.createElement('div');
      toast.className = 'toast toast-info conn-request-toast';
      const text = document.createElement('div');
      const who = document.createElement('strong'); who.textContent = c.requester;
      text.appendChild(who);
      text.appendChild(document.createTextNode(' wants to connect on your trip '));
      const route = document.createElement('em'); route.textContent = `${c.trip_from} → ${c.trip_to}`;
      text.appendChild(route);
      const actions = document.createElement('div');
      actions.style.cssText = 'display:flex;gap:8px;margin-top:8px;';
      const respond = document.createElement('button');
      respond.className = 'btn btn-primary'; respond.style.cssText = 'padding:5px 12px;font-size:12px;'; respond.textContent = 'Respond';
      respond.onclick = () => { openRespondModal(c.id, `${c.requester} wants to connect on your trip from ${c.trip_from} to ${c.trip_to}.`); toast.remove(); };
      const close = document.createElement('button');
      close.style.cssText = 'background:none;border:none;cursor:pointer;font-size:18px;color:var(--muted);'; close.innerHTML = '&times;';
      close.onclick = () => toast.remove();
      actions.append(respond, close);
      toast.append(text, actions);
      container.appendChild(toast);
    });
  } catch (e) {}
}

// ===== INIT =====
loadResults();
if (IS_LOGGED_IN) {
  loadMyTrips();
  pollUnread();
  setInterval(pollUnread, 15000);
}

document.querySelectorAll('.toast').forEach(t => setTimeout(() => t.remove(), 5000));

// ===== AIRPORT AUTOCOMPLETE =====
function initAirportAutocomplete(input) {
  const wrapper = input.closest('.input-with-icon') || input.parentElement;
  wrapper.style.position = 'relative';

  const dropdown = document.createElement('div');
  dropdown.className = 'airport-dropdown';
  wrapper.appendChild(dropdown);

  let debounce = null;
  let activeIdx = -1;
  let options = [];

  function close() {
    dropdown.classList.remove('open');
    activeIdx = -1;
  }

  function renderOptions(airports) {
    options = airports;
    activeIdx = -1;
    dropdown.innerHTML = '';
    if (!airports.length) { close(); return; }
    airports.forEach((a) => {
      const div = document.createElement('div');
      div.className = 'airport-option';
      div.innerHTML = `<span class="airport-iata">${esc(a.iata)}</span><span><strong>${esc(a.city || a.name)}</strong> <span class="airport-detail">${esc(a.name)} · ${esc(a.country)}</span></span>`;
      div.addEventListener('mousedown', (e) => {
        e.preventDefault();
        input.value = `${a.city || a.name} (${a.iata})`;
        input.dispatchEvent(new Event('change', { bubbles: true }));
        close();
      });
      dropdown.appendChild(div);
    });
    dropdown.classList.add('open');
  }

  function setActive(idx) {
    const items = dropdown.querySelectorAll('.airport-option');
    items.forEach(el => el.classList.remove('active'));
    activeIdx = Math.max(-1, Math.min(idx, items.length - 1));
    if (activeIdx >= 0) items[activeIdx].classList.add('active');
  }

  input.addEventListener('input', () => {
    clearTimeout(debounce);
    const q = input.value.trim();
    if (q.length < 2) { close(); return; }
    debounce = setTimeout(() => {
      fetch(`/api/airports?q=${encodeURIComponent(q)}`)
        .then(r => r.json())
        .then(renderOptions);
    }, 250);
  });

  input.addEventListener('keydown', (e) => {
    if (!dropdown.classList.contains('open')) return;
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive(activeIdx + 1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(activeIdx - 1); }
    else if (e.key === 'Enter' && activeIdx >= 0) {
      e.preventDefault();
      const a = options[activeIdx];
      input.value = `${a.city || a.name} (${a.iata})`;
      input.dispatchEvent(new Event('change', { bubbles: true }));
      close();
    } else if (e.key === 'Escape') { close(); }
  });

  document.addEventListener('click', (e) => {
    if (!wrapper.contains(e.target)) close();
  });
}

document.querySelectorAll('.autocomplete-airport').forEach(initAirportAutocomplete);

function wireAirportAutocomplete(nodes) { nodes.forEach(initAirportAutocomplete); }
function wireAirlineAutocomplete(nodes) { nodes.forEach(initAirlineAutocomplete); }

// ===== AIRLINE AUTOCOMPLETE =====
function initAirlineAutocomplete(input) {
  const wrapper = input.closest('.input-with-icon') || input.parentElement;
  wrapper.style.position = 'relative';

  const dropdown = document.createElement('div');
  dropdown.className = 'airport-dropdown';
  wrapper.appendChild(dropdown);

  let debounce = null;
  let activeIdx = -1;
  let options = [];

  function close() { dropdown.classList.remove('open'); activeIdx = -1; }

  function renderOptions(airlines) {
    options = airlines;
    activeIdx = -1;
    dropdown.innerHTML = '';
    if (!airlines.length) { close(); return; }
    airlines.forEach((a) => {
      const div = document.createElement('div');
      div.className = 'airport-option';
      div.innerHTML = `<span class="airport-iata">${esc(a.iata)}</span><span><strong>${esc(a.name)}</strong> <span class="airport-detail">${esc(a.country)}</span></span>`;
      div.addEventListener('mousedown', (e) => {
        e.preventDefault();
        input.value = a.name;
        close();
      });
      dropdown.appendChild(div);
    });
    dropdown.classList.add('open');
  }

  function setActive(idx) {
    const items = dropdown.querySelectorAll('.airport-option');
    items.forEach(el => el.classList.remove('active'));
    activeIdx = Math.max(-1, Math.min(idx, items.length - 1));
    if (activeIdx >= 0) items[activeIdx].classList.add('active');
  }

  input.addEventListener('input', () => {
    clearTimeout(debounce);
    const q = input.value.trim();
    if (q.length < 2) { close(); return; }
    debounce = setTimeout(() => {
      fetch(`/api/airlines?q=${encodeURIComponent(q)}`)
        .then(r => r.json())
        .then(renderOptions);
    }, 250);
  });

  input.addEventListener('keydown', (e) => {
    if (!dropdown.classList.contains('open')) return;
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive(activeIdx + 1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(activeIdx - 1); }
    else if (e.key === 'Enter' && activeIdx >= 0) {
      e.preventDefault();
      input.value = options[activeIdx].name;
      close();
    } else if (e.key === 'Escape') { close(); }
  });

  document.addEventListener('click', (e) => { if (!wrapper.contains(e.target)) close(); });
}

document.querySelectorAll('.autocomplete-airline').forEach(initAirlineAutocomplete);


/* ===== GLOBAL CUSTOM CALENDAR =====
   Every native date input across the site opens this custom popup instead of the browser
   picker (typing is disabled; the ISO value is still submitted through the same input,
   and 'input'/'change' events fire so existing listeners keep working). */
const MCAL_MONTHS = ['January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December'];

function mcalClose() { document.querySelectorAll('.mcal-pop').forEach(el => el.remove()); }

function mcalOpen(input) {
  mcalClose();
  const pop = document.createElement('div');
  pop.className = 'mcal-pop';
  document.body.appendChild(pop);
  const pad = n => String(n).padStart(2, '0');
  let base = input.value ? new Date(input.value + 'T00:00:00') : new Date();
  if (isNaN(base.getTime())) base = new Date();
  base.setDate(1);
  const minIso = input.min || '';
  const maxIso = input.max || '';
  const thisYear = new Date().getFullYear();
  const yearFrom = minIso ? +minIso.slice(0, 4) : 1935;   // DOB pickers need to reach far back
  const yearTo = maxIso ? +maxIso.slice(0, 4) : thisYear + 3;

  function draw() {
    const y = base.getFullYear(), mo = base.getMonth();
    pop.innerHTML = '';
    const head = document.createElement('div'); head.className = 'mc2-head';
    const prev = document.createElement('button'); prev.type = 'button'; prev.innerHTML = '&lsaquo;'; prev.setAttribute('aria-label', 'Previous month');
    const next = document.createElement('button'); next.type = 'button'; next.innerHTML = '&rsaquo;'; next.setAttribute('aria-label', 'Next month');
    prev.onclick = e => { e.stopPropagation(); base = new Date(y, mo - 1, 1); draw(); };
    next.onclick = e => { e.stopPropagation(); base = new Date(y, mo + 1, 1); draw(); };
    const mSel = document.createElement('select'); mSel.className = 'mc2-sel'; mSel.setAttribute('data-no-search', '');
    MCAL_MONTHS.forEach((mn, i) => { const o = document.createElement('option'); o.value = i; o.textContent = mn; if (i === mo) o.selected = true; mSel.appendChild(o); });
    mSel.onchange = () => { base = new Date(base.getFullYear(), +mSel.value, 1); draw(); };
    const ySel = document.createElement('select'); ySel.className = 'mc2-sel'; ySel.setAttribute('data-no-search', ''); ySel.style.flex = '0 0 76px';
    for (let yy = yearFrom; yy <= yearTo; yy++) { const o = document.createElement('option'); o.value = yy; o.textContent = yy; if (yy === y) o.selected = true; ySel.appendChild(o); }
    ySel.onchange = () => { base = new Date(+ySel.value, base.getMonth(), 1); draw(); };
    head.appendChild(prev); head.appendChild(mSel); head.appendChild(ySel); head.appendChild(next);
    pop.appendChild(head);
    const g = document.createElement('div'); g.className = 'mc2-grid';
    ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'].forEach(d => { const sp = document.createElement('span'); sp.className = 'mc2-dow'; sp.textContent = d; g.appendChild(sp); });
    for (let i = 0; i < new Date(y, mo, 1).getDay(); i++) g.appendChild(document.createElement('span'));
    const days = new Date(y, mo + 1, 0).getDate();
    const t = new Date();
    const todayIso = `${t.getFullYear()}-${pad(t.getMonth() + 1)}-${pad(t.getDate())}`;
    for (let d = 1; d <= days; d++) {
      const iso = `${y}-${pad(mo + 1)}-${pad(d)}`;
      const b = document.createElement('button'); b.type = 'button'; b.className = 'mc2-day'; b.textContent = d;
      if ((minIso && iso < minIso) || (maxIso && iso > maxIso)) b.disabled = true;
      if (iso === todayIso) b.classList.add('today');
      if (iso === input.value) b.classList.add('sel');
      b.onclick = e => {
        e.stopPropagation();
        input.value = iso;
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
        mcalClose();
      };
      g.appendChild(b);
    }
    pop.appendChild(g);
  }
  draw();
  pop.addEventListener('mousedown', e => e.stopPropagation());
  // fixed positioning works inside modals and on scrolled pages; flip above when near the bottom
  const r = input.getBoundingClientRect();
  const W = 306, H = 342;
  pop.style.left = Math.max(8, Math.min(r.left, window.innerWidth - W - 8)) + 'px';
  pop.style.top = ((r.bottom + H + 12 > window.innerHeight && r.top - H - 8 > 0) ? r.top - H - 8 : r.bottom + 6) + 'px';
  setTimeout(() => {
    document.addEventListener('mousedown', mcalClose, { once: true });
    document.addEventListener('keydown', function esc(ev) {
      if (ev.key === 'Escape') { mcalClose(); document.removeEventListener('keydown', esc); }
    });
  }, 0);
  window.addEventListener('scroll', mcalClose, { once: true, capture: true });
}

document.addEventListener('mousedown', (e) => {
  const t = e.target;
  if (t && t.tagName === 'INPUT' && t.type === 'date' && !t.disabled && !t.readOnly) {
    e.preventDefault();                                   // suppress the native picker
    t.focus({ preventScroll: true });
    if (document.querySelector('.mcal-pop')) mcalClose(); else mcalOpen(t);
  }
}, true);
document.addEventListener('keydown', (e) => {
  const t = e.target;
  if (t && t.tagName === 'INPUT' && t.type === 'date' && !['Tab', 'Escape', 'Enter'].includes(e.key)) e.preventDefault();
}, true);
document.addEventListener('click', (e) => {
  const t = e.target;
  if (t && t.tagName === 'INPUT' && t.type === 'date') e.preventDefault();  // Chrome also opens the picker on click
}, true);


/* ===== TRIP DETAILS (the full story, one tap away) ==========================
 * The card carries the six things a scan needs; everything else lives here. One panel
 * element is reused, so only one can ever be open.
 *
 * Tap is the trigger that works for everyone -- phones have no hover -- and on a desktop
 * a deliberate rest of the pointer opens the same panel as a shortcut. Below the sheet
 * breakpoint the same content slides up as a bottom sheet instead.
 */
const TD = { panel: null, scrim: null, card: null, openTimer: null, closeTimer: null };

const tdSheetMode = () =>
  window.matchMedia('(max-width: 860px), (pointer: coarse)').matches;
const tdCanHover = () =>
  window.matchMedia('(hover: hover) and (pointer: fine)').matches;

function tdTypeLabel(trip) {
  return trip.trip_type === 'round_trip' ? 'Round trip'
       : trip.trip_type === 'multi_destination' ? 'Multi-stop' : 'One way';
}

function tdSentence(text) {
  const t = String(text || '').replace(/_/g, ' ').trim();
  return t ? t.charAt(0).toUpperCase() + t.slice(1) : '';
}

function tdFact(label, value) {
  if (!value) return '';
  return '<div class="td-fact"><small>' + esc(label) + '</small><strong>' + value + '</strong></div>';
}

function tdContent(trip, ownTrip) {
  const anon = trip.is_anonymous;
  const isMulti = trip.trip_type === 'multi_destination';
  let fromText = trip.flying_from, toText = trip.destination;
  if (isMulti && (trip.legs || []).length) {
    fromText = fromText || trip.legs[0].from;
    toText = toText || trip.legs[trip.legs.length - 1].to;
  }
  const fp = tcPort(fromText, trip.origin_iata);
  const tp = tcPort(toText, trip.dest_iata);
  const who = anon ? 'Anonymous traveller' : ((trip.author && trip.author.username) || trip.poster_name || 'Traveller');
  const byline = [who, (ROLE_LABELS[trip.role] || '').toLowerCase(), tdTypeLabel(trip).toLowerCase()]
    .filter(Boolean).join(' · ');

  const contacts = trip.contact_types || [];
  const reachable = contacts.length
    ? contacts.map(t => '<i class="' + (CONTACT_ICONS[t] || CONTACT_ICONS.other)
        + '" role="img" aria-label="' + esc(CONTACT_LABELS[t] || t) + '"></i>').join('')
      + '<span class="td-consent">after consent</span>'
    : '';

  const langs = (trip.preferred_languages || []).filter(Boolean);
  const needs = (trip.traveller_needs || []).filter(Boolean);
  const tags = (trip.connect_me_to || []).filter(Boolean);
  const needsTitle = trip.role === 'offering_help' ? 'Happy to help with' : 'Needs help with';

  const legsHtml = isMulti && (trip.legs || []).length
    ? '<div class="td-block"><h4>Every leg</h4><div class="td-legs">'
      + trip.legs.map((l, i) =>
          '<div class="td-leg"><span class="td-legn">' + (i + 1) + '</span>'
          + '<span class="td-legr">' + esc(l.from || '?') + ' → ' + esc(l.to || '?') + '</span>'
          + (l.date ? '<span class="td-legd">' + esc(l.date) + '</span>' : '')
          + (l.airline ? '<span class="td-lega">' + esc(l.airline)
              + (l.flight_number ? ' ' + esc(l.flight_number) : '') + '</span>' : '')
          + '</div>').join('')
      + '</div></div>'
    : '';

  const chips = (title, items, kind) => items.length
    ? '<div class="td-block"><h4>' + esc(title) + '</h4><div class="td-chips td-' + kind + '">'
      + items.map(x => '<span>' + esc(tdSentence(x)) + '</span>').join('') + '</div></div>'
    : '';

  // Per-person travellers — one companion is matched for the whole group, so each person's
  // own age, gender and the help they'd appreciate is shown here rather than collapsed.
  const travellers = anon ? [] : (trip.travellers || []).filter(t => t && t.who);
  const travellersHtml = travellers.length
    ? '<div class="td-block"><h4>' + (travellers.length > 1 ? "Who's travelling · " + travellers.length : "Who's travelling") + '</h4>'
      + '<div class="td-travellers">'
      + travellers.map(t => {
          const meta = [
            TC_AGE[t.age_group] || '',
            (t.gender && !['other', 'unspecified', 'prefer_not'].includes(t.gender))
              ? t.gender.charAt(0).toUpperCase() + t.gender.slice(1) : '',
          ].filter(Boolean).join(' · ');
          const tneeds = (t.needs || []).filter(Boolean).map(tcNeedLabel);
          return '<div class="td-trav">'
            + '<div class="td-trav-h"><i class="fa-solid fa-user"></i> <strong>' + esc(tdSentence(t.who)) + '</strong>'
            + (meta ? '<span class="td-trav-meta">' + esc(meta) + '</span>' : '') + '</div>'
            + (tneeds.length ? '<div class="td-trav-needs">'
                + tneeds.map(n => '<span>' + esc(n) + '</span>').join('') + '</div>' : '')
            + '</div>';
        }).join('')
      + '</div></div>'
    : '';
  // The trip-level needs chips only add value when there is no per-person breakdown, or when
  // the poster is the one offering help (then "needs" means what they can help with).
  const showTripNeeds = !travellers.length || trip.role === 'offering_help';

  const note = anon ? '' : [trip.special_needs_notes, trip.additional_comments].filter(Boolean).join('\n\n');

  return '' +
    '<button type="button" class="td-close" aria-label="Close">&times;</button>' +
    '<div class="td-head">' +
      '<h3>' + esc(fp.city) + ' <span>→</span> ' + esc(tp.city) + '</h3>' +
      '<p class="td-by">' + esc(byline) + '</p>' +
    '</div>' +
    '<div class="td-facts">' +
      tdFact('Trip', esc(tdTypeLabel(trip)) + (trip.category ? ' · ' + esc(trip.category) : '')) +
      tdFact('Ticket', trip.ticket_booked ? 'Booked ✓' : 'Not booked yet') +
      (travellers.length ? '' : tdFact('Travelling for', anon ? '' : esc(tdSentence(trip.on_behalf_of)))) +
      tdFact('Reachable via', reachable) +
    '</div>' +
    travellersHtml +
    legsHtml +
    chips('Languages', langs, 'lang') +
    (showTripNeeds ? chips(needsTitle, needs, 'need') : '') +
    chips('Happy to connect about', tags, 'lang') +
    (note ? '<div class="td-block"><h4>Their note</h4><blockquote class="td-note">'
            + esc(note) + '</blockquote></div>' : '') +
    '<div class="td-actions"></div>';
}

function tdBuildActions(box, trip, ownTrip) {
  box.innerHTML = '';
  if (ownTrip) {
    const mod = document.createElement('button');
    mod.className = 'btn btn-primary td-btn';
    mod.innerHTML = '<i class="fa-solid fa-pen-to-square"></i> Modify';
    mod.onclick = () => { closeTripDetails(); modifyTrip(trip.id); };
    const cls = document.createElement('button');
    cls.className = 'btn btn-outline-danger td-btn';
    cls.textContent = 'Close trip';
    cls.onclick = () => { closeTripDetails(); disableTrip(trip.id); };
    box.append(mod, cls);
    return;
  }
  const connect = document.createElement('button');
  connect.className = 'btn td-cta td-btn';
  connect.innerHTML = '<i class="fa-solid fa-handshake"></i> Connect';
  connect.onclick = () => {
    closeTripDetails();
    if (IS_LOGGED_IN) openConnectModal(trip.id, (trip.author && trip.author.username) || 'this traveller');
    else window.location = '/auth/register';
  };
  box.appendChild(connect);
}

function tdEnsurePanel() {
  if (TD.panel) return TD.panel;
  const scrim = document.createElement('div');
  scrim.className = 'td-scrim';
  scrim.hidden = true;
  scrim.addEventListener('click', closeTripDetails);

  const panel = document.createElement('div');
  panel.className = 'td-panel';
  panel.hidden = true;
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-modal', 'false');
  panel.innerHTML = '<span class="td-arrow"></span><div class="td-grip"></div><div class="td-body"></div>';
  // clicks inside must not reach the document handler that closes the panel
  panel.addEventListener('click', e => e.stopPropagation());
  panel.addEventListener('mouseenter', () => clearTimeout(TD.closeTimer));
  panel.addEventListener('mouseleave', () => {
    if (tdCanHover() && !TD.pinned) TD.closeTimer = setTimeout(closeTripDetails, 220);
  });
  document.body.append(scrim, panel);
  TD.panel = panel; TD.scrim = scrim;
  return panel;
}

function tdPlace() {
  /* Beside the card, never on top of it; flips to the other side near the screen edge.
     The arrow tracks the card's middle so the panel always points back at its source. */
  const panel = TD.panel, card = TD.card;
  if (!panel || !card || panel.hidden) return;
  if (tdSheetMode()) { panel.style.cssText = ''; return; }
  const r = card.getBoundingClientRect();
  const gap = 14, edge = 12;
  const w = panel.offsetWidth, h = panel.offsetHeight;
  let left = r.right + gap, side = 'left';          // arrow on the panel's left edge
  if (left + w > window.innerWidth - edge) {
    left = r.left - w - gap; side = 'right';
    if (left < edge) {                              // no room either side: sit over the gutter
      left = Math.max(edge, Math.min(r.left, window.innerWidth - w - edge));
      side = 'none';
    }
  }
  const top = Math.max(edge, Math.min(r.top, window.innerHeight - h - edge));
  panel.style.left = left + 'px';
  panel.style.top = top + 'px';
  panel.dataset.side = side;
  const arrow = panel.querySelector('.td-arrow');
  const mid = r.top + r.height / 2 - top;
  arrow.style.top = Math.max(18, Math.min(mid, h - 18)) + 'px';
}

function openTripDetails(card, trip, ownTrip) {
  // Cards are also rendered inside the matches panel, where a popup on top of a modal
  // would be a second layer fighting the first.
  if (card.closest('.modal-overlay')) return;
  clearTimeout(TD.openTimer); clearTimeout(TD.closeTimer);
  const panel = tdEnsurePanel();
  if (TD.card && TD.card !== card) TD.card.classList.remove('is-detailed');
  TD.card = card;
  TD.pinned = true;                       // opened deliberately: a stray mouse-out keeps it
  card.classList.add('is-detailed');

  panel.querySelector('.td-body').innerHTML = tdContent(trip, ownTrip);
  tdBuildActions(panel.querySelector('.td-actions'), trip, ownTrip);
  panel.querySelector('.td-close').onclick = closeTripDetails;

  const sheet = tdSheetMode();
  panel.classList.toggle('is-sheet', sheet);
  TD.scrim.hidden = !sheet;
  panel.hidden = false;
  panel.style.cssText = '';
  requestAnimationFrame(() => { tdPlace(); panel.classList.add('is-in'); });
}

function closeTripDetails() {
  clearTimeout(TD.openTimer); clearTimeout(TD.closeTimer);
  TD.pinned = false;
  if (TD.card) { TD.card.classList.remove('is-detailed'); TD.card = null; }
  if (!TD.panel) return;
  TD.panel.classList.remove('is-in');
  TD.panel.hidden = true;
  TD.scrim.hidden = true;
}

function tdHoverIntent(card, trip, ownTrip) {
  /* The pause is the whole point: crossing the grid with the mouse opens nothing, only a
     deliberate rest does. Touch devices never reach any of this. */
  card.addEventListener('mouseenter', () => {
    if (!tdCanHover() || card.closest('.modal-overlay')) return;
    clearTimeout(TD.openTimer); clearTimeout(TD.closeTimer);
    TD.openTimer = setTimeout(() => {
      openTripDetails(card, trip, ownTrip);
      TD.pinned = false;                  // hover-opened: leaving both card and panel closes it
    }, 300);
  });
  card.addEventListener('mouseleave', () => {
    clearTimeout(TD.openTimer);
    if (tdCanHover() && !TD.pinned && TD.card === card) {
      TD.closeTimer = setTimeout(closeTripDetails, 220);
    }
  });
}

document.addEventListener('click', e => {
  if (TD.card && !e.target.closest('.td-panel') && !e.target.closest('.trip-card')) closeTripDetails();
});
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeTripDetails(); });
window.addEventListener('resize', () => { if (TD.card) tdPlace(); });
window.addEventListener('scroll', () => { if (TD.card && !tdSheetMode()) tdPlace(); }, true);


/* ===== staff sidebar: open / collapsed ======================================
 * Admin and CS share the shell, so one toggle serves both. The choice is per browser
 * and survives navigation -- an agent who works in the rail should not have to collapse
 * it again on every screen.
 */
(function () {
  const page = document.querySelector('.admin-page');
  const btn = document.querySelector('[data-rail-toggle]');
  if (!page || !btn) return;
  const KEY = 'cd.staffRail';

  function paint(collapsed) {
    page.classList.toggle('is-rail', collapsed);
    btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    const label = collapsed ? 'Expand the menu' : 'Collapse the menu';
    btn.setAttribute('aria-label', label);
    btn.setAttribute('title', label);
  }

  let saved = null;
  try { saved = localStorage.getItem(KEY); } catch (e) { /* private mode: just don't remember */ }
  paint(saved === '1');

  btn.addEventListener('click', () => {
    const collapsed = !page.classList.contains('is-rail');
    paint(collapsed);
    try { localStorage.setItem(KEY, collapsed ? '1' : '0'); } catch (e) { /* nothing to do */ }
  });
})();


/* ===== live search for the CS list screens ==================================
 * Results update as you type. The form still works without JavaScript -- it is a plain
 * GET form -- but with JS the page never reloads: we fetch the same URL with partial=1,
 * which returns the results fragment, and swap it in.
 *
 * Details that make it feel right rather than merely work:
 *   - a short debounce, so a query runs once you pause, not on every keystroke
 *   - each request carries a sequence number; a slow earlier response is dropped instead
 *     of overwriting a newer one
 *   - the address bar keeps up, so the view can be reloaded, bookmarked or shared
 *   - Enter still searches immediately, and Escape clears
 */
function liveSearch({ form, input, clear, spinner, results, delay = 250 }) {
  const f = document.getElementById(form);
  const box = document.getElementById(input);
  const wipe = document.getElementById(clear);
  const spin = document.getElementById(spinner);
  const out = document.getElementById(results);
  if (!f || !box || !out) return;

  let timer = null;
  let seq = 0;

  const params = () => {
    const p = new URLSearchParams(new FormData(f));
    for (const [k, v] of [...p]) if (!v) p.delete(k);   // keep the URL readable
    return p;
  };

  async function run(push = true) {
    const mine = ++seq;
    const p = params();
    if (spin) spin.hidden = false;
    out.setAttribute('aria-busy', 'true');
    try {
      // form.action resolves to the *current* URL when the attribute is absent, query
      // string and all -- reusing it would carry the previous search into the next one,
      // so a cleared box would keep returning the old results.
      const base = (f.getAttribute('action') || location.pathname).split('?')[0];
      const qs = p.toString();
      const res = await fetch(`${base}?${qs}${qs ? '&' : ''}partial=1`,
                              { headers: { 'X-Requested-With': 'fetch' } });
      const html = await res.text();
      if (mine !== seq) return;                        // a newer search already answered
      out.innerHTML = html;
      if (push) history.replaceState(null, '', p.toString() ? `?${p}` : location.pathname);
    } catch (e) {
      if (mine === seq) out.innerHTML = '<p class="muted">Could not load results — try again.</p>';
    } finally {
      if (mine === seq && spin) spin.hidden = true;
      out.removeAttribute('aria-busy');
    }
  }

  function toggleClear() { if (wipe) wipe.hidden = !box.value; }

  box.addEventListener('input', () => {
    toggleClear();
    clearTimeout(timer);
    timer = setTimeout(run, delay);
  });
  box.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); clearTimeout(timer); run(); }
    if (e.key === 'Escape' && box.value) { box.value = ''; toggleClear(); clearTimeout(timer); run(); }
  });
  f.addEventListener('submit', e => { e.preventDefault(); clearTimeout(timer); run(); });
  f.querySelectorAll('select').forEach(s => s.addEventListener('change', () => { clearTimeout(timer); run(); }));
  if (wipe) wipe.addEventListener('click', () => { box.value = ''; toggleClear(); box.focus(); run(); });

  // paging inside the swapped-in fragment stays on the page too
  out.addEventListener('click', e => {
    const a = e.target.closest('.pagination a');
    if (!a) return;
    e.preventDefault();
    const p = new URLSearchParams(a.search);
    const page = p.get('page');
    let hidden = f.querySelector('input[name="page"]');
    if (!hidden) {
      hidden = document.createElement('input');
      hidden.type = 'hidden'; hidden.name = 'page';
      f.appendChild(hidden);
    }
    hidden.value = page || '1';
    run();
    out.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });

  // a fresh keystroke always starts from page one
  box.addEventListener('input', () => {
    const hidden = f.querySelector('input[name="page"]');
    if (hidden) hidden.value = '1';
  });

  toggleClear();
}
