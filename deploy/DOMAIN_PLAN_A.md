> **Superseded on 2026-11-01 by [DOMAIN_WWW_GODADDY.md](DOMAIN_WWW_GODADDY.md):** the user wants
> Cloudflare gone, so the app goes to `www.nriparentservice.com` and DNS to GoDaddy. Phase 2 of this file
> (WordPress to travel.) was carried out and stays valid.

# nriparentservice.com → our app, step by step (Plan A)

The goal: `https://nriparentservice.com` is our Railway app (it already is, through Cloudflare's proxy),
`www.` redirects to it, the old WordPress site answers only at `travel.nriparentservice.com` on
MilesWeb, and Cloudflare stays only as the DNS host (every cloud grey, no Worker, no rules).

This is the complete, click-by-click version. The old www plan is in DOMAIN_SWITCH.md and is no
longer followed.

## Before you start

**Where things stand (checked 2026-10-31 evening)**

| Address | Now | After |
|---|---|---|
| `nriparentservice.com` | our app, but through Cloudflare's proxy (orange cloud) | our app, straight from Railway (grey cloud) |
| `www.nriparentservice.com` | Railway's "Application not found" | redirects to `nriparentservice.com` |
| `travel.nriparentservice.com` | a Cloudflare rule sends everything to the app | WordPress, on MilesWeb |
| WordPress | on MilesWeb, reachable at no address | at `travel.` |
| e-mail `…@nriparentservice.com` | MilesWeb | unchanged |

**Two DNS panels exist; only Cloudflare's counts.** The domain's name servers are Cloudflare's
(`dorthy` / `johnathan.ns.cloudflare.com`), so every DNS change goes in **dash.cloudflare.com → DNS →
Records**, the page with the orange/grey cloud column. MilesWeb's cPanel also shows a record list for
the domain (Zone Editor, name servers `odin/neon/luna.mydnsvault.com`); nobody on the internet reads
it, so changes there do nothing. Leave it alone.

**Logins you need**

| Service | Where |
|---|---|
| Railway | railway.com → project **grand-enjoyment** → environment **production** → service **travel-companion** |
| Cloudflare | dash.cloudflare.com → **nriparentservice.com** |
| MilesWeb panel | **dashboard.mympanel.com** (Websites, Emails, SSL & Security); shell: `ssh -p 22 preventi1@103.86.176.249` (no cPanel, no `uapi`) |
| WordPress admin | `https://travel.nriparentservice.com/` + the hidden login address (WPS Hide Login) |
| Our admin | `https://nriparentservice.com/travel-companions/admin/` |
| Google Cloud, Meta developers, Search Console | for the secrets and Search Console steps |

**Never:** remove `nriparentservice.com` from cPanel (the mailboxes live there); touch `preventia360.com`;
cancel the MilesWeb plan.

**Time:** Phase 1, 15 minutes. Phase 2, about an hour. Phase 3, 20 minutes plus up to an hour of
waiting for Railway's certificate, at the quietest hour (early morning India time). Phase 4, a few
days later, 15 minutes.

---

## Phase 1: Railway (nothing changes for visitors)

### 1.1 Push the code

The renamed-slug redirects are already pushed (commit "switch domain"). Still to push: the import's
link fix and this runbook. On your computer, in `Travel-companion/travel-companion`:

```
git add -A
git commit -m "WordPress import: point links between the posts at our blog; click-by-click runbook"
git push origin main
```

Railway builds and deploys on its own. Railway → **Deployments**: wait until the newest one says
**Active** (green). Then open `https://nriparentservice.com/how-to-buy-travel-insurance-for-parents-visiting-the-usa/`
in a private window: it must land on `https://nriparentservice.com/blog/how-to-buy-travel-insurance-for-parents-visiting-the-usa-2`.

### 1.2 Settings → Deploy

Railway → service **travel-companion** → **Settings** tab → scroll to **Deploy**.

1. **Custom Start Command.** The box shows `gunicorn run:app --bind 0.0.0.0:8080 …`. Delete every
   character so the box is empty, then click **Update**. Now the Dockerfile's own command runs, which
   does `flask db upgrade` (database changes) before starting the app.
2. **Pre-deploy Command.** The grey `npm run migrate` is Railway's example text, not a value. Leave it.
3. Everything else on this page stays as it is.

### 1.3 Variables

Railway → service → **Variables** tab. For each row below: click the variable (or **+ New Variable**),
type the value, press Enter. Railway stages the changes; at the top a **Deploy** / **Apply changes**
button appears: click it once you have done all of them. Everybody is signed out once (new secret keys).

On your computer, make three random values first:

```
python -c "import secrets; [print(secrets.token_urlsafe(48)) for _ in range(3)]"
```

| Variable | Set it to |
|---|---|
| `FLASK_SECRET_KEY` | the first random value |
| `SECRET_KEY` | the second random value |
| `MAIL_PASSWORD` | a Gmail **App password** for `bhavinvulli85@gmail.com`: myaccount.google.com → Security → 2-Step Verification (must be on) → **App passwords** → name it "NRI portal" → Create → the 16 letters, without spaces |
| `APP_ALIAS_PATHS` | `/travel-insurance,/sahayak,/contact-us` |
| `WP_SITE_URL` (new) | `https://travel.nriparentservice.com` |
| `VISITOR_PING_URL` (new) | `https://nriparentservice.com/travel-companions` |
| `APP_PUBLIC_HOST` | leave: `nriparentservice.com` |
| `SITE_URL` | leave: `https://nriparentservice.com/travel-companions` |
| `APP_URL_PREFIX` | leave: `/travel-companions` |

Click **Deploy** (top of the page). Wait for the deployment to be **Active**, then sign in to our
admin again at `https://nriparentservice.com/travel-companions/admin/`.

### 1.4 Rotate the secrets that were pasted into chats

Do these at any time, each one a separate small job:

| Secret | Where to make a new one | Then |
|---|---|---|
| `GOOGLE_OAUTH_CLIENT_SECRET` | console.cloud.google.com → APIs & Services → Credentials → the OAuth client `534981752888-…` → **Add secret** → copy the new one | Railway variable, Deploy, test Google sign-in, then **Disable** and delete the old secret in Google |
| `FACEBOOK_OAUTH_CLIENT_SECRET` | developers.facebook.com → the app → App settings → Basic → App secret → **Reset** | Railway variable, Deploy |
| `PREVENTIA_API_KEY` | the Care360 API admin (preventia360) → make a new key | Railway variable, Deploy, then delete the old key there |
| `WACRM_API_KEY` | the WhatsApp CRM (studio.preventia360.com/crm) → its API keys | Railway variable, Deploy |
| `WACRM_PORTAL_SECRET` | a new random value (the Python line above) | **both sides**: Railway variable **and** `PORTAL_SECRET` in the CRM box's `.env.local`, then the CRM rebuild (that is a CRM deploy: ask for it) |

---

## Phase 2: WordPress moves to travel.nriparentservice.com

Order matters: DNS first, then the padlock, then the database, then the import.

### 2.1 Cloudflare: delete the travel. redirect rule

dash.cloudflare.com → **nriparentservice.com** → left menu **Rules** → **Overview**. Find the rule
that redirects `travel.nriparentservice.com` to `nriparentservice.com/travel-companions` (it may be
under **Redirect Rules** or **Page Rules**). Click its **…** (or Edit) → **Delete** → confirm. If a
second rule mentions `travel.`, delete it too.

### 2.2 Cloudflare: point travel. at MilesWeb

Left menu **DNS** → **Records**.

1. First, **Import and Export** (top right of the records list) → **Export** → save the file. It is
   the way back.
2. Find the row named `travel`. Click **Edit** → **Delete** → confirm.
3. **Add record**:
   - Type: **A**
   - Name: `travel`
   - IPv4 address: `103.86.176.249`
   - Proxy status: click the cloud so it is **grey** ("DNS only")
   - TTL: Auto
   - **Save**.

### 2.3 MilesWeb panel: give travel. a home and a padlock (DONE 2026-11-01)

MilesWeb's panel is **dashboard.mympanel.com**, not cPanel. Its **Websites** page is the list of names the
server knows (Website Name / Document Root / Kind). There is no "Domains" tab under Manage; the Websites
page itself is that list.

1. **Websites → Add Website**: Website Name `travel.nriparentservice.com`, Document Root the **existing**
   folder `nriparentservice.com`. The row then reads `travel.nriparentservice.com | nriparentservice.com |
   Subdomain`. Nothing is copied.
2. The panel issues a Let's Encrypt certificate on its own once DNS points at the server (it did, within
   the hour). Until then browsers show a certificate warning that Chrome refuses to bypass, because the
   app sends HSTS with includeSubDomains. Just wait.
