"""The one definition of what "contact us" asks for.

There were two forms. The popup asked for a topic, a preferred contact method, a language, a time
and a time zone, and packed them into the message text in JavaScript before posting. The /contact
page asked for a name, an e-mail, a phone number and a message, and nothing else -- so the same
enquiry arrived in the CS console looking completely different depending on which one somebody
happened to find, and an agent reading the page version had no idea when or how to call back.

One list of fields, one way of composing the message, used by both. The extras ride in the
message body rather than in columns of their own: they are things to read before picking up the
phone, not things anything queries or filters on, and a column nobody filters on is a migration
spent on nothing.
"""

# Which service it is about -- not which question it is.
#
# This was seven options, most of them tasks within one service ("Help posting my trip", "A
# question about an existing match", "Privacy and how my details are used"). A visitor who
# wants insurance had to read past four companion questions to find it, and the one thing the
# list never said was which part of the business to send it to. Five, by service, with one row
# for people who already have something open and one for everything else.
#
# Each maps to a bucket in models.CONTACT_TOPICS, so what somebody picks now files the enquiry
# in the CS inbox instead of only appearing as a line of text in the message body.
TOPICS = [
    'Travel insurance',
    'Travel companion',
    'Sahayak - a health professional at home',
    'An existing booking or request',
    'Something else',
]

# What a form opens on. Named rather than "whatever is first", so the order of the list and the
# thing most people are writing in about stay two separate decisions.
DEFAULT_TOPIC = 'Travel insurance'

# label -> models.CONTACT_TOPICS. Anything not named here is a general enquiry, which is also
# what an unanswered dropdown means.
TOPIC_ROUTES = {
    'Travel companion': 'companion',
    'Travel insurance': 'insurance',
    'Sahayak - a health professional at home': 'sahayak',
}
DEFAULT_ROUTE = 'general'


def route(topic, default=DEFAULT_ROUTE):
    """The inbox bucket for a chosen topic.

    "An existing booking or request" still lands in general: it spans all three products, so
    the only honest answer is the inbox that is not filtered by one. Everything else routes to
    the product it names, which is what puts it on that product's screen in the console.
    """
    return TOPIC_ROUTES.get((topic or '').strip(), default)

VIA = ['WhatsApp', 'Phone call', 'Email']

TIMES = ['Morning (9 - 12)', 'Afternoon (12 - 4)', 'Evening (4 - 8)', 'Any time']

ZONES = ['India (IST)', 'US Eastern', 'US Central', 'US Pacific', 'UK',
         'Canada Eastern', 'Australia Eastern', 'Gulf (GST)', 'Other']

# The same country the phone field opens on. A form that offers +1 and then assumes the caller
# is on IST is asking them to correct it twice.
DEFAULT_ZONE = 'US Eastern'

# What the visitor typed, and what they chose. Only the first four are required; the rest make a
# call-back possible instead of a guess.
TEXT_FIELDS = ('name', 'email', 'phone', 'message')
CHOICE_FIELDS = ('topic', 'via', 'language', 'time', 'zone')

_LABELS = {'topic': 'Topic', 'via': 'Preferred contact', 'language': 'Preferred language',
           'time': 'Best time', 'zone': 'Time zone'}


def clean(src):
    """Everything both forms send, trimmed. Unknown choices are dropped rather than stored: they
    are rendered from the lists above, so anything else was not chosen from the form.

    The phone number is normalised with the country the visitor picked, so what reaches CS is
    dialable from anywhere rather than nine digits with no code.
    """
    from app.services import phone as phone_svc

    out = {k: (src.get(k) or '').strip() for k in TEXT_FIELDS}
    out['phone_cc'] = (src.get('phone_cc') or phone_svc.DEFAULT_ISO).strip().upper()
    if out['phone']:
        e164, error = phone_svc.normalise(out['phone'], out['phone_cc'])
        # Kept as typed when unusable, so a redrawn form shows what they wrote -- but the error
        # travels with it, and main._validate_contact refuses the enquiry until it is fixed or
        # cleared. It used to be stored as typed with nobody told, which is how numbers with no
        # country code reached the inbox.
        out['phone'] = e164 or out['phone']
        out['phone_error'] = error
    allowed = {'topic': TOPICS, 'via': VIA, 'time': TIMES, 'zone': ZONES}
    for key in CHOICE_FIELDS:
        value = (src.get(key) or '').strip()
        if key in allowed and value not in allowed[key]:
            value = ''
        out[key] = value[:80]
    return out


def compose(fields):
    """The message as CS reads it: the preferences first, then what they actually wrote.

    Done here rather than in the browser so the two forms produce the same thing. The popup used
    to build this string in JavaScript, which is why the page version never had it.
    """
    lines = ['%s: %s' % (_LABELS[k], fields[k]) for k in CHOICE_FIELDS if fields.get(k)]
    body = (fields.get('message') or '').strip()
    return ('\n'.join(lines) + '\n\n' + body).strip() if lines else body
