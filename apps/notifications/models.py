"""
Notifications (You-Notifications) and push devices.

A notification is a line of text with some words in bold (`parts`), an
icon or the person it's from, and where tapping it goes (`link`, an app
route such as /activity/12). Props on the same thing are grouped into one
row while it's unread.
"""

from django.conf import settings
from django.db import models

User = settings.AUTH_USER_MODEL

# Categories members can turn off (Settings → Notifications). Safety notes
# (your report was reviewed, a warning) can't be turned off.
CATEGORIES = [
    ('ride_reminders', 'Ride reminders'),      # RSVPs, start times, changes, invites
    ('props_comments', 'Props & comments'),    # props, comments, follows, waves
    ('club_announcements', 'Club announcements'),
    ('messages', 'Messages'),                  # push only; chats have their own inbox
    ('match', 'A Good Match'),                 # Phase 8
    ('safety', 'Safety'),
]
TOGGLEABLE = ['ride_reminders', 'props_comments', 'club_announcements', 'messages']


class Notification(models.Model):
    KINDS = [
        ('props', 'Props'), ('comment', 'Comment'), ('follow', 'Follow'), ('wave', 'Wave'),
        ('ride_invite', 'Ride invite'), ('ride_update', 'Ride update'), ('ride_reminder', 'Ride reminder'),
        ('announcement', 'Club announcement'), ('report_update', 'Report update'),
        ('warning', 'Warning'), ('segment', 'Segment'), ('challenge', 'Challenge'), ('match', 'A Good Match'),
    ]
    CATEGORY = {
        'props': 'props_comments', 'comment': 'props_comments', 'follow': 'props_comments',
        'wave': 'props_comments', 'ride_invite': 'ride_reminders', 'ride_update': 'ride_reminders',
        'ride_reminder': 'ride_reminders', 'announcement': 'club_announcements', 'report_update': 'safety',
        'warning': 'safety', 'segment': 'props_comments', 'challenge': 'props_comments', 'match': 'match',
    }

    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    kind = models.CharField(max_length=20, choices=KINDS)
    actor = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='+')
    # [[text, bold], ...]: "Alex" (bold) " gave props to your " ...
    parts = models.JSONField(default=list)
    # Who's in a grouped row (props): most recent first, and how many in all.
    actor_ids = models.JSONField(default=list, blank=True)
    count = models.PositiveIntegerField(default=1)
    # Where tapping goes in the app.
    link = models.CharField(max_length=200, blank=True)
    group_key = models.CharField(max_length=80, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'notifications'
        ordering = ['-updated_at']
        indexes = [models.Index(fields=['recipient', 'read_at', '-updated_at'])]

    def __str__(self):
        return ''.join(p[0] for p in self.parts)[:80]

    @property
    def category(self):
        return self.CATEGORY.get(self.kind, 'props_comments')

    @property
    def text(self):
        return ''.join(p[0] for p in self.parts)


class NotificationSettings(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='notification_settings')
    ride_reminders = models.BooleanField(default=True)
    props_comments = models.BooleanField(default=True)
    club_announcements = models.BooleanField(default=True)
    messages = models.BooleanField(default=True)

    class Meta:
        db_table = 'notification_settings'

    @staticmethod
    def of(user):
        return NotificationSettings.objects.get_or_create(user=user)[0]

    def allows(self, category):
        return getattr(self, category, True) if category in TOGGLEABLE else True


class Device(models.Model):
    """A phone that can get push notifications (FCM token)."""

    PLATFORMS = [('ios', 'iOS'), ('android', 'Android')]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='devices')
    token = models.CharField(max_length=300, unique=True)
    platform = models.CharField(max_length=10, choices=PLATFORMS)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'push_devices'
