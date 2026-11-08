"""
Sign-up, log-in and onboarding endpoints (Phase 1).

Flow (Technical Requirements, "Onboarding, in order"):

  Email:          register (name, birthday, email, password) -> intent ->
                  interests -> photo (optional) -> guidelines -> member
  Apple / Google: social sign-in -> birthday -> intent -> ... -> member

Every response that signs someone in carries `next_step`, so the app always
resumes where the person left off (closing the app on the birthday step
returns them to it). The server enforces each rule; the app only mirrors it.
"""

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .age_gate import AgeGateError, parse_birthday, subject_hash
from .models import AgeGateEvent, SocialAgeBlock, UserGoals, UserPreferences, UserStats
from .serializers import MeSerializer
from .social import SocialAuthError, verify_apple, verify_google

User = get_user_model()


def _session(user, request, http_status=status.HTTP_200_OK, **extra):
    refresh = RefreshToken.for_user(user)
    return Response(
        {
            'user': MeSerializer(user, context={'request': request}).data,
            'tokens': {'refresh': str(refresh), 'access': str(refresh.access_token)},
            'next_step': user.next_step,
            **extra,
        },
        status=http_status,
    )


def _error(code, message, http_status=status.HTTP_400_BAD_REQUEST, **extra):
    return Response({'code': code, 'detail': message, **extra}, status=http_status)


def _ensure_related(user):
    UserGoals.objects.get_or_create(user=user)
    UserStats.objects.get_or_create(user=user)
    UserPreferences.objects.get_or_create(user=user)


def _split_name(full_name):
    parts = (full_name or '').strip().split()
    if not parts:
        return '', ''
    return parts[0], ' '.join(parts[1:])


class BirthdayField(serializers.Serializer):
    year = serializers.IntegerField()
    month = serializers.IntegerField()
    day = serializers.IntegerField()


# --- Email ---------------------------------------------------------------------

class RegisterSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=100)
    birthday = BirthdayField()
    email = serializers.EmailField()
    password = serializers.CharField(min_length=8, write_only=True)
    timezone = serializers.CharField(required=False, default='UTC', max_length=64)

    def validate_full_name(self, value):
        if not value.strip():
            raise serializers.ValidationError('Enter your name.')
        return value.strip()

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError('An account with this email already exists. Log in instead.')
        return value.lower()


