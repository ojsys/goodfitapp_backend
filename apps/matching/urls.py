"""
Matching URLs for GoodFit API
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from apps.matching.views import UserProfileViewSet, SwipeViewSet, MatchViewSet

router = DefaultRouter()
router.register(r'profiles', UserProfileViewSet, basename='profile')
router.register(r'swipes', SwipeViewSet, basename='swipe')
router.register(r'matches', MatchViewSet, basename='match')

urlpatterns = [
    path('', include(router.urls)),
]
