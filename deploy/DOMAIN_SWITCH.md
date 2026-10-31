# Switch: our app to www.nriparentservice.com, WordPress to travel.nriparentservice.com, no Cloudflare

## The result

| Address | Today | After |
|---|---|---|
| `www.nriparentservice.com` | WordPress (via Cloudflare) | **our app on Railway**: React home page at `/`, About at `/about-us`, the app at `/travel-companions/…`, `/travel-insurance`, `/sahayak`, `/contact-us` |
| `nriparentservice.com/<anything>` | WordPress + a Cloudflare Worker for the app's paths | redirects (301) to `https://www.nriparentservice.com/<anything>`, the path kept |
| `travel.nriparentservice.com` | a Cloudflare redirect to the app | **WordPress**: the same files and database on MilesWeb |
| old app links on `travel.` (`/auth/…`, `/match/…`, `/trips` … from e-mails and WhatsApp) | redirect to the app | still redirect to the app |
| WordPress's old addresses on the main domain (`/privacy-policy/`, `/blog/`, the 10 posts) | WordPress | redirect to our pages (posts to our blog) |
| e-mail `…@nriparentservice.com` | MilesWeb | MilesWeb, unchanged |
| the domain's records | Cloudflare | **GoDaddy** |

**Why www:** Railway has no fixed IP, so a domain needs a CNAME record to reach it. The bare address
(no www) can't have a CNAME at GoDaddy; Railway's docs list GoDaddy as unsupported for it. `www` can.
So the app answers at `www`, and the bare address points at MilesWeb, which redirects every request to
`www` with its path, by a rule in `.htaccess`. That keeps every old link, Google result and WhatsApp
template link working.

**Time:** Part 1, about an hour; nothing changes for visitors. Parts 2–4, about two hours in one sitting,
at the quietest hour. Part 5 whenever you're ready, at least two or three days later: 20 minutes, then
up to 48 hours of waiting. Until then Cloudflare stays, holding the records with the cloud grey, so the
site already works the way it will on GoDaddy.

## The logins

| Service | Where | Used in |
|---|---|---|
| **Railway** | railway.com → Login → the project → the **travel-companion** service (address `travel-companion-production-261c.up.railway.app`) | Parts 1, 2 |
| **MilesWeb** | client area → Services → the hosting plan → **Login to cPanel** (server vivid.herosite.pro, user `preventi1`) | Parts 1, 4 |
| **WordPress** | `travel.nriparentservice.com` + your hidden login address (WPS Hide Login) | Part 4 |
| **Cloudflare** | dash.cloudflare.com → nriparentservice.com | Parts 1, 2, 4, 5 (then it's gone) |
| **GoDaddy** | sso.godaddy.com → My Products → nriparentservice.com → **DNS** | Part 5 |
| **Google Cloud** | console.cloud.google.com → APIs & Services → Credentials | Part 1 (Google sign-in) |
| **Meta** | developers.facebook.com → your app | Part 3 (webhooks) |
| **Search Console** | search.google.com/search-console | Parts 1, 3 |
| **tawk.to, Google Ads** | their dashboards | Part 3 (lead webhooks) |

**Never:**
- remove nriparentservice.com from cPanel: that deletes the mailboxes;
- touch preventia360.com;
- cancel the MilesWeb plan.

Turn on two-step sign-in everywhere. WordPress stays online and was broken into twice in October: keep
it updated, and change both admins' passwords if that's still open.

---

## Part 1: get ready (nothing changes for visitors)

1. **Commit and push the switch code.** These files are not committed yet:
   - changed: `app/__init__.py`, `app/routes/admin_blog.py`, `app/routes/homepage_draft.py`,
     `app/routes/main.py`, `app/services/access.py`, `app/services/urls.py`,
     `app/services/wp_blog.py`, `app/static/homepage-draft/homepage-draft.js`,
     `app/templates/_analytics.html`, `app/templates/admin/blog_import.html`,
     `app/templates/homepage_draft/landing.html`, `deploy/cloudflare-worker.js`,
     `frontend/homepage-draft/src/components/Closing.jsx`
   - new: `app/services/old_site.py`, `app/services/wp_import.py`, `tests/test_domain_switch.py`,
     this file

   Push `main`; Railway deploys. While the Worker is in front, the site behaves as before.
2. **Cloudflare → DNS → Records → Import and Export → Export.** Keep the file: it's the full record
   list you'll copy to GoDaddy, and the way back.
3. **Our admin → Blog → Import blog posts → From the old WordPress site → Bring the WordPress posts
   over.** Check them at `nriparentservice.com/travel-companions/blog`. Do it now, while WordPress is
   still at the main domain.
4. **Google sign-in.** Google Cloud → APIs & Services → Credentials → the OAuth client. *Add*; don't
   remove the old ones:
   - Authorized JavaScript origins: `https://www.nriparentservice.com`
   - Authorized redirect URIs: `https://www.nriparentservice.com/travel-companions/auth/google/authorized`

   If Facebook sign-in is set up: Facebook app → Facebook Login → Settings → Valid OAuth Redirect
   URIs, add `https://www.nriparentservice.com/travel-companions/auth/facebook/authorized`, and App
   domains, add `www.nriparentservice.com`.
5. **Search Console** → Add property → **Domain** → `nriparentservice.com`. Copy the
   `google-site-verification=…` text. Cloudflare → DNS → Add record: TXT, Name `@`, Content that text →
   Save → **Verify**. Remove owners you don't know (the October attackers used `sgab97294@gmail.com`
   and `sayaoranglohh2@gmail.com`).
