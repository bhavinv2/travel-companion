"""Promotion dashboards: the built-in Overview and the ones a Marketing head designs (2026-10-29).

    OVERVIEW                  the Overview's boxes (the first tab of the Promotion dashboard, for everybody)
    BOARDS                    the built-in tabs: the Overview, Google Analytics in full, Google search in full and
                              our own visitors (2026-11-01)
    SUGGESTIONS               ready-made boxes the designer offers ("Add a ready-made box")
    tabs(user)                the dashboards this person sees: the built-in ones, then every published one for them
    boxes_for(dash, draft, board)   a dashboard's cleaned boxes (`dash` None: the built-in `board`)
    render(boxes, period, user)   each box with its numbers -- or `async` for website boxes, which the page's script
                              asks for (marketing.box) so one slow answer from Google does not hold the page
    create / save / publish / unpublish / duplicate / delete / move   the designer's buttons
    can_design(user)          may design and publish (the `mkt_design` page)

A dashboard keeps two copies of its boxes: `draft`, what the designer is changing, and `published`, what people see.
Publish copies one onto the other, so a half-made change is never on anyone's screen.
"""
from collections import OrderedDict
from datetime import datetime

from app import db
from app.models import MktDashboard
from app.services import mkt_engine as eng

NAME_MAX = 80
MAX_BOXES = 70
MAX_DASHBOARDS = 30
AUDIENCES = {'all': 'Everyone who has the Promotion dashboard', 'designers': 'Only the people who design dashboards'}


class DashError(ValueError):
    pass


def _m(source, measure='count', filters=None, date=None, label=''):
    out = {'source': source, 'measure': measure, 'filters': filters or {}, 'label': label}
    if date:
        out['date'] = date
    return out


def _box(i, title, chart, x, y, w, h, metrics=(), group='', split='', rng='page', top=10, colour='brand', note='',
         empty='', compare=True, body='', of=None):
    out = {'id': 'o%d' % i, 'title': title, 'chart': chart, 'x': x, 'y': y, 'w': w, 'h': h,
           'metrics': list(metrics), 'group': group, 'split': split, 'range': rng, 'top': top, 'colour': colour,
           'note': note, 'empty': empty, 'compare': compare, 'body': body}
    if of:
        out['of'] = of                  # a 'retention' box: whose visitors
    return out


FROM_INDIA = {'direction': ['India → abroad']}
TO_INDIA = {'direction': ['Abroad → India']}

# The Overview. Rows are 64px; a big number is 2 rows, a chart 5.
OVERVIEW = [
    _box(1, 'On the website right now', 'live', 0, 0, 4, 4, [_m('website_now', 'activeUsers')], group='device',
         note='People on any of our pages in the last 30 minutes, from Google Analytics.'),
    _box(2, 'Website visitors', 'number', 4, 0, 2, 2, [_m('website', 'activeUsers')], group='auto'),
    _box(3, 'Website visits', 'number', 6, 0, 2, 2, [_m('website', 'sessions')], group='auto'),
    _box(4, 'Sign-ups', 'number', 8, 0, 2, 2, [_m('signups')], group='auto'),
    _box(5, 'Enquiries received', 'number', 10, 0, 2, 2, [_m('enquiries')], group='auto',
         note='Travel Companion, Travel Insurance, Sahayak and the rest, from every contact form on the site.'),
    _box(6, 'Trips posted', 'number', 4, 2, 2, 2, [_m('trips')], group='auto', note='Travel Companion'),
    _box(7, 'Insurance quote requests', 'number', 6, 2, 2, 2, [_m('insurance')], group='auto',
         note='Travel Insurance'),
    _box(8, 'Sahayak bookings', 'number', 8, 2, 2, 2, [_m('sahayak')], group='auto', note='Sahayak'),
    _box(9, 'New leads', 'number', 10, 2, 2, 2, [_m('leads')], group='auto', note='All products, staff only.'),
    _box(10, 'Our growth', 'line', 0, 4, 8, 5,
         [_m('enquiries', label='Enquiries'), _m('trips', label='Trips posted'),
          _m('insurance', label='Insurance quotes'), _m('sahayak', label='Sahayak bookings'),
          _m('signups', label='Sign-ups')], group='auto'),
    _box(11, 'Trips by direction', 'donut', 8, 4, 4, 5, [_m('trips')], group='direction',
         note='Where a trip starts and ends: India to abroad, abroad to India, or neither.'),
    _box(12, 'From India: where they fly to', 'hbar', 0, 9, 4, 5, [_m('trips', filters=FROM_INDIA)],
         group='dest_country', top=8, colour='ocean', empty='No trips from India in these dates.'),
    _box(13, 'To India: where they fly from', 'hbar', 4, 9, 4, 5, [_m('trips', filters=TO_INDIA)],
         group='origin_country', top=8, colour='sunset', empty='No trips to India in these dates.'),
    _box(14, 'Who flies when (next 12 months)', 'stacked', 8, 9, 4, 5, [_m('trips', date='travel')],
         group='month', split='direction', rng='next_365', compare=False),
    _box(15, 'Most requested routes', 'hbar', 0, 14, 6, 5, [_m('trips')], group='route', top=8,
         empty='No trips with both cities recorded yet.'),
    _box(16, 'Country to country', 'hbar', 6, 14, 6, 5, [_m('trips')], group='country_route', top=8,
         colour='forest', empty='No trips with both countries known yet.'),
    _box(17, 'Insurance destinations asked about', 'hbar', 0, 19, 4, 5, [_m('insurance')], group='dest', top=8,
         colour='berry', empty='No quote requests with a destination yet.'),
    _box(18, 'Insurance plans asked for', 'donut', 4, 19, 4, 5, [_m('insurance')], group='plan'),
    _box(19, "Insured travellers' ages", 'bar', 8, 19, 4, 5, [_m('insurance', 'travellers')], group='ages',
         colour='berry'),
    _box(20, 'How visitors find us', 'donut', 0, 24, 4, 5, [_m('website', 'sessions')], group='channel'),
    _box(21, 'Visitors by country', 'hbar', 4, 24, 4, 5, [_m('website', 'activeUsers')], group='country', top=8,
         colour='ocean'),
    _box(22, 'Devices', 'donut', 8, 24, 4, 5, [_m('website', 'activeUsers')], group='device'),
    _box(23, 'Visitors over time', 'area', 0, 29, 6, 5, [_m('website', 'activeUsers', label='Visitors'),
                                                       _m('website', 'newUsers', label='New visitors')],
         group='auto'),
    _box(24, 'Top landing pages', 'table', 6, 29, 6, 5, [_m('website', 'sessions', label='Visits'),
                                                       _m('website', 'activeUsers', label='Visitors')],
         group='landing', top=10),
    _box(30, 'Clicks from Google search', 'number', 0, 34, 3, 2, [_m('search', 'clicks')], group='auto',
         colour='forest', note='From Google Search Console: a click on one of our pages in Google results.'),
    _box(31, 'Times shown in Google', 'number', 3, 34, 3, 2, [_m('search', 'impressions')], group='auto',
         colour='forest'),
    _box(32, 'Click rate in Google', 'number', 6, 34, 3, 2, [_m('search', 'ctr')], group='auto', colour='forest'),
    _box(33, 'Average position in Google', 'number', 9, 34, 3, 2, [_m('search', 'position')], group='auto',
         colour='forest', note='1 is the top of the first page. Lower is better.'),
    _box(34, 'Clicks from Google over time', 'area', 0, 36, 6, 5, [_m('search', 'clicks', label='Clicks')],
         group='auto', colour='forest'),
    _box(35, 'What people search for', 'table', 6, 36, 6, 5,
         [_m('search', 'clicks', label='Clicks'), _m('search', 'impressions', label='Shown'),
          _m('search', 'position', label='Position')], group='query', top=10),
    _box(36, 'Pages people find in Google', 'table', 0, 41, 6, 5,
         [_m('search', 'clicks', label='Clicks'), _m('search', 'impressions', label='Shown')], group='page', top=10),
    _box(37, 'Google search by country', 'hbar', 6, 41, 6, 5, [_m('search', 'clicks')], group='country', top=8,
         colour='forest'),
    _box(25, 'Enquiries by service', 'table', 0, 46, 4, 5, [_m('enquiries')], group='topic', top=0),
    _box(26, 'Reviews by service', 'table', 4, 46, 4, 5, [_m('reviews', label='Published'),
                                                        _m('reviews', 'rating', label='Average rating')],
         group='product', top=0, rng='all', compare=False),
    _box(27, 'How people rate us', 'hbar', 8, 46, 4, 5, [_m('reviews')], group='stars', top=0, rng='all',
         colour='sunset', compare=False, empty='No published reviews yet.'),
    _box(28, 'Published reviews you can quote', 'quotes', 0, 51, 8, 6, top=6),
    _box(29, 'Pages to send people to', 'links', 8, 51, 4, 6),
]

