/* URL prefix support for the browser side (pairs with PrefixMiddleware in app/__init__.py).

   When the app is served under a subpath (https://nriparentservice.com/travel-companions/), the
   server renders every url_for() link prefixed already, but hand-written JavaScript paths such as
   fetch('/api/search') or location = '/dashboard' would escape to the site root — which is the
   WordPress site, not us. This script must load first, synchronously, in every <head>:

     window.APP_ROOT   the prefix ('' when served from the root, e.g. the Railway test domain)
     appUrl(path)      prefixes a root-relative path ('/api/x' -> '/travel-companions/api/x');
                       anything else (absolute URLs, '//cdn', relative 'x', non-strings) is returned as-is
     fetch(...)        transparently routed through appUrl for string URLs, so existing calls keep working

   With an empty prefix every function is a no-op, so local development and the Railway URL are
   byte-for-byte unaffected. */
(function () {
  var meta = document.querySelector('meta[name="app-root"]');
  var root = ((meta && meta.getAttribute('content')) || '').replace(/\/+$/, '');
  window.APP_ROOT = root;
  window.appUrl = function (path) {
    if (typeof path !== 'string' || !root) return path;
    if (path.charAt(0) === '/' && path.charAt(1) !== '/' && path.indexOf(root + '/') !== 0 && path !== root) {
      return root + path;
    }
    return path;
  };
  if (root && typeof window.fetch === 'function') {
    var nativeFetch = window.fetch;
    window.fetch = function (input, init) {
      return nativeFetch.call(window, typeof input === 'string' ? window.appUrl(input) : input, init);
    };
  }
})();
