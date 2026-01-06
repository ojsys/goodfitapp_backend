"""
URL patterns for User authentication
"""

from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    RegisterView, LoginView, LogoutView,
    ProfileView, UpdateProfileView, ChangePasswordView,
    UserGoalsView, UserStatsView, UserPreferencesView,
    OnlineStatusView
)

app_name = 'users'

urlpatterns = [
    # Authentication
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    # Profile Management
    path('profile/', ProfileView.as_view(), name='profile'),
    path('profile/update/', UpdateProfileView.as_view(), name='update-profile'),
    path('password/change/', ChangePasswordView.as_view(), name='change-password'),

    # User Goals, Stats, and Preferences
    path('goals/', UserGoalsView.as_view(), name='goals'),
    path('stats/', UserStatsView.as_view(), name='stats'),
    path('preferences/', UserPreferencesView.as_view(), name='preferences'),

    # Online Status
    path('status/', OnlineStatusView.as_view(), name='online-status'),
]
