"""What the Sales CRM starts with: pipelines, their message steps, ready answers and lead sources.

Everything here is a starting point an admin edits on screen (Sales CRM -> Setup). It is written
into the database the first time the CRM is opened and never again, so an edit is never undone by
a deploy. The steps and their codes come from the "Messaging" sheet of Sales Process 1.5
(TC #1-#10, TI #1-#4, CL #1-#3, PI #1-#4, CE #1-#3, PF #1); the answers from its FAQ sheet and the
questions families ask most.

Message text may use these, filled in when it is sent:
    {name}        the person's first name             {agent}       the owner's first name
    {product}     e.g. "travel insurance"             {departure}   the trip's departure date
    {days}        days left before departure          {helplines}   the published phone numbers
    {ends}        the date the policy / trip ends
    {insurance_link} {companion_link} {sahayak_link} {site_link}
"""
import re

# ---------------------------------------------------------------------------------------- pipelines
# (key, name, product, fallout reasons, stages)
# stage: (key, name, kind, on_reply, sla_hours, steps[, automation])
#   automation: (kind, days, stage key to move to, reason) -- see CRM_AUTO_KINDS
# step:  (code, title, channel, trigger, value, auto, body)
# These tuples keep the vocabulary from before U5 (D / E triggers, 'departed'); ensure_defaults() turns
# them into date_offset / after_date with seed_trigger() / seed_auto() below.
H = 'after_hours'
D = 'before_departure_days'
E = 'before_end_days'

