"""
URL patterns for Activities
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ActivityListCreateView, ActivityDetailView, RecentActivitiesView,
    ActivityStatsView, DailySummaryListView, TodaySummaryView,
    UpdateDailySummaryView
)
from .live_views import LiveActivityViewSet

app_name = 'activities'

# Router for live tracking
router = DefaultRouter()
router.register(r'live', LiveActivityViewSet, basename='live-activity')

urlpatterns = [
    # Activity CRUD
    path('', ActivityListCreateView.as_view(), name='activity-list-create'),
    path('<int:pk>/', ActivityDetailView.as_view(), name='activity-detail'),
    path('recent/', RecentActivitiesView.as_view(), name='recent-activities'),
    path('stats/', ActivityStatsView.as_view(), name='activity-stats'),

    # Daily Summaries
    path('summaries/', DailySummaryListView.as_view(), name='daily-summaries'),
    path('summaries/today/', TodaySummaryView.as_view(), name='today-summary'),
    path('summaries/update/', UpdateDailySummaryView.as_view(), name='update-summary'),

    # Live GPS Tracking
    path('', include(router.urls)),
]
