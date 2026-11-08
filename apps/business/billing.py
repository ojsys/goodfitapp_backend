"""Stripe for business packages (charged only after a featured event is
approved) and the Partner plan (a monthly subscription).

Off until STRIPE_SECRET_KEY is set: events are then approved without a
charge ("Approved without billing") and the Partner plan is set in the admin.

Card on file: Checkout in setup mode saves a card for off-session charges.
Approval charges it (PaymentIntent, off_session, confirm). Partner: Checkout
in subscription mode with STRIPE_PRICE_PARTNER. Webhooks keep the account in
step: checkout completed, subscription updated or deleted, invoice failed.
"""

import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timezone as dt_tz

import requests
from django.conf import settings

from .models import BusinessAccount

log = logging.getLogger('agf.business')
API = 'https://api.stripe.com/v1'


def configured():
    return bool(settings.STRIPE_SECRET_KEY)


class StripeError(Exception):
    pass


def _call(method, path, data=None, idempotency=None):
    headers = {'Authorization': f'Bearer {settings.STRIPE_SECRET_KEY}'}
    if idempotency:
        headers['Idempotency-Key'] = idempotency
    try:
        r = requests.request(method, f'{API}{path}', data=data, headers=headers, timeout=20)
    except requests.RequestException as e:
        raise StripeError(f'network: {e}')
    body = r.json() if r.content else {}
    if r.status_code >= 400:
        raise StripeError((body.get('error') or {}).get('message') or f'HTTP {r.status_code}')
    return body


def customer(acct):
    if acct.stripe_customer_id:
        return acct.stripe_customer_id
    c = _call('POST', '/customers', {'name': acct.name, 'email': acct.work_email,
                                     'metadata[account]': str(acct.id)}, idempotency=f'customer-{acct.id}')
    acct.stripe_customer_id = c['id']
    acct.save(update_fields=['stripe_customer_id'])
    return c['id']


def card_checkout(acct, return_url):
    s = _call('POST', '/checkout/sessions', {
        'mode': 'setup', 'customer': customer(acct), 'payment_method_types[]': 'card',
        'success_url': f'{return_url}{"&" if "?" in return_url else "?"}card=saved',
        'cancel_url': return_url, 'metadata[account]': str(acct.id), 'metadata[kind]': 'card',
    })
    return s['url']


def partner_checkout(acct, return_url):
    if not settings.STRIPE_PRICE_PARTNER:
        raise StripeError('The Partner plan price isn’t set up yet.')
    s = _call('POST', '/checkout/sessions', {
        'mode': 'subscription', 'customer': customer(acct),
        'line_items[0][price]': settings.STRIPE_PRICE_PARTNER, 'line_items[0][quantity]': '1',
        'success_url': f'{return_url}{"&" if "?" in return_url else "?"}partner=started', 'cancel_url': return_url,
        'metadata[account]': str(acct.id), 'metadata[kind]': 'partner',
        'subscription_data[metadata][account]': str(acct.id),
    })
    return s['url']


def manage_url(acct, return_url):
    s = _call('POST', '/billing_portal/sessions', {'customer': customer(acct), 'return_url': return_url})
    return s['url']


def card(acct):
    if not (configured() and acct.stripe_payment_method):
        return None
    try:
        pm = _call('GET', f'/payment_methods/{acct.stripe_payment_method}')
    except StripeError:
        return None
    c = pm.get('card') or {}
    return {'brand': (c.get('brand') or 'card').title(), 'last4': c.get('last4', ''),
            'expires': f'{c.get("exp_month", 0):02d}/{str(c.get("exp_year", ""))[-2:]}'}


def charge(acct, cents, description, key):
    """Charge the card on file. Returns (ok, payment intent id)."""
    if not acct.stripe_payment_method:
        return False, None
    try:
        pi = _call('POST', '/payment_intents', {
            'amount': str(cents), 'currency': 'usd', 'customer': customer(acct),
            'payment_method': acct.stripe_payment_method, 'off_session': 'true', 'confirm': 'true',
            'description': description, 'metadata[account]': str(acct.id),
        }, idempotency=key)
    except StripeError as e:
        log.warning('charge failed for account %s: %s', acct.id, e)
        return False, None
    return pi.get('status') == 'succeeded', pi.get('id')


# --------------------------------------------------------------- webhooks

def verify(payload, header, tolerance=300):
    """Stripe-Signature: t=..., v1=... (HMAC-SHA256 of "t.payload")."""
    secret = settings.STRIPE_WEBHOOK_SECRET
    if not secret or not header:
        return False
    parts = dict(p.split('=', 1) for p in header.split(',') if '=' in p)
    sigs = [v for k, v in (p.split('=', 1) for p in header.split(',') if '=' in p) if k == 'v1']
    try:
        t = int(parts.get('t', '0'))
    except ValueError:
        return False
    if abs(time.time() - t) > tolerance:
        return False
    want = hmac.new(secret.encode(), f'{t}.'.encode() + payload, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(want, s) for s in sigs)


def _acct(obj):
    meta = obj.get('metadata') or {}
    if meta.get('account'):
        return BusinessAccount.objects.filter(pk=meta['account']).first()
    if obj.get('customer'):
        return BusinessAccount.objects.filter(stripe_customer_id=obj['customer']).first()
    return None


def _apply_subscription(acct, sub):
    status = sub.get('status')
    acct.stripe_subscription_id = sub.get('id', '')
    if status in ('active', 'trialing'):
        acct.plan, acct.plan_status = 'partner', 'active'
    elif status in ('past_due', 'unpaid'):
        acct.plan, acct.plan_status = 'partner', 'past_due'
    else:
        acct.plan, acct.plan_status = 'none', 'canceled'
    end = sub.get('current_period_end') or ((sub.get('items') or {}).get('data') or [{}])[0].get('current_period_end')
    acct.plan_renews_at = datetime.fromtimestamp(end, tz=dt_tz.utc) if end else None
    acct.save(update_fields=['plan', 'plan_status', 'plan_renews_at', 'stripe_subscription_id'])


def handle(event):
    kind, obj = event.get('type', ''), (event.get('data') or {}).get('object') or {}
    acct = _acct(obj)
    if acct is None:
        return
    if kind == 'checkout.session.completed':
        if obj.get('mode') == 'setup' and obj.get('setup_intent'):
            si = _call('GET', f'/setup_intents/{obj["setup_intent"]}')
            pm = si.get('payment_method')
            if pm:
                acct.stripe_payment_method = pm
                acct.save(update_fields=['stripe_payment_method'])
                _call('POST', f'/customers/{customer(acct)}', {'invoice_settings[default_payment_method]': pm})
        elif obj.get('mode') == 'subscription' and obj.get('subscription'):
            _apply_subscription(acct, _call('GET', f'/subscriptions/{obj["subscription"]}'))
    elif kind in ('customer.subscription.created', 'customer.subscription.updated', 'customer.subscription.deleted'):
        _apply_subscription(acct, obj)
    elif kind == 'invoice.payment_failed' and acct.plan == 'partner':
        acct.plan_status = 'past_due'
        acct.save(update_fields=['plan_status'])


def parse(payload):
    return json.loads(payload.decode() or '{}')
