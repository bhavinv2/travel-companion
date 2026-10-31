# Plan A: our app answers at nriparentservice.com itself; Cloudflare only holds the records

This replaces the "www" plan in DOMAIN_SWITCH.md (kept for its WordPress and MilesWeb detail). The app
code needs no change: `APP_PUBLIC_HOST=nriparentservice.com` is what Railway already has, and `www`
already redirects to the bare address.

## The result

| Address | After |
|---|---|
| `nriparentservice.com` | **our app on Railway**: `/home`, `/blog`, `/about-us`, `/travel-insurance`, `/sahayak`, `/contact-us`, `/travel-companions/…` |
| `www.nriparentservice.com` | redirects (301) to the same path on `nriparentservice.com` |
| `travel.nriparentservice.com` | **WordPress**, on MilesWeb (the same files and database). Old app links that people saved with `travel.` in them redirect to the app. |
| e-mail `…@nriparentservice.com` | MilesWeb, unchanged |
| the domain's records | still Cloudflare, but **DNS only**: grey cloud on every record, no Worker, no rules |

**Why Cloudflare stays for records:** Railway has no fixed IP, so the bare address needs a CNAME-style
record, and GoDaddy's DNS can't do that. Cloudflare's DNS can ("CNAME flattening"). With the cloud grey
it sits outside the traffic: visitors, forms and webhooks go straight to Railway, and the app sees real
visitor addresses.

**Unchanged, so nothing to redo:** Google and Facebook sign-in, Meta and tawk.to webhooks, the WhatsApp
CRM links, `SITE_URL`, `APP_PUBLIC_HOST`.

## Where things stand (checked 2026-10-31, evening)

