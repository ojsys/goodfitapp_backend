"""
Chats (Phase 4): ride chats tied to one event, direct messages, and (Phase 8)
match chats.

Everything time-based is decided when a request comes in, so no background
worker is needed: a ride chat is read-only once `closes_at` passes, slow mode
is a timestamp on the member row, and live locations stop at `live_until`.
"""

from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

User = settings.AUTH_USER_MODEL

RIDE_CHAT_GRACE = timedelta(hours=48)
SLOW_WINDOW = timedelta(seconds=20)
SLOW_MAX = 3
SLOW_LOCK = timedelta(seconds=30)
# Three slow-mode locks within an hour pause the sender for a day.
SPAM_STRIKES = 3
SPAM_WINDOW = timedelta(hours=1)
SPAM_PAUSE = timedelta(hours=24)


class Chat(models.Model):
    KINDS = [('ride', 'Ride'), ('direct', 'Direct'), ('match', 'A Good Match')]
    kind = models.CharField(max_length=10, choices=KINDS)
    event = models.OneToOneField('events.Event', on_delete=models.CASCADE, null=True, blank=True,
                                 related_name='chat')
    # Direct: "<low id>:<high id>", so a pair has one chat.
    pair_key = models.CharField(max_length=40, null=True, blank=True, unique=True)
    opens_at = models.DateTimeField(default=timezone.now)
    closes_at = models.DateTimeField(null=True, blank=True)
    last_message_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'chats'

    @property
    def is_closed(self):
        return bool(self.closes_at and timezone.now() >= self.closes_at)

    @staticmethod
    def ride_close_time(event):
        end = event.end_time or (event.start_time + timedelta(minutes=event.duration_min or 180))
        return end + RIDE_CHAT_GRACE


class ChatMember(models.Model):
    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name='members')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_memberships')
    joined_at = models.DateTimeField(auto_now_add=True)
    last_read_id = models.BigIntegerField(default=0)
    # Slow mode (enforced on the server).
    locked_until = models.DateTimeField(null=True, blank=True)
    strikes = models.PositiveSmallIntegerField(default=0)
    strike_window_start = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'chat_members'
        constraints = [models.UniqueConstraint(fields=['chat', 'user'], name='chat_member_once')]


class ChatMessage(models.Model):
    ATTACHMENTS = [('', 'None'), ('route', 'Route'), ('photo', 'Photo'), ('location', 'Location')]
    MAX_BODY = 2000

    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='chat_messages')
    body = models.TextField(blank=True, max_length=MAX_BODY)
    attachment = models.CharField(max_length=10, choices=ATTACHMENTS, blank=True)
    route = models.ForeignKey('routes.Route', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    photo = models.ImageField(upload_to='chat_photos/', null=True, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    # Live location: updated by the sender until this time, then it stops.
    live_until = models.DateTimeField(null=True, blank=True)
    # The app's id for the message, so a resend from the outbox isn't a duplicate.
    client_id = models.CharField(max_length=40, blank=True)
    removed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    removed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'chat_messages'
        ordering = ['id']
        indexes = [models.Index(fields=['chat', 'id']), models.Index(fields=['chat', 'sender', 'created_at'])]
        constraints = [
            models.UniqueConstraint(fields=['sender', 'client_id'], condition=~models.Q(client_id=''),
                                    name='chat_message_client_id_once'),
        ]