6. **cPanel → Domains → Create A New Domain**:
   - Domain: `travel.nriparentservice.com`
   - Tick **Share document root (/home/preventi1/nriparentservice.com)**
   - Submit.

   On an older cPanel: **Subdomains**, Subdomain `travel`, Domain `nriparentservice.com`, Document Root
   `nriparentservice.com`. It points the new name at the same WordPress folder; nothing is copied.
7. **cPanel → Advanced → Terminal** (or SSH), to back up WordPress:

   ```
   cd ~/nriparentservice.com
   wp db export ~/nri-wp-before-move.sql
   grep -n "WP_HOME\|WP_SITEURL" wp-config.php
   ```

   The `grep` should print nothing. If it prints a line, that line must say
   `https://travel.nriparentservice.com` after Part 4 step 3.

## Part 2: Railway takes www

1. **Railway** → the service → **Settings → Networking → + Custom Domain** → type
   `www.nriparentservice.com` → port **8080** if asked → Add. Railway shows a **CNAME** target (like
   `abc123.up.railway.app`) and a **TXT** record. Copy both. Only `www`: the bare address doesn't go to
   Railway.
2. **Cloudflare → DNS → Records:**
   - **Add record:** TXT, with the Name and Content exactly as Railway shows.
   - Delete the `www` row. **Add record:** CNAME, Name `www`, Target = Railway's target, **Proxy
     status off** (grey) → Save.
3. Wait until Railway shows `www.nriparentservice.com` ready with its certificate (minutes, up to an
   hour).
4. **Railway → the service → Variables**, then **Deploy** if Railway asks:

   | Variable | New value |
   |---|---|
   | `APP_PUBLIC_HOST` | `www.nriparentservice.com` |
   | `SITE_URL` | `https://www.nriparentservice.com/travel-companions` |
   | `WP_SITE_URL` | `https://travel.nriparentservice.com` |
   | `VISITOR_PING_URL` | `https://www.nriparentservice.com/travel-companions` |
   | `APP_URL_PREFIX` | unchanged: `/travel-companions` |

   When it's deployed, `https://www.nriparentservice.com/` opens our home page, `https://www.nriparentservice.com/home`.
   Every link, e-mail, sign-in
   and sitemap the app writes now says `www`. The bare address still works through the Worker until
   Part 4.

