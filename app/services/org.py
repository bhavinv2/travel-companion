"""Who this business is, in one place, for the structured data that says so.

Search engines read an Organization node off several pages and treat it as one entity, so the
name, address, phone and e-mail have to be identical everywhere they appear. They were about to
be pasted into a page template, which is how a second spelling of the address ends up on the
next page somebody adds.

These are claims about a real company -- a street address and a phone number that has to ring --
so they are configuration, not code: an environment variable changes any of them without a
deploy, and nothing here is invented. Clearing ORG_STREET drops the postal address from the
graph entirely rather than publishing half of one.
"""
import os
from urllib.parse import urlparse

from flask import current_app


def _env(name, default=''):
    return (os.environ.get(name, default) or '').strip()


def identity():
    """The @id the whole graph hangs off. One entity, one identifier, every page.

    The site ROOT, not SITE_URL as configured: in production that carries the app's /travel-
    companions prefix, and the company is not a subdirectory of itself. Scheme and host only, so
    the identifier stays the same whichever part of the site emits it.
    """
    configured = (current_app.config.get('SITE_URL', '') or '').rstrip('/')
    parsed = urlparse(configured)
    site = ('%s://%s' % (parsed.scheme, parsed.netloc)) if parsed.netloc else configured
    return {
        'site': site,
        'org_id': site + '/#organization',
        'website_id': site + '/#website',
    }


def address():
    """The head office, as schema.org wants it.

    Read from services/offices, which is also what the contact page prints -- so the address a
    search engine is told and the address a visitor reads cannot drift apart.

    All of it or none of it: a PostalAddress missing its street or its country is worse than no
    address, because it still claims to be one.
    """
    from app.services import offices
    hq = offices.headquarters()
    if not hq:
        return None
    parts = {
        'streetAddress': hq['street'],
        'addressLocality': _env('ORG_CITY', 'Ann Arbor'),
        'addressRegion': _env('ORG_REGION', 'Michigan'),
        'postalCode': _env('ORG_POSTCODE', '48108'),
        'addressCountry': _env('ORG_COUNTRY', 'US'),
    }
    if not all(parts.values()):
        return None
    return dict({'@type': 'PostalAddress'}, **parts)


def organization(phones=()):
    """The Organization node, ready to drop into a @graph.

    `phones` are the support lines staff have published on the page; they become contactPoints so
    a caller can pick the team in their own country. The company's own telephone is separate and
    comes from config -- it is the number on the letterhead, not a support rota.
    """
    ids = identity()
    node = {
        '@type': 'Organization',
        '@id': ids['org_id'],
        'name': _env('ORG_NAME', 'NRI Parent Service'),
        'url': ids['site'] + '/',
        'description': _env('ORG_DESCRIPTION',
                            'NRI Parent Service supports NRI families with parent care, travel '
                            'support, travel insurance guidance and related services.'),
    }
    # The address on the letterhead, which is not the support desk: SUPPORT_EMAIL is where
    # replies come from, this is where somebody writes to the company.
    email = _env('ORG_EMAIL', 'info@nriparentservice.com')
    if email:
        node['email'] = email
    telephone = _env('ORG_TELEPHONE', '+91-8019111360')
    if telephone:
        node['telephone'] = telephone
    postal = address()
    if postal:
        node['address'] = postal
    if phones:
        node['contactPoint'] = [{
            '@type': 'ContactPoint',
            'contactType': 'customer service',
            'telephone': '+' + p['digits'],
            'areaServed': 'IN' if p['label'] == 'India' else 'US',
            'availableLanguage': ['en', 'hi', 'te'],
        } for p in phones]
    return node


def website():
    """The WebSite node every page's WebPage hangs off, so the pages read as one site."""
    ids = identity()
    return {
        '@type': 'WebSite',
        '@id': ids['website_id'],
        'url': ids['site'] + '/',
        'name': _env('ORG_NAME', 'NRI Parent Service'),
        'publisher': {'@id': ids['org_id']},
        'inLanguage': 'en-US',
    }
