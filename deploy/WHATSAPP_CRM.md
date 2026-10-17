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
| `WACRM_API_KEY` | unchanged |
| `WACRM_WEBHOOK_SECRET` | optional: "Connect replies" keeps its own secret and checks it first; a reply signed with this one is still accepted |

Deploying the portal runs `flask db upgrade`, which adds the workspace tables (q1ws001) and the WhatsApp
sync columns on the CRM's people (r1crm003, r2crm004, s1crm005). `s5crm009` adds products, stage meaning and
any-date follow-ups: no WhatsApp tag changes, and three sources now show the pipeline their leads already went to. The first time an
admin opens **Workspace** the first workspace is made from today's admins and CS agents (or run
`flask workspace-setup`).

## 4. Supabase

**Database migration 043** (automation schedules, round robin, scheduled broadcasts) must be applied to the
hosted Supabase project, the same way as the earlier ones (`npx supabase db push` from the wacrm folder,
linked to the project, or paste `supabase/migrations/043_automation_scheduling.sql` into the SQL editor).
It only adds columns and indexes. Nothing else changes in Supabase, and the Meta callback URL stays
`https://studio.preventia360.com/crm/api/whatsapp/webhook`.

## Release 2 (one app): updating production

0. **Before deploying anything, check the switch on production is Not yet.** Set-up → WhatsApp connection →
   "What should the Sales CRM do with WhatsApp?" must say **Not yet**. If it says anything else, set it to Not yet
   now: otherwise the deploy itself starts the Sales-tag rule push and the quick-reply clean-up before you check.
1. **Ship the WhatsApp CRM first** (section 1: ship the code and rebuild). No new settings and no database
   change: no Supabase migration.
2. **Then the portal.** Make sure the rebuilt page bundles are committed (`npm run build` in `frontend/insurance`
   and `frontend/sahayak` writes `app/static/insurance` and `app/static/sahayak`; the Dockerfile does not build
   them), or the /travel-insurance and /sahayak forms will not show the WhatsApp tick. Deploy as usual:
   `flask db upgrade` runs the portal migrations `s1crm005` ... `s7crm011` by itself (`s7crm011` only gives quick
   replies that share a title " (2)", " (3)" ...).
3. **Check the switch still says Not yet** (it should, from step 0).
4. **Set it to "Keep contacts in step".** Nothing is sent by itself. The quick replies and the Sales-tag rule go to
   WhatsApp now.
5. **Pause the reply rules WhatsApp connection lists** under "Before you switch: pause these reply rules" (each has
   Open). Automatic messages → What goes out by itself shows the same list.
6. **Press "Add existing leads and customers to WhatsApp"** once. Every lead with a phone (open, won and lost)
   becomes a WhatsApp contact with its tags, quietly; nobody is messaged. The jobs runner brings them in, 30 a run.
7. **Run the two one-off imports once:** Set-up → Bring in & download → "Bring in WhatsApp notes", and Messaging →
   Quick replies → "Bring in WhatsApp's own text replies".
8. **Switch to "Keep in step and send follow-ups"** once the follow-up templates show Approved (Set-up →
   Pipelines). The page first says how many follow-ups would go now (due in the last 24 hours) and how many older
   ones wait for a person.
9. **Check deals once.** In the Supabase SQL editor run `select count(*) from deals;`. If it is above zero, export
   the rows (Download CSV) and keep the file: the WhatsApp CRM's deals are retired and are not moved.
10. **Nothing new to set in Railway.**

## Updating an installation that is already switched on

The "one process" release (templates from the steps, the lead beside the inbox, replies and
reassignments flowing back) changes both sides. **Ship the CRM first, then the portal:** the portal
registers two webhook events (`message.sent`, `conversation.assigned`) that an older CRM refuses, and
uses four new `/api/portal/*` endpoints.

1. **Before deploying, open Set-up → WhatsApp connection on production. If the switch is not Not yet, set it to Not yet until
   the WhatsApp CRM release is live and the automations it lists are paused.**
