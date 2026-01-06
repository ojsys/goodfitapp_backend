"""
User Models for GoodFit API
"""

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    """Custom user manager"""

    def create_user(self, email, password=None, **extra_fields):
        """Create and save a regular user"""
        if not email:
            raise ValueError('Users must have an email address')

        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        """Create and save a superuser"""
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True')

        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """Custom User model"""

    # Authentication
    email = models.EmailField(unique=True, max_length=255)
    password = models.CharField(max_length=128)

    # Profile Information
    display_name = models.CharField(max_length=100, blank=True)
    first_name = models.CharField(max_length=50, blank=True)
    last_name = models.CharField(max_length=50, blank=True)
    avatar_url = models.URLField(max_length=500, blank=True, null=True)
    bio = models.TextField(max_length=500, blank=True)

    # Status
    online_status = models.CharField(
        max_length=20,
        choices=[
            ('online', 'Online'),
            ('offline', 'Offline'),
            ('away', 'Away'),
        ],
        default='offline'
    )
    last_seen = models.DateTimeField(auto_now=True)

    # Permissions
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # User Manager
    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['display_name']

    class Meta:
        db_table = 'users'
        verbose_name = 'User'
        verbose_name_plural = 'Users'
        ordering = ['-created_at']

    def __str__(self):
        return self.email

    @property
    def full_name(self):
        """Get user's full name"""
        return f"{self.first_name} {self.last_name}".strip() or self.display_name


class UserGoals(models.Model):
    """User fitness goals"""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='goals')

    # Goals
    selected_goals = models.JSONField(default=list)  # List of goal strings
    daily_step_goal = models.IntegerField(default=10000)
    weekly_workout_goal = models.IntegerField(default=5)
    daily_calorie_goal = models.IntegerField(default=500)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'user_goals'
        verbose_name = 'User Goals'
        verbose_name_plural = 'User Goals'

    def __str__(self):
        return f"Goals for {self.user.email}"


class UserStats(models.Model):
    """User activity statistics"""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='stats')

    # Streaks
    current_streak = models.IntegerField(default=0)
    longest_streak = models.IntegerField(default=0)
    last_activity_date = models.DateField(null=True, blank=True)

    # Totals
    total_workouts = models.IntegerField(default=0)
    total_minutes = models.IntegerField(default=0)
    total_calories = models.IntegerField(default=0)
    total_distance = models.FloatField(default=0.0)  # in meters

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'user_stats'
        verbose_name = 'User Stats'
        verbose_name_plural = 'User Stats'

    def __str__(self):
        return f"Stats for {self.user.email}"


class UserPreferences(models.Model):
    """User app preferences"""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='preferences')

    # Notification Settings
    email_notifications = models.BooleanField(default=True)
    push_notifications = models.BooleanField(default=True)
    activity_reminders = models.BooleanField(default=True)

    # Privacy Settings
    profile_visibility = models.CharField(
        max_length=20,
        choices=[
            ('public', 'Public'),
            ('friends', 'Friends Only'),
            ('private', 'Private'),
        ],
        default='public'
    )
    show_stats_publicly = models.BooleanField(default=True)

    # App Settings
    theme = models.CharField(
        max_length=10,
        choices=[
            ('light', 'Light'),
            ('dark', 'Dark'),
            ('auto', 'Auto'),
        ],
        default='dark'
    )
    units = models.CharField(
        max_length=10,
        choices=[
            ('metric', 'Metric'),
            ('imperial', 'Imperial'),
        ],
        default='metric'
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'user_preferences'
        verbose_name = 'User Preferences'
        verbose_name_plural = 'User Preferences'

    def __str__(self):
        return f"Preferences for {self.user.email}"
