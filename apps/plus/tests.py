"""Phase 9: A Good Fit Plus. Purchases checked with the stores (a fake Apple
chain stands in for Apple's), renewals, grace periods, refunds and expiry
from store events, restore, one account per purchase, and the Plus-only
checks (early RSVP, story styles)."""

import base64
import datetime as dt
import json
import os
import tempfile
from unittest import mock

import jwt
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.social.home import event_card
from apps.social.tests import member
from apps.social.tests_community import event

from . import services as svc
from .models import Subscription
from .stores import APPLE_INTERMEDIATE_OID, APPLE_LEAF_OID

MONTHLY, YEARLY = 'agoodfit.plus.monthly', 'agoodfit.plus.yearly'
BUNDLE = 'app.agoodfit.test'


def _cert(name, key, issuer_name, issuer_key, oid=None, ca=False):
    now = dt.datetime.now(dt.timezone.utc)
    b = (x509.CertificateBuilder()
         .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)]))
         .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, issuer_name)]))
         .public_key(key.public_key()).serial_number(x509.random_serial_number())
         .not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=30))
         .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True))
    if oid is not None:
        b = b.add_extension(x509.UnrecognizedExtension(oid, b'\x05\x00'), critical=False)
    return b.sign(issuer_key, hashes.SHA256())


class FakeApple:
    """A root, a WWDR-like intermediate and a signing leaf, like Apple's."""

    def __init__(self):
        self.root_key = ec.generate_private_key(ec.SECP256R1())
        self.mid_key = ec.generate_private_key(ec.SECP256R1())
        self.leaf_key = ec.generate_private_key(ec.SECP256R1())
        self.root = _cert('Fake Apple Root', self.root_key, 'Fake Apple Root', self.root_key, ca=True)
        self.mid = _cert('Fake WWDR', self.mid_key, 'Fake Apple Root', self.root_key, APPLE_INTERMEDIATE_OID, ca=True)
        self.leaf = _cert('Fake Signing', self.leaf_key, 'Fake WWDR', self.mid_key, APPLE_LEAF_OID)
        fd, self.root_path = tempfile.mkstemp(suffix='.pem')
        os.write(fd, self.root.public_bytes(serialization.Encoding.PEM))
        os.close(fd)

    def sign(self, payload, leaf_key=None):
        x5c = [base64.b64encode(c.public_bytes(serialization.Encoding.DER)).decode()
               for c in (self.leaf, self.mid, self.root)]
        return jwt.encode(payload, leaf_key or self.leaf_key, algorithm='ES256', headers={'x5c': x5c})


def ms(t):
    return int(t.timestamp() * 1000)


APPLE = FakeApple()


@override_settings(APPLE_ROOT_CERTS=[APPLE.root_path], APPLE_BUNDLE_ID=BUNDLE, PLUS_TEST_PURCHASES=True,
                   GOOGLE_PLAY_PACKAGE='app.agoodfit', GOOGLE_PLAY_CREDENTIALS_JSON='{}', GOOGLE_RTDN_TOKEN='s3cret')
