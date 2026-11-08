"""Phase 10: business portal and featured events. Sign-up, role checks,
review and charging on approval, placements and targeting in the app,
counts-only reporting with the minimum group size, check-in name sharing,
suggested rides, name flags, team invites and the permission grid, Stripe
webhooks, and serving the React portal."""

import datetime as dt
import hashlib
import hmac
import json
import time
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.events.models import Event, EventRSVP
from apps.notifications.models import Notification
from apps.social.models import Club, ClubMembership, ClubTeamLog, RideSuggestion
from apps.social.tests import member

from . import services as svc
from .models import BusinessAccount, BusinessMember, FeaturedImpression, FeaturedPlacement, NameFlag, TeamInvite

B = '/api/business/'


def future(days=5, hour=9):
    d = timezone.localdate() + dt.timedelta(days=days)
    return d.isoformat(), f'{hour:02d}:00'


class Base(TestCase):
    def tearDown(self):
        cache.clear()  # sign-in rate limits are shared with other apps' tests

    def setUp(self):
        self.owner = member('lena@lumen.example', 'Lena Moreau', timezone='America/New_York')
        self.lumen = BusinessAccount.objects.create(name='Lumen Yoga Studio', category='yoga', status='verified',
                                                    work_email='lena@lumen.example')
        BusinessMember.objects.create(account=self.lumen, user=self.owner, role='owner')
        self.fan = member('maya@example.com', 'Maya Ruiz', timezone='America/New_York')
        self.fan.neighborhood, self.fan.interests = 'Fort Greene', ['yoga']
        self.fan.save()
        self.staff = member('review@agoodfit.example', 'Rae View')
        self.staff.is_staff = True
        self.staff.save()

    def portal(self, user):
        c = APIClient()
        c.force_login(user)
        return c

    def app(self, user):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(user).access_token}')
        return c

    def draft(self, package='spotlight', hoods=('Fort Greene',), interests=('yoga',), days=5, submit=False, acct=None,
              user=None):
        date, time_ = future(days)
        acct = acct or self.lumen
        r = self.portal(user or self.owner).post(f'{B}a/{acct.id}/featured/', {
            'title': 'Sunrise Flow in the Park', 'date': date, 'time': time_, 'location': 'Fort Greene Park',
            'description': 'Free, mats provided.', 'package': package, 'neighborhoods': list(hoods),
            'interests': list(interests), 'submit': submit, 'timezone': 'America/New_York'}, format='json')
        return r

    def live(self, **kw):
        r = self.draft(submit=True, **kw)
        self.assertEqual(r.status_code, 201, r.data)
        p = FeaturedPlacement.objects.get(pk=r.data['id'])
        svc.approve(p, self.staff)
        p.refresh_from_db()
        return p