## Part 3: point the outside services at www

A webhook or form that posts to the bare address would meet a redirect, and posts don't follow
redirects. In each of these, change only the start of the address from `https://nriparentservice.com`
to `https://www.nriparentservice.com`; the rest stays the same.

| Where | The address now |
|---|---|
| Meta app → WhatsApp → Configuration → Callback URL (US number, if connected) | `https://www.nriparentservice.com/travel-companions/api/whatsapp/lines-webhook` |
| Meta app → Webhooks → Page → leadgen (Facebook lead ads, if set up) | `https://www.nriparentservice.com/travel-companions/api/crm/meta-webhook` |
| tawk.to → Administration → Webhooks | `https://www.nriparentservice.com/travel-companions/api/crm/tawk-webhook` |
| Google Ads → the lead form → Webhook URL | `https://www.nriparentservice.com/travel-companions/api/crm/google-leads` |
| lead forms on other websites | `https://www.nriparentservice.com/travel-companions/api/leads` |
| the live chat line on other websites | `<script src="https://www.nriparentservice.com/travel-companions/live-chat.js" async></script>` |
| WhatsApp CRM box (studio.preventia360.com) `.env.local`, then rebuild | `NEXT_PUBLIC_PORTAL_ORIGIN=https://www.nriparentservice.com`, `PORTAL_URL=https://www.nriparentservice.com/travel-companions/admin/messaging/sso` (`FRAME_ANCESTORS` already lists www) |

Meta asks to verify the new callback with the same verify token as before. Use **Test** in Meta and in
tawk.to to see each one arrive.

## Part 4: WordPress to travel., the bare address to www

1. **Cloudflare → Rules** (Redirect Rules, Page Rules): delete the rule for `travel.nriparentservice.com`.
2. **Cloudflare → DNS:** delete the `travel` row. **Add record:** A, Name `travel`, IPv4
   `103.86.176.249`, **grey** → Save. Then **cPanel → SSL/TLS Status** → tick `travel.nriparentservice.com`
   → **Run AutoSSL**, and wait for green. `www.travel…` failing is fine.
3. **Move WordPress to its new address.** cPanel → Terminal:

   ```
   cd ~/nriparentservice.com
   wp search-replace '//nriparentservice.com' '//travel.nriparentservice.com' --all-tables-with-prefix --skip-columns=guid --dry-run
   ```

   The dry run only counts. If the numbers look sensible, run the real thing:

   ```
   wp search-replace '//nriparentservice.com' '//travel.nriparentservice.com' --all-tables-with-prefix --skip-columns=guid
   wp search-replace '\/\/nriparentservice.com' '\/\/travel.nriparentservice.com' --all-tables-with-prefix --skip-columns=guid
   wp search-replace '//www.nriparentservice.com' '//travel.nriparentservice.com' --all-tables-with-prefix --skip-columns=guid
   wp option get home
   wp option get siteurl
   wp option update blog_public 0
   wp cache flush
   ```

   - The second line catches the addresses Elementor and Slider Revolution store as `https:\/\/…`.
   - Both `get`s must print `https://travel.nriparentservice.com`.
   - `blog_public 0` keeps Google from listing WordPress's copies of the posts our blog now has
     (Settings → Reading → *Discourage search engines*).
   - E-mail addresses aren't touched: they have no `//`.
