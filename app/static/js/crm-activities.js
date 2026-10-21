/* Tasks, calls, meetings and the e-mail composer (lead page and contact page), and the Calendar's List tab.
   Vanilla, delegated. Uses the helpers crm.js shares on window.CRM (post, toast). Nothing here sends
   anything to a customer without the person pressing Send in the composer. */
(function () {
  'use strict';
  var box = document.querySelector('[data-tasks-box]');
  var CRM = window.CRM || {};

  function csrf() { return (document.querySelector('meta[name="csrf-token"]') || {}).content || ''; }
  function post(url, body) {
    return fetch(url, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf(), 'Accept': 'application/json' },
      body: JSON.stringify(body || {})
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) { d._ok = r.ok; return d; });
    }).catch(function () { return { _ok: false, error: 'No connection. Please try again.' }; });
  }
  function toast(msg, bad) {
    if (window.CRM && window.CRM.toast) { window.CRM.toast(msg, bad); return; }
    window.alert(msg);
  }
  function show(el, text) { if (!el) return; el.textContent = text || ''; el.hidden = !text; }
  function fromPath(base, id) { return base.replace(/\/0\//, '/' + id + '/'); }

  /* ------------------------------------------------------------ the task form */
  var dlg = document.getElementById('task-dialog');
  var form = dlg && dlg.querySelector('[data-tk-form]');
  var editing = null;

  function syncKind() {
    if (!form) return;
    var meeting = form.elements.kind.value === 'meeting';
    form.querySelectorAll('[data-tk-meeting]').forEach(function (el) { el.hidden = !meeting; });
  }

  function openForm(task) {
    if (!dlg) return;
    editing = task || null;
    form.reset();
    form.querySelector('[data-tk-title]').textContent = task ? 'Edit task' : 'New task';
    var defaultDue = form.elements.due.defaultValue;
    if (task) {
      ['title', 'kind', 'priority', 'due', 'ends', 'location', 'notes'].forEach(function (k) {
        if (form.elements[k]) form.elements[k].value = task[k] || '';
      });
      if (task.owner_id) form.elements.owner_id.value = String(task.owner_id);
    } else {
      form.elements.due.value = defaultDue;
    }
    show(form.querySelector('[data-tk-err]'), '');
    syncKind();
    dlg.showModal();
    form.elements.title.focus();
  }

  if (form) {
    form.elements.kind.addEventListener('change', syncKind);
    dlg.querySelector('[data-tk-cancel]').addEventListener('click', function () { dlg.close(); });
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var body = {};
      Array.prototype.forEach.call(form.elements, function (el) { if (el.name) body[el.name] = el.value; });
      var url;
      if (editing) {
        url = fromPath(box.dataset.editBase, editing.id);
      } else {
        url = box.dataset.add;
        if (box.dataset.lead) body.lead_id = box.dataset.lead; else body.person_id = box.dataset.person;
      }
      post(url, body).then(function (d) {
        if (!d._ok) { show(form.querySelector('[data-tk-err]'), d.error || 'That did not work.'); return; }
        dlg.close();
        toast(editing ? 'Saved' : 'Task added');
        setTimeout(function () { location.reload(); }, 500);
      });
    });
  }

  /* ------------------------------------------------------------ the e-mail composer */
  var edlg = document.getElementById('email-dialog');
  var eform = edlg && edlg.querySelector('[data-em-form]');
  var state = { canSend: false, answers: [] };

  function mailtoHref() {
    var to = eform.querySelector('#em-to').value;
    return 'mailto:' + encodeURIComponent(to).replace(/%40/g, '@') + '?subject=' + encodeURIComponent(eform.elements.subject.value) +
      '&body=' + encodeURIComponent(eform.elements.body.value);
  }

  function openComposer() {
    if (!edlg || !box) return;
    var q = box.dataset.lead ? 'lead_id=' + box.dataset.lead : 'person_id=' + box.dataset.person;
    fetch(box.dataset.compose + '?' + q, { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        state.canSend = !!d.can_send;
        eform.reset();
        var sel = eform.querySelector('[data-em-answers]');
        sel.innerHTML = '<option value="">Choose…</option>';
        state.answers = d.answers || [];
        state.answers.forEach(function (a, i) {
          var o = document.createElement('option');
          o.value = String(i); o.textContent = a.title; sel.appendChild(o);
        });
        eform.querySelector('#em-to').value = d.to || '';
        show(eform.querySelector('[data-em-err]'), '');
        var note = eform.querySelector('[data-em-note]');
        var noAddress = !d.to;
        show(note, noAddress ? 'This person has no e-mail address yet. Add one under Edit details.' :
          (!state.canSend ? 'This server is not set up to send e-mail to customers. Open it in your own mail app instead.' : ''));
        eform.querySelector('[data-em-send]').hidden = !state.canSend || noAddress;
        eform.querySelector('[data-em-mailto]').hidden = noAddress || state.canSend;
        eform.querySelector('[data-em-logrow]').hidden = noAddress || state.canSend;
        edlg.showModal();
      })
      .catch(function () { toast('Could not open the e-mail box.', true); });
  }

  if (eform) {
    eform.querySelector('[data-em-answers]').addEventListener('change', function (e) {
      var a = state.answers[+e.target.value];
      if (!a) return;
      var ta = eform.elements.body;
      ta.value = ta.value ? ta.value + '\n\n' + a.text : a.text;
      eform.dataset.answer = '';
      var chosen = e.target.options[e.target.selectedIndex];
      eform.dataset.answer = chosen ? String(a.id) : '';
    });
    edlg.querySelector('[data-em-cancel]').addEventListener('click', function () { edlg.close(); });
    var link = eform.querySelector('[data-em-mailto]');
    link.addEventListener('click', function () {
      link.href = mailtoHref();
      // the mail app opens by itself; the line on the timeline is only written when they tick "Log it"
      if (eform.querySelector('[data-em-log]').checked) {
        post(box.dataset.send, { lead_id: box.dataset.lead || null, person_id: box.dataset.person, own_app: true, log: true,
          subject: eform.elements.subject.value, answer_id: eform.dataset.answer || null }).then(function (d) {
          if (d._ok) toast('Logged: e-mail written in own mail app');
        });
      }
    });
    eform.addEventListener('submit', function (e) {
      e.preventDefault();
      if (!state.canSend) return;
      var btn = eform.querySelector('[data-em-send]');
      btn.disabled = true;
      post(box.dataset.send, { lead_id: box.dataset.lead || null, person_id: box.dataset.person,
        subject: eform.elements.subject.value, body: eform.elements.body.value, answer_id: eform.dataset.answer || null })
        .then(function (d) {
          btn.disabled = false;
          if (!d._ok) { show(eform.querySelector('[data-em-err]'), d.error || 'The e-mail was not sent.'); return; }
          edlg.close();
          toast('E-mail sent');
          setTimeout(function () { location.reload(); }, 600);
        });
    });
  }

  /* ------------------------------------------------------------ clicks */
  document.addEventListener('click', function (e) {
    var b;
    if ((b = e.target.closest('[data-tk-new]'))) { openForm(null); return; }
    if ((b = e.target.closest('[data-tk-edit]'))) {
      var row = b.closest('[data-json]');
      try { openForm(JSON.parse(row.dataset.json)); } catch (err) { /* a broken row is not editable */ }
      return;
    }
    if ((b = e.target.closest('[data-tk-del]'))) {
      var id = b.dataset.tkDel;
      var del = function () {
        post(fromPath(box.dataset.deleteBase, id), {}).then(function (d) {
          if (!d._ok) { toast(d.error || 'Could not delete.', true); return; }
          toast('Deleted'); setTimeout(function () { location.reload(); }, 400);
        });
      };
      // asked on the page (the shared chooser), never with the browser's own confirm box
      var ask = window.CRM && window.CRM.choose;
      if (!ask) { del(); return; }
      ask('Delete this task?', 'It goes from the list and the calendar.', [{ label: 'Yes, delete', value: 'yes' }])
        .then(function (v) { if (v === 'yes') del(); });
      return;
    }
    if ((b = e.target.closest('[data-tk-done]'))) {
      post(fromPath(box.dataset.doneBase, b.dataset.tkDone), {})
        .then(function (d) {
          if (!d._ok) { toast(d.error || 'That did not work.', true); return; }
          toast('Done'); setTimeout(function () { location.reload(); }, 400);
        });
      return;
    }
    if ((b = e.target.closest('[data-email-open]')) && box) { e.preventDefault(); openComposer(); return; }
  });
})();