PIPELINES = [
    ('ti-standard', 'Travel insurance', 'TI',
     ['Bought elsewhere', 'Price too high', 'Trip cancelled', 'Already insured', 'Not interested',
      'No response', 'Wrong number'],
     [
         ('cold', 'Cold lead', 'open', False, 24, [
             ('TI #1', 'Details: introduce yourself and offer a quote', 'whatsapp', H, 0, True,
              "Hi {name}, {agent} here from NRI Parent Service. You mentioned you might be looking "
              "into travel insurance options for your parents' upcoming visit.\n\n"
              "Managing coverage for parents travelling from India can get complicated with "
              "pre-existing conditions and emergency medical limits. We built our NRI parent "
              "insurance plans to handle exactly these needs, with seamless claims support and "
              "zero-hassle paperwork.\n\n"
              "Would you have 5 minutes this week for a quick chat, or would you prefer I send over "
              "a quick quote breakdown based on their travel dates?\n\n"
              "Here is the additional value we provide at no extra charge:\n"
              "* 24/7 local-language support: direct help with claims or policy questions, without "
              "waiting for a generic call centre.\n"
              "* A complimentary virtual doctor consultation for your parents while they are abroad.\n"
              "* Complimentary travel companion help, so your parents are not alone on the journey."),
             ('CL #2', 'Call after a day: ask for a good time to talk', 'call', H, 24, False,
              "Hi, I am {agent}, welcome to NRI Parent Service. Follow up on their insurance enquiry, "
              "ask when is a good time to go through the options, and send the flyer."),
             ('CL #3', 'Third and last call', 'call', H, 72, False,
              "Hi, I am {agent}, welcome to NRI Parent Service (send the flyer). This is the third "
              "call -- the limit. If there is still no answer the lead moves to fallout by itself."),
         ], ('no_reply', 7, 'prospect_fallout', 'No response after three calls')),
         ('prospect', 'Prospect', 'open', True, 48, [
             ('TI #2', 'Daily message: did they decide?', 'whatsapp', H, 24, False,
              "Hi {name}, I am {agent}. How are you doing? Did you make a decision on your parents' "
              "cover? Happy to answer any question, or to call if that is easier."),
             ('TI #3', 'Call after 2 days with no response: two options + payment link', 'call', H, 48, False,
              "Give at least two options with comparable prices, our unique selling points (local-"
              "language support, free virtual doctor consultation, travel companion help), and the "
              "details for the payment link."),
         ], ('no_reply', 10, 'prospect_fallout', 'No response')),
         ('quoted', 'Quoted', 'open', False, 72, [
             ('TI #4', 'Quotes: two options side by side', 'whatsapp', H, 0, False,
              "Hi {name}, here are two options for your parents' visit:\n\n"
              "1) [plan, cover, price]\n2) [plan, cover, price]\n\n"
              "Both can be bought online: {insurance_link}\n"
              "With us you also get local-language support for claims, a complimentary virtual "
              "doctor consultation while they are abroad, and travel companion help."),
         ]),
         ('pipeline', 'Pipeline', 'open', False, 120, [
             ('PI #1', 'Five-day follow-up', 'whatsapp', H, 120, False,
              "Hi {name}, I am {agent}. How are you doing? Did you make a decision on your parents' "
              "cover? I can hold the quotes for you."),
             ('PI #2', 'Call message: departure in 3 days or less', 'whatsapp', D, 3, False,
              "Hi {name}, your parents' travel is coming soon. We want to make sure you have an "
              "amazing time with them rather than worrying about health. If you haven't decided yet, "
              "we can have a call together and choose the best option possible."),
             ('PI #3', 'Sales call', 'call', H, 24, False,
              "Sales call: go through the two options again and help them pay."),
             ('PI #4', 'Day of travel: US escalation', 'call', D, 0, False,
              "Departure day. Escalate to the US sales team for a last sales call from the USA."),
         ], ('departed', 1, 'pipeline_fallout', 'Trip started without buying')),
         ('customer', 'Policy bought', 'won', False, None, [
             ('CE #1', 'Welcome to the family', 'whatsapp', H, 0, True,
              "Welcome to the NRI Parent Service family, {name}! We are here to support you -- "
              "please reach out to us for any of these:\n* claims or questions about the policy\n"
              "* a virtual doctor consultation for your parents\n* a travel companion for their "
              "next journey\nSave this number: {agent}, NRI Parent Service."),
             ('CE #2', 'Feedback and a reference', 'whatsapp', H, 168, False,
              "Hi {name}, how is the visit going? If we helped, a short review or a friend who "
              "could use us would mean a lot."),
             ('CE #3', 'Personal follow-up after 15 days', 'call', H, 360, False,
              "A personal check-in: how are the parents, anything they need? Note any upsell "
              "(Gift Health, Sahayak) in the lead."),
             ('ER', 'Policy ends in 10 days: offer an extension', 'whatsapp', E, 10, False,
              "Hi {name}, your parents' cover ends on {ends}. If they are staying longer, I can "
              "extend it before then so there is no gap -- just reply with the new return date."),
         ]),
         ('prospect_fallout', 'Prospect fallout', 'lost', False, None, [
             ('PF #1', 'Five days later: still here for them', 'whatsapp', H, 120, False,
              "Hi {name}, just checking everything is OK with your parents' trip. If anything is "
              "needed, we are still here."),
         ]),
         ('pipeline_fallout', 'Pipeline fallout', 'lost', False, None, [
             ('PF #1', 'Five days later: why could we not get your business?', 'whatsapp', H, 120, False,
              "Hi {name}, just checking everything is OK with your parents' trip -- we are still here "
              "if anything is needed. If you have a moment: what made you decide not to go ahead "
              "with us? It helps us do better."),
             ('PF #2', 'Feedback poll', 'whatsapp', H, 72, False,
              "Hi {name}, one quick question so we can improve: why did you not take the cover with "
              "us?\nA) Price  B) Bought elsewhere  C) Not needed any more  D) Something else"),
         ]),
     ]),

    ('tc-companion', 'Travel companion', 'TC',
     ['Found a companion elsewhere', 'Trip cancelled', 'Travelled already', 'Not interested',
      'No response', 'Wrong number', 'Duplicate'],
     [
         ('posted', 'Posted', 'open', False, 48, [
             ('TC #1', 'Welcome warm-up (compassion, no selling)', 'whatsapp', H, 0, True,
              "Hi {name}, I am {agent} from NRI Parent Service. We have your trip, and we will also be "
              "looking out for a companion for your parents -- we are here to make their journey "
              "smooth. Your trip and matches are here: {companion_link}\nYou can reach us on this "
              "WhatsApp, on Instagram, or in the chat on the site."),
             ('TC #4', 'Fifteen days out, no match yet', 'whatsapp', D, 15, False,
              "Hi {name}, we are still looking for the right companion and will keep at it. "
              "Meanwhile, have you sorted travel insurance? Parents' cover with pre-existing "
              "conditions is our speciality: {insurance_link}"),
             ('TC #5', 'Loyal lead, travel in 5 days: call', 'call', D, 5, False,
              "Call: we could not find a proper companion, but we can help with travel insurance -- "
              "explain what makes ours different."),
             ('TC #6', 'Non-responsive lead, travel in 5 days: insurance message', 'whatsapp', D, 5, False,
              "Hi {name}, we are still looking for a companion for your parents. Whatever happens, "
              "please make sure they travel insured: our parent plans cover pre-existing conditions, "
              "with a free virtual doctor consultation while abroad. {insurance_link}"),
         ], ('departed', 1, 'closed', 'Travelled already')),
         ('in_touch', 'In touch', 'open', True, 72, [
             ('TC #3', 'Closest match update (no selling)', 'whatsapp', H, 72, False,
              "Hi {name}, an update on your parents' trip: we are working on the closest matches for "
              "their route and dates. You can see them here: {companion_link}"),
         ], ('departed', 1, 'closed', 'Travelled already')),
         ('matched', 'Matched', 'open', False, 48, [
             ('TC #2', 'Match success: Hooray! Then insurance, short and sweet', 'whatsapp', H, 0, False,
              "Hooray {name}, your parents have a companion! One more thing for a worry-free trip: "
              "travel insurance built for parents, with a complimentary virtual doctor consultation. "
              "{insurance_link}"),
         ], ('departed', 1, 'connected', 'They travelled together')),
         ('connected', 'Connected', 'won', False, None, [
             ('TC #7', 'Match success: health, Sahayak and Gift Health', 'whatsapp', H, 48, False,
              "Hi {name}, glad the companion worked out! Health matters as much as the journey: a "
              "Sahayak nurse can take care of your parents' check-ups and appointments at home, and "
              "our preventive plans (Gift Health) keep an eye on them all year. {sahayak_link}"),
         ]),
         ('closed', 'No longer needed', 'lost', False, None, []),
     ]),

    ('sahayak-visit', 'Sahayak visit', 'SH',
     ['Cancelled by family', 'No Sahayak available', 'Outside service area', 'Price',
      'No response', 'Duplicate'],
     [
         ('new', 'Booking received', 'open', False, 2, [
             ('SH #1', 'Call to confirm the visit', 'call', H, 0, False,
              "Call the family, confirm the service, address and a time that suits the parent."),
         ]),
         ('confirmed', 'Confirmed', 'open', True, 24, [
             ('SH #2', 'Tell the family who is coming', 'whatsapp', H, 0, False,
              "Hi {name}, your Sahayak visit is confirmed. We will share the nurse's name before "
              "the visit and a summary after it."),
         ]),
         ('assigned', 'Sahayak assigned', 'open', False, 48, []),
         ('done', 'Visit completed', 'won', False, None, [
             ('SH #3', 'Ask how it went', 'whatsapp', H, 24, False,
              "Hi {name}, how did the visit go? Your feedback helps us, and we can plan the next "
              "one whenever you like."),
         ]),
         ('cancelled', 'Cancelled', 'lost', False, None, []),
     ]),

    ('nurse-recruitment', 'Nurse recruitment', 'SH',
     ['Not B.Sc Nursing / GNM / ANM', 'No council registration', 'Not interested', 'No response',
      'Outside service area'],
     [
         ('applied', 'Applied', 'open', False, 24, [
             ('NR #1', 'Call within a day', 'call', H, 0, False,
              "Call the applicant: confirm the qualification (B.Sc Nursing, GNM or ANM), the State "
              "Nursing Council registration number and the area they can work in."),
         ]),
         ('verified', 'Registration checked', 'open', True, 48, [
             ('NR #2', 'Ask for documents', 'whatsapp', H, 0, False,
              "Hi {name}, thank you for applying to Sahayak. Please send clear photos of your photo "
              "ID, your nursing certificate and your council registration certificate."),
         ]),
         ('documents', 'Documents received', 'open', False, 72, [
             ('NR #3', 'Book the orientation', 'call', H, 0, False,
              "Call to book the training and orientation session."),
         ]),
         ('active', 'Active Sahayak', 'won', False, None, [
             ('NR #4', 'Welcome to the network', 'whatsapp', H, 0, False,
              "Welcome to the Sahayak network, {name}! Your profile is active and assignments near "
              "you will start coming through the app."),
         ]),
         ('rejected', 'Not suitable', 'lost', False, None, []),
     ]),

    ('general', 'General enquiry', 'GEN',
     ['No response', 'Spam', 'Duplicate', 'Answered elsewhere'],
     [
         ('new', 'New enquiry', 'open', False, 2, [
             ('GEN #1', 'Reply within two hours', 'whatsapp', H, 0, False,
              "Hi {name}, this is {agent} from NRI Parent Service. Thank you for getting in touch. "
              "How can we help?"),
         ]),
         ('talking', 'In conversation', 'open', True, 48, [
             ('GEN #2', 'Follow up next day', 'whatsapp', H, 24, False,
              "Hi {name}, {agent} here. Is there anything else we can help with?"),
         ], ('no_reply', 7, 'closed', 'No response')),
         ('resolved', 'Resolved', 'won', False, None, []),
         ('closed', 'Closed', 'lost', False, None, []),
     ]),
]

