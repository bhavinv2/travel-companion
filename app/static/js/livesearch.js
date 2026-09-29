/* Search boxes that filter as you type.
 *
 * Opt in from the markup:
 *
 *     <form method="get" data-live-search="#leadResults"> ... <input type="search" name="q"> ...
 *     <div id="leadResults"> the table the server rendered </div>
 *
 * On each keystroke (debounced) the form's own GET is fetched and only the named container is
 * swapped in. The rest of the page -- the filters, the focus, the caret, the scroll position --
 * is untouched, which is the whole reason for not simply auto-submitting the form: a reload
 * takes the cursor out of the box you are typing in.
 *
 * Two things this deliberately keeps:
 *   - the Search button still works, and the form still submits normally. With no JavaScript,
 *     a slow network or an error, the screen behaves exactly as it did before.
 *   - the address bar follows along, so the result of a search is still a link you can share
 *     or reload.
 */
(function () {
  var DELAY = 300;

  function swap(form, target, url) {
    fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (r) { return r.ok ? r.text() : null; })
      .then(function (html) {
        if (html === null) return;              // leave what is on screen; the button still works
        var doc = new DOMParser().parseFromString(html, 'text/html');
        var fresh = doc.querySelector(target);
        var here = document.querySelector(target);
        if (!fresh || !here) return;
        here.innerHTML = fresh.innerHTML;
        history.replaceState(null, '', url);
        form.dispatchEvent(new CustomEvent('live-search:done', { bubbles: true }));
      })
      .catch(function () { /* a failed keystroke must not break the form under it */ });
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('form[data-live-search]').forEach(function (form) {
      var target = form.getAttribute('data-live-search');
      var box = form.querySelector('input[type=search], input[name=q]');
      if (!target || !box || !window.fetch || !window.DOMParser) return;

      var timer = null;
      var last = box.value;

      function run() {
        if (box.value === last) return;
        last = box.value;
        var params = new URLSearchParams(new FormData(form));
        // a new search starts at the first page, or an empty page 3 looks like no results
        params.delete('page');
        var action = form.getAttribute('action') || location.pathname;
        swap(form, target, action + '?' + params.toString());
      }

      box.addEventListener('input', function () {
        clearTimeout(timer);
        timer = setTimeout(run, DELAY);
      });
      // Enter should not wait out the debounce, and should not submit twice either
      form.addEventListener('submit', function (e) {
        if (!window.fetch) return;
        e.preventDefault();
        clearTimeout(timer);
        last = null;
        run();
      });
    });
  });
})();
