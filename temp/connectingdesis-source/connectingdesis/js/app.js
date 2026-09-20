(() => {
"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const icon = (n, c = "i i-sm") => `<svg class="${c}" aria-hidden="true"><use href="#i-${n}"/></svg>`;
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }
};
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const pad = n => String(n).padStart(2, "0");
const isoDate = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const TODAY = isoDate(new Date());
const parseISO = iso => { const [y, m, d] = iso.split("-").map(Number); return new Date(y, m - 1, d); };
const addDays = (iso, n) => { const d = parseISO(iso); d.setDate(d.getDate() + n); return isoDate(d); };
const fmtDate = (iso, opts = { day: "numeric", month: "short", year: "numeric" }) => iso ? parseISO(iso).toLocaleDateString("en-GB", opts) : "";
const city = v => String(v || "").replace(/\s*\([A-Z]{3}\)\s*$/, "").trim();
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
const phoneOk = v => { const d = v.replace(/[^\d]/g, ""); return d.length >= 10 && d.length <= 15; };

$$('input[type="date"]').forEach(i => i.min = TODAY);
setTimeout(() => $(".hero")?.classList.remove("hero-anim"), 3200);

/* ---------- Toast ---------- */
let toastTimer;
function toast(msg) {
  const t = $("#toast");
  t.innerHTML = icon("check") + "<span>" + esc(msg) + "</span>";
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 3400);
}

/* ---------- Field errors ---------- */
let errSeq = 0;
function setErr(wrap, msg) {
  if (!wrap) return;
  const e = wrap.querySelector(".err");
  wrap.classList.toggle("invalid", !!msg);
  if (e) { if (!e.id) e.id = "err" + (++errSeq); e.textContent = msg || ""; e.hidden = !msg; }
  wrap.querySelectorAll("input:not([type=radio]):not([type=checkbox]),select,textarea").forEach(inp => {
    inp.setAttribute("aria-invalid", msg ? "true" : "false");
    if (msg && e) inp.setAttribute("aria-describedby", e.id); else inp.removeAttribute("aria-describedby");
  });
}
function focusFirstInvalid(root) {
  const w = root.querySelector(".invalid");
  if (!w) return;
  const el = w.querySelector("input,select,textarea");
  el && el.focus();
}
document.addEventListener("input", e => {
  const w = e.target.closest("[data-f].invalid");
  if (w) setErr(w, "");
});
document.addEventListener("change", e => {
  const w = e.target.closest("[data-f].invalid");
  if (w) setErr(w, "");
});

/* ---------- Mobile menu ---------- */
const menuBtn = $(".menu-toggle"), menu = $("#mobile-menu");
menuBtn.addEventListener("click", () => { const o = menu.classList.toggle("open"); menuBtn.setAttribute("aria-expanded", String(o)); });
menu.addEventListener("click", e => { if (e.target.closest("a,button")) { menu.classList.remove("open"); menuBtn.setAttribute("aria-expanded", "false"); } });

/* ---------- Layers (modal / drawer) ---------- */
let layer = null, returnFocus = null;
const scrim = $("#scrim");
const inertTargets = () => [$("#main"), $(".site-header"), $(".footer")];
function openLayer(el, focusSel) {
  if (layer) { layer.classList.remove("open"); } else { returnFocus = document.activeElement; }
  layer = el;
  el.classList.add("open");
  scrim.classList.add("open");
  document.body.classList.add("locked");
  inertTargets().forEach(t => t && (t.inert = true));
  setTimeout(() => {
    const f = (focusSel && el.querySelector(focusSel)) || el.querySelector("input:not([type=radio]),select,textarea") || el.querySelector("button");
    f && f.focus({ preventScroll: true });
  }, 80);
}
function closeLayer() {
  if (!layer) return;
  layer.classList.remove("open");
  scrim.classList.remove("open");
  document.body.classList.remove("locked");
  inertTargets().forEach(t => t && (t.inert = false));
  layer = null;
  if (returnFocus && document.contains(returnFocus)) returnFocus.focus({ preventScroll: true });
}
scrim.addEventListener("click", closeLayer);
document.addEventListener("keydown", e => {
  if (!layer) return;
  if (e.key === "Escape") { e.preventDefault(); closeLayer(); return; }
  if (e.key === "Tab") {
    const f = $$('button,[href],input:not([type=hidden]),select,textarea,[tabindex]:not([tabindex="-1"])', layer)
      .filter(x => !x.disabled && x.offsetParent !== null);
    if (!f.length) return;
    const first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }
});

function openDialog(html, focusSel) {
  $("#dialog-body").innerHTML = html;
  openLayer($("#dialog"), focusSel);
}

/* ---------- Tabs ---------- */
const tabs = [$("#tab-find"), $("#tab-post")];
function setTab(name, focus) {
  tabs.forEach(t => {
    const on = t.id === "tab-" + name;
    t.setAttribute("aria-selected", String(on));
    t.tabIndex = on ? 0 : -1;
    $("#" + t.getAttribute("aria-controls")).hidden = !on;
    if (on && focus) t.focus();
  });
}
tabs.forEach(t => {
  t.addEventListener("click", () => setTab(t.id.slice(4)));
  t.addEventListener("keydown", e => {
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") { e.preventDefault(); setTab(t.id === "tab-find" ? "post" : "find", true); }
  });
});