3. Keep the `nriparentservice.com` row: the mailboxes hang off it. It serves no web pages any more.
   Note: on 2026-11-01 it became the account's **Primary** website (preventia360.com was Primary
   before); both sites still work.

### 2.4 Terminal: back up, then move WordPress to travel. (DONE 2026-11-01 over SSH; backup `~/nri-wp-before-move-2026-11-01.sql`)

cPanel → **Advanced** → **Terminal** (or SSH: `ssh -p 22 preventi1@103.86.176.249`). Paste one line at a
time.

Back up:

```
cd ~/nriparentservice.com
wp db export ~/nri-wp-before-move-$(date +%F).sql
grep -n "WP_HOME\|WP_SITEURL" wp-config.php
```

The `grep` should print nothing. If it prints lines, they must be changed to
`https://travel.nriparentservice.com` after the next step (File Manager → `wp-config.php` → Edit).

Dry run (it only counts):

```
wp search-replace '//nriparentservice.com' '//travel.nriparentservice.com' --all-tables-with-prefix --skip-columns=guid --dry-run
```

The real thing:

```
wp search-replace '//nriparentservice.com' '//travel.nriparentservice.com' --all-tables-with-prefix --skip-columns=guid
wp search-replace '\/\/nriparentservice.com' '\/\/travel.nriparentservice.com' --all-tables-with-prefix --skip-columns=guid
wp search-replace '//www.nriparentservice.com' '//travel.nriparentservice.com' --all-tables-with-prefix --skip-columns=guid
wp option get home
wp option get siteurl
wp option update blog_public 0
wp cache flush
```