class SignupAndAccessTests(Base):
    def test_signup_makes_login_and_account(self):
        c = APIClient(enforce_csrf_checks=True)
        token = c.get(f'{B}session/').data['csrf']
        body = {'name': 'Pier Pilates', 'category': 'yoga', 'email': 'hi@pier.example', 'password': 'a-long-pass-99',
                'agree': True, 'contact': 'Ada Lane'}
        self.assertEqual(c.post(f'{B}signup/', body, format='json').status_code, 403)  # no CSRF token
        r = c.post(f'{B}signup/', body, format='json', HTTP_X_CSRFTOKEN=token)
        self.assertEqual(r.status_code, 201, r.data)
        acct = BusinessAccount.objects.get(pk=r.data['account'])
        self.assertEqual(acct.status, 'pending')
        self.assertIsNotNone(acct.agreed_at)
        self.assertEqual(r.data['accounts'][0]['role'], 'owner')

    def test_signup_needs_agreement_and_a_new_email(self):
        c = APIClient()
        r = c.post(f'{B}signup/', {'name': 'X Studio', 'email': 'new@x.example', 'password': 'a-long-pass-99'},
                   format='json')
        self.assertEqual(r.data['code'], 'agree')
        r = c.post(f'{B}signup/', {'name': 'X Studio', 'email': 'maya@example.com', 'password': 'a-long-pass-99',
                                   'agree': True}, format='json')
        self.assertEqual(r.status_code, 409)

    def test_login_and_accounts(self):
        c = APIClient()
        r = c.post(f'{B}login/', {'email': 'lena@lumen.example', 'password': 'goodfit123'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual([a['name'] for a in r.data['accounts']], ['Lumen Yoga Studio'])
        self.assertEqual(c.get(f'{B}a/{self.lumen.id}/overview/').status_code, 200)

    def test_outsiders_and_roles(self):
        self.assertEqual(self.portal(self.fan).get(f'{B}a/{self.lumen.id}/overview/').status_code, 403)
        self.assertEqual(APIClient().get(f'{B}a/{self.lumen.id}/overview/').status_code, 403)
        # A ride leader can't see event data or feature events.
        rl = member('rl@example.com', 'Ride Leader')
        BusinessMember.objects.create(account=self.lumen, user=rl, role='ride_leader')
        self.assertEqual(self.portal(rl).get(f'{B}a/{self.lumen.id}/overview/').status_code, 403)
        self.assertEqual(self.draft(user=rl).status_code, 403)
        # App tokens don't open the portal.
        self.assertEqual(self.app(self.owner).get(f'{B}a/{self.lumen.id}/overview/').status_code, 403)


class FeatureAndReviewTests(Base):
    def test_unverified_saves_a_draft_only(self):
        self.lumen.status = 'pending'
        self.lumen.save()
        r = self.draft(submit=True)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.data['code'], 'unverified')
        p = FeaturedPlacement.objects.get(pk=r.data['draft'])
        self.assertEqual(p.status, 'draft')
        self.assertFalse(p.event.is_active)  # nobody sees drafts

    def test_submit_approve_schedules_it(self):
        r = self.draft(submit=True)
        p = FeaturedPlacement.objects.get(pk=r.data['id'])
        self.assertEqual(p.status, 'in_review')
        svc.approve(p, self.staff)
        p.refresh_from_db()
        self.assertEqual(p.payment, 'not_billed')  # Stripe off
        self.assertEqual(p.ends_at, p.event.start_time)
        self.assertEqual(round((p.ends_at - p.starts_at).total_seconds() / 86400), 3)
        self.assertTrue(p.event.is_active)
        self.assertEqual(p.shown_status, 'scheduled')

    def test_send_back_and_edit(self):
        p = FeaturedPlacement.objects.get(pk=self.draft(submit=True).data['id'])
        svc.reject(p, self.staff, 'Add the price.')
        r = self.portal(self.owner).get(f'{B}a/{self.lumen.id}/overview/')
        self.assertEqual(r.data['events'][0]['status'], 'rejected')
        date, t = future(6)
        r = self.portal(self.owner).patch(f'{B}a/{self.lumen.id}/featured/{p.id}/', {
            'title': 'Sunrise Flow', 'date': date, 'time': t, 'location': 'Fort Greene Park', 'package': 'boost',
            'submit': True}, format='json')
        self.assertEqual(r.data['status'], 'in_review')

    def test_partner_package_needs_the_plan(self):
        r = self.draft(package='partner', submit=True)
        self.assertEqual(r.data['code'], 'partner_required')
        self.lumen.plan, self.lumen.plan_status = 'partner', 'active'
        self.lumen.save()
        for _ in range(4):
            self.assertEqual(self.draft(package='partner', submit=True).status_code, 201)
        self.assertEqual(self.draft(package='partner', submit=True).data['code'], 'partner_limit')

    @override_settings(STRIPE_SECRET_KEY='sk_test_x')
    def test_stripe_card_required_then_charged_on_approval(self):
        self.assertEqual(self.draft(submit=True).data['code'], 'card_required')
        self.lumen.stripe_payment_method, self.lumen.stripe_customer_id = 'pm_1', 'cus_1'
        self.lumen.save()
        p = FeaturedPlacement.objects.get(pk=self.draft(submit=True).data['id'])
        with mock.patch('apps.business.billing._call', return_value={'id': 'pi_1', 'status': 'succeeded'}) as call:
            svc.approve(p, self.staff)
        self.assertEqual(call.call_args[0][1], '/payment_intents')
        self.assertEqual(call.call_args[0][2]['amount'], '4900')
        p.refresh_from_db()
        self.assertEqual((p.payment, p.stripe_payment_intent, p.status), ('charged', 'pi_1', 'approved'))
        # Declined: stays in review, never goes live.
        p2 = FeaturedPlacement.objects.get(pk=self.draft(submit=True).data['id'])
        with mock.patch('apps.business.billing._call', return_value={'id': 'pi_2', 'status': 'requires_action'}):
            with self.assertRaises(svc.Denied):
                svc.approve(p2, self.staff)
        p2.refresh_from_db()
        self.assertEqual((p2.status, p2.payment), ('in_review', 'failed'))

    def test_house_account_is_free(self):
        club = Club.objects.create(name='GoodCo Bike Club', initials='GC', is_house=True)
        house = BusinessAccount.objects.create(name='GoodCo Bike Club', is_house=True, club=club)
        ClubMembership.objects.create(club=club, user=self.owner, role='owner')
        p = FeaturedPlacement.objects.get(pk=self.draft(acct=house, submit=True).data['id'])
        svc.approve(p, self.staff)
        p.refresh_from_db()
        self.assertEqual(p.payment, 'house')
        self.assertEqual(house.initials, 'GC')


class PlacementTests(Base):
    def test_targeting_and_surfaces(self):
        p = self.live(package='spotlight')
        p.starts_at = timezone.now() - dt.timedelta(hours=1)
        p.save()
        events = self.app(self.fan).get('/api/social/events/').data
        self.assertEqual(events['featured']['featured']['placement'], p.id)
        self.assertNotIn(p.event_id, [e['id'] for e in events['items']])
        why = events['featured']['featured']['why']
        self.assertIn('Lumen Yoga Studio paid to feature this event', why)
        self.assertIn('near Fort Greene', why)
        self.assertIn('into yoga', why)
        # Spotlight is Events only.
        self.assertIsNone(self.app(self.fan).get('/api/social/home/').data['featured'])
        # Not targeted: someone elsewhere into running.
        other = member('sam@example.com', 'Sam Lee')
        other.neighborhood, other.interests = 'Williamsburg', ['running']
        other.save()
        self.assertIsNone(self.app(other).get('/api/social/events/').data['featured'])

    def test_boost_on_home_partner_on_hub(self):
        p = self.live(package='boost')
        p.starts_at = timezone.now() - dt.timedelta(hours=1)
        p.save()
        self.assertEqual(self.app(self.fan).get('/api/social/home/').data['featured']['id'], p.event_id)
        self.assertIsNone(self.app(self.fan).get('/api/social/community/').data['featured'])
        self.lumen.plan, self.lumen.plan_status = 'partner', 'active'
        self.lumen.save()
        p.package = 'partner'
        p.save()
        self.assertEqual(self.app(self.fan).get('/api/social/community/').data['featured']['id'], p.event_id)

    def test_views_and_taps_count_once_a_day(self):
        p = self.live()
        c = self.app(self.fan)
        for _ in range(3):
            c.post(f'{B}featured/{p.id}/seen/', {'surface': 'events'}, format='json')
        c.post(f'{B}featured/{p.id}/tap/', {'surface': 'events'}, format='json')
        self.assertEqual(FeaturedImpression.objects.filter(placement=p).count(), 1)
        self.assertTrue(FeaturedImpression.objects.get(placement=p).tapped)


class ReportingTests(Base):
    def crowd(self, p, n, hood='Fort Greene', interest='yoga', checked=0, share=0):
        for i in range(n):
            u = member(f'u{hood[:2]}{i}@example.com', f'Person {i}')
            u.neighborhood, u.interests = hood, [interest]
            u.save()
            FeaturedImpression.objects.create(placement=p, user=u, day=timezone.localdate(), tapped=i % 2 == 0)
            EventRSVP.objects.create(event=p.event, user=u, status='going', checked_in=i < checked,
                                     check_in_time=timezone.now() if i < checked else None, share_name=i < share)

    def test_overview_and_results_are_counts_with_min_group(self):
        p = self.live()
        self.crowd(p, 12, checked=6, share=2)
        self.crowd(p, 4, hood='Park Slope', interest='running')
        o = self.portal(self.owner).get(f'{B}a/{self.lumen.id}/overview/').data
        self.assertEqual([s['value'] for s in o['stats']], [16, 8, 16, 6])
        r = self.portal(self.owner).get(f'{B}a/{self.lumen.id}/featured/{p.id}/results/').data
        self.assertEqual(r['neighborhoods'], [{'label': 'Fort Greene', 'pct': 75}, {'label': 'Other', 'pct': 25}])
        self.assertEqual(r['interests'][0], {'label': 'Yoga', 'pct': 75})
        self.assertEqual(len(r['shared_names']), 2)  # only those who chose to share
        self.assertNotIn('email', json.dumps(r))

    def test_small_groups_are_hidden(self):
        p = self.live()
        self.crowd(p, 6)
        r = self.portal(self.owner).get(f'{B}a/{self.lumen.id}/featured/{p.id}/results/').data
        self.assertIsNone(r['neighborhoods'])

    def test_check_in(self):
        p = self.live()
        e = p.event
        c = self.app(self.fan)
        self.assertEqual(c.post(f'/api/events/{e.id}/check-in/', {}, format='json').status_code, 400)
        EventRSVP.objects.create(event=e, user=self.fan, status='going')
        self.assertEqual(c.post(f'/api/events/{e.id}/check-in/', {}, format='json').status_code, 409)  # too early
        e.start_time = timezone.now() + dt.timedelta(minutes=30)
        e.save()
        r = c.post(f'/api/events/{e.id}/check-in/', {'share_name': True}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(EventRSVP.objects.get(event=e, user=self.fan).share_name)


class ClubTests(Base):
    def setUp(self):
        super().setUp()
        self.club = Club.objects.create(name='GoodCo Bike Club', initials='GC', is_house=True)
        self.house = BusinessAccount.objects.create(name='GoodCo Bike Club', is_house=True, club=self.club,
                                                    status='verified')
        self.shari = member('shari@example.com', 'Shari Brown')
        ClubMembership.objects.create(club=self.club, user=self.shari, role='owner')
        self.jordan = member('jordan@example.com', 'Jordan Reyes')
        self.sasha = member('sasha@example.com', 'Sasha Kim')
        ClubMembership.objects.create(club=self.club, user=self.sasha, role='ride_leader')
        start = (timezone.now() + dt.timedelta(days=4)).isoformat()
        self.s = RideSuggestion.objects.create(member=self.jordan, club=self.club, note='Easy loop.', proposal={
            'title': 'Sunrise Coffee Spin', 'start': start, 'meeting_spot': 'Grand Army Plaza', 'pace': 'social',
            'no_drop': True, 'capacity': 20, 'who_can_join': 'anyone', 'activity_type': 'ride'})

    def test_team_reaches_the_portal_through_the_club(self):
        accts = svc.accounts_for(self.shari)
        self.assertEqual([a.name for a in accts], ['GoodCo Bike Club'])
        self.assertEqual(svc.accounts_for(self.sasha), [])  # ride leaders don't need the portal

    def test_approve_decline_undo(self):
        c = self.portal(self.shari)
        r = c.get(f'{B}a/{self.house.id}/suggestions/').data
        self.assertEqual(r['suggestions'][0]['member']['line'], 'First ride they’ve suggested')
        r = c.post(f'{B}a/{self.house.id}/suggestions/{self.s.id}/approve/')
        self.assertEqual(r.data['status'], 'approved')
        self.s.refresh_from_db()
        self.assertEqual((self.s.event.kind, self.s.event.leader_id), ('club', self.jordan.id))
        self.assertTrue(Notification.objects.filter(recipient=self.jordan, kind='ride_update').exists())
        r = c.post(f'{B}a/{self.house.id}/suggestions/{self.s.id}/undo/')
        self.assertEqual(r.data['status'], 'new')
        self.assertFalse(Event.objects.filter(title='Sunrise Coffee Spin').exists())
        c.post(f'{B}a/{self.house.id}/suggestions/{self.s.id}/decline/')
        self.assertIn('can still host it', Notification.objects.filter(recipient=self.jordan).first().text)
        self.assertTrue(ClubTeamLog.objects.filter(club=self.club, action__startswith='declined').exists())

    def test_name_flags(self):
        e = Event.objects.create(title='GoodCo Late Night Loop', description='', host=self.jordan, host_name='J',
                                 vibe='Social', kind='community', start_time=timezone.now() + dt.timedelta(days=2),
                                 location_name='x', location_address='x')
        c = self.portal(self.shari)
        flags = c.get(f'{B}a/{self.house.id}/suggestions/').data['flags']
        self.assertEqual(flags[0]['title'], e.title)
        c.post(f'{B}a/{self.house.id}/flags/{flags[0]["id"]}/rename/')
        self.assertEqual(NameFlag.objects.get().status, 'asked')
        self.assertTrue(Notification.objects.filter(recipient=self.jordan, link=f'/events/{e.id}').exists())
        self.assertEqual(c.get(f'{B}a/{self.house.id}/suggestions/').data['flags'], [])

    def test_invite_accept_roles_and_grid(self):
        c = self.portal(self.shari)
        self.assertEqual(c.get(f'{B}a/{self.house.id}/team/?q=jor').data['people'][0]['id'], self.jordan.id)
        r = c.post(f'{B}a/{self.house.id}/team/invite/', {'user': self.jordan.id, 'role': 'ride_leader'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        inv = TeamInvite.objects.get(user=self.jordan)
        self.assertTrue(Notification.objects.filter(recipient=self.jordan, kind='team_invite').exists())
        club_page = self.app(self.jordan).get(f'/api/social/clubs/{self.club.id}/').data
        self.assertEqual(club_page['team_invite']['id'], inv.id)
        self.app(self.jordan).post(f'{B}invites/{inv.id}/accept/')
        self.assertEqual(ClubMembership.objects.get(club=self.club, user=self.jordan).role, 'ride_leader')
        # Owners can't be changed; others can.
        self.assertEqual(c.patch(f'{B}a/{self.house.id}/team/{self.shari.id}/', {'role': 'admin'},
                                 format='json').status_code, 409)
        c.patch(f'{B}a/{self.house.id}/team/{self.jordan.id}/', {'role': 'organizer'}, format='json')
        self.assertEqual(ClubMembership.objects.get(club=self.club, user=self.jordan).role, 'organizer')
        # Organizers can see the portal; turn off their suggestion approvals.
        r = c.patch(f'{B}a/{self.house.id}/team/grid/', {'role': 'organizer', 'perm': 'approve_suggestions',
                                                          'on': False}, format='json')
        self.assertNotIn('approve_suggestions', r.data['grid']['organizer'])
        self.assertEqual(self.portal(self.jordan).get(f'{B}a/{self.house.id}/suggestions/').status_code, 403)
        self.assertEqual(c.patch(f'{B}a/{self.house.id}/team/grid/', {'role': 'admin', 'perm': 'manage_billing',
                                                                      'on': True}, format='json').status_code, 409)
        c.delete(f'{B}a/{self.house.id}/team/{self.jordan.id}/')
        self.assertEqual(ClubMembership.objects.get(club=self.club, user=self.jordan).role, 'member')


@override_settings(STRIPE_WEBHOOK_SECRET='whsec_test', STRIPE_SECRET_KEY='sk_test_x')
class StripeTests(Base):
    def post(self, event, secret='whsec_test'):
        payload = json.dumps(event).encode()
        t = int(time.time())
        sig = hmac.new(secret.encode(), f'{t}.'.encode() + payload, hashlib.sha256).hexdigest()
        return APIClient().post(f'{B}stripe/webhook/', payload, content_type='application/json',
                                HTTP_STRIPE_SIGNATURE=f't={t},v1={sig}')

    def test_signature_and_partner_subscription(self):
        ev = {'type': 'customer.subscription.updated', 'data': {'object': {
            'id': 'sub_1', 'status': 'active', 'current_period_end': int(time.time()) + 86400 * 30,
            'metadata': {'account': str(self.lumen.id)}}}}
        self.assertEqual(self.post(ev, secret='wrong').status_code, 400)
        self.assertEqual(self.post(ev).status_code, 200)
        self.lumen.refresh_from_db()
        self.assertTrue(self.lumen.partner)
        ev['type'], ev['data']['object']['status'] = 'customer.subscription.deleted', 'canceled'
        self.post(ev)
        self.lumen.refresh_from_db()
        self.assertFalse(self.lumen.partner)

    def test_card_saved_from_checkout(self):
        ev = {'type': 'checkout.session.completed', 'data': {'object': {
            'mode': 'setup', 'setup_intent': 'seti_1', 'metadata': {'account': str(self.lumen.id)}}}}
        self.lumen.stripe_customer_id = 'cus_1'
        self.lumen.save()
        with mock.patch('apps.business.billing._call', side_effect=[{'payment_method': 'pm_9'}, {}]):
            self.assertEqual(self.post(ev).status_code, 200)
        self.lumen.refresh_from_db()
        self.assertEqual(self.lumen.stripe_payment_method, 'pm_9')


class PortalServingTests(TestCase):
    @override_settings(BUSINESS_HOST='business.testserver', ALLOWED_HOSTS=['*'])
    def test_portal_host_and_path(self):
        r = self.client.get('/overview', HTTP_HOST='business.testserver')
        self.assertIn(r.status_code, (200, 503))  # 503 until the portal is built
        r = self.client.get('/api/health/', HTTP_HOST='business.testserver')
        self.assertEqual(r.status_code, 200)
        self.assertIn(self.client.get('/business/team').status_code, (200, 503))
        self.assertEqual(self.client.get('/featured-events-policy/').status_code, 200)
        self.assertContains(self.client.get('/community-guidelines/'), 'Show up. Look out. Keep it kind.')