/* ---------- Views & routing ---------- */
const homeView = $("#view-home"), resultsView = $("#view-results");
function route() {
  const h = location.hash;
  if (h.startsWith("#/find-companions")) {
    homeView.hidden = true; resultsView.hidden = false;
    renderResults(new URLSearchParams(h.split("?")[1] || ""));
    document.title = "Find travel companions — ConnectingDesis";
    window.scrollTo(0, 0);
  } else {
    const wasHidden = homeView.hidden;
    homeView.hidden = false; resultsView.hidden = true;
    document.title = "ConnectingDesis — Travel together. Feel at home.";
    if (wasHidden) {
      const target = h && h.length > 1 && document.getElementById(h.slice(1));
      if (target) target.scrollIntoView({ block: "start" }); else window.scrollTo(0, 0);
    }
  }
}
window.addEventListener("hashchange", route);
function goResults(params) {
  const q = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => { if (v) q.set(k, v); });
  location.hash = "#/find-companions?" + q.toString();
}
function whenHome(fn) {
  if (!homeView.hidden) { fn(); return; }
  location.hash = "#widget";
  setTimeout(fn, 40);
}
function scrollToWidget() {
  $("#widget").scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
}

function openPostTrip(forWhom) {
  whenHome(() => {
    setTab("post");
    if (!$("#pt-success").hidden) resetWizard();
    if (forWhom) { const r = $$('input[name="forWhom"]').find(x => x.value === forWhom); if (r) { r.checked = true; setErr(r.closest("[data-f]"), ""); } }
    scrollToWidget();
    setTimeout(() => paneFocus(step), reduceMotion ? 0 : 480);
  });
}
function openFind() {
  whenHome(() => {
    setTab("find");
    scrollToWidget();
    setTimeout(() => $("#f-from").focus({ preventScroll: true }), reduceMotion ? 0 : 480);
  });
}

/* ---------- Global click delegation ---------- */
document.addEventListener("click", e => {
  const t = e.target.closest("[data-post],[data-find],[data-contact],[data-insurance],[data-close],[data-swap],[data-route],[data-signin],[data-soon],[data-car]");
  if (!t) return;
  if (t.hasAttribute("data-post")) { e.preventDefault(); if (layer) closeLayer(); openPostTrip(t.dataset.post || ""); }
  else if (t.hasAttribute("data-find")) { e.preventDefault(); openFind(); }
  else if (t.hasAttribute("data-contact")) { e.preventDefault(); openContact(t.dataset.contact || ""); }
  else if (t.hasAttribute("data-insurance")) { e.preventDefault(); openInsurance(); }
  else if (t.hasAttribute("data-close")) { closeLayer(); }
  else if (t.hasAttribute("data-swap")) {
    const [a, b] = t.dataset.swap.split(" ").map(id => $("#" + id));
    [a.value, b.value] = [b.value, a.value];
  }
  else if (t.hasAttribute("data-route")) {
    const [from, to] = t.dataset.route.split("|");
    goResults({ from, to });
  }
  else if (t.hasAttribute("data-signin")) { openSignIn(t.dataset.signin === "up"); }
  else if (t.hasAttribute("data-soon")) { e.preventDefault(); toast("This page is on its way."); }
  else if (t.hasAttribute("data-car")) {
    const track = $("#dest-track"), card = track.querySelector(".dest-card");
    track.scrollBy({ left: (card.offsetWidth + 18) * Number(t.dataset.car), behavior: reduceMotion ? "auto" : "smooth" });
  }
});

/* ---------- Find a companion ---------- */
function validateSearch(fromEl, toEl, errEl) {
  const from = fromEl.value.trim(), to = toEl.value.trim();
  const cells = [fromEl.closest(".cell"), toEl.closest(".cell")];
  cells.forEach(c => c.classList.remove("invalid"));
  let msg = "";
  if (!from) { msg = "Enter where you're flying from."; cells[0].classList.add("invalid"); fromEl.focus(); }
  else if (!to) { msg = "Enter where you're flying to."; cells[1].classList.add("invalid"); toEl.focus(); }
  else if (city(from).toLowerCase() === city(to).toLowerCase()) { msg = "From and To need to be different places."; cells[1].classList.add("invalid"); toEl.focus(); }
  errEl.textContent = msg; errEl.hidden = !msg;
  return !msg;
}
[["#find-form", "f"], ["#r-form", "r"]].forEach(([sel, p]) => {
  $(sel).addEventListener("submit", e => {
    e.preventDefault();
    const fromEl = $(`#${p}-from`), toEl = $(`#${p}-to`), err = $(`#${p}-err`);
    if (!validateSearch(fromEl, toEl, err)) return;
    goResults({ from: city(fromEl.value), to: city(toEl.value), date: $(p === "f" ? "#f-date" : "#r-date-in").value, with: $(`#${p}-trav`).value });
  });
  $(sel).addEventListener("input", e => { const c = e.target.closest(".cell.invalid"); if (c) { c.classList.remove("invalid"); $(`#${p}-err`).hidden = true; } });
});