- Both `get` lines must print `https://travel.nriparentservice.com`.
- The second search-replace catches the `https:\/\/…` spelling Elementor and Slider Revolution use.
- `blog_public 0` = Settings → Reading → "Discourage search engines": Google must not list the old
  copies of the posts.
- E-mail addresses are untouched (they have no `//`).

Then `https://travel.nriparentservice.com/` must open WordPress with pictures, and stay on `travel.`.

### 2.5 The redirect rules on travel. (DONE 2026-11-01; old file kept as `.htaccess.before-domain-switch`)

cPanel → **File Manager** → folder `nriparentservice.com` → top right **Settings** → tick **Show
Hidden Files** → Save → right-click `.htaccess` → **Edit**. Paste this at the **very top** and Save:

```
# BEGIN domain-switch: WordPress answers at travel.; the app's old links on travel. go to the app
<IfModule mod_rewrite.c>
RewriteEngine On
RewriteCond %{HTTP_HOST} ^travel\.nriparentservice\.com$ [NC]
RewriteRule ^((travel-companions|travel-insurances?|sahayak|contact-us|about|admin|api|auth|claim|connections|contact|cs|dashboard|files|help|how-it-works|inbox|match|my|privacy|promotion|reviews|saved-filters|settings|static|switch-view|terms|trips|work-as|live-chat\.js)(/.*)?)$ https://nriparentservice.com/$1 [R=301,L]
</IfModule>
# END domain-switch
```

Check: `https://travel.nriparentservice.com/auth/login` must land on
`https://nriparentservice.com/travel-companions/auth/login`, and
`https://travel.nriparentservice.com/about-us/` must stay on WordPress.

### 2.6 Our admin: bring the WordPress posts over

`https://nriparentservice.com/travel-companions/admin/` → **Blog** → **Import** → the **From the old
WordPress site** box → **Bring the WordPress posts over**.

Expect the message "5 posts brought over from WordPress and published. 5 already here, left alone."
(the 5 copied by hand before the switch are recognised by title or slug). Open **Blog** and read each
new post once: pictures present, links work. Then in a private window:

- `https://nriparentservice.com/what-is-the-best-way-to-support-parents-living-alone-in-india/` → lands
  on `…/blog/what-is-the-best-way-to-support-parents-living-alone-in-india`.

