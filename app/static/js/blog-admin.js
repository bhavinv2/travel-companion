/* The blog workspace's screens (templates/admin/blog/*): the menu down the left (folded to icons, opened
   on a phone), All posts' ticks and bulk actions, forms that ask first (data-confirm), and the media
   library -- pictures dropped in, one picture's details in a dialog. The editor has its own script
   (blog-studio.js). */
(function () {
  const toast = (m, t) => (window.showToast ? window.showToast(m, t) : alert(m));
  const CSRF = document.querySelector('meta[name="csrf-token"]')?.content || '';
  const store = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { /* private mode */ } return null; };

  // ---------------------------------------------------------------- the menu
  const wpb = document.getElementById('wpb');
  if (!wpb) return;
  const burger = document.getElementById('wpbBurger');
  if (store('wpb.folded') === '1') wpb.classList.add('is-folded');
  document.getElementById('wpbFold')?.addEventListener('click', () => {
    wpb.classList.toggle('is-folded');
    store('wpb.folded', wpb.classList.contains('is-folded') ? '1' : '0');
  });
  burger?.addEventListener('click', () => {
    const open = !wpb.classList.contains('menu-open');
    wpb.classList.toggle('menu-open', open);
    burger.setAttribute('aria-expanded', open ? 'true' : 'false');
  });
  document.addEventListener('click', e => {
    if (wpb.classList.contains('menu-open') && !e.target.closest('#wpbMenu') && !e.target.closest('#wpbBurger')) {
      wpb.classList.remove('menu-open');
      burger.setAttribute('aria-expanded', 'false');
    }
  });

  // ---------------------------------------------------------------- forms and buttons that ask first
  document.addEventListener('submit', e => {
    const f = e.target;
    const b = e.submitter;
    const ask = (b && b.dataset.confirm) || f.dataset.confirm;
    if (ask && !confirm(ask)) e.preventDefault();
  });

  // ---------------------------------------------------------------- all posts: ticks and bulk actions
  const all = document.getElementById('wpbAll');
  const boxes = () => Array.from(document.querySelectorAll('#wpbPosts tbody input[name=ids]'));
  if (all) {
    const sync = () => {
      const on = boxes().filter(b => b.checked).length;
      all.checked = on > 0 && on === boxes().length;
      all.indeterminate = on > 0 && on < boxes().length;
      boxes().forEach(b => b.closest('tr').classList.toggle('is-ticked', b.checked));
    };
    all.addEventListener('change', () => {
      const on = all.checked;                    // each row's change below syncs "all" again
      boxes().forEach(b => {
        if (b.checked === on) return;
        b.checked = on;
        b.dispatchEvent(new Event('change', { bubbles: true }));     // the permanent-delete bar counts them too
      });
      sync();
    });
    document.getElementById('wpbPosts').addEventListener('change', e => { if (e.target.name === 'ids') sync(); });
    document.getElementById('wpbBulk').addEventListener('submit', e => {
      const action = e.target.querySelector('[name=action]').value;
      const n = boxes().filter(b => b.checked).length;
      if (!action || !n) { e.preventDefault(); toast(!n ? 'Tick the posts first.' : 'Choose what to do with them.', 'warning'); return; }
      if (action === 'trash' && !confirm('Move ' + n + ' post' + (n === 1 ? '' : 's') + ' to the Trash? They go off the site.')) e.preventDefault();
    });
  }

  // ---------------------------------------------------------------- media: adding pictures
  const drop = document.getElementById('wpbDrop');
  if (drop) {
    const input = document.getElementById('wpbMediaFile');
    const status = document.getElementById('wpbDropStatus');
    document.getElementById('wpbAddMedia').addEventListener('click', () => { drop.hidden = !drop.hidden; });
    drop.querySelector('[data-pick]').addEventListener('click', () => input.click());
    async function send(files) {
      files = Array.from(files).filter(f => /^image\/(jpeg|png|webp)$/.test(f.type) || /\.(jpe?g|png|webp)$/i.test(f.name));
      if (!files.length) { toast('Use JPG, PNG or WebP pictures.', 'danger'); return; }
      status.textContent = 'Uploading ' + files.length + ' picture' + (files.length === 1 ? '' : 's') + '…';
      drop.classList.add('is-busy');
      const fd = new FormData();
      files.forEach(f => fd.append('files', f));
      let d = {};
      try {
        const r = await fetch(drop.dataset.url, { method: 'POST', headers: { 'X-CSRFToken': CSRF }, body: fd, credentials: 'same-origin' });
        d = await r.json().catch(() => ({}));
      } catch (err) { d = { errors: ['The upload did not reach the server.'] }; }
      drop.classList.remove('is-busy');
      if (d.errors && d.errors.length) toast(d.errors.join(' '), d.uploaded ? 'warning' : 'danger');
      if (d.uploaded) location.reload();
      else status.textContent = '';
    }
    input.addEventListener('change', () => send(input.files));
    ['dragenter', 'dragover'].forEach(ev => document.addEventListener(ev, e => {
      if (!Array.from(e.dataTransfer?.types || []).includes('Files')) return;
      e.preventDefault();
      drop.hidden = false;
      drop.classList.add('is-drop');
    }));
    drop.addEventListener('dragleave', e => { if (!drop.contains(e.relatedTarget)) drop.classList.remove('is-drop'); });
    document.addEventListener('drop', e => {
      if (!e.dataTransfer?.files?.length) return;
      e.preventDefault();
      drop.classList.remove('is-drop');
      send(e.dataTransfer.files);
    });
  }

  // ---------------------------------------------------------------- media: one picture's details
  const dlg = document.getElementById('wpbMediaDialog');
  const rows = document.getElementById('wpbMediaRows');
  if (dlg && rows) {
    const alt = dlg.querySelector('.wpb-md-alt input');
    let row = null, altT = null;
    document.getElementById('wpbMedia').addEventListener('click', e => {
      const t = e.target.closest('.wpb-tile');
      if (!t) return;
      row = rows.content.querySelector('[data-i="' + t.dataset.i + '"]');
      const d = row.dataset;
      dlg.querySelector('.wpb-md-pic img').src = d.src;
      dlg.querySelector('.wpb-md-name').textContent = d.name;
      dlg.querySelectorAll('[data-f]').forEach(el => {
        const k = el.dataset.f;
        if (k === 'posts') {
          el.innerHTML = '';
          const links = row.querySelectorAll('a');
          if (!links.length) el.innerHTML = '<span class="wpb-dim">None yet.</span>';
          links.forEach(a => el.appendChild(a.cloneNode(true)));
        } else if (k === 'url') el.value = new URL(d.url, location.href).href;
        else el.textContent = d[k] || '—';
      });
      alt.value = d.alt || '';
      alt.disabled = !d.save;
      alt.closest('label').hidden = !d.save;
      const del = dlg.querySelector('.wpb-md-del');
      del.hidden = !d.delete;
      if (d.delete) del.action = d.delete;
      dlg.querySelector('.wpb-md-keep').hidden = !!d.delete || !d.save;
      dlg.showModal();
    });
    dlg.addEventListener('click', e => {
      if (e.target === dlg || e.target.closest('[data-close]')) dlg.close();
      const c = e.target.closest('[data-copy]');
      if (c) {
        const i = dlg.querySelector('[data-f=url]');
        i.select();
        (navigator.clipboard ? navigator.clipboard.writeText(i.value) : Promise.reject()).then(
          () => { c.textContent = 'Copied'; setTimeout(() => { c.textContent = 'Copy'; }, 1500); },
          () => document.execCommand('copy'));
      }
    });
    alt.addEventListener('input', () => {
      clearTimeout(altT);
      altT = setTimeout(async () => {
        if (!row || !row.dataset.save) return;
        const fd = new FormData();
        fd.append('alt', alt.value);
        const r = await fetch(row.dataset.save, { method: 'POST', headers: { 'X-CSRFToken': CSRF }, body: fd, credentials: 'same-origin' });
        if (r.ok) {
          row.dataset.alt = alt.value;
          const tile = document.querySelector('.wpb-tile[data-i="' + row.dataset.i + '"] img');
          if (tile) tile.alt = alt.value;
        }
      }, 600);
    });
  }
})();