/* ---------- Results ---------- */
const PEOPLE = [
  { id: "p1", name: "Priya S.", home: "Bengaluru", sameOrigin: false, langs: ["Telugu", "English"], age: "30–49", gender: "Female", with: "Parent travelling", match: "flight", off: 0, trips: 6, since: 2024, bio: "Flying to see my daughter. Happy to help an elder with transit and forms." },
  { id: "p2", name: "Ravi K.", home: "Hyderabad", sameOrigin: true, langs: ["Telugu", "Hindi"], age: "50–64", gender: "Male", with: "Travelling solo", match: "flight", off: 0, trips: 11, since: 2023, bio: "Frequent flyer on this route. I know the Doha and Dubai transfers well." },
  { id: "p3", name: "Lakshmi N.", home: "Chennai", sameOrigin: false, langs: ["Tamil", "English"], age: "65 and over", gender: "Female", with: "Couple travelling", match: "date", off: 0, trips: 3, since: 2025, bio: "Travelling with my husband to visit our son." },
  { id: "p4", name: "Arjun M.", home: "Hyderabad", sameOrigin: true, langs: ["Telugu", "English"], age: "18–29", gender: "Male", with: "Travelling solo", match: "flight", off: 0, trips: 4, since: 2025, bio: "Grad student heading back after winter break. Glad to lend a hand." },
  { id: "p5", name: "Meena R.", home: "Hyderabad", sameOrigin: true, langs: ["Telugu", "Kannada"], age: "30–49", gender: "Female", with: "Family travelling", match: "date", off: 1, trips: 5, since: 2024, bio: "With my two kids. We'd love a friendly face on the long leg." },
  { id: "p6", name: "Suresh P.", home: "Vijayawada", sameOrigin: false, langs: ["Telugu"], age: "50–64", gender: "Male", with: "Couple travelling", match: "date", off: -1, trips: 2, since: 2025, bio: "Visiting family for the holidays." },
  { id: "p7", name: "Ananya G.", home: "Pune", sameOrigin: false, langs: ["Marathi", "Hindi", "English"], age: "18–29", gender: "Female", with: "Travelling solo", match: "date", off: 0, trips: 7, since: 2024, bio: "Software engineer, calm flyer, happy to sit with someone nervous." },
  { id: "p8", name: "Farhan A.", home: "Hyderabad", sameOrigin: true, langs: ["Urdu", "Hindi", "Telugu"], age: "30–49", gender: "Male", with: "Parent travelling", match: "flight", off: 0, trips: 9, since: 2023, bio: "Bringing my father over. Two elders together is easier than one." },
  { id: "p9", name: "Kavya D.", home: "Bengaluru", sameOrigin: false, langs: ["Kannada", "Telugu", "English"], age: "18–29", gender: "Female", with: "Travelling solo", match: "date", off: 2, trips: 3, since: 2025, bio: "Starting a new job. First time on this route." },
  { id: "p10", name: "Venkat R.", home: "Hyderabad", sameOrigin: true, langs: ["Telugu"], age: "65 and over", gender: "Male", with: "Couple travelling", match: "flight", off: 0, trips: 5, since: 2024, bio: "Retired teacher. My wife and I fly this route every winter." },
  { id: "p11", name: "Deepa J.", home: "Kochi", sameOrigin: false, langs: ["Malayalam", "English"], age: "30–49", gender: "Female", with: "Family travelling", match: "date", off: -2, trips: 4, since: 2024, bio: "Nurse, travelling with family. Comfortable helping with medication schedules." },
  { id: "p12", name: "Harpreet S.", home: "Delhi", sameOrigin: false, langs: ["Punjabi", "Hindi", "English"], age: "30–49", gender: "Male", with: "Travelling solo", match: "date", off: 0, trips: 8, since: 2023, bio: "Business traveller. Always up for good conversation." }
];
const AV_BG = ["#FFF3D8", "#EAF3FF", "#EAF8F0", "#FFF0F3", "#EAF8FA"];
const INDIA = ["india", "hyderabad", "chennai", "bengaluru", "bangalore", "delhi", "mumbai", "kochi", "ahmedabad", "kolkata", "pune", "visakhapatnam", "vijayawada"];
const FLIGHTS = { dallas: "AI 127", "new york": "AI 101", newark: "AI 191", "san francisco": "AI 175", chicago: "AI 125", london: "AI 131", toronto: "AI 187", sydney: "AI 300", dubai: "EK 529", usa: "AI 127", uk: "AI 131", canada: "AI 187", australia: "AI 300", germany: "LH 761" };
let requests = new Set(store.get("cd.requests", []));
let current = { from: "", to: "", date: "", list: [] };

