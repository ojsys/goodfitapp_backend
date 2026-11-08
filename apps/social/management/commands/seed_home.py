"""
Development data for Home: clubs, members, rides and activities around
Prospect Park, so the feed and the new-member Home have something to show.

    python manage.py seed_home --member you@example.com

Refuses to run unless DEBUG is on. Demo accounts use @demo.agoodfit.app
emails and can be removed with --clear.
"""

import datetime as dt
import math
import random

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.activities.models import Activity
from apps.events.models import Event, EventRSVP
from apps.users.age_gate import encrypt_birthday
from apps.users.models import User
from apps.social.models import Announcement, Club, ClubGoal, ClubMembership, Follow, Post, Prop, Comment
from apps.routes.models import Route

DOMAIN = 'demo.agoodfit.app'
PEOPLE = [
    ('drew', 'Drew', 'Bennett', 'Park Slope', ['cycling', 'running']),
    ('alex', 'Alex', 'Rivera', 'Williamsburg', ['running']),
    ('sasha', 'Sasha', 'Kim', 'Williamsburg', ['running', 'yoga']),
    ('marvel', 'Marvel', 'Marcel', 'Prospect Heights', ['cycling']),
    ('jordan', 'Jordan', 'Reyes', 'Bed-Stuy', ['cycling']),
    ('nia', 'Nia', 'Park', 'Crown Heights', ['yoga', 'running']),
    ('theo', 'Theo', 'Owens', 'Park Slope', ['cycling', 'hiking']),
]
CLUBS = [
    ('GoodCo Bike Club', 'GC', '#5E7233', 'Brooklyn', 'Rides every weekend', ['cycling'], True),
    ('Prospect Run Crew', 'PR', '#8A5C46', 'Prospect Park', 'Tue and Sat runs', ['running']),
    ('Brooklyn Yoga Collective', 'BY', '#7D6224', 'Fort Greene', 'Park flows', ['yoga', 'pilates']),
]


def loop(laps=1.0, n=360, t0=None, speed=6.0, seed=1):
    """A loop around Prospect Park's drive, 3.4 mi a lap."""
    rnd = random.Random(seed)
    c_lat, c_lng, r_lat, r_lng = 40.6608, -73.9695, 0.0086, 0.0072
    pts, t = [], t0 or 0
    total = int(n * laps)
    for i in range(total):
        a = 2 * math.pi * i / n + math.pi / 2
        lat = c_lat + r_lat * math.sin(a) + rnd.uniform(-0.00003, 0.00003)
        lng = c_lng + r_lng * math.cos(a) * (1 + 0.15 * math.sin(2 * a))
        alt = 45 + 14 * math.sin(a * 2) + 5 * math.sin(a * 7)
        pts.append({'lat': lat, 'lng': lng, 'alt': alt, 't': t, 'seg': 0})
        t += int(1000 * 15 / speed)
    return pts


