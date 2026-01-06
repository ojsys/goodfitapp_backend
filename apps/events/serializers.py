"""
Event Serializers for GoodFit API
"""

from rest_framework import serializers
from .models import Event, EventRSVP


class EventRSVPSerializer(serializers.ModelSerializer):
    """Serializer for Event RSVP"""

    user_name = serializers.CharField(source='user.display_name', read_only=True)
    user_avatar = serializers.CharField(source='user.avatar_url', read_only=True)

    class Meta:
        model = EventRSVP
        fields = [
            'id',
            'user',
            'user_name',
            'user_avatar',
            'status',
            'checked_in',
            'created_at',
        ]
        read_only_fields = ['id', 'user', 'created_at']


class EventSerializer(serializers.ModelSerializer):
    """Serializer for Event list/detail"""

    attendee_count = serializers.IntegerField(read_only=True)
    is_past = serializers.BooleanField(read_only=True)
    formatted_date = serializers.CharField(read_only=True)
    formatted_time = serializers.CharField(read_only=True)
    user_rsvp_status = serializers.SerializerMethodField()
    attendee_avatars = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = [
            'id',
            'title',
            'description',
            'image_url',
            'host',
            'host_name',
            'vibe',
            'price_type',
            'price_amount',
            'start_time',
            'end_time',
            'location_name',
            'location_address',
            'latitude',
            'longitude',
            'max_attendees',
            'is_full',
            'tags',
            'what_to_bring',
            'is_active',
            'is_cancelled',
            'attendee_count',
            'is_past',
            'formatted_date',
            'formatted_time',
            'user_rsvp_status',
            'attendee_avatars',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'host', 'created_at', 'updated_at', 'is_full']

    def get_user_rsvp_status(self, obj):
        """Get current user's RSVP status for this event"""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            rsvp = obj.rsvps.filter(user=request.user).first()
            if rsvp:
                return rsvp.status
        return None

    def get_attendee_avatars(self, obj):
        """Get list of attendee avatar URLs (max 3)"""
        rsvps = obj.rsvps.filter(status='going')[:3]
        return [rsvp.user.avatar_url for rsvp in rsvps if rsvp.user.avatar_url]


class EventCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating/updating events"""

    class Meta:
        model = Event
        fields = [
            'title',
            'description',
            'image_url',
            'host_name',
            'vibe',
            'price_type',
            'price_amount',
            'start_time',
            'end_time',
            'location_name',
            'location_address',
            'latitude',
            'longitude',
            'max_attendees',
            'tags',
            'what_to_bring',
        ]

    def create(self, validated_data):
        """Create event with current user as host"""
        request = self.context.get('request')
        validated_data['host'] = request.user
        return super().create(validated_data)


class RSVPCreateSerializer(serializers.Serializer):
    """Serializer for creating/updating RSVP"""

    status = serializers.ChoiceField(choices=EventRSVP.STATUS_CHOICES)

    def create(self, validated_data):
        """Create or update RSVP"""
        request = self.context.get('request')
        event = self.context.get('event')

        rsvp, created = EventRSVP.objects.update_or_create(
            event=event,
            user=request.user,
            defaults={'status': validated_data['status']}
        )
        return rsvp