4. **The redirects.** cPanel → File Manager → `nriparentservice.com` → Settings → tick *Show Hidden Files*
   → edit `.htaccess`. Paste this at the **very top** and save:

   ```
   # BEGIN domain-switch: the main site is our app at www; WordPress answers only at travel.
   <IfModule mod_rewrite.c>
   RewriteEngine On
   RewriteCond %{REQUEST_URI} !^/\.well-known/
   RewriteCond %{HTTP_HOST} ^nriparentservice\.com$ [NC]
   RewriteRule ^(.*)$ https://www.nriparentservice.com/$1 [R=301,L]
   RewriteCond %{HTTP_HOST} ^travel\.nriparentservice\.com$ [NC]
   RewriteRule ^((travel-companions|travel-insurances?|sahayak|contact-us|about|admin|api|auth|claim|connections|contact|cs|dashboard|files|help|how-it-works|inbox|match|my|privacy|promotion|reviews|saved-filters|settings|static|switch-view|terms|trips|work-as|live-chat\.js)(/.*)?)$ https://www.nriparentservice.com/$1 [R=301,L]
   </IfModule>
   # END domain-switch
   ```

   - The first rule sends the bare address, whatever the path, to `www`. `/.well-known/` stays, so the
     padlock certificate can still renew.
   - The second sends the app's old links on `travel.` to `www`, where the app puts each one inside
     `/travel-companions/`. None of these names is a WordPress page (WordPress's are `/about-us/`,
     `/contactus/`, `/privacy-policy/` …), and `/blog/` stays with WordPress.
5. **Cloudflare → DNS:** delete the `A` row named `nriparentservice.com` (and its `AAAA`, if any).
   **Add record:** A, Name `@`, IPv4 `103.86.176.249`, **grey** → Save. MilesWeb already has a padlock
   for the bare address. If the browser warns, cPanel → SSL/TLS Status → Run AutoSSL.
6. **WordPress admin** at `travel.nriparentservice.com` + your hidden login address (log in again):
   - **LiteSpeed Cache → Toolbox → Purge All**
   - **Elementor → Tools → Regenerate CSS & Data**, then **Sync Library**

### Check (private window, and a phone on mobile data)

| Open | Expect |
|---|---|
| `https://www.nriparentservice.com/` | lands on our home page, `https://www.nriparentservice.com/home`, padlock OK |
| `https://nriparentservice.com/` | lands on `https://www.nriparentservice.com/home` |
| `https://nriparentservice.com/travel-insurance` | lands on `https://www.nriparentservice.com/travel-insurance` |
| `https://nriparentservice.com/privacy-policy/` | ends on `www…/privacy-policy` (ours) |
| an old post, e.g. `nriparentservice.com/travel-insurance-for-parents-travelling-to-usa/` | ends on the same post at `www…/blog/…` |
| `www…/blog`, then a post, then `www…/travel-companions/blog` | the blog is at `/blog/…`; the long address lands on `/blog` |
| `www…/travel-companions/`, then Sign in, also with Google | signing in works |
| `www…/robots.txt`, `/sitemap.xml` | the sitemap starts with `https://www.nriparentservice.com/home` |
| `https://travel.nriparentservice.com/` | WordPress, padlock OK, pictures and slider showing |
| a WordPress page and a post | they open and stay on `travel.` |
| `https://travel.nriparentservice.com/auth/login` | ends on `www…/travel-companions/auth/login` |
| Admin → Set-up → the WhatsApp CRM | opens inside the portal (after its rebuild) |
| a test lead from tawk.to and from a lead form | arrives in Leads |
| e-mail to `info@nriparentservice.com`, and a reply from it | both arrive |
| Admin → Inbox → Visitors | a new visit shows a real city |

Then: **Search Console** → Sitemaps: remove WordPress's, submit
`https://www.nriparentservice.com/sitemap.xml`. URL inspection on `https://www.nriparentservice.com/home`
→ Request indexing.

## Part 5: move the records to GoDaddy and remove Cloudflare (later, when you're ready)

Wait until Parts 2–4 have run quietly for a few days: going back is simple only while Cloudflare still
holds the records.

1. **Cloudflare → DNS → Export** once more: this is the final list.
2. **GoDaddy** → My Products → nriparentservice.com → **DNS** → tab **Nameservers** → **Change
   Nameservers** → **GoDaddy Nameservers (recommended)** → Save, and confirm.
