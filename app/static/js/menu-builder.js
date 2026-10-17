/* Team -> Menu builder (workspace/menu.html). The editor is drawn once from the saved layout; after that the
   page itself is the layout -- drag, "Move to", rename, hide -- and readLayout() turns it back into
   {sections, labels, hidden} for the preview (POST, nothing saved) and for Save. The server cleans whatever
   comes back (access.clean_layout), so nothing here can lose a line: one left out returns to its usual place. */
(function () {
  'use strict';
  var root = document.querySelector('[data-menu-builder]');
  if (!root) return;
  var data = JSON.parse(document.getElementById('mnu-data').textContent);
  var LINES = {};
  data.lines.forEach(function (l) { LINES[l.key] = l; });
  var sectionsEl = root.querySelector('[data-mnu-sections]');
  var form = document.querySelector('[data-mnu-form]');
  var dirtyEl = document.querySelector('[data-mnu-dirty]');
  var roleSel = root.querySelector('[data-mnu-role]');
  var roleLink = root.querySelector('[data-mnu-role-link]');
  var previewEl = root.querySelector('[data-mnu-preview]');
  var csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content
    || (form.querySelector('[name="csrf_token"]') || {}).value || '';
  var dirty = false, timer = null, seq = 0, made = 0;

  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'text') n.textContent = attrs[k];
      else if (k === 'cls') n.className = attrs[k];
      else n.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (c) { if (c) n.appendChild(c); });
    return n;
  }
  function ic(icon) { return icon.indexOf(' ') > -1 ? icon : 'fa-solid ' + icon; }
  function words(icon) { return icon.replace(/^fa-/, '').replace(/-/g, ' '); }

  /* ------------------------------------------------------------------ drawing */

  function iconPicker(value) {
    var shown = el('i', { cls: ic(value), 'aria-hidden': 'true' });
    var sel = el('select', { cls: 'mnu-icon', 'data-f': 'icon', 'aria-label': 'Icon' });
    var list = data.icons.indexOf(value) > -1 ? data.icons : [value].concat(data.icons);
    list.forEach(function (i) {
      var o = el('option', { value: i, text: words(i) });
      if (i === value) o.selected = true;
      sel.appendChild(o);
    });
    sel.addEventListener('change', function () { shown.className = ic(sel.value); });
    return el('span', { cls: 'mnu-icon-pick' }, [shown, sel]);
  }

  function tool(act, icon, title) {
    return el('button', { type: 'button', cls: 'cb sm quiet', 'data-act': act, title: title, 'aria-label': title },
      [el('i', { cls: 'fa-solid ' + icon, 'aria-hidden': 'true' })]);
  }

  function lineEl(key) {
    var l = LINES[key];
    if (!l) return null;
    var label = el('input', { type: 'text', cls: 'mnu-label', 'data-f': 'label', maxlength: '40', placeholder: l.label,
      'aria-label': 'Name of ' + l.label, title: 'Leave empty to keep “' + l.label + '”' });
    label.value = (data.layout.labels || {})[key] || '';
    var hide = el('input', { type: 'checkbox', 'data-f': 'hidden' });
    hide.checked = (data.layout.hidden || []).indexOf(key) > -1;
    var li = el('li', { cls: 'mnu-line' + (hide.checked ? ' is-hidden' : ''), 'data-page': key, title: l.tip || '' }, [
      el('span', { cls: 'mnu-grip', draggable: 'true', 'data-grip': 'line', title: 'Drag to move', 'aria-hidden': 'true', text: '⠿' }),
      el('i', { cls: ic(l.icon), 'aria-hidden': 'true' }),
      label,
      el('small', { cls: 'mnu-area', text: l.area }),
      el('select', { cls: 'mnu-move', 'data-move': '', 'aria-label': 'Move ' + l.label + ' to' }),
      el('label', { cls: 'mnu-hide', title: 'Leave it out of the menu. It still opens from its buttons and links.' },
        [hide, document.createTextNode(' Hide')])
    ]);
    hide.addEventListener('change', function () { li.classList.toggle('is-hidden', hide.checked); });
    return li;
  }

  function linesEl(keys) {
    return el('ul', { cls: 'mnu-lines', 'data-drop': '' }, (keys || []).map(lineEl));
  }

  function subEl(b) {
    var name = el('input', { type: 'text', cls: 'mnu-name', 'data-f': 'label', maxlength: '40', 'aria-label': 'Sub-menu name' });
    name.value = b.label;
    return el('div', { cls: 'mnu-sub', 'data-key': b.key }, [
      el('header', { cls: 'mnu-sub-head' }, [
        el('span', { cls: 'mnu-grip', draggable: 'true', 'data-grip': 'sub', title: 'Drag to move', 'aria-hidden': 'true', text: '⠿' }),
        iconPicker(b.icon), name,
        el('div', { cls: 'mnu-tools' }, [tool('up', 'fa-arrow-up', 'Move up'), tool('down', 'fa-arrow-down', 'Move down'),
          tool('del-sub', 'fa-trash-can', 'Remove this sub-menu (its lines move to the one beside it)')])
      ]),
      linesEl(b.pages)
    ]);
  }

  function sectionEl(s) {
    var name = el('input', { type: 'text', cls: 'mnu-name', 'data-f': 'label', maxlength: '40', 'aria-label': 'Section name' });
    name.value = s.label;
    var body = s.subs && s.subs.length ? el('div', { cls: 'mnu-subs' }, s.subs.map(subEl)) : linesEl(s.pages);
    return el('section', { cls: 'mnu-sec', 'data-key': s.key }, [
      el('header', { cls: 'mnu-sec-head' }, [
        el('span', { cls: 'mnu-grip', draggable: 'true', 'data-grip': 'sec', title: 'Drag to move', 'aria-hidden': 'true', text: '⠿' }),
        iconPicker(s.icon), name,
        el('div', { cls: 'mnu-tools' }, [tool('up', 'fa-arrow-up', 'Move up'), tool('down', 'fa-arrow-down', 'Move down'),
          el('button', { type: 'button', cls: 'cb sm', 'data-act': 'add-sub', text: '+ Sub-menu' }),
          tool('del-sec', 'fa-trash-can', 'Delete this section (move its lines out first)')])
      ]),
      body
    ]);
  }

  /* ------------------------------------------------------------------ reading it back */

  function val(scope, f) {
    var n = scope.querySelector(':scope > header [data-f="' + f + '"]');
    return n ? n.value : '';
  }

  function readLayout() {
    var labels = {}, hidden = [];
    function keys(ul) {
      return Array.prototype.map.call(ul.querySelectorAll(':scope > .mnu-line'), function (li) {
        var k = li.dataset.page, name = li.querySelector('[data-f="label"]').value.trim();
        if (name) labels[k] = name;
        if (li.querySelector('[data-f="hidden"]').checked) hidden.push(k);
        return k;
      });
    }
    var sections = Array.prototype.map.call(sectionsEl.querySelectorAll(':scope > .mnu-sec'), function (sec) {
      var s = { key: sec.dataset.key, label: val(sec, 'label'), icon: val(sec, 'icon') };
      var subs = sec.querySelectorAll(':scope > .mnu-subs > .mnu-sub');
      if (subs.length) {
        s.subs = Array.prototype.map.call(subs, function (sub) {
          return { key: sub.dataset.key, label: val(sub, 'label'), icon: val(sub, 'icon'),
                   pages: keys(sub.querySelector(':scope > .mnu-lines')) };
        });
      } else {
        s.pages = keys(sec.querySelector(':scope > .mnu-lines'));
      }
      return s;
    });
    return { sections: sections, labels: labels, hidden: hidden };
  }

  /* ------------------------------------------------------------------ after every change */

  function refreshMoves() {
    var targets = [];
    sectionsEl.querySelectorAll(':scope > .mnu-sec').forEach(function (sec, si) {
      var sname = val(sec, 'label') || 'Section';
      var subs = sec.querySelectorAll(':scope > .mnu-subs > .mnu-sub');
      if (subs.length) subs.forEach(function (sub, bi) {
        targets.push({ id: si + '.' + bi, text: sname + ' › ' + (val(sub, 'label') || 'Sub-menu'), ul: sub.querySelector(':scope > .mnu-lines') });
      });
      else targets.push({ id: si + '', text: sname, ul: sec.querySelector(':scope > .mnu-lines') });
    });
    sectionsEl.querySelectorAll('select[data-move]').forEach(function (sel) {
      var here = sel.closest('.mnu-lines');
      sel.innerHTML = '';
      sel.appendChild(el('option', { value: '', text: 'Move to…' }));
      targets.forEach(function (t) {
        if (t.ul !== here) sel.appendChild(el('option', { value: t.id, text: t.text }));
      });
      sel._targets = targets;
    });
    sectionsEl.querySelectorAll(':scope > .mnu-sec').forEach(function (sec) {
      var del = sec.querySelector(':scope > header [data-act="del-sec"]');
      var empty = !sec.querySelector('.mnu-line');
      del.disabled = !empty;
      del.title = empty ? 'Delete this section' : 'Move its lines out first, then delete it';
    });
  }

  function changed() {
    dirty = true;
    dirtyEl.hidden = false;
    refreshMoves();
    clearTimeout(timer);
    timer = setTimeout(preview, 300);
  }

  function preview() {
    var mine = ++seq;
    fetch(root.dataset.preview, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf, Accept: 'application/json' },
      body: JSON.stringify({ layout: readLayout(), role: roleSel ? roleSel.value : null })
    }).then(function (r) { return r.ok ? r.json() : null; }).then(function (d) {
      if (mine !== seq || !d) return;
      drawPreview(d.groups || []);
    }).catch(function () { /* the editor still works; the preview catches up on the next change */ });
  }

  function drawPreview(groups) {
    previewEl.innerHTML = '';
    if (!groups.length) {
      previewEl.appendChild(el('p', { cls: 'pv-none', text: 'This role has no lines in the menu.' }));
      return;
    }
    groups.forEach(function (g) {
      previewEl.appendChild(el('div', { cls: 'pv-sec' }, [el('i', { cls: ic(g.icon), 'aria-hidden': 'true' }), el('span', { text: g.label })]));
      var line = function (inSub) {
        return function (i) {
          previewEl.appendChild(el('div', { cls: 'pv-line' + (inSub ? ' in-sub' : '') },
            [el('i', { cls: ic(i.icon), 'aria-hidden': 'true' }), el('span', { text: i.label })]));
        };
      };
      if (g.subs && g.subs.length) {
        g.subs.forEach(function (s) {
          previewEl.appendChild(el('div', { cls: 'pv-sub' }, [el('i', { cls: ic(s.icon), 'aria-hidden': 'true' }), el('span', { text: s.label })]));
          s.items.forEach(line(true));
        });
      } else {
        g.items.forEach(line(false));
      }
    });
  }

  /* ------------------------------------------------------------------ buttons */

  function move(node, dir) {
    var sib = dir < 0 ? node.previousElementSibling : node.nextElementSibling;
    if (!sib) return;
    node.parentNode.insertBefore(node, dir < 0 ? sib : sib.nextElementSibling);
  }

  root.addEventListener('click', function (e) {
    var b = e.target.closest('[data-act]');
    if (!b || !root.contains(b)) return;
    var sec = b.closest('.mnu-sec'), sub = b.closest('.mnu-sub');
    var act = b.dataset.act;
    if (act === 'up' || act === 'down') move(sub || sec, act === 'up' ? -1 : 1);
    else if (act === 'add-sub') {
      var subs = sec.querySelector(':scope > .mnu-subs');
      if (!subs) {           // a plain section becomes sub-menus: what it had goes in the first one
        var flat = sec.querySelector(':scope > .mnu-lines');
        subs = el('div', { cls: 'mnu-subs' });
        var first = subEl({ key: 'main', label: 'General', icon: 'fa-folder-open', pages: [] });
        first.querySelector('.mnu-lines').replaceWith(flat);
        subs.appendChild(first);
        sec.appendChild(subs);
      }
      var fresh = subEl({ key: 'sub' + (++made) + Date.now() % 10000, label: 'New sub-menu', icon: 'fa-folder-open', pages: [] });
      subs.appendChild(fresh);
      fresh.querySelector('[data-f="label"]').select();
    } else if (act === 'del-sub') {
      var into = sub.previousElementSibling || sub.nextElementSibling;
      var lines = sub.querySelector(':scope > .mnu-lines');
      if (into) {
        var target = into.querySelector(':scope > .mnu-lines');
        while (lines.firstChild) target.appendChild(lines.firstChild);
        sub.remove();
      } else {                // the last one: the section goes back to plain lines
        sub.parentNode.replaceWith(lines);
      }
    } else if (act === 'del-sec') {
      if (sec.querySelector('.mnu-line')) return;
      sec.remove();
    } else return;
    changed();
  });

  root.querySelector('[data-mnu-add-section]').addEventListener('click', function () {
    var s = sectionEl({ key: 'new' + (++made) + Date.now() % 10000, label: 'New section', icon: 'fa-folder', pages: [] });
    sectionsEl.appendChild(s);
    s.querySelector('[data-f="label"]').select();
    changed();
  });

  sectionsEl.addEventListener('change', function (e) {
    var sel = e.target.closest('select[data-move]');
    if (sel && sel.value) {
      var t = (sel._targets || []).filter(function (x) { return x.id === sel.value; })[0];
      if (t) t.ul.appendChild(sel.closest('.mnu-line'));
    }
    changed();
  });
  sectionsEl.addEventListener('input', function (e) { if (e.target.matches('input[type="text"]')) changed(); });
  if (roleSel) roleSel.addEventListener('change', function () {
    if (roleLink) roleLink.href = data.roleUrl.replace(/0$/, roleSel.value);
    preview();
  });

  /* ------------------------------------------------------------------ dragging */

  var drag = null;
  sectionsEl.addEventListener('dragstart', function (e) {
    var g = e.target.closest && e.target.closest('[data-grip]');
    if (!g) return;
    var kind = g.dataset.grip;
    var node = g.closest(kind === 'line' ? '.mnu-line' : kind === 'sub' ? '.mnu-sub' : '.mnu-sec');
    drag = { kind: kind, node: node };
    node.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
    try { e.dataTransfer.setData('text/plain', kind); e.dataTransfer.setDragImage(node, 16, 16); } catch (x) { /* old browsers */ }
  });
  sectionsEl.addEventListener('dragover', function (e) {
    if (!drag) return;
    var over, list;
    if (drag.kind === 'line') {
      over = e.target.closest('.mnu-line');
      list = over ? over.parentNode : e.target.closest('.mnu-lines');
    } else if (drag.kind === 'sub') {
      over = e.target.closest('.mnu-sub');
      list = over && over.parentNode === drag.node.parentNode ? over.parentNode : null;
    } else {
      over = e.target.closest('.mnu-sec');
      list = over ? sectionsEl : null;
    }
    if (!list) return;
    e.preventDefault();
    if (!over || over === drag.node) { if (!over && drag.kind === 'line') list.appendChild(drag.node); return; }
    var r = over.getBoundingClientRect();
    list.insertBefore(drag.node, e.clientY < r.top + r.height / 2 ? over : over.nextElementSibling);
  });
  sectionsEl.addEventListener('drop', function (e) { if (drag) e.preventDefault(); });
  sectionsEl.addEventListener('dragend', function () {
    if (!drag) return;
    drag.node.classList.remove('dragging');
    drag = null;
    changed();
  });

  /* ------------------------------------------------------------------ save */

  form.addEventListener('submit', function () {
    form.querySelector('[data-mnu-out]').value = JSON.stringify(readLayout());
    dirty = false;
  });
  window.addEventListener('beforeunload', function (e) {
    if (dirty) { e.preventDefault(); e.returnValue = ''; }
  });

  data.layout.sections.forEach(function (s) { sectionsEl.appendChild(sectionEl(s)); });
  refreshMoves();
  preview();
})();
