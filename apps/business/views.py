"""
Business portal API (the React portal at business.getlovelly.cloud).

Signed in with a session cookie (same site as the portal); every write
sends the CSRF token from GET session/. Every account route checks the
person's role and the permission grid.

GET   /api/business/session/                       who's signed in, their accounts, the CSRF token
POST  /api/business/login/  logout/  signup/
GET   /api/business/a/<acct>/overview/
GET   /api/business/a/<acct>/options/              neighborhoods, interests, packages
POST  /api/business/a/<acct>/reach/                {neighborhoods, interests}
POST  /api/business/a/<acct>/featured/             new draft
GET|PATCH|DELETE /api/business/a/<acct>/featured/<id>/
POST  /api/business/a/<acct>/featured/<id>/submit/
GET   /api/business/a/<acct>/featured/<id>/results/
GET   /api/business/a/<acct>/suggestions/
POST  /api/business/a/<acct>/suggestions/<id>/<approve|decline|undo|message>/
POST  /api/business/a/<acct>/flags/<id>/<rename|allow>/
GET   /api/business/a/<acct>/team/                 ?q= searches members to invite
POST  /api/business/a/<acct>/team/invite/          {user, role}
PATCH|DELETE /api/business/a/<acct>/team/<user>/   {role}
PATCH /api/business/a/<acct>/team/grid/            {role, perm, on}
GET   /api/business/a/<acct>/billing/
POST  /api/business/a/<acct>/billing/<card|partner|manage>/   {return_url} -> Stripe page
GET|PATCH /api/business/a/<acct>/settings/
POST  /api/business/stripe/webhook/

Member app (JWT):
POST  /api/business/featured/<placement>/seen/     {surface}   a featured card was on screen
POST  /api/business/featured/<placement>/tap/
POST  /api/business/invites/<id>/<accept|decline>/
"""

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework import permissions, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from . import billing
from . import services as svc
from .models import BusinessAccount, FeaturedPlacement


def _bad(e):
    return Response(dict({'code': e.code, 'message': e.message}, **e.extra), status=e.http)


def _me(user):
    if not user.is_authenticated:
        return None
    return {'id': user.id, 'name': user.full_name or user.email, 'first_name': user.first_name or '',
            'email': user.email, 'member': bool(user.guidelines_agreed_at)}


