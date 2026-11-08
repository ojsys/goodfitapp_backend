"""
A Good Match: the opt-in dating space.

Only members with the Romantic intent see it or appear in it. One profile at
a time, a few a day. A like that's liked back locks the match: neither member
gets new matches until they meet up or one moves on. Moving on closes the
match chat and pauses new matches for the mover until 9:00 AM the next day
(their time); the other person gets a kind note with no details.

Nothing here needs a worker: the lock, the cooldown and the daily batch are
decided on each request.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

User = settings.AUTH_USER_MODEL

PROMPTS = [
    'My ideal Sunday',
    'Typical Saturday',
    'The way to win me over',
    'Looking for',
    'My go-to post-workout snack',
    'A route I could do with my eyes closed',
    'Green flag on a first date',
    'Best way to spend a rest day',
]
MAX_PROMPTS = 2


class MatchProfile(models.Model):
    """What a member shows (and wants) in A Good Match. Created on first visit."""

    GENDERS = [('woman', 'Woman'), ('man', 'Man'), ('nonbinary', 'Nonbinary')]
    SHOW_ME = ('women', 'men', 'everyone')

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='match_profile')
    gender = models.CharField(max_length=10, choices=GENDERS, blank=True)
    # Who to show: 'women', 'men' or 'everyone'.
    show_me = models.CharField(max_length=10, default='everyone')
    age_min = models.PositiveSmallIntegerField(default=21)
    age_max = models.PositiveSmallIntegerField(default=60)
    max_miles = models.PositiveSmallIntegerField(default=10)
    # [{"q": "My ideal Sunday", "a": "..."}], at most two.
    prompts = models.JSONField(default=list, blank=True)
    # "Easy, chatty" (the pace card adds the speed from their activities).
    pace_note = models.CharField(max_length=40, blank=True)
    # No new matches until then (moving on).
    cooldown_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'match_profiles'

    def __str__(self):
        return f'Match profile of {self.user}'

    @classmethod
    def of(cls, user):
        p, _ = cls.objects.get_or_create(user=user)
        return p

    def wants(self, gender):
        if self.show_me == 'everyone':
            return True
        return {'women': 'woman', 'men': 'man'}.get(self.show_me) == gender

    @property
    def cooling(self):
        return bool(self.cooldown_until and self.cooldown_until > timezone.now())


class Decision(models.Model):
    """Like or pass on someone's profile. A like may carry a reply to one of
    their prompts, which opens the match chat if it becomes a match."""

    ACTIONS = [('like', 'Like'), ('pass', 'Pass')]

    actor = models.ForeignKey(User, on_delete=models.CASCADE, related_name='match_decisions')
    target = models.ForeignKey(User, on_delete=models.CASCADE, related_name='match_decisions_received')
    action = models.CharField(max_length=4, choices=ACTIONS)
    prompt = models.CharField(max_length=80, blank=True)
    note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'match_decisions'
        constraints = [models.UniqueConstraint(fields=['actor', 'target'], name='match_decision_once')]
        indexes = [models.Index(fields=['actor', 'created_at']), models.Index(fields=['target', 'action'])]


class Match(models.Model):
    """Two members who liked each other. `a` is the lower user id.

    locked: matched, focused on each other.
    met:    one or both tapped "We met up". Each side then keeps seeing the
            other (still locked) or opens up to new matches (released).
    ended:  someone moved on (or blocked). The chat closes.
    """

    STATES = [('locked', 'Locked'), ('met', 'Met'), ('ended', 'Ended')]

    a = models.ForeignKey(User, on_delete=models.CASCADE, related_name='+')
    b = models.ForeignKey(User, on_delete=models.CASCADE, related_name='+')
    state = models.CharField(max_length=6, choices=STATES, default='locked')
    chat = models.OneToOneField('chats.Chat', on_delete=models.SET_NULL, null=True, blank=True,
                                related_name='match')
    locked_at = models.DateTimeField(default=timezone.now)
    # The first meetup one of them suggested (an event), shown on both sides.
    suggested_event = models.ForeignKey('events.Event', on_delete=models.SET_NULL, null=True, blank=True,
                                        related_name='+')
    suggested_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    met_at = models.DateTimeField(null=True, blank=True)
    # Per side: tapped "We met up", and chose "Open up to new matches".
    a_met = models.BooleanField(default=False)
    b_met = models.BooleanField(default=False)
    a_kept = models.BooleanField(default=False)
    b_kept = models.BooleanField(default=False)
    a_open = models.BooleanField(default=False)
    b_open = models.BooleanField(default=False)
    ended_at = models.DateTimeField(null=True, blank=True)
    ended_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        db_table = 'matches_v2'
        verbose_name_plural = 'matches'
        indexes = [models.Index(fields=['a', 'state']), models.Index(fields=['b', 'state'])]

    def __str__(self):
        return f'{self.a} + {self.b} ({self.state})'

    @staticmethod
    def involving(user):
        return Match.objects.filter(Q(a=user) | Q(b=user))

    def side(self, user):
        return 'a' if user.id == self.a_id else 'b'

    def other(self, user):
        return self.b if user.id == self.a_id else self.a

    def flag(self, user, name):
        return getattr(self, f'{self.side(user)}_{name}')

    def set_flag(self, user, name, value):
        setattr(self, f'{self.side(user)}_{name}', value)
        return f'{self.side(user)}_{name}'

    def holds(self, user):
        """Does this match keep `user` from new matches?"""
        return self.state in ('locked', 'met') and not self.flag(user, 'open')
