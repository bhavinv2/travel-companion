/* URL prefix support for the browser side (pairs with PrefixMiddleware in app/__init__.py).

   When the app is served under a subpath (https://nriparentservice.com/travel-companions/), the
   server renders every url_for() link prefixed already, but hand-written JavaScript paths such as
   fetch('/api/search') or location = '/dashboard' would escape to the site root — which is the
   WordPress site, not us. This script must load first, synchronously, in every <head>:

     window.APP_ROOT   the prefix ('' when served from the root, e.g. the Railway test domain)
     appUrl(path)      prefixes a root-relative path ('/api/x' -> '/travel-companions/api/x'), or moves a staff
                       console one to its address on the site ('/cs/crm/' -> '/admin/cs/crm/', meta app-mounts);
                       anything else (absolute URLs, '//cdn', relative 'x', non-strings) is returned as-is
     fetch(...)        transparently routed through appUrl for string URLs, so existing calls keep working

   With an empty prefix every function is a no-op, so local development and the Railway URL are
   byte-for-byte unaffected. */
(function () {
  var meta = document.querySelector('meta[name="app-root"]');
  var root = ((meta && meta.getAttribute('content')) || '').replace(/\/+$/, '');
  window.APP_ROOT = root;
  // the staff console's address on the site, once the domain points at the app: [[public, inside]] (/admin/cs <- /cs)
  var mounts = [];
  try { mounts = JSON.parse((document.querySelector('meta[name="app-mounts"]') || {}).content || '[]'); } catch (e) { /* none */ }
  function mounted(path) {
    for (var i = 0; i < mounts.length; i++) {
      var inside = mounts[i][1];
      if (path === inside || path.indexOf(inside + '/') === 0 || path.indexOf(inside + '?') === 0) {
        return mounts[i][0] + path.slice(inside.length);
      }
    }
    return null;
  }
  window.appUrl = function (path) {
    if (typeof path !== 'string' || !root) return path;
    if (path.charAt(0) === '/' && path.charAt(1) !== '/' && path.indexOf(root + '/') !== 0 && path !== root) {
      var bare = path.split('?')[0].split('#')[0];
      for (var i = 0; i < mounts.length; i++) {
        if (bare === mounts[i][0] || bare.indexOf(mounts[i][0] + '/') === 0) return path;   // already the site's
      }
      return mounted(path) || root + path;
    }
    if (path.indexOf(root + '/') === 0) return mounted(path.slice(root.length)) || path;
    return path;
  };
  if (root && typeof window.fetch === 'function') {
    var nativeFetch = window.fetch;
    window.fetch = function (input, init) {
      return nativeFetch.call(window, typeof input === 'string' ? window.appUrl(input) : input, init);
    };
  }
})();
