"""The structured data on the travel-insurance page.

Search engines read this as a claim about the page. Two things go wrong quietly and cost real
ranking: saying something the page does not show, and saying the same thing twice under two
identities. Both are easy to reintroduce by pasting a second <script> block in, which is exactly
what these tests are here to stop.
"""
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import help_center  # noqa: E402


def graph(client, path='/travel-insurance'):
    html = client.get(path).data.decode()
    blocks = re.findall(r'application/ld\+json">(.*?)</script>', html, re.S)
    assert len(blocks) == 1, 'one block per page: %d found' % len(blocks)
    doc = json.loads(blocks[0])
    return {node['@type']: node for node in doc['@graph']}, html


def test_the_page_carries_exactly_one_block(client, db):
    """A second one means two Organizations with two identities, two WebPages for one URL and
    two FAQPages. That is not extra coverage; it is a page that cannot say who it belongs to."""
    nodes, _ = graph(client)
    assert set(nodes) == {'Organization', 'WebSite', 'WebPage', 'Service', 'FAQPage'}


def test_the_graph_is_joined_up(client, db):
    """@id references, not repeated copies. The Organization named here is the same entity every
    other page names, which is the whole point of giving it an identifier."""
    nodes, _ = graph(client)
    org_id = nodes['Organization']['@id']
    site_id = nodes['WebSite']['@id']

    assert nodes['WebSite']['publisher'] == {'@id': org_id}
    assert nodes['WebPage']['publisher'] == {'@id': org_id}
    assert nodes['WebPage']['isPartOf'] == {'@id': site_id}
    assert nodes['WebPage']['about'] == {'@id': nodes['Service']['@id']}
    assert nodes['Service']['provider'] == {'@id': org_id}


def test_the_company_is_identified_at_the_site_root(client, db):
    """Not under the app's prefix: in production the app is mounted at /travel-companions, and
    the company is not a subdirectory of itself."""
    nodes, _ = graph(client)
    assert nodes['Organization']['@id'].endswith('/#organization')
    assert '/travel-companions' not in nodes['Organization']['@id']
    assert nodes['Organization']['address']['addressCountry'] == 'US'
    assert nodes['Organization']['telephone']
    assert nodes['Organization']['email']


def test_the_page_says_what_the_schema_says_it_says(client, db):
    """The title and the meta description are built from the same strings as the WebPage node.
    Schema describing a different page from the one it sits on is what gets discounted."""
    nodes, html = graph(client)
    title = re.search(r'<title>(.*?)</title>', html, re.S).group(1)
    desc = re.search(r'name="description" content="(.*?)"', html, re.S).group(1)
    assert nodes['WebPage']['name'] == title
    assert nodes['WebPage']['description'] == desc


def test_the_url_has_one_spelling(client, db):
    """The canonical, with no trailing slash. A second spelling in the schema is a second
    address for one page, which is the thing the alias redirect exists to prevent."""
    nodes, html = graph(client)
    canonical = re.search(r'<link rel="canonical" href="([^"]+)"', html).group(1)
    assert nodes['WebPage']['url'] == canonical
    assert nodes['Service']['url'] == canonical
    assert not canonical.endswith('/')


# ---------------------------------------------------------------------------
# The questions
# ---------------------------------------------------------------------------

def test_the_questions_are_the_ones_the_page_renders(client, db):
    """Never a list of its own. This is the difference between structured data and a claim."""
    nodes, _ = graph(client)
    asked = [q['name'] for q in nodes['FAQPage']['mainEntity']]
    assert asked == [f['question'] for f in help_center.faqs('insurance')]


def test_an_edited_question_moves_in_both_places_at_once(client, db):
    help_center.save([{'key': 'travel_insurance', 'title': 'Travel insurance',
                       'icon': 'fa-shield-halved', 'blurb': 'Cover'}],
                     [{'id': 'q1', 'category': 'travel_insurance',
                       'question': 'Does NRI Parent Service provide support in Telugu?',
                       'answer': 'Yes, before and after purchase.'}],
                     site='insurance')
    nodes, html = graph(client)
    assert [q['name'] for q in nodes['FAQPage']['mainEntity']] == \
        ['Does NRI Parent Service provide support in Telugu?']
    assert 'Does NRI Parent Service provide support in Telugu?' in html


def test_no_questions_means_no_faq_node(client, db):
    """An empty FAQPage promises answers that are not there."""
    help_center.save([{'key': 'travel_insurance', 'title': 'Travel insurance',
                       'icon': 'fa-shield-halved', 'blurb': 'Cover'}], [], site='insurance')
    nodes, _ = graph(client)
    assert 'FAQPage' not in nodes


def test_nothing_claims_a_rating(client, db):
    """Reviews come from the approved queue; an average nobody earned is a manual penalty."""
    _, html = graph(client)
    assert 'aggregateRating' not in html
