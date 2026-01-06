"""
Live Activity Views for GPS Tracking
"""

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404

from apps.activities.models import LiveActivity
from apps.activities.serializers import (
    LiveActivitySerializer,
    LiveActivityCreateSerializer,
    GPSPointSerializer,
)


class LiveActivityViewSet(viewsets.ModelViewSet):
    """
    ViewSet for live activity tracking with GPS
    """
    permission_classes = [IsAuthenticated]
    serializer_class = LiveActivitySerializer

    def get_queryset(self):
        """Get live activities for current user"""
        return LiveActivity.objects.filter(user=self.request.user)

    def get_serializer_class(self):
        """Use different serializer for create"""
        if self.action == 'create':
            return LiveActivityCreateSerializer
        return LiveActivitySerializer

    @action(detail=False, methods=['get'])
    def active(self, request):
        """Get currently active activity for user"""
        try:
            live_activity = LiveActivity.objects.get(
                user=request.user,
                status__in=['active', 'paused']
            )
            serializer = self.get_serializer(live_activity)
            return Response(serializer.data)
        except LiveActivity.DoesNotExist:
            return Response({'active': False}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def add_gps_point(self, request, pk=None):
        """Add GPS point to live activity"""
        live_activity = self.get_object()

        if live_activity.status != 'active':
            return Response(
                {'error': 'Activity is not active'},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = GPSPointSerializer(data=request.data)
        if serializer.is_valid():
            live_activity.add_gps_point(
                latitude=serializer.validated_data['latitude'],
                longitude=serializer.validated_data['longitude'],
                altitude=serializer.validated_data.get('altitude'),
                speed=serializer.validated_data.get('speed'),
                accuracy=serializer.validated_data.get('accuracy')
            )

            # Return updated activity
            response_serializer = LiveActivitySerializer(live_activity)
            return Response(response_serializer.data)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def pause(self, request, pk=None):
        """Pause live activity"""
        live_activity = self.get_object()
        live_activity.pause()

        serializer = self.get_serializer(live_activity)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def resume(self, request, pk=None):
        """Resume paused activity"""
        live_activity = self.get_object()
        live_activity.resume()

        serializer = self.get_serializer(live_activity)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def stop(self, request, pk=None):
        """Stop activity and create final Activity record"""
        live_activity = self.get_object()
        final_activity = live_activity.stop()

        from apps.activities.serializers import ActivitySerializer
        serializer = ActivitySerializer(final_activity)

        return Response({
            'activity': serializer.data,
            'message': 'Activity completed successfully'
        })

    @action(detail=True, methods=['post'])
    def update_metrics(self, request, pk=None):
        """Update current metrics (calories, pace, etc.)"""
        live_activity = self.get_object()

        # Update metrics from request
        if 'current_calories' in request.data:
            live_activity.current_calories = request.data['current_calories']
        if 'current_pace' in request.data:
            live_activity.current_pace = request.data['current_pace']
        if 'current_speed' in request.data:
            live_activity.current_speed = request.data['current_speed']

        live_activity.save()

        serializer = self.get_serializer(live_activity)
        return Response(serializer.data)
