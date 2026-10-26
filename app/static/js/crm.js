/* Sales CRM screens (/cs/crm). One file, delegated handlers, no framework.

   Every button does the whole job in one click: a follow-up's Send goes through the lead page's
   message box (or, beside the WhatsApp inbox, straight away), is logged, ticks the step off and
   plans the next one. The server decides all of that; this only collects what was clicked and
   shows the result. The lead page keeps itself fresh: its [data-lead-live] regions are swapped
   from <crm>/lead/<id>/live every few seconds, never over something half typed. */
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
    if (el && el.closest && el.closest('[data-lead-page][data-live]')) {
      setTimeout(function () { refreshLive(); }, Math.min(ms || 150, 300));
      return;
    }
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
     clicked, or null when closed. A dialog's 'close' event arrives a moment after close(): when the next question
     is already open in the same <dialog> (Move to... -> Mark as won?), that late event is not this one's. */
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
      dialog.addEventListener('close', function once() { if (dialog.open) return; dialog.removeEventListener('close', once); finish(null); });
      dialog.showModal();
    });
  }

  // copy words to the clipboard; an old browser gets a hidden text box and the copy command instead
  function copy(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) return navigator.clipboard.writeText(text);
    return new Promise(function (resolve, reject) {
      var ta = document.createElement('textarea');
      ta.value = text; ta.setAttribute('readonly', ''); ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select();
      try { if (document.execCommand('copy')) resolve(); else reject(); } catch (err) { reject(err); }
      ta.remove();
    });
  }

  // the set-up screens (crm-setup.js) use the same helpers
  window.CRM = { post: post, toast: toast, choose: choose, esc: esc, base: BASE, copy: copy };

  // [data-copy="<text>"] copies that text; [data-copy-from="<an element's id>"] copies what that element shows
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-copy], [data-copy-from]');
    if (!b) return;
    var from = b.dataset.copyFrom && document.getElementById(b.dataset.copyFrom);
    var text = from ? (from.value || from.textContent || '') : (b.dataset.copy || '');
    copy(text.trim()).then(function () { toast('Copied'); },
      function () { toast('Could not copy. Select the text and copy it by hand.', true); });
  });

  /* -------------------------------------------------------------- dialogs, asking first, menus */
  // [data-dlg-open="<a dialog's id>"] opens that dialog; [data-dlg-close] closes the one it sits in.
  // A click outside an open More menu or the value panel (_lead_value.html) closes it; so does Esc.
  document.addEventListener('click', function (e) {
    var o = e.target.closest('[data-dlg-open]');
    if (o) {
      var d = document.getElementById(o.dataset.dlgOpen);
      if (d && d.showModal && !d.open) {
        d.showModal();
        var first = d.querySelector('input:not([type=hidden]), textarea');
        if (first) first.focus();
      }
      return;
    }
    var c = e.target.closest('[data-dlg-close]');
    if (c && c.closest('dialog')) { c.closest('dialog').close(); return; }
    var lc = e.target.closest('[data-lv-close]');
    if (lc && lc.closest('details')) { lc.closest('details').open = false; return; }
    document.querySelectorAll('details.more-menu[open], details.lv[open]').forEach(function (m) {
      if (!m.contains(e.target)) m.open = false;
    });
  });
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape' || document.querySelector('dialog[open]')) return;
    document.querySelectorAll('details.more-menu[open], details.lv[open]').forEach(function (m) { m.open = false; });
  });
  // A form with data-ask asks first, in the page's own chooser (never the browser's confirm box): data-ask is
  // the question, data-ask-line a line under it, data-yes the button that goes ahead.
  document.addEventListener('submit', function (e) {
    var f = e.target;
    if (!f.matches || !f.matches('form[data-ask]') || !dialog) return;
    e.preventDefault();
    choose(f.dataset.ask, f.dataset.askLine || '', [{ label: f.dataset.yes || 'Yes', value: 'yes' }]).then(function (v) {
      if (v === 'yes') HTMLFormElement.prototype.submit.call(f);
    });
  });

  /* -------------------------------------------------------------- the lead page's tabs */
  // Conversation, Tasks, Quotes & payments, Files, History. The address keeps the open one (#tasks, #quotes...),
  // so a reload -- or a quote or file form coming back to #quotes, #files -- opens it again; an address naming
  // something inside a tab (#quote-3) opens that tab. Whatever fills the message box opens Conversation first.
  var tabBar = document.querySelector('[data-lead-tabs]');
  function showPane(name) {
    var pane = tabBar && document.querySelector('[data-lead-pane="' + name + '"]');
    if (!pane) return;
    document.querySelectorAll('[data-lead-pane]').forEach(function (p) { p.hidden = p !== pane; });
    tabBar.querySelectorAll('[data-lead-tab]').forEach(function (t) {
      var on = t.dataset.leadTab === name;
      t.setAttribute('aria-selected', on ? 'true' : 'false');
      t.tabIndex = on ? 0 : -1;
    });
    // the timeline opens at its newest line the first time it shows
    var sc = pane.querySelector('[data-tl-scroll]');
    if (sc && !sc.dataset.seen) { sc.dataset.seen = '1'; sc.scrollTop = sc.scrollHeight; }
    if (window.history && history.replaceState) {
      history.replaceState(history.state, '', name === 'conversation' ? location.pathname + location.search : '#' + name);
    }
  }
  window.CRM.showPane = showPane;
  if (tabBar) {
    var fromHash = function () {
      var id = '';
      try { id = decodeURIComponent(location.hash.slice(1)); } catch (err) { /* a broken address opens Conversation */ }
      var el = id && document.getElementById(id);
      var pane = el && el.closest('[data-lead-pane]');
      showPane(pane ? pane.dataset.leadPane : 'conversation');
      if (pane && el !== pane.firstElementChild) el.scrollIntoView({ block: 'center' });
    };
    tabBar.addEventListener('click', function (e) {
      var t = e.target.closest('[data-lead-tab]');
      if (t) showPane(t.dataset.leadTab);
    });
    tabBar.addEventListener('keydown', function (e) {
      var tabs = Array.prototype.slice.call(tabBar.querySelectorAll('[data-lead-tab]'));
      var i = tabs.indexOf(document.activeElement), n = -1;
      if (i < 0) return;
      if (e.key === 'ArrowRight') n = (i + 1) % tabs.length;
      else if (e.key === 'ArrowLeft') n = (i - 1 + tabs.length) % tabs.length;
      else if (e.key === 'Home') n = 0;
      else if (e.key === 'End') n = tabs.length - 1;
      if (n < 0) return;
      e.preventDefault();
      showPane(tabs[n].dataset.leadTab);
      tabs[n].focus();
    });
    fromHash();
    window.addEventListener('hashchange', fromHash);
  }

  function reasonsFrom(el) {
    try { return JSON.parse(el.dataset.reasons || '[]'); } catch (e) { return []; }
  }

  /* Moving a lead. A finish line asks once: won to confirm, lost for why (the pipeline's buttons). A stage
     with a milestone button asks "Did you send the quote?". `stage`: an element with data-stage, data-kind,
     data-name (and data-milestone, data-ask), or a plain object with those names. */
  /* The optional Amount in the "Did you send the quote?" dialog: prefilled with the lead's amount. */
  function amountField(value) {
    return '<label class="lbl" for="crm-ask-amount" style="margin-top:10px">Amount (optional)</label>' +
      '<input type="text" inputmode="decimal" id="crm-ask-amount" data-ask-amount autocomplete="off" placeholder="e.g. 18500" value="' + esc(value || '') + '"/>';
  }
  function askedAmount() {
    var i = dialog.querySelector('[data-ask-amount]');
    return i ? i.value.trim() : '';
  }

  /* A stage that needs something before a lead moves in (Set-up -> Pipelines): one small form, then the move
     is posted again with the typed values. Resolves the values, or null when closed. */
  function askFields(stageName, fields) {
    return new Promise(function (resolve) {
      var box = dialog.querySelector('.in');
      var rows = fields.map(function (f, i) {
        var id = 'crm-need-' + i, input;
        if (f.type === 'date') input = '<input type="date" id="' + id + '" data-need="' + esc(f.key) + '"/>';
        else if (f.type === 'money' || f.type === 'number') input = '<input type="text" inputmode="decimal" id="' + id + '" data-need="' + esc(f.key) + '" autocomplete="off"/>';
        else if (f.type === 'choice' && f.options && f.options.length) {
          input = '<select id="' + id + '" data-need="' + esc(f.key) + '"><option value=""></option>' + f.options.map(function (o) {
            return '<option>' + esc(o) + '</option>'; }).join('') + '</select>';
        } else if (f.type === 'yesno') input = '<select id="' + id + '" data-need="' + esc(f.key) + '"><option value=""></option><option>Yes</option><option>No</option></select>';
        else input = '<input type="text" id="' + id + '" data-need="' + esc(f.key) + '" autocomplete="off"/>';
        return '<label class="lbl" for="' + id + '" style="margin-top:8px">' + esc(f.label) +
          (f.currency ? ' (' + esc(f.currency) + ')' : '') + '</label>' + input;
      }).join('');
      box.innerHTML = '<h3>Before it moves to ' + esc(stageName) + '</h3><p class="muted" style="margin:0">This stage needs:</p>' + rows +
        '<div class="row end" style="margin-top:12px"><button type="button" class="cb ghost" data-close>Cancel</button>' +
        '<button type="button" class="cb primary" data-save>Save and move</button></div>';
      var done = false;
      function finish(v) { if (done) return; done = true; dialog.close(); resolve(v); }
      box.querySelector('[data-close]').onclick = function () { finish(null); };
      box.querySelector('[data-save]').onclick = function () {
        var vals = {};
        box.querySelectorAll('[data-need]').forEach(function (i) { vals[i.dataset.need] = i.value.trim(); });
        finish(vals);
      };
      dialog.addEventListener('close', function once() { if (dialog.open) return; dialog.removeEventListener('close', once); finish(null); });
      dialog.showModal();
    });
  }
  function postMove(leadId, body) {
    return post('lead/' + leadId + '/move', body).then(function (d) {
      if (d._ok || !d.need_fields) return d;
      if (body.fields) toast(d.error || 'Fill in what the stage needs.', true);
      return askFields(d.stage_name || 'this stage', d.need_fields).then(function (vals) {
        if (!vals) return null;
        body.fields = vals;
        return postMove(leadId, body);
      });
    });
  }

  function moveLead(leadId, stage, reasonsSource, amount0) {
    var info = stage.dataset || stage;
    if (amount0 == null) amount0 = (reasonsSource && reasonsSource.dataset && reasonsSource.dataset.amount) || '';
    var kind = info.kind, name = info.name, milestone = info.milestone || '';
    var ask = Promise.resolve('');
    if (kind === 'lost') {
      var reasons = reasonsFrom(reasonsSource);
      if (!reasons.length) reasons = ['No response', 'Not interested'];
      ask = choose('Why did we lose them?', 'Moving to "' + name + '".',
        reasons.map(function (r) { return { label: r, value: r }; }));
    } else if (kind === 'won') {
      ask = choose('Mark as won?', 'Moving to "' + name + '". Well done!', [{ label: 'Yes, won', value: 'won' }]);
    } else if (milestone && kind === 'open') {
      ask = choose(info.ask || 'Did you send it?', 'Moving to "' + name + '".',
        [{ label: 'Yes, log it', value: 'yes' }, { label: 'No, just move', value: 'no' }], amountField(amount0));
    }
    return ask.then(function (reason) {
      if (reason === null) return null;
      var body = { stage_id: +info.stage, reason: kind === 'lost' ? reason : '' };
      if (milestone && kind === 'open') {
        body.log_milestone = reason === 'yes';
        var amt = askedAmount();
        if (amt && amt !== amount0) body.amount = amt;
      }
      return postMove(leadId, body);
    }).then(function (d) {
      if (d === null) return null;
      if (!d._ok) { toast(d.error || 'Could not move it.', true); return null; }
      var said = d.logged ? '. Logged: ' + (d.logged_label || '') : '';
      toast(d.status === 'won' ? 'Won! 🎉 Moved to ' + d.stage : 'Moved to ' + d.stage + said, false,
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
      toast(action === 'snooze' ? 'Moved to tomorrow' : action === 'skip' ? 'Marked not needed' : 'Done ✓' +
        (d.next ? ' Next: ' + (d.next.title || 'the next follow-up') : ''));
      return d;
    });
  }

  function logCall(leadId, outcome, taskId, extra) {
    var body = { outcome: outcome, task_id: taskId || null };
    Object.keys(extra || {}).forEach(function (k) { body[k] = extra[k]; });
    return post('lead/' + leadId + '/call', body).then(function (d) {
      if (!d._ok) { toast(d.error || 'Could not save the call.', true); return null; }
      toast(d.call_back ? 'Saved. Call them back ' + d.call_back + '.' : 'Call saved');
      return d;
    });
  }

  var OUTCOMES = [
    { label: 'Talked', value: 'connected' }, { label: 'No answer', value: 'no_answer' },
    { label: 'Busy', value: 'busy' }, { label: 'Call back', value: 'call_back' },
    { label: 'Wrong number', value: 'wrong_number' }, { label: 'Switched off', value: 'switched_off' }];

  /* "Call back" asks when: a call goes on their follow-ups for then. Resolves {when, at} or null. */
  function askCallBack() {
    return choose('When?', 'A call goes on their follow-ups for then.', [
      { label: 'In 1 hour', value: '1h' }, { label: 'This evening', value: 'evening' },
      { label: 'Tomorrow morning', value: 'morning' }, { label: 'Pick a time', value: 'at' }
    ]).then(function (v) {
      if (!v) return null;
      if (v !== 'at') return { when: v };
      return new Promise(function (resolve) {
        var box = dialog.querySelector('.in');
        box.innerHTML = '<h3>Pick a time</h3><div class="stack" style="margin-top:10px">' +
          '<input type="datetime-local" id="crm-cb-at" aria-label="Call back at"/>' +
          '<div class="row end"><button type="button" class="cb ghost" data-close>Cancel</button>' +
          '<button type="button" class="cb primary" data-save>Save</button></div></div>';
        var done = false;
        function finish(r) { if (done) return; done = true; dialog.close(); resolve(r); }
        box.querySelector('[data-close]').onclick = function () { finish(null); };
        box.querySelector('[data-save]').onclick = function () {
          var at = document.getElementById('crm-cb-at').value;
          if (!at) { toast('Pick a time.', true); return; }
          finish({ when: 'at', at: at });
        };
        dialog.addEventListener('close', function once() { if (dialog.open) return; dialog.removeEventListener('close', once); finish(null); });
        dialog.showModal();
      });
    });
  }

  /* A link that leaves the page (their WhatsApp, the mail program): when the person comes back,
     ask whether it really went before anything is ticked. */
  function askOnReturn(title, options) {
    return new Promise(function (resolve) {
      var t0 = Date.now(), away = false, asked = false, timer = null;
      function ask() {
        if (asked) return;
        asked = true; cleanup();
        choose(title, '', options).then(resolve);
      }
      function back() {
        if (!away || asked || document.visibilityState === 'hidden') return;
        setTimeout(ask, Math.max(0, 1200 - (Date.now() - t0)));
      }
      function gone() { away = true; }
      function vis() { if (document.visibilityState === 'hidden') gone(); else back(); }
      function cleanup() {
        window.removeEventListener('blur', gone); window.removeEventListener('focus', back);
        document.removeEventListener('visibilitychange', vis); clearTimeout(timer);
      }
      window.addEventListener('blur', gone); window.addEventListener('focus', back);
      document.addEventListener('visibilitychange', vis);
      timer = setTimeout(function () { if (!away) ask(); }, 3000);   // it never left: ask anyway
    });
  }
  var YES_NO = [{ label: 'Yes', value: 'yes' }, { label: 'No', value: 'no' }];

  function afterCall(d, leadPage) {
    if (!d) return;
    if (d.suggest_fallout && leadPage) {
      var reasonsSource = leadPage;
      var lost = leadPage.querySelector('[data-journey] [data-kind="lost"]');
      if (lost) {
        choose(d.no_answers + ' calls in a row with no answer', 'Move them to "' + lost.dataset.name + '"?',
          [{ label: 'Yes, mark them lost', value: 'yes' }, { label: 'Keep trying', value: 'no' }])
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
      var gone = function (d) { if (d) card.classList.add('gone'); };
      if (act === 'tpl-send' || act === 'text-send') {
        // one press, one send: the lead page's message route claims the step before anything goes
        e.preventDefault();
        b.disabled = true;
        var tpl = act === 'tpl-send';
        post('lead/' + lid + '/message', tpl ? { kind: 'template', template: b.dataset.template, task_id: tid }
                                             : { kind: 'text', text: b.dataset.text, task_id: tid }).then(function (d) {
          b.disabled = false;
          if (d._ok) {
            toast(d.mode === 'unsure' ? (d.reason || 'WhatsApp did not answer. Check the chat.') : (tpl ? 'Template sent on WhatsApp' : 'Sent on WhatsApp'),
                  d.mode === 'unsure');
            card.classList.add('gone');
            return;
          }
          var open = d.mode === 'window_closed'
            ? { label: 'Open lead', run: function () { location.href = BASE + 'lead/' + lid + '?via=whatsapp'; } } : null;
          toast(d.error || 'Could not send.', true, open);
        });
      } else if (act === 'wa-own') {
        // their own WhatsApp (WhatsApp is not connected for leads): opened inside this click
        var wl = waLink(card.dataset.phone, b.dataset.text || '');
        if (wl) window.open(wl, '_blank', 'noopener');
        askOnReturn('Did you send it?', YES_NO).then(function (v) {
          if (v !== 'yes') return;
          post('lead/' + lid + '/send', { text: b.dataset.text || '', task_id: tid }).then(function (d) {
            if (!d._ok) { toast(d.error || 'Could not save.', true); return; }
            toast('Saved as sent from your own WhatsApp.');
            card.classList.add('gone');
          });
        });
      } else if (act === 'mail-task') {
        // the mail program opens; when they come back, ask before anything is ticked
        var mbody = b.dataset.text || '';
        b.href = 'mailto:' + (card.dataset.email || '') + '?body=' + encodeURIComponent(mbody);
        askOnReturn('Did you send it?', YES_NO).then(function (v) {
          if (v !== 'yes') return;
          post('lead/' + lid + '/note', { text: mbody || 'E-mail sent', channel: 'email' }).then(function () {
            taskAction(tid, 'done').then(gone);
          });
        });
      } else if (act === 'done' || act === 'snooze' || act === 'skip') {
        taskAction(tid, act).then(gone);
      } else if (act === 'more-words') {
        var words = card.querySelector('[data-words]');
        var more = words.classList.toggle('clamp') === false;
        b.textContent = more ? '▴ fewer words' : '▾ all the words';
      } else if (act === 'dial') {
        // let the tel: link ring, then ask how it went
        setTimeout(function () {
          choose('How did the call go?', '', OUTCOMES).then(function (v) {
            if (!v) return null;
            return (v === 'call_back' ? askCallBack() : Promise.resolve({})).then(function (extra) {
              if (!extra) return;
              logCall(lid, v, tid, extra).then(gone);
            });
          });
        }, 400);
      }
      return;
    }

    var waitRow = b.closest('.crm-wait');
    if (waitRow) {
      if (act === 'lead-snooze') {
        post('lead/' + waitRow.dataset.lead + '/snooze', {}).then(function (d) {
          if (!d._ok) { toast(d.error || 'Could not do that.', true); return; }
          toast('Hidden for an hour.');
          waitRow.classList.add('gone');
        });
      }
      return;
    }

    if (act === 'signoff') {
      var n = +b.dataset.n || 0;
      choose('Send this to ' + n + ' open chat' + (n === 1 ? '' : 's') + '?', '“' + (b.dataset.preview || '') + '”',
             [{ label: 'Send to ' + n, value: 'yes' }]).then(function (v) {
        if (v !== 'yes') return;
        b.disabled = true;
        post('today/signoff', { text: b.dataset.text || '' }).then(function (d) {
          toast(d.message || d.error || 'Could not send.', !d._ok);
          b.disabled = false;
          reloadSoon(1500);
        });
      });
      return;
    }

    if (leadPage) {
      var leadId = leadPage.dataset.lead;
      var phone = leadPage.dataset.phone || '';
      var q = function (sel) { return leadPage.querySelector(sel); };
      if (act === 'send-next') {
        // beside the WhatsApp inbox: Instagram / Messenger from the card
        var next = q('[data-next]');
        b.disabled = true;
        sendMessage(leadId, b.dataset.text || '', next && next.dataset.task, phone, b.dataset.via)
          .then(function (d) { b.disabled = false; if (d) reloadFor(leadPage, 900); });
      } else if (act === 'send-step') {
        // beside the WhatsApp inbox: the follow-up's template, or its words as free text
        b.disabled = true;
        post('lead/' + leadId + '/message', { kind: b.dataset.kind, template: b.dataset.template || null,
                                              text: b.dataset.text || '', task_id: b.dataset.task || null }).then(function (d) {
          b.disabled = false;
          if (handleMessage(d, leadPage, b.dataset.kind)) reloadFor(leadPage, 900);
        });
      } else if (act === 'box-send') {
        boxSend(b, leadPage);
      } else if (act === 'fill-box') {
        fillBox(b, leadPage);
      } else if (act === 'wa-own') {
        // their own WhatsApp (WhatsApp is not connected for leads): opened inside this click
        var link = waLink(phone, b.dataset.text || '');
        if (link) window.open(link, '_blank', 'noopener');
        askOnReturn('Did you send it?', YES_NO).then(function (v) {
          if (v !== 'yes') return;
          post('lead/' + leadId + '/send', { text: b.dataset.text || '', task_id: b.dataset.task || null }).then(function (d) {
            if (!d._ok) { toast(d.error || 'Could not save.', true); return; }
            toast('Saved as sent from your own WhatsApp.'); reloadFor(leadPage);
          });
        });
      } else if (act === 'compose') {
        // contract 25: the WhatsApp CRM fills its box (never sends) and answers wacrm:composed; the frame says a refusal (messaging/frame.html)
        if (!(window.CRM_compose && window.CRM_compose(b.dataset.text || ''))) toast('Open the chat on the left first.', true);
      } else if (act === 'open-chat') {
        e.preventDefault();
        openChat(leadPage);
      } else if (act === 'close-chat') {
        closeChat(leadPage);
      } else if (act === 'opt-in') {
        choose('Opt them back in to WhatsApp?', 'Only if they asked to hear from us again.',
               [{ label: 'Yes, opt back in', value: 'yes' }]).then(function (v) {
          if (v !== 'yes') return;
          post('lead/' + leadId + '/opt-in', {}).then(function (d) {
            if (!d._ok) { toast(d.error || 'Could not do that.', true); return; }
            toast(d.message); refreshLive();
          });
        });
      } else if (act === 'wa-retry') {
        b.disabled = true;
        post('lead/' + leadId + '/wa-retry', {}).then(function (d) {
          b.disabled = false;
          if (!d._ok) { toast(d.error || 'Could not do that.', true); return; }
          toast('Trying again now.'); refreshLive(); setTimeout(refreshLive, 4000);
        });
      } else if (act === 'done' || act === 'snooze' || act === 'skip') {
        taskAction(b.dataset.task, act).then(function (d) { if (d) reloadFor(leadPage); });
      } else if (act === 'mail') {
        // the mail program opens; when they come back, ask before anything is ticked
        var mbody = b.dataset.text || '';
        b.href = b.href.split('?')[0] + '?body=' + encodeURIComponent(mbody);
        if (b.dataset.task) {
          askOnReturn('Did you send it?', YES_NO).then(function (v) {
            if (v !== 'yes') return;
            post('lead/' + leadId + '/note', { text: mbody || 'E-mail sent', channel: 'email' }).then(function () {
              taskAction(b.dataset.task, 'done').then(function (d) { if (d) reloadFor(leadPage); });
            });
          });
        }
      } else if (act === 'note') {
        var text = q('[data-note-text]').value.trim();
        if (!text) { toast('Write something first.', true); return; }
        post('lead/' + leadId + '/note', { text: text, channel: 'note' }).then(function (d) {
          if (!d._ok) { toast(d.error || 'Could not save.', true); return; }
          q('[data-note-text]').value = '';
          toast('Saved'); reloadFor(leadPage);
        });
      } else if (act === 'wrote') {
        var chip = q('[data-wrote-ch].on');
        var said = q('[data-wrote-text]').value.trim();
        if (!chip) { toast('Pick where they wrote.', true); return; }
        if (!said) { toast('Write what they said first.', true); return; }
        post('lead/' + leadId + '/note', { text: said, channel: chip.dataset.wroteCh, from_them: true }).then(function (d) {
          if (!d._ok) { toast(d.error || 'Could not save.', true); return; }
          q('[data-wrote-text]').value = ''; chip.classList.remove('on');
          toast('Saved'); reloadFor(leadPage);
        });
      } else if (act === 'undo') {
        undoMove(leadId, leadPage);
      } else if (act === 'reopen') {
        post('lead/' + leadId + '/reopen', {}).then(function (d) {
          if (!d._ok) { toast(d.error || 'Could not reopen.', true); return; }
          toast('Back to work, in ' + d.stage); reloadFor(leadPage);
        });
      } else if (act === 'remove') {
        choose('Remove this lead?',
               'It goes to the Recycle bin for 30 days, with its follow-ups and timeline, and an admin can put it back. ' + (b.dataset.name || 'The contact') + ' stays in Contacts.',
               [{ label: 'Yes, remove', value: 'yes' }]).then(function (v) {
          if (v !== 'yes') return;
          post('lead/' + leadId + '/remove', {}).then(function (d) {
            if (!d._ok) { toast(d.error || 'Could not remove.', true); return; }
            location.href = d.next;
          });
        });
      }
    }
  });

  /* -------------------------------------------------------------- the message box */
  function handleMessage(d, leadPage, kind) {
    // true when it went (or may have): the caller then clears the box and refreshes
    if (d._ok && d.mode === 'unsure') { toast(d.reason || 'WhatsApp did not answer. Check the chat.', true); return true; }
    if (d._ok) { toast(kind === 'template' ? 'Template sent on WhatsApp' : 'Sent on WhatsApp'); return true; }
    var box = leadPage.querySelector('[data-box]');
    if (d.mode === 'window_closed') {
      if (box) { box.dataset.userMode = 'template'; syncBox(leadPage); }
      toast(d.error || 'WhatsApp says the chat has closed. Choose an approved template.', true);
      refreshLive();
    } else if (d.mode === 'ambiguous') {
      toast(d.error, true, { label: 'Open full chat', run: function () { openChat(leadPage); } });
    } else {
      toast(d.error || 'Could not send.', true);
    }
    return false;
  }

  function boxReset(box) {
    var input = box.querySelector('[data-box-input]');
    if (input) input.value = '';
    box.querySelectorAll('[data-tpl-fills] input').forEach(function (i) { i.value = ''; });
    delete box.dataset.task; delete box.dataset.answer; delete box.dataset.userMode; delete box.dataset.taskTemplate;
    var tpl = box.querySelector('[data-lead-live="templates"]');
    if (tpl) delete tpl.dataset.touched;
  }

  function boxSend(b, leadPage) {
    var box = leadPage.querySelector('[data-box]');
    if (!box) return;
    var leadId = leadPage.dataset.lead, via = box.dataset.via || 'whatsapp', kind = b.dataset.kind;
    var input = box.querySelector('[data-box-input]');
    var task = box.dataset.task || null;
    if (via !== 'whatsapp') {
      var words = input.value.trim();
      if (!words) { toast('Write the message first.', true); return; }
      b.disabled = true;
      sendMessage(leadId, words, task, '', via, box.dataset.answer).then(function (d) {
        b.disabled = false;
        if (d) { boxReset(box); refreshLive(); }
      });
      return;
    }
    var body;
    if (kind === 'text') {
      var text = input.value.trim();
      if (!text) { toast('Write the message first.', true); return; }
      body = { kind: 'text', text: text, task_id: task, answer_id: box.dataset.answer || null };
    } else {
      var sel = box.querySelector('[data-tpl]');
      if (!sel) { toast('Choose an approved template first.', true); return; }
      var opt = sel.options[sel.selectedIndex];
      if (opt.dataset.blocked) { toast(opt.dataset.blocked, true); return; }
      var params = [];
      box.querySelectorAll('[data-tpl-fills] input').forEach(function (i) { params.push(i.value.trim()); });
      body = { kind: 'template', template: sel.value, params: params, task_id: task };
    }
    b.disabled = true;
    post('lead/' + leadId + '/message', body).then(function (d) {
      b.disabled = false;
      if (handleMessage(d, leadPage, body.kind)) { boxReset(box); refreshLive(); }
    });
  }

  /* The follow-up's Send puts its message in the box; the agent presses Send there. */
  function fillBox(b, leadPage) {
    var box = leadPage.querySelector('[data-box]');
    if (!box) return;
    showPane('conversation');
    var via = b.dataset.via || 'whatsapp';
    box.dataset.via = via;
    if (b.dataset.task) box.dataset.task = b.dataset.task; else delete box.dataset.task;
    function done() { syncBox(leadPage); box.scrollIntoView({ block: 'center', behavior: 'smooth' }); }
    if (via === 'whatsapp' && b.dataset.kind === 'template') {
      box.dataset.userMode = 'template';
      syncBox(leadPage);
      var sel = box.querySelector('[data-tpl]');
      var opt = sel && Array.prototype.find.call(sel.options, function (o) { return o.value === b.dataset.template; });
      if (sel && b.dataset.template && !opt) toast('That template is not approved yet. Choose another.', true);
      if (opt) { sel.value = opt.value; box.dataset.taskTemplate = opt.value; }
      renderFills(box);
      var tp = box.querySelector('[data-lead-live="templates"]');
      if (tp) tp.dataset.touched = '1';
      done();
      return;
    }
    var input = box.querySelector('[data-box-input]');
    var put = function () {
      input.value = b.dataset.text || '';
      box.dataset.userMode = 'text';
      done();
      input.focus();
    };
    if (input.value.trim() && input.value.trim() !== (b.dataset.text || '').trim()) {
      choose('Replace what you typed?', '', [{ label: 'Replace', value: 'yes' }]).then(function (v) { if (v === 'yes') put(); });
    } else {
      put();
    }
  }

  function syncBox(leadPage) {
    var box = leadPage.querySelector('[data-box]');
    if (!box) return;
    var tl = leadPage.querySelector('[data-lead-live="timeline"]');
    var d = tl ? tl.dataset : {};
    var via = box.dataset.via || 'whatsapp', st = d.waState || 'never', mode = box.dataset.userMode || '';
    var showText = false, showTpl = false, note = '', setup = false, toTpl = false, toText = false;
    if (via === 'instagram' || via === 'facebook') {
      note = (via === 'instagram' ? d.igNote : d.fbNote) || '';
      showText = !note;
    } else if (st === 'off') {
      note = d.waNote || ''; setup = true;
    } else if (st === 'no_phone' || st === 'opted_out') {
      note = d.waNote || '';
    } else if (st === 'opted_out_open') {
      showText = true; note = d.waNote || '';
    } else if (st === 'open') {
      if (mode === 'template') { showTpl = true; toText = true; } else { showText = true; toTpl = true; }
    } else {
      showTpl = true; note = d.waNote || '';
    }
    var set = function (sel, on) { var el = box.querySelector(sel); if (el) el.hidden = !on; };
    set('[data-box-text]', showText); set('[data-box-tpl]', showTpl); set('[data-box-setup]', setup);
    set('[data-box-text] [data-box-mode="template"]', toTpl); set('[data-box-tpl] [data-box-mode="text"]', toText);
    var n = box.querySelector('[data-box-note]');
    if (n) { n.textContent = note; n.hidden = !note; }
    box.querySelectorAll('[data-box-via]').forEach(function (c) { c.classList.toggle('on', c.dataset.via === via); });
    if (showTpl) renderFills(box);
  }

  /* the picked template's fill-ins, one box each, and a preview of the words as they will go */
  function renderFills(box) {
    var sel = box.querySelector('[data-tpl]');
    var holder = box.querySelector('[data-tpl-fills]');
    if (!sel || !holder) return;
    var opt = sel.options[sel.selectedIndex];
    if (!opt) return;
    var body = opt.dataset.body || '';
    var seen = [];
    body.replace(/\{\{(\d+)\}\}/g, function (m, k) { if (seen.indexOf(+k) < 0) seen.push(+k); return m; });
    var n = opt.dataset.vars !== '' && opt.dataset.vars != null ? +opt.dataset.vars : seen.length;
    var fill = [];
    try { fill = JSON.parse(opt.dataset.fill || '[]'); } catch (e) { fill = []; }
    if (holder.dataset.for !== sel.value || holder.children.length !== n) {
      holder.dataset.for = sel.value;
      holder.innerHTML = '';
      for (var i = 0; i < n; i++) {
        var inp = document.createElement('input');
        inp.type = 'text'; inp.maxLength = 200; inp.setAttribute('value', fill[i] || '');
        inp.setAttribute('aria-label', 'Fill-in ' + (i + 1)); inp.placeholder = 'Fill-in ' + (i + 1);
        holder.appendChild(inp);
      }
    }
    var why = box.querySelector('[data-tpl-why]');
    var send = box.querySelector('[data-box-tpl] [data-act="box-send"]');
    var blocked = opt.dataset.blocked || '';
    if (why) why.textContent = blocked || opt.dataset.warn || '';
    if (send) send.disabled = !!blocked;
    renderPreview(box);
  }

  function renderPreview(box) {
    var sel = box.querySelector('[data-tpl]');
    var pv = box.querySelector('[data-tpl-preview]');
    if (!sel || !pv) return;
    var opt = sel.options[sel.selectedIndex];
    var vals = Array.prototype.map.call(box.querySelectorAll('[data-tpl-fills] input'), function (i) { return i.value; });
    var seen = [];
    var text = (opt.dataset.body || '').replace(/\{\{(\d+)\}\}/g, function (m, k) {
      var at = +k - 1;
      return vals[at] ? vals[at] : m;
    });
    pv.textContent = text;
    if (seen.length) return;
  }

  /* -------------------------------------------------------------- the full chat drawer */
  function openChat(leadPage) {
    var drawer = leadPage.querySelector('[data-chat-drawer]');
    var src = leadPage.dataset.chatSrc;
    if (!drawer || !src) return;
    var frame = drawer.querySelector('[data-chat-frame]');
    if (frame && !frame.getAttribute('src')) frame.setAttribute('src', src);
    drawer.hidden = false;
    document.body.classList.add('crm-drawer-open');
  }
  function closeChat(leadPage) {
    var drawer = leadPage.querySelector('[data-chat-drawer]');
    if (drawer) drawer.hidden = true;
    document.body.classList.remove('crm-drawer-open');
  }

  /* -------------------------------------------------------------- the lead page stays fresh */
  var page = document.querySelector('[data-lead-page][data-live]');
  var liveBusy = false, liveAgain = false, liveOff = false;

  function refreshLive(first) {
    if (!page || liveOff) return;
    if (liveBusy) { liveAgain = true; return; }
    liveBusy = true;
    fetch(page.dataset.live + (first === true ? '?first=1' : ''), { credentials: 'same-origin', headers: { 'Accept': 'text/html' } })
      .then(function (r) {
        if (r.status === 404) { liveOff = true; return ''; }
        return r.ok ? r.text() : '';
      })
      .then(function (html) { if (html) applyLive(page, html); })
      .catch(function () { /* the next round tries again */ })
      .then(function () {
        liveBusy = false;
        if (liveAgain) { liveAgain = false; refreshLive(); }
      });
  }
  window.CRM_refreshLead = function () { refreshLive(); };

  // something half typed or open in a region: leave that region as it is
  function regionBusy(el) {
    if (el.querySelector('[data-detail-edit]:not([hidden])')) return true;      // a detail being changed
    var a = document.activeElement;
    if (a && el.contains(a) && /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName)) return true;
    if (el.querySelector('details.more-menu[open], details.box-qr[open], details.lv[open]')) return true;
    if (el.dataset.touched === '1') return true;
    if (el.querySelector('[data-wrote-ch].on')) return true;
    var fields = el.querySelectorAll('textarea, input[type="text"], input[type="datetime-local"]');
    for (var i = 0; i < fields.length; i++) if (fields[i].value !== fields[i].defaultValue) return true;
    return false;
  }

  function applyLive(leadPage, html) {
    var doc = new DOMParser().parseFromString(html, 'text/html');
    doc.querySelectorAll('[data-lead-live]').forEach(function (fresh) {
      var name = fresh.dataset.leadLive;
      var old = leadPage.querySelector('[data-lead-live="' + name + '"]');
      if (!old) return;
      // the tags box filled itself from WhatsApp: it stays as it is, and is not part of the comparison
      var keepTags = old.querySelector('[data-tags]'), newTags = fresh.querySelector('[data-tags]');
      if (keepTags && newTags && keepTags.dataset.url === newTags.dataset.url) newTags.replaceWith(keepTags.cloneNode(true));
      else keepTags = null;
      if (old.outerHTML === fresh.outerHTML || regionBusy(old)) return;
      var scroller = old.querySelector('[data-tl-scroll]');
      var atBottom = scroller ? scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 40 : false;
      var top = scroller ? scroller.scrollTop : 0;
      var open = Array.prototype.map.call(old.querySelectorAll('details[open][data-fold]'), function (d) { return d.dataset.fold; });
      var node = document.importNode(fresh, true);
      old.replaceWith(node);
      if (keepTags) { var slot = node.querySelector('[data-tags]'); if (slot) slot.replaceWith(keepTags); }
      open.forEach(function (f) { var d = node.querySelector('details[data-fold="' + f + '"]'); if (d) d.open = true; });
      var sc = node.querySelector('[data-tl-scroll]');
      if (sc) sc.scrollTop = atBottom ? sc.scrollHeight : top;
      bindLeadNodes(node, leadPage);
    });
    syncBox(leadPage);
    var focusOn = document.body.classList.contains('crm-focus');
    document.querySelectorAll('[data-focus]').forEach(function (b) {
      b.innerHTML = focusOn ? '<i class="fa-solid fa-compress"></i>' : '<i class="fa-solid fa-expand"></i>';
    });
  }

  /* -------------------------------------------------------------- the lead card's own controls */
  // Two parts. bindLead hangs delegated listeners on the lead page once; bindLeadNodes touches only
  // the nodes that were just swapped in (the live regions), so nothing is bound twice. Beside the
  // WhatsApp inbox the card is replaced whole each time a conversation's lead is loaded
  // (window.CRM_bindLead).
  function bindLeadNodes(node, leadPage) {
    if (node.querySelector && node.querySelector('[data-tpl]')) renderFills(leadPage.querySelector('[data-box]') || node);
    // a tags box fills itself from WhatsApp (crm-people.js, loaded after this file)
    if (window.CRM_bindTags && node.querySelectorAll) node.querySelectorAll('[data-tags]').forEach(window.CRM_bindTags);
  }

  function bindLead(leadPage) {
    if (leadPage.dataset.bound) return;
    leadPage.dataset.bound = '1';
    var leadId = leadPage.dataset.lead;

    // the value / close date / forecast form in the lead's header
    leadPage.addEventListener('submit', function (e) {
      var f = e.target.closest('[data-money-form]');
      if (!f || !leadPage.contains(f)) return;
      e.preventDefault();
      var body = { amount: f.elements.amount.value.trim(), currency: f.elements.currency.value,
                   close_date: f.elements.close_date.value };
      if (!f.elements.forecast.disabled) body.forecast = f.elements.forecast.value;
      post('lead/' + leadId + '/money', body).then(function (d) {
        if (!d._ok) { toast(d.error || 'Could not save.', true); return; }
        leadPage.dataset.amount = body.amount;
        // saved: the typed values are no longer "half typed", so the live refresh may redraw the header now
        Array.prototype.forEach.call(f.querySelectorAll('input'), function (i) { i.defaultValue = i.value; });
        var det = f.closest('details'); if (det) det.open = false;
        toast(d.changed && d.changed.length ? 'Saved' : 'Nothing changed');
        reloadFor(leadPage, 150);
      });
    });

    leadPage.addEventListener('click', function (e) {
      var btn = e.target.closest('[data-journey] button[data-stage]');
      if (btn && leadPage.contains(btn)) {
        if (btn.classList.contains('now')) return;
        moveLead(leadId, btn, leadPage).then(function (d) { if (d) reloadFor(leadPage, 200); });
        return;
      }
      var lk = e.target.closest('[data-likelihood] [data-lk]');
      if (lk && leadPage.contains(lk)) {
        var on = lk.classList.contains('on');
        post('lead/' + leadId + '/update', { likelihood: on ? '' : lk.dataset.lk }).then(function (d) {
          if (!d._ok) { toast(d.error || 'Could not save.', true); return; }
          leadPage.querySelectorAll('[data-likelihood] [data-lk]').forEach(function (x) { x.classList.remove('on'); });
          if (!on) lk.classList.add('on');
          toast('Saved');
        });
        return;
      }
      var oc = e.target.closest('[data-call-outcomes] [data-outcome]');
      if (oc && leadPage.contains(oc)) {
        var group = oc.closest('[data-call-outcomes]');
        var outcome = oc.dataset.outcome;
        group.querySelectorAll('[data-outcome]').forEach(function (x) { x.disabled = true; });
        var again = function () { group.querySelectorAll('[data-outcome]').forEach(function (x) { x.disabled = false; }); };
        (outcome === 'call_back' ? askCallBack() : Promise.resolve({})).then(function (extra) {
          if (!extra) { again(); return; }
          logCall(leadId, outcome, group.dataset.task || null, extra).then(function (d) {
            if (!d) { again(); return; }
            afterCall(d, leadPage);
          });
        });
        return;
      }
      var wc = e.target.closest('[data-wrote-ch]');
      if (wc && leadPage.contains(wc)) {
        var was = wc.classList.contains('on');
        wc.closest('[data-wrote-chips]').querySelectorAll('[data-wrote-ch]').forEach(function (x) { x.classList.remove('on'); });
        if (!was) wc.classList.add('on');
        return;
      }
      var ed = e.target.closest('[data-act="edit-detail"]');
      if (ed && leadPage.contains(ed)) {
        var box = ed.closest('dd').querySelector('[data-detail-edit]');
        box.hidden = !box.hidden;
        var fld = box.querySelector('input, select');
        if (!box.hidden && fld) fld.focus();
        return;
      }
      var sp = e.target.closest('[data-act="set-product"]');
      if (sp && leadPage.contains(sp)) {
        var all = leadPage.querySelectorAll('[data-act="set-product"]');
        all.forEach(function (x) { x.disabled = true; });
        post('lead/' + leadId + '/update', { product: sp.dataset.product || '' }).then(function (d) {
          if (!d._ok) { all.forEach(function (x) { x.disabled = false; }); toast(d.error || 'Could not save.', true); return; }
          toast(d.message || 'Saved');
          if (d.moved && !leadPage.closest('[data-lead-panel]')) reloadSoon(1200); else reloadFor(leadPage, 1200);
        });
        return;
      }
      var ev = e.target.closest('[data-act="event"]');
      if (ev && leadPage.contains(ev)) {
        // "I sent the quote" / "I sent the payment link": the amount can be put right at the same time
        var amount0 = leadPage.dataset.amount || '';
        choose(ev.textContent.trim() + '?', 'This only notes it down. Nothing is sent to them.',
          [{ label: 'Save', value: 'yes' }], amountField(amount0)).then(function (v) {
          if (v !== 'yes') return;
          var body = { code: ev.dataset.code }, amt = askedAmount();
          if (amt && amt !== amount0) body.amount = amt;
          ev.disabled = true;
          post('lead/' + leadId + '/event', body).then(function (d) {
            if (!d._ok) { ev.disabled = false; toast(d.error || 'Could not save.', true); return; }
            if (body.amount) leadPage.dataset.amount = body.amount;
            toast(d.stage ? 'Saved. Moved to ' + d.stage : 'Saved');
            reloadFor(leadPage);
          });
        });
        return;
      }
      // the message box
      var bv = e.target.closest('[data-box-via]');
      if (bv && leadPage.contains(bv)) {
        var bx = leadPage.querySelector('[data-box]');
        bx.dataset.via = bv.dataset.via; delete bx.dataset.userMode; syncBox(leadPage);
        return;
      }
      var bm = e.target.closest('[data-box-mode]');
      if (bm && leadPage.contains(bm)) {
        leadPage.querySelector('[data-box]').dataset.userMode = bm.dataset.boxMode; syncBox(leadPage);
        return;
      }
      var qr = e.target.closest('[data-qr]');
      if (qr && leadPage.contains(qr)) {
        var ta = leadPage.querySelector('[data-box-input]');
        ta.value = ta.value.trim() ? ta.value.replace(/\s+$/, '') + '\n' + qr.dataset.text : qr.dataset.text;
        leadPage.querySelector('[data-box]').dataset.answer = qr.dataset.answer;
        var menu = qr.closest('details');
        if (menu) menu.open = false;
        ta.focus();
      }
    });

    leadPage.addEventListener('change', function (e) {
      var el = e.target;
      if (el.matches && el.matches('[data-detail]')) {
        // one lead detail, edited on the card (✎)
        var one = {}; one[el.dataset.detail] = el.value;
        post('lead/' + leadId + '/update', { details: one }).then(function (d) {
          if (!d._ok) { toast(d.error || 'Could not save.', true); return; }
          toast(d.message || 'Saved');
          reloadFor(leadPage, d.message ? 1800 : undefined);
        });
      } else if (el.matches && el.matches('[data-update]')) {
        var body = {}; body[el.dataset.update] = el.value;
        post('lead/' + leadId + '/update', body).then(function (d) {
          if (!d._ok) { toast(d.error || 'Could not save.', true); return; }
          toast(d.message || (el.dataset.update === 'owner_id' && d.whatsapp ? 'Saved. Their WhatsApp chat goes to them too' : 'Saved'));
          if (el.dataset.update === 'owner_id') {
            leadPage.querySelectorAll('[data-update="owner_id"]').forEach(function (x) { x.value = el.value; });
            reloadFor(leadPage);
          }
          if (el.dataset.update === 'departure_date' || el.dataset.update === 'ends_on') reloadFor(leadPage, d.message ? 1800 : undefined);
        });
      } else if (el.matches && el.matches('[data-tpl]')) {
        var box = leadPage.querySelector('[data-box]');
        if (box.dataset.taskTemplate && box.dataset.taskTemplate !== el.value) {
          delete box.dataset.task; delete box.dataset.taskTemplate;     // a different template is not that follow-up
        }
        var holder = box.querySelector('[data-tpl-fills]');
        if (holder) delete holder.dataset.for;
        renderFills(box);
        var region = box.querySelector('[data-lead-live="templates"]');
        if (region) region.dataset.touched = '1';
      }
    });

    leadPage.addEventListener('input', function (e) {
      if (e.target.closest && e.target.closest('[data-tpl-fills]')) {
        var box = leadPage.querySelector('[data-box]');
        renderPreview(box);
        var region = box.querySelector('[data-lead-live="templates"]');
        if (region) region.dataset.touched = '1';
      }
    });

    bindLeadNodes(leadPage, leadPage);
    var sc = leadPage.querySelector('[data-tl-scroll]');
    if (sc) sc.scrollTop = sc.scrollHeight;
    syncBox(leadPage);
  }
  window.CRM_bindLead = bindLead;
  document.querySelectorAll('[data-lead-page]').forEach(bindLead);
  if (page) {
    setTimeout(function () { refreshLive(true); }, 300);
    setInterval(function () { if (document.visibilityState === 'visible') refreshLive(); }, 8000);
    document.addEventListener('visibilitychange', function () { if (document.visibilityState === 'visible') refreshLive(); });
    // contract 10: the full-chat drawer says when a message appears in it; the page follows once the
    // webhook has landed here instead of on the next 8-second turn
    var activityT = null;
    window.addEventListener('message', function (e) {
      var f = document.querySelector('[data-chat-frame]');
      if (!f || e.source !== f.contentWindow || !e.data || e.data.type !== 'wacrm:activity') return;
      clearTimeout(activityT);
      activityT = setTimeout(function () { refreshLive(); }, 1500);
    });
  }

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
    // a column's count and money (and the strip above) follow a card that moved, without a reload. The server
    // counts more than the 60 cards a column shows, so the numbers move by the card, not by counting cards.
    var SYM = { INR: '₹', USD: '$', EUR: '€', GBP: '£', AED: 'AED ', CAD: 'C$', AUD: 'A$', SGD: 'S$' };
    var indian = function (n) {
      var s = String(n);
      if (s.length <= 3) return s;
      var head = s.slice(0, -3), parts = [];
      while (head.length > 2) { parts.unshift(head.slice(-2)); head = head.slice(0, -2); }
      if (head) parts.unshift(head);
      return parts.concat([s.slice(-3)]).join(',');
    };
    var moneyShort = function (n) {          // crm_money.money(compact=True): ₹29,400 / ₹1.2 L / ₹1.5 Cr
      var code = board.dataset.currency || 'INR', sym = SYM[code] || (code + ' ');
      var neg = n < 0 ? '-' : '';
      n = Math.abs(n);
      if (code === 'INR' && n >= 100000) {
        var big = n >= 10000000, v = n / (big ? 10000000 : 100000);
        return neg + sym + v.toFixed(1).replace(/\.0$/, '') + (big ? ' Cr' : ' L');
      }
      var whole = Math.round(n);
      return neg + sym + (code === 'INR' ? indian(whole) : whole.toLocaleString('en-US'));
    };
    var bump = function (stageId, count, value) {
      var col = board.querySelector('[data-col="' + stageId + '"]');
      if (col) {
        var c = col.querySelector('[data-col-count]'), v = col.querySelector('[data-col-value]');
        if (c) { c.dataset.colCount = Math.max(0, (+c.dataset.colCount || 0) + count); c.textContent = c.dataset.colCount; }
        if (v) {
          var sum = Math.max(0, (parseFloat(v.dataset.colSum) || 0) + value);
          v.dataset.colSum = sum;
          v.textContent = sum > 0 ? '· ' + moneyShort(sum) : '';
        }
      }
      var strip = document.querySelector('[data-strip="' + stageId + '"] b');
      if (strip) strip.textContent = Math.max(0, (+strip.textContent || 0) + count);
    };
    var recount = function (card, fromStage, toStage, res) {
      var before = parseFloat(card.dataset.value) || 0;
      var after = (res && res.value != null) ? (parseFloat(res.value) || 0) : before;
      card.dataset.value = after;
      bump(fromStage, -1, -before);
      bump(toStage, 1, after);
      // and it takes its new stage's colour: the column's r-* (what the stage means)
      var col = card.closest('.crm-col'), role = col && (col.className.match(/\br-[a-z]+/) || [])[0];
      if (role) card.className = card.className.replace(/\br-[a-z]+/g, '').replace(/\s+/g, ' ').trim() + ' ' + role;
    };
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
      var fromStage = card.closest('[data-drop]').dataset.stage;
      moveLead(card.dataset.lead, d, board, card.dataset.amount || '').then(function (res) {
        if (!res) return;
        d.insertBefore(card, d.firstChild);
        recount(card, fromStage, d.dataset.stage, res);
      });
    });
    // a drag that ends on a card must not also open it
    board.addEventListener('click', function (e) {
      if (moved && e.target.closest('.crm-card')) { e.preventDefault(); moved = false; }
    }, true);

    // the buttons inside a card and a column's ⋯ menu: dragging is bound to the card, so they stop the
    // click from opening the lead
    var stages = [];
    try { stages = JSON.parse(board.dataset.stages || '[]'); } catch (err) { stages = []; }
    board.addEventListener('click', function (e) {
      var b = e.target.closest('button[data-act]');
      if (!b) return;
      e.preventDefault(); e.stopPropagation();
      if (b.dataset.act === 'move-to') {
        var card = b.closest('.crm-card'), here = card.closest('[data-drop]');
        var name = (card.querySelector('.nm') || {}).textContent || 'this lead';
        choose('Move ' + name + ' to…', '', stages.filter(function (s) { return String(s.stage) !== here.dataset.stage; })
          .map(function (s) { return { label: s.name, value: s }; })).then(function (s) {
          if (!s) return;
          moveLead(card.dataset.lead, s, board, card.dataset.amount || '').then(function (res) {
            if (!res) return;
            var to = board.querySelector('[data-drop][data-stage="' + s.stage + '"]');
            if (to) to.insertBefore(card, to.firstChild); else card.remove();
            recount(card, here.dataset.stage, s.stage, res);
          });
        });
      } else if (b.dataset.act === 'show-more') {
        // the cards past the first 20 are already on the page, only hidden
        var drop = b.closest('[data-drop]');
        drop.querySelectorAll('.crm-card[data-extra]').forEach(function (c) { c.hidden = false; c.removeAttribute('data-extra'); });
        b.remove();
      } else if (b.dataset.act === 'stage-broadcast') {
        var can = +b.dataset.can > 0;
        choose('Message everyone in this stage', b.dataset.reach || '',
               can ? [{ label: 'Open Broadcasts', value: 'go' }] : []).then(function (v) {
          if (v === 'go') window.location.href = b.dataset.url;
        });
      }
    }, true);

    // How we sell links here: scroll to the stage and outline it
    if (board.dataset.focusStage) {
      var col = board.querySelector('[data-col="' + board.dataset.focusStage + '"]');
      if (col) { col.classList.add('outlined'); col.scrollIntoView({ inline: 'center', block: 'nearest' }); }
    }
    // a phone with no saved choice starts on the list
    if (board.dataset.viewAuto === '1' && window.matchMedia && window.matchMedia('(max-width: 640px)').matches
        && board.dataset.listUrl) {
      location.replace(board.dataset.listUrl);
    }
  }

  /* -------------------------------------------------------------- the list: tick boxes, give, move */
  var bulk = document.querySelector('[data-bulk]');
  if (bulk) {
    var bar = bulk.querySelector('[data-bulk-bar]'), count = bulk.querySelector('[data-bulk-count]');
    var staff = [], lstages = [];
    try { staff = JSON.parse(bulk.dataset.staff || '[]'); lstages = JSON.parse(bulk.dataset.stages || '[]'); } catch (err) { /* ignore */ }
    var ticked = function () {
      return Array.prototype.map.call(bulk.querySelectorAll('[data-bulk-one]:checked'), function (c) { return +c.value; });
    };
    var syncBulk = function () {
      var n = ticked().length;
      if (bar) bar.hidden = !n;
      if (count) count.textContent = n + ' chosen';
    };
    bulk.addEventListener('change', function (e) {
      if (e.target.matches('[data-bulk-all]')) {
        bulk.querySelectorAll('[data-bulk-one]').forEach(function (c) { c.checked = e.target.checked; });
      }
      syncBulk();
    });
    var sendBulk = function (body) {
      return post('leads/bulk', body).then(function (d) {
        if (!d._ok) { toast(d.error || 'Could not do that.', true); return d; }
        toast(d.message || 'Done');
        reloadSoon(700);
        return d;
      });
    };
    bulk.addEventListener('click', function (e) {
      var b = e.target.closest('button[data-act]');
      if (!b) return;
      var ids = ticked();
      if (!ids.length) return;
      if (b.dataset.act === 'bulk-give') {
        choose('Give them to…', '', staff.map(function (s) { return { label: s[1], value: s[0] }; })).then(function (v) {
          if (v === null) return;
          sendBulk({ lead_ids: ids, action: 'give', owner_id: v });
        });
      } else if (b.dataset.act === 'bulk-move') {
        choose('Move them to…', '', lstages.map(function (s) { return { label: s.name, value: s }; })).then(function (s) {
          if (!s) return;
          var go = function (reason) {
            return post('leads/bulk', { lead_ids: ids, action: 'move', stage_id: s.stage, reason: reason || '' }).then(function (d) {
              if (!d._ok && d.need_reason) {
                // a finish line: ask why once, with the pipeline's own reasons
                var reasons = (d.reasons && d.reasons.length) ? d.reasons : ['No response', 'Not interested'];
                return choose('Why did we lose them?', '', reasons.map(function (r) { return { label: r, value: r }; }))
                  .then(function (r) { if (r) go(r); });
              }
              if (!d._ok) { toast(d.error || 'Could not do that.', true); return null; }
              toast(d.message || 'Done');
              if (d.not_moved_url) { setTimeout(function () { location.href = d.not_moved_url; }, 2500); return d; }
              reloadSoon(700);
              return d;
            });
          };
          go('');
        });
      }
    });
  }

  /* -------------------------------------------------------------- phones: one fold open at a time on My day */
  if (window.matchMedia && window.matchMedia('(max-width: 640px)').matches) {
    var folds = document.querySelectorAll('details[data-acc]');
    var firstFull = Array.prototype.find.call(folds, function (d) { return d.querySelector('.crm-task, .crm-wait, .chips'); });
    folds.forEach(function (d) { if (d !== firstFull) d.removeAttribute('open'); });
  }

  /* -------------------------------------------------------------- focus mode */
  // every [data-focus] button does it: a page header's Full screen button
  function setFocus(on) {
    document.body.classList.toggle('crm-focus', on);
    document.querySelectorAll('[data-focus]').forEach(function (b) {
      b.innerHTML = on ? '<i class="fa-solid fa-compress"></i>' : '<i class="fa-solid fa-expand"></i>';
    });
    try { localStorage.setItem('crm-focus', on ? '1' : ''); } catch (e) { /* private window */ }
  }
  if (document.querySelector('[data-focus]')) {
    try { if (localStorage.getItem('crm-focus') === '1') setFocus(true); } catch (e) { /* ignore */ }
    document.addEventListener('click', function (e) {
      if (e.target.closest('[data-focus]')) setFocus(!document.body.classList.contains('crm-focus'));
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && document.body.classList.contains('crm-drawer-open')) {
        var lp = document.querySelector('[data-lead-page]');
        if (lp) { closeChat(lp); return; }
      }
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
      // a big tile says who ticked it and when, and the count above it moves: draw the page again
      if (t.hasAttribute('data-tile')) { t.classList.toggle('on', !!d.ticked); reloadSoon(250); return; }
      t.classList.toggle('on', !!d.ticked);
      t.textContent = d.ticked ? '✓' : '';
      if (d.ticked) t.classList.remove('miss');
    });
  });

  /* -------------------------------------------------------------- the check, live: a new half hour draws the page
     again; with "Remind me each half hour" (this browser) a browser notice says so too */
  var hcLive = document.querySelector('[data-hc-live]');
  var hcRemind = document.querySelector('[data-hc-remind]');
  var REMIND = 'crm-check-remind';
  var reminding = function () { try { return localStorage.getItem(REMIND) === '1'; } catch (e) { return false; } };
  if (hcRemind) {
    hcRemind.checked = reminding();
    hcRemind.addEventListener('change', function () {
      try { localStorage.setItem(REMIND, hcRemind.checked ? '1' : '0'); } catch (e) { /* private window */ }
      if (hcRemind.checked && window.Notification && Notification.permission === 'default') Notification.requestPermission();
    });
  }
  if (hcLive) {
    var untilNext = (+hcLive.dataset.left || 30) * 60000 - new Date().getSeconds() * 1000;
    setTimeout(function () {
      if (reminding() && window.Notification && Notification.permission === 'granted') {
        new Notification('Half-hourly check · ' + hcLive.dataset.slotLabel, { body: 'A new half hour: look at each inbox and tick it.' });
      }
      location.reload();
    }, Math.max(untilNext, 5000) + 2000);
  }

  /* -------------------------------------------------------------- slow forms say they are working */
  document.querySelectorAll('form[data-busy]').forEach(function (f) {
    f.addEventListener('submit', function () {
      var b = f.querySelector('button');
      if (b) { b.disabled = true; b.textContent = 'Working… this can take a minute'; }
    });
  });

  /* -------------------------------------------------------------- add a lead: the chosen product's details */
  var addForm = document.querySelector('[data-add-lead]');
  if (addForm) {
    // the card on the right says how the lead will show: where it came from, what they want, who has it
    var said = function (name, box) {
      var on = addForm.querySelector('input[name=' + name + ']:checked');
      var dd = addForm.querySelector(box);
      if (!dd) return;
      dd.textContent = on ? on.dataset.label || '' : (name === 'source' ? 'Choose where they came from' : '—');
      dd.classList.toggle('muted', !on);
    };
    var productPicked = false;          // somebody chose the product themselves: a source no longer changes it
    var productAuto = false;            // the product shown was filled in by the source
    addForm.addEventListener('change', function (e) {
      if (e.target.name === 'source') {
        said('source', '[data-al-src]');
        if (productPicked) return;
        var code = e.target.dataset.product;
        var tile = code && addForm.querySelector('input[name=product][value="' + code + '"]');
        if (tile) {
          if (!tile.checked) {
            tile.checked = true;
            tile.dispatchEvent(new Event('change', { bubbles: true }));
          }
          productAuto = true;
        } else if (productAuto) {          // a source that says no product: take back the one an earlier source chose
          addForm.querySelectorAll('input[name=product]').forEach(function (r) { r.checked = false; });
          addForm.querySelectorAll('[data-add-fields]').forEach(function (g) { g.hidden = true; });
          said('product', '[data-al-product]');
          productAuto = false;
        }
        return;
      }
      if (e.target.name === 'owner' || e.target.name === 'owner_id') {
        var pick = addForm.querySelector('[data-owner-pick]');
        var dd = addForm.querySelector('[data-al-owner]');
        var who = addForm.querySelector('input[name=owner]:checked');
        if (dd && who) dd.textContent = who.value === 'pick' && pick && pick.value ? pick.options[pick.selectedIndex].text : who.dataset.label;
        return;
      }
      if (e.target.name !== 'product') return;
      if (e.isTrusted) productPicked = true;
      said('product', '[data-al-product]');
      addForm.querySelectorAll('[data-add-fields]').forEach(function (g) { g.hidden = g.dataset.addFields !== e.target.value; });
      // the product's usual price, unless somebody typed an amount themselves
      var amt = addForm.querySelector('[data-add-amount]'), cur = addForm.querySelector('[data-add-currency]');
      if (amt && amt.dataset.typed !== '1') {
        amt.value = e.target.dataset.price || '';
        if (cur && e.target.dataset.currency) cur.value = e.target.dataset.currency;
      }
    });
    var typed = addForm.querySelector('[data-add-amount]');
    if (typed) typed.addEventListener('input', function () { typed.dataset.typed = '1'; });
    // shown again after an error, or opened with a source or product: the card says so from the start
    said('source', '[data-al-src]');
    said('product', '[data-al-product]');
    var ownerNow = addForm.querySelector('input[name=owner]:checked');
    if (ownerNow) ownerNow.dispatchEvent(new Event('change', { bubbles: true }));
  }

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
})();
