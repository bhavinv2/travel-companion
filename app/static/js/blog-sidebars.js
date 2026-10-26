/* Blog › Sidebars (templates/admin/blog/sidebars.html, sidebar_edit.html; routes admin_blog.blog_sidebar_*).

   The Sidebars screen: a card is dragged by its grip to another place or the other sidebar (or moved with its
   arrows), its bottom edge dragged to make it taller or shorter, a sidebar's inner edge dragged to make it wider;
   on / off and "last card stays in view" are switches. Each change is saved at once.

   One card's form: only the fields its kind uses show; the picture comes up from the computer or from Media; the
   preview on the right is redrawn from the form as it changes, at the width of the sidebar it is in. */
(function () {
  const CSRF = document.querySelector('meta[name="csrf-token"]')?.content || '';
  const toast = (m, t) => (window.showToast ? window.showToast(m, t) : alert(m));
  async function post(url, data) {
    const fd = data instanceof FormData ? data : new FormData();
    if (!(data instanceof FormData)) Object.entries(data || {}).forEach(([k, v]) => fd.append(k, v));
    const r = await fetch(url, { method: 'POST', headers: { 'X-CSRFToken': CSRF, Accept: 'application/json' }, body: fd, credentials: 'same-origin' });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.error || 'That was not saved: try again.');
    return d;
  }

  /* ================================================================ the Sidebars screen */
  const page = document.getElementById('sbmPage');
  if (page) {
    const said = document.getElementById('sbmSaved');
    let saidT = null;
    const saved = (msg) => {
      said.textContent = msg || 'Saved';
      said.classList.add('on');
      clearTimeout(saidT);
      saidT = setTimeout(() => said.classList.remove('on'), 1600);
    };
    const fail = err => toast(err.message, 'danger');
    const lists = () => Array.from(page.querySelectorAll('[data-list]'));
    const empties = () => page.querySelectorAll('.sbm-rail').forEach(r => {
      r.querySelector('.sbm-empty').hidden = !!r.querySelector('.sbm-card');
    });
    function saveOrder() {
      const ids = side => Array.from(page.querySelectorAll('[data-list="' + side + '"] > .sbm-card')).map(c => c.dataset.id).join(',');
      empties();
      post(page.dataset.orderUrl, { left: ids('left'), right: ids('right') }).then(() => saved('Order saved')).catch(fail);
    }

    // ------------------------------------------------ moving a card: its arrows, or dragged by its grip
    page.addEventListener('click', e => {
      const b = e.target.closest('[data-move]');
      if (!b) return;
      const card = b.closest('.sbm-card');
      const list = card.parentNode;
      if (b.dataset.move === 'up' && card.previousElementSibling) list.insertBefore(card, card.previousElementSibling);
      else if (b.dataset.move === 'down' && card.nextElementSibling) list.insertBefore(card.nextElementSibling, card);
      else if (b.dataset.move === 'swap') lists().find(l => l !== list).appendChild(card);
      else return;
      b.focus();
      saveOrder();
    });
    let dragging = null;
    const line = document.createElement('div');
    line.className = 'sbm-dropline';
    page.addEventListener('mousedown', e => {           // only the grip starts a drag: the card's own links stay links
      const grip = e.target.closest('.sbm-drag');
      page.querySelectorAll('.sbm-card[draggable]').forEach(c => c.removeAttribute('draggable'));
      if (grip) grip.closest('.sbm-card').setAttribute('draggable', 'true');
    });
    page.addEventListener('dragstart', e => {
      dragging = e.target.closest('.sbm-card');
      if (!dragging) return;
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', dragging.dataset.id);
      requestAnimationFrame(() => dragging && dragging.classList.add('is-dragging'));
    });
    page.addEventListener('dragover', e => {
      const list = e.target.closest('.sbm-rail') && e.target.closest('.sbm-rail').querySelector('[data-list]');
      if (!dragging || !list) return;
      e.preventDefault();
      const after = Array.from(list.querySelectorAll(':scope > .sbm-card:not(.is-dragging)'))
        .find(c => e.clientY < c.getBoundingClientRect().top + c.offsetHeight / 2);
      if (after) list.insertBefore(line, after); else list.appendChild(line);
    });
    page.addEventListener('drop', e => {
      if (!dragging || !line.parentNode) return;
      e.preventDefault();
      line.parentNode.insertBefore(dragging, line);
      line.remove();
      saveOrder();
    });
    page.addEventListener('dragend', () => {
      if (dragging) { dragging.classList.remove('is-dragging'); dragging.removeAttribute('draggable'); }
      dragging = null;
      line.remove();
    });

    // ------------------------------------------------ on / off
    page.addEventListener('change', e => {
      const on = e.target.closest('[data-on]');
      if (on) {
        const card = on.closest('.sbm-card');
        post(card.dataset.quick, { is_on: on.checked ? '1' : '0' }).then(d => {
          card.className = card.className.replace(/\bst-\w+/, 'st-' + d.status);
          saved(on.checked ? 'On: readers see it' : 'Off: nobody sees it');
        }).catch(err => { on.checked = !on.checked; fail(err); });
        return;
      }
      const stick = e.target.closest('[data-sticky]');
      if (stick) {
        post(page.dataset.railUrl, { side: stick.closest('.sbm-rail').dataset.side, sticky: stick.checked ? '1' : '0' })
          .then(() => saved()).catch(fail);
      }
    });

    // ------------------------------------------------ a card's height: its bottom edge, dragged (or arrow keys)
    const H_MIN = 80, H_MAX = 1200;
    function setH(card, h) {
      const box = card.querySelector('.bsd');
      const label = card.querySelector('[data-h]');
      if (h) {
        box.style.setProperty('--h', h + 'px');
        box.classList.add('has-h');
        label.textContent = h + ' px tall';
      } else {
        box.style.removeProperty('--h');
        box.classList.remove('has-h');
        label.textContent = 'As tall as it needs';
      }
      card.querySelector('[data-auto]').hidden = !h;
    }
    const saveH = (card, h) => post(card.dataset.quick, { height: h || '' }).then(() => saved(h ? 'Height saved' : 'As tall as it needs')).catch(fail);
    page.addEventListener('pointerdown', e => {
      const grip = e.target.closest('[data-hgrip]');
      if (!grip || e.target.closest('button')) return;
      const card = grip.closest('.sbm-card');
      const box = card.querySelector('.bsd');
      const y0 = e.clientY, h0 = box.getBoundingClientRect().height;
      let h = Math.round(h0);
      grip.setPointerCapture(e.pointerId);
      card.classList.add('is-sizing');
      const move = ev => { h = Math.max(H_MIN, Math.min(H_MAX, Math.round((h0 + ev.clientY - y0) / 10) * 10)); setH(card, h); };
      const up = () => {
        grip.removeEventListener('pointermove', move);
        card.classList.remove('is-sizing');
        if (Math.abs(h - h0) >= 4) saveH(card, h);
      };
      grip.addEventListener('pointermove', move);
      grip.addEventListener('pointerup', up, { once: true });
      grip.addEventListener('pointercancel', up, { once: true });
    });
    page.addEventListener('keydown', e => {
      const grip = e.target.closest('[data-hgrip]');
      if (grip && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
        e.preventDefault();
        const card = grip.closest('.sbm-card');
        const h0 = Math.round(card.querySelector('.bsd').getBoundingClientRect().height / 10) * 10;
        const h = Math.max(H_MIN, Math.min(H_MAX, h0 + (e.key === 'ArrowDown' ? 20 : -20)));
        setH(card, h);
        clearTimeout(grip.saveT);
        grip.saveT = setTimeout(() => saveH(card, h), 500);
      }
      const wgrip = e.target.closest('[data-wgrip]');
      if (wgrip && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) {
        e.preventDefault();
        const rail = wgrip.closest('.sbm-rail');
        const grow = (e.key === 'ArrowRight') === (rail.dataset.side === 'left');
        setW(rail, widthOf(rail) + (grow ? 10 : -10));
        clearTimeout(wgrip.saveT);
        wgrip.saveT = setTimeout(() => saveW(rail), 500);
      }
    });
    page.addEventListener('click', e => {
      const b = e.target.closest('[data-auto]');
      if (!b) return;
      const card = b.closest('.sbm-card');
      setH(card, null);
      saveH(card, null);
    });

    // ------------------------------------------------ a sidebar's width: its inner edge, dragged
    const W_MIN = 200, W_MAX = 360;
    const widthOf = rail => parseInt(getComputedStyle(page).getPropertyValue(rail.dataset.side === 'left' ? '--wl' : '--wr'), 10) || 260;
    function setW(rail, w) {
      w = Math.max(W_MIN, Math.min(W_MAX, Math.round(w / 10) * 10));
      page.style.setProperty(rail.dataset.side === 'left' ? '--wl' : '--wr', w + 'px');
      rail.querySelector('[data-w]').textContent = w;
      return w;
    }
    const saveW = rail => post(page.dataset.railUrl, { side: rail.dataset.side, width: widthOf(rail) }).then(() => saved('Width saved')).catch(fail);
    page.addEventListener('pointerdown', e => {
      const grip = e.target.closest('[data-wgrip]');
      if (!grip) return;
      const rail = grip.closest('.sbm-rail');
      const x0 = e.clientX, w0 = widthOf(rail), sign = rail.dataset.side === 'left' ? 1 : -1;
      grip.setPointerCapture(e.pointerId);
      page.classList.add('is-sizing');
      const move = ev => setW(rail, w0 + sign * (ev.clientX - x0));
      const up = () => {
        grip.removeEventListener('pointermove', move);
        page.classList.remove('is-sizing');
        if (widthOf(rail) !== w0) saveW(rail);
      };
      grip.addEventListener('pointermove', move);
      grip.addEventListener('pointerup', up, { once: true });
      grip.addEventListener('pointercancel', up, { once: true });
    });

    document.querySelectorAll('[data-autosubmit]').forEach(s => s.addEventListener('change', () => s.form.submit()));
    // the cards' own links are pictures of what readers get: not a way off this screen
    page.addEventListener('click', e => { if (e.target.closest('.sbm-body a')) e.preventDefault(); });
  }

  /* ================================================================ one card's form */
  const form = document.getElementById('sbeForm');
  if (!form) return;
  const box = document.getElementById('sbePreview');
  const widths = JSON.parse(form.dataset.widths || '{}');
  const val = n => (form.querySelector('[name=' + n + ']:checked') || {}).value;

  // only the fields this kind uses
  function kindFields() {
    const k = val('kind');
    form.querySelectorAll('[data-for]').forEach(el => { el.hidden = !el.dataset.for.split(' ').includes(k); });
    form.querySelectorAll('[data-label-for]').forEach(el => { el.hidden = !el.dataset.labelFor.split(' ').includes(k); });
    const show = val('show_on');
    form.querySelectorAll('[data-show-on]').forEach(el => { el.hidden = el.dataset.showOn !== show; });
    const side = val('side') || 'right';
    box.style.width = (widths[side] || 300) + 'px';
    document.getElementById('sbeW').textContent = (widths[side] || 300) + ' px wide, as the ' + side + ' sidebar';
  }

  // the preview, drawn by the server from the form as it is now
  let previewT = null, previewN = 0;
  function preview() {
    clearTimeout(previewT);
    previewT = setTimeout(async () => {
      const n = ++previewN;
      try {
        const r = await fetch(form.dataset.previewUrl, { method: 'POST', headers: { 'X-CSRFToken': CSRF }, body: new FormData(form), credentials: 'same-origin' });
        const html = await r.text();
        if (n !== previewN || !r.ok) return;
        box.innerHTML = html;
        box.querySelectorAll('.sbe-errs').forEach(u => u.remove());
        if (!box.querySelector('.bsd')) box.innerHTML = '<p class="sbe-wait wpb-dim">Fill in the card: it shows here as readers will see it.</p>';
      } catch (err) { /* the preview waits for the next change */ }
    }, 250);
  }
  form.addEventListener('input', e => { if (!e.target.closest('.sbe-find')) preview(); });
  form.addEventListener('change', e => { if (!e.target.closest('.sbe-find, #sbeFile')) { kindFields(); preview(); } });
  box.addEventListener('click', e => { if (e.target.closest('a')) e.preventDefault(); });

  // the height: the slider and the box say the same, and either picks "This tall"
  const hRange = document.getElementById('sbeHRange'), hBox = document.getElementById('sbeH');
  const fixed = form.querySelector('[name=height_mode][value=fixed]');
  hRange.addEventListener('input', () => { hBox.value = hRange.value; fixed.checked = true; });
  hBox.addEventListener('input', () => { if (+hBox.value) { hRange.value = hBox.value; fixed.checked = true; } });

  // the links of a list: one more row, one row out
  const links = document.getElementById('sbeLinks');
  document.getElementById('sbeLinkAdd').addEventListener('click', () => {
    if (links.children.length >= 12) { toast('Twelve links at most.', 'warning'); return; }
    const row = links.lastElementChild.cloneNode(true);
    row.querySelectorAll('input').forEach(i => { i.value = ''; });
    links.appendChild(row);
    row.querySelector('input').focus();
  });
  links.addEventListener('click', e => {
    const x = e.target.closest('[data-link-x]');
    if (!x) return;
    const row = x.closest('.sbe-link');
    if (links.children.length > 1) row.remove(); else row.querySelectorAll('input').forEach(i => { i.value = ''; });
    preview();
  });

  // the posts to pick from: found by their title
  const find = form.querySelector('.sbe-find');
  if (find) find.addEventListener('input', () => {
    const q = find.value.trim().toLowerCase();
    form.querySelectorAll('.sbe-pick-list [data-t]').forEach(l => { l.hidden = !!q && !l.dataset.t.includes(q); });
  });

  // the picture: from the computer (dropped or picked) or from Media
  const pic = document.getElementById('sbePic');
  const url = form.querySelector('[name=image_url]');
  const alt = form.querySelector('[name=image_alt]');
  const file = document.getElementById('sbeFile');
  function setPic(u, src) {
    url.value = u || '';
    const img = pic.querySelector('img');
    img.hidden = !u;
    if (u) img.src = src || u; else img.removeAttribute('src');
    pic.querySelector('p').hidden = !!u;
    form.querySelector('[data-pic=remove]').hidden = !u;
    preview();
  }
  async function upload(f) {
    if (!f) return;
    pic.classList.add('is-busy');
    const fd = new FormData();
    fd.append('file', f);
    fd.append('purpose', 'side');
    try { const d = await post(form.dataset.imageUrl, fd); setPic(d.url, d.src); }
    catch (err) { toast(err.message, 'danger'); }
    pic.classList.remove('is-busy');
  }
  pic.addEventListener('click', () => file.click());
  file.addEventListener('change', () => { upload(file.files[0]); file.value = ''; });
  pic.addEventListener('dragover', e => { e.preventDefault(); pic.classList.add('is-drop'); });
  pic.addEventListener('dragleave', () => pic.classList.remove('is-drop'));
  pic.addEventListener('drop', e => { e.preventDefault(); pic.classList.remove('is-drop'); upload(e.dataTransfer.files && e.dataTransfer.files[0]); });
  const lib = document.getElementById('sbeLib'), libQ = document.getElementById('sbeLibQ'), grid = document.getElementById('sbeLibGrid');
  let items = [], libT = null;
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  async function loadLib() {
    try {
      const u = new URL(form.dataset.mediaUrl, location.href);
      if (libQ.value.trim()) u.searchParams.set('q', libQ.value.trim());
      items = (await (await fetch(u, { credentials: 'same-origin' })).json()).items || [];
    } catch (err) { items = []; }
    grid.innerHTML = items.length ? items.map((m, i) => '<button type="button" class="sbe-tile" data-i="' + i + '" title="' + esc(m.name) +
      (m.width ? ' · ' + m.width + ' × ' + m.height : '') + '"><img src="' + esc(m.src) + '" alt="" loading="lazy"/></button>').join('')
      : '<p class="wpb-dim">' + (libQ.value.trim() ? 'No picture matches.' : 'No pictures yet: upload one.') + '</p>';
  }
  form.addEventListener('click', e => {
    const b = e.target.closest('[data-pic]');
    if (!b) return;
    if (b.dataset.pic === 'upload') file.click();
    else if (b.dataset.pic === 'remove') setPic('', '');
    else { if (lib.showModal) lib.showModal(); else lib.setAttribute('open', ''); loadLib(); }
  });
  libQ.addEventListener('input', () => { clearTimeout(libT); libT = setTimeout(loadLib, 250); });
  lib.addEventListener('click', e => {
    if (e.target.closest('[data-lib-close]') || e.target === lib) { lib.close ? lib.close() : lib.removeAttribute('open'); return; }
    const t = e.target.closest('.sbe-tile');
    if (!t) return;
    const m = items[+t.dataset.i];
    if (!m) return;
    setPic(m.url, m.src);
    if (!alt.value.trim() && m.alt) alt.value = m.alt;
    lib.close ? lib.close() : lib.removeAttribute('open');
  });

  kindFields();
})();
