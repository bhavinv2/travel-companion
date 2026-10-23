"""Where leads come from: the one list of lead sources, and everything that reads it.

The list is the business's own (2026-10-23): these are the only ways a lead reaches us, in the groups the screens
show them in. Each item is a CrmSource row (its `key`); the website forms, the WhatsApp feed, the imports and
"Add a lead" all file a lead under one of them.

    GROUPS        the groups, in order, each with its items
    item(key)     one item: its group, its full name and its short one
    group_of(src) which group a source row belongs to (a lead-ad form joins Meta or Other by its key)
    canonical()   the key a lead is filed under: an old key (instagram, ti-support, sales-sheet ...) is the item
                  it became; "call" and "reference" are split by the person's number (+1: the USA)
    tidy()        once per workspace: the items exist with their names, and the old sources' leads, campaigns,
                  rules and inbox rows move onto the items (crm.ensure_defaults calls it)
    origin(lead)  how it came to us: by itself (organic), added by staff (manual), or imported
    came_from()   everything a screen says about where a lead came from, when and by whom (India time)
"""
from collections import namedtuple
from datetime import timedelta

from app import db

Item = namedtuple('Item', 'key name short kind product pipeline sub')
IST = timedelta(hours=5, minutes=30)


def _i(key, name, short, kind, product='GEN', pipeline='general', sub=None):
    return Item(key, name, short, kind, product, pipeline, sub)


# (group key, group name, icon, items). `name` is the source's name everywhere (lists, filters, reports);
# `short` is how it reads inside its group.
GROUPS = (
    ('calls', 'Calls & chats', 'fa-phone', (
        _i('wa-india', 'WhatsApp India · chat', 'WhatsApp India · chat', 'chat'),
        _i('wa-india-call', 'WhatsApp India · call', 'WhatsApp India · call', 'call'),
        _i('company-call', 'Company number · call', 'Company number · call', 'call'),
        _i('wa-usa', 'USA number · chat', 'USA number · chat', 'chat'),
        _i('usa-call', 'USA number · call', 'USA number · call', 'call'),
        _i('canada-chat', 'Canada number · chat', 'Canada number · chat', 'chat'),
        _i('canada-call', 'Canada number · call', 'Canada number · call', 'call'),
        _i('tawk', 'Tawk chat', 'Tawk chat', 'chat'),
    )),
    ('social', 'Social media', 'fa-hashtag', (
        _i('meta', 'Meta · Instagram & Facebook', 'Meta · Instagram & Facebook', 'chat'),
        _i('telegram', 'Telegram', 'Telegram', 'chat'),
    )),
    ('reference', 'Personal references', 'fa-handshake', (
        _i('ref-usa', 'Reference · via USA', 'Through someone in the USA', 'manual'),
        _i('ref-india', 'Reference · via India', 'Through someone in India', 'manual'),
    )),
    ('staff', 'Added by staff', 'fa-user-pen', (
        _i('tc-cs-post', 'Companion post · added by staff', 'Companion posts', 'manual', 'TC', 'tc-companion'),
    )),
    ('other', 'Other', 'fa-ellipsis', (
        _i('other', 'Other', 'Other', 'manual'),
    )),
    ('imports', 'Imports', 'fa-file-import', (
        _i('import-ti', 'Import · Travel insurance', 'Travel insurance', 'import', 'TI', 'ti-standard'),
        _i('import-sh', 'Import · Sahayak', 'Sahayak', 'import', 'SH', 'sahayak-visit'),
        _i('tc-import', 'Import · Travel companion', 'Travel companion', 'import', 'TC', 'tc-companion'),
        _i('import-other', 'Import · Other', 'Other', 'import'),
    )),
    ('web', 'Websites', 'fa-globe', (
        _i('contact-general', 'Contact us · General enquiry', 'General enquiry', 'form', sub='Contact us'),
        _i('contact-insurance', 'Contact us · Travel insurance', 'Travel insurance', 'form', 'TI', 'ti-standard',
           'Contact us'),
        _i('contact-companion', 'Contact us · Travel companion', 'Travel companion', 'form', 'TC', 'tc-companion',
           'Contact us'),
        _i('contact-sahayak', 'Contact us · Sahayak', 'Sahayak', 'form', 'SH', 'sahayak-visit', 'Contact us'),
        _i('contact-other', 'Contact us · Others', 'Others', 'form', sub='Contact us'),
        _i('ti-quote', 'Travel insurance site · Search quote', 'Search quote', 'form', 'TI', 'ti-standard',
           'Travel insurance site'),
        _i('ti-expert', 'Travel insurance site · Request (WhatsApp / call)', 'Request (WhatsApp / call)', 'popup',
           'TI', 'ti-standard', 'Travel insurance site'),
        _i('tc-trip-post', 'Travel companion site · Companion post', 'Companion posts', 'form', 'TC', 'tc-companion',
           'Travel companion site'),
        _i('tc-request', 'Travel companion site · Request (WhatsApp / call)', 'Request (WhatsApp / call)', 'popup',
           'TC', 'tc-companion', 'Travel companion site'),
        _i('sh-booking', 'Sahayak site · Request Sahayak', 'Request Sahayak', 'form', 'SH', 'sahayak-visit',
           'Sahayak site'),
        _i('sh-request', 'Sahayak site · Request (WhatsApp / call)', 'Request (WhatsApp / call)', 'popup', 'SH',
           'sahayak-visit', 'Sahayak site'),
        _i('sh-apply', 'Sahayak site · Nurse job application', 'Nurse job application', 'form', 'SH',
           'nurse-recruitment', 'Sahayak site'),
        _i('web-other', 'Website · Others', 'Others', 'form', sub='Other websites'),
    )),
)
ITEMS = {it.key: (g, it) for g, _n, _ic, items in GROUPS for it in items}
# what each group is, for the Lead sources screen
GROUP_SAYS = {
    'calls': 'Calls and chats on our own numbers, and Tawk on the sites. The half-hourly check watches these.',
    'social': 'Messages, posts and comments on Instagram and Facebook (Meta), and Telegram. Meta lead-ad forms join here.',
    'reference': 'Someone who knows us sent them: a friend, a family member, a past customer.',
    'staff': 'Companion posts the team put up from Facebook groups and WhatsApp.',
    'other': 'Anything that fits nowhere else, an e-mail to us included.',
    'imports': 'Lists brought in on Bring in & download: Excel sheets, the scraper, CSV files.',
    'web': 'Forms on our websites: they file their leads here by themselves.',
    'unsorted': 'Not on the list: an old source, or a page nobody has set up. Move their leads onto the list.'}
