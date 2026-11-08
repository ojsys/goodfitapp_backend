"""
Reports, blocks and moderation (requirements: Safety).

- Block: two-way. Neither person sees the other anywhere (feed, search,
  suggestions, leaderboards, club lists, rides, chats). See visibility.py.
- Report: any person, post, comment, activity or chat message. Unsafe
  reports go to the front of the queue, then under-21, then the rest,
  oldest first. The reporter follows it in Your reports.
- ModerationAction: what a moderator did, for the record and for repeat
  offenders.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

User = settings.AUTH_USER_MODEL


class Block(models.Model):
    """Two-way invisibility between two members."""

    blocker = models.ForeignKey(User, on_delete=models.CASCADE, related_name='blocks_made')
    blocked = models.ForeignKey(User, on_delete=models.CASCADE, related_name='blocks_received')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'blocks'
        constraints = [models.UniqueConstraint(fields=['blocker', 'blocked'], name='block_once')]

    def __str__(self):
        return f'{self.blocker} blocked {self.blocked}'

    @staticmethod
    def between_ids(user):
        """Ids of everyone `user` blocked or was blocked by."""
        rows = Block.objects.filter(Q(blocker=user) | Q(blocked=user)).values_list('blocker_id', 'blocked_id')
        return {b if a == user.id else a for a, b in rows}


# Reasons per kind of target (Core-Feed / Fit Buddies / chat report sheets).
REASONS = {
    'member': ['fake', 'under21', 'harassment', 'unsafe', 'other'],
    'post': ['spam', 'harassment', 'unsafe', 'inappropriate', 'other'],
    'activity': ['spam', 'harassment', 'unsafe', 'inappropriate', 'other'],
    'comment': ['spam', 'harassment', 'unsafe', 'inappropriate', 'other'],
    'message': ['spam', 'harassment', 'unsafe', 'inappropriate', 'other'],
}
REASON_LABELS = {
    'member': {'fake': 'Fake profile or impersonation', 'under21': 'Seems under 21',
               'harassment': 'Harassment or hate', 'unsafe': 'Unsafe or pressuring behavior',
               'other': 'Something else'},
    'message': {'spam': 'Spam or repeated messages', 'harassment': 'Harassment or hate',
                'unsafe': 'Unsafe or pressuring behavior', 'inappropriate': 'Inappropriate content',
                'other': 'Something else'},
    '*': {'spam': 'Spam or scam', 'harassment': 'Harassment or hate', 'unsafe': 'Unsafe or dangerous',
          'inappropriate': 'Inappropriate content', 'other': 'Something else'},
}


def reason_label(kind, reason):
    return REASON_LABELS.get(kind, REASON_LABELS['*']).get(reason) or REASON_LABELS['*'].get(reason, reason)


class Report(models.Model):
    TARGETS = [('member', 'Member'), ('post', 'Post'), ('comment', 'Comment'), ('activity', 'Activity'),
               ('message', 'Message')]
    STATUSES = [('open', 'Open'), ('resolved', 'Resolved')]
    OUTCOMES = [('', 'Not decided'), ('action_taken', 'Action taken'), ('no_violation', 'No violation')]
    # Queue order: lower first.
    PRIORITY_UNSAFE, PRIORITY_UNDER21, PRIORITY_NORMAL = 0, 1, 2
    PRIORITIES = [(0, 'Unsafe'), (1, 'Under 21'), (2, 'Standard')]

    reporter = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reports_made')
    target_kind = models.CharField(max_length=10, choices=TARGETS)
    target_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reports_about')
    target_id = models.PositiveBigIntegerField(null=True, blank=True)
    # Where it was reported ("Fit Buddies profile", "Message in Sunday Social Ride").
    context = models.CharField(max_length=120, blank=True)
    # Copy of what was reported (and, for a message, the lines before it),
    # kept even if the original is deleted later.
    snapshot = models.TextField(blank=True)
    reason = models.CharField(max_length=20)
    details = models.TextField(blank=True)
    priority = models.PositiveSmallIntegerField(choices=PRIORITIES, default=PRIORITY_NORMAL, db_index=True)
    status = models.CharField(max_length=10, choices=STATUSES, default='open', db_index=True)
    outcome = models.CharField(max_length=20, choices=OUTCOMES, blank=True)
    # What the reporter sees in Your reports once resolved.
    outcome_note = models.CharField(max_length=300, blank=True)
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'reports'
        ordering = ['-created_at']

    def __str__(self):
        return f'#{self.id} {self.get_target_kind_display()} · {self.reason}'

    @property
    def urgent(self):
        return self.priority == self.PRIORITY_UNSAFE

    @property
    def reason_label(self):
        return reason_label(self.target_kind, self.reason)

    @staticmethod
    def priority_for(reason):
        if reason == 'unsafe':
            return Report.PRIORITY_UNSAFE
        if reason == 'under21':
            return Report.PRIORITY_UNDER21
        return Report.PRIORITY_NORMAL

    def resolve(self, outcome, note, reviewer):
        self.status, self.outcome, self.outcome_note = 'resolved', outcome, note[:300]
        self.reviewed_by, self.resolved_at = reviewer, timezone.now()
        self.save(update_fields=['status', 'outcome', 'outcome_note', 'reviewed_by', 'resolved_at'])


class ModerationAction(models.Model):
    """A moderator's decision about a member."""

    KINDS = [('removed_content', 'Removed content'), ('warned', 'Warned'),
             ('suspended', 'Suspended'), ('age_check', 'Suspended for age check'), ('banned', 'Banned'),
             ('reinstated', 'Reinstated')]

    member = models.ForeignKey(User, on_delete=models.CASCADE, related_name='moderation_actions')
    kind = models.CharField(max_length=20, choices=KINDS)
    report = models.ForeignKey(Report, on_delete=models.SET_NULL, null=True, blank=True, related_name='actions')
    note = models.CharField(max_length=300, blank=True)
    by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'moderation_actions'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_kind_display()}: {self.member}'


class SupportMessage(models.Model):
    """"Contact the Good Co. team" on the Community Guidelines page."""

    TOPICS = [('question', 'Ask a question'), ('safety', 'Report a safety concern'), ('feedback', 'Share feedback')]
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='support_messages')
    topic = models.CharField(max_length=10, choices=TOPICS)
    text = models.TextField(max_length=2000)
    handled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'support_messages'
        ordering = ['handled', '-created_at']

    def __str__(self):
        return f'{self.get_topic_display()}: {self.text[:60]}'
