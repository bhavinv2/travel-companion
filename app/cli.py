"""Management commands: flask set-role / make-admin / backfill-locations."""
import click
from app import db


def register(app):

    @app.cli.command('set-role')
    @click.argument('email')
    @click.argument('roles')
    def set_role(email, roles):
        """Set a user's roles: comma-separated keys, e.g. "user,cs" (roles are managed at /admin/options)."""
        from app.models import User
        from app.options import role_defs
        u = User.query.filter_by(email=email.lower()).first()
        if not u:
            raise click.ClickException(f'No user with email {email}')
        known = {r['key'] for r in role_defs()}
        keys = [k.strip() for k in roles.split(',') if k.strip()]
        bad = [k for k in keys if k not in known]
        if bad:
            raise click.ClickException(f"Unknown role(s): {', '.join(bad)}. Known: {', '.join(sorted(known))}")
        u.set_roles(keys)
        db.session.commit()
        click.echo(f"{u.username} now has roles {', '.join(u.role_keys)} (access: {u.effective_role})")

    @app.cli.command('make-admin')
    @click.argument('email')
    def make_admin(email):
        """Shortcut for: set-role EMAIL admin."""
        from app.models import User
        u = User.query.filter_by(email=email.lower()).first()
        if not u:
            raise click.ClickException(f'No user with email {email}')
        u.set_roles(u.role_keys + ['admin'])
        db.session.commit()
        click.echo(f'{u.username} is now admin')

    @app.cli.command('run-jobs')
    def run_jobs():
        """Escalate silent matches to CS and close departed posts (same as POST /internal/jobs/run)."""
        from app.services import jobs
        result = jobs.run_all()
        click.echo(f"escalated={result['escalated']} closed_departed={result['closed_departed']}")

    # ----------------------------------------------------------------- scraper

    def _find_recipe(ref):
        from app.models import ScrapeRecipe
        rec = None
        if str(ref).isdigit():
            rec = db.session.get(ScrapeRecipe, int(ref))
        if rec is None:
            rec = ScrapeRecipe.query.filter_by(name=ref).first()
        if rec is None:
            raise click.ClickException(f'No scrape recipe named or numbered {ref!r} (see: flask scrape-list)')
        return rec

    @app.cli.command('scrape-import-recipe')
    @click.argument('path', type=click.Path(exists=True, dir_okay=False))
    @click.option('--name', default=None, help='Recipe name (default: the site in the file)')
    @click.option('--source', default='website', type=click.Choice(['website', 'facebook']))
    def scrape_import_recipe(path, name, source):
        """Load a fetchall recipe JSON (made with `python -m fetchall teach URL`) into the app."""
        import json
        from app.models import ScrapeRecipe
        from app.services import scraper
        with open(path, encoding='utf-8') as f:
            recipe = json.load(f)
        errors = scraper.validate_recipe(recipe)
        if errors:
            raise click.ClickException('Invalid recipe: ' + ' '.join(errors))
        name = name or recipe.get('site') or scraper.site_of(recipe['start_url'])
        columns = scraper.recipe_columns(recipe)
        rec = ScrapeRecipe.query.filter_by(name=name).first()
        if rec is None:
            rec = ScrapeRecipe(name=name, mode='recipe', field_mapping=scraper.suggest_mapping(columns))
            db.session.add(rec)
        else:
            rec.field_mapping = scraper.merge_mapping(rec.field_mapping, columns)
        rec.site = recipe.get('site') or scraper.site_of(recipe['start_url'])
        rec.start_url = recipe['start_url']
        rec.recipe_json = recipe
        rec.default_source = source
        db.session.commit()
        click.echo(f'Recipe #{rec.id} "{rec.name}" saved ({len(columns)} columns); mapping: '
                   + ', '.join(f'{k}->{v}' for k, v in rec.field_mapping.items() if v != 'ignore'))

    @app.cli.command('scrape-list')
    def scrape_list():
        """List scrape recipes and their last run."""
        from app.models import ScrapeRecipe
        for r in ScrapeRecipe.query.order_by(ScrapeRecipe.id).all():
            click.echo(f"#{r.id:<4} {r.name:<30} {r.mode:<7} rows={r.rows.count():<5} last={r.last_status or '-'} "
                       f"{r.last_run_at.strftime('%Y-%m-%d %H:%M') if r.last_run_at else ''}")

    @app.cli.command('scrape-run')
    @click.argument('ref')
    @click.option('--max-pages', type=int, default=None)
    @click.option('--max-rows', type=int, default=None)
    @click.option('--full', is_flag=True, help='Re-scrape everything instead of only new items')
    def scrape_run(ref, max_pages, max_rows, full):
        """Run a scrape recipe now (synchronously) and print the health report."""
        from app.services import scraper, scraper_worker
        rec = _find_recipe(ref)
        app.config['SCRAPER_INLINE'] = True
        try:
            run = scraper_worker.enqueue('run', recipe=rec, trigger='cli',
                                         options={'incremental': not full, 'max_pages': max_pages, 'max_rows': max_rows})
        except scraper_worker.AlreadyRunning as e:
            raise click.ClickException(str(e))
        except scraper.ScraperUnavailable as e:
            raise click.ClickException(str(e))
        for line in run.log_tail(20):
            click.echo(line)
        rep = run.report
        click.echo(f"status={run.status} rows_total={run.rows_total} new={run.rows_new} duplicate={run.rows_duplicate} "
                   f"health={rep.get('headline', '-')}")
        for m in rep.get('messages', []):
            click.echo(f'  - {m}')
        if run.error:
            click.echo(f'error: {run.error}')
        raise SystemExit(0 if run.status == 'done' and rep.get('exit_code', 0) == 0 else (rep.get('exit_code') or 1))

    @app.cli.command('scrape-recover')
    def scrape_recover():
        """Mark runs whose worker died as failed."""
        from app.services import scraper_worker
        click.echo(f'recovered {scraper_worker.recover_stale_runs()} stale run(s)')

    @app.cli.command('backfill-locations')
    def backfill_locations():
        """Fill origin_/dest_ iata/city/metro for existing posts from their display strings."""
        from app.models import CompanionRequest
        from app.services.locations import apply_route
        n = 0
        for t in CompanionRequest.query.filter(CompanionRequest.travel_type == 'air').all():
            o, d = apply_route(t)
            if o or d:
                n += 1
        db.session.commit()
        click.echo(f'Backfilled {n} posts')

    @app.cli.command('seed-demo-match')
    @click.option('--password', default='Demo#Desis2026', show_default=True, help='Password for both demo users')
    @click.option('--days', default=20, show_default=True, help='Departure date = today + DAYS')
    def seed_demo_match(password, days):
        """Create two demo travellers (user1 seeking help, user2 offering help) whose posts match, and print their logins.

        Safe to re-run: existing users/posts are updated in place, the match is recomputed, nothing is duplicated.
        """
        from datetime import date, timedelta
        from app.models import User, CompanionRequest, ContactPoint, Match
        from app.services import matching
        from app.services.locations import apply_route

        when = date.today() + timedelta(days=days)
        spec = [
            dict(email='user1@connectingdesis.com', username='user1', first='Priya', last='Sharma',
                 phone='+12145550101', role='seeking_help', gender='female', age='60_plus',
                 comment='My mother (68) is flying alone for the first time. A fellow Telugu speaker on the same '
                         'flight to keep her company and help at Doha transit would be wonderful.'),
            dict(email='user2@connectingdesis.com', username='user2', first='Ravi', last='Kumar',
                 phone='+14695550202', role='offering_help', gender='male', age='26_40',
                 comment='Frequent flyer on this route; happy to help an elderly traveller with forms, '
                         'wheelchair pickup and the DOH transfer.'),
        ]
        users, trips = [], []
        for s in spec:
            u = User.query.filter_by(email=s['email']).first()
            if u is None:
                u = User(email=s['email'], username=s['username'])
                db.session.add(u)
            u.first_name, u.last_name, u.phone = s['first'], s['last'], s['phone']
            u.role, u.is_admin, u.is_active, u.is_verified = 'user', False, True, True
            u.set_password(password)
            db.session.flush()
            users.append(u)
        for u, s in zip(users, spec):
            t = CompanionRequest.query.filter_by(user_id=u.id, flight_number='QR573').first()
            if t is None:
                t = CompanionRequest(user_id=u.id, travel_type='air', trip_type='one_way', source='organic')
                db.session.add(t)
            t.flying_from, t.destination, t.from_date = 'Hyderabad (HYD)', 'Dallas (DFW)', when
            t.airline, t.flight_number = 'Qatar Airways', 'QR573'
            t.preferred_languages = ['Telugu', 'Hindi', 'English']
            t.role, t.traveler_gender, t.traveler_age_group = s['role'], s['gender'], s['age']
            t.additional_comments, t.ticket_booked = s['comment'], True
            apply_route(t)
            t.set_status('open')
            db.session.flush()
            if not t.contact_points:
                db.session.add(ContactPoint(trip=t, user_id=u.id, type='email', value=u.email,
                                            consent_to_share=True, is_preferred=True, added_by='owner'))
                db.session.add(ContactPoint(trip=t, user_id=u.id, type='whatsapp', value=u.phone,
                                            consent_to_share=True, added_by='owner'))
            trips.append(t)
        db.session.commit()

        matching.compute_matches_for(trips[0])          # commits; alerts user2 about the new match
        a, b = Match.ordered_ids(trips[0].id, trips[1].id)
        m = Match.query.filter_by(trip_a_id=a, trip_b_id=b).first()
        if m is None:
            raise click.ClickException('The two demo posts did not match - check MATCH_WEIGHTS / MIN_SCORE')
        click.echo(f'Match #{m.id}: {m.score}% ({m.status}) between post #{trips[0].id} and post #{trips[1].id} '
                   f'- {trips[0].route_display} on {when} (Qatar Airways QR573)')
        click.echo('Logins (both use the same password):')
        for u, t in zip(users, trips):
            click.echo(f"  {u.email:32} {password:16} {t.role.replace('_', ' ')} - post #{t.id}")
        # --- more demo travellers so user1/user2 have several matches (idempotent) ----------------
        extra = [
            ('user3@connectingdesis.com', 'user3', 'Anil', 'offering_help', 'Hyderabad (HYD)', 'Dallas (DFW)',
             when, 'Qatar Airways', 'QR573', 'I do this route every quarter - happy to keep an eye out for co-passengers.'),
            ('user4@connectingdesis.com', 'user4', 'Sunita', 'offering_help', 'Hyderabad (HYD)', 'Dallas (DFW)',
             when + timedelta(days=2), 'American Airlines', 'AA127', 'Flying two days later but my dates are flexible; glad to help at DFW immigration.'),
            ('user5@connectingdesis.com', 'user5', 'Kiran', 'seeking_help', 'Hyderabad (HYD)', 'Dallas (DFW)',
             when, 'Qatar Airways', 'QR573', 'First international flight - would love some company from HYD.'),
            ('user6@connectingdesis.com', 'user6', 'Meera', 'offering_help', 'Dallas (DFW)', 'Hyderabad (HYD)',
             when + timedelta(days=20), 'Qatar Airways', 'QR574', 'Returning home to Hyderabad; can help with bags and the DOH transit.'),
        ]
        for email, uname, first, role_, frm, to, dt, airline, flight, note in extra:
            u = User.query.filter_by(email=email).first()
            if u is None:
                u = User(email=email, username=uname)
                db.session.add(u)
            u.first_name, u.last_name = first, 'Desi'
            u.role, u.is_admin, u.is_active, u.is_verified = 'user', False, True, True
            u.set_password(password)
            db.session.flush()
            t = CompanionRequest.query.filter_by(user_id=u.id).first()
            if t is None:
                t = CompanionRequest(user_id=u.id, travel_type='air', trip_type='one_way', source='organic')
                db.session.add(t)
            t.flying_from, t.destination, t.from_date = frm, to, dt
            t.airline, t.flight_number = airline, flight
            t.preferred_languages = ['Telugu', 'English']
            t.role, t.additional_comments, t.ticket_booked = role_, note, True
            t.from_date_flexible = (uname == 'user4')
            apply_route(t)
            t.set_status('open')
            db.session.flush()
            if not t.contact_points:
                db.session.add(ContactPoint(trip=t, user_id=u.id, type='email', value=email,
                                            consent_to_share=True, is_preferred=True, added_by='owner'))
            db.session.commit()
            matching.compute_matches_for(t)

        # user1 also gets a return post (matches user6) and one with no matches yet
        u1 = users[0]
        second = CompanionRequest.query.filter_by(user_id=u1.id, flying_from='Dallas (DFW)').first()
        if second is None:
            second = CompanionRequest(user_id=u1.id, travel_type='air', trip_type='one_way', source='organic')
            db.session.add(second)
        second.flying_from, second.destination = 'Dallas (DFW)', 'Hyderabad (HYD)'
        second.from_date = when + timedelta(days=20)
        second.airline, second.flight_number = 'Qatar Airways', 'QR574'
        second.preferred_languages = ['Telugu', 'English']
        second.role, second.ticket_booked = 'seeking_help', False
        second.additional_comments = 'The return leg - my mother flies back and help at DOH would be appreciated.'
        apply_route(second)
        second.set_status('open')
        db.session.flush()
        if not second.contact_points:
            db.session.add(ContactPoint(trip=second, user_id=u1.id, type='email', value=u1.email,
                                        consent_to_share=True, added_by='owner'))
        third = CompanionRequest.query.filter_by(user_id=u1.id, flying_from='Bengaluru (BLR)').first()
        if third is None:
            third = CompanionRequest(user_id=u1.id, travel_type='air', trip_type='one_way', source='organic')
            db.session.add(third)
        third.flying_from, third.destination = 'Bengaluru (BLR)', 'San Francisco (SFO)'
        third.from_date = when + timedelta(days=10)
        third.role = 'seeking_help'
        third.preferred_languages = ['Kannada', 'English']
        third.additional_comments = 'Exploring dates for this one - no ticket yet.'
        apply_route(third)
        third.set_status('open')
        db.session.commit()
        matching.compute_matches_for(second)
        matching.compute_matches_for(third)
        click.echo(f'Extra travellers user3-user6 seeded (password {password}); total matches now {Match.query.count()}.')
        click.echo('Sign in and open /dashboard -> "Your matches" -> "Share my contact & notify".')

    @app.cli.command('seed-demo-user6')
    @click.option('--password', default='Demo#Desis2026', show_default=True)
    @click.option('--days', default=14, show_default=True, help='Days from today to the anchor date')
    def seed_demo_user6(password, days):
        """Give user6 one post of every trip type - one-way, round trip, multi-stop - plus
        counterpart travellers (user7-user11) so she has at least five matches.

        The counterparts are picked to show off leg-level matching: one-way posts pair with
        the round trip's outbound AND its return, and with single hops of the multi-stop
        itinerary. Safe to re-run; the one-way post is the same row seed-demo-match maintains.
        """
        from datetime import date, timedelta
        from app.models import User, CompanionRequest, ContactPoint
        from app.services import matching
        from app.services.locations import apply_route

        base = date.today() + timedelta(days=days)

        def ensure_user(email, uname, first):
            u = User.query.filter_by(email=email).first()
            if u is None:
                u = User(email=email, username=uname)
                db.session.add(u)
            u.first_name, u.last_name = first, 'Desi'
            u.role, u.is_admin, u.is_active, u.is_verified = 'user', False, True, True
            u.set_password(password)
            db.session.flush()
            return u

        def ensure_post(u, lookup, **fields):
            t = CompanionRequest.query.filter_by(user_id=u.id, **lookup).first()
            if t is None:
                t = CompanionRequest(user_id=u.id, travel_type='air', source='organic', **lookup)
                db.session.add(t)
            for k, v in fields.items():
                setattr(t, k, v)
            t.ticket_booked = True
            t.preferred_languages = ['Telugu', 'English']
            apply_route(t)
            t.set_status('open')
            db.session.flush()
            if not t.contact_points:
                db.session.add(ContactPoint(trip=t, user_id=u.id, type='email', value=u.email,
                                            consent_to_share=True, is_preferred=True, added_by='owner'))
            return t

        u6 = ensure_user('user6@connectingdesis.com', 'user6', 'Meera')
        one_way = ensure_post(
            u6, dict(trip_type='one_way', flight_number='QR574'),
            flying_from='Dallas (DFW)', destination='Hyderabad (HYD)',
            from_date=base + timedelta(days=20), airline='Qatar Airways', role='offering_help',
            additional_comments='Returning home to Hyderabad; can help with bags and the DOH transit.')
        round_trip = ensure_post(
            u6, dict(trip_type='round_trip'),
            flying_from='Hyderabad (HYD)', destination='San Francisco (SFO)',
            from_date=base + timedelta(days=7), to_date=base + timedelta(days=28),
            airline='Air India', flight_number='AI173', role='seeking_help',
            additional_comments='Visiting my son in the Bay Area - company in either direction would be lovely.')
        multi = ensure_post(
            u6, dict(trip_type='multi_destination'),
            flying_from='Hyderabad (HYD)', destination='Dallas (DFW)',
            from_date=base + timedelta(days=2), role='offering_help',
            legs=[
                {'from': 'Hyderabad (HYD)', 'to': 'Doha (DOH)',
                 'date': (base + timedelta(days=2)).isoformat(), 'airline': 'Qatar Airways', 'flight_number': 'QR4779'},
                {'from': 'Doha (DOH)', 'to': 'New York (JFK)',
                 'date': (base + timedelta(days=2)).isoformat(), 'airline': 'Qatar Airways', 'flight_number': 'QR701'},
                {'from': 'New York (JFK)', 'to': 'Dallas (DFW)',
                 'date': (base + timedelta(days=5)).isoformat(), 'airline': 'American Airlines', 'flight_number': 'AA1503'},
            ],
            additional_comments='Multi-city trip via Doha and New York; glad to help a co-passenger on any hop.')

        counterparts = [
            ('user7@connectingdesis.com', 'user7', 'Arjun', 'seeking_help',
             'Dallas (DFW)', 'Hyderabad (HYD)', base + timedelta(days=20), 'Qatar Airways', 'QR574',
             'Flying home with two toddlers - an extra pair of hands at DOH would mean a lot.'),
            ('user8@connectingdesis.com', 'user8', 'Lakshmi', 'offering_help',
             'Hyderabad (HYD)', 'San Francisco (SFO)', base + timedelta(days=7), 'Air India', 'AI173',
             'I fly this sector often; happy to sit nearby and help with the immigration forms.'),
            ('user9@connectingdesis.com', 'user9', 'Venkat', 'seeking_help',
             'San Francisco (SFO)', 'Hyderabad (HYD)', base + timedelta(days=28), 'Air India', 'AI173',
             'First trip back in years - would appreciate company on the way to Hyderabad.'),
            ('user10@connectingdesis.com', 'user10', 'Sana', 'seeking_help',
             'Hyderabad (HYD)', 'Doha (DOH)', base + timedelta(days=2), 'Qatar Airways', 'QR4779',
             'Short hop to Doha; travelling alone for the first time.'),
            ('user11@connectingdesis.com', 'user11', 'Rohit', 'seeking_help',
             'Doha (DOH)', 'New York (JFK)', base + timedelta(days=2), 'Qatar Airways', 'QR701',
             'Long Doha to New York leg - would love a companion to talk to.'),
        ]
        posts = [one_way, round_trip, multi]
        for email, uname, first, role_, frm, to, when, airline, flight, note in counterparts:
            u = ensure_user(email, uname, first)
            posts.append(ensure_post(
                u, dict(trip_type='one_way', flight_number=flight),
                flying_from=frm, destination=to, from_date=when, airline=airline,
                role=role_, additional_comments=note))
        db.session.commit()
        for t in posts:
            matching.compute_matches_for(t)

        total = 0
        click.echo(f"user6's posts and matches (anchor date {base}):")
        for t in (one_way, round_trip, multi):
            ms = matching.ranked_matches_for(t)
            total += len(ms)
            click.echo(f'  post #{t.id} [{t.trip_type}] {t.route_display}: {len(ms)} match(es)')
            for m in ms:
                other = m.other_trip(t.id)
                my_leg = m.leg_a if m.trip_a_id == t.id else m.leg_b
                click.echo(f'    {m.score:3}% with {other.display_name} (post #{other.id}) on my {my_leg.label.lower()}')
        if total < 5:
            raise click.ClickException(f'Only {total} matches for user6 - expected at least 5; '
                                       'check MATCH_WEIGHTS / MIN_SCORE')
        click.echo(f'Total: {total} matches for user6.')
        click.echo('Logins (all one password):')
        for email in ['user6@connectingdesis.com'] + [c[0] for c in counterparts]:
            click.echo(f'  {email:32} {password}')

    @app.cli.command('seed-demo-trips')
    @click.option('--count', default=50, show_default=True, help='How many open demo trips to ensure')
    @click.option('--password', default='Demo#Desis2026', show_default=True)
    def seed_demo_trips(count, password):
        """Fill the site with N open dummy trips from generated demo accounts (demo01, demo02, ...)."""
        import random
        from datetime import date, timedelta
        from app.models import User, CompanionRequest, ContactPoint
        from app.services import matching
        from app.services.locations import apply_route
        random.seed(42)
        routes = [('Hyderabad (HYD)', 'Dallas (DFW)'), ('Mumbai (BOM)', 'New York (JFK)'),
                  ('Delhi (DEL)', 'San Francisco (SFO)'), ('Bengaluru (BLR)', 'Seattle (SEA)'),
                  ('Chennai (MAA)', 'London (LHR)'), ('Hyderabad (HYD)', 'Chicago (ORD)'),
                  ('Ahmedabad (AMD)', 'Toronto (YYZ)'), ('Kochi (COK)', 'Dubai (DXB)'),
                  ('Delhi (DEL)', 'Melbourne (MEL)'), ('Mumbai (BOM)', 'Dallas (DFW)')]
        airlines = [('Qatar Airways', 'QR'), ('Emirates', 'EK'), ('Air India', 'AI'),
                    ('Lufthansa', 'LH'), ('British Airways', 'BA'), ('Etihad Airways', 'EY')]
        langsets = [['Telugu', 'English'], ['Hindi', 'English'], ['Tamil', 'English'], ['Gujarati', 'Hindi'],
                    ['Malayalam', 'English'], ['Punjabi', 'Hindi', 'English'], ['Bengali', 'English'], ['Kannada', 'English']]
        names = ['Aarav', 'Diya', 'Rohan', 'Isha', 'Vikram', 'Ananya', 'Karthik', 'Priyanka', 'Sanjay', 'Lakshmi',
                 'Arjun', 'Neha', 'Rahul', 'Pooja', 'Suresh', 'Divya', 'Manoj', 'Sneha', 'Harish', 'Kavya',
                 'Nikhil', 'Swathi', 'Ramesh', 'Anjali', 'Vivek']
        comments = [None, 'Happy to meet at the gate.', 'First time on this route.',
                    'Travelling light - can help with forms and bags.', 'Would prefer a companion on the same flight.',
                    'Long layover, company would be lovely.']
        created, i = 0, 0
        while created < count and i < count * 2:
            i += 1
            uname = f'demo{i:02d}'
            email = f'{uname}@connectingdesis.com'
            u = User.query.filter_by(email=email).first()
            if u is None:
                u = User(email=email, username=uname, first_name=random.choice(names), last_name='Demo', is_verified=True)
                u.set_password(password)
                db.session.add(u)
                db.session.flush()
            missing = 2 - CompanionRequest.query.filter_by(user_id=u.id).count()
            for _ in range(max(missing, 0)):
                frm, to = random.choice(routes)
                if random.random() < 0.4:
                    frm, to = to, frm
                al, code = random.choice(airlines)
                t = CompanionRequest(
                    user_id=u.id, travel_type='air',
                    trip_type='round_trip' if random.random() < 0.25 else 'one_way',
                    source='organic', flying_from=frm, destination=to,
                    from_date=date.today() + timedelta(days=random.randint(5, 75)),
                    airline=al, flight_number=f'{code}{random.randint(100, 999)}',
                    preferred_languages=random.choice(langsets),
                    role=random.choice(['seeking_help', 'offering_help', 'seeking_help', 'open']),
                    ticket_booked=random.random() < 0.6,
                    from_date_flexible=random.random() < 0.3,
                    is_anonymous=random.random() < 0.1,
                    additional_comments=random.choice(comments))
                if t.trip_type == 'round_trip':
                    t.to_date = t.from_date + timedelta(days=random.randint(10, 30))
                apply_route(t)
                t.set_status('open')
                db.session.add(t)
                db.session.flush()
                if random.random() < 0.7:
                    db.session.add(ContactPoint(trip=t, user_id=u.id, type='email', value=email,
                                                consent_to_share=True, added_by='owner'))
                created += 1
                if created >= count:
                    break
        db.session.commit()
        recomputed = 0
        for t in (CompanionRequest.query.join(User, CompanionRequest.user_id == User.id)
                  .filter(User.email.like('demo%@connectingdesis.com')).all()):
            matching.compute_matches_for(t)
            recomputed += 1
        click.echo(f'{created} demo trip(s) created across demo accounts (password {password}); matches recomputed for {recomputed} posts.')

    @app.cli.command('seed-demo-inbox')
    def seed_demo_inbox():
        """Give user1 a lively inbox: pending connection requests plus an accepted chat with user2."""
        from datetime import datetime, timedelta
        from app.models import User, CompanionRequest, ConnectionRequest, ChatRoom, ChatMessage
        from app.services import notify
        u1 = User.query.filter_by(email='user1@connectingdesis.com').first()
        u2 = User.query.filter_by(email='user2@connectingdesis.com').first()
        if not u1 or not u2:
            raise click.ClickException('Run `flask seed-demo-match` first.')
        trip = CompanionRequest.query.filter_by(user_id=u1.id, flight_number='QR573').first()
        made = 0
        for email in ('demo03@connectingdesis.com', 'demo07@connectingdesis.com'):
            d = User.query.filter_by(email=email).first()
            if d and not ConnectionRequest.query.filter_by(requester_id=d.id, trip_id=trip.id).first():
                db.session.add(ConnectionRequest(requester_id=d.id, trip_id=trip.id, status='pending'))
                notify.push(u1.id, 'connection_request', title=f'{d.username} wants to connect',
                            body=f'On your trip {trip.route_display}.', link='/inbox', category='connection')
                made += 1
        conn = ConnectionRequest.query.filter_by(requester_id=u2.id, trip_id=trip.id).first()
        if conn is None:
            db.session.add(ConnectionRequest(requester_id=u2.id, trip_id=trip.id, status='accepted'))
        else:
            conn.status = 'accepted'
        room = ChatRoom.query.filter(((ChatRoom.user1_id == u1.id) & (ChatRoom.user2_id == u2.id)) |
                                     ((ChatRoom.user1_id == u2.id) & (ChatRoom.user2_id == u1.id))).first()
        if room is None:
            room = ChatRoom(user1_id=u1.id, user2_id=u2.id, trip_id=trip.id)
            db.session.add(room)
            db.session.flush()
        if ChatMessage.query.filter_by(room_id=room.id).count() == 0:
            now = datetime.utcnow()
            msgs = [(u2.id, 'Hi Priya! I saw we matched for the HYD to DFW flight on 20 Sept.'),
                    (u1.id, 'Hello Ravi! Yes - my mother is travelling alone, thank you for offering to help.'),
                    (u2.id, 'Happy to. I will be at the Qatar Airways counter about 3 hours before departure.'),
                    (u1.id, 'Perfect, I will share her details here. She speaks Telugu and a little English.'),
                    (u2.id, 'Telugu works great. See you both at HYD!')]
            for i, (sender, text) in enumerate(msgs):
                db.session.add(ChatMessage(room_id=room.id, sender_id=sender, message=text,
                                           created_at=now - timedelta(minutes=(len(msgs) - i) * 7)))
            notify.push(u1.id, 'message', title=f'New message from {u2.username}',
                        body=msgs[-1][1][:80], link='/inbox', category='chat')
        # a third pending request, plus data for the Sent tab of /connections
        d11 = User.query.filter_by(email='demo11@connectingdesis.com').first()
        if d11 and not ConnectionRequest.query.filter_by(requester_id=d11.id, trip_id=trip.id).first():
            db.session.add(ConnectionRequest(requester_id=d11.id, trip_id=trip.id, status='pending', requester_anonymous=True))
            notify.push(u1.id, 'connection_request', title='Someone wants to connect (anonymous)',
                        body=f'On your trip {trip.route_display}.', link='/inbox', category='connection')
        for email, status in (('demo05@connectingdesis.com', 'pending'), ('demo09@connectingdesis.com', 'accepted')):
            d = User.query.filter_by(email=email).first()
            dtrip = CompanionRequest.query.filter_by(user_id=d.id).first() if d else None
            if d and dtrip and not ConnectionRequest.query.filter_by(requester_id=u1.id, trip_id=dtrip.id).first():
                db.session.add(ConnectionRequest(requester_id=u1.id, trip_id=dtrip.id, status=status))
                if status == 'accepted':
                    r2 = ChatRoom.query.filter(((ChatRoom.user1_id == u1.id) & (ChatRoom.user2_id == d.id)) |
                                               ((ChatRoom.user1_id == d.id) & (ChatRoom.user2_id == u1.id))).first()
                    if r2 is None:
                        r2 = ChatRoom(user1_id=u1.id, user2_id=d.id, trip_id=dtrip.id)
                        db.session.add(r2)
                        db.session.flush()
                    if ChatMessage.query.filter_by(room_id=r2.id).count() == 0:
                        db.session.add(ChatMessage(room_id=r2.id, sender_id=d.id,
                                                   message=f'Hi! Accepted your request about {dtrip.route_display} - happy to talk details.',
                                                   created_at=datetime.utcnow() - timedelta(hours=5)))
                    notify.push(u1.id, 'connection_accepted', title=f'{d.username} accepted your request',
                                body=f'You can now chat about {dtrip.route_display}.', link='/inbox', category='connection')
        db.session.commit()
        click.echo(f'Inbox demo ready for user1: {made} new pending request(s), chat with {u2.username} '
                   f'({ChatMessage.query.filter_by(room_id=room.id).count()} messages), '
                   f'plus sent requests to demo05 (pending) and demo09 (accepted, with chat).')


    @app.cli.command('backfill-legs')
    @click.option('--recompute/--no-recompute', default=True,
                  help='Also rebuild matches once the legs exist')
    def backfill_legs(recompute):
        """Build trip_legs for every existing post, then rematch leg by leg.

        Safe to re-run: sync_legs updates rows in place, so leg ids (and the matches that
        point at them) survive. Alerts are suppressed -- nobody should get a notification
        for a match that already existed under the old engine.
        """
        from app.models import CompanionRequest, Match
        from app.services import legs as legsvc, matching

        trips = CompanionRequest.query.order_by(CompanionRequest.id).all()
        counts = {}
        for t in trips:
            rows = legsvc.sync_legs(t)
            counts[t.trip_type or 'one_way'] = counts.get(t.trip_type or 'one_way', 0) + len(rows)
        db.session.commit()
        click.echo(f'Legs built for {len(trips)} posts: '
                   + ', '.join(f'{k} {v}' for k, v in sorted(counts.items())))

        if not recompute:
            return
        # Old rows have no legs and can never be reproduced by the leg matcher, so clear
        # them out rather than leave matches nothing in the UI can explain.
        stale = Match.query.filter(Match.leg_a_id.is_(None)).all()
        for m in stale:
            db.session.delete(m)
        db.session.commit()
        click.echo(f'Removed {len(stale)} pre-leg match rows.')

        made = 0
        for t in CompanionRequest.query.filter(CompanionRequest.status.in_(['open', 'matched'])):
            made += len(matching.compute_matches_for(t, commit=True, notify=False))
        click.echo(f'Recomputed matches: {Match.query.count()} rows now on file.')

    @app.cli.command('seed-demo-content')
    def seed_demo_content():
        """Fill the content screens: blog posts, reviews + contact enquiries (Voices),
        CS-created posts awaiting claim, an escalated match for the CS queue, and fresh
        notifications for the documented demo logins. Safe to re-run."""
        from datetime import date, datetime, timedelta
        from app.models import (ActivityEvent, Blog, ClaimToken, CompanionRequest, ContactMessage,
                                ContactPoint, Feedback, Match, MatchParty, Notification, User)
        from app.services import matching, notify
        from app.services.locations import apply_route

        now = datetime.utcnow()
        today = date.today()

        # ---- the documented logins (doc/keys.md); existing accounts keep their password ----
        accounts = {
            'admin@connectingdesis.com': ('desisadmin', 'Admin', ['user', 'admin'], 'Admin#Desis2026'),
            'cs@connectingdesis.com': ('csagent', 'Chitra', ['user', 'cs'], 'Cs#Desis2026'),
            'user@connectingdesis.com': ('regularuser', 'Uma', ['user'], 'User#Desis2026'),
            'super@connectingdesis.com': ('superdemo', 'Sam', ['user', 'cs', 'admin'], 'Super#Desis2026'),
        }

        def ensure_account(email):
            uname, first, roles, pw = accounts[email]
            u = User.query.filter_by(email=email).first()
            if u is None:
                u = User(email=email, username=uname, first_name=first, last_name='Desis')
                u.set_password(pw)
                db.session.add(u)
            u.is_active, u.is_verified = True, True
            u.set_roles(roles)
            db.session.flush()
            return u

        admin = ensure_account('admin@connectingdesis.com')
        cs = ensure_account('cs@connectingdesis.com')
        regular = ensure_account('user@connectingdesis.com')
        ensure_account('super@connectingdesis.com')

        def event_once(event, trip=None, actor=None, match_id=None, **meta):
            q = ActivityEvent.query.filter_by(event=event)
            q = q.filter_by(trip_id=trip.id if trip is not None else None)
            if match_id is not None:
                q = q.filter_by(match_id=match_id)
            if q.first() is None:
                ActivityEvent.log(event, trip=trip, actor=actor, match_id=match_id, **meta)

        # ---- blog: four published stories + one draft (public /blog + admin blog manager) ----
        blog_posts = [
            (2, True, 'how-matching-works', 'How our matching works, leg by leg',
             '<p>Every post you create is broken into legs - the outbound, the return, each hop of a '
             'multi-city itinerary - and every leg is compared with everyone else\'s. Same route on the '
             'same date scores highest, nearby dates and flexible tickets still count.</p>'
             '<p>When a pairing crosses the threshold you both get an alert, and our customer support '
             'team steps in whenever one side goes quiet. Nothing is shared until you consent.</p>'),
            (6, True, 'first-flight-checklist', 'A checklist for first-time flyers to the US',
             '<p>Keep the passport, visa papers and the emergency contact card in one clear pouch. '
             'Arrive three hours early; Qatar and Emirates counters in Hyderabad get long queues after 9pm.</p>'
             '<p>At transit, follow the purple "Transfer" signs in Doha - our companions say 45 minutes is '
             'plenty if you do not stop for shopping. Ask any airline staff for a wheelchair; it is free.</p>'),
            (10, True, 'meera-found-company', 'Community story: how Meera found company for her mother',
             '<p>Meera posted a Hyderabad to Dallas trip for her 68-year-old mother, who was flying alone '
             'for the first time. Within two days the site suggested Ravi - a frequent flyer on the same '
             'Qatar Airways flight.</p><p>They chatted in the app, met at the check-in counter, and her '
             'mother had help through Doha transit and DFW immigration. "It felt like family," Meera wrote.</p>'),
            (16, True, 'doha-transit-guide', 'Airport guide: Doha transit without the stress',
             '<p>Hamad International is big but simple: one terminal, one security check for transfers, '
             'gates 15-25 minutes of walking apart. Free water fountains are past security on every concourse.</p>'
             '<p>If your layover is under two hours, skip the duty-free loop and go straight to your gate; '
             'the train inside the terminal saves ten minutes to the C gates.</p>'),
            (0, False, 'whatsapp-alerts-draft', 'Coming soon: WhatsApp alerts (draft)',
             '<p>Draft announcement for the WhatsApp notification channel. Not published yet - this is '
             'what an unpublished post looks like in the admin blog manager.</p>'),
        ]
        for days_ago, published, slug, title, body in blog_posts:
            b = Blog.query.filter_by(slug=slug).first()
            if b is None:
                b = Blog(slug=slug, author_id=admin.id)
                db.session.add(b)
            b.author_id, b.title, b.content = admin.id, title, body
            b.send_notification = False
            b.is_published = published
            b.published_at = (now - timedelta(days=days_ago)) if published else None
            b.created_at = now - timedelta(days=days_ago, hours=3)
        db.session.flush()

        # ---- reviews: six approved (live on the home page), three pending approval ----
        reviews = [
            ('user1@connectingdesis.com', 5, True, 3,
             'Found a companion for my mother within two days. The chat made coordinating at the airport easy.'),
            ('user2@connectingdesis.com', 5, True, 5,
             'I travel this route often and helping someone made the flight go faster. Lovely idea.'),
            ('user6@connectingdesis.com', 4, True, 8,
             'Got three matches for my multi-city trip. One did not reply, but support followed up for me.'),
            ('demo03@connectingdesis.com', 5, True, 12,
             'My parents had company from Hyderabad all the way to Chicago. Thank you Connecting Desis!'),
            ('demo07@connectingdesis.com', 4, True, 15,
             'Simple to post, and the anonymous option let me share details only after we matched.'),
            ('demo11@connectingdesis.com', 5, True, 21,
             'The claim link worked great - CS posted for my aunt from the Facebook group and we took over.'),
            ('user5@connectingdesis.com', 4, False, 1,
             'First international flight and I had someone to talk to at the gate. A rating option per leg would be nice.'),
            ('demo05@connectingdesis.com', 3, False, 2,
             'Good matches, but I wish alerts also came on WhatsApp. Waiting for that feature.'),
            ('demo09@connectingdesis.com', 5, False, 0,
             'Matched with a fellow Telugu speaker on the exact flight. Five stars.'),
        ]
        for email, rating, approved, days_ago, text in reviews:
            u = User.query.filter_by(email=email).first() or regular
            fb = Feedback.query.filter_by(user_id=u.id, comment=text).first()
            if fb is None:
                fb = Feedback(user_id=u.id, comment=text)
                db.session.add(fb)
            fb.rating, fb.is_approved = rating, approved
            fb.created_at = now - timedelta(days=days_ago, hours=5)

        # ---- contact enquiries in all three states (Voices > Contact, for CS and admin) ----
        enquiries = [
            ('Bhavani Devi', 'bhavani.devi@example.com', '+91 98490 11223',
             'I posted for my son travelling BLR to SEA but cannot log in any more - the password reset '
             'email never arrives. Can you help?', 'new', None, 0.2, None, None),
            ('Prakash Rao', 'prakash.rao@example.com', None,
             'Is there a way to search only for companions on Emirates flights via Dubai?', 'new', None, 1, None, None),
            ('Meera Iyer', 'meera.iyer@example.com', '+1 408 555 0188',
             'A member I matched with shared a phone number that seems out of service. What should I do next?',
             'in_progress', cs, 2, 'Called the other party once - no answer. Will retry tomorrow and update both sides.', None),
            ('Sunil Varma', 'sunil.varma@example.com', None,
             'Please delete my old post from March; the trip already happened.', 'closed', cs, 6,
             'Post closed on request, confirmation sent by email.', None),
            ('Uma Desis', 'user@connectingdesis.com', '+1 214 555 0170',
             'Loving the site - just wanted to say the new matching explanations are very clear!', 'closed',
             admin, 9, 'Thanked her; forwarded to the team channel.', 'user@connectingdesis.com'),
        ]
        for name, email, phone, message, status, handler, days_ago, notes, user_email in enquiries:
            m = ContactMessage.query.filter_by(email=email, message=message).first()
            if m is None:
                m = ContactMessage(name=name, email=email, phone=phone, message=message)
                db.session.add(m)
            if user_email:
                linked = User.query.filter_by(email=user_email).first()
                m.user_id = linked.id if linked else None
            m.set_status(status, by=handler)
            m.cs_notes = notes
            m.created_at = now - timedelta(days=days_ago)
            if status != 'new':
                m.handled_at = now - timedelta(days=max(days_ago - 1, 0))

        # ---- user@ portal: her own post that joins the QR573 crowd (dashboard, matches, chat) ----
        anchor_post = (CompanionRequest.query.filter_by(flight_number='QR573')
                       .filter(CompanionRequest.from_date >= today).first())
        anchor = anchor_post.from_date if anchor_post else today + timedelta(days=20)
        t = CompanionRequest.query.filter_by(user_id=regular.id, flight_number='QR573').first()
        if t is None:
            t = CompanionRequest(user_id=regular.id, travel_type='air', trip_type='one_way', source='organic')
            db.session.add(t)
        t.flying_from, t.destination, t.from_date = 'Hyderabad (HYD)', 'Dallas (DFW)', anchor
        t.airline, t.flight_number = 'Qatar Airways', 'QR573'
        t.preferred_languages = ['Telugu', 'English']
        t.role, t.ticket_booked = 'offering_help', True
        t.additional_comments = 'Flying for work; glad to keep an eye out for anyone travelling alone.'
        apply_route(t)
        t.set_status('open')
        db.session.flush()
        if not t.contact_points:
            db.session.add(ContactPoint(trip=t, user_id=regular.id, type='email', value=regular.email,
                                        consent_to_share=True, is_preferred=True, added_by='owner'))
        event_once('post_created', trip=t, actor=regular)

        # ---- CS-created posts awaiting claim (the CS home queues) ----
        def ensure_cs_post(poster, traveler, frm, to, days_out, created_days_ago, notes, flight=None):
            p = CompanionRequest.query.filter_by(poster_name=poster, created_by_id=cs.id).first()
            if p is None:
                p = CompanionRequest(travel_type='air', trip_type='one_way', user_id=None)
                db.session.add(p)
            p.created_by_id, p.source, p.source_url = cs.id, 'facebook', 'https://facebook.com/groups/connectingdesis'
            p.poster_name, p.traveler_name = poster, traveler
            p.flying_from, p.destination = frm, to
            p.from_date = today + timedelta(days=days_out)
            p.airline, p.flight_number = ('Qatar Airways', flight) if flight else (None, None)
            p.role, p.cs_notes = 'seeking_help', notes
            p.preferred_languages = ['Telugu', 'English']
            apply_route(p)
            p.set_status('unconfirmed')
            p.created_at = now - timedelta(days=created_days_ago)
            db.session.flush()
            return p

        p1 = ensure_cs_post('Sridevi Akka', 'Sridevi', 'Chennai (MAA)', 'Seattle (SEA)', 12, 5,
                            'From the Facebook group. Claim link sent; no reply yet - chase this week.', 'QR529')
        if not p1.claim_tokens.first():
            tok = ClaimToken.issue(p1, days=14, created_by=cs)
            db.session.flush()
            tok.created_at = now - timedelta(days=4)
        event_once('post_created', trip=p1, actor=cs)
        event_once('claim_link_issued', trip=p1, actor=cs)

        p2 = ensure_cs_post('Gopal Uncle', 'Gopal', 'Vijayawada (VGA)', 'Houston (IAH)', 18, 3,
                            'Posted in the group without contact details - need to DM for an email first.')
        event_once('post_created', trip=p2, actor=cs)

        # the same phone number on both posts -> the "repeated contact" queue lights up
        for p in (p1, p2):
            if not any(c.type == 'mobile' for c in p.contact_points):
                db.session.add(ContactPoint(trip=p, type='mobile', value='+91 90000 11223',
                                            consent_to_share=False, added_by='cs'))

        # a post departing in 2 days with nothing consented -> the "needs action" queue
        owner = User.query.filter_by(email='demo02@connectingdesis.com').first() or regular
        p3 = CompanionRequest.query.filter_by(user_id=owner.id, dest_city='Chicago').first()
        if p3 is None:
            p3 = CompanionRequest(user_id=owner.id, travel_type='air', trip_type='one_way', source='organic')
            db.session.add(p3)
        p3.flying_from, p3.destination = 'Hyderabad (HYD)', 'Chicago (ORD)'
        p3.from_date = today + timedelta(days=2)
        p3.airline, p3.flight_number = 'Lufthansa', 'LH753'
        p3.role, p3.preferred_languages = 'seeking_help', ['Hindi', 'English']
        p3.additional_comments = 'Short notice trip - grandmother needs company to Chicago.'
        apply_route(p3)
        p3.set_status('open')
        db.session.flush()

        # ---- a match escalated to CS (match tasks on the CS home + post detail timeline) ----
        escalated = 0
        for i, m in enumerate(Match.query.order_by(Match.score.desc(), Match.id.asc()).limit(2).all()):
            m.needs_cs_attention = True
            if i == 0:
                m.cs_owner_id = cs.id
                if m.status == 'suggested':
                    m.status = 'notified'
                pa = MatchParty.get_or_create(m, m.trip_a_id, channel='email')
                pa.status, pa.sent_at, pa.sent_by_id = 'no_response', now - timedelta(days=5), cs.id
                pa.escalated_at, pa.last_activity_at = now - timedelta(days=1), now - timedelta(days=5)
                pb = MatchParty.get_or_create(m, m.trip_b_id, channel='inapp')
                pb.status, pb.sent_at = 'opened', now - timedelta(days=5)
                pb.opened_at = pb.last_activity_at = now - timedelta(days=2)
                event_once('match_alert_sent', trip=m.trip_a, actor=cs, match_id=m.id)
                event_once('escalated', trip=m.trip_a, match_id=m.id, reason='no response for 5 days')
            escalated += 1

        # ---- notifications so the demo logins have a live bell ----
        def push_once(user, ntype, title, body, link):
            if Notification.query.filter_by(user_id=user.id, title=title).first():
                return
            if notify.push(user.id, ntype, title=title, body=body, link=link) is None:
                db.session.add(Notification(user_id=user.id, type=ntype, title=title, body=body, link=link))

        push_once(regular, 'blog', 'New on the blog: How our matching works',
                  'Leg-by-leg scoring, alerts and consent - explained in two minutes.', '/blog/how-matching-works')
        push_once(regular, 'match_found', 'You have new matches on HYD -> DFW',
                  'Travellers on Qatar Airways QR573 match your post.', '/dashboard')
        push_once(cs, 'cs_escalation', 'A match needs your attention',
                  'One side has not responded in 5 days.', '/cs')

        db.session.commit()
        matching.compute_matches_for(t)      # user@ joined after the bulk recompute
        matching.compute_matches_for(p3)
        click.echo(f'Content seeded: {Blog.query.count()} blog posts ({Blog.query.filter_by(is_published=False).count()} draft), '
                   f'{Feedback.query.count()} reviews ({Feedback.query.filter_by(is_approved=False).count()} pending), '
                   f'{ContactMessage.query.count()} contact enquiries, '
                   f'{CompanionRequest.query.filter_by(status="unconfirmed").count()} posts awaiting claim, '
                   f'{escalated} match(es) flagged for CS.')
        click.echo('Logins: admin@ / cs@ / user@ / super@connectingdesis.com - passwords in doc/keys.md.')

    @app.cli.command('seed-demo-all')
    @click.pass_context
    def seed_demo_all(ctx):
        """Every demo dataset in one go, so each admin / CS / user screen has data.

        Order: backfill-legs, seed-demo-match, seed-demo-user6, seed-demo-trips,
        seed-demo-inbox, seed-demo-content. Everything is idempotent - safe to re-run.
        """
        for cmd in (backfill_legs, seed_demo_match, seed_demo_user6, seed_demo_trips,
                    seed_demo_inbox, seed_demo_content):
            click.echo(f'== {cmd.name} ==')
            ctx.invoke(cmd)
        click.echo('== done: all demo data in place ==')
