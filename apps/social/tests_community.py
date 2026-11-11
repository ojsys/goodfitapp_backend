"""Phase 3: hub, clubs, events browse, hosting, Fit Buddies, routes."""

import datetime as dt

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.activities.models import Activity
from apps.events.models import Event, EventRSVP
from apps.routes.models import Route

from .community_views import approve_suggestion
from .models import Club, ClubGoal, ClubMembership, Follow, Hide, RideInvite, RideSuggestion
from .tests import Base, line, member

LOOP = [[40.6608 + 0.0086 * (i % 2), -73.9695 + 0.001 * i] for i in range(10)]


def event(host, days=2, **kw):
    return Event.objects.create(title=kw.pop('title', 'Sunday Social Ride'), description='', host=host,
                                host_name='GoodCo', vibe='Social', start_time=timezone.now() + dt.timedelta(days=days),
                                location_name='Grand Army Plaza', location_address='x', **kw)


class ClubTests(Base):
    def setUp(self):
        super().setUp()
        self.club = Club.objects.create(name='GoodCo Bike Club', initials='GC', location='Brooklyn, NY',
                                        founded_year=2021)
        ClubMembership.objects.create(club=self.club, user=self.friend, role='owner', title='Co-founder')
        ClubMembership.objects.create(club=self.club, user=self.me, role='organizer')

    def test_permission_grid(self):
        org = ClubMembership.objects.get(user=self.me)
        self.assertTrue(org.can('create_events'))
        self.assertFalse(org.can('edit_club'))
        self.assertTrue(ClubMembership.objects.get(user=self.friend).can('manage_billing'))
        self.club.permissions = {'organizer': ['run_rides']}
        self.club.save()
        org.refresh_from_db()
        self.assertFalse(org.can('create_events'))

    def test_club_page_goal_leaders_team(self):
        now = timezone.now()
        ClubGoal.objects.create(club=self.club, title='Ride 10,000 miles together', target_m=10000,
                                starts_at=now - dt.timedelta(days=5), ends_at=now + dt.timedelta(days=3))
        self.act(self.me, distance=3000)
        self.act(self.friend, distance=5000)
        self.act(self.me, vis='me', distance=9999)  # Only me never counts
        r = self.client_for(self.me).get(f'/api/social/clubs/{self.club.id}/').data
        self.assertEqual(r['meta'], 'Brooklyn, NY · 2 members · Founded 2021')
        self.assertEqual(r['goal']['progress'], 8000)
        self.assertEqual(r['goal']['mine'], 3000)
        self.assertEqual(r['goal']['contributors'], 2)
        self.assertEqual([l['distance'] for l in r['leaders']], [5000, 3000])
        self.assertTrue(r['leaders'][1]['is_me'])
        self.assertEqual(r['team'][0]['label'], 'Co-founder · Owner')
        self.assertEqual(r['team'][1]['label'], 'Organizer')

    def test_hub(self):
        h = self.client_for(self.me).get('/api/social/community/').data
        self.assertEqual(h['clubs'][0]['name'], 'GoodCo Bike Club')
        self.assertEqual(h['clubs'][0]['role'], 'Organizer')
        self.assertFalse(h['match'])


