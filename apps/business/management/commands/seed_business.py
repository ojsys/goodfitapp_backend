"""
Development data for the business portal, from the 07-Business-Portal
screens: Lumen Yoga Studio (verified, Partner plan) with four featured
events (live, in review, draft, ended) and real-looking counts, and the
GoodCo house account (runs GoodCo Bike Club) with three suggested rides,
a community ride using the club's name and a pending team invite.

    python manage.py seed_home --member you@example.com     (first)
    python manage.py seed_business --member you@example.com

--member becomes an owner of GoodCo (house account) and sees Lumen's live
featured event in the app. Portal logins: lumen@demo.agoodfit.app and
your own member email, password goodfit123 for the demo ones.
Refuses to run unless DEBUG is on.
"""

import datetime as dt
import random

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.events.models import Event, EventRSVP
from apps.social.models import Club, ClubMembership, ClubTeamLog, RideSuggestion
from apps.users.age_gate import encrypt_birthday
from apps.users.models import User

from ...models import (BusinessAccount, BusinessMember, FeaturedImpression, FeaturedPlacement, NameFlag,
                       TeamInvite)

DOMAIN = 'demo.agoodfit.app'
HOODS = ['Fort Greene'] * 8 + ['Clinton Hill'] * 5 + ['Prospect Heights'] * 4 + ['Boerum Hill'] * 3 + \
        ['Park Slope', 'Williamsburg', 'Bed-Stuy', 'Crown Heights']
FIRST = ['Maya', 'Leo', 'Ava', 'Sam', 'Zoe', 'Eli', 'Ivy', 'Noah', 'Ruby', 'Kai', 'Lena', 'Omar', 'Tess', 'Jude',
         'Nora', 'Ezra', 'Mila', 'Finn', 'Rosa', 'Ben', 'Iris', 'Max', 'Cleo', 'Dev', 'June', 'Rafi', 'Ines', 'Gus',
         'Lila', 'Theo', 'Vera', 'Ari', 'Dana', 'Hugo', 'Elle', 'Remy', 'Skye', 'Otto', 'Pia', 'Cy']