3. At once, tab **DNS Records**: make it match this list exactly, and add any other record from the
   export (a `_domainkey`, say). Delete GoDaddy's "Parked" `A` record, and change its default
   `www → @` CNAME to the Railway target:

   | Type | Name | Value | Note |
   |---|---|---|---|
   | A | `@` | `103.86.176.249` | the bare address → MilesWeb → redirect to www |
   | CNAME | `www` | Railway's target (`….up.railway.app`) | our app |
   | TXT | as Railway shows | as Railway shows | Railway's proof |
   | A | `travel` | `103.86.176.249` | WordPress |
   | A | `mail` | `103.86.176.249` | e-mail |
   | A | `ftp` | `103.86.176.249` | |
   | MX | `@` | `mail.nriparentservice.com`, priority 0 | e-mail |
   | TXT | `@` | `v=spf1 +a +mx include:relay.mailbaby.net ~all` | e-mail |
   | TXT | `_dmarc` | `v=DMARC1;p=quarantine;sp=none;adkim=r;aspf=r;pct=100;fo=0;rf=afrf;ri=86400` | e-mail |
   | TXT | `@` | `google-site-verification=…` | Search Console |

4. **Wait** until the world sees GoDaddy: open
   `https://dns.google/resolve?name=nriparentservice.com&type=NS` and look for `domaincontrol.com`.
   That's usually a few hours, up to 48. Both sets of records are the same, so visitors notice nothing
   meanwhile. Don't touch Cloudflare until then.
5. **Cloudflare:**
   - **Workers & Pages** → the Worker → Settings → **Delete**.
   - Websites → nriparentservice.com → Overview → *Advanced Actions* → **Remove site from Cloudflare**.
6. Run the check table once more, the e-mail rows especially.

## Going back

**Before Part 5**, while Cloudflare holds the records:
1. Cloudflare: put back the `@`, `www` and `travel` records from the Part 1 export (orange) and the
   `travel.` redirect rule.
2. Railway: put back `APP_PUBLIC_HOST=nriparentservice.com` and
   `SITE_URL=https://nriparentservice.com/travel-companions`.
3. WordPress:

   ```
   cd ~/nriparentservice.com && wp db import ~/nri-wp-before-move.sql && wp cache flush
   ```

   Then remove the `domain-switch` block from `.htaccess`, and LiteSpeed → Purge All.

**After Part 5**, the Worker setup doesn't exist any more. Fix forward instead.

---

## For developers

- `PrefixMiddleware` (app/__init__.py): `APP_PUBLIC_HOST` is the site's one address, now `www`. A
  direct request on it serves the domain's own pages (`APP_SITE_PAGES`: `/home`, `/about-us`, the legal
  pages, `/robots.txt`, `/sitemap.xml`) and its sections (`APP_SITE_SECTIONS`: everything under `/blog`).
  The app's `url_for` (`SiteFlask` → `urls.to_site`) writes those at their root address, so every blog
  link, redirect, e-mail, canonical and sitemap entry says `/blog/…`, and `/travel-companions/blog/…`
  301s there. It hands the rest of the root to `services/old_site.py`, which:
  - sends the root `/` to the home page, `/home` (keeping campaign tags), and the old draft address
    `/homepage-draft` there too;
  - redirects WordPress's old addresses;
  - answers 410 for WordPress's machinery;
  - moves unprefixed app addresses inside `/travel-companions/`, which the `travel.` rule relies on.
- Requests with `X-Forwarded-Prefix: /travel-companions` (the Worker, until it's deleted) behave as
  before.
- The bare address never reaches Railway; MilesWeb's `.htaccess` redirects it.
- `services/wp_blog.py` reads WordPress at `WP_SITE_URL`; `services/wp_import.py` copies its posts.
- Tests: `tests/test_domain_switch.py`. Checked on 2026-10-31 with `APP_PUBLIC_HOST=www.nriparentservice.com`:
  `/`, `/about-us`, the sitemap, robots and the old WordPress addresses all answer on `www`.