# "Add a ready-made box": a starting point for each kind of question, which the designer then changes
SUGGESTIONS = [
    ('Travel', 'India → abroad, abroad → India', _box(0, 'Trips by direction', 'donut', 0, 0, 4, 5, [_m('trips')],
                                                      group='direction')),
    ('Travel', 'Trips from India, by month', _box(0, 'Trips from India, by month', 'bar', 0, 0, 6, 5,
                                                 [_m('trips', filters=FROM_INDIA)], group='month')),
    ('Travel', 'Trips to India, by month', _box(0, 'Trips to India, by month', 'bar', 0, 0, 6, 5,
                                               [_m('trips', filters=TO_INDIA)], group='month', colour='sunset')),
    ('Travel', 'Direction over time', _box(0, 'Trips by direction over time', 'stacked', 0, 0, 6, 5, [_m('trips')],
                                           group='auto', split='direction')),
    ('Travel', 'Countries people fly to from India', _box(0, 'From India to …', 'hbar', 0, 0, 4, 5,
                                                           [_m('trips', filters=FROM_INDIA)], group='dest_country')),
    ('Travel', 'Countries people fly to India from', _box(0, 'To India from …', 'hbar', 0, 0, 4, 5,
                                                          [_m('trips', filters=TO_INDIA)], group='origin_country')),
    ('Travel', 'Indian cities people leave from', _box(0, 'Indian cities people leave from', 'hbar', 0, 0, 4, 5,
                                                       [_m('trips', filters=FROM_INDIA)], group='origin_city')),
    ('Travel', 'Top routes', _box(0, 'Top routes', 'hbar', 0, 0, 6, 5, [_m('trips')], group='route')),
    ('Travel', 'Upcoming flights by direction', _box(0, 'Flights in the next 90 days', 'stacked', 0, 0, 6, 5,
                                                     [_m('flights', date='travel')], group='week', split='direction',
                                                     rng='next_90', compare=False)),
    ('Travel', 'Airlines', _box(0, 'Airlines people fly', 'hbar', 0, 0, 4, 5, [_m('trips')], group='airline')),
    ('Travel', 'Help travellers need', _box(0, 'Help travellers need', 'hbar', 0, 0, 4, 5, [_m('trips')],
                                            group='needs')),
    ('Travel', 'Languages travellers speak', _box(0, 'Languages travellers speak', 'pie', 0, 0, 4, 5,
                                                  [_m('trips')], group='languages')),
    ('Travel', 'Travellers by age', _box(0, 'Travellers by age', 'bar', 0, 0, 4, 5, [_m('trips', 'travellers')],
                                         group='age')),
    ('Insurance', 'Quote requests by plan', _box(0, 'Quote requests by plan', 'donut', 0, 0, 4, 5,
                                                 [_m('insurance')], group='plan')),
    ('Insurance', 'Destinations asked about', _box(0, 'Insurance destinations', 'hbar', 0, 0, 4, 5,
                                                   [_m('insurance')], group='dest')),
    ('Insurance', 'Trip lengths', _box(0, 'How long they travel for', 'bar', 0, 0, 4, 5, [_m('insurance')],
                                       group='length')),
    ('Website', 'Visitors (big number)', _box(0, 'Website visitors', 'number', 0, 0, 3, 2,
                                              [_m('website', 'activeUsers')], group='auto')),
    ('Website', 'Live visitors', _box(0, 'On the website right now', 'live', 0, 0, 4, 4,
                                      [_m('website_now', 'activeUsers')], group='device')),
    ('Website', 'Visitors over time', _box(0, 'Visitors over time', 'area', 0, 0, 6, 5,
                                           [_m('website', 'activeUsers')], group='auto')),
    ('Website', 'Channels', _box(0, 'How visitors find us', 'donut', 0, 0, 4, 5, [_m('website', 'sessions')],
                                 group='channel')),
    ('Website', 'Countries', _box(0, 'Visitors by country', 'hbar', 0, 0, 4, 5, [_m('website', 'activeUsers')],
                                  group='country')),
    ('Website', 'Indian cities', _box(0, 'Visitors from Indian cities', 'hbar', 0, 0, 4, 5,
                                      [_m('website', 'activeUsers', filters={'country': ['India']})], group='city')),
    ('Website', 'Landing pages', _box(0, 'Top landing pages', 'table', 0, 0, 6, 5, [_m('website', 'sessions')],
                                      group='landing')),
    ('Website', 'Campaigns', _box(0, 'Visits by campaign', 'hbar', 0, 0, 6, 5, [_m('website', 'sessions')],
                                  group='campaign')),
    ('Website', 'Conversions by channel', _box(0, 'Key events by channel', 'bar', 0, 0, 6, 5,
                                               [_m('website', 'keyEvents')], group='channel')),
    ('Search', 'Words people search for', _box(0, 'What people search for', 'table', 0, 0, 6, 5,
                                               [_m('search', 'clicks', label='Clicks'),
                                                _m('search', 'impressions', label='Shown')], group='query')),
    ('Search', 'Pages found in Google', _box(0, 'Pages people find in Google', 'table', 0, 0, 6, 5,
                                             [_m('search', 'clicks')], group='page')),
    ('Search', 'Clicks from Google over time', _box(0, 'Clicks from Google', 'area', 0, 0, 6, 5,
                                                    [_m('search', 'clicks')], group='auto', colour='forest')),
    ('Search', 'Shown and clicked, by device', _box(0, 'Google search by device', 'bar', 0, 0, 4, 5,
                                                    [_m('search', 'impressions', label='Shown'),
                                                     _m('search', 'clicks', label='Clicks')], group='device')),
    ('Search', 'Average position (big number)', _box(0, 'Average position in Google', 'number', 0, 0, 3, 2,
                                                     [_m('search', 'position')], group='auto')),
    ('Search', 'Searches from India', _box(0, 'What people in India search for', 'table', 0, 0, 6, 5,
                                           [_m('search', 'clicks', filters={'country': ['India']})], group='query')),
    ('Website', 'Time engaged per visitor', _box(0, 'Time engaged per visitor', 'number', 0, 0, 3, 2,
                                                 [_m('website', 'avgEngagement')], group='auto')),
    ('Website', 'Pages: views, visitors, time', _box(0, 'Pages', 'table', 0, 0, 12, 7,
                                                     [_m('website', 'screenPageViews', label='Views'),
                                                      _m('website', 'activeUsers', label='Visitors'),
                                                      _m('website', 'avgEngagement', label='Time engaged')],
                                                     group='page', top=20)),
    ('Website', 'Source / medium', _box(0, 'Source / medium', 'table', 0, 0, 6, 6,
                                        [_m('website', 'sessions', label='Visits'),
                                         _m('website', 'keyEvents', label='Key events')], group='source_medium')),
    ('Website', 'Events', _box(0, 'Events', 'table', 0, 0, 6, 6, [_m('website', 'eventCount')], group='event')),
    ('Website', 'Age', _box(0, 'Age', 'bar', 0, 0, 4, 5, [_m('website', 'activeUsers')], group='age')),
    ('Website', 'Gender', _box(0, 'Gender', 'donut', 0, 0, 4, 5, [_m('website', 'activeUsers')], group='gender')),
    ('Website', 'Hour of the day', _box(0, 'Visits by hour of the day', 'bar', 0, 0, 6, 5,
                                        [_m('website', 'sessions')], group='hour', compare=False)),
    ('Website', 'Screen sizes', _box(0, 'Screen sizes', 'hbar', 0, 0, 4, 5, [_m('website', 'activeUsers')],
                                     group='screen')),
    ('Search', 'Nearly on the first page', _box(0, 'Nearly on the first page (11th to 20th)', 'table', 0, 0, 6, 6,
                                                [_m('search', 'impressions', label='Shown',
                                                    filters={'band': ['11th to 20th (second page)']}),
                                                 _m('search', 'position', label='Position',
                                                    filters={'band': ['11th to 20th (second page)']})],
                                                group='query')),
    ('Search', 'Where we come in Google', _box(0, 'Where we come in Google', 'bar', 0, 0, 6, 5,
                                               [_m('search', 'impressions')], group='band', top=0)),
    ('Search', 'Kind of search', _box(0, 'Kind of search', 'table', 0, 0, 6, 4, [_m('search', 'clicks')],
                                      group='type', top=0)),
    ('Search', "Pages in Google's index", _box(0, "Our pages in Google's index", 'indexing', 0, 0, 12, 8, top=12)),
    ('Search', 'Our sitemaps', _box(0, 'Our sitemaps in Google', 'sitemaps', 0, 0, 12, 4)),
    ('Visitors', 'On our websites now', _box(0, 'On our websites now', 'live', 0, 0, 4, 5, [_m('visitors_now')],
                                             group='country')),
    ('Visitors', 'Visitors one by one', _box(0, 'Who is on the site now, and lately', 'people', 0, 0, 8, 8, top=12)),
    ('Visitors', 'Who came back (ours)', _box(0, 'Who came back, week by week', 'retention', 0, 0, 12, 6, top=8,
                                              of='visitors')),
    ('Website', 'Who came back (Google)', _box(0, 'Who came back, week by week', 'retention', 0, 0, 12, 6, top=6,
                                               of='website')),
    ('Visitors', 'Visitors over time', _box(0, 'Our visitors', 'area', 0, 0, 6, 5,
                                            [_m('visitors', 'visitors', label='Visitors'),
                                             _m('visitors', 'visits', label='Visits')], group='auto')),
    ('Visitors', 'Countries', _box(0, 'Visitors by country', 'hbar', 0, 0, 4, 5, [_m('visitors', 'visitors')],
                                   group='country')),
    ('Visitors', 'Indian cities', _box(0, 'Visitors from Indian cities', 'hbar', 0, 0, 4, 5,
                                       [_m('visitors', 'visitors', filters={'country': ['India']})], group='city')),
    ('Visitors', 'How they found us', _box(0, 'How visitors found us', 'donut', 0, 0, 4, 5, [_m('visitors', 'visits')],
                                           group='source')),
    ('Visitors', 'Most read pages', _box(0, 'Most read pages', 'table', 0, 0, 6, 6,
                                         [_m('visitors', 'count', label='Opened'),
                                          _m('visitors', 'secs', label='Time on it')], group='page')),
    ('Visitors', 'Hour of the day', _box(0, 'Pages opened by hour (India time)', 'bar', 0, 0, 6, 5,
                                         [_m('visitors', 'count')], group='hour', compare=False)),
    ('Growth', 'Our growth', _box(0, 'Our growth', 'line', 0, 0, 8, 5,
                                  [_m('enquiries', label='Enquiries'), _m('trips', label='Trips posted'),
                                   _m('insurance', label='Insurance quotes'), _m('signups', label='Sign-ups')],
                                  group='auto')),
    ('Growth', 'Sign-ups (big number)', _box(0, 'Sign-ups', 'number', 0, 0, 3, 2, [_m('signups')], group='auto')),
    ('Growth', 'Enquiries by service', _box(0, 'Enquiries by service', 'bar', 0, 0, 4, 5, [_m('enquiries')],
                                            group='topic')),
    ('Sales', 'Leads by campaign', _box(0, 'Leads by campaign', 'hbar', 0, 0, 6, 5, [_m('leads')],
                                        group='campaign')),
    ('Sales', 'Leads by source', _box(0, 'Where leads come from', 'donut', 0, 0, 4, 5, [_m('leads')],
                                      group='source')),
    ('Sales', 'Won over time', _box(0, 'Leads and wins', 'line', 0, 0, 6, 5,
                                    [_m('leads', label='Leads'), _m('leads', 'won', label='Won')], group='auto')),
    ('Reviews', 'How people rate us', _box(0, 'How people rate us', 'hbar', 0, 0, 4, 5, [_m('reviews')],
                                           group='stars', rng='all')),
    ('Reviews', 'Reviews to quote', _box(0, 'Published reviews you can quote', 'quotes', 0, 0, 8, 6, top=6)),
    ('More', 'Words: a heading or a note', _box(0, '', 'text', 0, 0, 12, 1, body='A heading')),
    ('More', 'Pages to send people to', _box(0, 'Pages to send people to', 'links', 0, 0, 4, 6)),
]


