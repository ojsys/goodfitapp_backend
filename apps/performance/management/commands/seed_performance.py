"""Demo segments, rides, challenges and trophies (DEBUG only). Run after
seed_home:

    python manage.py seed_performance --member you@example.com

Segments are cut from the Prospect Park loop the demo riders ride, so
matching finds real efforts.
"""

import datetime as dt
import math

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.activities.models import Activity
from apps.activities.record_views import track_stats
from apps.performance import segments as seg_svc
from apps.performance.models import Challenge, ChallengeEntry, Segment, Trophy
from apps.social.management.commands.seed_home import loop
from apps.social.models import Club
from apps.users.models import User

MI = 1609.344


def arc(i0, i1, n=360):
    """Points of the (noise-free) loop from index i0 to i1, as a segment line."""
    c_lat, c_lng, r_lat, r_lng = 40.6608, -73.9695, 0.0086, 0.0072
    out = []
    for i in range(i0, i1 + 1):
        a = 2 * math.pi * i / n + math.pi / 2
        out.append([round(c_lat + r_lat * math.sin(a), 6),
                    round(c_lng + r_lng * math.cos(a) * (1 + 0.15 * math.sin(2 * a)), 6),
                    round(45 + 14 * math.sin(a * 2) + 5 * math.sin(a * 7), 1)])
    return out


class Command(BaseCommand):
    help = 'Seed demo segments, challenges and trophies (DEBUG only).'

    def add_arguments(self, parser):
        parser.add_argument('--member', required=True)

    def handle(self, *args, **o):
        if not settings.DEBUG:
            raise CommandError('Only with DEBUG on.')
        me = User.objects.filter(email=o['member']).first()
        if not me:
            raise CommandError(f"No account {o['member']}")
        now = timezone.now()

        for name, i0, i1 in [('Park Drive Sprint', 20, 84), ('Zoo Hill', 150, 182), ('Lakeside Straight', 220, 330)]:
            Segment.objects.get_or_create(name=name, defaults={'area': 'Prospect Park, Brooklyn', 'line': arc(i0, i1)})

        # Riders on the loop at different speeds (m/s), so the boards fill in.
        riders = [('marvel', 8.6), ('drew', 8.3), ('alex', 8.1), ('sasha', 7.4), ('theo', 7.0)]
        demo = {u.email.split('@')[0]: u for u in User.objects.filter(email__endswith='@demo.agoodfit.app')}
        mine = [('Monday morning ride', 7.9, 2), ('Wednesday evening ride', 7.6, 9), ('Long Sunday loop', 7.4, 16)]
        rides = [(demo[k], f'{k.title()} loop', s, 3) for k, s in riders if k in demo]
        rides += [(me, title, s, d) for title, s, d in mine]
        for user, title, speed, days in rides:
            if Activity.objects.filter(user=user, title=title).exists():
                continue
            start = now - dt.timedelta(days=days, hours=2)
            pts = loop(2.0, t0=int(start.timestamp() * 1000), speed=speed, seed=hash(title) % 97)
            dist, gain, _, _ = track_stats(pts)
            moving = int((pts[-1]['t'] - pts[0]['t']) / 1000)
            act = Activity.objects.create(user=user, type='ride', title=title, start_time=start, duration=moving // 60,
                                          moving_time=moving, elapsed_time=moving + 90, distance=dist,
                                          elevation_gain=gain, average_speed=(dist / 1000) / (moving / 3600),
                                          visibility='everyone', route=pts, start_address='Prospect Park, Brooklyn',
                                          route_name='Prospect Park Loop', start_latitude=pts[0]['lat'],
                                          start_longitude=pts[0]['lng'])
            seg_svc.record_efforts(act)

        gc = Club.objects.filter(name='GoodCo Bike Club').first()
        from apps.users.age_gate import safe_zone
        local = timezone.localtime(now, safe_zone(me.timezone))
        month0 = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month1 = (month0 + dt.timedelta(days=32)).replace(day=1)
        specs = [
            dict(title='Ride 500 miles', kind='distance', target=500 * MI, featured=True, trophy_label='500 mi',
                 activity_types=['ride'], icon='bike', color='olive'),
            dict(title='Climb 5,000 ft', kind='elevation', target=5000 / 3.28084, club=gc, trophy_label='5,000 ft',
                 activity_types=['ride'], icon='mountain', color='clay'),
            dict(title='Ride 4 days a week', kind='days_per_week', target=4, trophy_label='4 a week',
                 activity_types=['ride'], icon='bike', color='olive'),
            dict(title='Prospect Park Sweep', kind='segments', target=3, subtitle='Ride all 3 park segments',
                 trophy_label='Park sweep', activity_types=['ride'], icon='bridge', color='gold'),
            dict(title='Run 50 km', kind='distance', target=50000, trophy_label='50 km', activity_types=['run'],
                 icon='run', color='clay'),
        ]
        for spec in specs:
            ch, made = Challenge.objects.get_or_create(title=spec['title'], defaults={
                **spec, 'starts_at': month0, 'ends_at': month1})
            if spec['kind'] == 'segments' and made:
                ch.segments.set(Segment.objects.all())
            if spec['title'] != 'Run 50 km':
                ChallengeEntry.objects.get_or_create(challenge=ch, user=me)
            for u in list(demo.values())[:6]:
                ChallengeEntry.objects.get_or_create(challenge=ch, user=u)

        if not Trophy.objects.filter(user=me).exists():
            for months_ago, label in [(2, '400 mi'), (3, 'Gran Fondo'), (4, 'Everest 1k'), (5, '30 Rides')]:
                Trophy.objects.create(user=me, label=label, earned_at=now - dt.timedelta(days=30 * months_ago))
        call_command('match_segments', stdout=self.stdout)
        self.stdout.write(self.style.SUCCESS('Performance demo data ready.'))