# which pipeline a product's leads start in when their source does not name one (seed data only:
# crm_products.default_pipeline_id is what is read)
PRODUCT_PIPELINE = {'TI': 'ti-standard', 'TC': 'tc-companion', 'SH': 'sahayak-visit',
                    'GH': 'general', 'VC': 'general', 'GEN': 'general'}

# products: seed data only -- written into crm_products once (crm_products.ensure_seeded)
PRODUCT_ICONS = {'TI': 'fa-shield-heart', 'TC': 'fa-plane-departure', 'SH': 'fa-house-medical',
                 'GH': 'fa-gift', 'VC': 'fa-user-doctor', 'GEN': 'fa-comments'}
PRODUCT_KPI_ROWS = {'TC': 'tc_posts'}


def products():
    """(code, name, icon, offered, pipeline key, kpi_row) from CRM_PRODUCTS / CRM_PRODUCT_LABELS / PRODUCT_PIPELINE."""
    from app.models import CRM_PRODUCTS, CRM_PRODUCT_LABELS
    return [(c, CRM_PRODUCT_LABELS[c], PRODUCT_ICONS.get(c, 'fa-layer-group'), True,
             PRODUCT_PIPELINE.get(c, 'general'), PRODUCT_KPI_ROWS.get(c)) for c in CRM_PRODUCTS]


