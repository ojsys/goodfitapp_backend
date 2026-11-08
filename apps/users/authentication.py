"""
Authentication that enforces membership on the server.

An account exists from the first sign-up step, but it is only a member once
it has passed the age gate and agreed to the Community Guidelines (see
User.next_step). Until then its token works only on views that declare
`allow_pending_member = True` (the onboarding endpoints). Everything else is
refused with code `onboarding_incomplete` and the step to resume.
"""

from rest_framework import exceptions, status
from rest_framework_simplejwt.authentication import JWTAuthentication


class OnboardingIncomplete(exceptions.APIException):
    status_code = status.HTTP_403_FORBIDDEN
    default_code = 'onboarding_incomplete'
    default_detail = 'Finish signing up to continue.'

    def __init__(self, next_step):
        super().__init__({
            'detail': self.default_detail,
            'code': self.default_code,
            'next_step': next_step,
        })


class MemberJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None
        user, token = result
        view = (getattr(request, 'parser_context', None) or {}).get('view')
        if not getattr(view, 'allow_pending_member', False):
            step = user.next_step
            if step != 'done':
                raise OnboardingIncomplete(step)
        return user, token
