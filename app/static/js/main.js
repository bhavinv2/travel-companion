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

// Auth modal
document.getElementById('authModalBtn')?.addEventListener('click', () => {
  document.getElementById('authModal').classList.add('open');
});
document.getElementById('closeAuthModal')?.addEventListener('click', () => {
  document.getElementById('authModal').classList.remove('open');
});
document.getElementById('authModal')?.addEventListener('click', (e) => {
  if (e.target === e.currentTarget) e.currentTarget.classList.remove('open');
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

// ===== TESTIMONIAL CAROUSEL =====
const tCards = document.querySelectorAll('.testimonial-card');
let tIdx = 0;
const tDotsEl = document.getElementById('tDots');

if (tCards.length > 0 && tDotsEl) {
  tCards.forEach((_, i) => {
    const dot = document.createElement('span');
    dot.className = i === 0 ? 'active' : '';
    dot.onclick = () => goToTestimonial(i);
    tDotsEl.appendChild(dot);
  });

  function goToTestimonial(idx) {
    tCards.forEach(c => c.classList.remove('active'));
    tDotsEl.querySelectorAll('span').forEach(d => d.classList.remove('active'));
    tIdx = idx;
    tCards[tIdx]?.classList.add('active');
    tDotsEl.querySelectorAll('span')[tIdx]?.classList.add('active');
  }
  setInterval(() => goToTestimonial((tIdx + 1) % tCards.length), 4500);
}

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
document.querySelectorAll('.multi-select-btn').forEach(btn => {
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    const targetId = btn.dataset.target;
    const dropdown = document.getElementById(targetId);
    document.querySelectorAll('.multi-dropdown').forEach(d => { if (d.id !== targetId) d.classList.remove('open'); });
    dropdown?.classList.toggle('open');
  });
});

document.addEventListener('click', () => {
  document.querySelectorAll('.multi-dropdown').forEach(d => d.classList.remove('open'));
});

function updateMultiLabel(dropdownId, labelId) {
  const dropdown = document.getElementById(dropdownId);
  const label = document.getElementById(labelId);
  if (!dropdown || !label) return;
  const checked = dropdown.querySelectorAll('input:checked');
  label.textContent = checked.length === 0 ? label.dataset.placeholder || 'Select...' : Array.from(checked).map(c => c.parentElement.textContent.trim()).join(', ');
}

[['connectTo', 'connectToLabel'], ['travellerNeeds', 'travellerNeedsLabel'], ['langSelect', 'langSelectLabel'], ['langSelectMulti', 'langSelectMultiLabel']].forEach(([dd, lbl]) => {
  document.getElementById(dd)?.querySelectorAll('input').forEach(cb => {
    cb.addEventListener('change', () => updateMultiLabel(dd, lbl));
  });
});

// ===== RESULTS CAROUSEL =====
const CAROUSEL_PAGE_SIZE = 4;
let _carouselTrips = [];
let _carouselPage = 0;

async function loadResults() {
  const grid = document.getElementById('resultsGrid');
  const countEl = document.getElementById('resultsCount');
  if (!grid) return;
  grid.innerHTML = '<div class="loading-spinner"><i class="fa-solid fa-spinner fa-spin"></i> Loading trips...</div>';

  const form = document.getElementById('searchForm');
  const formData = {};
  if (form) {
    new FormData(form).forEach((v, k) => { if (!k.startsWith('contact_')) formData[k] = v; });
  }
  formData.travel_type = 'air';
  formData.limit = 20;

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
  if (prevBtn) prevBtn.style.display = totalPages > 1 ? '' : 'none';
  if (nextBtn) nextBtn.style.display = totalPages > 1 ? '' : 'none';

  if (dotsEl) {
    dotsEl.innerHTML = '';
    for (let i = 0; i < totalPages; i++) {
      const dot = document.createElement('span');
      dot.className = 'carousel-dot' + (i === _carouselPage ? ' active' : '');
      dot.onclick = () => { _carouselPage = i; renderCarouselPage(); };
      dotsEl.appendChild(dot);
    }
  }
}

function carouselNav(dir) {
  const totalPages = Math.ceil(_carouselTrips.length / CAROUSEL_PAGE_SIZE);
  _carouselPage = (_carouselPage + dir + totalPages) % totalPages;
  renderCarouselPage();
}