class Base(TestCase):
    def setUp(self):
        self.shari = member('shari@example.com', 'Shari Brown', timezone='America/New_York')
        self.alex = member('alex@example.com', 'Alex Rivera', timezone='America/New_York')

    def c(self, user=None):
        c = APIClient()
        if user:
            c.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(user).access_token}')
        return c

    def tx(self, user, original='1000001', days=7, trial=True, product=MONTHLY, signed=None, **kw):
        now = timezone.now()
        p = {'transactionId': kw.pop('transactionId', original), 'originalTransactionId': original,
             'bundleId': BUNDLE, 'productId': product, 'purchaseDate': ms(now), 'expiresDate': ms(now + dt.timedelta(days=days)),
             'type': 'Auto-Renewable Subscription', 'environment': 'Sandbox',
             'appAccountToken': svc.account_token(user) if user else None,
             'signedDate': ms(signed or now)}
        if trial:
            p.update(offerType=1, offerDiscountType='FREE_TRIAL')
        p.update(kw)
        return APPLE.sign(p)

    def notify(self, kind, tx, subtype='', renewal=None, signed=None):
        data = {'bundleId': BUNDLE, 'environment': 'Sandbox', 'signedTransactionInfo': tx}
        if renewal is not None:
            data['signedRenewalInfo'] = APPLE.sign(renewal)
        body = {'notificationType': kind, 'subtype': subtype, 'data': data,
                'signedDate': ms(signed or timezone.now()), 'notificationUUID': 'x'}
        return self.c().post('/api/plus/webhooks/apple/', {'signedPayload': APPLE.sign(body)}, format='json')

    def plan(self, user):
        user.refresh_from_db()
        return user.plan


class AccountTokenTests(Base):
    def test_token_names_its_member_and_cant_be_forged(self):
        t = svc.account_token(self.shari)
        self.assertEqual(svc.user_for_token(t), self.shari)
        forged = t[:-12] + f'{self.alex.id:012x}'
        self.assertIsNone(svc.user_for_token(forged))
        self.assertIsNone(svc.user_for_token('not a uuid'))


