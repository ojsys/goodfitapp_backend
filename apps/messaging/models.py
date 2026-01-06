"""
Messaging Models for GoodFit API
Conversations and messages between matched users
"""

from django.db import models
from django.conf import settings
from django.utils import timezone
from django.db.models import Q


class Conversation(models.Model):
    """Conversation between two matched users"""

    # Participants (always store lower ID first for consistency)
    participant1 = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='conversations_as_participant1'
    )
    participant2 = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='conversations_as_participant2'
    )

    # Match reference (optional, for context)
    match = models.ForeignKey(
        'matching.Match',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='conversation'
    )

    # Status
    is_active = models.BooleanField(default=True)

    # Last message cache for conversation list
    last_message_text = models.TextField(blank=True)
    last_message_at = models.DateTimeField(null=True, blank=True)
    last_message_sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+'
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'conversations'
        verbose_name = 'Conversation'
        verbose_name_plural = 'Conversations'
        unique_together = ['participant1', 'participant2']
        ordering = ['-last_message_at', '-created_at']
        indexes = [
            models.Index(fields=['participant1', 'is_active']),
            models.Index(fields=['participant2', 'is_active']),
            models.Index(fields=['-last_message_at']),
        ]

    def __str__(self):
        return f"Conversation: {self.participant1.display_name} ↔ {self.participant2.display_name}"

    def save(self, *args, **kwargs):
        """Ensure participant1 ID is always less than participant2 ID"""
        if self.participant1.id > self.participant2.id:
            self.participant1, self.participant2 = self.participant2, self.participant1
        super().save(*args, **kwargs)

    def get_other_participant(self, user):
        """Get the other participant in the conversation"""
        return self.participant2 if self.participant1 == user else self.participant1

    @classmethod
    def get_or_create_for_users(cls, user1, user2):
        """Get or create a conversation between two users"""
        # Ensure consistent ordering
        if user1.id > user2.id:
            user1, user2 = user2, user1

        conversation, created = cls.objects.get_or_create(
            participant1=user1,
            participant2=user2
        )
        return conversation, created


class Message(models.Model):
    """Individual message in a conversation"""

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='messages'
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='messages_sent'
    )

    # Message content
    text = models.TextField()

    # Message type (for future expansion: text, image, etc.)
    message_type = models.CharField(
        max_length=20,
        default='text',
        choices=[
            ('text', 'Text'),
            ('image', 'Image'),
            ('system', 'System'),
        ]
    )

    # Read status
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'messages'
        verbose_name = 'Message'
        verbose_name_plural = 'Messages'
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['conversation', 'created_at']),
            models.Index(fields=['conversation', 'is_read']),
            models.Index(fields=['sender', 'created_at']),
        ]

    def __str__(self):
        return f"{self.sender.display_name}: {self.text[:50]}"

    def save(self, *args, **kwargs):
        """Update conversation's last message cache"""
        is_new = self.pk is None
        super().save(*args, **kwargs)

        if is_new:
            # Update conversation last message
            self.conversation.last_message_text = self.text
            self.conversation.last_message_at = self.created_at
            self.conversation.last_message_sender = self.sender
            self.conversation.save(update_fields=['last_message_text', 'last_message_at', 'last_message_sender'])

    def mark_as_read(self):
        """Mark message as read"""
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at'])


class MessageReadReceipt(models.Model):
    """Track when users read messages in conversations"""

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='read_receipts'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='message_read_receipts'
    )
    last_read_message = models.ForeignKey(
        Message,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+'
    )
    last_read_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'message_read_receipts'
        verbose_name = 'Message Read Receipt'
        verbose_name_plural = 'Message Read Receipts'
        unique_together = ['conversation', 'user']
        indexes = [
            models.Index(fields=['user', 'conversation']),
        ]

    def __str__(self):
        return f"{self.user.display_name} - {self.conversation}"
