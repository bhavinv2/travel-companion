"""Set-up > Integrations: everything the portal is connected to, one card each, the way tawk.to shows its own
(2026-10-26). A card says what the integration does, whether it works, and opens three tabs: Overview, Installation
(the addresses and the snippet to paste somewhere else) and Settings (what is set, and where its settings live).

    GROUPS            the card groups, in order
    cards(ctx)        every card, in order: [{key, name, group, icon, color, says, state, chip, last, ...}]
    card(key, ctx)    one card with everything its tabs need, or None
    intake_origins()  the other websites whose forms may send leads (the server's list plus the saved one)

`ctx` gives the links: Ctx(link=crm_url, user=current_user). Nothing here calls another service, so the page is
quick: it reads our own tables, the settings, and whether the server's keys are SET -- never their values. The
live WhatsApp checks stay on the WhatsApp page; each integration's own settings stay where they already live
(one function, one home) and the card links there.
"""
import os
from collections import namedtuple
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from flask import current_app, url_for

from app.services import settings

Ctx = namedtuple('Ctx', 'link user')

GROUPS = (('conversations', 'Conversations'), ('leads', 'Lead capture'), ('money', 'Payments'), ('ai', 'AI'),
          ('partners', 'Partners'), ('site', 'Website & sign-in'))
STATE_ORDER = {'warn': 0, 'on': 1, 'info': 2, 'off': 3}
ORIGINS_SETTING = 'crm.intake_origins'
LOCAL = ('localhost', '127.0.0.1')


# ============================================================================================ helpers

def _env(name):
    return bool((os.environ.get(name) or '').strip())


def _cfg(name):
    return bool(str(current_app.config.get(name) or '').strip())


def _addr(endpoint, **kw):
    """The public address of one of our endpoints (the live site's, behind a proxy too)."""
    from app.services import urls
    try:
        out = urls.public_absolute(endpoint)
    except Exception:          # noqa: BLE001 -- no public host configured (a laptop): this request's own
        out = url_for(endpoint, _external=True)
    if kw:
        out += ('&' if '?' in out else '?') + '&'.join('%s=%s' % kv for kv in kw.items())
    return out


def _page(ctx, key):
    """The address of one of our screens, when this person may open it."""
    from app.services import access
    if key not in access.PAGES or not access.can(ctx.user, key):
        return None
    return access.page_url(access.PAGES[key])


def _line(ok, text):
    return {'ok': ok, 'text': text}


def _envs(*names, cfg=()):
    """[(name, is set)] for the developer: server settings by NAME only."""
    return [(n, _env(n)) for n in names] + [(n, _cfg(n)) for n in cfg]


def _latest_touch(**filters):
    from app.models import CrmTouchpoint
    q = CrmTouchpoint.query.filter_by(direction='in', **{k: v for k, v in filters.items() if k != 'channels'})
    if filters.get('channels'):
        q = CrmTouchpoint.query.filter(CrmTouchpoint.direction == 'in', CrmTouchpoint.channel.in_(filters['channels']))
    row = q.order_by(CrmTouchpoint.created_at.desc()).first()
    return row.created_at if row is not None else None


def _base(key, name, group, icon, color, says):
    return {'key': key, 'name': name, 'group': group, 'icon': icon, 'color': color, 'says': says, 'state': 'off',
            'chip': 'Not set up', 'last': None, 'lines': [], 'overview': [], 'where': [], 'steps': [], 'addresses': [],
            'snippet': None, 'env': [], 'home': None, 'form': None, 'note': None}


# ============================================================================================ website origins

def clean_origin(text):
    """'https://host[:port]' from what an admin typed ('example.com', a whole page address ...), or None."""
    t = (text or '').strip().rstrip('/')
    if not t:
        return None
    if '://' not in t:
        t = 'https://' + t
    try:
        u = urlsplit(t)
    except ValueError:
        return None
    host = (u.hostname or '').lower()
    if not host or '.' not in host and host not in LOCAL or ' ' in host:
        return None
    if u.scheme != 'https' and not (u.scheme == 'http' and host in LOCAL):
        return None
    return '%s://%s%s' % (u.scheme, host, ':%d' % u.port if u.port else '')


