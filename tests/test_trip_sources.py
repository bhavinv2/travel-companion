"""Post source options: staff pick from CS_TRIP_SOURCES; 'organic' is never one of them.

'organic' marks a trip the traveller posted themselves and drives is_claimed, the CS queue filter
and the reminder jobs — so it stays a valid stored value, it just is not something a human selects.
"""
from datetime import date, timedelta

from conftest import login
from app.models import CompanionRequest, CS_TRIP_SOURCES, TRIP_SOURCES

DEPART = (date.today() + timedelta(days=21)).isoformat()


def test_cs_post_form_offers_only_the_four_staff_sources(client, db, cs_user):
    login(client, 'cs@test.com')
    html = client.get('/cs/posts/new').data.decode()
    form = html.split('name="source"')[1].split('</select>')[0]
    for value in ('whatsapp', 'website', 'facebook', 'other'):
        assert f'value="{value}"' in form
    assert 'value="organic"' not in form and 'value="excel"' not in form
    assert CS_TRIP_SOURCES == ('whatsapp', 'website', 'facebook', 'other')
    assert 'organic' in TRIP_SOURCES          # still a valid stored value


def test_editing_an_organic_post_cannot_silently_change_its_source(client, db, cs_user, user):
    """The dropdown cannot express 'organic', so a submit must not downgrade it to 'website'
    — that would flip is_claimed and pull a self-posted trip into the CS follow-up queue."""
    trip = CompanionRequest(user_id=user.id, travel_type='air', trip_type='one_way', source='organic',
                            flying_from='Hyderabad (HYD)', destination='Dallas (DFW)', role='seeking_help',
                            from_date=date.today() + timedelta(days=21))
    db.session.add(trip)
    db.session.commit()
    tid = trip.id
    assert trip.is_claimed

    login(client, 'cs@test.com')
    # the form shows the real source so it is not misrepresented as "Website"
    html = client.get(f'/cs/posts/{tid}/edit').data.decode()
    assert 'value="organic"' in html.split('name="source"')[1].split('</select>')[0]
    # and a submit that omits/spoofs it leaves the stored value alone
    client.post(f'/cs/posts/{tid}/edit', data={'source': 'website', 'role': 'seeking_help',
                                               'flying_from': 'Hyderabad (HYD)', 'destination': 'Dallas (DFW)',
                                               'from_date': DEPART})
    assert db.session.get(CompanionRequest, tid).source == 'organic'


def test_new_cs_post_stores_the_chosen_source(client, db, cs_user):
    login(client, 'cs@test.com')
    client.post('/cs/posts/new', data={'source': 'whatsapp', 'role': 'seeking_help',
                                       'flying_from': 'Hyderabad (HYD)', 'destination': 'Dallas (DFW)',
                                       'from_date': DEPART, 'poster_name': 'Ramesh'})
    trip = CompanionRequest.query.filter_by(poster_name='Ramesh').first()
    assert trip is not None and trip.source == 'whatsapp'
    assert not trip.is_claimed        # CS-created posts still await a claim