class EventsTests(Base):
    def setUp(self):
        super().setUp()
        self.club = Club.objects.create(name='GoodCo Bike Club', initials='GC')
        ClubMembership.objects.create(club=self.club, user=self.friend)

    def test_club_only_events_hidden_from_non_members(self):
        e = event(self.friend, club=self.club, who_can_join='club')
        open_e = event(self.friend, title='Open ride', who_can_join='anyone')
        mine = self.client_for(self.me).get('/api/social/events/', {'date': e.start_time.astimezone(
            timezone.get_current_timezone()).date().isoformat()}).data
        ids = [i['id'] for i in mine['items']]
        self.assertNotIn(e.id, ids)
        self.assertIn(open_e.id, ids)
        self.assertEqual(len(mine['days']), 7)

    def test_friends_going_line_and_plans(self):
        e = event(self.friend)
        EventRSVP.objects.create(event=e, user=self.friend)
        EventRSVP.objects.create(event=e, user=self.me)
        r = self.client_for(self.me).get('/api/social/events/').data
        card = next(i for i in r['items'] if i['id'] == e.id)
        self.assertEqual(card['friends_line'], 'Marvel is going')
        self.assertEqual(card['kind_label'], 'Club')
        self.assertEqual([p['id'] for p in r['plans']], [e.id])

    def host_payload(self, **over):
        day = (timezone.now() + dt.timedelta(days=3)).date().isoformat()
        p = {'mode': 'community', 'title': 'Saturday Shakeout Ride', 'activity_type': 'ride', 'date': day,
             'time': '08:00', 'meeting_spot': 'Grand Army Plaza', 'pace': 'social', 'no_drop': True,
             'capacity': 20, 'who_can_join': 'anyone'}
        p.update(over)
        return p

    def test_community_ride_needs_plus_and_agreement(self):
        c = self.client_for(self.me)
        r = c.post('/api/social/events/host/', self.host_payload(), format='json')
        self.assertEqual(r.status_code, 402)
        self.me.plan = 'plus'
        self.me.save()
        r = c.post('/api/social/events/host/', self.host_payload(), format='json')
        self.assertEqual(r.data['code'], 'agreement_required')
        r = c.post('/api/social/events/host/', self.host_payload(agree=True), format='json')
        self.assertEqual(r.status_code, 201, r.data)
        e = Event.objects.get(title='Saturday Shakeout Ride')
        self.assertEqual(e.kind, 'community')
        self.assertTrue(EventRSVP.objects.filter(event=e, user=self.me).exists())
        # Agreement is remembered.
        r = c.post('/api/social/events/host/', self.host_payload(title='Again'), format='json')
        self.assertEqual(r.status_code, 201)

    def test_suggest_then_approve(self):
        ClubMembership.objects.create(club=self.club, user=self.me)
        c = self.client_for(self.me)
        r = c.post('/api/social/events/host/', self.host_payload(mode='suggest', club=self.club.id), format='json')
        self.assertEqual(r.status_code, 201, r.data)
        s = RideSuggestion.objects.get()
        self.assertEqual(s.status, 'new')
        self.assertFalse(Event.objects.exists())
        with self.assertRaises(PermissionError):
            approve_suggestion(s, self.stranger)
        ClubMembership.objects.filter(club=self.club, user=self.friend).update(role='organizer')
        e = approve_suggestion(s, self.friend)
        self.assertEqual((e.kind, e.club, e.leader), ('club', self.club, self.me))

    def test_suggest_requires_membership(self):
        r = self.client_for(self.me).post('/api/social/events/host/',
                                          self.host_payload(mode='suggest', club=self.club.id), format='json')
        self.assertEqual(r.data['code'], 'not_a_member')


class BuddiesTests(Base):
    def test_suggestions_hide_and_location(self):
        c = self.client_for(self.me)
        c.patch('/api/social/me/location/', {'latitude': 40.67891, 'longitude': -73.97123}, format='json')
        self.me.refresh_from_db()
        self.assertEqual((self.me.approx_lat, self.me.approx_lng), (40.68, -73.97))
        self.friend.approx_lat, self.friend.approx_lng = 40.69, -73.95
        self.friend.save()
        items = c.get('/api/social/buddies/').data['items']
        ids = [b['person']['id'] for b in items]
        self.assertIn(self.friend.id, ids)
        near = c.get('/api/social/buddies/', {'filter': 'near'}).data['items']
        self.assertEqual([b['person']['id'] for b in near], [self.friend.id])
        c.post(f'/api/social/buddies/{self.friend.id}/hide/')
        self.assertNotIn(self.friend.id, [b['person']['id'] for b in c.get('/api/social/buddies/').data['items']])
        c.delete(f'/api/social/buddies/{self.friend.id}/hide/')
        self.assertFalse(Hide.objects.exists())

    def test_invite_needs_your_rsvp(self):
        e = event(self.me)
        c = self.client_for(self.me)
        self.assertEqual(c.post(f'/api/social/buddies/{self.friend.id}/invite/', {'event': e.id},
                                format='json').status_code, 400)
        EventRSVP.objects.create(event=e, user=self.me)
        r = c.post(f'/api/social/buddies/{self.friend.id}/invite/', {'event': e.id}, format='json')
        self.assertTrue(r.data['invited'])
        self.assertTrue(RideInvite.objects.filter(recipient=self.friend).exists())