# the lead page's buttons, by stage key: (button label, code)
MILESTONES = {'quoted': ('I sent the quote', 'Q'), 'pipeline': ('I sent the payment link', 'PLS')}
CATCH_ALL = ('general',)           # pipeline keys that pass a lead on to its product's own pipeline
# a new pipeline starts as (key, name, means, on_reply) and can be changed on screen
SIMPLE_PATH = [('new', 'New', 'new', False), ('talking', 'Talking', 'talking', True),
               ('won', 'Won', 'won', False), ('lost', 'Lost', 'lost', False)]
SIMPLE_REASONS = ['No response', 'Not interested', 'Duplicate']

STEP_KIND_PREFIXES = {'PI': 'reminder', 'CE': 'care', 'SH': 'care', 'BW': 'birthday', 'FM': 'festival',
                      'OM': 'festival', 'PM': 'promotion', 'ER': 'expiry', 'PF': 'after_lost'}
STEP_KIND_CODES = {'reminder': 'PI', 'care': 'CE', 'birthday': 'BW', 'festival': 'FM', 'promotion': 'PM',
                   'expiry': 'ER', 'after_lost': 'PF', 'other': 'FU'}    # first -> the product code
LEGACY_TRIGGERS = {'before_departure_days': 'departure_date', 'before_end_days': 'ends_on'}


