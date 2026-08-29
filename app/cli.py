"""Management commands: flask set-role / make-admin / backfill-locations."""
import click
from app import db


def register(app):

    @app.cli.command('set-role')
    @click.argument('email')
    @click.argument('role', type=click.Choice(['user', 'cs', 'admin']))
    def set_role(email, role):
        """Give a user the 'user', 'cs' (customer service) or 'admin' role."""
        from app.models import User
        u = User.query.filter_by(email=email.lower()).first()
        if not u:
            raise click.ClickException(f'No user with email {email}')
        u.role = role
        u.is_admin = (role == 'admin')
        db.session.commit()
        click.echo(f'{u.username} is now {role}')

    @app.cli.command('make-admin')
    @click.argument('email')
    def make_admin(email):
        """Shortcut for: set-role EMAIL admin."""
        from app.models import User
        u = User.query.filter_by(email=email.lower()).first()
        if not u:
            raise click.ClickException(f'No user with email {email}')
        u.role = 'admin'
        u.is_admin = True
        db.session.commit()
        click.echo(f'{u.username} is now admin')

    @app.cli.command('run-jobs')
    def run_jobs():
        """Escalate silent matches to CS and close departed posts (same as POST /internal/jobs/run)."""
        from app.services import jobs
        result = jobs.run_all()
        click.echo(f"escalated={result['escalated']} closed_departed={result['closed_departed']}")

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
