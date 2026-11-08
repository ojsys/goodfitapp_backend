"""A Good Fit Plus: who has it, buying, restoring, store events, and the
Plus-only checks the rest of the API asks about.

user.plan is the cached answer ('free' or 'plus'); refresh_plan() recomputes
it from the member's subscriptions whenever one changes, and the hourly job
catches periods that ran out without a store event.
"""

import hashlib
import hmac
import logging
import uuid
from datetime import datetime, timedelta, timezone as dt_tz

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.users.age_gate import safe_zone

from . import stores
from .models import Subscription
from .stores import StoreError

log = logging.getLogger('agf.plus')
TRIAL_DAYS = 7


# ------------------------------------------------------------ who has Plus

def is_plus(user):
    return getattr(user, 'plan', 'free') == 'plus'


def refresh_plan(user):
    """Recompute user.plan from the subscriptions. Returns the plan."""
    now = timezone.now()
    for s in Subscription.objects.filter(user=user, status__in=Subscription.GRANTS, access_until__lte=now):
        s.status = 'expired'
        s.save(update_fields=['status', 'access_until', 'updated_at'])
    plan = 'plus' if any(s.grants for s in Subscription.objects.filter(user=user)) else 'free'
    if user.plan != plan:
        log.info('analytics plus_%s user=%s', 'upgrade' if plan == 'plus' else 'cancel', user.id)
        user.plan = plan
        user.save(update_fields=['plan'])
    return plan


def sweep():
    """Hourly: end Plus for periods that ran out without a store event."""
    from apps.users.models import User
    now = timezone.now()
    ids = set(Subscription.objects.filter(status__in=Subscription.GRANTS, access_until__lte=now)
              .values_list('user_id', flat=True))
    ids |= set(User.objects.filter(plan='plus').exclude(
        subscriptions__status__in=Subscription.GRANTS).values_list('id', flat=True))
    changed = 0
    for u in User.objects.filter(id__in=ids):
        before = u.plan
        if refresh_plan(u) != before:
            changed += 1
    return changed


def current(user):
    """The subscription that matters most for the Plus screen."""
    subs = list(Subscription.objects.filter(user=user).exclude(status='replaced'))
    live = [s for s in subs if s.grants]
    if live:
        return max(live, key=lambda s: (s.access_until is None, s.access_until or timezone.now()))
    return subs[0] if subs else None


def trial_available(user):
    """One free trial per member (the stores enforce theirs too)."""
    return not Subscription.objects.filter(user=user).exclude(store='comp').exists()


# ------------------------------------------------------------- the screen

def products():
    p = settings.PLUS_PRODUCTS
    return [
        {'id': 'yearly', 'title': 'Yearly', 'price': '$59.99 / year', 'note': '$5 a month · Save 37%',
         'store_ids': {'apple': p['yearly'], 'google': p['yearly']}},
        {'id': 'monthly', 'title': 'Monthly', 'price': '$7.99 / month', 'note': 'Cancel anytime',
         'store_ids': {'apple': p['monthly'], 'google': p['monthly']}},
    ]


def _day(dt, user):
    return f'{dt.astimezone(safe_zone(user.timezone)):%b} {dt.astimezone(safe_zone(user.timezone)).day}'


def status_line(s, user):
    if s is None:
        return ''
    end = s.access_until or s.expires_at
    if s.store == 'comp':
        return f'Plus from the A Good Fit team{f" until {_day(end, user)}" if end else ""}'
    if not s.grants:
        return {'on_hold': 'Your payment didn’t go through. Update it in your app store to keep Plus.',
                'pending': 'Waiting for your app store to confirm the payment.',
                'refunded': 'Your Plus purchase was refunded.'}.get(s.status, 'Your Plus subscription ended.')
    if s.status == 'grace':
        return f'Your payment didn’t go through. Update it in your app store by {_day(end, user)} to keep Plus.'
    if s.status == 'trial':
        return (f'Free trial · Plus starts {_day(end, user)}' if s.will_renew
                else f'Free trial · Ends {_day(end, user)}')
    return f'{"Renews" if s.will_renew else "Ends"} {_day(end, user)}' if end else 'Plus'