function initials(n) { return n.split(/\s+/).map(w => w[0]).join("").slice(0, 2).toUpperCase(); }
function renderResults(q) {
  const from = city(q.get("from")) || "Hyderabad";
  const to = city(q.get("to"));
  const date = q.get("date") || "";
  $("#r-from").value = from; $("#r-to").value = to; $("#r-date-in").value = date;
  $("#r-trav").value = q.get("with") || ""; $("#flt-with").value = q.get("with") || "";
  $("#r-err").hidden = true;
  const fromIndia = INDIA.includes(from.toLowerCase());
  const flight = FLIGHTS[(to || "").toLowerCase()] || "AI 127";
  const baseDate = date || "2026-12-15";
  current = {
    from, to, date,
    list: PEOPLE.map((p, i) => ({
      ...p,
      origin: fromIndia ? (p.sameOrigin && from.toLowerCase() !== "india" ? from : p.home) : from,
      dest: to || ["Dallas", "London", "Toronto", "New York", "Sydney", "Dubai"][i % 6],
      flight,
      travelDate: addDays(baseDate, p.off),
      av: AV_BG[i % AV_BG.length]
    }))
  };
  $("#r-route").innerHTML = `${esc(from)} ${icon("plane", "i")} ${esc(to || "All destinations")}`;
  $("#r-date").textContent = date ? fmtDate(date) : "Any date";
  applyFilters();
}
function matchLabel(p) {
  if (!current.date) return { text: `Flying ${fmtDate(p.travelDate, { day: "numeric", month: "short" })}`, gold: false };
  if (p.match === "flight" && current.to) return { text: `Same flight · ${p.flight}`, gold: true };
  if (p.off === 0) return { text: "Same date", gold: true };
  const n = Math.abs(p.off);
  return { text: `${fmtDate(p.travelDate, { day: "numeric", month: "short" })} · ${n} day${n > 1 ? "s" : ""} ${p.off > 0 ? "later" : "earlier"}`, gold: false };
}
function applyFilters() {
  const lang = $("#flt-lang").value, age = $("#flt-age").value, gender = $("#flt-gender").value, w = $("#flt-with").value, sort = $("#r-sort").value;
  let list = current.list.filter(p => (!lang || p.langs.includes(lang)) && (!age || p.age === age) && (!gender || p.gender === gender) && (!w || p.with === w));
  const score = p => (p.match === "flight" ? 0 : 10) + Math.abs(p.off);
  list.sort(sort === "date" ? (a, b) => Math.abs(a.off) - Math.abs(b.off) || score(a) - score(b) : (a, b) => score(a) - score(b));
  const n = list.length, label = `${n} traveller${n === 1 ? "" : "s"} found`;
  $("#r-count").textContent = label; $("#r-count2").textContent = label;
  const box = $("#r-cards");
  if (!n) {
    box.innerHTML = `<div class="empty" style="grid-column:1/-1"><h3>No travellers match these filters</h3><p>Try a different language or age group, or post your trip so travellers on this route can find you.</p><div class="row"><button class="btn btn-outline" type="button" id="empty-clear">Clear filters</button><button class="btn btn-navy" type="button" data-post>Post Your Trip — Free</button></div></div>`;
    $("#empty-clear").addEventListener("click", clearFilters);
    return;
  }
  box.innerHTML = list.map(p => {
    const m = matchLabel(p), sent = requests.has(p.id);
    return `<article class="c-card" aria-label="${esc(p.name)}">
      <div class="c-top"><span class="avatar" style="background:${p.av}">${esc(initials(p.name))}</span><div><div class="name">${esc(p.name)}</div><span class="verified">${icon("check")}Verified</span></div></div>
      <div><div class="c-route">${esc(p.origin)} ${icon("plane")} ${esc(p.dest)}</div><div class="tag-row" style="margin-top:8px"><span class="tag ${m.gold ? "gold" : ""}">${esc(m.text)}</span></div></div>
      <div class="tag-row">${p.langs.map(l => `<span class="tag">${esc(l)}</span>`).join("")}</div>
      <p class="c-meta">${icon("users")}${esc(p.with)}</p>
      <div class="c-actions"><button class="btn btn-outline btn-sm" type="button" data-profile="${p.id}">View Profile</button>
      <button class="btn btn-gold btn-sm" type="button" data-connect="${p.id}" ${sent ? "disabled" : ""}>${sent ? icon("check") + "Request sent" : "Connect"}</button></div>
    </article>`;
  }).join("");
}
function clearFilters() { $$("[data-flt]").forEach(s => s.value = ""); applyFilters(); }
$$("[data-flt]").forEach(s => s.addEventListener("change", applyFilters));
$("#r-sort").addEventListener("change", applyFilters);
$("#flt-clear").addEventListener("click", clearFilters);
$("#r-cards").addEventListener("click", e => {
  const pb = e.target.closest("[data-profile]"), cb = e.target.closest("[data-connect]");
  if (pb) openProfile(pb.dataset.profile);
  if (cb) openConnect(cb.dataset.connect);
});
const person = id => current.list.find(p => p.id === id);
function openProfile(id) {
  const p = person(id); if (!p) return;
  const sent = requests.has(p.id);
  openDialog(`<div class="prof-head"><span class="avatar" style="background:${p.av}">${esc(initials(p.name))}</span><div><h2 id="dialog-h" style="padding:0">${esc(p.name)}</h2><span class="verified">${icon("check")}Phone &amp; ID verified</span></div></div>
    <p style="margin-top:16px">${esc(p.bio)}</p>
    <dl class="kv"><dt>Trip</dt><dd>${esc(p.origin)} → ${esc(p.dest)}, ${esc(fmtDate(p.travelDate))}</dd><dt>Match</dt><dd>${esc(matchLabel(p).text)}</dd><dt>Speaks</dt><dd>${esc(p.langs.join(", "))}</dd><dt>Travelling</dt><dd>${esc(p.with)}</dd><dt>Trips on ConnectingDesis</dt><dd>${p.trips}</dd><dt>Member since</dt><dd>${p.since}</dd></dl>
    <p class="lock-note" style="justify-content:flex-start;margin:0 0 18px">${icon("lock")}Contact details are shared only after you both agree to connect.</p>
    <button class="btn btn-gold btn-block" type="button" id="prof-connect" ${sent ? "disabled" : ""}>${sent ? "Request sent" : "Connect with " + esc(p.name.split(" ")[0])}</button>`, "#prof-connect");
  const b = $("#prof-connect"); if (b) b.addEventListener("click", () => openConnect(p.id));
}
function openConnect(id) {
  const p = person(id); if (!p || requests.has(id)) return;
  const first = esc(p.name.split(" ")[0]);
  openDialog(`<h2 id="dialog-h">Connect with ${first}?</h2>
    <p class="intro">${first} will see your route, dates and language. Your email and phone stay hidden until you both agree.</p>
    <div class="f"><label for="cn-msg">Say hello <span class="opt">(optional)</span></label><div class="control ta"><textarea id="cn-msg" maxlength="300" placeholder="Hi ${first}, my mother is on the same flight and speaks Telugu…"></textarea></div></div>
    <div class="pt-foot"><button class="btn btn-text" type="button" data-close>Cancel</button><span class="spacer"></span><button class="btn btn-gold" type="button" id="cn-send">Send request ${icon("arrow")}</button></div>`, "#cn-msg");
  $("#cn-send").addEventListener("click", ev => {
    const btn = ev.currentTarget; btn.disabled = true; btn.classList.add("loading"); btn.innerHTML = '<span class="spinner"></span>Sending';
    setTimeout(() => {
      requests.add(id); store.set("cd.requests", [...requests]);
      $("#dialog-body").innerHTML = `<div class="success" style="margin-top:0"><div class="success-mark">${icon("check", "i")}</div><h2 id="dialog-h" style="padding:0">Request sent</h2><p>We'll let you know when ${first} responds.</p><div class="row"><button class="btn btn-navy" type="button" data-close>Done</button></div></div>`;
      $("#dialog-body [data-close]").focus();
      applyFilters();
    }, 700);
  });
}