GROUP_NAMES = {g: (name, icon) for g, name, icon, _items in GROUPS}
UNSORTED = ('unsorted', 'Not in the list', 'fa-circle-question')

# old keys and the item each became: the leads under them move there (tidy), and a capture still sending one is
# filed there (canonical)
MERGED = {'instagram': 'meta', 'facebook': 'meta', 'ti-support': 'ti-expert', 'sales-sheet': 'import-other',
          'csv-import': 'import-other', 'event': 'other', 'direct-sale': 'other', 'email': 'other',
          'google-ads': 'web-other', 'site-account': 'web-other', 'newsletter': 'web-other'}
# old keys that were two things: a +1 number is the USA side, any other the India side
SPLIT = {'call': ('usa-call', 'company-call'), 'reference': ('ref-usa', 'ref-india')}

# how a lead came to us: (key, the word on a badge, what it means, icon)
ORIGINS = (('organic', 'Organic', 'Came in by itself', 'fa-seedling'),
           ('manual', 'Manual', 'Added by staff', 'fa-user-pen'),
           ('imported', 'Imported', 'Brought in from a list or the sales sheet', 'fa-file-import'))
ORIGIN = {k: (word, says, icon) for k, word, says, icon in ORIGINS}


def item(key):
    """(group key, Item) for a key on the list, else None."""
    return ITEMS.get(key)


def group_of(src):
    """The group key a source row is shown in: its item's; a Meta lead-ad form is Meta's, a Google one Other's;
    anything else is not on the list."""
    key = getattr(src, 'key', src) or ''
    if key in ITEMS:
        return ITEMS[key][0]
    if key.startswith('meta-form-'):
        return 'social'
    if key.startswith('google-form-'):
        return 'other'
    return UNSORTED[0]