def manage_url(s):
    if s is None:
        return None
    if s.store == 'apple':
        return 'https://apps.apple.com/account/subscriptions'
    if s.store == 'google':
        pid = s.store_product_id or settings.PLUS_PRODUCTS.get(s.product, '')
        return (f'https://play.google.com/store/account/subscriptions?sku={pid}'
                f'&package={settings.GOOGLE_PLAY_PACKAGE}')
    return None


def payload(user):
    s = current(user)
    return {
        'plan': user.plan,
        'subscription': None if s is None else {
            'store': s.store, 'product': s.product, 'status': s.status, 'active': s.grants,
            'ends_at': (s.access_until or s.expires_at).isoformat() if (s.access_until or s.expires_at) else None,
            'will_renew': s.will_renew, 'line': status_line(s, user), 'manage_url': manage_url(s),
        },
        'trial_days': TRIAL_DAYS,
        'trial_available': trial_available(user),
        'products': products(),
        'account_token': account_token(user),
        'test_purchases': settings.PLUS_TEST_PURCHASES,
    }


# ------------------------------------------------- tying purchases to members

def account_token(user):
    """A UUID the app passes to the store (Apple appAccountToken, Play
    obfuscatedAccountId). It carries the member id plus a signature, so a
    store event names its member without a lookup table."""
    sig = hmac.new(settings.SECRET_KEY.encode(), f'plus:{user.id}'.encode(), hashlib.sha256).hexdigest()[:20]
    return str(uuid.UUID(sig + f'{user.id:012x}'))


def user_for_token(token):
    from apps.users.models import User
    try:
        h = uuid.UUID(str(token)).hex
        u = User.objects.get(pk=int(h[20:], 16))
    except (ValueError, TypeError, User.DoesNotExist):
        return None
    return u if hmac.compare_digest(account_token(u), str(uuid.UUID(h))) else None


def _owner_check(sub, user, token):
    """A purchase belongs to whoever bought it."""
    if sub is not None and sub.user_id != user.id and sub.user.is_active:
        raise StoreError('other_account', 'This subscription belongs to another A Good Fit account.', 409)
    if token and str(token).lower() != account_token(user):
        owner = user_for_token(token)
        if owner is not None and owner.id != user.id and owner.is_active:
            raise StoreError('other_account', 'This subscription belongs to another A Good Fit account.', 409)


def _ms(v):
    return datetime.fromtimestamp(int(v) / 1000, tz=dt_tz.utc) if v else None


def _iso(v):
    if not v:
        return None
    return datetime.fromisoformat(v.replace('Z', '+00:00'))


def _product_for(store_id):
    for k, v in settings.PLUS_PRODUCTS.items():
        if v == store_id:
            return k
    return None


# ------------------------------------------------------------------- Apple

def apply_apple(tx, renewal=None, user=None, event='', subtype='', signed_at=None):
    """Save what an Apple transaction (and renewal info) says. Returns the
    subscription, or None when it's for nobody we know."""
    stores.check_bundle(tx.get('bundleId'))
    product = _product_for(tx.get('productId'))
    if product is None:
        raise StoreError('unknown_product', 'That isn’t an A Good Fit Plus purchase.')
    original = str(tx.get('originalTransactionId') or tx.get('transactionId') or '')
    if not original:
        raise StoreError('invalid', 'That isn’t an App Store purchase.')
    with transaction.atomic():
        sub = Subscription.objects.select_for_update().filter(store='apple', original_id=original).first()
        token = tx.get('appAccountToken')
        if user is not None:
            _owner_check(sub, user, token)
        else:
            user = sub.user if sub else user_for_token(token)
            if user is None:
                log.warning('apple event %s for unknown purchase %s', event, original)
                return None
        signed_at = signed_at or _ms(tx.get('signedDate')) or timezone.now()
        if sub and sub.last_event_at and signed_at < sub.last_event_at:
            return sub  # older than what we already know (events can arrive out of order)
        sub = sub or Subscription(user=user, store='apple', original_id=original)
        now = timezone.now()
        expires = _ms(tx.get('expiresDate'))
        sub.product, sub.store_product_id = product, tx.get('productId', '')
        sub.environment = tx.get('environment', '')
        sub.expires_at = expires
        if renewal is not None:
            sub.will_renew = str(renewal.get('autoRenewStatus', 1)) == '1'
        if event == 'DID_CHANGE_RENEWAL_STATUS':
            sub.will_renew = subtype != 'AUTO_RENEW_DISABLED'
        grace = _ms((renewal or {}).get('gracePeriodExpiresDate'))
        if tx.get('revocationDate') or event in ('REFUND', 'REVOKE'):
            sub.status = 'refunded'
        elif event == 'DID_FAIL_TO_RENEW' or (renewal or {}).get('isInBillingRetryPeriod'):
            sub.status = 'grace' if grace and grace > now else 'on_hold'
        elif expires and expires > now:
            trial = tx.get('offerDiscountType') == 'FREE_TRIAL' or (
                tx.get('offerType') == 1 and not tx.get('offerDiscountType') and tx.get('price') == 0)
            sub.status = 'trial' if trial else 'active'
        else:
            sub.status = 'expired'
        sub.save()
        if sub.status == 'grace':
            sub.access_until = grace
            sub.save(update_fields=['access_until'])
        sub.last_event_at = signed_at
        sub.last_event = event or 'app'
        sub.save(update_fields=['last_event_at', 'last_event'])
    refresh_plan(sub.user)
    return sub