def env_origins():
    return [o for o in (clean_origin(x) for x in str(current_app.config.get('CRM_INTAKE_ORIGINS') or '').split(','))
            if o]


def saved_origins():
    v = settings.get_setting(ORIGINS_SETTING) or []
    return [o for o in (clean_origin(x) for x in v) if o] if isinstance(v, list) else []


def intake_origins():
    out = []
    for o in env_origins() + saved_origins():
        if o not in out:
            out.append(o)
    return out


def save_origins(text, actor):
    """Keep the websites listed one per line (or comma). Returns (kept, refused). Commits."""
    kept, refused = [], []
    for raw in str(text or '').replace(',', '\n').splitlines():
        if not raw.strip():
            continue
        o = clean_origin(raw)
        if o is None:
            refused.append(raw.strip()[:80])
        elif o not in kept:
            kept.append(o)
    settings.set_setting(ORIGINS_SETTING, kept[:40], actor)
    return kept[:40], refused


# ============================================================================================ the cards

def _whatsapp(ctx):
    from app.services import crm, crm_connection, wacrm, wacrm_team
    c = _base('whatsapp', 'WhatsApp', 'conversations', 'fa-brands fa-whatsapp', '#25d366',
              'Chats, templates and follow-ups through the WhatsApp CRM.')
    ready = wacrm.enabled()
    mode = crm.wa_mode()
    hook = crm._wa_webhook_saved()
    stuck = crm_connection.needs_attention(limit=20)['count'] if mode != 'off' else 0
    if not ready:
        c.update(state='off', chip='Not set up')
    elif mode == 'off':
        c.update(state='warn', chip='Switched off')
    elif not hook.get('id'):
        c.update(state='warn', chip='Replies not connected')
    elif stuck:
        c.update(state='warn', chip='%d to look at' % stuck)
    else:
        c.update(state='on', chip='Connected')
    c['lines'] = [_line(ready, 'The WhatsApp CRM address and key are set on the server'),
                  _line(bool(hook.get('id')), 'Replies are connected' if hook.get('id') else 'Replies are not connected yet'),
                  _line(wacrm_team.enabled(), 'Team sign-in is set up'),
                  _line(mode != 'off', 'What the Sales CRM does: %s' % crm.WA_MODES.get(mode, mode))]
    c['last'] = _latest_touch(channel='whatsapp')
    c['overview'] = ["Every WhatsApp chat shows on the lead's timeline, with a message box underneath.",
                     'A follow-up step can go by itself as an approved WhatsApp template.',
                     'Quick replies, templates and tags are shared with the WhatsApp CRM, so they exist once.',
                     'Another WhatsApp number -- one connected in tawk.to, say -- can be answered from the portal '
                     'itself: Set-up › Channels › WhatsApp numbers.']
    c['where'] = [(t, u) for t, u in (('WhatsApp chats', _page(ctx, 'wa_inbox')), ('Messages', _page(ctx, 'crm_quick')),
                                      ('WhatsApp numbers', _page(ctx, 'crm_channels')))
                  if u]
    c['steps'] = ['Your developer sets the four server settings below (the WhatsApp CRM gives the address and keys).',
                  'Open the WhatsApp settings and press Connect replies.',
                  'Link this workspace under Team sign-in, so the team can open WhatsApp chats here.',
                  'Choose what the Sales CRM does with WhatsApp: keep contacts in step, then send follow-ups.']
    c['env'] = [('WACRM_URL', bool(wacrm.base_url())), ('WACRM_API_KEY', bool(wacrm.api_key())),
                ('WACRM_PORTAL_SECRET', bool(wacrm_team.secret())), ('WACRM_WEBHOOK_SECRET', bool(wacrm.webhook_secret()))]
    url = _page(ctx, 'crm_connection')
    c['home'] = {'label': 'Open WhatsApp settings', 'url': url, 'says': 'The live checks, the replies link, team '
                 'sign-in and what the Sales CRM does with WhatsApp.'} if url else None
    return c


