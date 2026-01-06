"""
Matching Models for GoodFit API
User profiles, swipes, and matches for the fitness buddy matching system
"""

from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator


class UserProfile(models.Model):
    """Extended user profile for matching"""

    GENDER_CHOICES = [
        ('male', 'Male'),
        ('female', 'Female'),
        ('non_binary', 'Non-Binary'),
        ('prefer_not_to_say', 'Prefer Not to Say'),
    ]

    EXPERIENCE_LEVEL_CHOICES = [
        ('beginner', 'Beginner'),
        ('intermediate', 'Intermediate'),
        ('advanced', 'Advanced'),
        ('elite', 'Elite'),
    ]

    # User relationship
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='matching_profile'
    )

    # Personal Information
    age = models.IntegerField(
        validators=[MinValueValidator(18), MaxValueValidator(100)],
        null=True,
        blank=True
    )
    gender = models.CharField(max_length=20, choices=GENDER_CHOICES, blank=True)
    location_city = models.CharField(max_length=100, blank=True)
    location_state = models.CharField(max_length=100, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    # Fitness Profile
    fitness_level = models.CharField(
        max_length=20,
        choices=EXPERIENCE_LEVEL_CHOICES,
        default='beginner'
    )
    favorite_activities = models.JSONField(
        default=list,
        help_text='List of favorite activity types'
    )
    fitness_goals = models.JSONField(
        default=list,
        help_text='List of fitness goals'
    )

    # Matching Preferences
    looking_for = models.JSONField(
        default=list,
        help_text='What user is looking for: workout_partner, running_buddy, gym_buddy, etc.'
    )
    preferred_age_min = models.IntegerField(default=18)
    preferred_age_max = models.IntegerField(default=100)
    preferred_distance_miles = models.IntegerField(default=25, help_text='Max distance in miles')
    preferred_gender = models.JSONField(
        default=list,
        help_text='List of preferred genders to match with'
    )

    # Profile Prompts (for matching screen)
    prompt_question = models.CharField(
        max_length=200,
        default='Ask me about my post-run snack routine 🥑',
        help_text='Fun prompt to start conversations'
    )

    # Visibility
    is_active = models.BooleanField(default=True, help_text='Profile visible in matching')
    is_verified = models.BooleanField(default=False)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'user_profiles'
        verbose_name = 'User Profile'
        verbose_name_plural = 'User Profiles'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.display_name}'s Profile"

    def distance_from(self, latitude, longitude):
        """Calculate distance from given coordinates using Haversine formula"""
        if not self.latitude or not self.longitude:
            return None

        from math import radians, sin, cos, sqrt, atan2

        R = 3959  # Earth radius in miles

        lat1 = radians(self.latitude)
        lon1 = radians(self.longitude)
        lat2 = radians(latitude)
        lon2 = radians(longitude)

        dlat = lat2 - lat1
        dlon = lon2 - lon1

        a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
        c = 2 * atan2(sqrt(a), sqrt(1 - a))

        return R * c


class Swipe(models.Model):
    """Track user swipes/likes"""

    ACTION_CHOICES = [
        ('like', 'Like'),
        ('pass', 'Pass'),
        ('super_like', 'Super Like'),
    ]

    # Who swiped on whom
    from_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='swipes_made'
    )
    to_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='swipes_received'
    )

    # Swipe action
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'swipes'
        verbose_name = 'Swipe'
        verbose_name_plural = 'Swipes'
        unique_together = ['from_user', 'to_user']
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['from_user', 'action']),
            models.Index(fields=['to_user', 'action']),
        ]

    def __str__(self):
        return f"{self.from_user.display_name} {self.action}d {self.to_user.display_name}"

    def save(self, *args, **kwargs):
        """Override save to check for mutual matches"""
        is_new = self.pk is None
        super().save(*args, **kwargs)

        # If this is a like, check for mutual match
        if is_new and self.action == 'like':
            # Check if the other user also liked this user
            mutual_like = Swipe.objects.filter(
                from_user=self.to_user,
                to_user=self.from_user,
                action='like'
            ).exists()

            if mutual_like:
                # Create a match if it doesn't exist
                Match.objects.get_or_create(
                    user1=self.from_user,
                    user2=self.to_user
                )


class Match(models.Model):
    """Mutual matches between users"""

    # Matched users (order doesn't matter, always store lower ID first for consistency)
    user1 = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='matches_as_user1'
    )
    user2 = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='matches_as_user2'
    )

    # Match status
    is_active = models.BooleanField(default=True)
    unmatched_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='unmatches_initiated'
    )
    unmatched_at = models.DateTimeField(null=True, blank=True)

    # Timestamps
    matched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'matches'
        verbose_name = 'Match'
        verbose_name_plural = 'Matches'
        unique_together = ['user1', 'user2']
        ordering = ['-matched_at']
        indexes = [
            models.Index(fields=['user1', 'is_active']),
            models.Index(fields=['user2', 'is_active']),
        ]

    def __str__(self):
        return f"Match: {self.user1.display_name} ↔ {self.user2.display_name}"

    def save(self, *args, **kwargs):
        """Ensure user1 ID is always less than user2 ID for consistency"""
        if self.user1.id > self.user2.id:
            self.user1, self.user2 = self.user2, self.user1
        super().save(*args, **kwargs)

    def get_other_user(self, user):
        """Get the other user in the match"""
        return self.user2 if self.user1 == user else self.user1

    def unmatch(self, user):
        """Unmatch users"""
        self.is_active = False
        self.unmatched_by = user
        self.unmatched_at = timezone.now()
        self.save()