def apple_notification(signed_payload):
    """App Store Server Notifications V2."""
    n = stores.verify_apple_jws(signed_payload)
    data = n.get('data') or {}
    stores.check_bundle(data.get('bundleId'))
    event, subtype = n.get('notificationType', ''), n.get('subtype', '')
    if event == 'TEST' or not data.get('signedTransactionInfo'):
        return None
    tx = stores.verify_apple_jws(data['signedTransactionInfo'])
    renewal = stores.verify_apple_jws(data['signedRenewalInfo']) if data.get('signedRenewalInfo') else None
    return apply_apple(tx, renewal, event=event, subtype=subtype, signed_at=_ms(n.get('signedDate')))


# ------------------------------------------------------------------ Google

GOOGLE_STATES = {
    'SUBSCRIPTION_STATE_ACTIVE': 'active',
    'SUBSCRIPTION_STATE_IN_GRACE_PERIOD': 'grace',
    'SUBSCRIPTION_STATE_ON_HOLD': 'on_hold',
    'SUBSCRIPTION_STATE_PAUSED': 'on_hold',
    'SUBSCRIPTION_STATE_PENDING': 'pending',
    'SUBSCRIPTION_STATE_EXPIRED': 'expired',
}


def apply_google(token, data, user=None, event=''):
    """Save what Play says about a purchase token (subscriptionsv2)."""
    items = data.get('lineItems') or []
    item = next((i for i in items if _product_for(i.get('productId'))), None)
    if item is None:
        raise StoreError('unknown_product', 'That isn’t an A Good Fit Plus purchase.')
    with transaction.atomic():
        sub = Subscription.objects.select_for_update().filter(store='google', original_id=token).first()
        acct = (data.get('externalAccountIdentifiers') or {}).get('obfuscatedExternalAccountId')
        if user is not None:
            _owner_check(sub, user, acct)
        else:
            user = sub.user if sub else user_for_token(acct)
            if user is None:
                log.warning('google event %s for unknown purchase', event)
                return None
        sub = sub or Subscription(user=user, store='google', original_id=token)
        now = timezone.now()
        expires = _iso(item.get('expiryTime'))
        state = data.get('subscriptionState', '')
        sub.product, sub.store_product_id = _product_for(item['productId']), item['productId']
        sub.expires_at = expires
        sub.environment = 'Test' if data.get('testPurchase') is not None else 'Production'
        sub.will_renew = bool((item.get('autoRenewingPlan') or {}).get('autoRenewEnabled'))
        if event == 'voided':
            sub.status = 'refunded'
        elif state == 'SUBSCRIPTION_STATE_CANCELED':
            # Cancelled renewing; Plus lasts to the end of the period.
            sub.status = 'active' if expires and expires > now else 'expired'
            sub.will_renew = False
        else:
            sub.status = GOOGLE_STATES.get(state, 'expired')
        phase = item.get('offerPhase') or {}
        offer = (item.get('offerDetails') or {})
        if sub.status == 'active' and ('freeTrial' in phase or 'trial' in (offer.get('offerId') or '')
                                       or 'trial' in ' '.join(offer.get('offerTags') or [])):
            sub.status = 'trial'
        sub.last_event_at, sub.last_event = now, event or 'app'
        sub.save()
        # On Play a grace period runs to the line item's expiry.
        linked = data.get('linkedPurchaseToken')
        if linked:
            Subscription.objects.filter(store='google', original_id=linked).exclude(pk=sub.pk).update(
                status='replaced', updated_at=now)
    refresh_plan(sub.user)
    return sub