class RegisterView(APIView):
    """Create account (email). Under 21: nothing is stored."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth'

    def post(self, request):
        s = RegisterSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        b = d['birthday']
        try:
            birthday = parse_birthday(b['year'], b['month'], b['day'], d['timezone'])
        except AgeGateError as e:
            if e.code == 'under_21':
                AgeGateEvent.objects.create(method='email', passed=False)
                return _error(e.code, e.message, status.HTTP_403_FORBIDDEN)
            return _error(e.code, e.message)

        first, last = _split_name(d['full_name'])
        with transaction.atomic():
            user = User.objects.create_user(
                email=d['email'],
                password=d['password'],
                display_name=d['full_name'],
                first_name=first,
                last_name=last,
                timezone=d['timezone'],
            )
            user.set_birthday_once(birthday)
            user.save(update_fields=['birthday_enc'])
            _ensure_related(user)
        AgeGateEvent.objects.create(method='email', passed=True)
        return _session(user, request, status.HTTP_201_CREATED)


class LoginView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth'

    def post(self, request):
        email = (request.data.get('email') or '').strip().lower()
        password = request.data.get('password') or ''
        user = authenticate(request=request, username=email, password=password)
        if user is None:
            return _error('invalid_credentials', 'That email and password don’t match.',
                          status.HTTP_401_UNAUTHORIZED)
        if not user.is_active:
            return _error('account_disabled', 'This account is turned off. Contact the team for help.',
                          status.HTTP_403_FORBIDDEN)
        user.online_status = 'online'
        user.save(update_fields=['online_status'])
        return _session(user, request)


# --- Apple and Google ------------------------------------------------------------

class _SocialView(APIView):
    """Sign in or sign up with a verified Apple/Google token.

    New people become a pending sign-up held at the birthday step. A sign-in
    ID that failed the age gate before is refused.
    """

    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth'
    provider = ''

    def verify(self, request):
        raise NotImplementedError

    def post(self, request):
        try:
            ident = self.verify(request)
        except SocialAuthError as e:
            code = status.HTTP_503_SERVICE_UNAVAILABLE if e.code == 'not_configured' else status.HTTP_401_UNAUTHORIZED
            return _error(e.code, e.message, code)

        if SocialAgeBlock.objects.filter(subject_hash=subject_hash(ident.provider, ident.subject)).exists():
            return _error('under_21_blocked', 'A Good Fit is for adults 21 and over.',
                          status.HTTP_403_FORBIDDEN)

        sub_field = f'{ident.provider}_sub'
        user = User.objects.filter(**{sub_field: ident.subject}).first()
        created = False
        if user is None and ident.email and ident.email_verified:
            # Link to an existing account with the same verified email.
            user = User.objects.filter(email__iexact=ident.email).first()
            if user is not None:
                setattr(user, sub_field, ident.subject)
                user.save(update_fields=[sub_field])
        if user is None:
            email = (ident.email or f'{ident.provider}.{ident.subject[:24]}@users.agoodfit.invalid').lower()
            first = (request.data.get('first_name') or ident.first_name or '').strip()
            last = (request.data.get('last_name') or ident.last_name or '').strip()
            try:
                with transaction.atomic():
                    user = User.objects.create_user(
                        email=email,
                        password=None,
                        display_name=f'{first} {last}'.strip() or email.split('@')[0],
                        first_name=first,
                        last_name=last,
                        timezone=request.data.get('timezone') or 'UTC',
                        **{sub_field: ident.subject},
                    )
                    user.set_unusable_password()
                    if ident.picture:
                        user.avatar_url = ident.picture
                    user.save()
                    _ensure_related(user)
            except IntegrityError:
                return _error('account_conflict', 'That account is already linked to someone else.',
                              status.HTTP_409_CONFLICT)
            created = True
        if not user.is_active:
            return _error('account_disabled', 'This account is turned off. Contact the team for help.',
                          status.HTTP_403_FORBIDDEN)
        return _session(user, request, provider=ident.provider, is_new_user=created)


class AppleSignInView(_SocialView):
    provider = 'apple'

    def verify(self, request):
        return verify_apple(request.data.get('identity_token') or '')


class GoogleSignInView(_SocialView):
    provider = 'google'

    def verify(self, request):
        return verify_google(request.data.get('id_token') or '')


# --- Onboarding steps ------------------------------------------------------------

class _Onboarding(APIView):
    permission_classes = [permissions.IsAuthenticated]
    allow_pending_member = True


class BirthdayStepView(_Onboarding):
    """The required birthday step for Apple/Google sign-ups (and accounts from
    before the age gate). Under 21: the pending account and the birthday are
    discarded and the sign-in ID is flagged."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth'

    def post(self, request):
        user = request.user
        if user.birthday_enc:
            return _error('birthday_locked', 'Your birthday is already set. Contact the team to fix it.',
                          status.HTTP_409_CONFLICT)
        s = BirthdayField(data=request.data)
        s.is_valid(raise_exception=True)
        tz = request.data.get('timezone') or user.timezone
        method = 'apple' if user.apple_sub else 'google' if user.google_sub else 'existing'
        try:
            birthday = parse_birthday(s.validated_data['year'], s.validated_data['month'],
                                      s.validated_data['day'], tz)
        except AgeGateError as e:
            if e.code != 'under_21':
                return _error(e.code, e.message)
            AgeGateEvent.objects.create(method=method, passed=False)
            with transaction.atomic():
                for provider in ('apple', 'google'):
                    sub = getattr(user, f'{provider}_sub')
                    if sub:
                        SocialAgeBlock.objects.get_or_create(
                            subject_hash=subject_hash(provider, sub), defaults={'provider': provider}
                        )
                if method == 'existing':
                    # An account from before the gate: turn it off rather than
                    # deleting history; support can review.
                    user.is_active = False
                    user.save(update_fields=['is_active'])
                else:
                    user.delete()
            return _error(e.code, e.message, status.HTTP_403_FORBIDDEN)

        user.timezone = tz
        user.set_birthday_once(birthday)
        user.save(update_fields=['birthday_enc', 'timezone'])
        AgeGateEvent.objects.create(method=method, passed=True)
        return Response({'user': MeSerializer(user, context={'request': request}).data,
                         'next_step': user.next_step})


