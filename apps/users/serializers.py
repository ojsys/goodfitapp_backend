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

    goals = UserGoalsSerializer(read_only=True)
    stats = UserStatsSerializer(read_only=True)
    preferences = UserPreferencesSerializer(read_only=True)
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = [
            'id', 'email', 'display_name', 'first_name', 'last_name', 'full_name',
            'avatar_url', 'bio', 'online_status', 'last_seen',
            'goals', 'stats', 'preferences', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'email', 'created_at', 'updated_at', 'last_seen']


class UserSerializer(serializers.ModelSerializer):
    """Basic User Serializer (for lists and minimal info)"""

    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = ['id', 'email', 'display_name', 'full_name', 'avatar_url', 'online_status']
        read_only_fields = ['id', 'email']


class RegisterSerializer(serializers.ModelSerializer):
    """Serializer for user registration"""

    password = serializers.CharField(write_only=True, min_length=8, style={'input_type': 'password'})
    password_confirm = serializers.CharField(write_only=True, min_length=8, style={'input_type': 'password'})

    class Meta:
        model = User
        fields = ['email', 'display_name', 'password', 'password_confirm']

    def validate(self, data):
        """Validate passwords match"""
        if data['password'] != data['password_confirm']:
            raise serializers.ValidationError({"password": "Passwords do not match"})
        return data

    def create(self, validated_data):
        """Create user with hashed password and related models"""
        # Remove password_confirm from validated data
        validated_data.pop('password_confirm')

        # Create user
        user = User.objects.create_user(
            email=validated_data['email'],
            password=validated_data['password'],
            display_name=validated_data.get('display_name', '')
        )

        # Create related models
        UserGoals.objects.create(user=user)
        UserStats.objects.create(user=user)
        UserPreferences.objects.create(user=user)

        # Create matching profile
        from apps.matching.models import UserProfile
        UserProfile.objects.create(
            user=user,
            age=25,  # Default age, can be updated later
            location_city='San Francisco',
            location_state='CA',
            latitude=37.7749,
            longitude=-122.4194,
            fitness_level='beginner',
            favorite_activities=['Walk', 'Run'],
            fitness_goals=['Stay Healthy'],
            looking_for=['workout_partner'],
            is_active=True,
        )

        return user


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
    """Serializer for updating user profile"""

    class Meta:
        model = User
        fields = ['display_name', 'first_name', 'last_name', 'avatar_url', 'bio']

    def update(self, instance, validated_data):
        """Update user profile"""
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance
