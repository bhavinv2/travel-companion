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

# ---------------------------------------------------------------------------------------- pipelines
# (key, name, product, fallout reasons, stages)
# stage: (key, name, kind, on_reply, sla_hours, steps)
# step:  (code, title, channel, trigger, value, auto, body)
H = 'after_hours'
D = 'before_departure_days'
E = 'before_end_days'

PIPELINES = [
    ('ti-standard', 'Travel insurance', 'TI',
     ['Bought elsewhere', 'Price too high', 'Trip cancelled', 'Already insured', 'Not interested',
      'No response', 'Wrong number'],
     [
         ('cold', 'Cold lead', 'open', False, 24, [
             ('TI #1', 'Introduce yourself and ask for ages and dates', 'whatsapp', H, 0, True,
              "Hi {name}, this is {agent} from NRI Parent Service. You asked about travel insurance "
              "for your parents. Cover for parents travelling from India can be tricky with "
              "pre-existing conditions and medical limits, and that is exactly what we help with. "
              "Could you share their ages and travel dates? I will send you two options to compare."),
             ('CL #2', 'Call and ask for a good time to talk', 'call', H, 24, False,
              "Introduce yourself, say you are following up on their insurance enquiry, and ask "
              "when is a good time to go through the options."),
             ('CL #3', 'Third and last call', 'call', H, 72, False,
              "Last try. If there is still no answer, move the lead to fallout with the reason "
              "'No response'."),
         ]),
         ('prospect', 'Prospect', 'open', True, 48, [
             ('TI #2', 'Check in: did they decide?', 'whatsapp', H, 24, False,
              "Hi {name}, {agent} here. Did you get a chance to look at cover for your parents? "
              "Happy to answer any question, or to call if that is easier."),
             ('TI #3', 'Call with two options and the payment link', 'call', H, 48, False,
              "Call and walk them through at least two comparable plans with prices, explain what "
              "we add at no extra cost, and send the payment link."),
         ]),
         ('quoted', 'Quoted', 'open', False, 72, [
             ('TI #4', 'Send two quotes side by side', 'whatsapp', H, 0, False,
              "Hi {name}, here are two options for your parents' visit:\n\n"
              "1) [plan, cover, price]\n2) [plan, cover, price]\n\n"
              "Both can be bought online: {insurance_link}\n"
              "With us you also get local-language support for claims, a complimentary virtual "
              "doctor consultation while they are abroad, and travel companion help."),
         ]),
         ('pipeline', 'Pipeline', 'open', False, 120, [
             ('PI #1', 'Five-day follow-up', 'whatsapp', H, 120, False,
              "Hi {name}, {agent} here. Just checking in on your parents' cover. Did you make a "
              "decision? I can hold the quotes for you."),
             ('PI #2', 'Call: travel is close', 'call', D, 3, False,
              "Their travel is {days} days away. Call: we want them to enjoy the visit rather "
              "than worry about health; choose the best option together."),
             ('PI #4', 'Day of travel: hand to the US team', 'call', D, 0, False,
              "Departure day. Escalate to the US sales team for a last call."),
         ]),
         ('customer', 'Policy bought', 'won', False, None, [
             ('CE #1', 'Welcome to the family', 'whatsapp', H, 0, True,
              "Welcome to the NRI Parent Service family, {name}! We are here for anything during "
              "your parents' visit: claims, questions, or a doctor consultation. Save this number."),
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
         ('prospect_fallout', 'Prospect fallout', 'lost', False, None, []),
         ('pipeline_fallout', 'Pipeline fallout', 'lost', False, None, [
             ('PF #1', 'Five days later: still here for them', 'whatsapp', H, 120, False,
              "Hi {name}, just checking everything is OK with your parents' trip. If anything is "
              "needed, we are still here."),
         ]),
     ]),

    ('tc-companion', 'Travel companion', 'TC',
     ['Found a companion elsewhere', 'Trip cancelled', 'Travelled already', 'Not interested',
      'No response', 'Wrong number', 'Duplicate'],
     [
         ('posted', 'Posted', 'open', False, 48, [
             ('TC #1', 'Warm welcome, no selling', 'whatsapp', H, 0, True,
              "Hi {name}, this is {agent} from NRI Parent Service. We have your trip and we are "
              "looking out for a companion for you. You can follow your matches here: "
              "{companion_link}. We are here to make the journey smooth."),
             ('TC #4', 'Fifteen days out, no match yet', 'whatsapp', D, 15, False,
              "Hi {name}, we are still looking for the right companion and will keep at it. "
              "Meanwhile, have you sorted travel insurance? Parents' cover with pre-existing "
              "conditions is our speciality: {insurance_link}"),
             ('TC #5', 'Five days out: call a loyal lead', 'call', D, 5, False,
              "Call: we could not find a companion yet. Offer travel insurance and what makes ours "
              "different."),
         ]),
         ('in_touch', 'In touch', 'open', True, 72, [
             ('TC #3', 'Closest match update', 'whatsapp', H, 72, False,
              "Hi {name}, an update on your trip: we are working on the closest matches for your "
              "route and dates. Nothing for you to do yet."),
         ]),
         ('matched', 'Matched', 'open', False, 48, [
             ('TC #2', 'Hooray! Then insurance, briefly', 'whatsapp', H, 0, False,
              "Hooray {name}, you have a companion! One more thing for a worry-free trip: travel "
              "insurance built for parents, with a complimentary virtual doctor consultation. "
              "{insurance_link}"),
         ]),
         ('connected', 'Connected', 'won', False, None, [
             ('TC #7', 'Gift Health and Sahayak, gently', 'whatsapp', H, 48, False,
              "Hi {name}, glad the companion worked out. When your parents are home, a Sahayak "
              "nurse can take care of check-ups and appointments: {sahayak_link}"),
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
         ]),
         ('resolved', 'Resolved', 'won', False, None, []),
         ('closed', 'Closed', 'lost', False, None, []),
     ]),
]

# which pipeline a product's leads start in when their source does not name one
PRODUCT_PIPELINE = {'TI': 'ti-standard', 'TC': 'tc-companion', 'SH': 'sahayak-visit',
                    'GH': 'general', 'VC': 'general', 'GEN': 'general'}

# ---------------------------------------------------------------------------------------- sources
# (key, name, kind, product, pipeline key, pages, status)
SOURCES = [
    ('tc-trip-post', 'TC: trip posted on the site', 'form', 'TC', 'tc-companion', ['/'], 'live'),
    ('tc-cs-post', 'TC: post added by CS (Facebook groups, WhatsApp)', 'manual', 'TC', 'tc-companion',
     ['/cs/posts/new'], 'live'),
    ('tc-import', 'TC: Excel import and scraper', 'import', 'TC', 'tc-companion', ['/cs/import'], 'live'),
    ('ti-quote', 'TI: quote request', 'form', 'TI', 'ti-standard', ['/travel-insurance'], 'live'),
    ('ti-expert', 'TI: expert form and consultation pop-up', 'popup', 'TI', 'ti-standard',
     ['/travel-insurance'], 'live'),
    ('ti-support', 'TI: support form', 'form', 'TI', 'general', ['/travel-insurance'], 'live'),
    ('sh-booking', 'Sahayak: visit booking', 'form', 'SH', 'sahayak-visit', ['/sahayak'], 'live'),
    ('sh-apply', 'Sahayak: nurse application', 'form', 'SH', 'nurse-recruitment', ['/sahayak'], 'live'),
    ('contact-companion', 'Contact us: travel companion', 'form', 'TC', 'general', ['/contact-us'], 'live'),
    ('contact-insurance', 'Contact us: insurance', 'form', 'TI', 'ti-standard', ['/contact-us'], 'live'),
    ('contact-sahayak', 'Contact us: Sahayak', 'form', 'SH', 'general', ['/contact-us'], 'live'),
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
