"""
Phase 1 tests: the 21+ age gate, sign-up flow and server-side membership.
"""

import datetime as dt
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .age_gate import compute_age, parse_birthday, AgeGateError, subject_hash
from .models import AgeGateEvent, SocialAgeBlock
from .social import SocialIdentity, SocialAuthError, verify_google

User = get_user_model()

NOW = dt.datetime(2026, 10, 29, 12, 0, tzinfo=dt.timezone.utc)


def bday(years_ago, days_offset=0):
    """A birthday exactly `years_ago` before NOW's date, shifted by days."""
    d = NOW.date().replace(year=NOW.year - years_ago)
    return d + dt.timedelta(days=days_offset)


class AgeMathTests(TestCase):
    def test_turns_21_today(self):
        self.assertEqual(compute_age(bday(21), 'UTC', NOW), 21)

    def test_turns_21_tomorrow(self):
        self.assertEqual(compute_age(bday(21, 1), 'UTC', NOW), 20)

    def test_member_time_zone_decides_the_date(self):
        # 2026-10-29 02:00 UTC is still Oct 28 in New York.
        now = dt.datetime(2026, 10, 29, 2, 0, tzinfo=dt.timezone.utc)
        birthday = dt.date(2005, 10, 29)
        self.assertEqual(compute_age(birthday, 'UTC', now), 21)
        self.assertEqual(compute_age(birthday, 'America/New_York', now), 20)

    def test_under_21_raises(self):
        b = bday(20)
        with self.assertRaises(AgeGateError) as ctx:
            parse_birthday(b.year, b.month, b.day, 'UTC', NOW)
        self.assertEqual(ctx.exception.code, 'under_21')

    def test_invalid_date(self):
        with self.assertRaises(AgeGateError) as ctx:
            parse_birthday(1990, 2, 30, 'UTC', NOW)
        self.assertEqual(ctx.exception.code, 'invalid_birthday')

    def test_unknown_time_zone_falls_back(self):
        self.assertEqual(compute_age(bday(30), 'Not/AZone', NOW), 30)


def register_payload(**over):
    p = {
        'full_name': 'Shari Brown',
        'birthday': {'year': 1992, 'month': 3, 'day': 14},
        'email': 'shari@example.com',
        'password': 'goodfit123',
        'timezone': 'America/New_York',
    }
    p.update(over)
    return p


class ApiTestCase(TestCase):
    def setUp(self):
        self.c = APIClient()

    def auth(self, token):
        self.c.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

    def register(self, **over):
        return self.c.post('/api/auth/register/', register_payload(**over), format='json')

    def finish_onboarding(self):
        self.c.patch('/api/auth/onboarding/', {'intents': ['community'], 'interests': ['cycling'],
                                               'photo_step_done': True}, format='json')
        return self.c.post('/api/auth/onboarding/guidelines/', {'agreed': True}, format='json')


class EmailSignUpTests(ApiTestCase):
    def test_register_creates_pending_account_with_encrypted_birthday(self):
        r = self.register()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['next_step'], 'intent')
        u = User.objects.get(email='shari@example.com')
        self.assertEqual(u.birthday, dt.date(1992, 3, 14))
        self.assertNotIn('1992', u.birthday_enc)
        self.assertFalse(u.is_member)
        self.assertTrue(AgeGateEvent.objects.filter(method='email', passed=True).exists())

    def test_under_21_creates_nothing(self):
        y = dt.date.today().year - 18
        r = self.register(birthday={'year': y, 'month': 1, 'day': 1})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.data['code'], 'under_21')
        self.assertFalse(User.objects.exists())
        self.assertTrue(AgeGateEvent.objects.filter(method='email', passed=False).exists())

    def test_short_password_rejected(self):
        self.assertEqual(self.register(password='short').status_code, 400)

    def test_duplicate_email_rejected(self):
        self.register()
        self.assertEqual(self.register().status_code, 400)

    def test_login_returns_next_step(self):
        self.register()
        r = self.c.post('/api/auth/login/', {'email': 'SHARI@example.com', 'password': 'goodfit123'},
                        format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['next_step'], 'intent')

    def test_bad_login(self):
        self.register()
        r = self.c.post('/api/auth/login/', {'email': 'shari@example.com', 'password': 'nope'}, format='json')
        self.assertEqual(r.status_code, 401)


class MembershipGateTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.auth(self.register().data['tokens']['access'])

    def test_pending_account_is_refused_outside_onboarding(self):
        r = self.c.get('/api/auth/stats/')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.data['code'], 'onboarding_incomplete')
        self.assertEqual(r.data['next_step'], 'intent')

    def test_profile_works_mid_sign_up(self):
        r = self.c.get('/api/auth/profile/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['next_step'], 'intent')
        self.assertEqual(r.data['birthday'], '1992-03-14')

    def test_full_flow_makes_a_member(self):
        r = self.c.patch('/api/auth/onboarding/', {'intents': ['romantic', 'community']}, format='json')
        self.assertEqual(r.data['next_step'], 'interests')
        self.assertEqual(r.data['user']['intents'], ['community', 'romantic'])
        r = self.c.patch('/api/auth/onboarding/', {'interests': ['yoga', 'cycling']}, format='json')
        self.assertEqual(r.data['next_step'], 'photo')
        r = self.c.patch('/api/auth/onboarding/', {'photo_step_done': True}, format='json')
        self.assertEqual(r.data['next_step'], 'guidelines')
        r = self.c.post('/api/auth/onboarding/guidelines/', {'agreed': True}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['next_step'], 'done')
        u = User.objects.get()
        self.assertEqual(u.guidelines_version, '2026-10-29')
        self.assertIsNotNone(u.guidelines_agreed_at)
        self.assertTrue(u.match_opted_in)
        self.assertEqual(self.c.get('/api/auth/stats/').status_code, 200)

    def test_interests_limited_to_three(self):
        r = self.c.patch('/api/auth/onboarding/', {'interests': ['yoga', 'hiit', 'hiking', 'running']},
                         format='json')
        self.assertEqual(r.status_code, 400)

    def test_unknown_interest_rejected(self):
        r = self.c.patch('/api/auth/onboarding/', {'interests': ['golf']}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_guidelines_need_explicit_agreement(self):
        r = self.c.post('/api/auth/onboarding/guidelines/', {}, format='json')
        self.assertEqual(r.data['code'], 'agreement_required')

    def test_guidelines_cannot_skip_steps(self):
        r = self.c.post('/api/auth/onboarding/guidelines/', {'agreed': True}, format='json')
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.data['next_step'], 'intent')

    def test_birthday_cannot_be_changed(self):
        r = self.c.post('/api/auth/signup/birthday/', {'year': 1980, 'month': 1, 'day': 1}, format='json')
        self.assertEqual(r.status_code, 409)
        self.finish_onboarding()
        self.c.patch('/api/auth/profile/update/', {'date_of_birth': '1980-01-01', 'bio': 'hi'}, format='json')
        self.assertEqual(User.objects.get().birthday, dt.date(1992, 3, 14))

    def test_bio_max_150(self):
        self.finish_onboarding()
        r = self.c.patch('/api/auth/profile/update/', {'bio': 'x' * 151}, format='json')
        self.assertEqual(r.status_code, 400)


APPLE = SocialIdentity(provider='apple', subject='apple-sub-1', email='hidden@privaterelay.appleid.com',
                       email_verified=True)


@mock.patch('apps.users.signup_views.verify_apple', return_value=APPLE)
class SocialSignUpTests(ApiTestCase):
    def sign_in(self):
        return self.c.post('/api/auth/apple/', {'identity_token': 'x', 'timezone': 'UTC'}, format='json')

    def test_new_apple_user_is_held_at_birthday(self, _):
        r = self.sign_in()
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['next_step'], 'birthday')
        self.assertTrue(r.data['is_new_user'])
        self.assertEqual(r.data['user']['signin_provider'], 'apple')
        self.auth(r.data['tokens']['access'])
        self.assertEqual(self.c.get('/api/auth/stats/').status_code, 403)

    def test_signing_in_again_resumes_at_birthday(self, _):
        self.sign_in()
        r = self.sign_in()
        self.assertEqual(r.data['next_step'], 'birthday')
        self.assertFalse(r.data['is_new_user'])
        self.assertEqual(User.objects.count(), 1)

    def test_birthday_pass_moves_on(self, _):
        self.auth(self.sign_in().data['tokens']['access'])
        r = self.c.post('/api/auth/signup/birthday/', {'year': 1990, 'month': 6, 'day': 1}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['next_step'], 'intent')

    def test_under_21_deletes_account_and_blocks_retry(self, _):
        self.auth(self.sign_in().data['tokens']['access'])
        y = dt.date.today().year - 19
        r = self.c.post('/api/auth/signup/birthday/', {'year': y, 'month': 1, 'day': 1}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.data['code'], 'under_21')
        self.assertFalse(User.objects.exists())
        block = SocialAgeBlock.objects.get()
        self.assertEqual(block.subject_hash, subject_hash('apple', 'apple-sub-1'))
        self.assertNotIn('apple-sub-1', block.subject_hash)
        self.c.credentials()
        r = self.sign_in()
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.data['code'], 'under_21_blocked')
        self.assertFalse(User.objects.exists())

    def test_links_existing_email_account(self, _):
        User.objects.create_user(email='hidden@privaterelay.appleid.com', password='goodfit123')
        r = self.sign_in()
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(User.objects.get().apple_sub, 'apple-sub-1')
        self.assertFalse(r.data['is_new_user'])


class GoogleAudienceTests(TestCase):
    @override_settings(GOOGLE_CLIENT_IDS=[])
    def test_not_configured(self):
        with self.assertRaises(SocialAuthError) as ctx:
            verify_google('t')
        self.assertEqual(ctx.exception.code, 'not_configured')

    @override_settings(GOOGLE_CLIENT_IDS=['ours.apps.googleusercontent.com'])
    @mock.patch('apps.users.social.google_id_token.verify_oauth2_token',
                return_value={'aud': 'someone-else', 'sub': '1', 'email': 'a@b.co'})
    def test_rejects_other_apps_tokens(self, _):
        with self.assertRaises(SocialAuthError) as ctx:
            verify_google('t')
        self.assertEqual(ctx.exception.code, 'invalid_token')


class ExistingAccountTests(ApiTestCase):
    def test_pre_gate_account_must_add_birthday(self):
        User.objects.create_user(email='old@example.com', password='goodfit123')
        r = self.c.post('/api/auth/login/', {'email': 'old@example.com', 'password': 'goodfit123'}, format='json')
        self.assertEqual(r.data['next_step'], 'birthday')


class PasswordResetTests(ApiTestCase):
    def test_sends_email_for_real_account(self):
        self.register()
        r = self.c.post('/api/auth/password/reset/', {'email': 'shari@example.com'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('/reset/', mail.outbox[0].body)

    def test_same_answer_for_unknown_email(self):
        r = self.c.post('/api/auth/password/reset/', {'email': 'nobody@example.com'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)

    def test_reset_link_page_renders(self):
        self.register()
        self.c.post('/api/auth/password/reset/', {'email': 'shari@example.com'}, format='json')
        link = [w for w in mail.outbox[0].body.split() if '/reset/' in w][0]
        path = link.split('localhost:8000')[-1]
        r = self.c.get(path, follow=True)
        self.assertContains(r, 'Set a new password')
