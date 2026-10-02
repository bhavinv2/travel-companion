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

TOPICS = [
    'Understanding how the service works',
    'Finding a companion for my parents',
    'Help posting my trip',
    'A question about an existing match',
    'Privacy and how my details are used',
    'Travel insurance',
    'Something else',
]

VIA = ['WhatsApp', 'Phone call', 'Email']

TIMES = ['Morning (9 - 12)', 'Afternoon (12 - 4)', 'Evening (4 - 8)', 'Any time']

ZONES = ['India (IST)', 'US Eastern', 'US Central', 'US Pacific', 'UK',
         'Canada Eastern', 'Australia Eastern', 'Gulf (GST)', 'Other']

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
        # an unusable number is kept as typed rather than dropped: it is optional, and somebody
        # reading the enquiry can still see what they meant
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