// ===== TRIP CARD (all user-supplied strings are escaped) =====
function buildTripCard(trip, isOwn = false) {
  const card = document.createElement('div');
  card.className = 'trip-card';
  card.dataset.tripId = trip.id;

  const ownTrip = isOwn || !!trip.is_own;
  const anon = trip.is_anonymous;
  const isMulti = trip.trip_type === 'multi_destination';
  const from = esc(trip.flying_from || '?');
  const to = esc(trip.destination || '?');
  const fromDate = esc(trip.from_date || '');
  const toDate = esc(trip.to_date || '');
  const tags = [...(trip.connect_me_to || []), ...(trip.traveller_needs || [])].slice(0, 4);
  const langs = (trip.preferred_languages || []).map(esc).join(', ');
  const roleBadge = trip.role ? `<span class="trip-role-badge chip-role-${esc(trip.role)}">${esc(ROLE_LABELS[trip.role] || trip.role)}</span>` : '';
  const contactTypes = trip.contact_types || [];
  const contactIcons = contactTypes.length
    ? `<span class="trip-contact-icons" title="Reachable via ${esc(contactTypes.map(t => CONTACT_LABELS[t] || t).join(', '))}">${contactTypes.map(t => `<i class="${CONTACT_ICONS[t] || CONTACT_ICONS.other}"></i>`).join('')}</span>`
    : '';

  let legsHtml = '';
  if (isMulti && (trip.legs || []).length) {
    legsHtml = `<div class="trip-legs">${trip.legs.map((l, i) =>
      `<div class="trip-leg-row"><span class="leg-dot">${i + 1}</span><span>${esc(l.from)} → ${esc(l.to)}</span>${l.date ? `<span class="leg-date">${esc(l.date)}</span>` : ''}${l.airline ? `<span class="leg-airline">${esc(l.airline)}${l.flight_number ? ' ' + esc(l.flight_number) : ''}</span>` : ''}</div>`
    ).join('')}</div>`;
  }

  const detailsHtml = anon ? '' : `
      ${!isMulti && trip.airline ? `<div class="trip-detail-row"><i class="fa-solid fa-plane"></i> ${esc(trip.airline)}${trip.flight_number ? ' ' + esc(trip.flight_number) : ''}</div>` : ''}
      ${!isMulti && fromDate ? `<div class="trip-detail-row"><i class="fa-solid fa-calendar"></i> ${fromDate}${toDate ? ' → ' + toDate : ''}${trip.from_date_flexible ? ' <small>(flexible)</small>' : ''}</div>` : ''}
      ${trip.on_behalf_of ? `<div class="trip-detail-row"><i class="fa-solid fa-person"></i> On behalf of: ${esc(String(trip.on_behalf_of).replace(/_/g, ' '))}</div>` : ''}
      ${langs ? `<div class="trip-detail-row"><i class="fa-solid fa-language"></i> ${langs}</div>` : ''}
      ${trip.ticket_booked ? `<div class="trip-detail-row"><i class="fa-solid fa-ticket"></i> Ticket booked</div>` : ''}
      ${trip.special_needs_notes ? `<div class="trip-detail-row"><i class="fa-solid fa-heart-pulse"></i> ${esc(trip.special_needs_notes)}</div>` : ''}
      ${trip.additional_comments ? `<div class="trip-detail-row"><i class="fa-solid fa-comment"></i> ${esc(truncate(trip.additional_comments, 140))}</div>` : ''}`;

  const anonDatesHtml = anon && !isMulti && fromDate
    ? `<div class="trip-detail-row"><i class="fa-solid fa-calendar"></i> ${fromDate}${toDate ? ' → ' + toDate : ''}</div>` : '';

  const statusChip = ownTrip && trip.status && trip.status !== 'open'
    ? `<span class="chip chip-${esc(trip.status)}">${esc(trip.status)}</span>` : '';

  card.innerHTML = `
    <div class="trip-card-header">
      <div class="trip-route">${from} <span>→</span> ${to}</div>
      <span class="trip-type-badge">✈ ${trip.trip_type === 'round_trip' ? 'Round Trip' : trip.trip_type === 'multi_destination' ? 'Multi-Stop' : 'One Way'}</span>
    </div>
    <div class="trip-details">
      ${roleBadge ? `<div class="trip-detail-row">${roleBadge}${statusChip ? ' ' + statusChip : ''}</div>` : ''}
      ${isMulti ? legsHtml : (anon ? anonDatesHtml : detailsHtml)}
    </div>
    ${!anon && tags.length ? `<div class="trip-tags">${tags.map(t => `<span class="trip-tag">${esc(String(t).replace(/_/g, ' '))}</span>`).join('')}</div>` : ''}
    <div class="trip-card-footer"></div>`;

  const footer = card.querySelector('.trip-card-footer');
  const author = document.createElement('div');
  author.className = 'trip-author';
  if (anon) {
    author.innerHTML = '<i class="fa-solid fa-user-secret"></i>';
    const s = document.createElement('span'); s.textContent = 'Anonymous'; author.appendChild(s);
  } else {
    if (trip.author?.photo_url) {
      const img = document.createElement('img'); img.src = trip.author.photo_url; img.alt = trip.author.username || '';
      author.appendChild(img);
    } else {
      author.innerHTML = '<i class="fa-solid fa-circle-user"></i>';
    }
    const s = document.createElement('span'); s.textContent = trip.author?.username || 'Traveller'; author.appendChild(s);
  }
  if (contactIcons) author.insertAdjacentHTML('beforeend', contactIcons);
  footer.appendChild(author);

  if (ownTrip) {
    const actions = document.createElement('div');
    actions.className = 'my-trip-actions';
    if (trip.status === 'open' || trip.status === 'matched' || !trip.status) {
      const mt = document.createElement('button');
      mt.className = 'btn-sm-outline' + (trip.matches_count ? ' has-matches' : '');
      mt.innerHTML = `<i class="fa-solid fa-handshake"></i> ${trip.matches_count || 0} match${trip.matches_count === 1 ? '' : 'es'}`;
      mt.onclick = () => openMatchesModal(trip);
      actions.appendChild(mt);
      const mod = document.createElement('button'); mod.className = 'btn-sm-outline'; mod.textContent = 'Modify';
      mod.onclick = () => modifyTrip(trip.id);
      const dis = document.createElement('button'); dis.className = 'btn-sm-outline danger'; dis.textContent = 'Close';
      dis.onclick = () => disableTrip(trip.id);
      actions.append(mod, dis);
    }
    footer.appendChild(actions);
  } else {
    const btn = document.createElement('button');
    btn.className = 'connect-btn';
    btn.textContent = 'Connect';
    if (IS_LOGGED_IN) btn.onclick = () => openConnectModal(trip.id, trip.author?.username || 'this traveller');
    else btn.onclick = () => { window.location = '/auth/register'; };
    footer.appendChild(btn);
  }
  return card;
}

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
document.getElementById('postTripBtn')?.addEventListener('click', async () => {
  if (!IS_LOGGED_IN) {
    document.getElementById('authModal').classList.add('open');
    return;
  }
  const form = document.getElementById('searchForm');
  const tripType = document.getElementById('tripTypeHidden').value;
  const isMulti = tripType === 'multi_destination';

  const formData = {};
  new FormData(form).forEach((v, k) => { if (!k.startsWith('contact_')) formData[k] = v; });

  if (isMulti) {
    formData.legs = collectLegs();
    formData.preferred_languages = [...document.querySelectorAll('#langSelectMulti input:checked')].map(el => el.value);
    formData.ticket_booked = document.querySelector('input[name="ticket_booked_multi"]')?.checked ? 'on' : '';
  } else {
    formData.preferred_languages = [...form.querySelectorAll('input[name="preferred_languages"]:checked')].map(el => el.value);
  }

  ['connect_me_to', 'traveller_needs'].forEach(name => {
    formData[name] = [...form.querySelectorAll(`input[name="${name}"]:checked`)].map(el => el.value);
  });

  formData.contact_points = collectContactRows(document.getElementById('contactRowsBody'));
  formData.contact_consent = !!document.getElementById('contactConsent')?.checked;

  const btn = document.getElementById('postTripBtn');
  btn.disabled = true;
  try {
    const res = await apiFetch('/api/post-trip', { method: 'POST', body: JSON.stringify(formData) });
    const data = await res.json();
    if (data.success) {
      showToast(data.matches_count
        ? `Trip posted! We found ${data.matches_count} possible companion${data.matches_count === 1 ? '' : 's'} — see My Trips.`
        : 'Trip posted successfully! We will notify you when a companion on your route appears.', 'success');
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
  }
});

document.getElementById('findDesisBtn')?.addEventListener('click', () => {
  loadResults();
  document.getElementById('results')?.scrollIntoView({ behavior: 'smooth' });
});

// ===== MY TRIPS =====
async function loadMyTrips() {
  const grid = document.getElementById('myTripsGrid');
  if (!grid || !IS_LOGGED_IN) return;

  const res = await apiFetch('/api/my-trips');
  const data = await res.json();
  grid.innerHTML = '';
  if (!data.trips?.length) {
    grid.innerHTML = '<div class="loading-spinner">You have no trips yet. Post one above!</div>';
    return;
  }
  data.trips.forEach(trip => grid.appendChild(buildTripCard(trip, true)));
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
  if (t.trip_type === 'multi_destination') {
    return showToast('Multi-stop trips cannot be edited yet — close it and post an updated one.', 'info');
  }
  const f = document.getElementById('editTripForm');
  f.elements.trip_id.value = t.id;
  f.elements.role.value = t.role || 'seeking_help';
  f.elements.flying_from.value = t.flying_from || '';
  f.elements.destination.value = t.destination || '';
  f.elements.from_date.value = t.from_date || '';
  f.elements.to_date.value = t.to_date || '';
  f.elements.airline.value = t.airline || '';
  f.elements.flight_number.value = t.flight_number || '';
  f.elements.additional_comments.value = t.additional_comments || '';
  f.elements.ticket_booked.checked = !!t.ticket_booked;
  f.elements.is_anonymous.checked = !!t.is_anonymous;
  f.querySelectorAll('input[name="preferred_languages"]').forEach(cb => { cb.checked = (t.preferred_languages || []).includes(cb.value); });
  f.querySelectorAll('input[name="traveller_needs"]').forEach(cb => { cb.checked = (t.traveller_needs || []).includes(cb.value); });
  document.getElementById('editReturnRow').style.display = t.trip_type === 'round_trip' ? '' : 'none';
  modal.style.display = 'flex';
}

document.getElementById('closeEditTripModal')?.addEventListener('click', () => { document.getElementById('editTripModal').style.display = 'none'; });
document.getElementById('cancelEditTrip')?.addEventListener('click', () => { document.getElementById('editTripModal').style.display = 'none'; });

document.getElementById('editTripForm')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const f = e.target;
  const id = f.elements.trip_id.value;
  const body = {
    role: f.elements.role.value,
    flying_from: f.elements.flying_from.value.trim(),
    destination: f.elements.destination.value.trim(),
    from_date: f.elements.from_date.value,
    to_date: document.getElementById('editReturnRow').style.display === 'none' ? '' : f.elements.to_date.value,
    airline: f.elements.airline.value.trim(),
    flight_number: f.elements.flight_number.value.trim(),
    additional_comments: f.elements.additional_comments.value.trim(),
    ticket_booked: f.elements.ticket_booked.checked,
    is_anonymous: f.elements.is_anonymous.checked,
    preferred_languages: [...f.querySelectorAll('input[name="preferred_languages"]:checked')].map(c => c.value),
    traveller_needs: [...f.querySelectorAll('input[name="traveller_needs"]:checked')].map(c => c.value),
  };
  if (!body.flying_from || !body.destination || !body.from_date) return showToast('Route and departure date are required.', 'danger');
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

async function openMatchesModal(trip) {
  const modal = document.getElementById('matchesModal');
  if (!modal) return;
  document.getElementById('matchesSubtitle').textContent = `For your trip ${trip.flying_from || '?'} → ${trip.destination || '?'}${trip.from_date ? ' on ' + trip.from_date : ''}.`;
  const list = document.getElementById('matchesList');
  list.innerHTML = '<div class="loading-spinner"><i class="fa-solid fa-spinner fa-spin"></i></div>';
  modal.style.display = 'flex';
  const res = await apiFetch(`/api/trip/${trip.id}/matches?recompute=1`);
  const data = await res.json();
  list.innerHTML = '';
  if (!data.matches?.length) {
    list.innerHTML = '<div class="notif-empty">No matches yet. We will notify you when a traveller on your route appears.</div>';
    return;
  }
  data.matches.forEach(m => {
    const o = m.other || {};
    const card = document.createElement('div'); card.className = 'match-item';
    const head = document.createElement('div'); head.className = 'match-head';
    const score = document.createElement('div');
    score.className = 'score-badge ' + (m.score >= 75 ? 'score-high' : m.score >= 55 ? 'score-mid' : 'score-low');
    score.textContent = `${m.score}%`;
    const title = document.createElement('div'); title.className = 'match-title';
    const name = document.createElement('strong'); name.textContent = o.author?.username || 'Traveller';
    const meta = document.createElement('div'); meta.className = 'muted';
    meta.textContent = `${o.flying_from || '?'} → ${o.destination || '?'} · ${o.from_date || 'similar date'}${o.airline ? ' · ' + o.airline + (o.flight_number ? ' ' + o.flight_number : '') : ''}`;
    const role = document.createElement('span'); role.className = `trip-role-badge chip-role-${esc(o.role || '')}`; role.textContent = ROLE_LABELS[o.role] || o.role || '';
    title.append(name, document.createTextNode(' '), role, meta);
    head.append(score, title);
    card.appendChild(head);
    card.appendChild(criteriaChips(m.criteria));
    const status = document.createElement('div'); status.className = 'muted'; status.style.fontSize = '12px';
    const mine = m.my_status, theirs = m.their_status;
    status.textContent = mine || theirs
      ? `You: ${(mine || 'not notified').replace(/_/g, ' ')} · Them: ${(theirs || 'not notified').replace(/_/g, ' ')}`
      : 'Not shared yet — click "Share my contact & notify" to introduce yourselves.';
    card.appendChild(status);
    const actions = document.createElement('div'); actions.className = 'match-actions';
    if (m.status !== 'connected' && m.status !== 'dismissed') {
      const share = document.createElement('button'); share.className = 'btn btn-primary';
      share.style.cssText = 'padding:7px 12px;font-size:12px';
      share.innerHTML = '<i class="fa-solid fa-paper-plane"></i> Share my contact & notify';
      share.onclick = async () => {
        share.disabled = true;
        const r = await apiFetch(`/api/matches/${m.id}/notify`, { method: 'POST', body: '{}' });
        const d = await r.json();
        if (d.success) {
          showToast('Introduction sent. Check the link in your notifications.', 'success');
          if (d.problems?.length) d.problems.forEach(p => showToast(p, 'info'));
          openMatchesModal(trip);
        } else { showToast(d.error || 'Failed', 'danger'); share.disabled = false; }
      };
      actions.appendChild(share);
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
        if ((await r.json()).success) { showToast('Match dismissed', 'info'); openMatchesModal(trip); loadMyTrips(); }
      };
      actions.appendChild(dis);
    }
    card.appendChild(actions);
    list.appendChild(card);
  });
}

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
document.querySelectorAll('.star-rating i').forEach(star => {
  star.addEventListener('mouseenter', () => {
    document.querySelectorAll('.star-rating i').forEach((s, i) => {
      s.classList.toggle('active', i < +star.dataset.val);
    });
  });
  star.addEventListener('mouseleave', () => {
    document.querySelectorAll('.star-rating i').forEach((s, i) => {
      s.classList.toggle('active', i < selectedRating);
    });
  });
  star.addEventListener('click', () => {
    selectedRating = +star.dataset.val;
    document.getElementById('ratingValue').value = selectedRating;
  });
});

document.getElementById('reviewForm')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const rating = document.getElementById('ratingValue').value;
  const comment = document.getElementById('reviewComment').value.trim();
  if (!rating || rating === '0') return showToast('Please select a star rating.', 'danger');
  const res = await apiFetch('/api/feedback', { method: 'POST', body: JSON.stringify({ rating: +rating, comment }) });
  const data = await res.json();
  if (data.success) showToast(data.message, 'success');
  else showToast(data.error || 'Failed', 'danger');
});

// ===== CHAT SIDEBAR =====
let activeChatRoomId = null;
let chatPollInterval = null;
let chatLastMsgId = 0;
let _chatRooms = [];

document.getElementById('chatToggle')?.addEventListener('click', () => {
  const panel = document.getElementById('chatPanel');
  panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
  if (panel.style.display === 'block') loadChatRooms();
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