def _tawk(ctx):
    from app.models import CrmSource
    from app.services import tawk
    c = _base('tawk', 'tawk.to chat', 'conversations', 'fa-solid fa-comment-dots', '#03a84e',
              'The chat bubble on the websites. A chat that leaves a phone or e-mail becomes a lead.')
    on = tawk.enabled()
    src = CrmSource.query.filter_by(key=tawk.SOURCE_KEY).first()
    c['last'] = tawk.last_seen()
    if on:
        c.update(state='on', chip='Connected')
    else:
        c.update(state='off', chip='Not connected', note='Until it is connected, tawk chats are looked at by hand on '
                                                         'the Half-hourly check.')
    from_env = _env(tawk.ENV)
    kept = tawk.saved()
    c['lines'] = [_line(on, ('The key is set on the server' if from_env else
                             'A key is saved%s' % (' by %s' % kept['by'] if kept.get('by') else ''))
                        if on else 'No key yet: the address answers “not found”'),
                  _line(bool(src and src.status == 'live'),
                        'Its leads go to the lead source “Tawk chat”' + ('' if src and src.status == 'live' else
                                                                          ' (set it up under Lead sources)'))]
    c['overview'] = ['A chat where the visitor leaves an e-mail or phone number becomes a lead under “Tawk chat”, '
                     'with the chat on its timeline.',
                     'The same chat is filed once; its whole transcript replaces the first message when the chat ends.',
                     'A ticket left while nobody was online comes in the same way.',
                     'Chats with no way to reach the visitor stay in tawk only.']
    c['where'] = [(t, u) for t, u in (('Leads', _page(ctx, 'crm_board')), ('Lead sources', _page(ctx, 'crm_sources')))
                  if u]
    c['steps'] = ['In tawk.to open Administration › Settings › Webhooks and press Create Webhook.',
                  'Paste the address below as the Endpoint URL.',
                  'Tick the events Chat Start, Chat Transcript Created and New Ticket, then save.',
                  'tawk shows a Secret Key: copy it and paste it on the Settings tab here.',
                  'Start a test chat on the website and type an e-mail address: it shows under Leads.']
    c['addresses'] = [{'id': 'ig-tawk-url', 'label': 'Endpoint URL', 'value': _addr('crm_public.tawk_webhook')}]
    from app.services.crm import _parse_utc
    c['seen'] = [dict(r, at=_parse_utc(r.get('at'))) for r in tawk.seen()]
    c['env'] = _envs(tawk.ENV)
    c['form'] = 'tawk'
    from app.services import crm
    c['saved'] = {'from_env': from_env, 'at': crm._parse_utc(kept.get('at')), 'by': kept.get('by'),
                  'has': bool(kept.get('secret'))}
    return c


def _meta(ctx):
    from app.services import meta
    c = _base('meta', 'Facebook & Instagram', 'conversations', 'fa-brands fa-meta', '#0866ff',
              'Messenger and Instagram messages, comments, and lead-ad forms.')
    have = [bool(meta.app_secret()), bool(meta.page_token()), bool(meta.verify_token())]
    if all(have):
        c.update(state='on', chip='Connected')
    elif any(have):
        c.update(state='warn', chip='Half set up')
    c['last'] = _latest_touch(channels=('facebook', 'instagram'))
    c['lines'] = [_line(have[0] and have[1], 'Messages and comments can come in and be answered'),
                  _line(have[2], 'Meta can check the address (verify token)')]
    c['overview'] = ['Messages and comments on the Facebook Page and the Instagram account land on the lead, or '
                     'start one.',
                     'You answer Messenger and Instagram from the lead page within 24 hours of their last message.',
                     'Each lead-ad form shows up under Lead sources as its own source, needing set-up, until you '
                     'choose its pipeline and who gets its leads. Until then nobody is messaged.']
    c['where'] = [(t, u) for t, u in (('Lead sources', _page(ctx, 'crm_sources')),) if u]
    c['steps'] = ['In the Meta app add the products Messenger, Instagram and Webhooks.',
                  'Ask for the permissions pages_messaging, instagram_manage_messages, pages_read_engagement, '
                  'instagram_manage_comments, leads_retrieval and pages_manage_metadata.',
                  'Under Webhooks choose Page: paste the address below, and as verify token the value your developer '
                  'set in META_VERIFY_TOKEN. Subscribe to messages, feed and leadgen.',
                  'Under Webhooks choose Instagram too and subscribe to messages and comments.',
                  'Your developer sets the three server settings below; the Page token is the same for messages and '
                  'lead forms.']
    c['addresses'] = [{'id': 'ig-meta-url', 'label': 'Callback URL', 'value': _addr('crm_public.meta_webhook')}]
    c['env'] = _envs('META_APP_SECRET', 'META_PAGE_TOKEN', 'META_VERIFY_TOKEN')
    return c


