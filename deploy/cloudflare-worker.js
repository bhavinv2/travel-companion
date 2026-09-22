/* Cloudflare Worker: serve this Flask app at https://nriparentservice.com/travel-companions/*
   while the rest of nriparentservice.com stays on WordPress.

   Route: nriparentservice.com/travel-companions*     (no slash before the *, so it also
                                                       catches /travel-companions itself)

   IMPORTANT — this Worker is a *plain proxy*. It must NOT rewrite the HTML and must NOT strip
   the prefix silently:

     * Rewriting href/src/action in the HTML only fixes links that exist in the markup. The app's
       JavaScript calls paths at runtime (fetch('/api/...'), fetch('/admin/users/1/toggle'), ...),
       and no HTML rewriter can reach those — they escape to the WordPress site and 404. That is
       what breaks the admin dashboard.
     * Instead the app prefixes every URL itself, driven by APP_URL_PREFIX (see PrefixMiddleware in
       app/__init__.py). It also publishes the prefix to the browser as <meta name="app-root">, so
       runtime fetches are prefixed too.
     * Therefore: if you rewrite HTML here AND set APP_URL_PREFIX there, you get
       /travel-companions/travel-companions/... Pick one. The app-side one is the correct one.

   Required on Railway (Variables):
     APP_URL_PREFIX  = /travel-companions
     APP_PUBLIC_HOST = nriparentservice.com
     SITE_URL        = https://nriparentservice.com/travel-companions
*/

const ORIGIN = 'travel-companion-production-261c.up.railway.app';
const PREFIX = '/travel-companions';

export default {
  async fetch(request) {
    const url = new URL(request.url);

    // /travel-companions -> /travel-companions/ so relative URLs resolve inside the app
    if (url.pathname === PREFIX) {
      return Response.redirect(url.origin + PREFIX + '/' + url.search, 301);
    }

    // Forward the path UNCHANGED. PrefixMiddleware strips it into SCRIPT_NAME, which is what
    // makes url_for() emit /travel-companions/... everywhere.
    const upstream = new URL(url.pathname + url.search, 'https://' + ORIGIN);

    const headers = new Headers(request.headers);
    headers.set('Host', ORIGIN);              // Railway routes by Host
    headers.set('X-Forwarded-Host', url.host);
    headers.set('X-Forwarded-Proto', 'https');
    headers.set('X-Forwarded-Prefix', PREFIX); // belt and braces: works even if the path is stripped

    const response = await fetch(upstream, {
      method: request.method,
      headers,
      body: request.body,
      // Hand the app's own 3xx (login, post-submit, OAuth) to the browser untouched. Without this
      // the Worker follows them itself and the browser never sees the redirect.
      redirect: 'manual',
    });

    // Pass the response straight through; only the headers object needs to be mutable.
    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: new Headers(response.headers),
    });
  },
};
