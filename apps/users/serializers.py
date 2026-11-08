"""
Serializers for User models
"""

from rest_framework import serializers
from django.contrib.auth import get_user_model, authenticate
from .models import UserGoals, UserStats, UserPreferences

User = get_user_model()


class UserGoalsSerializer(serializers.ModelSerializer):
    """Serializer for User Goals"""

    class Meta:
        model = UserGoals
        fields = ['selected_goals', 'daily_step_goal', 'weekly_workout_goal', 'daily_calorie_goal']


class UserStatsSerializer(serializers.ModelSerializer):
    """Serializer for User Stats"""

    class Meta:
        model = UserStats
        fields = [
            'current_streak', 'longest_streak', 'last_activity_date',
            'total_workouts', 'total_minutes', 'total_calories', 'total_distance'
        ]


class UserPreferencesSerializer(serializers.ModelSerializer):
    """Serializer for User Preferences"""

    class Meta:
        model = UserPreferences
        fields = [
            'email_notifications', 'push_notifications', 'activity_reminders',
            'profile_visibility', 'show_stats_publicly', 'theme', 'units'
        ]


class UserProfileSerializer(serializers.ModelSerializer):
    """Serializer for User Profile (Full details)"""

    photo_url = serializers.SerializerMethodField()
    # The member's own birthday, read-only (support changes it). Only ever
    # sent to the member themselves.
    birthday = serializers.SerializerMethodField()
    age = serializers.IntegerField(read_only=True)
    next_step = serializers.CharField(read_only=True)
    is_member = serializers.BooleanField(read_only=True)
    match_opted_in = serializers.BooleanField(read_only=True)
    # 'apple' / 'google' when the account was created with one (no password).
    signin_provider = serializers.SerializerMethodField()
    goals = UserGoalsSerializer(read_only=True)
    stats = UserStatsSerializer(read_only=True)
    preferences = UserPreferencesSerializer(read_only=True)
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = User
        # Two apps define a `UserProfileSerializer`; an explicit ref_name keeps
        # them distinct in the OpenAPI schema, which otherwise fails to build.
        ref_name = 'AccountProfile'
        fields = [
            'id', 'email', 'display_name', 'first_name', 'last_name', 'full_name',
            'avatar_url', 'avatar', 'photo_url', 'bio', 'online_status',
            'last_seen', 'weight_kg', 'height_cm',
            'birthday', 'age', 'neighborhood', 'headline', 'intents', 'interests',
            'units', 'plan', 'guidelines_version', 'guidelines_agreed_at',
            'next_step', 'is_member', 'match_opted_in', 'signin_provider',
            'goals', 'stats', 'preferences', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'email', 'created_at', 'updated_at', 'last_seen', 'avatar',
            'intents', 'interests', 'plan', 'guidelines_version', 'guidelines_agreed_at',
        ]

    def get_photo_url(self, obj):
        return obj.photo_url(self.context.get('request'))

    def get_signin_provider(self, obj):
        if obj.has_usable_password():
            return None
        return 'apple' if obj.apple_sub else 'google' if obj.google_sub else None

    def get_birthday(self, obj):
        b = obj.birthday
        return b.isoformat() if b else None


# The signed-in member's own profile.
MeSerializer = UserProfileSerializer


class UserSerializer(serializers.ModelSerializer):
    """Basic User Serializer (for lists and minimal info)"""

    full_name = serializers.CharField(read_only=True)
    photo_url = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'email', 'display_name', 'full_name', 'avatar_url',
            'photo_url', 'online_status',
        ]

    def get_photo_url(self, obj):
        return obj.photo_url(self.context.get('request'))
        read_only_fields = ['id', 'email']


class LoginSerializer(serializers.Serializer):
    """Serializer for user login"""

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, style={'input_type': 'password'})

    def validate(self, data):
        """Validate user credentials"""
        email = data.get('email')
        password = data.get('password')

        if email and password:
            user = authenticate(
                request=self.context.get('request'),
                username=email,
                password=password
            )

            if not user:
                raise serializers.ValidationError("Invalid email or password")

            if not user.is_active:
                raise serializers.ValidationError("User account is disabled")

            data['user'] = user
            return data
        else:
            raise serializers.ValidationError("Must include email and password")


class ChangePasswordSerializer(serializers.Serializer):
    """Serializer for changing password"""

    old_password = serializers.CharField(write_only=True, required=True)
    new_password = serializers.CharField(write_only=True, required=True, min_length=8)

    def validate_old_password(self, value):
        """Validate old password is correct"""
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError("Old password is incorrect")
        return value

    def save(self):
        """Update user password"""
        user = self.context['request'].user
        user.set_password(self.validated_data['new_password'])
        user.save()
        return user


class UpdateProfileSerializer(serializers.ModelSerializer):
    """Edit profile. The birthday is not editable (support only)."""

    bio = serializers.CharField(max_length=150, allow_blank=True, required=False)

    class Meta:
        model = User
        fields = [
            'display_name', 'first_name', 'last_name', 'avatar_url', 'bio',
            'weight_kg', 'height_cm', 'neighborhood', 'headline', 'units',
        ]

    def update(self, instance, validated_data):
        """Update user profile"""
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance
