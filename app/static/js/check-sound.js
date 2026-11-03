/* The half-hour sound (services/check_sound.py, templates/_check_sound.html). At the start of every half hour (India
   time) it rings on whatever staff page is open -- only while it is on, in the person's hours and days -- with a note
   at the bottom of the page and, when chosen, a desktop notice; a few minutes later it rings again when the inboxes
   are not all ticked (data-now). One ring per half hour however many tabs are open. The sounds are made here (Web
   Audio); "My own sound" is a file kept in this browser (IndexedDB), never uploaded. Browsers play sound only after
   a click on the page: until then the note shows and, when the page cannot play, the desktop notice comes anyway.
   Every half hour it also tells the page ('crm:half-hour'), so the half-hourly check draws itself again after the
   sound. The settings window saves to data-save. */
(function () {
  'use strict';
  var script = document.currentScript;
  if (!script || window.self !== window.top) return;
  var cfg = {};
  try { cfg = JSON.parse(script.dataset.cfg || '{}'); } catch (e) { return; }
  var SAVE = script.dataset.save, NOW = script.dataset.now, CHECK = script.dataset.check;
  var CSRF = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
  var HALF = 1800000, IST = 19800000;          // India is UTC+5:30, so its half hours start with UTC's

  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function slotStart(t) { return Math.floor(t / HALF) * HALF; }
  function hm(t) { var d = new Date(t + IST); return pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes()); }
  function mins(s) { var p = String(s || '').split(':'); return (+p[0] || 0) * 60 + (+p[1] || 0); }
  function get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private window */ } }

  /* does the half hour starting at t ring with settings s? (the day is the half hour's own, in India) */
  function rings(s, t) {
    if (!s.on) return false;
    var d = new Date(t + IST), wd = (d.getUTCDay() + 6) % 7;            // Monday is 0
    if ((s.days || []).indexOf(wd) < 0) return false;
    if (s.all_day) return true;
    var at = d.getUTCHours() * 60 + d.getUTCMinutes(), a = mins(s.from), b = mins(s.to);
    return a < b ? at >= a && at < b : at >= a || at < b;               // from 22:00 to 06:00 goes past midnight
  }

  /* -------------------------------------------------------------- the sounds */
  var ctx = null;
  function audio() {
    if (!ctx) {
      var AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return null;
      ctx = new AC();
    }
    return ctx;
  }
  // a click or a key on the page lets the browser play sound on it
  function unlock() { var c = audio(); if (c && c.state === 'suspended') c.resume(); }
  ['pointerdown', 'keydown'].forEach(function (ev) { document.addEventListener(ev, unlock, { capture: true, passive: true }); });

  function playable(c) {
    if (c.state === 'running') return Promise.resolve(true);
    // without a click the promise may never settle: give it a moment
    return Promise.race([c.resume().catch(function () {}), new Promise(function (r) { setTimeout(r, 300); })])
      .then(function () { return c.state === 'running'; });
  }

  function tone(c, out, f, at, len, type, peak) {
    var o = c.createOscillator(), g = c.createGain();
    o.type = type || 'sine';
    o.frequency.setValueAtTime(f, at);
    g.gain.setValueAtTime(0.0001, at);
    g.gain.exponentialRampToValueAtTime(peak || 0.5, at + 0.012);
    g.gain.exponentialRampToValueAtTime(0.0001, at + len);
    o.connect(g); g.connect(out);
    o.start(at); o.stop(at + len + 0.05);
  }
  function blip(c, out, at) {                  // a short rising drop
    var o = c.createOscillator(), g = c.createGain();
    o.frequency.setValueAtTime(380, at);
    o.frequency.exponentialRampToValueAtTime(920, at + 0.09);
    g.gain.setValueAtTime(0.0001, at);
    g.gain.exponentialRampToValueAtTime(0.6, at + 0.01);
    g.gain.exponentialRampToValueAtTime(0.0001, at + 0.16);
    o.connect(g); g.connect(out);
    o.start(at); o.stop(at + 0.2);
  }
  var SYNTH = {
    chime: function (c, o, t) { tone(c, o, 1318.5, t, 1.1); tone(c, o, 1046.5, t + 0.28, 1.6); },
    bell: function (c, o, t) {
      [[880, 0.5, 2.6], [1760, 0.2, 1.6], [2426, 0.14, 1.2], [3530, 0.06, 0.8]].forEach(function (p) {
        tone(c, o, p[0], t, p[2], 'sine', p[1]);
      });
    },
    dingdong: function (c, o, t) { tone(c, o, 784, t, 1.1, 'triangle', 0.6); tone(c, o, 622.3, t + 0.55, 1.5, 'triangle', 0.6); },
    marimba: function (c, o, t) {
      [523.3, 659.3, 784, 1046.5].forEach(function (f, i) { tone(c, o, f, t + i * 0.13, 0.5, 'sine', 0.55); });
    },
    pop: function (c, o, t) { blip(c, o, t); blip(c, o, t + 0.18); },
    alarm: function (c, o, t) {
      for (var i = 0; i < 6; i++) tone(c, o, i % 2 ? 1046.5 : 880, t + i * 0.22, 0.18, 'square', 0.3);
    }
  };

  /* my own sound: one file in this browser */
  var DB = 'crm-sound', STORE = 'files', ownBuf = null;
  function idb() {
    return new Promise(function (ok, no) {
      if (!window.indexedDB) { no(); return; }
      var r = indexedDB.open(DB, 1);
      r.onupgradeneeded = function () { r.result.createObjectStore(STORE); };
      r.onsuccess = function () { ok(r.result); };
      r.onerror = function () { no(r.error); };
    });
  }
  function ownGet() {
    return idb().then(function (db) {
      return new Promise(function (ok) {
        var q = db.transaction(STORE).objectStore(STORE).get('own');
        q.onsuccess = function () { ok(q.result || null); };
        q.onerror = function () { ok(null); };
      });
    }).catch(function () { return null; });
  }
  function ownPut(rec) {
    return idb().then(function (db) {
      return new Promise(function (ok, no) {
        var tx = db.transaction(STORE, 'readwrite');
        tx.objectStore(STORE).put(rec, 'own');
        tx.oncomplete = ok;
        tx.onerror = function () { no(tx.error); };
      });
    });
  }
  function decode(c, blob) {
    return blob.arrayBuffer().then(function (buf) {
      return new Promise(function (ok, no) { c.decodeAudioData(buf, ok, no); });
    });
  }
  function ownBuffer(c) {
    if (ownBuf) return Promise.resolve(ownBuf);
    return ownGet().then(function (rec) {
      return rec && rec.blob ? decode(c, rec.blob).then(function (b) { ownBuf = b; return b; }) : null;
    }).catch(function () { return null; });
  }

  /* play a sound at a loudness (5-100): true once it plays, false when the page may not play sound yet */
  function play(sound, volume) {
    var c = audio();
    if (!c) return Promise.resolve(false);
    return playable(c).then(function (ok) {
      if (!ok) return false;
      var out = c.createGain();
      out.gain.value = Math.max(0.05, (+volume || 70) / 100);
      out.connect(c.destination);
      var t = c.currentTime + 0.03;
      if (sound !== 'own') { (SYNTH[sound] || SYNTH.chime)(c, out, t); return true; }
      return ownBuffer(c).then(function (buf) {
        if (!buf) { SYNTH.chime(c, out, t); return true; }       // chosen on another computer: the chime here
        var s = c.createBufferSource();
        s.buffer = buf; s.connect(out); s.start(t); s.stop(t + 10);
        return true;
      });
    });
  }

  /* -------------------------------------------------------------- ringing */
  var note = null, flashing = null, title = document.title;
  function showNote(when, again, played) {
    if (note) note.remove();
    note = document.createElement('div');
    note.className = 'snd-toast';
    note.setAttribute('role', 'status');
    note.innerHTML = '<span class="snd-toast-i" aria-hidden="true"><i class="fa-solid fa-bell"></i></span><div><b></b><span></span></div>' +
      '<a class="snd-btn primary" href="">Open the check</a><button type="button" class="snd-x" aria-label="Close"><i class="fa-solid fa-xmark" aria-hidden="true"></i></button>';
    note.querySelector('b').textContent = when + ' · ' + (again ? 'Inboxes not all ticked yet' : 'Time for the half-hourly check');
    note.querySelector('span:not(.snd-toast-i)').textContent = played ? 'Look at each inbox and tick it.'
      : 'Click anywhere on the page once, and the sound plays here next time.';
    note.querySelector('a').href = CHECK;
    note.querySelector('button').addEventListener('click', function () { note.remove(); note = null; });
    document.body.appendChild(note);
    var mine = note;
    setTimeout(function () { if (note === mine) { note.remove(); note = null; } }, 5 * 60000);
  }
  function flash(when) {
    if (!document.hidden || flashing) return;
    var on = false;
    flashing = setInterval(function () { on = !on; document.title = on ? '🔔 ' + when + ' Check the inboxes' : title; }, 1000);
  }
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden && flashing) { clearInterval(flashing); flashing = null; document.title = title; }
  });
  function desktop(when, again) {
    if (!window.Notification || Notification.permission !== 'granted') return;
    var n = new Notification('Half-hourly check · ' + when, {
      body: again ? 'The inboxes are not all ticked yet.' : 'A new half hour: look at each inbox and tick it.',
      tag: 'crm-check-sound'
    });
    n.onclick = function () { window.focus(); location.href = CHECK; };
  }
  function ring(t, again) {
    var when = hm(t);
    play(cfg.sound, cfg.volume).then(function (played) {
      showNote(when, again, played);
      if (cfg.notice || !played) desktop(when, again);
    });
    flash(when);
  }

  /* once per half hour in this browser, whatever the tabs: the first to take it rings */
  function once(what, key, fn) {
    var k = 'crm-sound-' + what;
    var take = function () { if (get(k) !== key) { set(k, key); fn(); } };
    if (navigator.locks && navigator.locks.request) navigator.locks.request(k, take);
    else setTimeout(take, Math.random() * 400);
  }

  function planAgain(s) {
    if (!cfg.again || !NOW) return;
    var wait = s + cfg.again * 60000 - Date.now();
    if (wait < -60000) return;
    setTimeout(function () {
      if (!rings(cfg, s) || slotStart(Date.now()) !== s) return;
      fetch(NOW, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) { if (d && d.done === false) once('again', String(s), function () { ring(s, true); }); })
        .catch(function () { /* offline */ });
    }, Math.max(0, wait));
  }

  var seen = slotStart(Date.now());
  function tick() {
    var now = Date.now(), s = slotStart(now);
    if (s === seen) return;
    seen = s;
    document.dispatchEvent(new CustomEvent('crm:half-hour', { detail: { at: s } }));
    // a computer waking up long after the half hour began does not ring for it
    if (now - s < 5 * 60000 && rings(cfg, s)) once('rung', String(s), function () { ring(s, false); });
    planAgain(s);
  }
  (function arm() {
    var now = Date.now();
    setTimeout(function () { tick(); arm(); }, slotStart(now) + HALF - now + 250);
  })();
  setInterval(tick, 20000);                 // a tab in the background has its timers held back: this catches up
  // a page opened just as the half hour began (somebody moving between pages) rings for it, unless another did
  if (Date.now() - seen < 60000 && rings(cfg, seen)) once('rung', String(seen), function () { ring(seen, false); });
  planAgain(seen);

  /* -------------------------------------------------------------- the settings window */
  var dlg = document.getElementById('sndDialog');
  var form = dlg && dlg.querySelector('[data-snd-form]');
  if (!form) return;
  var el = form.elements;

  function read() {
    return {
      on: el.snd_on.checked, all_day: (form.querySelector('[name=snd_all_day]:checked') || {}).value !== '0',
      from: el.snd_from.value, to: el.snd_to.value,
      days: [].map.call(form.querySelectorAll('[name=snd_days]:checked'), function (x) { return +x.value; }),
      sound: (form.querySelector('[name=snd_sound]:checked') || {}).value || 'chime',
      volume: +el.snd_volume.value, again: +el.snd_again.value, notice: el.snd_notice.checked
    };
  }
  function fill(s) {
    el.snd_on.checked = !!s.on;
    form.querySelector('[name=snd_all_day][value="' + (s.all_day ? '1' : '0') + '"]').checked = true;
    el.snd_from.value = s.from; el.snd_to.value = s.to;
    form.querySelectorAll('[name=snd_days]').forEach(function (x) { x.checked = (s.days || []).indexOf(+x.value) >= 0; });
    var pick = form.querySelector('[name=snd_sound][value="' + s.sound + '"]');
    if (pick) pick.checked = true;
    el.snd_volume.value = s.volume; el.snd_again.value = String(s.again); el.snd_notice.checked = !!s.notice;
  }
  var DAY = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  function next() {
    var s = read(), out = form.querySelector('[data-snd-next]');
    form.querySelector('[data-snd-body]').classList.toggle('off', !s.on);
    if (!s.on) { out.textContent = 'Off: no sound.'; return; }
    var now = Date.now(), t = slotStart(now) + HALF;
    for (var i = 0; i < 48 * 8; i++, t += HALF) {
      if (rings(s, t)) {
        var d = new Date(t + IST), today = new Date(now + IST);
        var day = d.getUTCDate() === today.getUTCDate() ? 'today' : DAY[d.getUTCDay()];
        out.textContent = 'Next sound: ' + day + ' at ' + hm(t) + ' (India time).';
        return;
      }
    }
    out.textContent = 'These hours and days never ring.';
  }
  function err(text) { var e = form.querySelector('[data-snd-err]'); e.textContent = text || ''; e.hidden = !text; }
  function ownName() {
    var out = form.querySelector('[data-snd-own-name]');
    ownGet().then(function (rec) { out.textContent = rec ? rec.name : 'No file chosen on this computer'; });
  }
  function says(text, on) {
    document.querySelectorAll('[data-sound-open]').forEach(function (b) {
      b.classList.toggle('off', !on);
      b.classList.toggle('on', !!on);
      if (b.hasAttribute('title')) b.title = 'Half-hour sound: ' + text;
      if (b.hasAttribute('aria-label')) b.setAttribute('aria-label', 'Half-hour sound: ' + text);
      var i = b.querySelector('i');
      if (i) i.className = 'fa-solid ' + (on ? 'fa-volume-high' : 'fa-volume-xmark');
      var w = b.querySelector('[data-sound-says]');
      if (w) w.textContent = text;
    });
  }

  document.addEventListener('click', function (e) {
    if (!e.target.closest('[data-sound-open]')) return;
    e.preventDefault();
    fill(cfg); err(''); next(); ownName();
    dlg.showModal();
  });
  form.querySelectorAll('[data-snd-close]').forEach(function (b) { b.addEventListener('click', function () { dlg.close(); }); });
  form.addEventListener('change', next);
  form.addEventListener('click', function (e) {
    var b = e.target.closest('[data-snd-play]');
    if (b) {
      if (b.dataset.sndPlay === 'own') {
        ownGet().then(function (rec) {
          if (!rec) { form.querySelector('[data-snd-file]').click(); return; }
          play('own', el.snd_volume.value);
        });
      } else play(b.dataset.sndPlay, el.snd_volume.value);
      return;
    }
    if (e.target.closest('[data-snd-test]')) play(read().sound, el.snd_volume.value);
    if (e.target.closest('[data-snd-choose]')) form.querySelector('[data-snd-file]').click();
  });
  form.querySelector('[data-snd-file]').addEventListener('change', function () {
    var f = this.files && this.files[0];
    this.value = '';
    if (!f) return;
    if (f.size > 1048576) { err('That file is over 1 MB: choose a shorter sound.'); return; }
    var c = audio();
    if (!c) { err('This browser cannot play sounds.'); return; }
    decode(c, f).then(function (buf) {
      return ownPut({ name: f.name, blob: f }).then(function () {
        ownBuf = buf; err('');
        form.querySelector('[name=snd_sound][value=own]').checked = true;
        ownName(); next();
        play('own', el.snd_volume.value);
      });
    }).catch(function () { err('That file is not a sound this browser can play: try an MP3.'); });
  });
  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var s = read();
    if (s.notice && window.Notification && Notification.permission === 'default') Notification.requestPermission();
    fetch(SAVE, {
      method: 'POST', credentials: 'same-origin', body: JSON.stringify(s),
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF, Accept: 'application/json' }
    }).then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (x) {
        if (!x.ok) { err(x.d.error || 'Could not save.'); return; }
        cfg = x.d.settings;
        says(x.d.says, cfg.on);
        dlg.close();
        if (cfg.on) planAgain(slotStart(Date.now()));
      })
      .catch(function () { err('Could not save: are you online?'); });
  });
})();
