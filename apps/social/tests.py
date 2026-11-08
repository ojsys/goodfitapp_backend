"""Phase 2: feed, posts, props, comments, checklist, privacy, recording."""

import datetime as dt
import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.activities.models import Activity
from apps.events.models import Event, EventRSVP
from apps.users.age_gate import encrypt_birthday

from .models import Club, ClubMembership, Comment, Follow, Post, PrivacyZone, Prop
from .privacy import public_track, visible_range

User = get_user_model()

# A straight line north from Grand Army Plaza, a point every ~11 m.
BASE = (40.6740, -73.9700)


def line(n=300, seg_every=None, t0=1_730_000_000_000):
    pts = []
    for i in range(n):
        pts.append({'lat': BASE[0] + i * 0.0001, 'lng': BASE[1], 'alt': 50 + (i % 40),
                    't': t0 + i * 2000, 'seg': (i // seg_every) if seg_every else 0})
    return pts


def member(email, name='Shari Brown', **over):
    first, _, last = name.partition(' ')
    u = User.objects.create_user(email, 'goodfit123', first_name=first, last_name=last,
                                 intents=['community'], interests=over.pop('interests', ['cycling']),
                                 photo_step_done=True, guidelines_agreed_at=timezone.now(),
                                 guidelines_version='2026-10-29', **over)
    u.birthday_enc = encrypt_birthday(dt.date(1990, 1, 1))
    u.save()
    return u


class Base(TestCase):
    def setUp(self):
        self.me = member('me@example.com', 'Shari Brown')
        self.friend = member('friend@example.com', 'Marvel Marcel')
        self.stranger = member('stranger@example.com', 'Alex Rivera')
        Follow.objects.create(follower=self.me, followee=self.friend)

    def client_for(self, user):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(user).access_token}')
        return c

    def act(self, user, vis='followers', **kw):
        return Activity.objects.create(
            user=user, type=kw.pop('type', 'ride'), title=kw.pop('title', 'Loop'),
            start_time=kw.pop('start_time', timezone.now()), duration=30, moving_time=1800,
            distance=kw.pop('distance', 5000), visibility=vis, route=kw.pop('route', line()), **kw)


class FeedTests(Base):
    def feed(self, user, tab):
        r = self.client_for(user).get(f'/api/social/feed/?tab={tab}')
        self.assertEqual(r.status_code, 200, r.data)
        return [(i['kind'], i['id']) for i in r.data['items']]

    def test_following_shows_me_and_people_i_follow_only(self):
        mine = self.act(self.me)
        theirs = self.act(self.friend)
        stranger = self.act(self.stranger, vis='everyone')
        private = self.act(self.friend, vis='me')
        ids = self.feed(self.me, 'following')
        self.assertIn(('activity', mine.id), ids)
        self.assertIn(('activity', theirs.id), ids)
        self.assertNotIn(('activity', stranger.id), ids)
        self.assertNotIn(('activity', private.id), ids)

    def test_post_audiences_land_in_the_right_tab(self):
        club = Club.objects.create(name='GoodCo Bike Club', initials='GC')
        ClubMembership.objects.create(club=club, user=self.me)
        c = self.client_for(self.me)
        f = c.post('/api/social/posts/', {'text': 'hi', 'audience': 'followers'}, format='json')
        k = c.post('/api/social/posts/', {'text': 'club', 'audience': 'club', 'club': club.id}, format='json')
        m = c.post('/api/social/posts/', {'text': 'secret', 'audience': 'me'}, format='json')
        self.assertEqual(f.data['toast'], 'Posted to Following')
        self.assertEqual(k.data['toast'], 'Posted to GoodCo Bike Club')
        self.assertEqual(m.data['toast'], 'Saved to My Activity')
        following = self.feed(self.me, 'following')
        clubtab = self.feed(self.me, 'club')
        mine = self.feed(self.me, 'mine')
        fid, kid, mid = f.data['item']['id'], k.data['item']['id'], m.data['item']['id']
        self.assertIn(('post', fid), following)
        self.assertNotIn(('post', kid), following)
        self.assertNotIn(('post', mid), following)
        self.assertEqual(clubtab, [('post', kid)])
        self.assertEqual({('post', fid), ('post', kid), ('post', mid)}, set(mine))
        # A follower sees the Followers post, not the Only me one.
        Follow.objects.create(follower=self.friend, followee=self.me)
        theirs = self.feed(self.friend, 'following')
        self.assertIn(('post', fid), theirs)
        self.assertNotIn(('post', mid), theirs)

    def test_post_needs_text_photo_or_mood(self):
        c = self.client_for(self.me)
        self.assertEqual(c.post('/api/social/posts/', {'text': '  '}, format='json').status_code, 400)
        r = c.post('/api/social/posts/', {'type': 'checkin', 'mood': 'recharged'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(c.post('/api/social/posts/', {'type': 'moment', 'mood': 'tired'},
                                format='json').status_code, 400)

    def test_club_post_requires_membership(self):
        club = Club.objects.create(name='Other', initials='OT')
        r = self.client_for(self.me).post('/api/social/posts/', {'text': 'x', 'audience': 'club', 'club': club.id},
                                          format='json')
        self.assertEqual(r.data['code'], 'not_a_member')

    def test_only_author_deletes_and_props_comments_go_with_it(self):
        p = Post.objects.create(author=self.me, text='hi')
        Prop.objects.create(user=self.friend, post=p)
        Comment.objects.create(author=self.friend, post=p, text='nice')
        self.assertEqual(self.client_for(self.friend).delete(f'/api/social/posts/{p.id}/').status_code, 403)
        self.assertEqual(self.client_for(self.me).delete(f'/api/social/posts/{p.id}/').status_code, 204)
        self.assertFalse(Prop.objects.exists())
        self.assertFalse(Comment.objects.exists())

    def test_paging(self):
        now = timezone.now()
        for i in range(25):
            self.act(self.me, start_time=now - dt.timedelta(minutes=i))
        c = self.client_for(self.me)
        first = c.get('/api/social/feed/?tab=mine').data
        self.assertEqual(len(first['items']), 20)
        second = c.get('/api/social/feed/', {'tab': 'mine', 'before': first['next']}).data
        self.assertEqual(len(second['items']), 5)
        self.assertIsNone(second['next'])

    def test_pending_member_is_refused(self):
        pending = User.objects.create_user('p@example.com', 'goodfit123')
        r = self.client_for(pending).get('/api/social/feed/')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.data['code'], 'onboarding_incomplete')


class PropsCommentsTests(Base):
    def test_props_toggle_and_visibility(self):
        a = self.act(self.friend)
        c = self.client_for(self.me)
        r = c.post(f'/api/social/activities/{a.id}/props/')
        self.assertEqual(r.data, {'props': 1, 'propped': True})
        c.post(f'/api/social/activities/{a.id}/props/')  # twice is fine
        self.assertEqual(Prop.objects.count(), 1)
        self.assertEqual(c.delete(f'/api/social/activities/{a.id}/props/').data['props'], 0)
        # A stranger can't see a Followers activity, so can't prop or comment.
        s = self.client_for(self.stranger)
        self.assertEqual(s.post(f'/api/social/activities/{a.id}/props/').status_code, 404)
        self.assertEqual(s.post(f'/api/social/activities/{a.id}/comments/', {'text': 'x'}).status_code, 404)

    def test_comment(self):
        a = self.act(self.friend)
        c = self.client_for(self.me)
        r = c.post(f'/api/social/activities/{a.id}/comments/', {'text': 'Strong finish'}, format='json')
        self.assertEqual(r.status_code, 201)
        got = c.get(f'/api/social/activities/{a.id}/comments/').data
        self.assertEqual(got['count'], 1)
        self.assertEqual(got['items'][0]['text'], 'Strong finish')


class PrivacyTests(Base):
    def test_track_ends_trimmed_by_default(self):
        pts = [(p['lat'], p['lng']) for p in line()]
        visible = public_track(pts, self.me)
        # ~200 m of 11 m steps = 18-19 points off each end.
        self.assertLess(len(visible), len(pts) - 30)
        self.assertNotEqual(visible[0], pts[0])
        self.assertNotEqual(visible[-1], pts[-1])

    def test_zone_trims_more(self):
        PrivacyZone.objects.create(user=self.me, latitude=BASE[0], longitude=BASE[1], radius_m=500)
        pts = [(p['lat'], p['lng']) for p in line()]
        i, _ = visible_range(pts, self.me)
        self.assertGreater(i, 45 + 17)  # 500 m zone plus the 200 m end trim

    def test_detail_trims_for_others_but_not_owner(self):
        self.me.hide_track_ends = True
        self.me.save()
        a = self.act(self.me, vis='everyone')
        mine = self.client_for(self.me).get(f'/api/activities/{a.id}/detail/').data
        theirs = self.client_for(self.stranger).get(f'/api/activities/{a.id}/detail/').data
        self.assertEqual(len(mine['track']), 300)
        self.assertLess(len(theirs['track']), 270)
        self.assertNotEqual(theirs['track'][0], mine['track'][0])
        # The profile never gives others a position inside the trimmed part.
        self.assertIsNone(theirs['profile'][0]['p'])
        self.assertIsNotNone(mine['profile'][0]['p'])

    def test_only_me_is_hidden(self):
        a = self.act(self.me, vis='me')
        self.assertEqual(self.client_for(self.friend).get(f'/api/activities/{a.id}/detail/').status_code, 404)


class RecordTests(Base):
    def payload(self, **over):
        p = {'client_id': str(uuid.uuid4()), 'type': 'ride', 'title': 'Wednesday evening ride',
             'start_time': '2026-11-04T22:33:00+00:00', 'elapsed_time': 700, 'moving_time': 598,
             'effort': 2, 'visibility': 'followers', 'track': line(300, seg_every=150),
             'laps': [{'n': 1, 'distance': 1000, 'moving_time': 300}]}
        p.update(over)
        return p

    def test_record_is_idempotent(self):
        c = self.client_for(self.me)
        p = self.payload()
        first = c.post('/api/activities/record/', p, format='json')
        self.assertEqual(first.status_code, 201, first.data)
        again = c.post('/api/activities/record/', p, format='json')
        self.assertEqual(again.status_code, 200)
        self.assertEqual(first.data['id'], again.data['id'])
        self.assertEqual(Activity.objects.count(), 1)

    def test_distance_from_track_skips_pause_gap(self):
        r = self.client_for(self.me).post('/api/activities/record/', self.payload(), format='json').data
        # 299 steps of ~11.1 m, minus the one bridging the pause.
        self.assertAlmostEqual(r['distance'], 298 * 11.12, delta=20)
        self.assertEqual(r['moving_time'], 598)
        self.assertEqual(r['split_unit'], 'mi')
        # 2.06 mi: two full miles; a tail under a tenth of a mile is dropped.
        self.assertEqual([s['n'] for s in r['splits']], [1, 2])
        self.assertAlmostEqual(r['splits'][0]['distance'], 1609.344, delta=12)
        self.assertGreater(r['elevation_gain'], 0)

    def test_timer_activity_has_no_track(self):
        r = self.client_for(self.me).post('/api/activities/record/', self.payload(type='yoga', track=line()),
                                          format='json').data
        self.assertEqual(r['track'], [])
        self.assertEqual(r['distance'], 0)

    def test_invalid_values(self):
        c = self.client_for(self.me)
        self.assertEqual(c.post('/api/activities/record/', self.payload(type='swim'), format='json').status_code, 400)
        self.assertEqual(c.post('/api/activities/record/', self.payload(effort=7), format='json').status_code, 400)
        self.assertEqual(c.post('/api/activities/record/', self.payload(moving_time=900), format='json').status_code,
                         400)


class HomeTests(Base):
    def test_checklist_and_new_member_home(self):
        c = self.client_for(self.me)
        h = c.get('/api/social/home/').data
        self.assertEqual(h['checklist']['done'], 2)
        self.assertTrue(h['checklist']['new_member_home'])
        self.assertIn('clubs_near_you', h)
        club = Club.objects.create(name='GoodCo Bike Club', initials='GC', interests=['cycling'])
        c.post(f'/api/social/clubs/{club.id}/join/')
        c.post('/api/social/posts/', {'text': 'Hi! I’m Shari.', 'is_intro': True}, format='json')
        self.act(self.me)
        ev = Event.objects.create(title='First Spin', description='x', host=self.friend, host_name='Drew',
                                  vibe='Social', start_time=timezone.now() + dt.timedelta(days=2),
                                  location_name='Grand Army Plaza', location_address='x', beginner_friendly=True)
        EventRSVP.objects.create(event=ev, user=self.me)
        h = c.get('/api/social/home/').data
        self.assertEqual(h['checklist']['done'], 6)
        self.assertEqual(h['upcoming_ride']['title'], 'First Spin')
        c.patch('/api/social/checklist/', {'hidden': True}, format='json')
        self.assertFalse(c.get('/api/social/home/').data['checklist']['new_member_home'])

    def test_clubs_near_you_follow_interests(self):
        Club.objects.create(name='Prospect Run Crew', initials='PR', interests=['running'])
        Club.objects.create(name='GoodCo Bike Club', initials='GC', interests=['cycling'])
        h = self.client_for(self.me).get('/api/social/home/').data
        self.assertEqual(h['clubs_near_you']['clubs'][0]['name'], 'GoodCo Bike Club')
        self.assertEqual(h['clubs_near_you']['based_on'], 'Cycling')

    def test_week_uses_member_time_zone(self):
        self.me.timezone = 'America/New_York'
        self.me.save()
        # Monday 11:30 PM in New York is Tuesday in UTC.
        now = timezone.now()
        h = self.client_for(self.me).get('/api/social/home/').data['week']
        self.assertEqual(len(h['days']), 7)
        self.act(self.me, distance=1000, start_time=now)
        h2 = self.client_for(self.me).get('/api/social/home/').data['week']
        self.assertEqual(h2['activities'], h['activities'] + 1)
        self.assertEqual(h2['days'][h2['today']], h['days'][h['today']] + 1000)
