"""Site-wide analytics and tag manager config — the tags that belong on every page, not just
the travel-insurance one. See app/services/ads.py for the per-page Google Ads conversion
tracking (quote / popup_lead / whatsapp / expert_form) that stays separate from this: those
four events are specific to the travel-insurance page, these tags are not.

IDs live here rather than inline in the templates for the same reason as ads.py: rotating one,
or turning the whole thing off, should be a config change, not a rebuild and a deploy. None of
these are secrets -- a measurement ID is public the moment any page using it renders.

When it does NOT load, which matters more than when it does:

  * tests -> never, or the suite reports visits
  * localhost -> never. Development traffic in these reports is noise nobody asked for, and on
    the Ads side it inflates the number somebody is about to make a spending decision on (see
    app/services/ads.py for the fuller version of this argument).

google_site_verification() is deliberately NOT gated the same way: Search Console checks the
live production domain, so there is nothing to protect by hiding the tag in dev, and hiding it
risks someone "fixing" a blank-looking page by deleting it.
"""
import os

from flask import current_app, request

DEFAULT_GA4_ID = 'G-NPHSR9PNTC'
DEFAULT_GTM_ID = 'GTM-KGHBGZGM'
DEFAULT_SITE_VERIFICATION = 'WzvybcLxnJKDG6UvLhtOCjOOJLR86bnoWng1yR_qxW0'
# A second Ads account tracked site-wide. Distinct from ads.DEFAULT_ID, which is the
# per-conversion-event account used only on the travel-insurance page.
DEFAULT_ADS2_ID = 'AW-18413942725'

# Hosts that are somebody working on the site, not a real visitor.
LOCAL_HOSTS = ('localhost', '127.0.0.1', '0.0.0.0', '[::1]')


def enabled():
    """Whether this request should carry the site-wide tags at all."""
    if current_app.config.get('TESTING'):
        return False
    host = (request.host or '').split(':')[0].lower()
    return host not in LOCAL_HOSTS


def ga4_id():
    return (os.environ.get('GA4_ID', DEFAULT_GA4_ID) or '').strip()


def gtm_id():
    return (os.environ.get('GTM_ID', DEFAULT_GTM_ID) or '').strip()


def ads2_id():
    return (os.environ.get('GOOGLE_ADS2_ID', DEFAULT_ADS2_ID) or '').strip()


def site_verification():
    return (os.environ.get('GOOGLE_SITE_VERIFICATION', DEFAULT_SITE_VERIFICATION) or '').strip()
