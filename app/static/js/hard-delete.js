/* Admin hard delete -- the buttons drawn by templates/admin/_hard_delete.html.
 *
 * One delegated listener for every screen, in both consoles, so a table that live search swaps
 * out (insurance leads, CS posts) keeps working without re-wiring: nothing here holds a reference
 * to an element that might be replaced.
 *
 * Every delete posts to /admin/delete/<kind>/<id> or /admin/delete/<kind>/bulk. The server is the
 * check that counts -- it answers a non-admin with 403 -- and these buttons are only drawn for
 * admins in the first place.
 */
(function () {
  'use strict';

  function toast(msg, kind) {
    if (window.showToast) window.showToast(msg, kind || 'success');
    else window.alert(msg);
  }

  function rowsFor(kind, id) {
    var key = kind + '-' + id;
    return document.querySelectorAll('[data-hd-row="' + key + '"], [data-hd-also="' + key + '"]');
  }

  // A pick is any checkbox that names a kind, not only the ones row_check() draws: a screen with
  // checkboxes of its own (the scraper's rows) marks those instead of drawing a second set.
  function picks(kind) {
    return 'input[type=checkbox][data-hd-kind="' + kind + '"]:not(.hd-all)';
  }

  function isPick(el) {
    return el.matches && el.matches('input[type=checkbox][data-hd-kind]:not(.hd-all)');
  }

  function checked(kind) {
    return Array.prototype.slice.call(document.querySelectorAll(picks(kind) + ':checked'));
  }

  function sync(kind) {
    var n = checked(kind).length;
    document.querySelectorAll('.hd-bulk[data-hd-kind="' + kind + '"]').forEach(function (bar) {
      bar.style.display = n ? '' : 'none';
      var c = bar.querySelector('.hd-count');
      if (c) c.textContent = String(n);
    });
    var all = document.querySelectorAll(picks(kind) + ':not(:disabled)').length;
    document.querySelectorAll('.hd-all[data-hd-kind="' + kind + '"]').forEach(function (box) {
      box.checked = !!all && n === all;
      box.indeterminate = n > 0 && n < all;
    });
  }

  function syncAll() {
    var kinds = {};
    document.querySelectorAll('input[type=checkbox][data-hd-kind], .hd-bulk').forEach(function (el) { kinds[el.dataset.hdKind] = 1; });
    Object.keys(kinds).forEach(sync);
  }

  function post(url, body) {
    var call = window.apiFetch
      ? window.apiFetch(url, { method: 'POST', body: JSON.stringify(body || {}) })
      : fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
    return call.then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) { return { ok: r.ok, data: d }; });
    });
  }

  function gone(kind, ids) {
    ids.forEach(function (id) { rowsFor(kind, id).forEach(function (el) { el.remove(); }); });
    sync(kind);
    // for a page with counts of its own to redo (the scraper's bulk bar)
    document.dispatchEvent(new CustomEvent('hard-delete:done', { detail: { kind: kind, ids: ids.map(String) } }));
  }

  function deleteOne(btn) {
    var kind = btn.dataset.hdKind, id = btn.dataset.hdId, what = btn.dataset.hdWhat || 'this';
    var run = function () {
      btn.disabled = true;
      post('/admin/delete/' + encodeURIComponent(kind) + '/' + encodeURIComponent(id)).then(function (res) {
        btn.disabled = false;
        if (!res.ok || !res.data.success) return toast(res.data.error || 'Could not delete it.', 'danger');
        toast('Deleted ' + what + '.');
        if (btn.dataset.hdRedirect) { window.location.href = btn.dataset.hdRedirect; return; }
        gone(kind, [id]);
      }).catch(function () { btn.disabled = false; toast('Could not reach the server.', 'danger'); });
    };
    var msg = 'Permanently delete ' + what + '?' + (btn.dataset.hdDetail ? ' ' + btn.dataset.hdDetail : '');
    if (btn.dataset.hdTier === 'type' && window.openHardDeleteModal) window.openHardDeleteModal(msg, run);
    else if (window.confirm(msg + ' This cannot be undone.')) run();
  }

  function deleteSelected(btn) {
    var kind = btn.dataset.hdKind, noun = btn.dataset.hdNoun || 'records';
    var ids = checked(kind).map(function (b) { return b.value; });
    if (!ids.length) return;
    var run = function () {
      btn.disabled = true;
      post('/admin/delete/' + encodeURIComponent(kind) + '/bulk', { ids: ids }).then(function (res) {
        btn.disabled = false;
        if (!res.ok || !res.data.success) return toast(res.data.error || 'Could not delete them.', 'danger');
        gone(kind, (res.data.ids || []).map(String));
        var skipped = res.data.skipped || [];
        toast('Deleted ' + res.data.deleted + ' ' + noun + '.' +
              (skipped.length ? ' ' + skipped.length + ' could not be: ' + skipped[0].error : ''),
              skipped.length ? 'warning' : 'success');
      }).catch(function () { btn.disabled = false; toast('Could not reach the server.', 'danger'); });
    };
    var msg = 'Permanently delete ' + ids.length + ' ' + noun + ' and everything tied to them?';
    if (window.openHardDeleteModal) window.openHardDeleteModal(msg, run);
    else if (window.confirm(msg)) run();
  }

  document.addEventListener('click', function (e) {
    var one = e.target.closest && e.target.closest('.hd-del');
    if (one) { e.preventDefault(); deleteOne(one); return; }
    var many = e.target.closest && e.target.closest('.hd-bulk-del');
    if (many) { e.preventDefault(); deleteSelected(many); }
  });

  document.addEventListener('change', function (e) {
    var t = e.target;
    if (!t || !t.classList) return;
    if (t.classList.contains('hd-all')) {
      document.querySelectorAll(picks(t.dataset.hdKind) + ':not(:disabled)')
        .forEach(function (b) { b.checked = t.checked; });
      sync(t.dataset.hdKind);
    } else if (isPick(t)) {
      sync(t.dataset.hdKind);
    }
  });

  // live search replaces a table's rows: count the selection again
  document.addEventListener('live-search:done', syncAll);
  document.addEventListener('DOMContentLoaded', syncAll);
})();
