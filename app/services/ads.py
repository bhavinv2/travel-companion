"""Google Ads conversion tracking for the travel-insurance page.

Four things on that page are worth money to whoever is buying the ads, and each has its own
conversion action in the Ads account:

    quote        somebody asked for a quote and got priced results back
    popup_lead   the welcome popup collected a lead
    expert_form  the "discuss your cover with an expert" form was completed
    whatsapp     somebody opened WhatsApp from the page

The IDs live here rather than in the bundle so that changing one, or turning the whole thing off,
is a config change instead of a rebuild and a deploy. They are not secrets -- a conversion label
is public the moment the page renders -- so they ship as defaults and an environment variable
overrides them.

When it does NOT load, which matters more than when it does:

  * no GOOGLE_ADS_ID -> nothing at all, so a fork or a staging copy is silent by default
  * tests -> never, or the suite reports conversions
  * localhost -> never. Development traffic in a conversion report is worse than no report: it
    inflates exactly the number somebody is about to make a spending decision on.
"""
import os

from flask import current_app, request

# The Ads account. Everything else here is meaningless without it, and unsetting it is the
# documented way to switch tracking off.
DEFAULT_ID = 'AW-18430711486'

# conversion action -> the label Google generated for it. Sent as "<account>/<label>".
DEFAULT_LABELS = {
    'quote': 'l4geCNSpvokdEL6tudRE',
    'popup_lead': 'XhR4COzM0YkdEL6tudRE',
    'whatsapp': 'rPgKCLOM04kdEL6tudRE',
    'expert_form': '11uuCLyj0YkdEL6tudRE',
}

# Hosts that are somebody working on the page, not somebody who might buy a policy.
LOCAL_HOSTS = ('localhost', '127.0.0.1', '0.0.0.0', '[::1]')


def account_id():
    """The Ads account to load the tag for, or '' to load nothing."""
    return (os.environ.get('GOOGLE_ADS_ID', DEFAULT_ID) or '').strip()


def _label(action, default):
    return (os.environ.get('GOOGLE_ADS_LABEL_%s' % action.upper(), default) or '').strip()


def enabled():
    """Whether this request should carry the tag at all."""
    if current_app.config.get('TESTING'):
        return False
    if not account_id():
        return False
    host = (request.host or '').split(':')[0].lower()
    return host not in LOCAL_HOSTS


def conversions():
    """{action: 'AW-x/label'} for the page to fire, or {} when tracking is off.

    Already joined, because the page should not have to know how Google spells this and because a
    half-built id is the kind of thing that fails silently in an ad account for a month.
    """
    if not enabled():
        return {}
    acct = account_id()
    out = {}
    for action, default in DEFAULT_LABELS.items():
        label = _label(action, default)
        if label:
            out[action] = '%s/%s' % (acct, label)
    return out
