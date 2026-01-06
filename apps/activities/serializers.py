"""
Serializers for Activity models
"""

from rest_framework import serializers
from .models import Activity, DailySummary, LiveActivity
from apps.users.serializers import UserSerializer


class ActivitySerializer(serializers.ModelSerializer):
    """Serializer for Activity model"""

    user = UserSerializer(read_only=True)

    class Meta:
        model = Activity
        fields = [
            'id', 'user', 'type', 'title', 'notes',
            'start_time', 'end_time', 'duration',
            'distance', 'calories_burned', 'average_speed', 'pace',
            'elevation_gain', 'heart_rate_avg', 'heart_rate_max',
            'start_latitude', 'start_longitude', 'start_address',
            'route', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'user', 'created_at', 'updated_at']

    def create(self, validated_data):
        """Create activity with user from request"""
        validated_data['user'] = self.context['request'].user
        return super().create(validated_data)


class ActivityListSerializer(serializers.ModelSerializer):
    """Minimal serializer for activity lists"""

    class Meta:
        model = Activity
        fields = [
            'id', 'type', 'title', 'start_time', 'duration',
            'distance', 'calories_burned', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class ActivityCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating activities"""

    class Meta:
        model = Activity
        fields = [
            'type', 'title', 'notes', 'start_time', 'end_time', 'duration',
            'distance', 'calories_burned', 'average_speed', 'pace',
            'elevation_gain', 'heart_rate_avg', 'heart_rate_max',
            'start_latitude', 'start_longitude', 'start_address', 'route'
        ]

    def create(self, validated_data):
        """Create activity with user from request"""
        validated_data['user'] = self.context['request'].user
        return Activity.objects.create(**validated_data)


class DailySummarySerializer(serializers.ModelSerializer):
    """Serializer for Daily Summary"""

    class Meta:
        model = DailySummary
        fields = [
            'id', 'date', 'total_steps', 'total_distance', 'total_calories',
            'total_active_minutes', 'total_workouts',
            'step_goal_progress', 'calorie_goal_progress', 'workout_goal_progress',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class ActivityStatsSerializer(serializers.Serializer):
    """Serializer for activity statistics"""

    total_activities = serializers.IntegerField()
    total_distance = serializers.FloatField()
    total_duration = serializers.IntegerField()
    total_calories = serializers.IntegerField()
    activities_by_type = serializers.DictField()
    average_duration = serializers.FloatField()
    longest_activity = serializers.IntegerField()


class LiveActivitySerializer(serializers.ModelSerializer):
    """Serializer for LiveActivity"""

    active_duration = serializers.SerializerMethodField()
    distance_km = serializers.SerializerMethodField()
    distance_miles = serializers.SerializerMethodField()

    class Meta:
        model = LiveActivity
        fields = [
            'id', 'type', 'title', 'status',
            'start_time', 'paused_at', 'stopped_at', 'total_paused_duration',
            'current_distance', 'current_duration', 'current_calories',
            'current_pace', 'current_speed',
            'route_points', 'last_latitude', 'last_longitude', 'last_update',
            'final_activity', 'created_at', 'updated_at',
            'active_duration', 'distance_km', 'distance_miles'
        ]
        read_only_fields = [
            'id', 'start_time', 'created_at', 'updated_at',
            'current_distance', 'last_update', 'final_activity'
        ]

    def get_active_duration(self, obj):
        """Get active duration in seconds (excluding paused time)"""
        from django.utils import timezone
        if obj.status == 'stopped':
            total_duration = (obj.stopped_at - obj.start_time).total_seconds()
        else:
            total_duration = (timezone.now() - obj.start_time).total_seconds()
        return int(total_duration - obj.total_paused_duration)

    def get_distance_km(self, obj):
        """Get distance in kilometers"""
        return round(obj.current_distance / 1000, 2) if obj.current_distance else 0

    def get_distance_miles(self, obj):
        """Get distance in miles"""
        return round(obj.current_distance / 1609.34, 2) if obj.current_distance else 0


class LiveActivityCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating live activities"""

    class Meta:
        model = LiveActivity
        fields = ['type', 'title']

    def create(self, validated_data):
        validated_data['user'] = self.context['request'].user
        return LiveActivity.objects.create(**validated_data)


class GPSPointSerializer(serializers.Serializer):
    """Serializer for GPS point update"""

    latitude = serializers.FloatField()
    longitude = serializers.FloatField()
    altitude = serializers.FloatField(required=False, allow_null=True)
    speed = serializers.FloatField(required=False, allow_null=True)
    accuracy = serializers.FloatField(required=False, allow_null=True)