class OnboardingSerializer(serializers.Serializer):
    intents = serializers.ListField(child=serializers.ChoiceField(choices=User.INTENTS),
                                    required=False, allow_empty=False)
    interests = serializers.ListField(child=serializers.ChoiceField(choices=User.INTERESTS),
                                      required=False, allow_empty=False,
                                      max_length=User.MAX_INTERESTS)
    photo_step_done = serializers.BooleanField(required=False)

    def validate_intents(self, value):
        return [i for i in User.INTENTS if i in value]

    def validate_interests(self, value):
        seen = []
        for i in value:
            if i not in seen:
                seen.append(i)
        return seen


class OnboardingView(_Onboarding):
    """Save What's your good fit (1+ intents), Interests (1 to 3) and the
    photo step. Also used later from Edit profile."""

    def patch(self, request):
        user = request.user
        if user.next_step == 'birthday':
            return _error('birthday_required', 'Add your birthday first.', status.HTTP_409_CONFLICT)
        s = OnboardingSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        fields = []
        for key, value in s.validated_data.items():
            setattr(user, key, value)
            fields.append(key)
        if fields:
            user.save(update_fields=fields)
        return Response({'user': MeSerializer(user, context={'request': request}).data,
                         'next_step': user.next_step})


class GuidelinesAgreementView(_Onboarding):
    """Agree to the Community Guidelines: the last step. Stores the version
    and time, and makes the account a member."""

    def post(self, request):
        user = request.user
        if request.data.get('agreed') is not True:
            return _error('agreement_required', 'Check “I’ve read and agree” to continue.')
        step = user.next_step
        if step not in ('guidelines', 'done'):
            return _error('steps_remaining', 'Finish the earlier steps first.',
                          status.HTTP_409_CONFLICT, next_step=step)
        user.guidelines_version = settings.GUIDELINES_VERSION
        user.guidelines_agreed_at = timezone.now()
        user.save(update_fields=['guidelines_version', 'guidelines_agreed_at'])
        self._ensure_matching_profile(user)
        return Response({'user': MeSerializer(user, context={'request': request}).data,
                         'next_step': user.next_step})

    @staticmethod
    def _ensure_matching_profile(user):
        # Fit Buddies still reads the legacy matching profile. Age is
        # deliberately not copied: it may only appear inside A Good Match.
        from apps.matching.models import UserProfile
        UserProfile.objects.get_or_create(
            user=user,
            defaults={'favorite_activities': list(user.interests or []), 'is_active': True},
        )


# --- Password reset ---------------------------------------------------------------

class PasswordResetRequestView(APIView):
    """Always answers 200 so the endpoint can't be used to find accounts."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'password_reset'

    def post(self, request):
        email = (request.data.get('email') or '').strip().lower()
        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if user is not None and user.has_usable_password():
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            link = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/reset/{uid}/{token}/"
            send_mail(
                subject='Reset your A Good Fit password',
                message=(
                    f'Hi {user.first_name or "there"},\n\n'
                    f'Use this link to set a new password. It works once and expires in a few days.\n\n'
                    f'{link}\n\n'
                    'If you didn’t ask for this, you can ignore this email.\n\n'
                    'A Good Fit'
                ),
                from_email=None,
                recipient_list=[user.email],
                fail_silently=True,
            )
        return Response({'detail': 'If that email has an account, a reset link is on its way.'})