If it says "Nothing was brought over: … did not answer", `WP_SITE_URL` is not set (Phase 1.3) or 2.3
is not finished.

### 2.7 WordPress admin: caches

`https://travel.nriparentservice.com/` + the hidden login address. Sign in (use **Lost your password?**
if needed: both admins' passwords were reset on 2026-10-23).

- **LiteSpeed Cache** → Toolbox → **Purge All**
- **Elementor** → Tools → **Regenerate CSS & Data**, then **Sync Library**
- Settings → Reading: "Discourage search engines" must be ticked

---

## Phase 3: the cut-over (quietest hour)

### 3.1 Railway: swap travel. for www

Railway → service → **Settings** → **Networking** → **Public networking**.

1. On the row `travel.nriparentservice.com`: click its **…** / trash icon → **Remove domain** →
   confirm. (This frees the second of the plan's two custom-domain places.)
2. **+ Custom Domain** → type `www.nriparentservice.com` → port **8080** → **Add**.
3. Railway now shows **two records to create**: a **CNAME** (Name `www`, Value something like
   `abc123.up.railway.app`) and a **TXT** (for ownership). Leave this dialog open, or copy both
   exactly. Both are required: with only the CNAME, www would answer 404.

### 3.2 Cloudflare: www, grey

**DNS → Records**:

1. Find the row named `www`. **Edit** → Type **CNAME**, Target = the Value Railway showed, Proxy
   status **grey** (DNS only) → **Save**. (If there is no `www` row: **Add record** with those values.)
2. **Add record** → Type **TXT**, Name and Content exactly as Railway showed (the name is
   `_railway-verify.www`, the content starts with `railway-verify=`) → **Save**.
3. Back in Railway, wait for `www.nriparentservice.com` to get a **green tick** (usually minutes, up to
   an hour). Then `https://www.nriparentservice.com/blog` must land on
   `https://nriparentservice.com/blog`.

### 3.3 Cloudflare: the Worker's routes

Left menu **Workers & Pages** → click the Worker (the one with `nriparentservice.com/travel-companions*`
on it) → **Settings** → **Domains & Routes**. For each of the four routes
(`nriparentservice.com/travel-companions*`, `…/travel-insurance*`, `…/sahayak*`, `…/contact-us*`):
**…** → **Remove**. Do not delete the Worker itself yet.

### 3.4 Cloudflare: the bare address, grey

**DNS → Records**. The row named `nriparentservice.com` (type CNAME, target `….up.railway.app`,
orange cloud):

1. **Edit** → click the cloud so it is **grey** (DNS only) → **Save**. Keep the target as it is.
2. If there is also an **A** or **AAAA** row named `nriparentservice.com`, delete it (the app has
   no fixed address; the CNAME is the only right row).
3. Go down the whole list. **Every** row must now have a grey cloud: `nriparentservice.com`, `www`,
   `travel`, `mail`, `ftp`, the MX row, the TXT rows (`v=spf1…`, `_dmarc`, `google-site-verification`,
   Railway's). Orange on any of them: Edit → grey → Save.
4. Optional tidy: the `ftp` row is a CNAME that now follows the app. If FTP is used, change it to
   **A** `103.86.176.249`, grey.

### 3.5 Wait for Railway's padlock

Railway → Settings → Networking: `nriparentservice.com` goes from "Cloudflare proxy detected" to a
**green tick** when Railway has issued its certificate. Usually minutes, up to an hour. Until then a
browser may warn about the certificate on `nriparentservice.com`: that is the one window of risk,
which is why this is done at the quietest hour. **If the tick has not come after an hour:** Cloudflare →
DNS → the `nriparentservice.com` row → Edit → orange → Save (everything works again within a minute,
as before), and ask Railway support with a screenshot.

### 3.6 Check (private window, and a phone on mobile data)

| Open | Expect |
|---|---|
| `https://nriparentservice.com/` | lands on `/home`, our home page, padlock OK |
| `https://www.nriparentservice.com/blog` | lands on `https://nriparentservice.com/blog` |
| `/blog`, then a post | opens at `/blog/<post>` |
| `/travel-insurance`, `/sahayak`, `/contact-us`, `/about-us` | open |
| `/travel-companions/`, then Sign in, also with Google | signing in works |
| `/robots.txt`, `/sitemap.xml` | the sitemap starts with `https://nriparentservice.com/home` |
| `https://nriparentservice.com/how-to-buy-travel-insurance-for-parents-visiting-the-usa/` | lands on `/blog/…-usa-2` |
| `https://nriparentservice.com/wp-login.php` | "Gone." |
| `https://travel.nriparentservice.com/` | WordPress, padlock OK, pictures and slider showing |
| `https://travel.nriparentservice.com/auth/login` | lands on `nriparentservice.com/travel-companions/auth/login` |
| Admin → Set-up → the WhatsApp CRM | opens inside the portal |
| a test lead from a form, and a message to the live-chat bubble | arrive in Leads / Inbox |
| e-mail to `info@nriparentservice.com`, and a reply from it | both arrive |
| Admin → Inbox → Visitors (after the step above) | the new visit shows a real city, not a Cloudflare one |

---

## Phase 4: tidy up (after a few quiet days)

1. **Cloudflare** → Workers & Pages → the Worker → **Settings** → bottom → **Delete** → type its name
   → confirm. Rules → Overview: nothing should be left. SSL/TLS, caching and the rest no longer
   matter: with every cloud grey, Cloudflare only answers DNS questions.
2. **Search Console** (search.google.com/search-console):
   - **Add property** → **Domain** → `nriparentservice.com` → it shows a `google-site-verification=…`
     text → Cloudflare → DNS → **Add record**: TXT, Name `@`, Content that text, grey → Save → back in
     Search Console → **Verify**.
   - Settings → Users and permissions: remove owners you don't know (the October attackers used
     `sgab97294@gmail.com` and `sayaoranglohh2@gmail.com`).
   - **Sitemaps**: remove WordPress's (`sitemap_index.xml`, `post-sitemap.xml` …); add
     `https://nriparentservice.com/sitemap.xml`.
   - **URL inspection** → `https://nriparentservice.com/home` → **Request indexing**. Same for `/blog`.
3. **Google Analytics / Ads**: nothing to change; the addresses did not move.
4. A week later, if nobody needs WordPress: leave it at `travel.` but keep it updated, or follow
   DOMAIN_SWITCH.md Part 6 to remove its files and database (keep the cPanel domain: the mailboxes).

---

## Going back

- **Phase 3 undone in one minute:** Cloudflare → DNS → the `nriparentservice.com` row → Edit → orange
  → Save. The site is as it was before Phase 3 (through Cloudflare's proxy). The Worker routes are
  not needed for that: the bare address already points at Railway.
- **Phase 2 undone:** Cloudflare → DNS: `travel` back to a CNAME on Railway's target, orange; the
  redirect rule back (Rules → Create rule → Redirect Rule: hostname `travel.nriparentservice.com`,
  dynamic redirect to `concat("https://nriparentservice.com/travel-companions", http.request.uri.path)`,
  301). WordPress: `cd ~/nriparentservice.com && wp db import ~/nri-wp-before-move-<date>.sql && wp cache flush`,
  and remove the `domain-switch` block from `.htaccess`.
- **Phase 1 undone:** the Railway variables back to their old values (they are in the Variables tab's
  history, or your paste).

## For developers

- `APP_PUBLIC_HOST=nriparentservice.com` is the site's one address. A direct request on it (no
  `X-Forwarded-Prefix`) serves the domain's own pages (`APP_SITE_PAGES`) and `/blog` at the root, and
  hands the rest to `services/old_site.py`: WordPress's old addresses redirect (its renamed posts via
  `OLD_POSTS`), its machinery answers 410, and unprefixed app addresses move inside
  `/travel-companions/`.
- `services/wp_import.py` copies WordPress's posts from `WP_SITE_URL`, skips the ones already here
  (same slug, same title, or a slug in `OLD_POSTS`) and points links between them at our blog.
- `services/visitors.py`: the live-chat bubble reports visits to `VISITOR_PING_URL`.
- Tests: `tests/test_domain_switch.py` (47). Run them with `venv/Scripts/python.exe -m pytest tests/test_domain_switch.py`.
- Reach WordPress on MilesWeb without a name, for checks:
  `curl -k --resolve nriparentservice.com:443:103.86.176.249 https://nriparentservice.com/wp-json/wp/v2/posts`.
