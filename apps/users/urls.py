"""
URL patterns for User authentication
"""

from django.urls import path

from . import account_views
from rest_framework_simplejwt.views import TokenRefreshView

from .signup_views import (
    AppleSignInView, BirthdayStepView, GoogleSignInView, GuidelinesAgreementView,
    LoginView, OnboardingView, PasswordResetRequestView, RegisterView,
)
from .views import (
    LogoutView,
    ProfileView, UpdateProfileView, ChangePasswordView, AvatarUploadView,
    UserGoalsView, UserStatsView, UserPreferencesView,
    OnlineStatusView
)

app_name = 'users'

urlpatterns = [
    # Authentication
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', LoginView.as_view(), name='login'),
    path('apple/', AppleSignInView.as_view(), name='apple'),
    path('google/', GoogleSignInView.as_view(), name='google'),
    # Older app builds call this path.
    path('google-login/', GoogleSignInView.as_view(), name='google-login'),
    path('password/reset/', PasswordResetRequestView.as_view(), name='password-reset'),

    # Sign-up steps (usable before the account is a member)
    path('signup/birthday/', BirthdayStepView.as_view(), name='signup-birthday'),
    path('onboarding/', OnboardingView.as_view(), name='onboarding'),
    path('onboarding/guidelines/', GuidelinesAgreementView.as_view(), name='onboarding-guidelines'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    # Profile Management
    path('profile/', ProfileView.as_view(), name='profile'),
    # Phase 6: You, Edit profile, Settings.
    path('me/', account_views.MeView.as_view(), name='me'),
    path('settings/', account_views.SettingsView.as_view(), name='settings'),
    path('email/', account_views.EmailView.as_view(), name='email'),
    path('password/', account_views.PasswordView.as_view(), name='password'),
    path('export/', account_views.ExportView.as_view(), name='export'),
    path('delete/', account_views.DeleteAccountView.as_view(), name='delete'),
    path('profile/update/', UpdateProfileView.as_view(), name='update-profile'),
    path('profile/avatar/', AvatarUploadView.as_view(), name='profile-avatar'),
    path('password/change/', ChangePasswordView.as_view(), name='change-password'),

    # User Goals, Stats, and Preferences
    path('goals/', UserGoalsView.as_view(), name='goals'),
    path('stats/', UserStatsView.as_view(), name='stats'),
    path('preferences/', UserPreferencesView.as_view(), name='preferences'),

    # Online Status
    path('status/', OnlineStatusView.as_view(), name='online-status'),
]