# ================================================================================================ the built-in boards
# Besides the Overview, three dashboards everybody with the Promotion dashboard has, ready-made: Google Analytics in
# full, Google search in full, and our own visitors -- what one would otherwise go to Google for, box by box, here.

def _b(title, chart, w, h, metrics=(), at=None, **kw):
    """A box of a board laid out by _flow: `at` puts it at that column instead of after the one before."""
    b = _box(0, title, chart, 0, 0, w, h, metrics, **kw)
    if at is not None:
        b['_at'] = at
    return b


def _head(text):
    return _b('', 'text', 12, 1, body=text)


def _flow(prefix, rows):
    """Boxes laid out a row at a time, left to right, each row as tall as its tallest box (clean_boxes then lets a
    box rise into any space left above it)."""
    out, y, n = [], 0, 0
    for row in rows:
        x = 0
        for b in row:
            n += 1
            b = dict(b)
            x = b.pop('_at', x)
            out.append(dict(b, id='%s%d' % (prefix, n), x=x, y=y))
            x += b['w']
        y += max(b['h'] for b in row)
    return out


W, L, S, V, VN = 'website', 'website_now', 'search', 'visitors', 'visitors_now'


def _n(title, source, measure, w=2, colour='brand', **kw):
    return _b(title, 'number', w, 2, [_m(source, measure)], group='auto', colour=colour, **kw)


