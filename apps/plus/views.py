"""
A Good Fit Plus API.

GET     /api/plus/                       plan, subscription, products, trial
POST    /api/plus/verify/                {store: apple|google|test, data, product?} after a purchase
POST    /api/plus/restore/               {store, items: [data, ...]} Restore purchases
DELETE  /api/plus/                       end a test purchase (test servers only)
POST    /api/plus/webhooks/apple/        App Store Server Notifications V2 {signedPayload}
POST    /api/plus/webhooks/google/?token= Google Play real-time notifications (Pub/Sub push)
"""

import hmac
import logging

from django.conf import settings
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services as svc
from .stores import StoreError

log = logging.getLogger('agf.plus')


def _bad(e):
    return Response({'code': e.code, 'message': e.message}, status=e.http)


class PlusView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        svc.refresh_plan(request.user)
        return Response(svc.payload(request.user))

    def delete(self, request):
        if not settings.PLUS_TEST_PURCHASES:
            return Response({'code': 'store', 'message': 'Cancel Plus in your app store settings.'}, status=403)
        svc.end_test(request.user)
        return Response(svc.payload(request.user))


class VerifyView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        d = request.data
        try:
            sub, started = svc.verify(request.user, d.get('store'), d.get('data'), d.get('product'))
        except StoreError as e:
            return _bad(e)
        return Response(dict(svc.payload(request.user), started=started, trial=sub.status == 'trial'))


class RestoreView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        d = request.data
        items = d.get('items') or []
        if not isinstance(items, list):
            items = []
        errors = []
        for data in items[:20]:
            try:
                svc.verify(request.user, d.get('store'), data)
            except StoreError as e:
                errors.append(e)
        svc.refresh_plan(request.user)
        if request.user.plan != 'plus':
            other = next((e for e in errors if e.code == 'other_account'), None)
            if other:
                return _bad(other)
            return Response({'code': 'nothing_to_restore',
                             'message': 'We couldn’t find an active Plus subscription for this account.'}, status=404)
        return Response(dict(svc.payload(request.user), restored=True))


class AppleWebhookView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        try:
            svc.apple_notification(request.data.get('signedPayload'))
        except StoreError as e:
            log.warning('apple notification refused: %s', e.code)
            return Response({'code': e.code}, status=400)
        return Response({'ok': True})


class GoogleWebhookView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        want = settings.GOOGLE_RTDN_TOKEN
        if not want or not hmac.compare_digest(request.query_params.get('token', ''), want):
            return Response({'code': 'forbidden'}, status=403)
        try:
            svc.google_notification(request.data.get('message'))
        except StoreError as e:
            log.warning('google notification refused: %s', e.code)
            # 5xx makes Pub/Sub retry; bad input won't get better.
            return Response({'code': e.code}, status=502 if e.http >= 500 else 200)
        return Response({'ok': True})