def google_notification(message):
    """Real-time developer notification (Pub/Sub push)."""
    import base64
    import json
    try:
        data = json.loads(base64.b64decode((message or {}).get('data') or ''))
    except (ValueError, TypeError):
        raise StoreError('invalid', 'Bad notification.')
    if settings.GOOGLE_PLAY_PACKAGE and data.get('packageName') not in (None, settings.GOOGLE_PLAY_PACKAGE):
        raise StoreError('wrong_app', 'That notification is for a different app.')
    if data.get('voidedPurchaseNotification'):
        token = data['voidedPurchaseNotification'].get('purchaseToken')
        sub = Subscription.objects.filter(store='google', original_id=token).first()
        if sub:
            sub.status, sub.last_event, sub.last_event_at = 'refunded', 'voided', timezone.now()
            sub.save()
            refresh_plan(sub.user)
        return sub
    note = data.get('subscriptionNotification')
    if not note:
        return None  # testNotification, one-time products
    token = note.get('purchaseToken')
    return apply_google(token, stores.google_subscription(token), event=f'rtdn:{note.get("notificationType")}')


# ------------------------------------------------------- from the app

def verify(user, store, data, product=None):
    """The app finished (or restored) a purchase. Returns (subscription, started)."""
    was = user.plan
    if store == 'apple':
        sub = apply_apple(stores.verify_apple_jws(data), user=user)
    elif store == 'google':
        sub = apply_google(data, stores.google_subscription(data), user=user)
    elif store == 'test':
        if not settings.PLUS_TEST_PURCHASES:
            raise StoreError('store_unavailable', 'Test purchases are off on this server.', 403)
        if product not in ('monthly', 'yearly'):
            raise StoreError('unknown_product', 'Pick monthly or yearly.')
        trial = trial_available(user)
        now = timezone.now()
        sub, _ = Subscription.objects.get_or_create(user=user, store='test', original_id=f'test:{user.id}')
        sub.product = product
        sub.status = 'trial' if trial else 'active'
        sub.started_at = now
        sub.expires_at = now + timedelta(days=TRIAL_DAYS if trial else (365 if product == 'yearly' else 30))
        sub.will_renew = True
        sub.environment = 'Test'
        sub.last_event, sub.last_event_at = 'app', now
        sub.save()
        refresh_plan(user)
    else:
        raise StoreError('store', 'Unknown store.')
    if sub is None:
        raise StoreError('invalid', 'That purchase couldn’t be checked.')
    user.refresh_from_db(fields=['plan'])
    return sub, (was != 'plus' and user.plan == 'plus')


def end_test(user):
    Subscription.objects.filter(user=user, store='test').delete()
    refresh_plan(user)


# ---------------------------------------------------- Plus-only features

def rsvp_opens_at(event):
    """Early RSVP: capped rides open to Plus members first. Everyone else can
    RSVP EARLY_RSVP_HOURS after it's posted (and at least two days before it
    starts). None once it's open to all."""
    if not event.max_attendees or not event.created_at:
        return None
    opens = min(event.created_at + timedelta(hours=settings.EARLY_RSVP_HOURS),
                event.start_time - timedelta(hours=48))
    return opens if opens > timezone.now() else None


def early_rsvp(event, user):
    """For event cards: when RSVP opens to everyone, if it hasn't yet."""
    opens = rsvp_opens_at(event)
    if opens is None:
        return None
    t = opens.astimezone(safe_zone(user.timezone))
    return {'opens': opens.isoformat(), 'label': f'{t:%a} {t:%-I:%M %p}', 'plus': is_plus(user)}


def rsvp_blocked(event, user):
    """Message if a free member is too early, else None."""
    if is_plus(user) or (event.host_id == user.id) or (event.leader_id == user.id):
        return None
    e = early_rsvp(event, user)
    if not e:
        return None
    return f'Plus members get first dibs on this ride. RSVP opens to everyone {e["label"]}.'


STORY_STYLES = [('classic', 'Classic', False), ('light', 'Light', True), ('olive', 'Olive', True),
                ('clay', 'Clay', True)]


def story_styles(user):
    plus = is_plus(user)
    return [{'id': i, 'name': n, 'locked': p and not plus} for i, n, p in STORY_STYLES]