def step_kind(code, product_codes):
    """A step's kind from its code: the kind prefixes first (SH is Sahayak's care), then a product code
    is the first contact, else other."""
    text = (code or '').strip().upper()
    m = re.match(r'^[A-Z][A-Z0-9]*', text)
    prefix = m.group(0) if m else ''
    if prefix not in STEP_KIND_PREFIXES and prefix not in (product_codes or ()):
        m = re.match(r'^[A-Z]+', text)         # "TC2" still reads as TC
        prefix = m.group(0) if m else ''
    if prefix in STEP_KIND_PREFIXES:
        return STEP_KIND_PREFIXES[prefix]
    if prefix in (product_codes or ()):
        return 'first'
    return 'other'


def seed_trigger(trigger, value):
    """('before_departure_days', 3) -> ('date_offset', 'departure_date', -3); after_hours unchanged."""
    if trigger in LEGACY_TRIGGERS:
        return 'date_offset', LEGACY_TRIGGERS[trigger], -abs(value or 0)
    return trigger, None, value


def seed_auto(kind):
    """'departed' -> ('after_date', 'departure_date'); others -> (kind, None)."""
    if kind == 'departed':
        return 'after_date', 'departure_date'
    return kind, None

# ---------------------------------------------------------------------------------------- sources
# (key, name, kind, product, pipeline key, pages, status)
# ti-support, contact-companion and contact-sahayak name the pipeline the catch-all rule already passed
# their leads on to (U5)
SOURCES = [
    ('tc-trip-post', 'TC: trip posted on the site', 'form', 'TC', 'tc-companion', ['/'], 'live'),
    ('tc-cs-post', 'TC: post added by CS (Facebook groups, WhatsApp)', 'manual', 'TC', 'tc-companion',
     ['/cs/posts/new'], 'live'),
    ('tc-import', 'TC: Excel import and scraper', 'import', 'TC', 'tc-companion', ['/cs/import'], 'live'),
    ('ti-quote', 'TI: quote request', 'form', 'TI', 'ti-standard', ['/travel-insurance'], 'live'),
    ('ti-expert', 'TI: expert form and consultation pop-up', 'popup', 'TI', 'ti-standard',
     ['/travel-insurance'], 'live'),
    ('ti-support', 'TI: support form', 'form', 'TI', 'ti-standard', ['/travel-insurance'], 'live'),
    ('sh-booking', 'Sahayak: visit booking', 'form', 'SH', 'sahayak-visit', ['/sahayak'], 'live'),
    ('sh-apply', 'Sahayak: nurse application', 'form', 'SH', 'nurse-recruitment', ['/sahayak'], 'live'),
    ('contact-companion', 'Contact us: travel companion', 'form', 'TC', 'tc-companion', ['/contact-us'], 'live'),
    ('contact-insurance', 'Contact us: insurance', 'form', 'TI', 'ti-standard', ['/contact-us'], 'live'),
    ('contact-sahayak', 'Contact us: Sahayak', 'form', 'SH', 'sahayak-visit', ['/contact-us'], 'live'),
    ('contact-general', 'Contact us: general', 'form', 'GEN', 'general', ['/contact-us'], 'live'),
    ('newsletter', 'Newsletter sign-up', 'form', 'GEN', 'general', ['/'], 'paused'),
    ('wa-india', 'WhatsApp: India number', 'chat', 'GEN', 'general', [], 'live'),
    ('wa-usa', 'WhatsApp: USA number', 'chat', 'GEN', 'general', [], 'live'),
    ('instagram', 'Instagram DMs and comments', 'chat', 'GEN', 'general', [], 'live'),
    ('facebook', 'Facebook messages and comments', 'chat', 'GEN', 'general', [], 'live'),
    ('tawk', 'Tawk chat', 'chat', 'GEN', 'general', [], 'live'),
    ('call', 'Phone call (India or USA)', 'manual', 'GEN', 'general', [], 'live'),
    ('event', 'Event or association', 'manual', 'GEN', 'general', [], 'live'),
    ('reference', 'Reference / friends and family', 'manual', 'GEN', 'general', [], 'live'),
    ('telegram', 'Telegram', 'chat', 'GEN', 'general', [], 'live'),
    ('google-ads', 'Google Ads', 'ads', 'TI', 'ti-standard', [], 'live'),
    ('direct-sale', 'Direct sale', 'manual', 'TI', 'ti-standard', [], 'live'),
    ('sales-sheet', 'Sales sheet (Excel import)', 'import', 'GEN', 'general', [], 'live'),
    ('site-account', 'Site account (added from existing data)', 'manual', 'GEN', 'general', [], 'live'),
    ('csv-import', 'Imported list (CSV)', 'import', 'GEN', 'general', [], 'live'),
]