def _email(ctx):
    from app.services import crm_email, mailer
    c = _base('email', 'E-mail', 'conversations', 'fa-solid fa-envelope', '#6366f1',
              'Send e-mails from the lead page and file customers\' replies on the timeline.')
    out, inbound = crm_email.can_send(), bool(crm_email.inbound_token())
    if out and inbound:
        c.update(state='on', chip='Sending and receiving')
    elif out or inbound:
        c.update(state='warn', chip='Sending only' if out else 'Receiving only')
    else:
        c.update(note="Until it is set up, the E-mail button opens each person's own mail app.")
    provider = mailer.transport_for(False) if out else None
    c['lines'] = [_line(out, 'Sending through %s' % ('SendGrid' if provider == 'sendgrid' else 'the mail server')
                        if out else 'Sending is not set up'),
                  _line(inbound, 'Replies are filed on the lead' if inbound else 'Replies are not filed yet')]
    c['last'] = _latest_touch(channel='email')
    c['overview'] = ['Write an e-mail from the lead page; it is kept on the timeline.',
                     'A customer\'s reply finds their lead by the address and lands on the timeline.',
                     'The sender name and reply address are set once for everybody.']
    c['steps'] = ['Sending: your developer sets MAIL_PROVIDER=sendgrid and SENDGRID_API_KEY (or a mail server).',
                  'Receiving: in SendGrid open Settings › Inbound Parse and add the domain you receive on (its MX '
                  'record points to mx.sendgrid.net).',
                  'Paste the address below as the destination URL, putting the value of CRM_INBOUND_EMAIL_TOKEN '
                  'after token=.',
                  'Send yourself a test reply: it shows on the lead.']
    c['addresses'] = [{'id': 'ig-mail-url', 'label': 'Destination URL',
                  'value': _addr('crm_public.email_inbound') + '?token=<CRM_INBOUND_EMAIL_TOKEN>'}]
    c['env'] = _envs('CRM_INBOUND_EMAIL_TOKEN', cfg=('MAIL_PROVIDER', 'SENDGRID_API_KEY'))
    url = _page(ctx, 'crm_quick')
    c['home'] = {'label': 'Open the sender settings', 'url': url + '#email-sender',
                 'says': 'The name customers see and where their replies go.'} if url else None
    return c


