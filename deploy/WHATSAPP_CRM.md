# The WhatsApp CRM inside the admin portal

The WhatsApp CRM (Next.js + Supabase, code in `E:/OS/webscrapping/wacrm`) **stays where it is**: on the
Flow Studio server, at

```
https://studio.preventia360.com/crm/...
```

The portal (`https://nriparentservice.com/travel-companions/...`) shows its screens inside its own
pages (the WhatsApp menu, the conversation on a lead) and signs people in to it. Nothing changes in
Cloudflare. The contract between the two is `wacrm/docs/portal-integration.md`.

Because the portal and the CRM are **two different sites**, the CRM is built so a browser keeps its
sign-in inside the portal's frame: session cookies `SameSite=None; Secure; Partitioned`, the portal
allowed to frame it, and the frame reporting its place to the portal's origin. Tested in Chromium,
including with third-party cookies blocked. A browser that still refuses (some Safari settings) gets a
page with "Allow and continue" and "Open WhatsApp in a new tab" instead of a sign-in loop.

## 1. The CRM on the Flow Studio server

1. **Ship the updated code** to `~/wacrm` the usual way (tar without `node_modules/.next/.git/.env.local`,
   scp, extract).
2. **Add to `~/wacrm/.env.local`** (everything already there stays, including
   `NEXT_PUBLIC_BASE_PATH=/crm`):

   ```
   NEXT_PUBLIC_PORTAL_MODE=1
   NEXT_PUBLIC_PORTAL_CROSS_SITE=1
   NEXT_PUBLIC_PORTAL_ORIGIN=https://nriparentservice.com
   FRAME_ANCESTORS='self' https://nriparentservice.com https://www.nriparentservice.com
   PORTAL_SECRET=<a new random value, 40+ characters>
   PORTAL_URL=https://nriparentservice.com/travel-companions/admin/messaging/sso
   ```

   Do **not** set `INTERNAL_CRON` here: the crontab already calls the two cron endpoints every minute.
3. **Rebuild:** `cd ~/wacrm && docker compose --env-file .env.local up --build -d`.

## 2. Caddy on the Flow Studio server

The Flow Studio login gate (`forward_auth`) cannot see its own cookie inside the portal's frame (it is
`SameSite=Strict`), so it has to let through what the CRM authenticates itself. In the
`studio.preventia360.com` block, extend the public matcher and add one for requests that already carry a
CRM sign-in (the CRM checks those sessions itself); keep the gate for everything else under `/crm`:

```
@crm_public {
    path /crm/api/whatsapp/webhook* /crm/api/v1/* /crm/api/automations/cron /crm/api/flows/cron /crm/api/portal/* /crm/portal-blocked* /crm/_next/*
}
@crm_signed_in {
    path /crm/*
    header_regexp crm_cookie Cookie sb-[A-Za-z0-9]+-auth-token
}
handle @crm_public {
    reverse_proxy 127.0.0.1:3001
}
handle @crm_signed_in {
    reverse_proxy 127.0.0.1:3001
}
# ...then the existing /crm block with forward_auth, unchanged
```

(Adjust to the matcher names already in `/etc/caddy/Caddyfile`.) Make sure nothing in the Caddyfile adds
`X-Frame-Options` to `/crm` responses. Then `sudo systemctl reload caddy`.

## 3. The portal (Railway variables)

| Name | Value |
|---|---|
| `WACRM_URL` | `https://studio.preventia360.com/crm` (unchanged) |
| `WACRM_PORTAL_SECRET` | the same value as `PORTAL_SECRET` above |
| `WACRM_API_KEY`, `WACRM_WEBHOOK_SECRET` | unchanged |

Deploying the portal runs `flask db upgrade`, which adds the workspace tables (q1ws001). The first time an
admin opens **Workspace** the first workspace is made from today's admins and CS agents (or run
`flask workspace-setup`).

## 4. Supabase

**Database migration 043** (automation schedules, round robin, scheduled broadcasts) must be applied to the
hosted Supabase project, the same way as the earlier ones (`npx supabase db push` from the wacrm folder,
linked to the project, or paste `supabase/migrations/043_automation_scheduling.sql` into the SQL editor).
It only adds columns and indexes. Nothing else changes in Supabase, and the Meta callback URL stays
`https://studio.preventia360.com/crm/api/whatsapp/webhook`.

## Updating an installation that is already switched on

The "one process" release (templates from the steps, the lead beside the inbox, replies and
reassignments flowing back) changes both sides. **Ship the CRM first, then the portal:** the portal
registers two webhook events (`message.sent`, `conversation.assigned`) that an older CRM refuses, and
uses four new `/api/portal/*` endpoints.

1. CRM: ship the code and rebuild as in section 1. No new variables and no new Supabase migration.
2. Portal: deploy as usual (no new variables, no new portal migration).
3. Do steps 3 to 5 of "Switch on" below.

## 5. Switch on

1. Open Admin -> Workspace -> WhatsApp CRM -> **Link this workspace**. Everyone whose role has WhatsApp
   pages is added to the CRM; anyone already in the CRM but not in the workspace is listed there for you
   to add or remove (nothing is removed automatically).
2. Open WhatsApp -> Inbox in the portal and send one test message.
3. **Sales CRM -> Set-up -> Connect -> "Connect replies"** once more. The portal now also hears about
   messages agents send from the WhatsApp inbox (they count in the numbers and tick the due follow-up)
   and about reassignments there (the lead's owner follows), and those two events are added when the
   webhook is registered.
4. **Set-up -> WhatsApp templates -> "Put them in WhatsApp as drafts".** Then in WhatsApp -> Templates,
   check each draft and press Submit; Meta approves in minutes to a day. The list is also in
   `deploy/whatsapp-templates.csv`. Once a step's template is approved, that step sends through it --
   by one click, or by itself if the step is set to "Send by itself".
5. **Set-up -> Ready answers -> "Copy to WhatsApp quick replies"**, so agents pick them in the inbox.

## If a second copy was deployed on Railway

Only one copy of the CRM may run against the Supabase project: two would both run the automation timers
and the scheduled broadcasts. If a WhatsApp CRM service was created on Railway, remove it (or scale it
to zero), and if the Cloudflare Worker was deployed with a `WHATSAPP_ORIGIN` route, redeploy the version
in `deploy/cloudflare-worker.js`, which has none.
