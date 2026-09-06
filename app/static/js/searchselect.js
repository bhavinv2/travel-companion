/* Searchable dropdowns, site-wide (traveller, CS console and admin).
 *
 * Every <select> on the page is wrapped in a button + popup with a search box. The native
 * <select> is KEPT in the DOM (visually hidden) and stays the single source of truth, so
 * FormData, .value, inline onchange="" handlers and every bit of existing form code keep
 * working untouched — this only changes what the user sees and types into.
 *
 * Opt out of a single element with  <select data-no-search>.
 */
(function () {
  'use strict';

  const OPEN = [];                       // popups currently open, so outside-clicks can close them

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function labelFor(sel) {
    const chosen = [...sel.selectedOptions].filter(o => o.value !== '' || !sel.multiple);
    if (!chosen.length) {
      const ph = sel.multiple ? (sel.dataset.placeholder || 'Select…')
                              : (sel.options[0] ? sel.options[0].textContent : 'Select…');
      return { text: ph, empty: true };
    }
    if (sel.multiple) {
      return chosen.length === 1
        ? { text: chosen[0].textContent.trim(), empty: false }
        : { text: chosen.length + ' selected', empty: false };
    }
    return { text: chosen[0].textContent.trim(), empty: chosen[0].value === '' };
  }

  function build(sel) {
    if (sel.dataset.ssDone || sel.hasAttribute('data-no-search')) return;
    sel.dataset.ssDone = '1';

    const wrap = document.createElement('div');
    wrap.className = 'ss' + (sel.multiple ? ' ss-multi' : '');
    if (sel.disabled) wrap.classList.add('ss-disabled');

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'ss-btn';
    btn.setAttribute('aria-haspopup', 'listbox');
    btn.setAttribute('aria-expanded', 'false');
    btn.disabled = sel.disabled;
    btn.innerHTML = '<span class="ss-label"></span><i class="fa-solid fa-chevron-down ss-caret"></i>';

    const pop = document.createElement('div');
    pop.className = 'ss-pop';
    pop.hidden = true;
    pop.innerHTML =
      '<div class="ss-search"><span class="ss-search-in">' +
      '<i class="fa-solid fa-magnifying-glass"></i>' +
      '<input type="text" placeholder="Search…" autocomplete="off" spellcheck="false"/>' +
      '</span></div>' +
      '<div class="ss-list" role="listbox"></div>' +
      '<div class="ss-none" hidden>No matches</div>';

    sel.parentNode.insertBefore(wrap, sel);
    wrap.appendChild(sel);
    wrap.appendChild(btn);
    wrap.appendChild(pop);
    sel.classList.add('ss-native');

    const search = pop.querySelector('input');
    const list = pop.querySelector('.ss-list');
    const none = pop.querySelector('.ss-none');

    function paintLabel() {
      const { text, empty } = labelFor(sel);
      const el = btn.querySelector('.ss-label');
      const chosen = sel.selectedOptions[0];
      const icon = (!sel.multiple && chosen && chosen.dataset.icon) ? chosen.dataset.icon : '';
      el.innerHTML = (icon ? '<i class="fa-solid ' + esc(icon) + ' ss-ico"></i>' : '') +
                     '<span>' + esc(text) + '</span>';
      el.classList.toggle('is-empty', empty);
    }

    function renderList() {
      const q = search.value.trim().toLowerCase();
      list.innerHTML = '';
      let shown = 0;
      [...sel.options].forEach((o, i) => {
        const text = o.textContent.trim();
        if (q && !text.toLowerCase().includes(q)) return;
        shown++;
        const row = document.createElement('div');
        row.className = 'ss-opt' + (o.selected ? ' is-on' : '') + (o.disabled ? ' is-off' : '');
        row.setAttribute('role', 'option');
        row.setAttribute('aria-selected', o.selected ? 'true' : 'false');
        row.dataset.i = i;
        const glyph = o.dataset.icon ? '<i class="fa-solid ' + esc(o.dataset.icon) + ' ss-ico"></i>' : '';
        row.innerHTML = (sel.multiple ? '<span class="ss-box"><i class="fa-solid fa-check"></i></span>' : '')
          + glyph
          + '<span class="ss-txt">' + esc(text) + '</span>'
          + (!sel.multiple && o.selected ? '<i class="fa-solid fa-check ss-tick"></i>' : '');
        if (!o.disabled) row.addEventListener('mousedown', e => { e.preventDefault(); pick(i); });
        list.appendChild(row);
      });
      none.hidden = shown > 0;
    }

    function pick(i) {
      const o = sel.options[i];
      if (!o || o.disabled) return;
      if (sel.multiple) {
        o.selected = !o.selected;
      } else {
        sel.selectedIndex = i;
      }
      // the native element is the source of truth: let everything already listening react
      sel.dispatchEvent(new Event('input', { bubbles: true }));
      sel.dispatchEvent(new Event('change', { bubbles: true }));
      paintLabel();
      if (sel.multiple) renderList(); else close();
    }

    function open() {
      if (sel.disabled) return;
      closeAll();
      pop.hidden = false;
      wrap.classList.add('is-open');
      btn.setAttribute('aria-expanded', 'true');
      search.value = '';
      renderList();
      OPEN.push(close);
      const r = wrap.getBoundingClientRect();
      // flip upwards when there is no room below
      pop.classList.toggle('ss-up', window.innerHeight - r.bottom < 280 && r.top > 300);
      // ...and anchor to the right edge when a narrow trigger would push the panel off
      // screen. Left as-is it creates page-wide horizontal overflow and the whole layout
      // scrolls sideways, which reads as the section stretching.
      pop.classList.remove('ss-right');
      if (pop.getBoundingClientRect().right > document.documentElement.clientWidth - 8) {
        pop.classList.add('ss-right');
      }
      search.focus();
    }

    function close() {
      pop.hidden = true;
      wrap.classList.remove('is-open');
      btn.setAttribute('aria-expanded', 'false');
      const i = OPEN.indexOf(close);
      if (i >= 0) OPEN.splice(i, 1);
    }

    btn.addEventListener('click', e => {
      e.preventDefault(); e.stopPropagation();
      pop.hidden ? open() : close();
    });
    search.addEventListener('input', renderList);
    pop.addEventListener('click', e => e.stopPropagation());

    search.addEventListener('keydown', e => {
      const rows = [...list.querySelectorAll('.ss-opt:not(.is-off)')];
      const cur = list.querySelector('.ss-opt.is-cursor');
      let idx = rows.indexOf(cur);
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        if (!rows.length) return;
        idx = e.key === 'ArrowDown' ? Math.min(idx + 1, rows.length - 1) : Math.max(idx - 1, 0);
        rows.forEach(r => r.classList.remove('is-cursor'));
        rows[idx].classList.add('is-cursor');
        rows[idx].scrollIntoView({ block: 'nearest' });
      } else if (e.key === 'Enter') {
        e.preventDefault();
        const target = cur || rows[0];
        if (target) pick(+target.dataset.i);
      } else if (e.key === 'Escape') {
        e.preventDefault(); close(); btn.focus();
      }
    });

    // anything that changes the select programmatically should refresh the button
    sel.addEventListener('change', paintLabel);
    sel.ssSync = () => { paintLabel(); if (!pop.hidden) renderList(); };
    paintLabel();
  }

  function closeAll() {
    while (OPEN.length) OPEN.pop()();
  }
  document.addEventListener('click', closeAll);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeAll(); });

  function scan(root) {
    (root || document).querySelectorAll('select:not([data-ss-done])').forEach(build);
  }

  // initial pass, plus anything added later (admin screens build selects in JS)
  document.addEventListener('DOMContentLoaded', () => {
    scan();
    new MutationObserver(muts => {
      for (const m of muts) {
        for (const n of m.addedNodes) {
          if (n.nodeType !== 1) continue;
          if (n.tagName === 'SELECT') build(n);
          else scan(n);
        }
      }
    }).observe(document.body, { childList: true, subtree: true });
  });

  window.refreshSearchSelects = scan;
  window.syncSearchSelect = el => { if (el && el.ssSync) el.ssSync(); };
})();