class Command(BaseCommand):
    help = 'Seed business portal development data (DEBUG only).'

    def add_arguments(self, parser):
        parser.add_argument('--member', required=True, help='Email of your test account.')

    def handle(self, *args, **o):
        if not settings.DEBUG:
            raise CommandError('seed_business only runs with DEBUG on.')
        me = User.objects.filter(email=o['member']).first()
        if me is None:
            raise CommandError(f'No member {o["member"]}.')
        rnd = random.Random(7)
        now = timezone.now()
        tz = dt.timezone(dt.timedelta(hours=-5))

        # Members who see and RSVP to featured events.
        crowd = []
        for i, first in enumerate(FIRST):
            u, created = User.objects.get_or_create(email=f'fan{i}@{DOMAIN}', defaults=dict(
                first_name=first, last_name=chr(65 + i % 26) + 'x', neighborhood=HOODS[i % len(HOODS)],
                interests=(['yoga'] if i % 10 < 6 else ['running'] if i % 10 < 8 else ['cycling'])
                + (['pilates'] if i % 3 == 0 else []),
                intents=['community'], photo_step_done=True, guidelines_agreed_at=now,
                guidelines_version=settings.GUIDELINES_VERSION, timezone='America/New_York'))
            if created:
                u.set_password('goodfit123')
                u.birthday_enc = encrypt_birthday(dt.date(1992, 3, 3))
                u.save()
            crowd.append(u)
        me.neighborhood = me.neighborhood or 'Fort Greene'
        me.interests = list(dict.fromkeys((me.interests or []) + ['yoga']))[:3]
        me.save(update_fields=['neighborhood', 'interests'])

        # Lumen Yoga Studio.
        owner, created = User.objects.get_or_create(email=f'lumen@{DOMAIN}', defaults=dict(
            first_name='Lena', last_name='Moreau', timezone='America/New_York'))
        if created:
            owner.set_password('goodfit123')
            owner.save()
        lumen, _ = BusinessAccount.objects.update_or_create(name='Lumen Yoga Studio', defaults=dict(
            category='yoga', address='88 DeKalb Ave, Brooklyn, NY', website='@lumenyogabk',
            work_email=f'lumen@{DOMAIN}', status='verified', verified_at=now, plan='partner', plan_status='active',
            plan_renews_at=now + dt.timedelta(days=6), agreed_at=now))
        BusinessMember.objects.get_or_create(account=lumen, user=owner, defaults={'role': 'owner'})
        Event.objects.filter(placement__account=lumen).delete()

        def featured(title, days, hour, minute, place, status, package='partner', desc='', hoods=None, ints=None,
                     run_days=7):
            start = (now + dt.timedelta(days=days)).astimezone(tz).replace(hour=hour, minute=minute, second=0,
                                                                          microsecond=0)
            e = Event.objects.create(
                title=title, description=desc, host=owner, host_name=lumen.name, vibe='Chill', kind='featured',
                start_time=start, location_name=place, location_address=place, activity_type='class',
                duration_min=60, tags=['yoga'], is_active=status == 'approved', who_can_join='anyone',
                host_label='Hosted by Lumen Yoga Studio · Verified business', max_attendees=150)
            p = FeaturedPlacement.objects.create(
                account=lumen, event=e, package=package, status=status, created_by=owner,
                neighborhoods=hoods if hoods is not None else ['Fort Greene', 'Clinton Hill', 'Prospect Heights',
                                                               'Boerum Hill'],
                interests=ints if ints is not None else ['yoga', 'pilates'],
                price_cents=FeaturedPlacement.PACKAGES[package]['price'],
                submitted_at=now - dt.timedelta(days=run_days + 1) if status != 'draft' else None)
            if status == 'approved':
                p.starts_at, p.ends_at = start - dt.timedelta(days=run_days), start
                p.payment, p.reviewed_at = 'included', p.starts_at
                p.save()
            return p

        live = featured('Sunrise Flow in the Park', 2, 7, 30, 'Fort Greene Park', 'approved',
                        desc='60 min flow at sunrise. Free, mats provided.')
        featured('Pilates on the Pier', 8, 9, 0, 'Pier 6, Brooklyn Bridge Park', 'in_review', package='boost',
                 desc='A 50-minute mat Pilates class on the pier. All levels, mats provided.')
        featured('Full Moon Flow', 16, 19, 0, 'Fort Greene Park', 'draft')
        ended = featured('Fall Equinox Flow', -40, 8, 0, 'Fort Greene Park', 'approved')

        def activity(p, days, per_day, rsvp_share, checkin_share):
            start_day = timezone.localtime(p.starts_at).date()
            for d in range(days):
                day = start_day + dt.timedelta(days=d)
                if day > timezone.localdate():
                    break
                for u in rnd.sample(crowd, min(len(crowd), per_day + d * 2)):
                    FeaturedImpression.objects.get_or_create(placement=p, user=u, day=day,
                                                             defaults={'tapped': rnd.random() < 0.3})
            going = crowd[: int(len(crowd) * rsvp_share)]
            for u in going:
                r, _ = EventRSVP.objects.get_or_create(event=p.event, user=u, defaults={'status': 'going'})
                EventRSVP.objects.filter(pk=r.pk).update(created_at=p.starts_at + dt.timedelta(
                    days=rnd.randint(0, 5), hours=rnd.randint(0, 20)))
            if checkin_share:
                for i, u in enumerate(going[: int(len(going) * checkin_share)]):
                    EventRSVP.objects.filter(event=p.event, user=u).update(
                        checked_in=True, check_in_time=p.event.start_time + dt.timedelta(minutes=5),
                        share_name=i % 4 == 0)

        # Starting soon, so --member can check in (and share their name).
        soon = featured('Pier Stretch Pop-up', 0, 0, 0, 'Pier 6, Brooklyn Bridge Park', 'approved', package='boost',
                        desc='20 minutes of easy stretching on the pier. Free.', hoods=[], ints=[], run_days=3)
        soon.event.start_time = now + dt.timedelta(minutes=40)
        soon.event.save(update_fields=['start_time'])
        soon.ends_at = soon.event.start_time
        soon.save(update_fields=['ends_at'])
        EventRSVP.objects.get_or_create(event=soon.event, user=me, defaults={'status': 'going'})

        activity(live, 7, 20, 0.7, 0)
        activity(ended, 7, 16, 0.6, 0.75)

        # GoodCo: the house account runs GoodCo Bike Club.
        gc = Club.objects.filter(name='GoodCo Bike Club').first()
        if gc is None:
            raise CommandError('Run seed_home first (it creates GoodCo Bike Club).')
        house, _ = BusinessAccount.objects.update_or_create(name='GoodCo Bike Club', defaults=dict(
            category='shop', is_house=True, status='verified', verified_at=now, club=gc,
            work_email=f'hello@{DOMAIN}', agreed_at=now))
        m, _ = ClubMembership.objects.get_or_create(club=gc, user=me, defaults={'role': 'owner'})
        if m.role != 'owner':
            m.role, m.title = 'owner', 'Co-founder'
            m.save()
        people = {k: User.objects.filter(email=f'{k}@{DOMAIN}').first() for k in
                  ('drew', 'alex', 'sasha', 'marvel', 'jordan', 'nia')}
        for k, role, title in (('drew', 'owner', 'Co-founder'), ('marvel', 'owner', 'Co-founder'),
                               ('alex', 'organizer', ''), ('sasha', 'ride_leader', '')):
            if people[k]:
                ClubMembership.objects.update_or_create(club=gc, user=people[k], defaults={'role': role, 'title': title})
        if people['jordan']:
            ClubMembership.objects.filter(club=gc, user=people['jordan']).update(role='member')
            TeamInvite.objects.filter(club=gc, user=people['jordan']).delete()
            TeamInvite.objects.create(club=gc, user=people['jordan'], role='ride_leader', invited_by=people['marvel'])

        RideSuggestion.objects.filter(club=gc).delete()
        sat = (now + dt.timedelta(days=(5 - now.weekday()) % 7 or 7)).astimezone(tz)
        for who, title, when, spot, pace, note in (
            ('jordan', 'Sunrise Coffee Spin', sat.replace(hour=7, minute=0), 'Grand Army Plaza', 'social',
             'Easy loop, then coffee at the plaza. Great for newer riders.'),
            ('nia', 'Brownstone Roll', (sat + dt.timedelta(days=1)).replace(hour=10, minute=0),
             'Herbert Von King Park', 'social', 'Slow architecture ride through Bed-Stuy and Clinton Hill.'),
            ('sasha', 'Women’s Hill Repeats', (sat + dt.timedelta(days=4)).replace(hour=18, minute=30), 'Prospect Park',
             'steady', 'Monthly women’s session. Lights required.'),
        ):
            if people[who]:
                RideSuggestion.objects.create(member=people[who], club=gc, note=note, proposal={
                    'title': title, 'start': when.replace(second=0, microsecond=0).isoformat(),
                    'meeting_spot': spot, 'pace': pace, 'no_drop': pace == 'social', 'capacity': 20,
                    'who_can_join': 'anyone', 'activity_type': 'ride'})
        Event.objects.filter(title='GoodCo Late Night Loop').delete()
        if people['alex']:
            ricky, _ = User.objects.get_or_create(email=f'ricky@{DOMAIN}', defaults=dict(
                first_name='Ricky', last_name='Torres', guidelines_agreed_at=now, timezone='America/New_York',
                guidelines_version=settings.GUIDELINES_VERSION))
            Event.objects.create(title='GoodCo Late Night Loop', description='', host=ricky, host_name='Ricky T.',
                                 vibe='Social', kind='community', start_time=(sat - dt.timedelta(days=1)).replace(
                                     hour=23, minute=0), location_name='Grand Army Plaza',
                                 location_address='Grand Army Plaza', activity_type='ride')
        NameFlag.objects.filter(club=gc).delete()
        # An invite for --member to help run Prospect Run Crew (accept it in the app).
        prc = Club.objects.filter(name='Prospect Run Crew').first()
        if prc and people['alex']:
            ClubMembership.objects.filter(club=prc, user=me).exclude(role='member').update(role='member')
            TeamInvite.objects.filter(club=prc, user=me).delete()
            TeamInvite.objects.create(club=prc, user=me, role='organizer', invited_by=people['alex'])
        if not ClubTeamLog.objects.filter(club=gc).exists() and people['drew']:
            ClubTeamLog.objects.create(club=gc, actor=people['drew'], action='created Sunday Social Ride')
        self.stdout.write(self.style.SUCCESS(
            f'Lumen Yoga Studio (lumen@{DOMAIN} / goodfit123) and the GoodCo house account '
            f'({me.email} is an owner). Portal: http://127.0.0.1:8000/business/'))