class Command(BaseCommand):
    help = 'Seed development data for Home (DEBUG only).'

    def add_arguments(self, parser):
        parser.add_argument('--member', help='Email of your test account: follows, a club and RSVPs.')
        parser.add_argument('--new', action='store_true', help='Leave --member as a brand-new member (no club, no follows).')
        parser.add_argument('--clear', action='store_true', help='Remove demo data first.')

    def handle(self, *args, **o):
        if not settings.DEBUG:
            raise CommandError('seed_home only runs with DEBUG on.')
        if o['clear']:
            User.objects.filter(email__endswith='@' + DOMAIN).delete()
            Club.objects.filter(name__in=[c[0] for c in CLUBS]).delete()
            Event.objects.filter(title__in=['First Spin', 'Sunday Social Ride']).delete()

        now = timezone.now()
        people = {}
        for key, first, last, hood, interests in PEOPLE:
            u, created = User.objects.get_or_create(
                email=f'{key}@{DOMAIN}',
                defaults=dict(first_name=first, last_name=last, neighborhood=hood, intents=['community'],
                              interests=interests, photo_step_done=True, guidelines_agreed_at=now,
                              guidelines_version=settings.GUIDELINES_VERSION, timezone='America/New_York'),
            )
            if created:
                u.set_password('goodfit123')
                u.birthday_enc = encrypt_birthday(dt.date(1990, 5, 5))
                u.save()
            people[key] = u

        clubs = {}
        for name, initials, color, hood, tagline, interests, *house in CLUBS:
            club, _ = Club.objects.get_or_create(name=name, defaults=dict(
                initials=initials, color=color, neighborhood=hood, tagline=tagline, interests=interests,
                is_house=bool(house)))
            clubs[initials] = club
        for key in ('drew', 'marvel', 'jordan', 'theo', 'alex'):
            ClubMembership.objects.get_or_create(club=clubs['GC'], user=people[key],
                                                 defaults={'role': 'organizer' if key == 'drew' else 'member'})
        for key in ('alex', 'sasha', 'nia'):
            ClubMembership.objects.get_or_create(club=clubs['PR'], user=people[key])
        for key in ('sasha', 'nia'):
            ClubMembership.objects.get_or_create(club=clubs['BY'], user=people[key])

        days = (5 - now.weekday()) % 7 or 7  # next Saturday
        sat = (now + dt.timedelta(days=days)).replace(hour=14, minute=0, second=0, microsecond=0)
        first, _ = Event.objects.get_or_create(title='First Spin', defaults=dict(
            description='An easy loop for new riders. Loaner helmets at the start.', host=people['drew'],
            host_name='GoodCo Bike Club', vibe='Social', start_time=sat, location_name='Grand Army Plaza',
            location_address='Grand Army Plaza, Brooklyn, NY', club=clubs['GC'], leader=people['drew'],
            distance_m=3.4 * 1609.344, route_name='Prospect Park Loop', pace='Easy pace', no_drop=True,
            beginner_friendly=True, tags=['Loaner helmets']))
        social, _ = Event.objects.get_or_create(title='Sunday Social Ride', defaults=dict(
            description='A no-drop social ride.', host=people['drew'], host_name='GoodCo Bike Club',
            vibe='Social', start_time=sat + dt.timedelta(days=1, hours=-1), location_name='Grand Army Plaza',
            location_address='Grand Army Plaza, Brooklyn, NY', club=clubs['GC'], leader=people['drew'],
            distance_m=22 * 1609.344, pace='social pace', no_drop=True))
        for key in ('drew', 'alex', 'sasha', 'marvel', 'jordan', 'theo'):
            EventRSVP.objects.get_or_create(event=social, user=people[key])
        for key in ('drew', 'nia', 'theo'):
            EventRSVP.objects.get_or_create(event=first, user=people[key])

        if not Activity.objects.filter(user=people['marvel']).exists():
            specs = [
                ('marvel', 'ride', 'Golden hour loop before the heat', 7.3, 0.2, 7.0, 'Prospect Park, Brooklyn'),
                ('alex', 'run', 'Easy miles with the sunrise crew', 1.5, 0.9, 3.0, 'McCarren Park'),
                ('drew', 'ride', 'Saturday shakeout: 18 riders deep', 3.6, 25, 6.0, 'Greenpoint'),
                ('nia', 'yoga', 'Mobility reset after a heavy week', 0, 30, 0, 'Fort Greene'),
            ]
            for i, (key, kind, title, laps, hours_ago, speed, place) in enumerate(specs):
                start = now - dt.timedelta(hours=hours_ago)
                pts = loop(laps, t0=int(start.timestamp() * 1000), speed=speed, seed=i) if laps else []
                from apps.activities.record_views import track_stats
                dist, gain, _, _ = track_stats(pts) if pts else (0, 0, None, None)
                moving = int((pts[-1]['t'] - pts[0]['t']) / 1000) if pts else 2520
                a = Activity.objects.create(
                    user=people[key], type=kind, title=title, start_time=start, duration=moving // 60,
                    moving_time=moving, elapsed_time=moving + 120, distance=dist, elevation_gain=gain,
                    max_speed=speed * 3.6 * 1.5 if pts else None,
                    average_speed=(dist / 1000) / (moving / 3600) if dist else None,
                    visibility='everyone' if key != 'drew' else 'club', club=clubs['GC'] if key == 'drew' else None,
                    route=pts, start_address=place, route_name='Prospect Park Loop' if laps > 1 else '')
                for k2 in list(people)[: 3 + i]:
                    if k2 != key:
                        Prop.objects.get_or_create(user=people[k2], activity=a)
                Comment.objects.get_or_create(author=people['drew' if key != 'drew' else 'alex'], activity=a,
                                              defaults={'text': 'Strong finish on that last lap.'})

        # Phase 3: club page details, routes and a week of events.
        gc = clubs['GC']
        Club.objects.filter(pk=gc.pk).update(location='Brooklyn, NY', founded_year=2021)
        ClubMembership.objects.filter(club=gc, user=people['drew']).update(role='owner', title='Co-founder')
        ClubMembership.objects.filter(club=gc, user=people['marvel']).update(role='organizer')
        ClubMembership.objects.filter(club=gc, user=people['jordan']).update(role='ride_leader')
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        next_month = (month_start + dt.timedelta(days=32)).replace(day=1)
        ClubGoal.objects.get_or_create(club=gc, starts_at=month_start, defaults=dict(
            title='Ride 1,000 miles together', target_m=1000 * 1609.344, kinds=['ride'], ends_at=next_month))
        Announcement.objects.get_or_create(club=gc, pinned=True, defaults=dict(
            author=people['drew'], text='The Sunday Social Ride rolls at 8:00 AM from Grand Army Plaza. '
                                        'Lights and a helmet, and we wait at every turn.'))
        def route(name, pts, best_for, owner, **kw):
            from apps.routes.services import line_distance
            line = [[p['lat'], p['lng']] for p in pts]
            r, _ = Route.objects.get_or_create(name=name, defaults=dict(
                owner=owner, line=line, waypoints=line[::30], distance_m=line_distance(line), best_for=best_for,
                is_loop=True, club=gc, **kw))
            return r
        pp = route('Prospect Park Loop', loop(1.0), 'ride', people['drew'], elevation_gain_m=37)
        gp = route('Greenpoint Loop', loop(1.15, seed=7), 'ride', people['drew'], elevation_gain_m=9,
                   club_favorite=True)
        lm = route('Long Meadow Walk', loop(0.55, seed=3), 'walk', people['nia'], elevation_gain_m=12)
        Activity.objects.filter(user=people['marvel'], title__startswith='Golden').update(route_ref=pp)
        Event.objects.filter(title__in=['First Spin', 'Sunday Social Ride']).update(route=pp)
        plan = [
            (0, 18, 30, 'Track Night 5K', 'run', 'anyone', 'hard', None, 5000, None, clubs['PR']),
            (1, 17, 30, 'Sunset Yoga in the Park', 'yoga', 'anyone', 'easy', None, None, 60, clubs['BY']),
            (3, 8, 0, 'Greenpoint Shakeout', 'ride', 'anyone', 'easy', gp, None, None, gc),
            (3, 18, 0, 'Halloween Glow Walk', 'walk', 'anyone', 'easy', lm, None, None, None),
            (5, 7, 0, 'Strength in the Park', 'strength', 'anyone', 'moderate', None, None, 45, None),
            (6, 18, 30, 'Run Club Tuesday', 'run', 'anyone', 'moderate', None, 8000, None, clubs['PR']),
        ]
        import zoneinfo
        ny = zoneinfo.ZoneInfo('America/New_York')
        today = now.astimezone(ny).date()
        for offset, hh, mm, title, kind, who, level, rt, dist, dur, club in plan:
            start = dt.datetime.combine(today + dt.timedelta(days=offset + 1), dt.time(hh, mm), tzinfo=ny)
            e, created = Event.objects.get_or_create(title=title, defaults=dict(
                description='', host=people['drew'], host_name=club.name if club else 'Drew Bennett', vibe='Social',
                start_time=start, location_name='McCarren Park' if 'Greenpoint' in title else 'Prospect Park',
                location_address='Brooklyn, NY', latitude=40.665, longitude=-73.97, club=club,
                kind='club' if club else 'community', activity_type=kind, who_can_join=who, level=level,
                route=rt, distance_m=rt.distance_m if rt else dist, duration_min=dur,
                pace='Easy pace' if level == 'easy' else '', leader=people['drew']))
            if created:
                for key in list(people)[: 2 + offset % 4]:
                    EventRSVP.objects.get_or_create(event=e, user=people[key])
        # Fit Buddies profile extras and rough locations around Prospect Park.
        extras = {
            'jordan': (40.687, -73.941, ['Coffee after'], 'Post-Ride Snack?', '“Bagel, extra cream cheese. Non-negotiable.”'),
            'nia': (40.669, -73.944, ['Evenings'], '', ''),
            'sasha': (40.714, -73.961, ['Early mornings'], '', ''),
            'theo': (40.671, -73.981, ['Weekends'], '', ''),
        }
        for key, (lat, lng, tags, q, a) in extras.items():
            User.objects.filter(pk=people[key].pk).update(approx_lat=lat, approx_lng=lng, buddy_tags=tags,
                                                          prompt_question=q, prompt_answer=a,
                                                          id_verified=key == 'jordan')

        # Phase 5: someone else's post, to hide or report from the feed.
        Post.objects.get_or_create(author=people['alex'], text='Anyone up for a coffee ride Saturday? '
                                   'Thinking a Prospect Park loop, then pastries.',
                                   defaults={'audience': 'followers', 'type': 'moment'})

        # Phase 4: a ride chat and a direct message.
        from apps.chats import services as chat_svc
        from apps.chats.models import ChatMessage
        sunday = Event.objects.get(title='Sunday Social Ride')
        chat = chat_svc.join_ride_chat(sunday, people['drew'])
        if not ChatMessage.objects.filter(chat=chat).exists():
            for key in ('marvel', 'alex', 'sasha'):
                EventRSVP.objects.get_or_create(event=sunday, user=people[key])
            ClubMembership.objects.filter(club=gc, user=people['alex']).update(role='organizer')
            ClubMembership.objects.filter(club=gc, user=people['sasha']).update(role='ride_leader')
            ClubMembership.objects.get_or_create(club=gc, user=people['sasha'], defaults={'role': 'ride_leader'})
            lines = [
                ('marvel', 'Rolling out from Grand Army at 8 sharp. No drop for the first 10 miles.', None, 15),
                ('drew', 'Bringing a spare tube. Anyone need one?', None, 14),
                ('alex', '', pp, 2),
                ('sasha', 'Clocks fall back Sunday, so 8 AM will feel like 9. No excuses!', None, 1),
            ]
            for key, body, rt, hours_ago in lines:
                m = ChatMessage.objects.create(chat=chat, sender=people[key], body=body,
                                               attachment='route' if rt else '', route=rt)
                ChatMessage.objects.filter(pk=m.pk).update(created_at=now - dt.timedelta(hours=hours_ago))
            chat.last_message_at = now - dt.timedelta(hours=1)
            chat.save(update_fields=['last_message_at'])

        if o.get('member'):
            me = User.objects.filter(email=o['member']).first()
            if not me:
                raise CommandError(f"No account {o['member']}")
            if not o['new']:
                for key in ('marvel', 'alex', 'sasha', 'drew'):
                    Follow.objects.get_or_create(follower=me, followee=people[key])
                ClubMembership.objects.get_or_create(club=clubs['GC'], user=me)
                EventRSVP.objects.get_or_create(event=social, user=me)
                dm = chat_svc.direct_chat(me, people['jordan'])
                if not dm.messages.exists():
                    msg = ChatMessage.objects.create(chat=dm, sender=people['jordan'],
                                                     body='See you Saturday? I’ll be at the track entrance.')
                    dm.last_message_at = msg.created_at
                    dm.save(update_fields=['last_message_at'])
            self.stdout.write(f'Set up {me.email} ({"new member" if o["new"] else "member with follows and a club"}).')
        self.stdout.write(self.style.SUCCESS('Demo data ready.'))
