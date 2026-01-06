"""
Event Models for GoodFit API
"""

from django.db import models
from django.conf import settings
from django.utils import timezone


class Event(models.Model):
    """Community fitness event model"""

    VIBE_CHOICES = [
        ('Chill', 'Chill'),
        ('Intense', 'Intense'),
        ('Social', 'Social'),
        ('Educational', 'Educational'),
    ]

    PRICE_TYPE_CHOICES = [
        ('Free', 'Free'),
        ('Paid', 'Paid'),
    ]

    # Basic info
    title = models.CharField(max_length=200)
    description = models.TextField()
    image_url = models.URLField(max_length=500, blank=True)

    # Host information
    host = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='hosted_events'
    )
    host_name = models.CharField(max_length=100, help_text='Display name for host/organization')

    # Event details
    vibe = models.CharField(max_length=20, choices=VIBE_CHOICES)
    price_type = models.CharField(max_length=10, choices=PRICE_TYPE_CHOICES, default='Free')
    price_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Price in dollars (if paid)'
    )

    # Time and location
    start_time = models.DateTimeField()
    end_time = models.DateTimeField(null=True, blank=True)
    location_name = models.CharField(max_length=200, help_text='e.g., Griffith Park')
    location_address = models.CharField(max_length=500)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    # Capacity
    max_attendees = models.IntegerField(null=True, blank=True, help_text='Leave blank for unlimited')
    is_full = models.BooleanField(default=False)

    # Tags and categorization
    tags = models.JSONField(default=list, help_text='Array of tag strings')

    # What to bring list
    what_to_bring = models.JSONField(default=list, help_text='Array of items to bring')

    # Status
    is_active = models.BooleanField(default=True)
    is_cancelled = models.BooleanField(default=False)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'events'
        verbose_name = 'Event'
        verbose_name_plural = 'Events'
        ordering = ['start_time']
        indexes = [
            models.Index(fields=['start_time']),
            models.Index(fields=['host']),
            models.Index(fields=['is_active', 'is_cancelled']),
        ]

    def __str__(self):
        return f"{self.title} - {self.start_time.date()}"

    @property
    def attendee_count(self):
        """Get current number of RSVPs"""
        return self.rsvps.filter(status='going').count()

    @property
    def is_past(self):
        """Check if event has passed"""
        return self.start_time < timezone.now()

    @property
    def formatted_date(self):
        """Format date for display"""
        return self.start_time.strftime('%a, %b %d')

    @property
    def formatted_time(self):
        """Format time for display"""
        return self.start_time.strftime('%I:%M %p')


class EventRSVP(models.Model):
    """Event RSVP/attendance model"""

    STATUS_CHOICES = [
        ('going', 'Going'),
        ('interested', 'Interested'),
        ('not_going', 'Not Going'),
    ]

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='rsvps')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='event_rsvps')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='going')

    # Check-in for attendance tracking
    checked_in = models.BooleanField(default=False)
    check_in_time = models.DateTimeField(null=True, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'event_rsvps'
        verbose_name = 'Event RSVP'
        verbose_name_plural = 'Event RSVPs'
        unique_together = ['event', 'user']
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['event', 'status']),
            models.Index(fields=['user', 'status']),
        ]

    def __str__(self):
        return f"{self.user.email} - {self.event.title} ({self.status})"

    def save(self, *args, **kwargs):
        """Override save to update event full status"""
        super().save(*args, **kwargs)

        # Check if event is now full
        if self.event.max_attendees:
            going_count = self.event.rsvps.filter(status='going').count()
            self.event.is_full = going_count >= self.event.max_attendees
            self.event.save(update_fields=['is_full'])
