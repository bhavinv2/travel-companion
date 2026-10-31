# Our app at www.nriparentservice.com, DNS at GoDaddy, Cloudflare removed

Decided 2026-11-01. Replaces DOMAIN_PLAN_A.md (the bare-name plan). The WordPress half of the work is
already done: WordPress answers at `travel.nriparentservice.com` on MilesWeb with its own certificate.

## The result

| Address | After |
|---|---|
| `www.nriparentservice.com` | **our app on Railway**: `/home`, `/blog`, `/about-us`, `/travel-insurance`, `/sahayak`, `/contact-us`, `/travel-companions/…`. The address people see. |
| `nriparentservice.com` | MilesWeb answers it and redirects (301) every path to the same path on `www` |
| `travel.nriparentservice.com` | WordPress on MilesWeb (done) |
| e-mail | MilesWeb, unchanged |
| DNS | **GoDaddy**. Cloudflare removed. |

**Why www and not the bare name:** Railway has no fixed address, so a name must point at it by name
(CNAME). GoDaddy's DNS cannot do that for a bare domain, only for a sub-name like `www`. MilesWeb has a
fixed address (`103.86.176.249`), so the bare name points there and MilesWeb forwards it to `www`.

**Starting point (2026-11-01):** Cloudflare still holds the records (`@` CNAME to Railway, orange;
`www` CNAME to `@`, orange; everything else grey). Railway has `nriparentservice.com` and one free place.
WordPress is at `travel.`. MilesWeb's certificate for the bare name is valid to 2026-12-14 and renews once
the name points there again.

**Code:** `APP_PUBLIC_HOST=www.nriparentservice.com` makes `www` the site's one address; the bare name,
if it ever reaches the app, redirects to `www` (PrefixMiddleware, 2026-11-01). Everything else is
unchanged: `/travel-companions` stays, so sign-in, the CRM link and the webhooks only change their host.

---

## Phase 1: get ready (nothing changes for visitors)