def _website(ctx):
    from app.models import CrmSource, CrmTouchpoint
    c = _base('website', 'Website lead forms', 'leads', 'fa-solid fa-globe', '#0ea5e9',
              'Any form on our websites, WordPress ones too, sends its enquiries straight into Leads.')
    since = datetime.utcnow() - timedelta(days=30)
    n30 = CrmTouchpoint.query.filter(CrmTouchpoint.channel == 'form', CrmTouchpoint.direction == 'in',
                                     CrmTouchpoint.created_at >= since).count()
    unrouted = CrmSource.query.filter_by(status='unrouted').count()
    sites = intake_origins()
    if unrouted:
        c.update(state='warn', chip='%d new form%s to set up' % (unrouted, '' if unrouted == 1 else 's'))
    else:
        c.update(state='on', chip='On')
    c['last'] = _latest_touch(channel='form')
    c['lines'] = [_line(True, '%d enquir%s from forms in the last 30 days' % (n30, 'y' if n30 == 1 else 'ies')),
                  _line(not unrouted, 'Every form has its pipeline' if not unrouted else
                        '%d form(s) wait for their pipeline under Lead sources' % unrouted),
                  _line(bool(sites) or None, '%d other website%s may send leads' % (len(sites), '' if len(sites) == 1 else 's')
                        if sites else 'Only pages on this site send leads so far')]
    c['overview'] = ['Two lines turn any form into a lead form: give it a form ID and add our script.',
                     'Name, phone, e-mail and message are read by name; every other field is kept with the lead.',
                     'The campaign the visitor came from (utm, gclid, fbclid) goes with it.',
                     'A form ID nobody has set up still works: its leads wait under Lead sources until someone '
                     'chooses their pipeline.']
    c['where'] = [(t, u) for t, u in (('Lead sources', _page(ctx, 'crm_sources')), ('Leads', _page(ctx, 'crm_board')))
                  if u]
    c['steps'] = ['Pick the form below, or make one: Lead sources › Edit › its form ID.',
                  'On a page of this site: paste the snippet where the form should be.',
                  'On another website (a WordPress site): add the website on the Settings tab first, then paste the '
                  'snippet in a Custom HTML block.',
                  'Send a test enquiry: it shows under Leads within a minute.']
    c['addresses'] = [{'id': 'ig-intake-url', 'label': 'Address the forms send to', 'value': _addr('crm_public.intake')}]
    c['env'] = _envs(cfg=('CRM_INTAKE_ORIGINS',))
    c['form'] = 'origins'
    c['sites'] = {'env': env_origins(), 'saved': saved_origins()}
    c['sources'] = [(s.key, s.name) for s in CrmSource.query.filter(CrmSource.status != 'paused')
                    .order_by(CrmSource.name).all()]
    c['script'] = url_for('static', filename='js/lead-capture.js', _external=True)
    url = _page(ctx, 'crm_sources')
    c['home'] = {'label': 'Open Lead sources', 'url': url,
                 'says': "Each form's pipeline, who gets its leads, and how many came."} if url else None
    return c


def _google(ctx):
    from sqlalchemy import func
    from app import db
    from app.models import CrmSource
    from app.services import crm_lead_ads
    c = _base('google', 'Google Ads lead forms', 'leads', 'fa-brands fa-google', '#4285f4',
              'Leads from Google Ads lead forms arrive by themselves.')
    on = bool(crm_lead_ads.google_key())
    if on:
        c.update(state='on', chip='Ready')
    c['last'] = db.session.query(func.max(CrmSource.last_lead_at)).filter(
        CrmSource.key.like(crm_lead_ads.GOOGLE_PREFIX + '%')).scalar()
    c['lines'] = [_line(on, 'The shared key is set on the server' if on else
                        'No shared key yet: the address answers “not found”')]
    c['overview'] = ['Each lead form becomes its own source, “Google Ads form <number>”, needing set-up until you '
                     'choose its pipeline.',
                     '“Send test data” in Google Ads is accepted and not saved.']
    c['where'] = [(t, u) for t, u in (('Lead sources', _page(ctx, 'crm_sources')),) if u]
    c['steps'] = ['Your developer sets a secret key on the server: CRM_GOOGLE_LEADS_KEY.',
                  "In Google Ads, on the lead form's Lead delivery step, paste the address below and the same key.",
                  'Press “Send test data”. Real leads then show up under Lead sources.']
    c['addresses'] = [{'id': 'ig-google-url', 'label': 'Webhook URL', 'value': _addr('crm_public.google_leads')}]
    c['env'] = _envs('CRM_GOOGLE_LEADS_KEY')
    return c


