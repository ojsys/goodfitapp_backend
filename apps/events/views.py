"""
Event Views for GoodFit API
"""

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from django.utils import timezone
from django.db.models import Q, Count
from .models import Event, EventRSVP
from .serializers import (
    EventSerializer,
    EventCreateSerializer,
    EventRSVPSerializer,
    RSVPCreateSerializer,
)


class EventViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Event CRUD operations
    """

    permission_classes = [IsAuthenticatedOrReadOnly]
    queryset = Event.objects.filter(is_active=True, is_cancelled=False)

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return EventCreateSerializer
        return EventSerializer

    def get_queryset(self):
        """Filter events based on query params"""
        queryset = super().get_queryset()

        # Filter by upcoming/past
        time_filter = self.request.query_params.get('time', 'upcoming')
        now = timezone.now()

        if time_filter == 'upcoming':
            queryset = queryset.filter(start_time__gte=now)
        elif time_filter == 'past':
            queryset = queryset.filter(start_time__lt=now)

        # Filter by vibe
        vibe = self.request.query_params.get('vibe')
        if vibe:
            queryset = queryset.filter(vibe=vibe)

        # Filter by price type
        price_type = self.request.query_params.get('price_type')
        if price_type:
            queryset = queryset.filter(price_type=price_type)

        # Search by title, description, or location
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search) |
                Q(description__icontains=search) |
                Q(location_name__icontains=search) |
                Q(location_address__icontains=search)
            )

        # Filter by tags
        tags = self.request.query_params.get('tags')
        if tags:
            tag_list = tags.split(',')
            for tag in tag_list:
                queryset = queryset.filter(tags__contains=[tag.strip()])

        return queryset.annotate(
            rsvp_count=Count('rsvps', filter=Q(rsvps__status='going'))
        )

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def rsvp(self, request, pk=None):
        """RSVP to an event"""
        event = self.get_object()

        # Check if event is full
        if event.is_full:
            return Response(
                {'error': 'This event is full'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check if event is in the past
        if event.is_past:
            return Response(
                {'error': 'Cannot RSVP to past events'},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = RSVPCreateSerializer(
            data=request.data,
            context={'request': request, 'event': event}
        )

        if serializer.is_valid():
            rsvp = serializer.save()
            return Response(
                EventRSVPSerializer(rsvp).data,
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['delete'], permission_classes=[IsAuthenticated])
    def cancel_rsvp(self, request, pk=None):
        """Cancel RSVP to an event"""
        event = self.get_object()

        try:
            rsvp = EventRSVP.objects.get(event=event, user=request.user)
            rsvp.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except EventRSVP.DoesNotExist:
            return Response(
                {'error': 'No RSVP found'},
                status=status.HTTP_404_NOT_FOUND
            )

    @action(detail=True, methods=['get'])
    def attendees(self, request, pk=None):
        """Get list of attendees for an event"""
        event = self.get_object()
        rsvps = event.rsvps.filter(status='going')
        serializer = EventRSVPSerializer(rsvps, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def my_events(self, request):
        """Get events the user has RSVP'd to"""
        user_rsvps = request.user.event_rsvps.filter(status='going')
        event_ids = user_rsvps.values_list('event_id', flat=True)
        events = Event.objects.filter(id__in=event_ids, is_active=True)

        serializer = self.get_serializer(events, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def hosted(self, request):
        """Get events hosted by the user"""
        events = Event.objects.filter(host=request.user, is_active=True)
        serializer = self.get_serializer(events, many=True)
        return Response(serializer.data)