# ---------------------------------------------------------------------------------------- answers
# (product, question, keywords, answer)
ANSWERS = [
    ('TI', 'Why is your price different from another site?',
     'price difference cheaper expensive cost compare another site lower match',
     "All insurance products are regulated, so the same policy should cost the same everywhere. "
     "If you can share the policy you are looking at, I will try to match it or walk you through "
     "the differences. With us you also get, at no extra charge:\n"
     "- local-language support for claims and policy questions\n"
     "- a complimentary virtual doctor consultation while your parents are abroad\n"
     "- travel companion help, so your parents are not alone on the journey"),
    ('TI', 'How much does visitor insurance cost?',
     'price cost rate how much premium charge expensive budget age',
     "It depends mostly on age and the type of plan. As a rough guide for a visit to the USA:\n"
     "- age 40-50: about $40 (fixed) or $70 (comprehensive)\n"
     "- age 50-60: about $40 or $150\n"
     "- age 60-70: about $70 or $300\n"
     "- age 70-80: about $120 or $500\n"
     "These are approximate. Share your parents' ages and travel dates and I will send exact quotes."),
    ('TI', 'Are pre-existing conditions covered?',
     'pre-existing preexisting existing bp blood pressure diabetes sugar heart condition history disease',
     "It depends on the plan. Some plans exclude pre-existing conditions; others give limited cover, "
     "for example for a sudden flare-up (acute onset), subject to conditions and age limits. Tell me "
     "about your parents' conditions and I will point you to the plans that cover them."),
    ('TI', 'What is the difference between fixed and comprehensive plans?',
     'fixed comprehensive difference type plan benefit which better',
     "A fixed plan pays set amounts for each kind of treatment, whatever the bill. A comprehensive "
     "plan pays a share of the actual eligible costs after the deductible, up to the policy limit, "
     "so it usually protects better against large US hospital bills. Comprehensive costs more."),
    ('TI', 'How much cover should I take?',
     'coverage amount limit sum insured how much cover 50k 100k maximum',
     "For parents visiting the USA most families choose between $50,000 and $100,000; higher limits "
     "make sense for older parents or longer stays because US hospital costs are high. I can quote "
     "two limits side by side so you can compare."),
    ('TI', 'What is a deductible?',
     'deductible excess pay first out of pocket',
     "The deductible is the part of an eligible claim you pay before the plan pays. A higher "
     "deductible lowers the premium. Common choices are $0 to $500."),
    ('TI', 'How do I make a claim?',
     'claim reimbursement hospital bill pay back insurer cashless',
     "Claims go to the insurer or the claims administrator named on the policy. Keep every medical "
     "report, bill and receipt, and tell the insurer as soon as you can. We will help you with the "
     "forms and follow up with them for you."),
    ('TI', 'When should I buy?',
     'when buy before travel start date last minute early',
     "Buy before your parents travel, ideally soon after the tickets are booked. Cover cannot be "
     "bought for something that has already happened."),
    ('TI', 'Can I buy after my parents have arrived?',
     'already arrived landed after arrival here now in usa',
     "Many visitor plans can still be bought after arrival, but cover starts from the purchase date "
     "and some plans add a waiting period, so nothing before then is covered. Better to buy today."),
    ('TI', 'Do you have insurance for a Schengen visa?',
     'schengen visa europe embassy germany france italy',
     "Yes. We offer travel medical plans for Schengen visa applications. Check that the chosen policy "
     "meets your embassy's requirements; I can send a quote with the dates you need."),
    ('TC', 'How does the travel companion service work?',
     'companion how work match find someone travel with same flight',
     "You post your parents' trip (route and date), and we match them with others travelling the "
     "same way. Contact details are shared only when both sides agree. Our team checks every match "
     "and keeps you updated."),
    ('TC', 'Is it safe? Who are the companions?',
     'safe trust verified who stranger security',
     "Contact details are shared only when both families agree, and our team reviews matches before "
     "anyone is introduced. You decide whether to connect."),
    ('TC', 'Is the travel companion service free?',
     'free cost charge pay companion fee',
     "Yes, finding a travel companion is free."),
    ('SH', 'What does a Sahayak do?',
     'sahayak nurse home visit what do service help parents',
     "A Sahayak is a registered nurse (B.Sc Nursing, GNM or ANM) who takes each step with your "
     "parents: the health check, tests, appointments and medicines. Every step is recorded so you "
     "can read it from wherever you are."),
    ('SH', 'How soon can someone visit?',
     'when soon today tomorrow urgent time visit quickly',
     "We call you to agree a time that suits your parents. If it is urgent, tell us and we will try "
     "for the earliest slot."),
    ('SH', 'Which cities do you cover?',
     'city area cover location available pincode where hyderabad',
     "Share your parents' city and PIN code and we will confirm whether a Sahayak is available near "
     "them."),
    ('GEN', 'How can I talk to someone?',
     'call talk phone number contact human person speak',
     "You can reach us on {helplines}, or reply here and we will call you back."),
    ('GEN', 'What is NRI Parent Service?',
     'who are you what is company about nri parent service',
     "NRI Parent Service helps families abroad look after parents in India: travel companions, "
     "travel insurance for visiting parents, and Sahayak nurses for care at home."),
]


# ---------------------------------------------------------------------------------------- quick messages
# (product, code, title, body) -- sent from a lead at any time and counted under the code on the
# KPI dashboard (BW birthday wishes, FM festival messages, ER expiration reminders...).
QUICK_MESSAGES = [
    ('GEN', 'BW', 'Birthday wishes',
     "Happy birthday, {name}! Wishing you and your family a wonderful year ahead. -- {agent}, NRI Parent Service"),
    ('GEN', 'FM', 'Festival message',
     "Wishing you and your family a very happy festival, {name}! May it bring health and joy to your parents "
     "and to all of you. -- {agent}, NRI Parent Service"),
    ('GEN', 'OM', 'Occasion message',
     "Hi {name}, {agent} from NRI Parent Service here -- thinking of you and your family on this occasion. "
     "We are always here if your parents need anything."),
    ('GEN', 'CM', 'Casual message',
     "Hi {name}, {agent} here from NRI Parent Service. Just checking in -- how are you and your parents doing?"),
    ('TI', 'HJ', 'Happy journey',
     "Wishing your parents a safe and happy journey, {name}! If anything comes up on the way or after they "
     "land, call {helplines} or message me here."),
    ('TI', 'SA', 'Safely arrived?',
     "Hi {name}, have your parents arrived safely? I hope the journey went well. Remember they can have a "
     "free virtual doctor consultation any time during their stay."),
    ('TI', 'ER', 'Expiration reminder',
     "Hi {name}, your parents' cover ends on {ends}. If they are staying longer, I can extend it before then "
     "so there is no gap -- just reply with the new return date."),
    ('TI', 'CS', 'Feedback poll',
     "Hi {name}, one quick question so we can improve: how would you rate our help, from 1 (poor) to 5 "
     "(excellent)? And is there anything we could have done better?"),
    ('GEN', 'PM', 'Promotional message',
     "Hi {name}, {agent} from NRI Parent Service. Planning your parents' next visit? Travel insurance built "
     "for parents, a travel companion for the journey and a Sahayak nurse at home: {site_link}"),
    ('GEN', 'SE', 'Shift end message',
     "Hi {name}, {agent} here -- I am signing off for today. For anything urgent our team is on {helplines}, "
     "and I will pick up your conversation first thing tomorrow."),
    ('TC', 'TC #8', 'Closest match update: health and Gift Health',
     "Hi {name}, we have not found the right companion yet but we are still doing our best. Meanwhile, "
     "health matters as much as the journey: a Sahayak nurse at home and our preventive plans (Gift Health) "
     "keep an eye on your parents all year. {sahayak_link}"),
    ('TC', 'TC #10', 'Non-responsive lead, travel in 5 days: Gift Health',
     "Hi {name}, before your parents travel: our preventive health plans (Gift Health) and Sahayak home "
     "nurses look after them before and after the journey. {sahayak_link}"),
    ('TI', 'PF #3', 'Keep in touch after a fallout',
     "Hi {name}, {agent} from NRI Parent Service. Hope your parents are well! Whenever they plan the next "
     "visit, we would love to help with the cover, a companion or a nurse at home."),
]


# ---------------------------------------------------------------------------------------- the sales process
# The "Sales Process" tab's lead channels: (platform, activity, who owns it, where it stands).
# Edited on the Sales process page.
CHANNELS = [
    ('Facebook', 'Organic posting in groups', 'Sales', 'Ongoing'),
    ('Facebook', 'Commenting', 'Sales', 'Ongoing'),
    ('Instagram', 'Commenting', 'Sales', 'Ongoing'),
    ('Instagram', 'Drop-ins', 'Marketing', 'Needs positioning'),
    ('Facebook', 'Drop-ins', 'Marketing', 'Needs work'),
    ('WhatsApp', 'WhatsApp blasts', 'US Sales', ''),
    ('Traditional', 'Event marketing', 'US Sales', ''),
    ('WhatsApp', 'WhatsApp community', 'Sales', 'Will engage soon'),
    ('Traditional', 'Store signage', 'US Sales', 'Needs work'),
    ('Google', 'Search ads', 'Digital marketing', 'Waiting on the insurance website'),
    ('Google', 'Display ads', '', ''),
    ('Google', 'SEO', '', 'On page / off page'),
    ('Websites', 'Featured ads', '', ''),
    ('Facebook', 'Meta paid marketing', '', ''),
    ('YouTube', 'Drop-ins', '', ''),
    ('YouTube', 'Ads', '', ''),
    ('TikTok', 'Drop-ins', '', ''),
    ('TikTok', 'Ads', '', ''),
    ('Instagram', 'Threads drop-ins', '', ''),
    ('LinkedIn', 'Marketing', '', ''),
    ('LinkedIn', 'Paid marketing', '', ''),
    ('Google', 'Newsletters', '', ''),
    ('Media', 'Print media and publications', '', ''),
    ('Media', 'Digital print media', '', ''),
    ('Traditional', 'Telugu associations', '', ''),
    ('Media', 'Webinars', '', ''),
    ('Media', 'Radio ads', '', ''),
    ('Media', 'Television ads', '', ''),
    ('Websites', 'Digital media and channels', '', ''),
    ('Traditional', 'Customer reference', '', ''),
    ('Media', 'Podcast', '', ''),
    ('X', 'Drop-ins', '', ''),
    ('X', 'Paid marketing', '', ''),
    ('WhatsApp', 'WhatsApp paid marketing', '', ''),
    ('Websites', 'Blog', 'Sales', 'SEO'),
    ('Websites', 'Travel companion websites', 'Sales', 'We need to bring a baseline'),
    ('App stores', 'App promotion', '', ''),
    ('Traditional', 'Customer engagement', 'Sales', 'Working, needs rigour'),
    ('Traditional', 'Indian event marketing', '', ''),
    ('Social media', 'Influencer marketing', '', ''),
    ('Telegram', 'Telegram groups', '', 'Needs account opening'),
]