def _ms(source, *pairs, **kw):
    return [_m(source, measure, label=label, **kw) for measure, label in pairs]


SIGNALS = 'Google shows ages, gender and interests only with Google signals switched on, and only once enough people came.'
EVENT_EMPTY = 'None in these dates. Google Analytics records it with Enhanced measurement switched on.'

GOOGLE_FULL = _flow('g', [
    [_head('Right now')],
    [_b('On the website right now', 'live', 4, 4, [_m(L, 'activeUsers')], group='device'),
     _b('Pages being read now', 'hbar', 4, 4, [_m(L, 'activeUsers')], group='page', top=6),
     _b('Where they are now', 'hbar', 4, 4, [_m(L, 'activeUsers')], group='country', top=6)],
    [_head('Who came')],
    [_n('Visitors', W, 'activeUsers'), _n('New visitors', W, 'newUsers'), _n('Visits', W, 'sessions'),
     _n('Page views', W, 'screenPageViews'), _n('Time engaged per visitor', W, 'avgEngagement', colour='ocean'),
     _n('Engagement rate', W, 'engagementRate', colour='forest')],
    [_n('Bounce rate', W, 'bounceRate', colour='sunset'), _n('Pages per visit', W, 'screenPageViewsPerSession'),
     _n('Visits per visitor', W, 'sessionsPerUser'), _n('Key events', W, 'keyEvents', colour='berry'),
     _n('Events', W, 'eventCount'), _n('Scrolled to the end', W, 'scrolledUsers', colour='ocean')],
    [_b('Visitors, new visitors and visits', 'line', 8, 5,
        _ms(W, ('activeUsers', 'Visitors'), ('newUsers', 'New visitors'), ('sessions', 'Visits')), group='auto'),
     _b('New or returning', 'donut', 4, 5, [_m(W, 'activeUsers')], group='returning')],
    [_head('How they find us')],
    [_b('Visits by channel', 'table', 6, 6,
        _ms(W, ('sessions', 'Visits'), ('activeUsers', 'Visitors'), ('engagementRate', 'Engagement'),
            ('avgEngagement', 'Time engaged'), ('keyEvents', 'Key events')), group='channel', top=0),
     _b('Channels over time', 'stacked', 6, 6, [_m(W, 'sessions')], group='auto', split='channel', compare=False)],
    [_b('Source / medium', 'table', 6, 7,
        _ms(W, ('sessions', 'Visits'), ('activeUsers', 'Visitors'), ('newUsers', 'New'),
            ('engagementRate', 'Engagement'), ('keyEvents', 'Key events')), group='source_medium', top=20),
     _b('How new visitors first found us', 'hbar', 6, 7, [_m(W, 'newUsers')], group='first_channel', top=0,
        compare=False)],
    [_b('Campaigns', 'table', 6, 5, _ms(W, ('sessions', 'Visits'), ('newUsers', 'New'), ('keyEvents', 'Key events')),
        group='campaign', top=10),
     _b('Sites that send us visitors', 'hbar', 6, 5, [_m(W, 'sessions', filters={'medium': ['referral']})],
        group='source', top=10, empty='No visits from links on other sites in these dates.')],
    [_b("First visit's source", 'hbar', 4, 5, [_m(W, 'newUsers')], group='first_source', top=8, compare=False),
     _b('Ad keywords (utm_term)', 'table', 4, 5, [_m(W, 'sessions')], group='term', top=10, compare=False),
     _b('Pages they came from', 'table', 4, 5, [_m(W, 'screenPageViews')], group='referrer', top=10, compare=False)],
    [_head('What they read and do')],
    [_b('Pages', 'table', 12, 8,
        _ms(W, ('screenPageViews', 'Views'), ('activeUsers', 'Visitors'), ('avgEngagement', 'Time engaged'),
            ('eventCount', 'Events'), ('keyEvents', 'Key events')), group='page', top=25)],
    [_b('Landing pages', 'table', 6, 7,
        _ms(W, ('sessions', 'Visits'), ('newUsers', 'New'), ('engagementRate', 'Engagement'),
            ('bounceRate', 'Bounce'), ('keyEvents', 'Key events')), group='landing', top=15),
     _b('Page titles', 'table', 6, 7, _ms(W, ('screenPageViews', 'Views'), ('activeUsers', 'Visitors')),
        group='title', top=15)],
    [_b('Events', 'table', 6, 6, _ms(W, ('eventCount', 'Times'), ('activeUsers', 'Visitors')), group='event', top=20),
     _b('Key events (conversions)', 'hbar', 6, 6, [_m(W, 'keyEvents')], group='event', top=10,
        empty='No key events yet: mark an event as key in Google Analytics › Admin › Events.')],
    [_b('Links clicked to other sites', 'table', 4, 5, [_m(W, 'eventCount', filters={'event': ['click']})],
        group='link', top=10, empty=EVENT_EMPTY, compare=False),
     _b('Files downloaded', 'table', 4, 5, [_m(W, 'eventCount', filters={'event': ['file_download']})],
        group='file', top=10, empty=EVENT_EMPTY, compare=False),
     _b('Searched for on our site', 'table', 4, 5, [_m(W, 'eventCount', filters={'event': ['view_search_results']})],
        group='search_term', top=10, empty=EVENT_EMPTY, compare=False)],
    [_b('Time engaged per visitor', 'area', 6, 5, [_m(W, 'avgEngagement')], group='auto', colour='ocean'),
     _b('Engagement and bounce rate', 'line', 6, 5,
        _ms(W, ('engagementRate', 'Engagement rate'), ('bounceRate', 'Bounce rate')), group='auto',
        colour='forest')],
    [_head('Where they are')],
    [_b('Countries', 'table', 6, 7,
        _ms(W, ('activeUsers', 'Visitors'), ('newUsers', 'New'), ('sessions', 'Visits'),
            ('engagementRate', 'Engagement'), ('keyEvents', 'Key events')), group='country', top=15),
     _b('Cities', 'hbar', 6, 7, [_m(W, 'activeUsers')], group='city', top=15)],
    [_b('Indian states', 'hbar', 4, 6, [_m(W, 'activeUsers', filters={'country': ['India']})], group='region',
        top=12, compare=False),
     _b('Cities in the United States', 'hbar', 4, 6, [_m(W, 'activeUsers', filters={'country': ['United States']})],
        group='city', top=10, compare=False),
     _b('Parts of the world', 'donut', 4, 6, [_m(W, 'activeUsers')], group='subcontinent', compare=False)],
    [_b('Languages', 'donut', 4, 5, [_m(W, 'activeUsers')], group='language', top=8, compare=False),
     _b('Age', 'bar', 4, 5, [_m(W, 'activeUsers')], group='age', note=SIGNALS, compare=False),
     _b('Gender', 'donut', 4, 5, [_m(W, 'activeUsers')], group='gender', note=SIGNALS, compare=False)],
    [_b('Interests', 'hbar', 12, 5, [_m(W, 'activeUsers')], group='interests', top=12, note=SIGNALS, compare=False)],
    [_head('Their devices')],
    [_b('Devices', 'donut', 4, 5, [_m(W, 'activeUsers')], group='device'),
     _b('Operating systems', 'hbar', 4, 5, [_m(W, 'activeUsers')], group='os', top=8, compare=False),
     _b('Browsers', 'hbar', 4, 5, [_m(W, 'activeUsers')], group='browser', top=8, compare=False)],
    [_b('Screen sizes', 'hbar', 4, 6, [_m(W, 'activeUsers')], group='screen', top=10, compare=False),
     _b('Phone and computer makes', 'hbar', 4, 6, [_m(W, 'activeUsers')], group='brand', top=10, compare=False),
     _b('Device models', 'table', 4, 6, [_m(W, 'activeUsers')], group='model', top=12, compare=False)],
    [_b('Devices over time', 'stacked', 12, 5, [_m(W, 'activeUsers')], group='auto', split='device', compare=False)],
    [_head('When they come')],
    [_b('Visits by hour of the day', 'bar', 6, 5, [_m(W, 'sessions')], group='hour', compare=False,
        note="In Google Analytics' own time zone (Admin › Property details)."),
     _b('Visits by day of the week', 'bar', 6, 5, [_m(W, 'sessions')], group='weekday', compare=False)],
    [_head('Coming back')],
    [_b('Daily, weekly and monthly active visitors', 'line', 8, 5,
        _ms(W, ('active1DayUsers', 'Daily'), ('active7DayUsers', 'Weekly'), ('active28DayUsers', 'Monthly')),
        group='day', compare=False),
     _n('Stickiness: daily ÷ monthly', W, 'dauPerMau', w=4, colour='berry')],
    [_n('Stickiness: weekly ÷ monthly', W, 'wauPerMau', w=4, colour='berry', at=8)],
    [_b('Who came back, week by week', 'retention', 12, 6, top=6, of=W,
        note="Google Analytics' Retention report. Its weeks begin on Sunday.")],
])

