"""Admin-managed content for the travel-insurance landing page.

Stored as one JSON blob in app_settings, the same way options.py, messages.py and
help_center.py keep admin-editable content -- an edit shows on the public page within the
settings cache window, with no migration and no deploy.

Shape:
    {'price_from':    'from $1.20 a day ...',
     'assurances':    ['Policy documents by e-mail in minutes', ...],
     'support_email': '', 'availability': ''}

Everything here starts EMPTY and its section simply does not render until somebody fills it in.
These are claims about what the business actually offers -- a made-up price or an invented refund
window on an insurance page is worse than no line at all.

What used to be here and is not any more:

  * testimonials. A list staff typed, seeded with three invented customers. Reviews are ordinary
    Feedback rows now, written by people who used the service and published once an admin
    approves them -- the same queue, and the same standard of proof, as every other review.
  * the FAQ fallback. Ten answers shown when nothing had been filed under the category, which
    meant the page could display text that appeared on no screen anybody could edit. They are
    shipped defaults in help_center now, where the admin screen lists them.
"""
from app.services import settings

SETTING_KEY = 'insurance_page'

# Short reassurance lines shown beside the quote button ("free look period", "no medical exam").
# Suggestions for the admin screen only -- nothing here is published until it is saved, because
# only the business knows which of them are true of its plans.
ASSURANCE_SUGGESTIONS = [
    'Policy documents by e-mail within minutes',
    'Free look period — cancel within 10 days',
    'No medical exam for most plans',
    'Buy online, no paperwork',
    'Claims guidance in your time zone',
]
MAX_ASSURANCES = 4


def _blob():
    return settings.get_setting(SETTING_KEY, {}) or {}


def price_from():
    """The "from ..." line under the hero CTA. Empty until an admin sets a real number."""
    return (_blob().get('price_from') or '').strip()


def assurances():
    """Short reassurance lines shown with the quote CTA. Empty by default, by design."""
    return [a for a in (_blob().get('assurances') or []) if a]


def support_email():
    """The address shown on the page. Empty means "use the site-wide SUPPORT_EMAIL", so an admin
    only has to set this when insurance should answer somewhere else."""
    return (_blob().get('support_email') or '').strip()


def availability():
    """The "Availability" line in the contact block, e.g. "Across time zones, every day". Empty
    falls back to what the page shipped with -- it is a claim about staffing, so the business
    says it, not us."""
    return (_blob().get('availability') or '').strip()


def save_page(price_from_text, assurance_rows, actor=None, support_email_text=None,
              availability_text=None):
    blob = _blob()
    blob['price_from'] = (price_from_text or '').strip()[:120]
    blob['assurances'] = [(a or '').strip()[:60] for a in assurance_rows if (a or '').strip()][:MAX_ASSURANCES]
    if support_email_text is not None:
        blob['support_email'] = (support_email_text or '').strip()[:255]
    if availability_text is not None:
        blob['availability'] = (availability_text or '').strip()[:80]
    settings.set_setting(SETTING_KEY, blob, actor)
    settings.clear_cache()
    return blob