def _payments(ctx):
    from app.models import ActivityEvent
    from app.routes.crm_quotes import webhook_secret
    c = _base('payments', 'Payment links', 'money', 'fa-solid fa-credit-card', '#635bff',
              'The payment provider tells us when a link is paid or fails; the lead moves by itself.')
    on = bool(webhook_secret())
    if on:
        c.update(state='on', chip='Connected')
    else:
        c.update(note='Until it is connected, mark a payment as paid by hand on the lead.')
    row = ActivityEvent.query.filter_by(event='crm_payment_webhook').order_by(ActivityEvent.created_at.desc()).first()
    c['last'] = row.created_at if row is not None else None
    c['lines'] = [_line(on, 'The signing secret is set on the server' if on else
                        'No signing secret yet: the address answers “not found”')]
    c['overview'] = ['A payment link made on the lead carries a reference.',
                     'When the provider says it is paid, the payment is marked paid and the lead moves on; a failed '
                     'one is marked failed.',
                     'The same message twice changes nothing.']
    c['steps'] = ['Your developer sets CRM_PAYMENT_WEBHOOK_SECRET on the server and gives it to the provider.',
                  'The provider sends JSON {reference, status, amount, currency} to the address below, with the header '
                  'X-Signature: the hex HMAC-SHA256 of the body with that secret.',
                  'Pay a small test link: it shows as paid on the lead.']
    c['addresses'] = [{'id': 'ig-pay-url', 'label': 'Webhook URL', 'value': _addr('crm_public.payment_webhook')}]
    c['env'] = _envs('CRM_PAYMENT_WEBHOOK_SECRET')
    return c


def _ai(ctx):
    from app.services import crm_ai
    c = _base('ai', 'AI on the lead page', 'ai', 'fa-solid fa-wand-magic-sparkles', '#d97757',
              'Summarise a lead and suggest the next message, with Anthropic Claude.')
    key, on = crm_ai.has_key(), crm_ai.switched_on()
    if key and on:
        c.update(state='on', chip='On')
    elif key:
        c.update(state='off', chip='Switched off')
    c['lines'] = [_line(key, 'The Anthropic key is set on the server'), _line(on, 'Switched on under Automation')]
    c['overview'] = ['“Summarise” on the lead page writes a short summary and a suggested next message.',
                     'The suggestion only fills the message box: the agent reads it, edits it and presses Send.',
                     crm_ai.NOTE]
    c['steps'] = ['Your developer sets ANTHROPIC_API_KEY on the server.',
                  'Switch on “AI on the lead page” under Automation.']
    c['env'] = _envs(crm_ai.ENV_KEY)
    url = _page(ctx, 'crm_auto')
    c['home'] = {'label': 'Open Automation', 'url': url, 'says': 'The switch for AI on the lead page.'} if url else None
    return c


def _preventia(ctx):
    from app.services import preventia
    c = _base('preventia', 'Preventia360 (Sahayak)', 'partners', 'fa-solid fa-house-medical', '#0f766e',
              'The Sahayak catalogue and prices, and a copy of each booking for their review.')
    on = preventia.enabled()
    if on:
        c.update(state='on', chip='Connected')
    else:
        c.update(state='info', chip='Using our own list', note='Without it the Sahayak page shows our own catalogue.')
    c['lines'] = [_line(on, 'Their address and key are set on the server')]
    c['overview'] = ['The Sahayak page shows their categories and prices (refreshed every 5 minutes).',
                     'A booking or an application is copied to their review queue; we keep the original.']
    c['steps'] = ['Your developer sets PREVENTIA_API_URL and PREVENTIA_API_KEY on the server.']
    c['env'] = _envs('PREVENTIA_API_URL', 'PREVENTIA_API_KEY')
    url = _page(ctx, 'sahayak_services')
    c['home'] = {'label': 'Open Services & prices', 'url': url, 'says': 'Our own Sahayak catalogue.'} if url else None
    return c


def _analytics(ctx):
    from app.services import ads, analytics
    c = _base('analytics', 'Google Analytics & Ads', 'site', 'fa-solid fa-chart-simple', '#f9ab00',
              'Visits, campaigns and ad conversions on the public pages.')
    ids = [('Analytics', analytics.ga4_id()), ('Tag Manager', analytics.gtm_id()), ('Ads (whole site)', analytics.ads2_id()),
           ('Ads (insurance page)', ads.account_id())]
    if any(v for _, v in ids):
        c.update(state='on', chip='On')
    c['lines'] = [_line(bool(v), '%s: %s' % (n, v or 'off')) for n, v in ids]
    c['overview'] = ['The tags load on the public pages of the live site only, never on a laptop or in the tests.',
                     'The travel-insurance page reports four ad conversions: a quote, the popup lead, the expert form '
                     'and opening WhatsApp.']
    c['steps'] = ['These IDs are public. To change one, your developer sets GA4_ID, GTM_ID, GOOGLE_ADS2_ID or '
                  'GOOGLE_ADS_ID on the server; an empty value switches it off.']
    # reading the numbers back, for the Promotion dashboard (services/ga4): its settings live with the designer
    from app.services import ga4
    got = ga4.status()
    c['lines'].append(_line(got['connected'], 'Promotion dashboard reads it back: %s' % (
        'property %s' % got['property_id'] if got['connected'] else 'not connected yet')))
    c['overview'].append('The Promotion dashboard shows the same numbers -- visitors, channels, countries, who is on '
                         'the site right now -- once a read-only service account is connected.')
    if _page(ctx, 'mkt_design'):
        c['home'] = {'label': 'Connect it to the Promotion dashboard', 'url': url_for('marketing.google'),
                     'says': 'The property id and a read-only service-account key.'}
    return c


