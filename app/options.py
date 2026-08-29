"""Shared option lists used by the public post form, the CS form and the claim page."""

ON_BEHALF_OF = [
    ('myself', 'Myself'), ('loved_one', 'Loved Ones'), ('mother', 'Mother'), ('father', 'Father'),
    ('parents', 'Parents'), ('sister', 'Sister'), ('brother', 'Brother'), ('son', 'Son'),
    ('daughter', 'Daughter'), ('friend', 'Friend'), ('other', 'Other'),
]

CONNECT_ME_TO = [
    ('senior_citizens', 'Senior Citizens'), ('travelling_families', 'Travelling Families'),
    ('solo_male', 'Solo (Male)'), ('solo_female', 'Solo (Female)'),
    ('student', 'Student Travellers'), ('tourist', 'Tourists'),
    ('business', 'Business Travel'), ('religious', 'Religious Travel'),
]

TRAVELLER_NEEDS = [
    ('wheelchair', 'Wheelchair Assistance'), ('toddler', 'Travelling with Toddler'),
    ('first_time', 'First-time Flyer'), ('immigration', 'Help at Immigration / Customs'),
    ('connections', 'Help with Connecting Flights'), ('language_barrier', 'Language Barrier'),
    ('physically_challenged', 'Physically Challenged'), ('mentally_challenged', 'Mentally Challenged'),
    ('medicines', 'Need Medicines / Medical Support'), ('documents', 'Need Documents / Forms Help'),
]

LANGUAGES = [
    'English', 'Hindi', 'Gujarati', 'Tamil', 'Telugu', 'Kannada', 'Malayalam', 'Marathi',
    'Punjabi', 'Bengali', 'Urdu', 'Sindhi', 'Nepali', 'Sinhala',
]

CONNECT_ME_TO_LABELS = dict(CONNECT_ME_TO)
TRAVELLER_NEEDS_LABELS = dict(TRAVELLER_NEEDS)
ON_BEHALF_OF_LABELS = dict(ON_BEHALF_OF)