def group_name(group):
    return GROUP_NAMES.get(group, UNSORTED[1:])


def short_name(src):
    """How a source reads inside its group (its own name when it is not on the list)."""
    key = getattr(src, 'key', None)
    return ITEMS[key][1].short if key in ITEMS else getattr(src, 'name', '') or ''


def canonical(key, phone=None):
    """The key a lead from `key` is filed under (see MERGED and SPLIT)."""
    if key in SPLIT:
        usa, india = SPLIT[key]
        return usa if (phone or '').startswith('+1') else india
    return MERGED.get(key, key)


def standard_inboxes(wa_key='wa-india'):
    """The half-hourly check's rows from the list: a row for each call, chat and social inbox; the WhatsApp feed's
    own ticks itself once its replies are connected."""
    return [{'name': it.short.replace(' · ', ' ')[:40], 'source_key': it.key, 'auto': it.key == wa_key}
            for g, _n, _ic, items in GROUPS if g in ('calls', 'social') for it in items]


def seed_rows():
    """The items as crm_defaults.SOURCES rows: (key, name, kind, product, pipeline key, pages, status)."""
    return [(it.key, it.name, it.kind, it.product, it.pipeline, [], 'live')
            for _g, _n, _ic, items in GROUPS for it in items]


# ---------------------------------------------------------------------------------------- the old sources

def tidy():
    """Put this workspace's sources on the list. The items keep their names (the list is fixed: a name edited
    elsewhere comes back); an old source's leads move to the item it became -- "call" and "reference" lead by
    lead, by the person's number -- and the old source goes (move). Nothing to do, the usual case, is one query.
    No commit. True when anything changed."""
    from app.models import CrmLead, CrmPerson, CrmSource
    rows = CrmSource.query.all()
    by_key = {s.key: s for s in rows}
    changed = False
    for s in rows:
        it = ITEMS.get(s.key)
        if it is not None and (s.name != it[1].name or s.kind != it[1].kind):
            s.name, s.kind = it[1].name, it[1].kind
            changed = True
    for s in [s for s in rows if s.key in MERGED or s.key in SPLIT]:
        if s.key in SPLIT:
            usa, india = (by_key.get(k) for k in SPLIT[s.key])
            if usa is None or india is None:
                continue
            leads = CrmLead.query.filter(CrmLead.source_id == s.id).all()
            phones = dict(db.session.query(CrmPerson.id, CrmPerson.phone)
                          .filter(CrmPerson.id.in_({l.person_id for l in leads})).all()) if leads else {}
            for lead in leads:
                if (phones.get(lead.person_id) or '').startswith('+1'):
                    lead.source_id = usa.id
            db.session.flush()
            new = india                          # the rest, and its campaigns and rules, go to the India side
        else:
            new = by_key.get(MERGED[s.key])
            if new is None:
                continue
        move(s, new)
        changed = True
    return changed


def move(old, new):
    """Everything filed under source `old` -- its leads, campaigns, the rules that test it or share through it,
    the half-hourly check's rows -- goes to `new`, with its count and last lead; `old` is deleted when it is not
    one of the list's items (an item stays, empty). No commit. How many leads moved."""
    from app.models import CrmCampaign, CrmLead
    n = CrmLead.query.filter(CrmLead.source_id == old.id).update({'source_id': new.id}, synchronize_session=False)
    CrmCampaign.query.filter(CrmCampaign.source_id == old.id).update({'source_id': new.id},
                                                                     synchronize_session=False)
    _move_rules({old.id: new.id})
    _move_inboxes({old.key: new.key})
    new.lead_count = (new.lead_count or 0) + (old.lead_count or 0)
    if old.last_lead_at and (new.last_lead_at is None or old.last_lead_at > new.last_lead_at):
        new.last_lead_at = old.last_lead_at
    if old.key in ITEMS:
        old.lead_count, old.last_lead_at = 0, None
    else:
        db.session.delete(old)
    db.session.flush()
    return n