/* ---------- Post your trip wizard ---------- */
const form = $("#pt-form");
let step = 1, legSeq = 0;
function paneFocus(n) {
  const pane = $(`[data-pane="${n}"]`);
  const el = n === 1 ? $("#p-from") : pane.querySelector("input:not([type=hidden]),select,textarea");
  el && el.focus({ preventScroll: true });
}
function showStep(n, focus = true) {
  step = n;
  $$("[data-pane]").forEach(p => p.hidden = Number(p.dataset.pane) !== n);
  $$(".step").forEach(s => {
    const k = Number(s.dataset.step);
    s.classList.toggle("done", k < n);
    if (k === n) s.setAttribute("aria-current", "step"); else s.removeAttribute("aria-current");
    s.querySelector(".dot").innerHTML = k < n ? icon("check") : String(k);
  });
  if (n === 3) buildReview();
  const top = $("#widget").getBoundingClientRect().top;
  if (top < 0) $("#widget").scrollIntoView({ block: "start", behavior: reduceMotion ? "auto" : "smooth" });
  if (focus) setTimeout(() => paneFocus(n), 60);
}
const tripType = () => (form.querySelector('input[name="tripType"]:checked') || {}).value;
function syncTripType() {
  const t = tripType();
  $("#ret-wrap").hidden = t !== "round";
  $("#legs-wrap").hidden = t !== "multi";
  $("#p-date-lbl").textContent = t === "multi" ? "Flight 1 date" : "Departure date";
  if (t === "multi" && !$$("#legs [data-leg]").length) addLeg();
}
$$('input[name="tripType"]').forEach(r => r.addEventListener("change", syncTripType));
function addLeg() {
  const legs = $$("#legs [data-leg]");
  if (legs.length >= 3) return;
  const id = ++legSeq;
  const prevTo = legs.length ? legs[legs.length - 1].querySelector('[data-k="to"]').value : $("#p-to").value;
  const row = document.createElement("div");
  row.className = "leg"; row.setAttribute("data-leg", "");
  row.innerHTML = `<span class="num"></span>
    <div class="f" data-f="lf${id}"><label for="lf${id}">From</label><div class="control"><input id="lf${id}" data-k="from" list="airports" placeholder="City or airport" autocomplete="off" value="${esc(prevTo)}"></div><span class="err" hidden></span></div>
    <div class="f" data-f="lt${id}"><label for="lt${id}">To</label><div class="control"><input id="lt${id}" data-k="to" list="airports" placeholder="City or airport" autocomplete="off"></div><span class="err" hidden></span></div>
    <div class="f" data-f="ld${id}"><label for="ld${id}">Date</label><div class="control"><input id="ld${id}" data-k="date" type="date" min="${TODAY}"></div><span class="err" hidden></span></div>
    <button type="button" class="icon-btn" data-rm aria-label="Remove flight">${icon("x")}</button>`;
  $("#legs").appendChild(row);
  renumberLegs();
}
function renumberLegs() {
  const legs = $$("#legs [data-leg]");
  legs.forEach((l, i) => { l.querySelector(".num").textContent = `Flight ${i + 2}`; l.querySelector("[data-rm]").setAttribute("aria-label", `Remove flight ${i + 2}`); });
  $("#add-leg").hidden = legs.length >= 3;
}
$("#add-leg").addEventListener("click", () => { addLeg(); const l = $$("#legs [data-leg]").pop(); l && l.querySelector('[data-k="to"]').focus(); });
$("#legs").addEventListener("click", e => {
  const rm = e.target.closest("[data-rm]"); if (!rm) return;
  rm.closest("[data-leg]").remove(); renumberLegs();
  if (!$$("#legs [data-leg]").length) { $("#tt-one").checked = true; syncTripType(); $("#tt-one").focus(); } else $("#add-leg").focus();
});
$("#p-notes").addEventListener("input", e => $("#notes-count").textContent = `${e.target.value.length} / 500`);