@override_settings(ROUTING_URL_BIKE='', ROUTING_URL_FOOT='', ELEVATION_URL='', FREE_ROUTE_LIMIT=2)
class RoutesTests(Base):
    def test_create_list_save_and_limit(self):
        c = self.client_for(self.me)
        r = c.post('/api/routes/', {'name': 'Morning Prospect Loop', 'waypoints': LOOP[:4], 'best_for': 'ride'},
                   format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertGreater(r.data['distance'], 1000)
        rid = r.data['id']
        c.post(f'/api/routes/{rid}/save/')
        self.assertEqual([x['id'] for x in c.get('/api/routes/', {'filter': 'saved'}).data['items']], [rid])
        c.post('/api/routes/', {'name': 'Second', 'waypoints': LOOP[:3]}, format='json')
        r = c.post('/api/routes/', {'name': 'Third', 'waypoints': LOOP[:3]}, format='json')
        self.assertEqual(r.status_code, 402)
        self.assertEqual(r.data['code'], 'plus_required')

    def test_visibility(self):
        Route.objects.create(owner=self.friend, name='Secret', line=LOOP, visibility='me')
        Route.objects.create(owner=self.friend, name='Open', line=LOOP, visibility='public')
        names = [x['name'] for x in self.client_for(self.me).get('/api/routes/').data['items']]
        self.assertEqual(names, ['Open'])

    def test_snap_falls_back_to_straight_lines(self):
        r = self.client_for(self.me).post('/api/routes/snap/', {'waypoints': LOOP[:3], 'best_for': 'run',
                                                                'is_loop': True}, format='json').data
        self.assertFalse(r['snapped'])
        self.assertEqual(len(r['line']), 4)
        self.assertEqual(r['line'][0], r['line'][-1])
        self.assertGreater(r['est_minutes'], 0)

    def test_route_card_social_proof(self):
        club = Club.objects.create(name='GoodCo', initials='GC')
        for u in (self.me, self.friend):
            ClubMembership.objects.create(club=club, user=u)
        route = Route.objects.create(owner=self.friend, name='Prospect Park Loop', line=LOOP, distance_m=5470)
        Activity.objects.create(user=self.friend, type='ride', title='x', start_time=timezone.now(), duration=10,
                                route_ref=route, route=line(20), visibility='everyone')
        event(self.friend, route=route)
        card = self.client_for(self.me).get('/api/routes/').data['items'][0]
        self.assertEqual(card['club_mates_this_week'], 1)
        self.assertEqual(card['riders'], 1)
        self.assertEqual(card['used_by_event']['title'], 'Sunday Social Ride')


class DetailsTests(Base):
    """Small things members see: event details, Saved Routes."""

    def test_own_routes_count_as_saved(self):
        c = self.client_for(self.me)
        r = c.post('/api/routes/', {'name': 'Morning loop', 'waypoints': LOOP[:4], 'best_for': 'ride'},
                   format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data['saved'])
        self.assertEqual(c.get('/api/social/me/profile/').data['saved_routes'], 1)
        self.assertEqual([x['id'] for x in c.get('/api/routes/?filter=saved').data['items']], [r.data['id']])
        # A saved route someone made private again leaves both the list and the count.
        theirs = Route.objects.create(owner=self.friend, name='Their loop', line=LOOP, distance_m=5000)
        c.post(f'/api/routes/{theirs.id}/save/')
        self.assertEqual(c.get('/api/social/me/profile/').data['saved_routes'], 2)
        theirs.visibility = 'me'
        theirs.save()
        self.assertEqual(c.get('/api/social/me/profile/').data['saved_routes'], 1)
        self.assertEqual(len(c.get('/api/routes/?filter=saved').data['items']), 1)

    def test_event_detail(self):
        club = Club.objects.create(name='GoodCo Bike Club', initials='GC')
        ClubMembership.objects.create(club=club, user=self.friend)
        route = Route.objects.create(owner=self.friend, name='Prospect Park Loop', line=LOOP, distance_m=5470)
        e = event(self.friend, route=route, leader=self.friend, club=club)
        Event.objects.filter(pk=e.pk).update(description='Coffee after.')
        c = self.client_for(self.me)
        d = c.get(f'/api/social/events/{e.id}/').data
        self.assertEqual(d['title'], 'Sunday Social Ride')
        self.assertEqual(d['description'], 'Coffee after.')
        self.assertEqual(d['route']['name'], 'Prospect Park Loop')
        self.assertEqual(d['leader_person']['id'], self.friend.id)
        self.assertIsNone(d['chat'])  # not going yet
        self.assertFalse(d['cancelled'])
        c.post(f'/api/events/{e.id}/rsvp/', {'status': 'going'}, format='json')
        d = c.get(f'/api/social/events/{e.id}/').data
        self.assertTrue(d['i_going'])
        self.assertIsNotNone(d['chat'])
        self.assertIn(self.me.id, [p['id'] for p in d['attendees']])
        # Cancelled rides still open (from the "cancelled" notification).
        e.is_cancelled = True
        e.save()
        self.assertTrue(c.get(f'/api/social/events/{e.id}/').data['cancelled'])

    def test_event_detail_hidden_like_browse(self):
        club = Club.objects.create(name='Private Club', initials='PC')
        e = event(self.friend, club=club, who_can_join='club')
        self.assertEqual(self.client_for(self.me).get(f'/api/social/events/{e.id}/').status_code, 404)
        ClubMembership.objects.create(club=club, user=self.me)
        self.assertEqual(self.client_for(self.me).get(f'/api/social/events/{e.id}/').status_code, 200)
