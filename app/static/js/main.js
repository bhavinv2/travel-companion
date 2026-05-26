// ===== HELPERS =====
function showToast(msg, type = 'success') {
  const container = document.getElementById('toastContainer');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `<span>${msg}</span><button onclick="this.parentElement.remove()">&times;</button>`;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 5000);
}

function apiFetch(url, options = {}) {
  return fetch(url, {
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN, ...options.headers },
    ...options,
  });
}

// ===== NAVBAR =====
document.getElementById('hamburger')?.addEventListener('click', () => {
  document.getElementById('navLinks')?.classList.toggle('open');
});

// Auth modal
document.getElementById('authModalBtn')?.addEventListener('click', () => {
  document.getElementById('authModal').style.display = 'flex';
});
document.getElementById('closeAuthModal')?.addEventListener('click', () => {
  document.getElementById('authModal').style.display = 'none';
});

// User dropdown
document.getElementById('userMenuBtn')?.addEventListener('click', (e) => {
  e.stopPropagation();
  document.getElementById('userDropdown')?.classList.toggle('open');
});
document.addEventListener('click', () => {
  document.getElementById('userDropdown')?.classList.remove('open');
});

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


// Trip type radio
function applyTripTypeUI(type) {
  const hiddenEl = document.getElementById('tripTypeHidden');
  if (!hiddenEl) return;
  hiddenEl.value = type;
  const isMulti = type === 'multi_destination';
  const isRound = type === 'round_trip';

  // Single-leg route section
  document.getElementById('flightRoute').style.display = isMulti ? 'none' : '';
  // Return date only for round trip
  document.getElementById('fieldReturnDate').style.display = isRound ? '' : 'none';
  // Multi-destination section
  document.getElementById('multiDestSection').style.display = isMulti ? '' : 'none';
  if (isMulti && document.getElementById('legsContainer').children.length === 0) {
    addLeg(); addLeg(); // start with 2 legs
  }
}

document.querySelectorAll('input[name=trip_type]').forEach(r => {
  r.addEventListener('change', () => applyTripTypeUI(r.value));
});
// init on load
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