BAND_2 = {'band': ['11th to 20th (second page)']}
BAND_1 = {'band': ['4th to 10th (first page)']}
SEARCH_COLS = (('clicks', 'Clicks'), ('impressions', 'Shown'), ('ctr', 'Click rate'), ('position', 'Position'))

SEARCH_FULL = _flow('s', [
    [_n('Clicks from Google', S, 'clicks', w=3, colour='forest'), _n('Times shown in Google', S, 'impressions', w=3),
     _n('Click rate', S, 'ctr', w=3, colour='ocean'), _n('Average position', S, 'position', w=3, colour='sunset')],
    [_b('Clicks and times shown', 'line', 8, 5, _ms(S, ('clicks', 'Clicks'), ('impressions', 'Times shown')),
        group='auto', colour='forest'),
     _b('Average position over time', 'line', 4, 5, [_m(S, 'position')], group='auto', colour='sunset',
        note='Lower is better: 1 is the top of the page.')],
    [_head('What people search for')],
    [_b('Searches', 'table', 12, 8, _ms(S, *SEARCH_COLS), group='query', top=25)],
    [_b('Nearly on the first page (we come 11th to 20th)', 'table', 6, 7,
        _ms(S, ('impressions', 'Shown'), ('clicks', 'Clicks'), ('position', 'Position'), filters=BAND_2),
        group='query', top=15, note='A little work on these pages can bring them onto the first page.',
        empty='None in these dates.'),
     _b('On the first page (we come 4th to 10th)', 'table', 6, 7,
        _ms(S, ('impressions', 'Shown'), ('clicks', 'Clicks'), ('position', 'Position'), filters=BAND_1),
        group='query', top=15, note='Shown often, clicked less than the top three: better titles help.',
        empty='None in these dates.')],
    [_b('Where we come in Google', 'bar', 6, 5, _ms(S, ('impressions', 'Times shown'), ('clicks', 'Clicks')),
        group='band', top=0, note='Each search counted at its own average position.'),
     _b('Searches in India', 'table', 6, 5,
        _ms(S, ('clicks', 'Clicks'), ('impressions', 'Shown'), ('position', 'Position'),
            filters={'country': ['India']}), group='query', top=10)],
    [_b('Searches in the United States', 'table', 6, 6,
        _ms(S, ('clicks', 'Clicks'), ('impressions', 'Shown'), ('position', 'Position'),
            filters={'country': ['United States']}), group='query', top=10),
     _b('Searches in Canada', 'table', 6, 6,
        _ms(S, ('clicks', 'Clicks'), ('impressions', 'Shown'), ('position', 'Position'),
            filters={'country': ['Canada']}), group='query', top=10)],
    [_head('Our pages in Google')],
    [_b('Pages', 'table', 12, 8, _ms(S, *SEARCH_COLS), group='page', top=25)],
    [_b('Pages nearly on the first page', 'table', 6, 6,
        _ms(S, ('impressions', 'Shown'), ('position', 'Position'), filters=BAND_2), group='page', top=12,
        empty='None in these dates.'),
     _b('How Google showed us', 'table', 6, 6, _ms(S, ('clicks', 'Clicks'), ('impressions', 'Shown')),
        group='appearance', top=0, empty='Google showed plain results only in these dates.')],
    [_b("Our pages in Google's index", 'indexing', 12, 8, top=12)],
    [_b('Our sitemaps in Google', 'sitemaps', 12, 4)],
    [_head('Where and how people search')],
    [_b('Countries', 'table', 6, 7, _ms(S, *SEARCH_COLS), group='country', top=15),
     _b('Clicks by country', 'hbar', 6, 7, [_m(S, 'clicks')], group='country', top=12, compare=False)],
    [_b('Devices', 'table', 6, 4, _ms(S, *SEARCH_COLS), group='device', top=0),
     _b('Kind of search', 'table', 6, 4, _ms(S, ('clicks', 'Clicks'), ('impressions', 'Shown')), group='type',
        top=0, note='Web, Images, Videos, the News tab, Discover and Google News.')],
    [_b('Clicks by device over time', 'stacked', 12, 5, [_m(S, 'clicks')], group='auto', split='device',
        compare=False)],
])