class AppleTests(Base):
    def test_purchase_starts_the_trial(self):
        r = self.c(self.shari).post('/api/plus/verify/', {'store': 'apple', 'data': self.tx(self.shari)}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data['started'])
        self.assertTrue(r.data['trial'])
        self.assertEqual(r.data['plan'], 'plus')
        self.assertTrue(r.data['subscription']['line'].startswith('Free trial · Plus starts'))
        self.assertEqual(r.data['subscription']['manage_url'], 'https://apps.apple.com/account/subscriptions')
        self.assertFalse(r.data['trial_available'])
        # Now Plus-only actions work.
        self.assertEqual(self.plan(self.shari), 'plus')

    def test_not_signed_by_apple_is_refused(self):
        other = FakeApple()  # a chain that doesn't end at the trusted root
        bad = other.sign({'originalTransactionId': '9', 'productId': MONTHLY, 'bundleId': BUNDLE,
                          'expiresDate': ms(timezone.now() + dt.timedelta(days=3))})
        r = self.c(self.shari).post('/api/plus/verify/', {'store': 'apple', 'data': bad}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data['code'], 'untrusted')
        # Right chain, wrong signing key.
        forged = APPLE.sign({'originalTransactionId': '9', 'productId': MONTHLY},
                            leaf_key=ec.generate_private_key(ec.SECP256R1()))
        r = self.c(self.shari).post('/api/plus/verify/', {'store': 'apple', 'data': forged}, format='json')
        self.assertEqual(r.data['code'], 'untrusted')
        self.assertEqual(self.plan(self.shari), 'free')

    def test_other_apps_and_products_are_refused(self):
        r = self.c(self.shari).post('/api/plus/verify/', {'store': 'apple', 'data': self.tx(self.shari, bundleId='x.y')},
                                    format='json')
        self.assertEqual(r.data['code'], 'wrong_app')
        r = self.c(self.shari).post('/api/plus/verify/', {'store': 'apple', 'data': self.tx(self.shari, product='x')},
                                    format='json')
        self.assertEqual(r.data['code'], 'unknown_product')

    def test_one_purchase_one_account(self):
        tx = self.tx(self.shari)
        self.c(self.shari).post('/api/plus/verify/', {'store': 'apple', 'data': tx}, format='json')
        r = self.c(self.alex).post('/api/plus/verify/', {'store': 'apple', 'data': tx}, format='json')
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.data['code'], 'other_account')
        r = self.c(self.alex).post('/api/plus/restore/', {'store': 'apple', 'items': [tx]}, format='json')
        self.assertEqual(r.data['code'], 'other_account')
        self.assertEqual(self.plan(self.alex), 'free')

    def test_renewal_grace_expiry_and_refund_from_notifications(self):
        self.c(self.shari).post('/api/plus/verify/', {'store': 'apple', 'data': self.tx(self.shari)}, format='json')
        # Trial converts: DID_RENEW, paid month.
        r = self.notify('DID_RENEW', self.tx(self.shari, days=30, trial=False, transactionId='2'),
                        renewal={'autoRenewStatus': 1})
        self.assertEqual(r.status_code, 200)
        sub = Subscription.objects.get(user=self.shari)
        self.assertEqual(sub.status, 'active')
        # Turned off auto-renew: still Plus to the end of the month.
        self.notify('DID_CHANGE_RENEWAL_STATUS', self.tx(self.shari, days=30, trial=False),
                    subtype='AUTO_RENEW_DISABLED', renewal={'autoRenewStatus': 0})
        sub.refresh_from_db()
        self.assertFalse(sub.will_renew)
        self.assertEqual(self.plan(self.shari), 'plus')
        # Payment fails with a grace period: keeps Plus until it ends.
        grace = timezone.now() + dt.timedelta(days=6)
        self.notify('DID_FAIL_TO_RENEW', self.tx(self.shari, days=-1, trial=False), subtype='GRACE_PERIOD',
                    renewal={'autoRenewStatus': 1, 'gracePeriodExpiresDate': ms(grace)})
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'grace')
        self.assertEqual(self.plan(self.shari), 'plus')
        self.assertIn('Update it in your app store', svc.status_line(sub, self.shari))
        # Grace runs out.
        self.notify('GRACE_PERIOD_EXPIRED', self.tx(self.shari, days=-1, trial=False))
        self.assertEqual(self.plan(self.shari), 'free')
        # Resubscribes, then refunded.
        self.notify('SUBSCRIBED', self.tx(self.shari, days=30, trial=False))
        self.assertEqual(self.plan(self.shari), 'plus')
        self.notify('REFUND', self.tx(self.shari, days=30, trial=False, revocationDate=ms(timezone.now())))
        self.assertEqual(Subscription.objects.get(user=self.shari).status, 'refunded')
        self.assertEqual(self.plan(self.shari), 'free')

    def test_old_events_dont_undo_newer_ones(self):
        self.notify('SUBSCRIBED', self.tx(self.shari, days=30, trial=False))
        self.notify('EXPIRED', self.tx(self.shari, days=-1, trial=False),
                    signed=timezone.now() - dt.timedelta(days=40))
        self.assertEqual(self.plan(self.shari), 'plus')

    def test_notification_before_the_app_reports_it(self):
        # The store tells us first; the account token names the member.
        r = self.notify('SUBSCRIBED', self.tx(self.shari))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.plan(self.shari), 'plus')
        # Unknown token: ignored, not an error.
        r = self.notify('SUBSCRIBED', self.tx(None, original='777'))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Subscription.objects.filter(original_id='777').exists())

    def test_bad_notification_is_refused(self):
        r = self.c().post('/api/plus/webhooks/apple/', {'signedPayload': 'a.b.c'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_restore(self):
        r = self.c(self.shari).post('/api/plus/restore/', {'store': 'apple', 'items': []}, format='json')
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.data['code'], 'nothing_to_restore')
        r = self.c(self.shari).post('/api/plus/restore/', {'store': 'apple', 'items': [self.tx(self.shari, trial=False)]},
                                    format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data['restored'])
        self.assertEqual(r.data['plan'], 'plus')


def play(state='SUBSCRIPTION_STATE_ACTIVE', days=30, product=YEARLY, user=None, renew=True, trial=False, **kw):
    item = {'productId': product, 'expiryTime': (timezone.now() + dt.timedelta(days=days)).isoformat(),
            'autoRenewingPlan': {'autoRenewEnabled': renew}, 'offerDetails': {'basePlanId': 'p1y'}}
    if trial:
        item['offerPhase'] = {'freeTrial': {}}
    d = {'subscriptionState': state, 'lineItems': [item]}
    if user:
        d['externalAccountIdentifiers'] = {'obfuscatedExternalAccountId': svc.account_token(user)}
    d.update(kw)
    return d


class GoogleTests(Base):
    def rtdn(self, token, kind=2, secret='s3cret', voided=False):
        data = {'packageName': 'app.agoodfit'}
        if voided:
            data['voidedPurchaseNotification'] = {'purchaseToken': token}
        else:
            data['subscriptionNotification'] = {'notificationType': kind, 'purchaseToken': token,
                                                'subscriptionId': YEARLY}
        msg = {'message': {'data': base64.b64encode(json.dumps(data).encode()).decode()}}
        return self.c().post(f'/api/plus/webhooks/google/?token={secret}', msg, format='json')

    def test_purchase_renewal_cancel_and_refund(self):
        with mock.patch('apps.plus.stores.google_subscription', return_value=play(user=self.shari, trial=True)):
            r = self.c(self.shari).post('/api/plus/verify/', {'store': 'google', 'data': 'tok-1'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data['trial'])
        self.assertEqual(r.data['subscription']['product'], 'yearly')
        self.assertIn('play.google.com', r.data['subscription']['manage_url'])
        # Cancelled renewing: Plus to the end of the period.
        with mock.patch('apps.plus.stores.google_subscription',
                        return_value=play('SUBSCRIPTION_STATE_CANCELED', renew=False)):
            self.assertEqual(self.rtdn('tok-1', kind=3).status_code, 200)
        sub = Subscription.objects.get(user=self.shari)
        self.assertEqual((sub.status, sub.will_renew), ('active', False))
        self.assertEqual(self.plan(self.shari), 'plus')
        # On hold (payment failed past grace): no Plus.
        with mock.patch('apps.plus.stores.google_subscription', return_value=play('SUBSCRIPTION_STATE_ON_HOLD')):
            self.rtdn('tok-1', kind=5)
        self.assertEqual(self.plan(self.shari), 'free')
        with mock.patch('apps.plus.stores.google_subscription', return_value=play()):
            self.rtdn('tok-1', kind=1)
        self.assertEqual(self.plan(self.shari), 'plus')
        self.rtdn('tok-1', voided=True)
        self.assertEqual(self.plan(self.shari), 'free')

    def test_upgrade_replaces_the_old_token(self):
        with mock.patch('apps.plus.stores.google_subscription', return_value=play(product=MONTHLY, user=self.shari)):
            self.c(self.shari).post('/api/plus/verify/', {'store': 'google', 'data': 'tok-old'}, format='json')
        with mock.patch('apps.plus.stores.google_subscription',
                        return_value=play(user=self.shari, linkedPurchaseToken='tok-old')):
            self.c(self.shari).post('/api/plus/verify/', {'store': 'google', 'data': 'tok-new'}, format='json')
        self.assertEqual(Subscription.objects.get(original_id='tok-old').status, 'replaced')
        self.assertEqual(svc.current(self.shari).original_id, 'tok-new')

    def test_someone_elses_purchase(self):
        with mock.patch('apps.plus.stores.google_subscription', return_value=play(user=self.alex)):
            r = self.c(self.shari).post('/api/plus/verify/', {'store': 'google', 'data': 'tok-2'}, format='json')
        self.assertEqual(r.status_code, 409)

    def test_webhook_needs_the_secret(self):
        self.assertEqual(self.rtdn('tok', secret='nope').status_code, 403)

    @override_settings(GOOGLE_PLAY_PACKAGE='')
    def test_not_set_up_yet(self):
        r = self.c(self.shari).post('/api/plus/verify/', {'store': 'google', 'data': 'tok'}, format='json')
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.data['code'], 'store_unavailable')


class TestStoreAndExpiryTests(Base):
    def test_test_purchase_trial_then_end(self):
        r = self.c(self.shari).get('/api/plus/')
        self.assertEqual(r.data['plan'], 'free')
        self.assertTrue(r.data['trial_available'])
        self.assertEqual([p['id'] for p in r.data['products']], ['yearly', 'monthly'])
        r = self.c(self.shari).post('/api/plus/verify/', {'store': 'test', 'product': 'yearly'}, format='json')
        self.assertTrue(r.data['started'] and r.data['trial'])
        r = self.c(self.shari).delete('/api/plus/')
        self.assertEqual(r.data['plan'], 'free')

    @override_settings(PLUS_TEST_PURCHASES=False)
    def test_test_store_is_off_in_production(self):
        r = self.c(self.shari).post('/api/plus/verify/', {'store': 'test', 'product': 'yearly'}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.c(self.shari).delete('/api/plus/').status_code, 403)

    def test_sweep_ends_periods_without_a_store_event(self):
        self.c(self.shari).post('/api/plus/verify/', {'store': 'test', 'product': 'monthly'}, format='json')
        Subscription.objects.filter(user=self.shari).update(access_until=timezone.now() - dt.timedelta(minutes=1))
        self.assertEqual(svc.sweep(), 1)
        self.assertEqual(self.plan(self.shari), 'free')
        self.assertEqual(Subscription.objects.get(user=self.shari).status, 'expired')

    def test_team_given_plus(self):
        Subscription.objects.create(user=self.alex, store='comp', status='active')
        svc.refresh_plan(self.alex)
        self.assertEqual(self.plan(self.alex), 'plus')
        self.assertEqual(svc.sweep(), 0)
        self.assertEqual(svc.payload(self.alex)['subscription']['line'], 'Plus from the A Good Fit team')

    def test_plus_set_by_hand_without_a_subscription_ends(self):
        self.alex.plan = 'plus'
        self.alex.save()
        svc.sweep()
        self.assertEqual(self.plan(self.alex), 'free')


class PlusFeatureTests(Base):
    def test_early_rsvp_on_capped_rides(self):
        host = member('host@example.com', 'Drew Host')
        ride = event(host, days=5, max_attendees=12)
        r = self.c(self.alex).post(f'/api/events/{ride.id}/rsvp/', {'status': 'going'}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.data['code'], 'early_rsvp')
        self.assertIn('Plus members get first dibs', r.data['message'])
        card = event_card(ride, self.alex)
        self.assertEqual(card['capacity'], 12)
        self.assertFalse(card['early']['plus'])
        # Plus members are in.
        self.c(self.shari).post('/api/plus/verify/', {'store': 'test', 'product': 'monthly'}, format='json')
        self.shari.refresh_from_db()
        r = self.c(self.shari).post(f'/api/events/{ride.id}/rsvp/', {'status': 'going'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        # A day later it's open to everyone.
        ride.created_at = timezone.now() - dt.timedelta(hours=25)
        ride.save()
        self.assertIsNone(event_card(ride, self.alex)['early'])
        r = self.c(self.alex).post(f'/api/events/{ride.id}/rsvp/', {'status': 'going'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)

    def test_uncapped_and_soon_rides_are_open(self):
        host = member('host@example.com', 'Drew Host')
        self.assertIsNone(svc.rsvp_opens_at(event(host, days=5)))
        self.assertIsNone(svc.rsvp_opens_at(event(host, days=1, max_attendees=10)))

    def test_story_styles(self):
        styles = svc.story_styles(self.alex)
        self.assertEqual([s['id'] for s in styles if not s['locked']], ['classic'])
        Subscription.objects.create(user=self.alex, store='comp')
        svc.refresh_plan(self.alex)
        self.assertFalse(any(s['locked'] for s in svc.story_styles(self.alex)))