document.getElementById('connectTo')?.querySelectorAll('input').forEach(cb => {
  cb.addEventListener('change', () => updateMultiLabel('connectTo', 'connectToLabel'));
});
document.getElementById('travellerNeeds')?.querySelectorAll('input').forEach(cb => {
  cb.addEventListener('change', () => updateMultiLabel('travellerNeeds', 'travellerNeedsLabel'));
});
document.getElementById('langSelect')?.querySelectorAll('input').forEach(cb => {
  cb.addEventListener('change', () => updateMultiLabel('langSelect', 'langSelectLabel'));
});
document.getElementById('langSelectMulti')?.querySelectorAll('input').forEach(cb => {
  cb.addEventListener('change', () => updateMultiLabel('langSelectMulti', 'langSelectMultiLabel'));
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
  const formData = form ? Object.fromEntries(new FormData(form)) : {};
  formData.travel_type = 'air';
  formData.limit = 20;

  ['connect_me_to', 'traveller_needs', 'preferred_languages'].forEach(name => {
    const vals = [...(form?.querySelectorAll(`input[name="${name}"]:checked`) || [])].map(el => el.value);
    if (vals.length) formData[name] = vals;
  });

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

function buildTripCard(trip, isOwn = false) {
  const card = document.createElement('div');
  card.className = 'trip-card';
  card.dataset.tripId = trip.id;

  const ownTrip = isOwn || (IS_LOGGED_IN && trip.user_id === CURRENT_USER_ID);
  const anon = trip.is_anonymous;

  const isMulti = trip.trip_type === 'multi_destination';
  const from = trip.flying_from || '?';
  const to = trip.destination || '?';
  const fromDate = trip.from_date || '';
  const toDate = trip.to_date || '';
  const tags = [...(trip.connect_me_to || []), ...(trip.traveller_needs || [])].slice(0, 4);
  const langs = (trip.preferred_languages || []).join(', ');

  let legsHtml = '';
  if (isMulti && (trip.legs || []).length) {
    legsHtml = `<div class="trip-legs">${trip.legs.map((l, i) =>
      `<div class="trip-leg-row"><span class="leg-dot">${i+1}</span><span>${l.from} → ${l.to}</span>${l.date ? `<span class="leg-date">${l.date}</span>` : ''}${l.airline ? `<span class="leg-airline">${l.airline}${l.flight_number ? ' '+l.flight_number : ''}</span>` : ''}</div>`
    ).join('')}</div>`;
  }

  const detailsHtml = anon ? '' : `
      ${!isMulti && trip.airline ? `<div class="trip-detail-row"><i class="fa-solid fa-plane"></i> ${trip.airline}${trip.flight_number ? ' ' + trip.flight_number : ''}</div>` : ''}
      ${!isMulti && fromDate ? `<div class="trip-detail-row"><i class="fa-solid fa-calendar"></i> ${fromDate}${toDate ? ' → ' + toDate : ''}</div>` : ''}
      ${trip.on_behalf_of ? `<div class="trip-detail-row"><i class="fa-solid fa-person"></i> On behalf of: ${trip.on_behalf_of}</div>` : ''}
      ${langs ? `<div class="trip-detail-row"><i class="fa-solid fa-language"></i> ${langs}</div>` : ''}
      ${trip.ticket_booked ? `<div class="trip-detail-row"><i class="fa-solid fa-ticket"></i> Ticket booked</div>` : ''}
      ${trip.special_needs_notes ? `<div class="trip-detail-row"><i class="fa-solid fa-heart-pulse"></i> ${trip.special_needs_notes}</div>` : ''}`;

  const authorHtml = anon
    ? `<div class="trip-author"><i class="fa-solid fa-user-secret"></i> <span>Anonymous</span></div>`
    : `<div class="trip-author">
        ${trip.author.photo_url ? `<img src="${trip.author.photo_url}" alt="${trip.author.username}"/>` : '<i class="fa-solid fa-circle-user"></i>'}
        <span>${trip.author.username}</span>
       </div>`;

  let footerAction;
  if (ownTrip) {
    footerAction = `<div class="my-trip-actions">
      <button class="btn-sm-outline" onclick="modifyTrip(${trip.id})">Modify</button>
      <button class="btn-sm-outline danger" onclick="disableTrip(${trip.id})">Disable</button>
    </div>`;
  } else if (IS_LOGGED_IN) {
    footerAction = `<button class="connect-btn" onclick="openConnectModal(${trip.id}, '${trip.author.username}')">Connect</button>`;
  } else {
    footerAction = `<button class="connect-btn" onclick="window.location='/auth/register'">Connect</button>`;
  }

  card.innerHTML = `
    <div class="trip-card-header">
      <div class="trip-route">${from} <span>→</span> ${to}</div>
      <span class="trip-type-badge">✈ ${trip.trip_type === 'round_trip' ? 'Round Trip' : trip.trip_type === 'multi_destination' ? 'Multi-Stop' : 'One Way'}</span>
    </div>
    <div class="trip-details">
      ${isMulti ? legsHtml : detailsHtml}
    </div>
    ${!anon && tags.length ? `<div class="trip-tags">${tags.map(t => `<span class="trip-tag">${t.replace(/_/g,' ')}</span>`).join('')}</div>` : ''}
    <div class="trip-card-footer">
      ${authorHtml}
      ${footerAction}
    </div>`;
  return card;
}

// ===== POST TRIP =====
document.getElementById('postTripBtn')?.addEventListener('click', async () => {
  if (!IS_LOGGED_IN) {
    document.getElementById('authModal').style.display = 'flex';
    return;
  }
  const form = document.getElementById('searchForm');
  const tripType = document.getElementById('tripTypeHidden').value;
  const isMulti = tripType === 'multi_destination';

  const formData = {};
  new FormData(form).forEach((v, k) => { formData[k] = v; });

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

  try {
    const res = await apiFetch('/api/post-trip', { method: 'POST', body: JSON.stringify(formData) });
    const data = await res.json();
    if (data.success) {
      showToast('Trip posted successfully!', 'success');
      loadResults();
      loadMyTrips();
    } else {
      showToast(data.error || 'Failed to post trip', 'danger');
    }
  } catch (e) {
    showToast('Network error. Please try again.', 'danger');
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
    grid.innerHTML = '<div class="loading-spinner">You have no active trips. Post one above!</div>';
    return;
  }
  data.trips.forEach(trip => grid.appendChild(buildTripCard(trip, true)));
}

async function disableTrip(tripId) {
  showConfirm('Disable this trip?', 'This will remove your listing from search results.', async () => {
    const res = await apiFetch(`/api/trip/${tripId}`, { method: 'DELETE' });
    const data = await res.json();
    if (data.success) {
      showToast('Trip disabled.', 'success');
      loadMyTrips();
    }
  });
}

function modifyTrip(tripId) {
  showConfirm('Modify this trip?', 'You can update your trip details below. All connected users will be notified.', () => {
    document.getElementById('search').scrollIntoView({ behavior: 'smooth' });
  });
}

// ===== MESSAGE MODAL =====
// ===== CONNECTION REQUEST MODAL =====
function openConnectModal(tripId, username) {
  document.getElementById('connectTripId').value = tripId;
  document.getElementById('connectModalSubtitle').textContent = `Send a connection request to ${username}. They will be notified and can accept or decline.`;
  document.getElementById('connectAnonymous').checked = false;
  document.getElementById('connectModal').style.display = 'flex';
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
  document.getElementById('respondConnectionId').value = connectionId;
  document.getElementById('respondModalBody').textContent = body;
  document.getElementById('respondAnonymous').checked = false;
  document.getElementById('respondModal').style.display = 'flex';
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
  document.getElementById('confirmTitle').textContent = title;
  document.getElementById('confirmMsg').textContent = msg;
  confirmCallback = callback;
  document.getElementById('confirmModal').style.display = 'flex';
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

async function loadChatRooms() {
  if (!IS_LOGGED_IN) return;
  const list = document.getElementById('chatRoomsList');
  if (!list) return;
  const res = await apiFetch('/api/rooms');
  const data = await res.json();
  list.innerHTML = '';
  if (!data.rooms?.length) {
    list.innerHTML = '<div class="chat-loading">No conversations yet.</div>';
    return;
  }
  data.rooms.forEach(room => {
    const item = document.createElement('div');
    item.className = 'chat-room-item';
    item.innerHTML = `
      <div class="chat-room-avatar">
        ${room.other_user.photo_url ? `<img src="${room.other_user.photo_url}" style="width:38px;height:38px;border-radius:50%;object-fit:cover"/>` : '<i class="fa-solid fa-circle-user"></i>'}
      </div>
      <div class="chat-room-info">
        <strong>${room.other_user.username}</strong>
        <span>${room.last_message ? room.last_message.message || 'Sent a file' : 'Start chatting'}</span>
      </div>
      ${room.unread_count > 0 ? `<span class="badge">${room.unread_count}</span>` : ''}`;
    item.onclick = () => openChatWindow(room.room_id, room.other_user.username);
    list.appendChild(item);
  });
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

async function fetchChatMessages() {
  if (!activeChatRoomId) return;
  const res = await apiFetch(`/api/messages/${activeChatRoomId}?since_id=${chatLastMsgId}`);
  const data = await res.json();
  if (!data.messages?.length) return;
  const container = document.getElementById('chatMessages');
  data.messages.forEach(m => {
    const div = document.createElement('div');
    div.className = `msg-bubble ${m.sender_id === CURRENT_USER_ID ? 'sent' : 'received'}`;
    if (m.message_type === 'image') {
      div.innerHTML = `<img src="${m.file_url}" style="max-width:180px;border-radius:8px"/>`;
    } else {
      div.textContent = m.message;
    }
    container.appendChild(div);
    chatLastMsgId = Math.max(chatLastMsgId, m.id);
  });
  container.scrollTop = container.scrollHeight;
}

document.getElementById('chatSendBtn')?.addEventListener('click', sendChatMessage);
document.getElementById('chatInput')?.addEventListener('keydown', e => { if (e.key === 'Enter') sendChatMessage(); });

async function sendChatMessage() {
  const input = document.getElementById('chatInput');
  const msg = input.value.trim();
  if (!msg || !activeChatRoomId) return;
  input.value = '';
  await apiFetch(`/api/messages/${activeChatRoomId}`, { method: 'POST', body: JSON.stringify({ message: msg }) });
  fetchChatMessages();
}

// Unread count polling
async function pollUnread() {
  if (!IS_LOGGED_IN) return;
  try {
    const res = await apiFetch('/api/unread-count');
    const data = await res.json();
    const msgBadge = document.getElementById('unreadBadge');
    const chatBadge = document.getElementById('chatBadge');
    const pending = data.pending_connections || [];
    const total = (data.unread_messages || 0) + pending.length;
    if (msgBadge) { msgBadge.textContent = total; msgBadge.style.display = total > 0 ? 'flex' : 'none'; }
    if (chatBadge) { chatBadge.textContent = total; chatBadge.style.display = total > 0 ? 'flex' : 'none'; }

    // Show pending connection request toasts (once per session)
    pending.forEach(c => {
      const key = `conn_notified_${c.id}`;
      if (sessionStorage.getItem(key)) return;
      sessionStorage.setItem(key, '1');
      const container = document.getElementById('toastContainer');
      if (!container) return;
      const toast = document.createElement('div');
      toast.className = 'toast toast-info conn-request-toast';
      toast.innerHTML = `
        <div><strong>${c.requester}</strong> wants to connect on your trip <em>${c.trip_from} → ${c.trip_to}</em></div>
        <div style="display:flex;gap:8px;margin-top:8px;">
          <button class="btn btn-primary" style="padding:5px 12px;font-size:12px;" onclick="openRespondModal(${c.id}, '${c.requester} wants to connect on your trip from ${c.trip_from} to ${c.trip_to}.');this.closest('.conn-request-toast').remove();">Respond</button>
          <button style="background:none;border:none;cursor:pointer;font-size:18px;color:var(--muted);" onclick="this.closest('.conn-request-toast').remove()">&times;</button>
        </div>`;
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

// Auto-dismiss toasts
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
    airports.forEach((a, i) => {
      const div = document.createElement('div');
      div.className = 'airport-option';
      div.innerHTML = `<span class="airport-iata">${a.iata}</span><span><strong>${a.city || a.name}</strong> <span class="airport-detail">${a.name} · ${a.country}</span></span>`;
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
      div.innerHTML = `<span class="airport-iata">${a.iata}</span><span><strong>${a.name}</strong> <span class="airport-detail">${a.country}</span></span>`;
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