VISITORS_FULL = _flow('v', [
    [_b('On our websites now', 'live', 4, 5, [_m(VN)], group='country'),
     _b('Who is on the site now, and lately', 'people', 8, 9, top=12)],
    [_n('Visitors', V, 'visitors'), _n('Visits', V, 'visits')],
    [_n('Pages opened', V, 'count'), _n('Time on a page', V, 'secs', colour='ocean')],
    [_n('First-time visitors', V, 'new', w=4), _n('Started a chat', V, 'chatters', w=4, colour='berry'),
     _n('Time spent reading', V, 'time', w=4, colour='ocean')],
    [_b('Visitors, visits and pages', 'line', 8, 5,
        _ms(V, ('visitors', 'Visitors'), ('visits', 'Visits'), ('count', 'Pages opened')), group='auto'),
     _b('First visit or came back', 'donut', 4, 5, [_m(V, 'visitors')], group='returning')],
    [_head('Where they are')],
    [_b('Countries', 'table', 6, 7,
        _ms(V, ('visitors', 'Visitors'), ('visits', 'Visits'), ('count', 'Pages'), ('secs', 'Time on a page')),
        group='country', top=15),
     _b('Cities', 'hbar', 6, 7, [_m(V, 'visitors')], group='city', top=15)],
    [_b('Indian states', 'hbar', 6, 6, [_m(V, 'visitors', filters={'country': ['India']})], group='region', top=12),
     _b('Time zones', 'hbar', 6, 6, [_m(V, 'visitors')], group='tz', top=10)],
    [_head('How they found us')],
    [_b('How they found us', 'donut', 4, 6, [_m(V, 'visits')], group='source', top=8),
     _b('Campaigns', 'table', 4, 6, _ms(V, ('visits', 'Visits'), ('visitors', 'Visitors')), group='campaign', top=10,
        empty='No visits with utm_ words in their address in these dates.'),
     _b('How they first found us', 'hbar', 4, 6, [_m(V, 'visitors')], group='first_source', top=8)],
    [_b('Ways in over time', 'stacked', 12, 5, [_m(V, 'visits')], group='auto', split='source', compare=False)],
    [_head('What they read')],
    [_b('Most read pages', 'table', 6, 8,
        _ms(V, ('count', 'Opened'), ('visitors', 'Visitors'), ('secs', 'Time on it')), group='page', top=20),
     _b('Landing pages', 'table', 6, 8, _ms(V, ('visits', 'Visits'), ('visitors', 'Visitors')), group='landing',
        top=20)],
    [_head('Their devices, and when they come')],
    [_b('Devices', 'donut', 4, 5, [_m(V, 'visitors')], group='device'),
     _b('Browsers', 'hbar', 4, 5, [_m(V, 'visitors')], group='browser', top=8),
     _b('Operating systems', 'hbar', 4, 5, [_m(V, 'visitors')], group='os', top=8)],
    [_b('Pages opened by hour of the day (India time)', 'bar', 6, 5, [_m(V, 'count')], group='hour', compare=False),
     _b('Visits by day of the week', 'bar', 6, 5, [_m(V, 'visits')], group='weekday', compare=False)],
    [_b('Started a chat', 'donut', 4, 5, [_m(V, 'visitors')], group='chat'),
     _b('Websites', 'donut', 4, 5, [_m(V, 'visitors')], group='site'),
     _b('Browser languages', 'donut', 4, 5, [_m(V, 'visitors')], group='lang', top=8)],
    [_head('Coming back')],
    [_b('Who came back, week by week', 'retention', 12, 6, top=8, of=V,
        note='A browser is a visitor: the same person on a phone and a computer is two.')],
])