def _move_rules(moved):
    """Rules that test a moved source, or share in turn through one, now name the item it became."""
    if not moved:
        return
    from app.models import CrmRule

    def swap(v):                                 # a condition's value: an id, as a number or text, or a list of them
        if isinstance(v, list):
            return [swap(x) for x in v]
        return type(v)(moved[int(v)]) if isinstance(v, (int, str)) and str(v).isdigit() and int(v) in moved else v
    for rule in CrmRule.query.all():
        conds = [dict(c, value=swap(c.get('value'))) if isinstance(c, dict) and c.get('field') == 'source' else c
                 for c in rule.conditions or []]
        acts = []
        for a in rule.actions or []:
            via = a.get('via') if isinstance(a, dict) else None
            if via and via.startswith('source:') and via[7:].isdigit() and int(via[7:]) in moved:
                a = dict(a, via='source:%d' % moved[int(via[7:])])
            acts.append(a)
        if conds != (rule.conditions or []) or acts != (rule.actions or []):
            rule.conditions, rule.actions = conds, acts


def _move_inboxes(keys):
    """The half-hourly check's rows that pointed at an old source point at its item."""
    if not keys:
        return
    from app.services import crm
    raw = crm.crm_settings_raw().get('check_channels')
    if not raw or not any(isinstance(r, dict) and r.get('source_key') in keys for r in raw):
        return
    crm.save_settings(check_channels=[dict(r, source_key=keys[r['source_key']])
                                      if isinstance(r, dict) and r.get('source_key') in keys else r for r in raw])


# ---------------------------------------------------------------------------------------- one lead

def _is_staff(user):
    from app.models import request_cache
    from app.services import access
    cache = request_cache('crm_staff')
    if user.id not in cache:
        cache[user.id] = access.is_staff(user)
    return cache[user.id]


def origin(lead):
    """'imported' (a list or the sales sheet), 'manual' (somebody of ours added it), or 'organic' (it came by
    itself: a form, a message, a post a customer made -- whose account is recorded as its maker)."""
    if lead.imported:
        return 'imported'
    by = lead.created_by
    return 'manual' if by is not None and _is_staff(by) else 'organic'


def staff_ids(user_ids):
    """The staff among these user ids (for the "how it came" filter)."""
    from app.models import User
    ids = [i for i in set(user_ids) if i]
    return {u.id for u in User.query.filter(User.id.in_(ids)).all() if _is_staff(u)} if ids else set()


def came_from(lead):
    """What a screen says about where a lead came from:
        {group, group_name, icon, name, short, origin, origin_word, origin_label, origin_icon, by (a name or None),
         at (IST text)} -- `name` says it whole ("Sahayak site · Request (WhatsApp / call)"), `short` within its group"""
    src = lead.source
    group = group_of(src) if src is not None else UNSORTED[0]
    gname, icon = group_name(group)
    how = origin(lead)
    by = lead.created_by.full_name if how != 'organic' and lead.created_by is not None else None
    from app.services import clock
    at = clock.local(lead.created_at)
    return {'group': group, 'group_name': gname, 'icon': icon,
            'name': src.name if src is not None else 'Not known', 'short': short_name(src) if src else 'Not known',
            'origin': how, 'origin_word': ORIGIN[how][0], 'origin_label': ORIGIN[how][1], 'origin_icon': ORIGIN[how][2],
            'by': by,
            'at': '%d %s, %s' % (at.day, at.strftime('%b %Y'), at.strftime('%H:%M')) if at else ''}


def sections(rows):
    """One group's sources by their part of it (the websites: Contact us, Travel insurance site ...):
    [(part or None, [rows])], in order."""
    out = []
    for s in rows:
        it = ITEMS.get(s.key)
        sub = it[1].sub if it is not None else None
        if not out or out[-1][0] != sub:
            out.append((sub, []))
        out[-1][1].append(s)
    return out


def grouped(sources):
    """[(group key, name, icon, [source rows])] in the list's order, the items in theirs, the sources not on the
    list last."""
    order = {it.key: n for n, it in enumerate(it for _g, _n, _ic, items in GROUPS for it in items)}
    out = []
    for g, name, icon, _items in GROUPS + (UNSORTED + ((),),):
        rows = sorted([s for s in sources if group_of(s) == g],
                      key=lambda s: (order.get(s.key, 999), (s.name or '').lower()))
        if rows:
            out.append((g, name, icon, rows))
    return out
