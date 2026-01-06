"""
Activity Models for GoodFit API
"""

from django.db import models
from django.conf import settings
from django.utils import timezone


class Activity(models.Model):
    """Activity log model"""

    ACTIVITY_TYPES = [
        ('Run', 'Run'),
        ('Cycle', 'Cycle'),
        ('Walk', 'Walk'),
        ('Swim', 'Swim'),
        ('Yoga', 'Yoga'),
        ('Strength', 'Strength'),
    ]

    # User relationship
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='activities')

    # Activity details
    type = models.CharField(max_length=20, choices=ACTIVITY_TYPES)
    title = models.CharField(max_length=200)
    notes = models.TextField(blank=True)

    # Time tracking
    start_time = models.DateTimeField()
    end_time = models.DateTimeField(null=True, blank=True)
    duration = models.IntegerField(help_text='Duration in minutes')

    # Performance metrics
    distance = models.FloatField(null=True, blank=True, help_text='Distance in meters')
    calories_burned = models.IntegerField(null=True, blank=True)
    average_speed = models.FloatField(null=True, blank=True, help_text='Speed in km/h')
    pace = models.FloatField(null=True, blank=True, help_text='Pace in min/km')
    elevation_gain = models.FloatField(null=True, blank=True, help_text='Elevation in meters')
    heart_rate_avg = models.IntegerField(null=True, blank=True)
    heart_rate_max = models.IntegerField(null=True, blank=True)

    # Location data
    start_latitude = models.FloatField(null=True, blank=True)
    start_longitude = models.FloatField(null=True, blank=True)
    start_address = models.CharField(max_length=500, blank=True)

    # Route data (stored as JSON)
    route = models.JSONField(null=True, blank=True, help_text='Array of route points with lat/lng/altitude/speed/timestamp')

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'activities'
        verbose_name = 'Activity'
        verbose_name_plural = 'Activities'
        ordering = ['-start_time']
        indexes = [
            models.Index(fields=['user', '-start_time']),
            models.Index(fields=['type']),
        ]

    def __str__(self):
        return f"{self.user.email} - {self.title} ({self.start_time.date()})"

    def save(self, *args, **kwargs):
        """Override save to update user stats"""
        is_new = self.pk is None
        super().save(*args, **kwargs)

        if is_new:
            self.update_user_stats(increment=True)

    def delete(self, *args, **kwargs):
        """Override delete to update user stats"""
        self.update_user_stats(increment=False)
        super().delete(*args, **kwargs)

    def update_user_stats(self, increment=True):
        """Update user statistics when activity is created or deleted"""
        from apps.users.models import UserStats
        from datetime import date

        stats, created = UserStats.objects.get_or_create(user=self.user)

        if increment:
            # Add to stats
            stats.total_workouts += 1
            stats.total_minutes += self.duration or 0
            stats.total_calories += self.calories_burned or 0
            stats.total_distance += self.distance or 0

            # Update streak
            today = date.today()
            if stats.last_activity_date:
                days_diff = (today - stats.last_activity_date).days
                if days_diff == 1:
                    stats.current_streak += 1
                elif days_diff > 1:
                    stats.current_streak = 1
            else:
                stats.current_streak = 1

            stats.last_activity_date = today

            if stats.current_streak > stats.longest_streak:
                stats.longest_streak = stats.current_streak

        else:
            # Subtract from stats
            stats.total_workouts = max(0, stats.total_workouts - 1)
            stats.total_minutes = max(0, stats.total_minutes - (self.duration or 0))
            stats.total_calories = max(0, stats.total_calories - (self.calories_burned or 0))
            stats.total_distance = max(0, stats.total_distance - (self.distance or 0))

        stats.save()


class DailySummary(models.Model):
    """Daily activity summary"""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='daily_summaries')
    date = models.DateField()

    # Daily totals
    total_steps = models.IntegerField(default=0)
    total_distance = models.FloatField(default=0.0, help_text='Distance in meters')
    total_calories = models.IntegerField(default=0)
    total_active_minutes = models.IntegerField(default=0)
    total_workouts = models.IntegerField(default=0)

    # Goals progress
    step_goal_progress = models.FloatField(default=0.0, help_text='Percentage 0-100')
    calorie_goal_progress = models.FloatField(default=0.0, help_text='Percentage 0-100')
    workout_goal_progress = models.FloatField(default=0.0, help_text='Percentage 0-100')

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'daily_summaries'
        verbose_name = 'Daily Summary'
        verbose_name_plural = 'Daily Summaries'
        ordering = ['-date']
        unique_together = ['user', 'date']
        indexes = [
            models.Index(fields=['user', '-date']),
        ]

    def __str__(self):
        return f"{self.user.email} - {self.date}"

    def calculate_progress(self):
        """Calculate goal progress percentages"""
        from apps.users.models import UserGoals

        try:
            goals = self.user.goals
        except UserGoals.DoesNotExist:
            goals = UserGoals.objects.create(user=self.user)

        # Calculate progress
        self.step_goal_progress = min(100, (self.total_steps / goals.daily_step_goal) * 100) if goals.daily_step_goal > 0 else 0
        self.calorie_goal_progress = min(100, (self.total_calories / goals.daily_calorie_goal) * 100) if goals.daily_calorie_goal > 0 else 0

        self.save()


class LiveActivity(models.Model):
    """Track ongoing/live activities with real-time GPS updates"""

    # User relationship
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='live_activities'
    )

    # Activity details
    type = models.CharField(max_length=20, choices=Activity.ACTIVITY_TYPES)
    title = models.CharField(max_length=200)

    # Status
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('paused', 'Paused'),
        ('stopped', 'Stopped'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')

    # Time tracking
    start_time = models.DateTimeField(auto_now_add=True)
    paused_at = models.DateTimeField(null=True, blank=True)
    stopped_at = models.DateTimeField(null=True, blank=True)
    total_paused_duration = models.IntegerField(default=0, help_text='Total paused time in seconds')

    # Current metrics (updated in real-time)
    current_distance = models.FloatField(default=0.0, help_text='Distance in meters')
    current_duration = models.IntegerField(default=0, help_text='Active duration in seconds')
    current_calories = models.IntegerField(default=0)
    current_pace = models.FloatField(null=True, blank=True, help_text='Current pace in min/km')
    current_speed = models.FloatField(null=True, blank=True, help_text='Current speed in km/h')

    # GPS points (stored as JSON array)
    route_points = models.JSONField(
        default=list,
        help_text='Array of GPS points: [{lat, lng, altitude, speed, timestamp, accuracy}]'
    )

    # Last known location
    last_latitude = models.FloatField(null=True, blank=True)
    last_longitude = models.FloatField(null=True, blank=True)
    last_update = models.DateTimeField(null=True, blank=True)

    # Linked final activity (when stopped)
    final_activity = models.OneToOneField(
        Activity,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='live_session'
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'live_activities'
        verbose_name = 'Live Activity'
        verbose_name_plural = 'Live Activities'
        ordering = ['-start_time']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['-start_time']),
        ]

    def __str__(self):
        return f"{self.user.email} - {self.title} ({self.status})"

    def add_gps_point(self, latitude, longitude, altitude=None, speed=None, accuracy=None):
        """Add a new GPS point to the route"""
        from datetime import datetime

        point = {
            'lat': latitude,
            'lng': longitude,
            'timestamp': datetime.now().isoformat(),
        }

        if altitude is not None:
            point['altitude'] = altitude
        if speed is not None:
            point['speed'] = speed
        if accuracy is not None:
            point['accuracy'] = accuracy

        self.route_points.append(point)
        self.last_latitude = latitude
        self.last_longitude = longitude
        self.last_update = timezone.now()

        # Calculate distance if we have previous points
        if len(self.route_points) >= 2:
            self.current_distance = self.calculate_total_distance()

        self.save()

    def calculate_total_distance(self):
        """Calculate total distance from GPS points using Haversine formula"""
        from math import radians, sin, cos, sqrt, atan2

        if len(self.route_points) < 2:
            return 0.0

        total_distance = 0.0
        R = 6371000  # Earth radius in meters

        for i in range(1, len(self.route_points)):
            prev_point = self.route_points[i - 1]
            curr_point = self.route_points[i]

            lat1 = radians(prev_point['lat'])
            lon1 = radians(prev_point['lng'])
            lat2 = radians(curr_point['lat'])
            lon2 = radians(curr_point['lng'])

            dlat = lat2 - lat1
            dlon = lon2 - lon1

            a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
            c = 2 * atan2(sqrt(a), sqrt(1 - a))

            distance = R * c
            total_distance += distance

        return total_distance

    def pause(self):
        """Pause the activity"""
        if self.status == 'active':
            self.status = 'paused'
            self.paused_at = timezone.now()
            self.save()

    def resume(self):
        """Resume the activity from pause"""
        if self.status == 'paused' and self.paused_at:
            # Add paused duration to total
            paused_duration = (timezone.now() - self.paused_at).total_seconds()
            self.total_paused_duration += int(paused_duration)
            self.status = 'active'
            self.paused_at = None
            self.save()

    def stop(self):
        """Stop the activity and create final Activity record"""
        if self.status in ['active', 'paused']:
            self.status = 'stopped'
            self.stopped_at = timezone.now()

            # Calculate final metrics
            total_duration_seconds = (self.stopped_at - self.start_time).total_seconds()
            active_duration_seconds = total_duration_seconds - self.total_paused_duration
            active_duration_minutes = int(active_duration_seconds / 60)

            # Create final activity record
            activity = Activity.objects.create(
                user=self.user,
                type=self.type,
                title=self.title,
                start_time=self.start_time,
                end_time=self.stopped_at,
                duration=active_duration_minutes,
                distance=self.current_distance,
                calories_burned=self.current_calories,
                average_speed=self.current_speed,
                route=self.route_points,
                start_latitude=self.route_points[0]['lat'] if self.route_points else None,
                start_longitude=self.route_points[0]['lng'] if self.route_points else None,
            )

            self.final_activity = activity
            self.save()

            return activity
