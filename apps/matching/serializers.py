"""
Matching Serializers for GoodFit API
Serializers for user profiles, swipes, and matches
"""

from rest_framework import serializers
from django.contrib.auth import get_user_model
from apps.matching.models import UserProfile, Swipe, Match

User = get_user_model()


class UserProfileSerializer(serializers.ModelSerializer):
    """Serializer for user matching profiles"""

    user_id = serializers.IntegerField(source='user.id', read_only=True)
    display_name = serializers.CharField(source='user.display_name', read_only=True)
    profile_photo = serializers.CharField(source='user.avatar_url', read_only=True)

    class Meta:
        model = UserProfile
        fields = [
            'id',
            'user_id',
            'display_name',
            'profile_photo',
            'age',
            'gender',
            'location_city',
            'location_state',
            'latitude',
            'longitude',
            'fitness_level',
            'favorite_activities',
            'fitness_goals',
            'looking_for',
            'preferred_age_min',
            'preferred_age_max',
            'preferred_distance_miles',
            'preferred_gender',
            'prompt_question',
            'is_active',
            'is_verified',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'user_id', 'display_name', 'profile_photo', 'created_at', 'updated_at', 'is_verified']


class UserProfileCreateUpdateSerializer(serializers.ModelSerializer):
    """Serializer for creating/updating user profiles"""

    class Meta:
        model = UserProfile
        fields = [
            'age',
            'gender',
            'location_city',
            'location_state',
            'latitude',
            'longitude',
            'fitness_level',
            'favorite_activities',
            'fitness_goals',
            'looking_for',
            'preferred_age_min',
            'preferred_age_max',
            'preferred_distance_miles',
            'preferred_gender',
            'prompt_question',
            'is_active',
        ]


class MatchedUserSerializer(serializers.ModelSerializer):
    """Minimal user info for match discovery cards"""

    user_id = serializers.IntegerField(source='user.id', read_only=True)
    display_name = serializers.CharField(source='user.display_name', read_only=True)
    profile_photo = serializers.CharField(source='user.avatar_url', read_only=True)
    distance = serializers.SerializerMethodField()

    class Meta:
        model = UserProfile
        fields = [
            'user_id',
            'display_name',
            'profile_photo',
            'age',
            'gender',
            'location_city',
            'fitness_level',
            'favorite_activities',
            'fitness_goals',
            'looking_for',
            'prompt_question',
            'distance',
        ]

    def get_distance(self, obj):
        """Calculate distance from current user"""
        request = self.context.get('request')
        if request and hasattr(request.user, 'matching_profile'):
            current_profile = request.user.matching_profile
            if current_profile.latitude and current_profile.longitude:
                distance = obj.distance_from(current_profile.latitude, current_profile.longitude)
                if distance is not None:
                    return round(distance, 1)
        return None


class SwipeSerializer(serializers.ModelSerializer):
    """Serializer for swipes"""

    from_user_name = serializers.CharField(source='from_user.display_name', read_only=True)
    to_user_name = serializers.CharField(source='to_user.display_name', read_only=True)

    class Meta:
        model = Swipe
        fields = [
            'id',
            'from_user',
            'from_user_name',
            'to_user',
            'to_user_name',
            'action',
            'created_at',
        ]
        read_only_fields = ['id', 'from_user', 'from_user_name', 'to_user_name', 'created_at']


class SwipeCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating swipes"""

    class Meta:
        model = Swipe
        fields = ['to_user', 'action']

    def validate(self, data):
        """Validate swipe data"""
        request = self.context.get('request')
        if request:
            from_user = request.user
            to_user = data.get('to_user')

            # Can't swipe on yourself
            if from_user == to_user:
                raise serializers.ValidationError("You cannot swipe on yourself")

            # Check if already swiped
            if Swipe.objects.filter(from_user=from_user, to_user=to_user).exists():
                raise serializers.ValidationError("You have already swiped on this user")

        return data

    def create(self, validated_data):
        """Create swipe with current user as from_user"""
        request = self.context.get('request')
        validated_data['from_user'] = request.user
        return super().create(validated_data)


class MatchSerializer(serializers.ModelSerializer):
    """Serializer for matches"""

    user1_name = serializers.CharField(source='user1.display_name', read_only=True)
    user1_photo = serializers.CharField(source='user1.avatar_url', read_only=True)
    user2_name = serializers.CharField(source='user2.display_name', read_only=True)
    user2_photo = serializers.CharField(source='user2.avatar_url', read_only=True)
    other_user = serializers.SerializerMethodField()

    class Meta:
        model = Match
        fields = [
            'id',
            'user1',
            'user1_name',
            'user1_photo',
            'user2',
            'user2_name',
            'user2_photo',
            'other_user',
            'is_active',
            'matched_at',
            'unmatched_at',
        ]
        read_only_fields = ['id', 'user1', 'user2', 'matched_at']

    def get_other_user(self, obj):
        """Get the other user's profile in the match"""
        request = self.context.get('request')
        if request and request.user:
            other = obj.get_other_user(request.user)
            if hasattr(other, 'matching_profile'):
                return MatchedUserSerializer(other.matching_profile, context=self.context).data
        return None