const F = n => form.querySelector(`[data-f="${n}"]`);
function validateStep(n) {
  let ok = true;
  const bad = (w, m) => { setErr(w, m); ok = false; };
  const clear = w => setErr(w, "");
  if (n === 1) {
    const from = $("#p-from").value.trim(), to = $("#p-to").value.trim(), d = $("#p-date").value;
    from ? clear(F("from")) : bad(F("from"), "Enter where the trip starts.");
    if (!to) bad(F("to"), "Enter where the trip ends.");
    else if (from && city(from).toLowerCase() === city(to).toLowerCase()) bad(F("to"), "Choose a different destination from your origin.");
    else clear(F("to"));
    if (!d) bad(F("date"), "Choose your travel date.");
    else if (d < TODAY) bad(F("date"), "Choose today or a later date.");
    else clear(F("date"));
    if (tripType() === "round") {
      const r = $("#p-ret").value;
      if (!r) bad(F("ret"), "Choose your return date.");
      else if (d && r < d) bad(F("ret"), "Return date must be on or after departure.");
      else clear(F("ret"));
    }
    if (tripType() === "multi") {
      let prev = d;
      $$("#legs [data-leg]").forEach(l => {
        const [lf, lt, ld] = ["from", "to", "date"].map(k => l.querySelector(`[data-k="${k}"]`));
        lf.value.trim() ? clear(lf.closest(".f")) : bad(lf.closest(".f"), "Enter a city.");
        lt.value.trim() ? clear(lt.closest(".f")) : bad(lt.closest(".f"), "Enter a city.");
        if (!ld.value) bad(ld.closest(".f"), "Choose a date.");
        else if (prev && ld.value < prev) bad(ld.closest(".f"), "Must be on or after the previous flight.");
        else clear(ld.closest(".f"));
        prev = ld.value || prev;
      });
    }
    const fl = $("#p-flight").value.trim();
    if (fl && !/^[A-Za-z0-9]{2}\s?\d{1,4}[A-Za-z]?$/.test(fl)) bad(F("flight"), "Use the airline code and number, like AI 127."); else clear(F("flight"));
  }
  if (n === 2) {
    form.querySelector('input[name="forWhom"]:checked') ? clear(F("forWhom")) : bad(F("forWhom"), "Choose who this trip is for.");
    $("#p-lang").value ? clear(F("language")) : bad(F("language"), "Choose a language so we can match on it.");
    form.querySelector('input[name="assist"]:checked') ? clear(F("assist")) : bad(F("assist"), "Choose yes or no.");
  }
  if (n === 3) {
    $("#p-name").value.trim().length >= 2 ? clear(F("name")) : bad(F("name"), "Enter your name.");
    EMAIL_RE.test($("#p-email").value.trim()) ? clear(F("email")) : bad(F("email"), "Enter an email address like name@example.com.");
    const ph = $("#p-phone").value.trim();
    !ph || phoneOk(ph) ? clear(F("phone")) : bad(F("phone"), "Enter a number with country code, 10 to 15 digits.");
    $("#p-consent").checked ? clear(F("consent")) : bad(F("consent"), "Tick this so matched travellers can see your trip.");
  }
  if (!ok) focusFirstInvalid($(`[data-pane="${n}"]`));
  return ok;
}
form.addEventListener("click", e => {
  const g = e.target.closest("[data-go]"); if (!g) return;
  const target = Number(g.dataset.go);
  if (target > step) { for (let s = step; s < target; s++) { if (!validateStep(s)) { if (s !== step) showStep(s, false); return; } } }
  showStep(target);
});

function collectTrip() {
  const t = tripType();
  const legs = [{ from: city($("#p-from").value), to: city($("#p-to").value), date: $("#p-date").value }];
  if (t === "multi") $$("#legs [data-leg]").forEach(l => legs.push({ from: city(l.querySelector('[data-k="from"]').value), to: city(l.querySelector('[data-k="to"]').value), date: l.querySelector('[data-k="date"]').value }));
  const val = n => (form.querySelector(`input[name="${n}"]:checked`) || {}).value || "";
  return {
    type: t, legs, ret: t === "round" ? $("#p-ret").value : "",
    travellers: $("#p-trav").value, cls: $("#p-class").value, flight: $("#p-flight").value.trim().toUpperCase(),
    forWhom: val("forWhom"), language: $("#p-lang").value, companion: $("#p-comp").value, age: $("#p-age").value,
    assist: val("assist"), notes: $("#p-notes").value.trim()
  };
}
const TYPE_LABEL = { oneway: "One way", round: "Round trip", multi: "Multi-city" };
function routeText(trip) {
  if (trip.type === "multi") return [trip.legs[0].from, ...trip.legs.map(l => l.to)].join(" → ");
  return `${trip.legs[0].from} ${trip.type === "round" ? "⇄" : "→"} ${trip.legs[0].to}`;
}
function tripRows(trip) {
  const rows = [["Trip type", TYPE_LABEL[trip.type]]];
  if (trip.type === "multi") trip.legs.forEach((l, i) => rows.push([`Flight ${i + 1}`, `${l.from} → ${l.to}, ${fmtDate(l.date)}`]));
  else rows.push(["Departure", fmtDate(trip.legs[0].date)]);
  if (trip.ret) rows.push(["Return", fmtDate(trip.ret)]);
  rows.push(["Travellers", `${trip.travellers} traveller${trip.travellers === "1" ? "" : "s"}`], ["Class", trip.cls]);
  if (trip.flight) rows.push(["Flight number", trip.flight]);
  return rows;
}
function prefRows(trip) {
  const rows = [["Travelling for", trip.forWhom], ["Language", trip.language], ["Companion", trip.companion]];
  if (trip.age) rows.push(["Age group", trip.age]);
  rows.push(["Airport assistance", trip.assist]);
  if (trip.notes) rows.push(["Notes", trip.notes.length > 120 ? trip.notes.slice(0, 120) + "…" : trip.notes]);
  return rows;
}
const dl = rows => `<dl>${rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl>`;
function buildReview() {
  const trip = collectTrip();
  $("#review").innerHTML = `
    <div class="review-sec"><h3>Your trip</h3><button type="button" class="edit" data-go="1">Edit</button><p class="route">${esc(routeText(trip))}</p>${dl(tripRows(trip))}</div>
    <div class="review-sec"><h3>Your preferences</h3><button type="button" class="edit" data-go="2">Edit</button>${dl(prefRows(trip))}</div>`;
}
form.addEventListener("submit", e => {
  e.preventDefault();
  if (step !== 3) return;
  for (const s of [1, 2]) if (!validateStep(s)) { showStep(s, false); focusFirstInvalid($(`[data-pane="${s}"]`)); return; }
  if (!validateStep(3)) return;
  const btn = $("#pt-submit"), label = btn.innerHTML;
  btn.disabled = true; btn.classList.add("loading"); btn.innerHTML = '<span class="spinner"></span>Posting your trip';
  /* Production: POST /api/trips with an Idempotency-Key; the server re-validates and owns matching. */
  setTimeout(() => {
    const trip = collectTrip();
    const ref = "CD-" + Date.now().toString(36).slice(-6).toUpperCase();
    const saved = { ...trip, ref, postedAt: new Date().toISOString() };
    const trips = store.get("cd.trips", []); trips.unshift(saved); store.set("cd.trips", trips.slice(0, 5));
    btn.disabled = false; btn.classList.remove("loading"); btn.innerHTML = label;
    $("#pt-wizard").hidden = true;
    $("#pt-ref").textContent = "Trip reference " + ref;
    $("#pt-success").hidden = false;
    $("#pt-success").focus({ preventScroll: true });
    const top = $("#widget").getBoundingClientRect().top;
    if (top < 0) $("#widget").scrollIntoView({ block: "start" });
  }, 900);
});
function resetWizard() {
  form.reset();
  $$("#legs [data-leg]").forEach(l => l.remove()); renumberLegs();
  syncTripType();
  $$("[data-f].invalid", form).forEach(w => setErr(w, ""));
  $("#notes-count").textContent = "0 / 500";
  $("#pt-success").hidden = true; $("#pt-wizard").hidden = false;
  showStep(1, false);
}
$("#view-trip").addEventListener("click", () => {
  const t = (store.get("cd.trips", []) || [])[0]; if (!t) return;
  openDialog(`<h2 id="dialog-h">My trip</h2>
    <p class="intro">${esc(t.ref)}, posted ${esc(fmtDate(t.postedAt.slice(0, 10)))}</p>
    <div class="review"><div class="review-sec"><h3>Status</h3><p style="grid-column:1;display:flex;gap:8px;align-items:center;font-weight:600"><span class="spinner" style="color:var(--gold-2);border-width:2.5px"></span>Looking for travellers on your route</p></div>
    <div class="review-sec"><h3>Trip</h3><p class="route">${esc(routeText(t))}</p>${dl(tripRows(t))}</div>
    <div class="review-sec"><h3>Preferences</h3>${dl(prefRows(t))}</div></div>
    <div class="pt-foot"><button class="btn btn-text" type="button" data-close>Close</button><span class="spacer"></span><button class="btn btn-gold" type="button" id="see-route">See travellers on this route</button></div>`, "#see-route");
  $("#see-route").addEventListener("click", () => { closeLayer(); goResults({ from: t.legs[0].from, to: t.legs[0].to, date: t.legs[0].date }); });
});
$("#another").addEventListener("click", () => {
  const t = (store.get("cd.trips", []) || [])[0];
  resetWizard(); setTab("find");
  if (t) { $("#f-from").value = t.legs[0].from; $("#f-to").value = t.legs[0].to; $("#f-date").value = t.legs[0].date; }
  $("#f-from").focus();
});

/* ---------- Contact modal ---------- */
const cForm = $("#contact-form");
function syncMethod() {
  const m = (cForm.querySelector('input[name="cmethod"]:checked') || {}).value;
  $("#c-phone-wrap").hidden = m === "Email";
  $("#c-phone-lbl").textContent = m === "Phone call" ? "Phone number" : "WhatsApp number";
}
$$('input[name="cmethod"]').forEach(r => r.addEventListener("change", syncMethod));
function openContact(topic) {
  if (!$("#contact-done").hidden) { cForm.reset(); $("#contact-done").hidden = true; $("#contact-wrap").hidden = false; syncMethod(); }
  if (topic) $("#c-topic").value = topic;
  openLayer($("#contact"), "#c-name");
}
cForm.addEventListener("submit", e => {
  e.preventDefault();
  const W = n => cForm.querySelector(`[data-f="${n}"]`);
  let ok = true; const chk = (w, cond, m) => { setErr(w, cond ? "" : m); if (!cond) ok = false; };
  const method = cForm.querySelector('input[name="cmethod"]:checked').value;
  chk(W("name"), $("#c-name").value.trim().length >= 2, "Enter your full name.");
  chk(W("email"), EMAIL_RE.test($("#c-email").value.trim()), "Enter an email address like name@example.com.");
  chk(W("topic"), !!$("#c-topic").value, "Choose a topic so the right person replies.");
  if (method !== "Email") chk(W("phone"), phoneOk($("#c-phone").value), "Enter a number with country code, 10 to 15 digits."); else setErr(W("phone"), "");
  chk(W("msg"), $("#c-msg").value.trim().length >= 10, "Add a few more details — at least 10 characters.");
  if (!ok) { focusFirstInvalid(cForm); return; }
  const btn = $("#c-submit"), label = btn.innerHTML;
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>Sending';
  setTimeout(() => {
    btn.disabled = false; btn.innerHTML = label;
    const first = $("#c-name").value.trim().split(/\s+/)[0];
    const how = method === "Email" ? "by email" : method === "Phone call" ? "with a phone call" : "on WhatsApp";
    $("#contact-done-msg").textContent = `Thanks, ${first}. Our team will get back to you ${how}.`;
    $("#contact-wrap").hidden = true; $("#contact-done").hidden = false;
    $("#contact-done [data-close]").focus();
  }, 800);
});

/* ---------- Insurance drawer ---------- */
const iForm = $("#ins-form");
const RATE = { usa: 3.2, canada: 3.0, uk: 2.3, schengen: 2.2, australia: 2.6, uae: 1.6, singapore: 1.8, world: 3.6 };
const ageFactor = a => a < 40 ? 1 : a < 60 ? 1.45 : a < 70 ? 2.2 : a < 80 ? 3.1 : 4;
function openInsurance() {
  $("#ins-step1").hidden = false; $("#ins-step2").hidden = true;
  if (!$("#i-dep").value && $("#p-date").value) $("#i-dep").value = $("#p-date").value;
  if (!$("#i-ret").value && $("#p-ret").value) $("#i-ret").value = $("#p-ret").value;
  openLayer($("#insurance"), "#i-dest");
  $("#insurance").scrollTop = 0;
}
iForm.addEventListener("submit", e => {
  e.preventDefault();
  const W = n => iForm.querySelector(`[data-f="${n}"]`);
  const dep = $("#i-dep").value, ret = $("#i-ret").value, age = $("#i-age").value;
  let ok = true; const chk = (w, m) => { setErr(w, m); if (m) ok = false; };
  chk(W("dep"), !dep ? "Choose a date." : dep < TODAY ? "Choose today or later." : "");
  let retMsg = "";
  if (!ret) retMsg = "Choose a date."; else if (dep && ret < dep) retMsg = "Must be after departure.";
  else if (dep && (parseISO(ret) - parseISO(dep)) / 864e5 > 180) retMsg = "Trips up to 180 days only.";
  chk(W("ret"), retMsg);
  const a = Number(age);
  chk(W("age"), age === "" ? "Enter an age." : (a < 0 || a > 99 || !Number.isInteger(a)) ? "Enter an age from 0 to 99." : a > 85 ? "Over 85? Contact us for a quote." : "");
  if (!ok) { focusFirstInvalid(iForm); return; }
  const days = Math.round((parseISO(ret) - parseISO(dep)) / 864e5) + 1;
  const n = Number($("#i-n").value), dest = $("#i-dest");
  const base = RATE[dest.value] * days * ageFactor(a) * n;
  const senior = a >= 60 || $("#i-for").value === "Parent / elder";
  const plans = [
    { k: "essential", name: "Essential", m: .72, feat: ["Medical emergencies up to $50,000", "Emergency evacuation"] },
    { k: "comprehensive", name: "Comprehensive", m: 1, badge: "Most chosen", feat: ["Medical emergencies up to $100,000", "Missed connections and trip delay", "Lost or delayed baggage"] },
    { k: "plus", name: senior ? "Senior Care" : "Premium", m: 1.45, feat: senior ? ["Medical emergencies up to $250,000", "Built for travellers 60 and over", "Everything in Comprehensive"] : ["Medical emergencies up to $250,000", "Trip cancellation", "Everything in Comprehensive"] }
  ];
  $("#ins-summary").innerHTML = `<span><b>${esc(dest.options[dest.selectedIndex].text)}</b><br><span class="hint">${esc(fmtDate(dep, { day: "numeric", month: "short" }))} – ${esc(fmtDate(ret))}, ${days} days, ${n} traveller${n > 1 ? "s" : ""}</span></span>`;
  $("#ins-plans").innerHTML = plans.map((p, i) => `<label class="plan"><input type="radio" name="plan" value="${p.k}" ${i === 1 ? "checked" : ""}><span class="pn">${esc(p.name)}${p.badge ? `<span class="badge">${esc(p.badge)}</span>` : ""}</span><span class="pp">$${Math.max(12, Math.round(base * p.m))}<small>estimated total</small></span><ul>${p.feat.map(f => `<li>${esc(f)}</li>`).join("")}</ul></label>`).join("");
  $("#ins-step1").hidden = true; $("#ins-step2").hidden = false;
  $("#insurance").scrollTop = 0;
  $("#ins-plans-h").focus();
});
$("#ins-back").addEventListener("click", () => { $("#ins-step2").hidden = true; $("#ins-step1").hidden = false; $("#i-dest").focus(); });
$("#ins-continue").addEventListener("click", () => toast("Partner checkout connects here on the live site."));

/* ---------- Sign in ---------- */
function openSignIn(isUp) {
  openDialog(`<h2 id="dialog-h">${isUp ? "Create your account" : "Welcome back"}</h2>
    <p class="intro">${isUp ? "Post trips, chat with matches and track requests in one place." : "Sign in to see your trips and connection requests."}</p>
    <form id="si-form" class="stack" novalidate><div class="f" data-f="si"><label for="si-email">Email address</label><div class="control">${icon("mail", "i")}<input id="si-email" type="email" autocomplete="email" placeholder="you@example.com"></div><span class="err" hidden></span></div>
    <button class="btn btn-gold btn-block" type="submit">Email me a sign-in link</button></form>
    <p class="lock-note">${icon("lock")}No passwords to remember. The link expires in 15 minutes.</p>`, "#si-email");
  $("#si-form").addEventListener("submit", ev => {
    ev.preventDefault();
    const v = $("#si-email").value.trim();
    if (!EMAIL_RE.test(v)) { setErr($("#si-form [data-f]"), "Enter an email address like name@example.com."); $("#si-email").focus(); return; }
    $("#dialog-body").innerHTML = `<div class="success" style="margin-top:0"><div class="success-mark">${icon("mail", "i")}</div><h2 id="dialog-h" style="padding:0">Check your inbox</h2><p>We've sent a sign-in link to ${esc(v)}.</p><div class="row"><button class="btn btn-navy" type="button" data-close>Done</button></div></div>`;
    $("#dialog-body [data-close]").focus();
  });
}

/* ---------- FAQ ---------- */
$("#faq-grid").addEventListener("click", e => {
  const q = e.target.closest(".faq-q"); if (!q) return;
  const open = q.getAttribute("aria-expanded") !== "true";
  q.setAttribute("aria-expanded", String(open));
  $("#" + q.getAttribute("aria-controls")).classList.toggle("open", open);
});

/* ---------- Newsletter ---------- */
$("#news-form").addEventListener("submit", e => {
  e.preventDefault();
  const v = $("#news-email").value.trim(), msg = $("#news-msg");
  if (!EMAIL_RE.test(v)) { msg.textContent = "Enter a valid email address."; msg.style.color = "#FFC34A"; $("#news-email").focus(); return; }
  msg.style.color = ""; msg.textContent = "You're subscribed. Updates will arrive at " + v + ".";
  $("#news-email").value = "";
});

syncTripType();
route();
})();