| | State | What is left |
|---|---|---|
| `nriparentservice.com` | **our app already answers**: `/` → `/home`, `/blog`, `/about-us`, `/contact-us`, `/travel-companions/`, sitemap, `wp-login.php` → 410 | the `@` row is still **orange** (Railway says "Cloudflare proxy detected"): visitors reach us with Cloudflare's address, so Visitors and the rate limits see Cloudflare, not them. Turn it grey in Step 3. |
| `www.nriparentservice.com` | **broken**: Railway's "Application not found" (the row points at Railway, but www is not one of Railway's two domains) | free the slot (Step 2) and add www (Step 3) |
| `travel.nriparentservice.com` | a Cloudflare rule sends every path to `nriparentservice.com/travel-companions/…`; still one of Railway's two domains | Step 2 |
| WordPress | still on MilesWeb with its 10 posts, but **reachable at no address** (bare → Railway, travel. → the rule, www → Railway) | it must answer at `travel.` before the posts can be brought over |
| old post links (Google, WhatsApp) | 1 of 10 redirects; 5 more do once the next deploy is live (`old_site.OLD_POSTS`, because the hand-copied posts got other slugs); 4 stay 404 until the import | Step 2, items 5 and 7 |
| the visitor ping | goes to `travel.` (Railway's `RAILWAY_PUBLIC_DOMAIN`), which the rule redirects, so the bubble's visits are lost | `VISITOR_PING_URL` in Step 1 |
| Railway deploy settings | Start command still runs gunicorn directly (no `flask db upgrade`) | Step 1. The Pre-deploy field shows `npm run migrate` in grey: that is Railway's placeholder, the field is empty, leave it. |
| code | GitHub `main` = Railway's deploy (the switch commit "New uri design") | push the OLD_POSTS commit |

## Step 0: bring the site back today (2 minutes)

Cloudflare → Workers & Pages → the Worker → Edit code → change the `ORIGIN` line to
`const ORIGIN = "nriparentservice.up.railway.app";` → Deploy. (Railway renamed the app's address; the old
one no longer exists.) If you go straight on to Step 3 today, skip this.

## Step 1: Railway, before anything else (10 minutes)

Railway → the **travel-companion** service:

1. **Settings → Deploy → Start command: clear it.** Then the Dockerfile's own command runs, which does
   `flask db upgrade` before starting. (The field now starts gunicorn directly, so database changes
   never apply.)
2. **Settings → Deploy → Pre-deploy command:** leave it. The grey `npm run migrate` is Railway's placeholder
   text, not a value (a real `npm run migrate` would fail every deploy: there is no `package.json`).
3. **Variables:**
   - `FLASK_SECRET_KEY`, `SECRET_KEY`: two different long random values
     (`python -c "import secrets; print(secrets.token_urlsafe(48))"`). Everybody is signed out once.
   - `MAIL_PASSWORD`: a Gmail App Password for `bhavinvulli85@gmail.com`.
   - `APP_ALIAS_PATHS` = `/travel-insurance,/sahayak,/contact-us`
   - new `WP_SITE_URL` = `https://travel.nriparentservice.com`
   - new `VISITOR_PING_URL` = `https://nriparentservice.com/travel-companions`
   - Leave `APP_PUBLIC_HOST`, `SITE_URL`, `APP_URL_PREFIX` as they are.
4. **Rotate the secrets that were pasted into a chat:** Google OAuth secret, Facebook OAuth secret,
   `PREVENTIA_API_KEY`, `WACRM_API_KEY`, `WACRM_PORTAL_SECRET` (the last one on both sides).
5. Make sure the latest commit has deployed (Deployments tab: green) and
   `https://nriparentservice.up.railway.app/home` opens.

## Step 2: WordPress to travel. (30 minutes; follow DOMAIN_SWITCH.md for the commands)

Railway allows two custom domains. Today it holds `nriparentservice.com` and `travel.nriparentservice.com`.
`travel.` must leave Railway and go to MilesWeb, which frees a place for `www`.

1. **Railway → Settings → Networking:** delete `travel.nriparentservice.com`; **add `www.nriparentservice.com`**
   (note the CNAME target and any TXT it asks for).
2. **Cloudflare → Rules:** delete the rule that redirects `travel.` to the app.
3. **Cloudflare → DNS:** delete the `travel` row; add **A**, Name `travel`, `103.86.176.249`, **grey**.
4. **cPanel → Domains → Create A New Domain:** `travel.nriparentservice.com`, tick *Share document root*.
   Then **SSL/TLS Status → Run AutoSSL** for it.
5. **WordPress back-up and move**: DOMAIN_SWITCH.md, Part 1 step 7 and Part 4 step 3
   (`wp db export`, then the three `wp search-replace` lines, `blog_public 0`, `wp cache flush`).
6. **`.htaccess` in the WordPress folder** — paste at the very top (this replaces the Part 4 block;
   there is no bare-address rule any more, because the bare address leaves MilesWeb in Step 3):

   ```
   # BEGIN domain-switch: WordPress answers at travel.; the app's old links on travel. go to the app
   <IfModule mod_rewrite.c>
   RewriteEngine On
   RewriteCond %{HTTP_HOST} ^travel\.nriparentservice\.com$ [NC]
   RewriteRule ^((travel-companions|travel-insurances?|sahayak|contact-us|about|admin|api|auth|claim|connections|contact|cs|dashboard|files|help|how-it-works|inbox|match|my|privacy|promotion|reviews|saved-filters|settings|static|switch-view|terms|trips|work-as|live-chat\.js)(/.*)?)$ https://nriparentservice.com/$1 [R=301,L]
   </IfModule>
   # END domain-switch
   ```

7. **Our admin → Blog → Import → Bring the WordPress posts over.** Only now: WordPress answers at no
   address until items 3–5 are done, and before the `search-replace` its pictures point at
   `nriparentservice.com/wp-content/…`, which our app answers with 410, so none would copy. `WP_SITE_URL`
   (Step 1) must already say `https://travel.nriparentservice.com`. The 5 posts copied by hand before the
   switch are left alone (same title, or a slug in `old_site.OLD_POSTS`); the other 5 come over with
   their WordPress slugs, and their old links then redirect.
8. WordPress admin at `travel.nriparentservice.com`: LiteSpeed Cache → Purge All; Elementor → Tools →
   Regenerate CSS & Data → Sync Library.

## Step 3: the cut-over (15 minutes; the quietest hour)

1. **Cloudflare → Workers & Pages → Routes:** remove the four routes (`nriparentservice.com/travel-companions*`,
   `/travel-insurance*`, `/sahayak*`, `/contact-us*`). Don't delete the Worker yet.
2. **Cloudflare → DNS:**
   - delete the proxied `@` row(s) (orange, A or AAAA);
   - add **CNAME**, Name `@`, Target = the Railway target (`….up.railway.app`), **grey (DNS only)**;
   - set `www`: **CNAME**, Target = Railway's target, **grey**;
   - add any TXT record Railway asked for;
   - make sure **every other row is grey**: `mail`, `ftp`, `travel`, MX, TXT. (E-mail was grey already.)
3. **Railway → Settings → Networking:** wait for both domains to show a green tick (a few minutes; Railway
   issues the certificates).
4. **Check** (a private window, and a phone on mobile data):

   | Open | Expect |
   |---|---|
   | `https://nriparentservice.com/` | goes to `/home`, our home page, padlock OK |
   | `https://www.nriparentservice.com/blog` | lands on `https://nriparentservice.com/blog` |
   | `…/blog`, then a post | opens at `/blog/<post>` |
   | `…/travel-insurance`, `/sahayak`, `/contact-us` | open |
   | `…/travel-companions/`, then Sign in, also with Google | signing in works |
   | `…/robots.txt`, `/sitemap.xml` | the sitemap starts with `https://nriparentservice.com/home` |
   | `https://travel.nriparentservice.com/` | WordPress, padlock OK, pictures showing |
   | `https://travel.nriparentservice.com/auth/login` | lands on `nriparentservice.com/travel-companions/auth/login` |
   | an old post, e.g. `nriparentservice.com/how-to-buy-travel-insurance-for-parents-visiting-the-usa/` | lands on the same post at `/blog/…-usa-2` (and after the import, `…/what-is-the-best-way-to-support-parents-living-alone-in-india/` lands on `/blog/<the same slug>`) |
   | Admin → Set-up → the WhatsApp CRM | opens inside the portal |
   | a test lead from a form, and a message to the live-chat bubble | arrives |
   | e-mail to `info@nriparentservice.com`, and a reply | both arrive |
   | Admin → Inbox → Visitors | a new visit shows a real city |

## Step 4: tidy up (after a few quiet days)

- **Cloudflare:** delete the Worker (Workers & Pages → the Worker → Settings → Delete). The site stays on
  Cloudflare as DNS only, with no Worker, no proxy, no rules.
- **Search Console:** add the Domain property for `nriparentservice.com` (TXT record, Cloudflare DNS);
  remove WordPress's sitemap and submit `https://nriparentservice.com/sitemap.xml`; URL inspection on
  `https://nriparentservice.com/home` → Request indexing. Remove owners you don't know (the October
  attackers used `sgab97294@gmail.com` and `sayaoranglohh2@gmail.com`).

## Going back

Before the Worker is deleted: Cloudflare → DNS: put the orange `@` and `www` records back and re-add the
four Worker routes (Workers & Pages → Routes). If the Railway address changes again, edit `ORIGIN` in
`deploy/cloudflare-worker.js` and redeploy the Worker.

## If you want Cloudflare gone entirely, later

The bare address needs a DNS host that supports ALIAS at the apex (DNSimple, ClouDNS …). Copy every
record there, then change the nameservers at GoDaddy. Nothing else changes.