BOARDS = OrderedDict([
    ('overview', {'label': 'Overview', 'icon': 'fa-chart-simple', 'boxes': OVERVIEW, 'title': 'How things are going',
                  'lead': 'The website right now, our growth and where people travel.'}),
    ('google', {'label': 'Google Analytics', 'icon': 'fa-chart-line', 'boxes': GOOGLE_FULL,
                'title': 'The website, in full',
                'lead': 'Everything Google Analytics knows about the website: who came, how they found us, what '
                        'they read and did, where they are, their devices, when they come and who comes back.'}),
    ('search', {'label': 'Google search', 'icon': 'fa-magnifying-glass', 'boxes': SEARCH_FULL,
                'title': 'Google search, in full',
                'lead': 'Everything Search Console knows about us in Google: the searches, the pages, where we come, '
                        "which pages are in Google's index and our sitemaps."}),
    ('visitors', {'label': 'Our visitors', 'icon': 'fa-eye', 'boxes': VISITORS_FULL,
                  'title': 'Our visitors, as we record them',
                  'lead': 'Every visitor our chat bubble saw on our websites: where they are, how they found us, '
                          'what they read, when, and who comes back.'}),
])


# ================================================================================================ who

def can_design(user):
    from app.services import access
    return access.can(user, 'mkt_design')


def can_view(user):
    from app.services import access
    return access.can(user, 'promo')


def _query():
    return MktDashboard.query.order_by(MktDashboard.position, MktDashboard.id)


def tabs(user):
    """[{'key', 'label', 'icon', 'draft'}]: the built-in boards, then every published dashboard this person may see --
    and, for the people who design them, the ones never published yet (their drafts), so the switcher shows them all."""
    out = [{'key': k, 'label': b['label'], 'icon': b['icon'], 'dash': None, 'draft': False, 'board': True}
           for k, b in BOARDS.items()]
    designer = can_design(user)
    for d in _query().all():
        if d.published is not None and (d.audience != 'designers' or designer):
            out.append({'key': str(d.id), 'label': d.name, 'icon': d.icon or 'fa-chart-pie', 'dash': d, 'draft': False})
        elif d.published is None and designer:
            out.append({'key': str(d.id), 'label': d.name, 'icon': d.icon or 'fa-chart-pie', 'dash': d, 'draft': True})
    return out


def find(dash_id):
    try:
        return db.session.get(MktDashboard, int(dash_id))
    except (TypeError, ValueError):
        return None


# ================================================================================================ the boxes

def clean_boxes(raw):
    """Each box checked (mkt_engine.clean_box), named, and packed so none overlaps another."""
    if not isinstance(raw, list):
        raise DashError('The dashboard could not be read. Reload the page and try again.')
    if len(raw) > MAX_BOXES:
        raise DashError('A dashboard holds up to %d boxes. Make another dashboard for the rest.' % MAX_BOXES)
    out, ids = [], set()
    for i, b in enumerate(raw, start=1):
        try:
            box = eng.clean_box(b)
        except eng.EngineError as e:
            title = (b or {}).get('title') if isinstance(b, dict) else ''
            raise DashError('Box %d%s: %s' % (i, ' ("%s")' % title if title else '', e)) from None
        while box['id'] in ids or box['id'] == 'b':
            box['id'] = 'b%d' % (len(ids) + i)
        ids.add(box['id'])
        out.append(box)
    return pack(out)


def _overlaps(a, b):
    return a['x'] < b['x'] + b['w'] and b['x'] < a['x'] + a['w'] and a['y'] < b['y'] + b['h'] and b['y'] < a['y'] + a['h']


def pack(boxes):
    """Move boxes down until none overlaps one placed before it (top to bottom, left to right), then let each one
    rise into any space left above it -- the designer's grid does the same (mkt-designer.js pack)."""
    placed = []
    for b in sorted(boxes, key=lambda b: (b['y'], b['x'])):
        while any(_overlaps(b, p) for p in placed):
            b['y'] += 1
        placed.append(b)
    return compact(placed)


def compact(boxes):
    settled = []
    for b in sorted(boxes, key=lambda b: (b['y'], b['x'])):
        while b['y'] > 0 and not any(_overlaps(dict(b, y=b['y'] - 1), p) for p in settled):
            b['y'] -= 1
        settled.append(b)
    return settled


def overview():
    return clean_boxes([dict(b) for b in OVERVIEW])


def board(key):
    """A built-in board's cleaned boxes ('overview', 'google', 'search', 'visitors'); the Overview for any other key."""
    b = BOARDS.get(key) or BOARDS['overview']
    return clean_boxes([dict(x) for x in b['boxes']])


def boxes_for(dash, draft=False, key='overview'):
    if dash is None:
        return board(key)
    raw = dash.draft if draft else (dash.published or [])
    try:
        return clean_boxes(raw or [])
    except DashError:
        # a dashboard saved by an older version that no longer checks out: show what still does
        good = []
        for b in raw or []:
            try:
                good.append(eng.clean_box(b))
            except eng.EngineError:
                continue
        return pack(good)