def _signin(ctx):
    c = _base('signin', 'Sign in with Google or Facebook', 'site', 'fa-solid fa-right-to-bracket', '#64748b',
              'Visitors sign in to the site with Google or Facebook.')
    g, f = _cfg('GOOGLE_OAUTH_CLIENT_ID'), _cfg('FACEBOOK_OAUTH_CLIENT_ID')
    if g and f:
        c.update(state='on', chip='Google and Facebook')
    elif g or f:
        c.update(state='on', chip='Google' if g else 'Facebook')
    c['lines'] = [_line(g, 'Google'), _line(f, 'Facebook')]
    c['overview'] = ['The sign-in page shows a button for each one that is set up.',
                     'Staff sign in with a password: these buttons are for the public site.']
    c['steps'] = ['Register these return addresses with Google and Facebook, then your developer sets the client '
                  'ID and secret of each.']
    c['addresses'] = [{'id': 'ig-google-back', 'label': 'Google return address', 'value': _addr('auth.google_callback')},
                 {'id': 'ig-fb-back', 'label': 'Facebook return address', 'value': _addr('auth.facebook_callback')}]
    c['env'] = _envs(cfg=('GOOGLE_OAUTH_CLIENT_ID', 'GOOGLE_OAUTH_CLIENT_SECRET', 'FACEBOOK_OAUTH_CLIENT_ID',
                          'FACEBOOK_OAUTH_CLIENT_SECRET'))
    return c


def _storage(ctx):
    c = _base('storage', 'File storage', 'site', 'fa-solid fa-cloud', '#0284c7',
              'Where uploaded pictures and documents are kept.')
    s3 = current_app.config.get('STORAGE_BACKEND') == 's3'
    c.update(state='on' if s3 else 'info', chip='Cloud bucket' if s3 else 'On this server')
    c['lines'] = [_line(True, 'A cloud bucket (S3-compatible)' if s3 else 'On this server, in its upload folders')]
    c['overview'] = ['Pictures on posts and the blog, and private documents on leads, are kept here.',
                     'Private documents are never public: each download is checked first.']
    c['steps'] = ['To move to a bucket (AWS S3, Cloudflare R2, Backblaze B2), your developer sets STORAGE_BACKEND=s3 '
                  'and the S3_ settings.']
    c['env'] = _envs(cfg=('STORAGE_BACKEND', 'S3_BUCKET'))
    return c


BUILDERS = (_whatsapp, _tawk, _meta, _email, _website, _google, _payments, _ai, _preventia, _analytics, _signin,
            _storage)
KEYS = ('whatsapp', 'tawk', 'meta', 'email', 'website', 'google', 'payments', 'ai', 'preventia', 'analytics',
        'signin', 'storage')
BY_KEY = dict(zip(KEYS, BUILDERS))


def cards(ctx):
    return [b(ctx) for b in BUILDERS]


def card(key, ctx):
    b = BY_KEY.get(key)
    return b(ctx) if b else None


def summary(rows):
    """{'on', 'warn', 'off'}: how many cards are working, need a look, or are not set up."""
    out = {'on': 0, 'warn': 0, 'off': 0}
    for r in rows:
        out['on' if r['state'] in ('on', 'info') else r['state']] += 1
    return out