2. CRM: ship the code and rebuild as in section 1. No new variables and no new Supabase migration.
3. Portal: deploy as usual (no new variables; `flask db upgrade` adds the portal's own columns, see section 3).
4. Do steps 3 to 5 of "Switch on" below.

The WhatsApp tick ("Send my quote and updates on WhatsApp") on the /travel-insurance and /sahayak pages needs `npm run build` in `frontend/insurance` and `frontend/sahayak` (commit the result); the other forms have it already.

## 5. Switch on

1. Open Admin -> Workspace -> WhatsApp CRM -> **Link this workspace**. Everyone whose role has WhatsApp
   pages is added to the CRM; anyone already in the CRM but not in the workspace is listed there for you
   to add or remove (nothing is removed automatically).
2. Open WhatsApp -> Inbox in the portal and send one test message.
3. **Set-up → WhatsApp connection → "Connect replies"** once more. The portal now also hears about
   messages agents send from the WhatsApp inbox (they count in the numbers and tick the due follow-up)
   and about reassignments there (the lead's owner follows), and those two events are added when the
   webhook is registered.
4. **Set-up → Pipelines → WhatsApp templates → "Put them in WhatsApp as drafts".** Then in WhatsApp templates,
   check each draft and press **Send for approval**; Meta approves in minutes to a day. The list is also in
   `deploy/whatsapp-templates.csv`. Once a step's template is approved, that step sends through it --
   by one click, or by itself if the step is set to "Send by itself".
5. **Quick replies** go to WhatsApp chats by themselves while the switch is not Not yet. Admins can press **Push all to WhatsApp now** on Messaging → Quick replies. Quick replies copied from here are locked in the WhatsApp CRM; button replies are made there.

## Keeping leads in step

Set-up → WhatsApp connection → **What should the Sales CRM do with WhatsApp?**:

| Mode | What happens |
|---|---|
| Not yet | Nothing goes to WhatsApp. Changes made while it is off are not sent later, except an opt-out: the "opted-out" tag goes on their contact once it is switched on. Replies still come in. |
| Keep contacts in step | Every lead with a phone becomes a WhatsApp CRM contact tagged with its product, its stage ("TI: Prospect") and its source's tags; name and e-mail follow edits here. When the owner changes here, the chat goes to them too. Agents send from the lead page's message box or the WhatsApp chat. |
| Keep in step and send follow-ups | The same, and the follow-up steps marked *automatic* go out from here by themselves. |

Changes go a few seconds after saving, in the background, so nobody waits for the WhatsApp CRM. If it is
down, nothing is lost: the person stays marked and the jobs runner tries again, 30 people a run, an hour
later. A refusal somebody has to sort out (a number WhatsApp will not take, two WhatsApp contacts that could
be the number, an owner who is not in the WhatsApp team yet) is kept as that person's problem and tried
again with the next change to them, not every hour. New enquiries, stage moves, replies and the backfill never create a chat and never send
anything. An owner change made here gives the chat to the new owner. When somebody already here writes from
a chat we had not seen, the chat goes to their lead's owner too, but only if nobody in the WhatsApp CRM has it.

Leads that were already here (imports, the site's past enquiries) are not sent when they come in. To bring
in every lead with a phone (open, won and lost), press **Set-up → WhatsApp connection → Add existing leads and customers to WhatsApp** once (or run
`flask crm-wa-backfill`): contacts and tags only, nothing is sent, and the jobs runner works through them a
few at a time. This, and the re-tagging after a source's tags change, is quiet: the portal asks the WhatsApp
CRM not to start its "tag added" automations. A WhatsApp CRM older than this release ignores that and starts
them, so pause those automations first. Tags a source no longer adds stay the portal's (up to 200 are
remembered) and are taken off people's contacts; do not reuse such a tag by hand in the WhatsApp CRM.

**Before switching it on (or running the backfill):**

1. Ship the WhatsApp CRM's strict number matching and `/api/portal/conversation/ensure` first. On an older
   CRM the owner push fails and is retried every hour, and a contact matched on a different number is
   refused rather than tagged.
2. Pause every WhatsApp CRM automation that sends a message when a tag is added. Writing the stage tags
   starts those automations, and the backfill writes tags for every open lead.
3. Also pause WhatsApp CRM automations that send a message when a conversation is assigned: handing a chat
   to its owner starts them.

## Replies, opt-outs and missed messages

- **The webhook only writes here** and never calls the WhatsApp CRM back. An event it cannot store is
  logged and answered "ok: false", never an error, so the WhatsApp CRM does not switch it off.
- **Two open enquiries, one chat:** a reply goes to the one we last wrote to on WhatsApp. A message sent
  from WhatsApp goes to the one whose open step uses that template (and ticks that step). Otherwise the
  newest.
- **All their leads closed:** the message is logged on the latest and its owner gets a bell. If it closed
  over 30 days ago, a new lead from the WhatsApp source is made instead. A closed lead is never reopened.
- **Opt-out:** a message that is only STOP, UNSUBSCRIBE, STOP MESSAGES, STOP PROMOTIONS, STOP ALL or DON'T
  MESSAGE (any case, punctuation ignored), or Meta's error 131050. They get a note on their lead, the
  "opted-out" tag on their WhatsApp contact (broadcasts, automations and the AI reply leave them out), and
  automatic steps stop. There is no screen to undo it yet.
- **Failed deliveries** show Meta's reason in the bell (131047: over 24 hours; 131049: US numbers, or
  Meta's marketing limit; otherwise Meta's own words).
- **The catch-up:** each jobs run asks the WhatsApp CRM which chats changed (up to 200) and records the
  last message they sent if it is missing here, at the time it was written. The first run looks back one
  day, and the last two minutes are left for the webhook. Only the last message of a chat is fetched; read
  the rest in the chat. It needs "Connect replies" done on this site and `WACRM_PORTAL_SECRET`.
- **Webhook health:** hourly, the jobs runner checks our webhook in the WhatsApp CRM. If it was switched
  off it is switched back on (unless the mode is Not yet), and the admins get one bell, at most once a day.
- Both keep their state in their own settings rows: `crm_wa_catchup` and `crm_wa_health`.

## Sending from here

Things that go by themselves need "Keep in step and send follow-ups". A person pressing Send in the lead page's message box works in "Keep contacts in step" too. Not yet sends nothing.

- **Each step is taken before it goes.** A second click, the other worker or an overlapping jobs run finds
  it taken and sends nothing. If WhatsApp does not answer, or fails after Meta has it, the step may have
  gone: it stays "sending" and is never sent again by itself. After 15 minutes it waits for a person to
  check the chat (WhatsApp connection → Needs attention lists them, with It went: mark done / It didn't: back to open; the jobs report counts them as `crm_sends_to_check`). A step
  WhatsApp refused is open again with the reason.
- **The automatic run stops taking steps after one minute.** The rest go on the next run.
- **No backlog:** an automatic step overdue by more than a day is not sent. It goes back on the owner's
  list as "Was due ...; check before sending". Switching sending on does not send old steps.
- **"Automatic first messages need their OK"** (on by default). An automatic template to somebody who did
  not tick WhatsApp on a form and never wrote to us waits for a click: "Needs a click: they have not
  agreed to WhatsApp messages yet". A click still sends it.
- **Opted out:** nothing goes from here, not even the wa.me link, until they write again. Then an agent
  can reply inside the 24 hours. Templates and automatic steps never go to them.
- **US numbers** (+1, except Canadian area codes): no marketing templates, because Meta does not deliver
  them. Utility templates and replies inside the 24 hours still go.
- **Free text only inside the 24 hours.** Just before it goes, the WhatsApp CRM is asked when they last
  wrote (at most once a minute per number). Only their real WhatsApp messages count: a typed-in reply, a
  note or a form does not. "Make them a lead" in the inbox logs a note, not a message from them.
- **A template with other blanks** than the step's words is not used. The step goes as a link, with the
  reason, until they match.
- **The lead page's message box** ensures the chat first, checks it is their number, sends free text only
  while the chat is open by the WhatsApp CRM's clock, otherwise approved templates only; never to somebody
  who opted out (templates), never a marketing template to a US number. A follow-up it carries out is
  taken first and ticked only once WhatsApp took it.

## Known limits of this release

- **Locks follow the switch.** Sales tags and portal quick replies are locked in the WhatsApp CRM once the portal has pushed its rules (the switch is not Not yet).
- **What goes out by itself** says how many chatbots are on and whether AI replies answer by themselves once the WhatsApp CRM of this release is shipped; with an older one those two lines say "Open it to see if it is on".
- **Hand-overs by reply rules, the chatbot or the AI.** When the WhatsApp CRM says a chat was handed over by a reply
  rule, the chatbot or the AI (origin `automation`, `flow` or `ai`), the lead keeps its owner and the chat goes back
  to them. A WhatsApp CRM that still reports those as `crm` is read as a person in the inbox: the lead moves to
  whoever got the chat, and they are told it is theirs. On such a release, switch off round robin in reply rules
  and the chatbot's hand-off to a person.

## If a second copy was deployed on Railway

Only one copy of the CRM may run against the Supabase project: two would both run the automation timers
and the scheduled broadcasts. If a WhatsApp CRM service was created on Railway, remove it (or scale it
to zero), and if the Cloudflare Worker was deployed with a `WHATSAPP_ORIGIN` route, redeploy the version
in `deploy/cloudflare-worker.js`, which has none.
