/* Cloudflare Worker: serve this Flask app at three paths on nriparentservice.com
   while the rest of the site stays on WordPress.

     https://nriparentservice.com/travel-companions/*   the companion app (every screen)
     https://nriparentservice.com/travel-insurance       the insurance landing page
     https://nriparentservice.com/sahayak                the Sahayak booking page

   Routes to add (Workers & Pages -> this Worker -> Settings -> Domains & Routes):

     nriparentservice.com/travel-companions*
     nriparentservice.com/travel-insurance*
     nriparentservice.com/sahayak*

   No slash before the `*`, so each pattern also catches the bare path itself. Add the same three
   for www.nriparentservice.com if that hostname serves traffic too — a route matches one hostname.

   TWO DIFFERENT JOBS, and the difference matters:

     * /travel-companions/... is the app mounted under a prefix. This Worker STRIPS the prefix and
       tells the app about it with X-Forwarded-Prefix, which PrefixMiddleware puts back into
       SCRIPT_NAME so url_for() emits /travel-companions/... everywhere.
     * /travel-insurance and /sahayak are standalone pages that sit BESIDE that prefix. Their path
       is forwarded UNCHANGED, because /travel-insurance is a real route in the app. The same
       X-Forwarded-Prefix still goes with it, so every link those pages render keeps the one
       canonical prefix and the app is never reachable at two sets of URLs.

   This Worker is a plain proxy and must NOT rewrite HTML. Rewriting href/src only fixes links in
   the markup; the app's JavaScript builds paths at runtime (fetch('/api/...')), and no rewriter
   reaches those — they escape to WordPress and 404. That is what breaks the admin dashboard.
   The app prefixes its own URLs and publishes the prefix as <meta name="app-root">.

   Required on Railway (Variables):
     APP_URL_PREFIX  = /travel-companions
     APP_PUBLIC_HOST = nriparentservice.com
     SITE_URL        = https://nriparentservice.com/travel-companions
     APP_ALIAS_PATHS = /travel-insurance,/sahayak     (also the built-in default)
*/

const ORIGIN = "travel-companion-production-261c.up.railway.app";
const PREFIX = "/travel-companions";

// Standalone pages beside the prefix. Keep in step with APP_ALIAS_PATHS on Railway.
const ALIASES = ["/travel-insurance", "/sahayak"];

export default {
  async fetch(request) {
    const url = new URL(request.url);
    const path = url.pathname;

    // Redirect /travel-companions to /travel-companions/
    if (path === PREFIX) {
      return Response.redirect(url.origin + PREFIX + "/" + url.search, 301);
    }

    const isApp = path.startsWith(PREFIX + "/");
    // startsWith, not an exact match: the route pattern /travel-insurance* sends us things like
    // the old plural /travel-insurances, and the app answers those with its own redirect.
    const alias = ALIASES.find((a) => path.startsWith(a));

    // A standalone page is an exact route, so a trailing slash would 404. Normalise it rather
    // than hand somebody an error.
    if (alias && path === alias + "/") {
      return Response.redirect(url.origin + alias + url.search, 301);
    }

    // Anything else should never have reached this Worker; leave it alone rather than proxy the
    // whole site by accident.
    if (!isApp && !alias) {
      return new Response("Not found", { status: 404 });
    }

    // The app path is stripped (the app re-adds it from X-Forwarded-Prefix); a standalone page
    // is forwarded as-is, because that path IS its route.
    const upstreamPath = isApp ? path.slice(PREFIX.length) || "/" : path;
    const upstream = new URL(upstreamPath + url.search, `https://${ORIGIN}`);

    const headers = new Headers(request.headers);
    headers.set("X-Forwarded-Host", url.host);
    headers.set("X-Forwarded-Proto", "https");
    headers.set("X-Forwarded-Prefix", PREFIX);

    const init = {
      method: request.method,
      headers,
      // Hand the app's own 3xx (login, post-submit, OAuth) to the browser untouched. Without
      // this the Worker follows them itself and the browser never sees the redirect.
      redirect: "manual",
    };

    if (request.method !== "GET" && request.method !== "HEAD") {
      init.body = request.body;
    }

    return fetch(new Request(upstream, init));
  },
};
