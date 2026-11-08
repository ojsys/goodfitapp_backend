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
    # An externally hosted avatar (set by pasting a link).
    avatar_url = models.URLField(max_length=500, blank=True, null=True)
    # An avatar uploaded from the device. Takes precedence over avatar_url.
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)
    bio = models.TextField(max_length=500, blank=True)

    # Body metrics. Weight is what makes calorie estimation possible — without
    # it the app cannot turn a duration into an energy figure.
    weight_kg = models.FloatField(null=True, blank=True, help_text='Body weight in kilograms')
    height_cm = models.FloatField(null=True, blank=True, help_text='Height in centimetres')

    # --- A Good Fit membership ------------------------------------------------
    # Birthday, encrypted (see apps/users/age_gate.py). Set once at sign-up;
    # only support can change it. Never serialized to other members.
    birthday_enc = models.TextField(blank=True, default='')
    # IANA time zone the age is computed in.
    timezone = models.CharField(max_length=64, default='UTC')

    neighborhood = models.CharField(max_length=80, blank=True)
    headline = models.CharField(max_length=80, blank=True)

    INTENTS = ('community', 'fitness', 'romantic')
    INTERESTS = (
        'running', 'cycling', 'strength', 'yoga', 'hiking',
        'pilates', 'hiit', 'crossfit',
    )
    MAX_INTERESTS = 3
    # What the member is here for. 'romantic' turns on A Good Match.
    intents = models.JSONField(default=list, blank=True)
    interests = models.JSONField(default=list, blank=True)

    units = models.CharField(
        max_length=2, choices=[('mi', 'Miles'), ('km', 'Kilometers')], default='mi'
    )
    plan = models.CharField(
        max_length=10, choices=[('free', 'Free'), ('plus', 'Plus')], default='free'
    )

    guidelines_version = models.CharField(max_length=20, blank=True)
    guidelines_agreed_at = models.DateTimeField(null=True, blank=True)
    # The optional photo step was seen (added or skipped).
    photo_step_done = models.BooleanField(default=False)
    # New-member Home: the getting-started card was closed (X). It then
    # shows collapsed ("Getting started · 2 of 6  Show").
    checklist_hidden = models.BooleanField(default=False)
    # Privacy and Safety: hide the start and end of every track from others,
    # even with no saved place. On by default (requirements: Location).
    hide_track_ends = models.BooleanField(default=True)

    # Fit Buddies distance ("2.4 mi away"). Rounded to 2 decimals (about
    # 1 km) before it's stored, so no address or routine can be read from it.
    approx_lat = models.FloatField(null=True, blank=True)
    approx_lng = models.FloatField(null=True, blank=True)
    # Profile extras shown on Fit Buddies ("Coffee after"; "Post-Ride Snack?").
    buddy_tags = models.JSONField(default=list, blank=True)
    prompt_question = models.CharField(max_length=60, blank=True)
    prompt_answer = models.CharField(max_length=150, blank=True)
    # Verified badge. How members verify is an open decision (BUILD_PLAN).
    id_verified = models.BooleanField(default=False)
    # Host an event > community ride: the host agreement, once.
    host_agreed_at = models.DateTimeField(null=True, blank=True)

    # Social sign-in subjects (Apple "sub", Google "sub").
    apple_sub = models.CharField(max_length=255, null=True, blank=True, unique=True)
    google_sub = models.CharField(max_length=255, null=True, blank=True, unique=True)

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


    # --- Birthday and age -----------------------------------------------------

    @property
    def birthday(self):
        from .age_gate import decrypt_birthday
        return decrypt_birthday(self.birthday_enc)

    def set_birthday_once(self, birthday):
        """Store the birthday. Members can't change it after sign-up."""
        from .age_gate import encrypt_birthday
        if self.birthday_enc:
            raise ValueError('Birthday is already set')
        self.birthday_enc = encrypt_birthday(birthday)

    @property
    def age(self):
        from .age_gate import compute_age
        b = self.birthday
        return compute_age(b, self.timezone) if b else None

    # --- Onboarding --------------------------------------------------------

    @property
    def next_step(self):
        """Where sign-up resumes. 'done' means a full member.

        Order matches the onboarding flow: birthday (Apple/Google, and
        accounts from before the age gate), What's your good fit, Interests,
        Profile photo (optional), Community Guidelines.
        """
        if not self.birthday_enc:
            return 'birthday'
        if not self.intents:
            return 'intent'
        if not self.interests:
            return 'interests'
        if not self.photo_step_done and not (self.avatar or self.avatar_url):
            return 'photo'
        if not self.guidelines_agreed_at:
            return 'guidelines'
        return 'done'

    @property
    def is_member(self):
        return self.next_step == 'done'

    @property
    def match_opted_in(self):
        return 'romantic' in (self.intents or [])

    def photo_url(self, request=None):
        """The avatar to display: the uploaded file if there is one, else the
        external link. Absolute when a request is available, so mobile clients
        can load it without knowing the host."""
        if self.avatar:
            url = self.avatar.url
            return request.build_absolute_uri(url) if request else url
        return self.avatar_url or None


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


class SocialAgeBlock(models.Model):
    """An Apple or Google sign-in ID that failed the 21+ check.

    Holds a keyed hash of the ID only, never the birthday, so a retry from the
    same ID with a different date is refused.
    """

    provider = models.CharField(max_length=10, choices=[('apple', 'Apple'), ('google', 'Google')])
    subject_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'social_age_blocks'


class AgeGateEvent(models.Model):
    """Product analytics for the age gate: pass or fail only, never the
    birthday or who it was."""

    METHODS = [('email', 'Email'), ('apple', 'Apple'), ('google', 'Google'), ('existing', 'Existing account')]
    method = models.CharField(max_length=10, choices=METHODS)
    passed = models.BooleanField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'age_gate_events'
