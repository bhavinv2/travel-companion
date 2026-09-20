"""The other NRI Parent Service / Preventia360 properties, as listed in the group's own menu.

This app (Travel Companion) is one of them, so the same list drives the header dropdown and the
footer column. All of these live on other domains, so every link opens in a new tab.
"""

SERVICES = [
    ('Book a Sahayak', 'https://preventia360.com/book-a-sahayak/'),
    ('Fit2Fly', 'https://preventia360.com/fit2fly/'),
    ('Gift Health', 'https://preventia360.com/gift-health/'),
    ('Elder Care', 'https://preventia360.com/'),
    ('Travel Insurance', 'https://nriparentservice.com/travel-insurance/'),
    ]

# Our insurance partner: they price every quote and take the purchase, so we credit them
# wherever a quote is shown.
INSURANCE_PARTNER_NAME = 'Preventia360'
INSURANCE_PARTNER_URL = 'https://preventia360.brokersnexus.com/'