class Portal(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    perm = None

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        self.a = None
        if 'acct' in kwargs:
            self.a = svc.access(request.user, kwargs['acct'])
            if self.perm:
                self.a.need(self.perm)

    def handle_exception(self, exc):
        if isinstance(exc, svc.Denied):
            return _bad(exc)
        return super().handle_exception(exc)

    def tz(self):
        from apps.users.age_gate import safe_zone
        return safe_zone(self.request.user.timezone or 'America/New_York')


# ---------------------------------------------------------------- session

@method_decorator(ensure_csrf_cookie, name='dispatch')
class SessionView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        u = request.user
        return Response({
            'csrf': get_token(request), 'user': _me(u),
            'accounts': [svc.account_card(a, u) for a in svc.accounts_for(u)] if u.is_authenticated else [],
            'categories': BusinessAccount.CATEGORIES, 'stripe': billing.configured(),
            'app_url': settings.PUBLIC_BASE_URL,
        })


@method_decorator(csrf_protect, name='dispatch')
class LoginView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth'

    def post(self, request):
        email = (request.data.get('email') or '').strip().lower()
        user = authenticate(request, username=email, password=request.data.get('password') or '')
        if user is None or not user.is_active:
            return Response({'code': 'login', 'message': 'That email and password don’t match.'}, status=400)
        accounts = svc.accounts_for(user)
        login(request, user)
        return Response({'csrf': get_token(request), 'user': _me(user),
                         'accounts': [svc.account_card(a, user) for a in accounts]})


@method_decorator(csrf_protect, name='dispatch')
class LogoutView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        logout(request)
        return Response({'ok': True, 'csrf': get_token(request)})


@method_decorator(csrf_protect, name='dispatch')
class SignupView(APIView):
    """Create a business account. Signed out: also makes the login (work
    email + password). Signed in: adds a business to this login."""
    authentication_classes = [SessionAuthentication]
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth'

    def post(self, request):
        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError
        from django.core.validators import validate_email
        from apps.users.models import User
        d = request.data
        user = request.user if request.user.is_authenticated else None
        try:
            if user is None:
                email = (d.get('email') or '').strip().lower()
                try:
                    validate_email(email)
                except ValidationError:
                    raise svc.Denied('email', 'Add your work email.', 400)
                if User.objects.filter(email__iexact=email).exists():
                    raise svc.Denied('email_taken', 'That email already has an A Good Fit login. Log in to add '
                                     'your business.', 409)
                pw = d.get('password') or ''
                try:
                    validate_password(pw)
                except ValidationError as e:
                    raise svc.Denied('password', ' '.join(e.messages), 400)
                svc.check_signup(d)  # the business fields first, before making the login
                name = (d.get('contact') or '').strip()
                user = User.objects.create_user(email=email, password=pw, first_name=name.split(' ')[0][:30],
                                                last_name=' '.join(name.split(' ')[1:])[:30])
                login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            acct = svc.signup(user, dict(d, email=d.get('email') or user.email))
        except svc.Denied as e:
            return _bad(e)
        return Response({'csrf': get_token(request), 'user': _me(user), 'account': acct.id,
                         'accounts': [svc.account_card(a, user) for a in svc.accounts_for(user)]},
                        status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------- account

class OverviewView(Portal):
    def get(self, request, acct):
        return Response(dict(svc.overview(self.a), account=svc.account_card(self.a.account, request.user)))


class OptionsView(Portal):
    perm = 'feature_events'

    def get(self, request, acct):
        a = self.a.account
        return Response({
            'neighborhoods': svc.neighborhood_options(),
            'interests': [[k, svc.INTEREST_LABELS[k]] for k in
                          ('yoga', 'pilates', 'running', 'cycling', 'walking', 'strength', 'hiking', 'hiit')],
            'packages': [dict(v, id=k, price=v['price'] // 100,
                              price_label=f'${v["price"] // 100}' + ('/mo' if k == 'partner' else ''))
                         for k, v in FeaturedPlacement.PACKAGES.items()],
            'business': a.name, 'verified': a.verified, 'is_house': a.is_house, 'partner': a.partner,
            'partner_used': svc.partner_used(a), 'partner_limit': FeaturedPlacement.PARTNER_EVENTS_A_MONTH,
            'needs_card': billing.configured() and not a.is_house and not a.stripe_payment_method,
            'stripe': billing.configured(),
        })


class ReachView(Portal):
    perm = 'feature_events'

    def post(self, request, acct):
        d = request.data
        return Response(svc.reach(d.get('neighborhoods') or [], d.get('interests') or []))


class FeaturedListView(Portal):
    def post(self, request, acct):
        p = svc.save_draft(self.a, request.data)
        if request.data.get('submit'):
            try:
                svc.submit(self.a, p)
            except svc.Denied as e:
                return Response(dict({'code': e.code, 'message': e.message, 'draft': p.id}), status=e.http)
        return Response(svc.draft_payload(p, self.tz()), status=status.HTTP_201_CREATED)


class FeaturedView(Portal):
    def _get(self, pk):
        p = FeaturedPlacement.objects.filter(pk=pk, account=self.a.account).select_related('event').first()
        if p is None:
            raise svc.Denied('not_found', 'No such featured event.', 404)
        return p

    def get(self, request, acct, pk):
        self.a.need('feature_events')
        return Response(svc.draft_payload(self._get(pk), self.tz()))

    def patch(self, request, acct, pk):
        p = svc.save_draft(self.a, request.data, self._get(pk))
        if p.status == 'in_review':
            # Edited while in review: back to draft until sent again.
            p.status = 'draft'
            p.save(update_fields=['status'])
        if request.data.get('submit'):
            svc.submit(self.a, p)
        return Response(svc.draft_payload(p, self.tz()))

    def delete(self, request, acct, pk):
        self.a.need('feature_events')
        p = self._get(pk)
        if p.status in ('approved',):
            raise svc.Denied('locked', 'Approved events can’t be deleted here. Contact us to stop it.', 409)
        title = p.event.title
        p.event.delete()
        svc.log(self.a.account, request.user, f'deleted the draft {title}')
        return Response(status=status.HTTP_204_NO_CONTENT)


class SubmitView(FeaturedView):
    def post(self, request, acct, pk):
        p = svc.submit(self.a, self._get(pk))
        return Response(svc.draft_payload(p, self.tz()))


class ResultsView(FeaturedView):
    def get(self, request, acct, pk):
        return Response(svc.results(self.a, self._get(pk)))


class SuggestionsView(Portal):
    def get(self, request, acct):
        return Response(svc.suggestions(self.a))


class SuggestionActionView(Portal):
    def post(self, request, acct, pk, action):
        if action == 'message':
            return Response(svc.message_member(self.a, pk))
        return Response(svc.decide_suggestion(self.a, pk, action))


class FlagActionView(Portal):
    def post(self, request, acct, pk, action):
        return Response(svc.decide_flag(self.a, pk, action))


class TeamView(Portal):
    def get(self, request, acct):
        q = request.query_params.get('q')
        if q is not None:
            return Response({'people': svc.search_members(self.a, q)})
        return Response(svc.team(self.a))


class InviteView(Portal):
    def post(self, request, acct):
        try:
            uid = int(request.data.get('user'))
        except (TypeError, ValueError):
            raise svc.Denied('user', 'Pick someone to invite.', 400)
        inv = svc.invite(self.a, uid, request.data.get('role'))
        return Response(dict(svc.team(self.a), invited=inv.user.full_name or inv.user.first_name))


class TeamMemberView(Portal):
    def patch(self, request, acct, uid):
        svc.set_role(self.a, uid, request.data.get('role'))
        return Response(svc.team(self.a))

    def delete(self, request, acct, uid):
        svc.remove(self.a, uid)
        return Response(svc.team(self.a))


class GridView(Portal):
    def patch(self, request, acct):
        svc.set_grid(self.a, request.data.get('role'), request.data.get('perm'), bool(request.data.get('on')))
        return Response(svc.team(self.a))


class BillingView(Portal):
    perm = 'manage_billing'

    def get(self, request, acct):
        a = self.a.account
        tz = self.tz()
        charges = [{'title': p.event.title, 'package': p.spec['name'], 'amount': f'${p.price_cents / 100:.0f}',
                    'payment': p.get_payment_display(), 'when': f'{p.reviewed_at.astimezone(tz):%b} '
                                                                 f'{p.reviewed_at.astimezone(tz).day}'}
                   for p in a.placements.filter(status='approved').select_related('event').order_by('-reviewed_at')[:20]
                   if p.reviewed_at]
        renews = a.plan_renews_at.astimezone(tz) if a.plan_renews_at else None
        return Response({
            'stripe': billing.configured(), 'is_house': a.is_house, 'card': billing.card(a),
            'plan': {'partner': a.partner, 'status': a.get_plan_status_display() if a.plan_status else '',
                     'renews': f'{renews:%b} {renews.day}' if renews else None,
                     'price': '$299/mo'},
            'charges': charges,
        })

    def post(self, request, acct, kind):
        if not billing.configured():
            raise svc.Denied('stripe_off', 'Online billing isn’t switched on yet. We’ll set up your plan for you.', 409)
        ret = request.data.get('return_url') or ''
        if not ret.startswith(('https://', 'http://localhost', 'http://127.0.0.1')):
            raise svc.Denied('return_url', 'Bad return link.', 400)
        try:
            url = {'card': billing.card_checkout, 'partner': billing.partner_checkout,
                   'manage': billing.manage_url}[kind](self.a.account, ret)
        except KeyError:
            raise svc.Denied('kind', 'Unknown.', 404)
        except billing.StripeError as e:
            raise svc.Denied('stripe', f'Stripe said: {e}', 502)
        return Response({'url': url})


class SettingsView(Portal):
    def get(self, request, acct):
        a = self.a.account
        return Response({'name': a.name, 'category': a.category, 'address': a.address, 'website': a.website,
                         'work_email': a.work_email, 'status': a.status, 'review_note': a.review_note,
                         'can_edit': self.a.can('edit_club') or self.a.role == 'owner'})

    def patch(self, request, acct):
        if not (self.a.can('edit_club') or self.a.role == 'owner'):
            raise svc.Denied('forbidden', 'Your role doesn’t include this.', 403)
        a = self.a.account
        d = request.data
        for f, n in (('name', 120), ('address', 200), ('website', 200), ('work_email', 254)):
            if f in d and isinstance(d[f], str):
                setattr(a, f, d[f].strip()[:n])
        if d.get('category') in dict(BusinessAccount.CATEGORIES):
            a.category = d['category']
        a.save()
        svc.log(a, request.user, 'updated the business details')
        return self.get(request, acct)


class StripeWebhookView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        payload = request.body
        if not billing.verify(payload, request.headers.get('Stripe-Signature', '')):
            return Response({'code': 'signature'}, status=400)
        try:
            billing.handle(billing.parse(payload))
        except billing.StripeError as e:
            return Response({'code': 'stripe', 'message': str(e)}, status=502)
        return Response({'ok': True})


# ------------------------------------------------------------ member app

class SeenView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        ok = svc.seen(request.user, pk, request.data.get('surface') or 'events')
        return Response({'ok': ok})


class TapView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        ok = svc.seen(request.user, pk, request.data.get('surface') or 'events', tapped=True)
        return Response({'ok': ok})


class InviteAnswerView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk, action):
        try:
            inv = svc.answer_invite(request.user, pk, action == 'accept')
        except svc.Denied as e:
            return _bad(e)
        return Response({'status': inv.status, 'role': inv.get_role_display(), 'club': inv.club_id})
