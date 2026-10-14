/* Sales CRM screens (/cs/crm). One file, delegated handlers, no framework.

   Every button does the whole job in one click: "Send on WhatsApp" opens WhatsApp with the message
   typed (or sends it, once the WhatsApp CRM is connected), logs it, ticks the step off and plans the
   next one. The server decides all of that; this only collects what was clicked and shows the result. */
(function () {
  'use strict';
  var root = document.querySelector('[data-crm]');
  if (!root) return;
  var BASE = (root.dataset.crm || '/cs/crm/').replace(/\/?$/, '/');
  var WA_READY = root.dataset.wa === '1';
  var csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
  var dialog = document.getElementById('crm-dialog');

  function post(path, body) {
    return fetch(BASE + path, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf, 'Accept': 'application/json' },
      body: JSON.stringify(body || {})
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) { d._ok = r.ok; return d; });
    }).catch(function () { return { _ok: false, error: 'No connection. Please try again.' }; });
  }

  function toast(msg, bad, action) {
    document.querySelectorAll('.crm-toast').forEach(function (x) { x.remove(); });
    var t = document.createElement('div');
    t.className = 'crm-toast' + (bad ? ' bad' : '');
    var span = document.createElement('span');
    span.textContent = msg;
    t.appendChild(span);
    if (action) {
      var b = document.createElement('button');
      b.type = 'button';
      b.textContent = action.label;
      b.addEventListener('click', function () { t.remove(); action.run(); });
      t.appendChild(b);
    }
    document.body.appendChild(t);
    setTimeout(function () { t.remove(); }, action ? 8000 : (bad ? 5000 : 2600));
  }

  // every move can be taken back for a few seconds: a wrong drop is one click to undo
  function undoMove(leadId, el) {
    post('lead/' + leadId + '/undo', {}).then(function (d) {
      if (!d._ok) { toast(d.error || 'Could not undo.', true); return; }
      toast('Back in ' + d.stage);
      reloadFor(el, 700);
    });
  }

  function reloadSoon(ms) { setTimeout(function () { location.reload(); }, ms || 600); }

  // the lead card in the panel beside the WhatsApp inbox reloads itself, not the page (which would
  // reload the inbox too); on the lead page and everywhere else the page reloads
  function reloadFor(el, ms) {
    var panel = el && el.closest && el.closest('[data-lead-panel]');
    if (panel && window.CRM_reloadPanel) { setTimeout(window.CRM_reloadPanel, ms || 400); return; }
    reloadSoon(ms);
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function waLink(phone, text) {
    var digits = String(phone || '').replace(/\D/g, '');
    return digits ? 'https://wa.me/' + digits + '?text=' + encodeURIComponent(text || '') : '';
  }

  /* A small chooser in the shared <dialog>: a title, a line, and buttons. Resolves with the value
     clicked, or null when closed. */
  function choose(title, line, options, extra) {
    return new Promise(function (resolve) {
      var box = dialog.querySelector('.in');
      box.innerHTML = '<h3>' + esc(title) + '</h3>' + (line ? '<p class="muted" style="margin:0">' + esc(line) + '</p>' : '') +
        '<div class="chips">' + options.map(function (o, i) {
          return '<button type="button" class="chip" data-i="' + i + '">' + esc(o.label) + '</button>';
        }).join('') + '</div>' + (extra || '') +
        '<div class="row end"><button type="button" class="cb ghost sm" data-close>Cancel</button></div>';
      var done = false;
      function finish(v) { if (done) return; done = true; dialog.close(); resolve(v); }
      box.querySelectorAll('[data-i]').forEach(function (b) {
        b.addEventListener('click', function () { finish(options[+b.dataset.i].value); });
      });
      box.querySelector('[data-close]').addEventListener('click', function () { finish(null); });
      dialog.addEventListener('close', function once() { dialog.removeEventListener('close', once); finish(null); });
      dialog.showModal();
    });
  }

  function reasonsFrom(el) {
    try { return JSON.parse(el.dataset.reasons || '[]'); } catch (e) { return []; }
  }

  /* Moving a lead. A finish line asks once: won to confirm, lost for why (the pipeline's buttons). */
  function moveLead(leadId, stage, reasonsSource) {
    var kind = stage.dataset.kind, name = stage.dataset.name;
    var ask = Promise.resolve('');
    if (kind === 'lost') {
      var reasons = reasonsFrom(reasonsSource);
      if (!reasons.length) reasons = ['No response', 'Not interested'];
      ask = choose('Why did they fall out?', 'Moving to "' + name + '".',
        reasons.map(function (r) { return { label: r, value: r }; }));
    } else if (kind === 'won') {
      ask = choose('Mark as won?', 'Moving to "' + name + '". Well done!', [{ label: 'Yes, won', value: 'won' }]);
    }
    return ask.then(function (reason) {
      if (reason === null) return null;
      return post('lead/' + leadId + '/move', { stage_id: +stage.dataset.stage, reason: kind === 'lost' ? reason : '' });
    }).then(function (d) {
      if (d === null) return null;
      if (!d._ok) { toast(d.error || 'Could not move it.', true); return null; }
      toast(d.status === 'won' ? 'Won! 🎉 Moved to ' + d.stage : 'Moved to ' + d.stage, false,
            { label: 'Undo', run: function () { undoMove(leadId, reasonsSource); } });
      return d;
    });
  }

  /* -------------------------------------------------------------- sending */
  // A step's message: the server decides how it goes -- its approved WhatsApp template, free text
  // inside the 24 hours after they last wrote, or the agent's own WhatsApp -- and says which.
  function sendMessage(leadId, text, taskId, phone, via, answerId) {
    text = (text || '').trim();
    if (!text && !taskId) { toast('Write the message first.', true); return Promise.resolve(null); }
    if (via && via !== 'whatsapp') {
      return post('lead/' + leadId + '/send', { text: text, task_id: taskId || null, via: via, answer_id: answerId || null }).then(function (d) {
        if (!d._ok) { toast(d.error || 'Could not send.', true); return null; }
        toast(via === 'instagram' ? 'Sent on Instagram' : 'Sent on Messenger');
        return d;
      });
    }
    // Opened here, inside the click, so the browser does not block it as a pop-up
    var opened = false;
    if (!WA_READY) {
      var link = waLink(phone, text);
      if (link) { window.open(link, '_blank', 'noopener'); opened = true; }
    }
    return post('lead/' + leadId + '/send', { text: text, task_id: taskId || null, answer_id: answerId || null }).then(function (d) {
      if (!d._ok) { toast(d.error || 'Could not send.', true); return null; }
      if (d.mode === 'sent') toast(d.via === 'template' ? 'Sent on WhatsApp (template)' : 'Sent on WhatsApp');
      else {
        if (!opened && d.url) window.open(d.url, '_blank', 'noopener');
        toast(d.reason || (d.warning ? 'Not sent automatically — WhatsApp opened instead' : 'WhatsApp opened — press send there'),
              !!(d.reason || d.warning));
      }
      return d;
    });
  }

  function taskAction(taskId, action, extra) {
    return post('task/' + taskId + '/' + action, extra || {}).then(function (d) {
      if (!d._ok) { toast(d.error || 'That did not work.', true); return null; }
      toast(action === 'snooze' ? 'Moved to tomorrow' : action === 'skip' ? 'Skipped' : 'Done ✓' +
        (d.next ? ' — next: ' + d.next.code : ''));
      return d;
    });
  }

  function logCall(leadId, outcome, taskId) {
    return post('lead/' + leadId + '/call', { outcome: outcome, task_id: taskId || null }).then(function (d) {
      if (!d._ok) { toast(d.error || 'Could not save the call.', true); return null; }
      toast('Call saved');
      return d;
    });
  }

  var OUTCOMES = [
    { label: 'Talked', value: 'connected' }, { label: 'No answer', value: 'no_answer' },
    { label: 'Busy', value: 'busy' }, { label: 'Asked us to call back', value: 'call_back' },
    { label: 'Switched off', value: 'switched_off' }, { label: 'Wrong number', value: 'wrong_number' }];

  function afterCall(d, leadPage) {
    if (!d) return;
    if (d.suggest_fallout && leadPage) {
      var reasonsSource = leadPage;
      var lost = leadPage.querySelector('[data-journey] [data-kind="lost"]');
      if (lost) {
        choose(d.no_answers + ' calls in a row with no answer', 'Move them to "' + lost.dataset.name + '"?',
          [{ label: 'Yes, they fell out', value: 'yes' }, { label: 'Keep trying', value: 'no' }])
          .then(function (v) {
            if (v === 'yes') {
              var reasons = reasonsFrom(reasonsSource);
              var reason = reasons.find(function (r) { return /respon|answer/i.test(r); }) || reasons[0] || 'No response';
              return post('lead/' + leadPage.dataset.lead + '/move', { stage_id: +lost.dataset.stage, reason: reason });
            }
          }).then(function () { reloadFor(leadPage, 200); });
        return;
      }
    }
    reloadFor(leadPage);
  }

  /* -------------------------------------------------------------- the to-do list */
  function taskCard(el) { return el.closest('[data-task]'); }

  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-act]');
    if (!b || !root.contains(b)) return;
    var act = b.dataset.act;
    var card = b.closest('.crm-task');
    var leadPage = b.closest('[data-lead-page]');

    if (card) {
      var tid = card.dataset.task, lid = card.dataset.lead;
      if (act === 'send') {
        e.preventDefault();
        b.disabled = true;
        sendMessage(lid, b.dataset.text, tid, b.dataset.phone).then(function (d) {
          b.disabled = false;
          if (d) card.classList.add('gone');
        });
      } else if (act === 'done' || act === 'snooze') {
        taskAction(tid, act).then(function (d) { if (d) card.classList.add('gone'); });
      } else if (act === 'dial') {
        // let the tel: link ring, then ask how it went
        setTimeout(function () {
          choose('How did the call go?', '', OUTCOMES).then(function (v) {
            if (!v) return;
            logCall(lid, v, tid).then(function (d) { if (d) card.classList.add('gone'); });
          });
        }, 400);
      } else if (act === 'done-after') {
        setTimeout(function () { taskAction(tid, 'done').then(function (d) { if (d) card.classList.add('gone'); }); }, 400);
      }
      return;
    }

    if (leadPage) {
      var leadId = leadPage.dataset.lead;
      var phone = leadPage.dataset.phone || '';
      var q = function (sel) { return leadPage.querySelector(sel); };
      if (act === 'send-next') {
        var next = q('[data-next]');
        var edited = q('[data-next-text]');
        b.disabled = true;
        // the words as they will go: what the agent changed, else the step's own (the button carries
        // them for the "open your WhatsApp" case, which has to open inside this click)
        sendMessage(leadId, edited && !edited.closest('[hidden]') ? edited.value : (b.dataset.text || ''),
                    next && next.dataset.task, phone, b.dataset.via)
          .then(function (d) { b.disabled = false; if (d) reloadFor(leadPage, 900); });
      } else if (act === 'edit-next') {
        var box = q('[data-next-edit]');
        if (box) { box.hidden = !box.hidden; if (!box.hidden) box.querySelector('textarea').focus(); }
      } else if (act === 'done' || act === 'snooze' || act === 'skip') {
        taskAction(b.dataset.task, act).then(function (d) { if (d) reloadFor(leadPage); });
      } else if (act === 'mail') {
        var nx = q('[data-next]');
        var body = (q('[data-next-text]') || {}).value || b.dataset.text || '';
        b.href = b.href.split('?')[0] + '?body=' + encodeURIComponent(body);
        if (nx) setTimeout(function () { taskAction(nx.dataset.task, 'done').then(function (d) { if (d) reloadFor(leadPage); }); }, 400);
      } else if (act === 'note') {
        var text = q('[data-note-text]').value.trim();
        if (!text) { toast('Write something first.', true); return; }
        post('lead/' + leadId + '/note', {
          text: text, channel: q('[data-note-ch]').value,
          from_them: q('[data-note-in]').checked
        }).then(function (d) {
          if (!d._ok) { toast(d.error || 'Could not save.', true); return; }
          toast('Saved'); reloadFor(leadPage);
        });
      } else if (act === 'undo') {
        undoMove(leadId, leadPage);
      } else if (act === 'reopen') {
        post('lead/' + leadId + '/reopen', {}).then(function (d) {
          if (!d._ok) { toast(d.error || 'Could not reopen.', true); return; }
          toast('Reopened — back in ' + d.stage); reloadFor(leadPage);
        });
      } else if (act === 'remove') {
        choose('Take ' + (b.dataset.name || 'this lead') + ' out of the Sales CRM?',
               'Their follow-ups and history in the CRM go too. The record on the site (their quote, booking or post) stays.',
               [{ label: 'Yes, remove', value: 'yes' }]).then(function (v) {
          if (v !== 'yes') return;
          post('lead/' + leadId + '/remove', {}).then(function (d) {
            if (!d._ok) { toast(d.error || 'Could not remove.', true); return; }
            location.href = d.next;
          });
        });
      } else if (act === 'edit-person') {
        var box = dialog.querySelector('.in');
        box.innerHTML = '<h3>Their details</h3><div class="stack" style="margin-top:10px">' +
          '<div><label class="lb">Name</label><input type="text" id="crm-e-name" maxlength="120" value="' + esc(b.dataset.name) + '"/></div>' +
          '<div><label class="lb">E-mail</label><input type="email" id="crm-e-email" maxlength="255" value="' + esc(b.dataset.email) + '"/></div>' +
          '<div><label class="lb">Phone / WhatsApp <small class="muted">with the country code, e.g. +91 98480 00000</small></label><input type="text" id="crm-e-phone" maxlength="24" value="' + esc(b.dataset.phone) + '"/></div>' +
          (b.dataset.instagram ? '' : '<div><label class="lb">Instagram</label><input type="text" id="crm-e-ig" maxlength="200" placeholder="@their.handle"/></div>') +
          (b.dataset.facebook ? '' : '<div><label class="lb">Facebook</label><input type="text" id="crm-e-fb" maxlength="200" placeholder="facebook.com/…"/></div>') +
          '<div class="row end"><button type="button" class="cb ghost" data-close>Cancel</button><button type="button" class="cb primary" data-save>Save</button></div></div>';
        box.querySelector('[data-close]').onclick = function () { dialog.close(); };
        box.querySelector('[data-save]').onclick = function () {
          var val = function (id) { var el = document.getElementById(id); return el ? el.value : ''; };
          var body = { name: val('crm-e-name'), email: val('crm-e-email'), instagram: val('crm-e-ig'), facebook: val('crm-e-fb') };
          if (val('crm-e-phone').trim() && val('crm-e-phone').trim() !== (b.dataset.phone || '')) body.phone = val('crm-e-phone');
          post('lead/' + leadId + '/update', body)
            .then(function (d) { if (!d._ok) { toast(d.error || 'Could not save.', true); return; } dialog.close(); toast('Saved'); reloadFor(leadPage); });
        };
        dialog.showModal();
      }
    }
  });

  /* -------------------------------------------------------------- the lead card's own controls */
  // Bound once per card: on the lead page at load, and in the panel beside the WhatsApp inbox
  // every time a conversation's lead is loaded into it (window.CRM_bindLead).
  function bindLead(leadPage) {
    var leadId = leadPage.dataset.lead;

    leadPage.querySelectorAll('[data-journey] button').forEach(function (btn) {
      btn.addEventListener('click', function () {
        if (btn.classList.contains('now')) return;
        moveLead(leadId, btn, leadPage).then(function (d) { if (d) reloadFor(leadPage, 2200); });
      });
    });

    leadPage.querySelectorAll('[data-update]').forEach(function (el) {
      el.addEventListener('change', function () {
        var body = {}; body[el.dataset.update] = el.value;
        post('lead/' + leadId + '/update', body).then(function (d) {
          if (!d._ok) toast(d.error || 'Could not save.', true);
          else {
            toast(el.dataset.update === 'owner_id' ? 'Saved — their WhatsApp chat goes to them too' : 'Saved');
            if (el.dataset.update === 'departure_date') reloadFor(leadPage);
          }
        });
      });
    });

    leadPage.querySelectorAll('[data-temps] [data-temp]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var on = btn.classList.contains('on');
        post('lead/' + leadId + '/update', { temperature: on ? '' : btn.dataset.temp }).then(function (d) {
          if (!d._ok) { toast(d.error || 'Could not save.', true); return; }
          leadPage.querySelectorAll('[data-temps] [data-temp]').forEach(function (x) { x.classList.remove('on'); });
          if (!on) btn.classList.add('on');
        });
      });
    });

    leadPage.querySelectorAll('[data-call-outcomes]').forEach(function (group) {
      group.addEventListener('click', function (e) {
        var c = e.target.closest('[data-outcome]');
        if (!c) return;
        group.querySelectorAll('[data-outcome]').forEach(function (x) { x.disabled = true; });
        logCall(leadId, c.dataset.outcome, group.dataset.task || null).then(function (d) { afterCall(d, leadPage); });
      });
    });

    // Quote sent / Payment link sent
    leadPage.addEventListener('click', function (e) {
      var b = e.target.closest('[data-act="event"]');
      if (!b) return;
      b.disabled = true;
      post('lead/' + leadId + '/event', { code: b.dataset.code }).then(function (d) {
        if (!d._ok) { b.disabled = false; toast(d.error || 'Could not save.', true); return; }
        toast(d.stage ? 'Saved — moved to ' + d.stage : 'Saved');
        reloadFor(leadPage);
      });
    });
    // ready to buy?
    leadPage.querySelectorAll('[data-likelihood] [data-lk]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var on = btn.classList.contains('on');
        post('lead/' + leadId + '/update', { likelihood: on ? '' : btn.dataset.lk }).then(function (d) {
          if (!d._ok) { toast(d.error || 'Could not save.', true); return; }
          leadPage.querySelectorAll('[data-likelihood] [data-lk]').forEach(function (x) { x.classList.remove('on'); });
          if (!on) btn.classList.add('on');
        });
      });
    });
  }
  window.CRM_bindLead = bindLead;
  document.querySelectorAll('[data-lead-page]').forEach(bindLead);

  /* -------------------------------------------------------------- suggested answers */
  var asked = document.querySelector('[data-asked], [data-try-answers]');
  if (asked) {
    var q = asked.querySelector('#crm-q');
    var list = asked.querySelector('[data-sugg]');
    var reply = document.getElementById('crm-reply');
    var timer = null, lastQ = q.value;

    function render(items) {
      if (!items.length) {
        list.innerHTML = '<div class="none">' + (q.value.trim() ? 'No ready answer for that yet — write your own' +
          (asked.hasAttribute('data-try-answers') ? ', or add one below.' : '.') : 'Type their question above and the best ready answers appear here.') + '</div>';
        return;
      }
      list.innerHTML = items.map(function (s) {
        return '<div class="s" data-id="' + esc(s.id) + '"><div class="t"><span>' + esc(s.title) + '</span>' +
          (s.kind === 'faq' ? '<span class="chip">Help page</span>' : '') + '</div><div class="b">' + esc(s.body) + '</div>' +
          (reply ? '<button type="button" class="cb sm primary" data-use>Use this answer</button>' : '') + '</div>';
      }).join('');
    }

    function lookup() {
      var text = q.value.trim();
      if (text === lastQ.trim()) return;
      lastQ = text;
      if (!text) { render([]); return; }
      var url = BASE + 'suggest?q=' + encodeURIComponent(text);
      fetch(url, { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
        .then(function (r) { return r.json(); })
        .then(function (d) { if (q.value.trim() === text) render(d.suggestions || []); })
        .catch(function () {});
    }

    q.addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(lookup, 300); });

    list.addEventListener('click', function (e) {
      var s = e.target.closest('.s');
      if (!s) return;
      if (e.target.closest('[data-use]') && reply) {
        reply.value = s.querySelector('.b').textContent;
        reply.focus();
        reply.scrollIntoView({ behavior: 'smooth', block: 'center' });
        post('answer/' + encodeURIComponent(s.dataset.id) + '/used', {});
      } else {
        s.classList.toggle('open');
      }
    });
  }

  /* -------------------------------------------------------------- the board */
  var board = document.querySelector('[data-board]');
  if (board) {
    var dragging = null, moved = false;
    board.addEventListener('dragstart', function (e) {
      var c = e.target.closest('.crm-card');
      if (!c) return;
      dragging = c; moved = false;
      c.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', c.dataset.lead);
    });
    board.addEventListener('dragend', function () {
      if (dragging) dragging.classList.remove('dragging');
      board.querySelectorAll('.drop.over').forEach(function (d) { d.classList.remove('over'); });
      dragging = null;
    });
    board.addEventListener('dragover', function (e) {
      var d = e.target.closest('[data-drop]');
      if (!d || !dragging) return;
      e.preventDefault();
      board.querySelectorAll('.drop.over').forEach(function (x) { if (x !== d) x.classList.remove('over'); });
      d.classList.add('over');
    });
    board.addEventListener('drop', function (e) {
      var d = e.target.closest('[data-drop]');
      if (!d || !dragging) return;
      e.preventDefault();
      d.classList.remove('over');
      var card = dragging;
      if (card.parentElement === d) return;
      moved = true;
      moveLead(card.dataset.lead, d, board).then(function (res) {
        if (!res) return;
        d.insertBefore(card, d.firstChild);
      });
    });
    // a drag that ends on a card must not also open it
    board.addEventListener('click', function (e) {
      if (moved && e.target.closest('.crm-card')) { e.preventDefault(); moved = false; }
    }, true);
  }

  /* -------------------------------------------------------------- focus mode */
  function setFocus(on) {
    document.body.classList.toggle('crm-focus', on);
    var b = document.querySelector('[data-focus]');
    if (b) b.innerHTML = on ? '<i class="fa-solid fa-compress"></i>' : '<i class="fa-solid fa-expand"></i>';
    try { localStorage.setItem('crm-focus', on ? '1' : ''); } catch (e) { /* private window */ }
  }
  var focusBtn = document.querySelector('[data-focus]');
  if (focusBtn) {
    try { if (localStorage.getItem('crm-focus') === '1') setFocus(true); } catch (e) { /* ignore */ }
    focusBtn.addEventListener('click', function () { setFocus(!document.body.classList.contains('crm-focus')); });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && document.body.classList.contains('crm-focus') && !document.querySelector('dialog[open]')) setFocus(false);
    });
  }

  /* -------------------------------------------------------------- log today's work: − / + */
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-step]');
    if (!b) return;
    var input = b.parentElement.querySelector('input');
    input.value = Math.max(0, (parseFloat(input.value) || 0) + parseFloat(b.dataset.step));
  });

  /* -------------------------------------------------------------- inbox check */
  document.addEventListener('click', function (e) {
    var t = e.target.closest('[data-tick]');
    var all = e.target.closest('[data-tick-all]');
    if (!t && !all) return;
    var btn = t || all;
    btn.disabled = true;
    var body = all ? { all: true, slot: +all.dataset.slot } : { slot: +t.dataset.slot, channel: t.dataset.channel };
    post('checks/tick', body).then(function (d) {
      btn.disabled = false;
      if (!d._ok) { toast(d.error || 'Could not save.', true); return; }
      if (all) { toast('All inboxes ticked for this half hour'); reloadSoon(400); return; }
      t.classList.toggle('on', !!d.ticked);
      t.textContent = d.ticked ? '✓' : '';
      if (d.ticked) t.classList.remove('miss');
    });
  });

  /* -------------------------------------------------------------- slow forms say they are working */
  document.querySelectorAll('form[data-busy]').forEach(function (f) {
    f.addEventListener('submit', function () {
      var b = f.querySelector('button');
      if (b) { b.disabled = true; b.textContent = 'Working… this can take a minute'; }
    });
  });

  /* -------------------------------------------------------------- set-up: {name} buttons */
  document.addEventListener('click', function (e) {
    var v = e.target.closest('[data-var]');
    if (!v) return;
    var ta = (v.closest('form') || document).querySelector('[data-vars-target]');
    if (!ta) return;
    var s = ta.selectionStart || ta.value.length, en = ta.selectionEnd || s;
    ta.value = ta.value.slice(0, s) + v.dataset.var + ta.value.slice(en);
    ta.focus();
    ta.selectionStart = ta.selectionEnd = s + v.dataset.var.length;
  });
  /* -------------------------------------------------------------- copy buttons (shift-end message) */
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-copy]');
    if (!b) return;
    var src = b.parentElement.querySelector('[data-copy-text]');
    var text = src ? src.textContent : '';
    (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject()).then(
      function () { toast('Copied'); }, function () { toast('Select the text and copy it', true); });
  });
})();