1. **Push the code** (the www redirect, the import's link fix, this file):
   `git add -A && git commit -m "www as the public host; runbook" && git push origin main`.
   Railway → Deployments → wait for Active.
2. **Railway → Settings → Networking → + Custom Domain** → `www.nriparentservice.com` → port 8080 → Add.
   Copy the two records it shows: a **CNAME** (Name `www`, Value `….up.railway.app`) and a **TXT**
   (Name `_railway-verify.www`, Content `railway-verify=…`). Both are required.
3. **Cloudflare → DNS → Records** (still the live DNS for now):
   - row `www`: Edit → Target = Railway's value, cloud **grey** → Save;
   - Add record: TXT, Name `_railway-verify.www`, Content as shown → Save.
   Railway shows a green tick on `www` within the hour. `https://www.nriparentservice.com/blog` then opens
   (and, for now, redirects to the bare name; that flips in Phase 2).
4. **Railway → Variables** (everything except the three host values, which wait for Phase 2):
   `WP_SITE_URL=https://travel.nriparentservice.com`, `APP_ALIAS_PATHS=/travel-insurance,/sahayak,/contact-us`,
   new random `FLASK_SECRET_KEY` and `SECRET_KEY`, `MAIL_PASSWORD` (Gmail App password). Deploy.
   **Settings → Deploy → Custom Start Command: empty the box** → Update.
5. **Bring the posts over now:** our admin → Blog → Import → Bring the WordPress posts over.
   Expect "5 posts brought over … 5 already here, left alone."
6. **Sign-in providers, add (don't remove):**
   - Google Cloud → APIs & Services → Credentials → the OAuth client:
     Authorized JavaScript origins + `https://www.nriparentservice.com`;
     Authorized redirect URIs + `https://www.nriparentservice.com/travel-companions/auth/google/authorized`.
   - Facebook app → Facebook Login → Settings → Valid OAuth Redirect URIs +
     `https://www.nriparentservice.com/travel-companions/auth/facebook/authorized`; App domains + `www.nriparentservice.com`.
7. **MilesWeb `.htaccess`** (folder `nriparentservice.com`, shared by `travel.`): replace the
   `# BEGIN domain-switch … # END domain-switch` block with the one below. The bare-name rule does not
   fire yet (the name does not reach MilesWeb until Phase 2); the `travel.` rule now points at `www`.

   ```
   # BEGIN domain-switch: the main site is our app at www; WordPress answers only at travel.
   <IfModule mod_rewrite.c>
   RewriteEngine On
   RewriteCond %{REQUEST_URI} !^/\.well-known/
   RewriteCond %{HTTP_HOST} ^(www\.)?nriparentservice\.com$ [NC]
   RewriteRule ^(.*)$ https://www.nriparentservice.com/$1 [R=301,L]
   RewriteCond %{HTTP_HOST} ^travel\.nriparentservice\.com$ [NC]
   RewriteRule ^((travel-companions|travel-insurances?|sahayak|contact-us|about|admin|api|auth|claim|connections|contact|cs|dashboard|files|help|how-it-works|inbox|match|my|privacy|promotion|reviews|saved-filters|settings|static|switch-view|terms|trips|work-as|live-chat\.js)(/.*)?)$ https://www.nriparentservice.com/$1 [R=301,L]
   </IfModule>
   # END domain-switch
   ```

   `/.well-known/` is excluded so MilesWeb can keep renewing the bare name's certificate.

## Phase 2: the cut-over (quiet hour, 10 minutes)

1. **Railway → Variables:** `APP_PUBLIC_HOST=www.nriparentservice.com`,
   `SITE_URL=https://www.nriparentservice.com/travel-companions`,
   `VISITOR_PING_URL=https://www.nriparentservice.com/travel-companions` → Deploy → wait for Active.
   From now on `www` is home and the bare name redirects to it, wherever it arrives.
2. **Cloudflare → DNS → Records:** row `nriparentservice.com` (CNAME to Railway, orange): Edit → Delete.
   **Add record:** A, Name `@`, IPv4 `103.86.176.249`, **grey** → Save. The bare name now reaches
   MilesWeb, which sends it to `www`.
3. **Check** (private window, and a phone on mobile data):

   | Open | Expect |
   |---|---|
   | `https://www.nriparentservice.com/` | lands on `https://www.nriparentservice.com/home`, padlock OK |
   | `https://nriparentservice.com/blog?x=1` | lands on `https://www.nriparentservice.com/blog?x=1` |
   | `https://www.nriparentservice.com/sitemap.xml` | starts with `https://www.nriparentservice.com/home` |
   | `/travel-companions/` → Sign in, also with Google | works |
   | `https://www.nriparentservice.com/how-to-buy-travel-insurance-for-parents-visiting-the-usa/` | lands on `/blog/…-usa-2` |
   | `https://travel.nriparentservice.com/` | WordPress |
   | `https://travel.nriparentservice.com/auth/login` | lands on `www…/travel-companions/auth/login` |
   | Admin → Inbox → Visitors | a new visit shows a real city |

4. **Railway → Settings → Networking:** after a day, remove `nriparentservice.com`. Then delete the
   `_railway-verify` TXT for the bare name. (This frees a place: `admin.nriparentservice.com` later costs nothing.)
5. **Outside callers → www.** Posts don't follow redirects, so change the start of each address from
   `https://nriparentservice.com` to `https://www.nriparentservice.com`:

   | Where | Address |
   |---|---|
   | Meta app → WhatsApp → Configuration → Callback URL | `https://www.nriparentservice.com/travel-companions/api/whatsapp/lines-webhook` |
   | Meta app → Webhooks → Page → leadgen (if set up) | `https://www.nriparentservice.com/travel-companions/api/crm/meta-webhook` |
   | tawk.to → Administration → Webhooks | `https://www.nriparentservice.com/travel-companions/api/crm/tawk-webhook` |
   | Google Ads → lead form → Webhook URL | `https://www.nriparentservice.com/travel-companions/api/crm/google-leads` |
   | lead forms on other websites | `https://www.nriparentservice.com/travel-companions/api/leads` |
   | the live chat line on other websites | `<script src="https://www.nriparentservice.com/travel-companions/live-chat.js" async></script>` |
   | WhatsApp CRM box `.env.local`, then rebuild (ask) | `NEXT_PUBLIC_PORTAL_ORIGIN=https://www.nriparentservice.com`, `PORTAL_URL=https://www.nriparentservice.com/travel-companions/admin/messaging/sso` |

6. **Search Console:** add the property `https://www.nriparentservice.com/` (or the Domain property);
   Sitemaps: remove WordPress's, add `https://www.nriparentservice.com/sitemap.xml`; URL inspection on
   `/home` → Request indexing. Remove owners you don't know (`sgab97294@gmail.com`, `sayaoranglohh2@gmail.com`).

## Phase 3: DNS to GoDaddy, Cloudflare removed (any time after Phase 2 has settled)

The records must be identical on both sides first, so this is only a change of who answers.

1. **Cloudflare → DNS → Records → Import and Export → Export.** Keep the file: it is the list to copy.
2. **GoDaddy** (sso.godaddy.com → Domain Portfolio → `nriparentservice.com` → **DNS**):
   - If GoDaddy shows a **DNS Records** tab while the name servers are still Cloudflare's, enter every
     record from the table below first, then change the name servers.
   - If it only offers **Nameservers**, change them first (next step) and enter the records
     **immediately**, within minutes: GoDaddy starts with a "parked" record set.
3. **Nameservers → Change Nameservers → "GoDaddy Nameservers" (the default) → Save.** Confirm.
4. **DNS Records.** Delete GoDaddy's defaults (the Parked `A @`, the `CNAME www → @`, anything else it
   made) and add these. TTL 600 seconds or 1 hour; priority on the MX row.

   | Type | Name | Value |
   |---|---|---|
   | A | `@` | `103.86.176.249` |
   | CNAME | `www` | Railway's target for www (`….up.railway.app`) |
   | TXT | `_railway-verify.www` | `railway-verify=…` (the value from Phase 1 step 2) |
   | A | `travel` | `103.86.176.249` |
   | A | `mail` | `103.86.176.249` |
   | A | `mysql` | `103.86.176.249` |
   | A | `ftp` | `103.86.176.249` |
   | CNAME | `imap` | `mail.nriparentservice.com` |
   | CNAME | `pop` | `mail.nriparentservice.com` |
   | CNAME | `smtp` | `mail.nriparentservice.com` |
   | MX | `@` | `mail.nriparentservice.com`, priority `0` |
   | TXT | `@` | `v=spf1 +a +mx include:relay.mailbaby.net ~all` |
   | TXT | `_dmarc` | `v=DMARC1;p=quarantine;sp=none;adkim=r;aspf=r;pct=100;fo=0;rf=afrf;ri=86400` |
   | TXT | `@` | the `google-site-verification=…` text, if Search Console asked for one |

   MilesWeb panel → Websites → `nriparentservice.com` → Manage → **Email Authentication** may list a
   DKIM record; add it too (TXT, the name and value it shows).
5. **Check after an hour**, from a phone on mobile data: `https://www.nriparentservice.com/`,
   `https://nriparentservice.com/` (redirects), `https://travel.nriparentservice.com/`, and send
   an e-mail to and from `info@nriparentservice.com`. `nslookup -type=NS nriparentservice.com 8.8.8.8`
   should answer with `…domaincontrol.com` name servers.
6. **Two days later: Cloudflare →** the site → Overview → bottom → **Remove site from Cloudflare.**
   (Delete the Worker first: Workers & Pages → the Worker → Settings → Delete.)

## Going back

- Before Phase 3: Cloudflare → DNS: `@` back to CNAME `l1fusgzp.up.railway.app` orange; Railway variables
  back to `APP_PUBLIC_HOST=nriparentservice.com` and the bare `SITE_URL`/`VISITOR_PING_URL`.
- After Phase 3: GoDaddy → Nameservers → custom → `dorthy.ns.cloudflare.com`, `johnathan.ns.cloudflare.com`,
  as long as the Cloudflare site still exists. Otherwise fix forward.