def is_async(box):
    """Website and Google search boxes are asked for by the page's script, after it has drawn -- and so are the boxes
    that show what is so this minute, which it asks for again every 30 seconds."""
    if box['chart'] in eng.SPECIAL_CHARTS:
        return True
    return box['chart'] not in eng.NO_DATA_CHARTS and any(
        eng.source(m['source']).kind in ('ga', 'gsc') or eng.source(m['source']).live for m in box.get('metrics') or ())


def render(boxes, period, user):
    """[{'box', 'title', 'result', 'async'}] -- the numbers of every box that is not the website's."""
    from flask import g
    out = []
    g._mkt_rows = {}            # the boxes of one page share what they read from our tables
    for b in boxes:
        item = {'box': b, 'title': eng.describe(b), 'async': is_async(b), 'result': None}
        if b['chart'] == 'quotes':
            from app.services import promo
            item['quotes'] = promo.quotable(limit=b.get('top') or 6)
        elif b['chart'] == 'links':
            from app.services import promo
            item['links'] = promo.links()
        elif not item['async'] and b['chart'] != 'text':
            item['result'] = eng.run(b, period, user)
        out.append(item)
    g.pop('_mkt_rows', None)
    return out


def run_one(box, period, user):
    return eng.run(box, period, user)


# ================================================================================================ the designer's buttons

def _name(name):
    name = ' '.join(str(name or '').split())[:NAME_MAX]
    if not name:
        raise DashError('Give the dashboard a name.')
    return name


def create(user, name, start='blank'):
    """A new draft: empty, a copy of the Overview, or of another dashboard (`start`: 'blank', 'overview', an id)."""
    if MktDashboard.query.count() >= MAX_DASHBOARDS:
        raise DashError('There are already %d dashboards. Delete one you no longer use first.' % MAX_DASHBOARDS)
    boxes = []
    if start in BOARDS:
        boxes = board(start)
    elif start not in ('', 'blank', None):
        src = find(start)
        if src is not None:
            boxes = boxes_for(src, draft=True)
    top = db.session.query(db.func.max(MktDashboard.position)).scalar() or 0
    now = datetime.utcnow()
    d = MktDashboard(name=_name(name), draft=boxes, published=None, audience='all', range_key='last_30',
                     position=top + 1, created_by_id=user.id, updated_by_id=user.id, created_at=now, updated_at=now)
    db.session.add(d)
    db.session.commit()
    return d


def save(user, d, payload):
    """The designer's Save: name, description, who sees it, the dates it opens on, and the boxes (the draft)."""
    payload = payload if isinstance(payload, dict) else {}
    boxes = clean_boxes(payload.get('boxes') if 'boxes' in payload else d.draft)
    d.name = _name(payload.get('name', d.name))
    d.description = ' '.join(str(payload.get('description', d.description) or '').split())[:300] or None
    aud = payload.get('audience', d.audience)
    d.audience = aud if aud in AUDIENCES else 'all'
    rng = payload.get('range_key', d.range_key)
    d.range_key = rng if rng in eng.PAGE_RANGES and rng != 'custom' else 'last_30'
    icon = str(payload.get('icon', d.icon) or '')
    d.icon = icon if icon.startswith('fa-') and len(icon) <= 40 and icon.replace('-', '').isalnum() else None
    d.draft = boxes
    d.updated_by_id = user.id
    d.updated_at = datetime.utcnow()
    db.session.commit()
    return d


def publish(user, d):
    if not d.draft:
        raise DashError('Add at least one box before publishing.')
    d.published = clean_boxes(list(d.draft))
    d.published_by_id = user.id
    d.published_at = datetime.utcnow()
    db.session.commit()
    return d


def unpublish(user, d):
    d.published = None
    d.updated_by_id = user.id
    db.session.commit()
    return d


def discard(user, d):
    """Throw the draft away: back to what is published."""
    if d.published is not None:
        d.draft = list(d.published)
        db.session.commit()
    return d


def duplicate(user, d):
    copy = create(user, ('Copy of ' + d.name)[:NAME_MAX], start=str(d.id))
    copy.description, copy.audience, copy.range_key, copy.icon = d.description, d.audience, d.range_key, d.icon
    db.session.commit()
    return copy


def delete(user, d):
    db.session.delete(d)
    db.session.commit()


def move(user, d, direction):
    rows = _query().all()
    i = rows.index(d)
    j = i - 1 if direction == 'up' else i + 1
    if 0 <= j < len(rows):
        rows[i], rows[j] = rows[j], rows[i]
        for n, r in enumerate(rows, start=1):
            r.position = n
        db.session.commit()
    return d


# ================================================================================================ reusable boxes

LIBRARY = 'mkt.box_library'
LIBRARY_MAX = 80


def library():
    """The boxes the designers saved to use again, newest first: [{'id', 'name', 'box', 'by', 'at'}]."""
    from app.services import settings
    rows = settings.get_setting(LIBRARY) or []
    out = []
    for r in rows if isinstance(rows, list) else []:
        try:
            out.append({'id': str(r['id']), 'name': str(r.get('name') or '')[:NAME_MAX], 'box': eng.clean_box(r['box']),
                        'by': r.get('by') or '', 'at': r.get('at') or ''})
        except (KeyError, TypeError, eng.EngineError):
            continue                # one an older version saved that no longer checks out
    return out


def library_add(user, name, box):
    """Keep a box for every designer to use again, in any dashboard. Its place on the grid is not kept."""
    import secrets
    from app.services import settings
    try:
        b = eng.clean_box(box)
    except eng.EngineError as e:
        raise DashError(str(e)) from None
    b.pop('x', None)
    b.pop('y', None)
    name = ' '.join(str(name or '').split())[:NAME_MAX] or eng.describe(b)[:NAME_MAX]
    rows = [r for r in library()]
    if len(rows) >= LIBRARY_MAX:
        raise DashError('The box library is full (%d). Delete a box you no longer use first.' % LIBRARY_MAX)
    rows.insert(0, {'id': secrets.token_hex(4), 'name': name, 'box': b,
                    'by': getattr(user, 'full_name', None) or getattr(user, 'username', ''),
                    'at': datetime.utcnow().strftime('%Y-%m-%d %H:%M')})
    settings.set_setting(LIBRARY, rows, actor=user)
    return library()


def library_delete(user, lid):
    from app.services import settings
    rows = [r for r in library() if r['id'] != str(lid)]
    settings.set_setting(LIBRARY, rows, actor=user)
    return rows
