"""
Views for Activity management
"""

from rest_framework import generics, status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Count, Sum, Avg, Max
from datetime import datetime, timedelta
from django.utils import timezone

from .models import Activity, DailySummary
from .serializers import (
    ActivitySerializer, ActivityListSerializer, ActivityCreateSerializer,
    DailySummarySerializer, ActivityStatsSerializer
)


class ActivityListCreateView(generics.ListCreateAPIView):
    """List all activities or create a new one"""

    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return ActivityCreateSerializer
        return ActivityListSerializer

    def get_queryset(self):
        """Get activities for current user"""
        queryset = Activity.objects.filter(user=self.request.user)

        # Filter by type
        activity_type = self.request.query_params.get('type', None)
        if activity_type:
            queryset = queryset.filter(type=activity_type)

        # Filter by date range
        start_date = self.request.query_params.get('start_date', None)
        end_date = self.request.query_params.get('end_date', None)

        if start_date:
            queryset = queryset.filter(start_time__gte=start_date)
        if end_date:
            queryset = queryset.filter(start_time__lte=end_date)

        return queryset

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class ActivityDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update or delete an activity"""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ActivitySerializer

    def get_queryset(self):
        return Activity.objects.filter(user=self.request.user)


class RecentActivitiesView(generics.ListAPIView):
    """Get recent activities (last 30 days)"""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ActivityListSerializer

    def get_queryset(self):
        thirty_days_ago = timezone.now() - timedelta(days=30)
        return Activity.objects.filter(
            user=self.request.user,
            start_time__gte=thirty_days_ago
        )[:20]


class ActivityStatsView(APIView):
    """Get activity statistics"""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        # Get date range from query params (default to last 30 days)
        days = int(request.query_params.get('days', 30))
        start_date = timezone.now() - timedelta(days=days)

        activities = Activity.objects.filter(
            user=request.user,
            start_time__gte=start_date
        )

        # Calculate statistics
        stats = activities.aggregate(
            total_activities=Count('id'),
            total_distance=Sum('distance'),
            total_duration=Sum('duration'),
            total_calories=Sum('calories_burned'),
            average_duration=Avg('duration'),
            longest_activity=Max('duration')
        )

        # Activities by type
        activities_by_type = {}
        for activity_type, _ in Activity.ACTIVITY_TYPES:
            count = activities.filter(type=activity_type).count()
            if count > 0:
                activities_by_type[activity_type] = count

        stats['activities_by_type'] = activities_by_type

        # Replace None with 0
        for key, value in stats.items():
            if value is None and key != 'activities_by_type':
                stats[key] = 0

        serializer = ActivityStatsSerializer(stats)
        return Response(serializer.data)


class DailySummaryListView(generics.ListAPIView):
    """Get daily summaries"""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = DailySummarySerializer

    def get_queryset(self):
        # Get summaries for last 30 days by default
        days = int(self.request.query_params.get('days', 30))
        start_date = timezone.now().date() - timedelta(days=days)

        return DailySummary.objects.filter(
            user=self.request.user,
            date__gte=start_date
        )


class TodaySummaryView(generics.RetrieveAPIView):
    """Get today's summary"""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = DailySummarySerializer

    def get_object(self):
        today = timezone.now().date()
        summary, created = DailySummary.objects.get_or_create(
            user=self.request.user,
            date=today
        )

        if created:
            summary.calculate_progress()

        return summary


class UpdateDailySummaryView(APIView):
    """Update today's summary (for step tracking, etc.)"""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        today = timezone.now().date()
        summary, created = DailySummary.objects.get_or_create(
            user=request.user,
            date=today
        )

        # Update fields from request data
        summary.total_steps = request.data.get('total_steps', summary.total_steps)
        summary.total_distance = request.data.get('total_distance', summary.total_distance)
        summary.total_calories = request.data.get('total_calories', summary.total_calories)
        summary.total_active_minutes = request.data.get('total_active_minutes', summary.total_active_minutes)
        summary.total_workouts = request.data.get('total_workouts', summary.total_workouts)

        summary.calculate_progress()

        serializer = DailySummarySerializer(summary)
        return Response(serializer.data)
