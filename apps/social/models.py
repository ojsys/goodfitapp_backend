"""
Home feed and the social graph: follows, clubs, posts, props, comments,
privacy zones. Phase 2 of BUILD_PLAN.md. Clubs are the minimum the feed and
the new-member Home need; team roles, announcements and goals come in Phase 3.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

User = settings.AUTH_USER_MODEL


class Follow(models.Model):
    follower = models.ForeignKey(User, on_delete=models.CASCADE, related_name='following_set')
    followee = models.ForeignKey(User, on_delete=models.CASCADE, related_name='follower_set')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'follows'
        constraints = [
            models.UniqueConstraint(fields=['follower', 'followee'], name='follow_unique'),
            models.CheckConstraint(condition=~Q(follower=models.F('followee')), name='follow_not_self'),
        ]


class Club(models.Model):
    name = models.CharField(max_length=120)
    initials = models.CharField(max_length=3)
    # Tile color on cards ("GC" on #5E7233). One of the avatar palette.
    color = models.CharField(max_length=7, default='#5E7233')
    neighborhood = models.CharField(max_length=80, blank=True)
    # Club page header: "Brooklyn, NY · 1,248 members · Founded 2021".
    location = models.CharField(max_length=80, blank=True)
    founded_year = models.PositiveSmallIntegerField(null=True, blank=True)
    banner = models.ImageField(upload_to='club_banners/', blank=True, null=True)
    # Second line on cards, e.g. "Rides every weekend".
    tagline = models.CharField(max_length=80, blank=True)
    # Onboarding interest keys this club is about (users.models.INTERESTS).
    interests = models.JSONField(default=list, blank=True)
    # Only verified partner businesses run clubs (requirements: Plans).
    is_house = models.BooleanField(default=False, help_text='GoodCo house club')
    owner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='owned_clubs')
    # Role -> permissions, overriding the defaults (ClubMembership.DEFAULT_PERMISSIONS).
    # Owners always have every permission.
    permissions = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'clubs'
        ordering = ['name']

    def __str__(self):
        return self.name


class ClubMembership(models.Model):
    ROLES = [
        ('member', 'Member'),
        ('ride_leader', 'Ride leader'),
        ('organizer', 'Organizer'),
        ('admin', 'Admin'),
        ('owner', 'Owner'),
    ]
    TEAM_ROLES = ('owner', 'admin', 'organizer', 'ride_leader')
    PERMISSIONS = (
        'create_events', 'approve_suggestions', 'run_rides', 'post_announcements', 'moderate',
        'edit_club', 'feature_events', 'see_event_data', 'manage_team', 'manage_billing',
    )
    # The grid in the requirements (Club team roles). Owners have everything.
    DEFAULT_PERMISSIONS = {
        'admin': ['create_events', 'approve_suggestions', 'run_rides', 'post_announcements', 'moderate',
                  'edit_club', 'feature_events', 'see_event_data', 'manage_team'],
        'organizer': ['create_events', 'approve_suggestions', 'run_rides', 'post_announcements', 'moderate',
                      'see_event_data'],
        'ride_leader': ['run_rides'],
        'member': [],
    }

    club = models.ForeignKey(Club, on_delete=models.CASCADE, related_name='memberships')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='club_memberships')
    role = models.CharField(max_length=20, choices=ROLES, default='member')
    # Shown on the Club Team card: "Co-founder · Owner".
    title = models.CharField(max_length=40, blank=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'club_memberships'
        constraints = [models.UniqueConstraint(fields=['club', 'user'], name='club_member_unique')]

    def can(self, permission):
        if self.role == 'owner':
            return True
        grid = self.club.permissions.get(self.role) if self.club.permissions else None
        return permission in (grid if grid is not None else self.DEFAULT_PERMISSIONS.get(self.role, []))

    @property
    def role_label(self):
        return dict(self.ROLES)[self.role]


class ClubTeamLog(models.Model):
    """Every team action: who, what, when (requirements: Club team roles)."""

    club = models.ForeignKey(Club, on_delete=models.CASCADE, related_name='team_log')
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='+')
    action = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'club_team_log'
        ordering = ['-created_at']


class ClubGoal(models.Model):
    """"Ride 10,000 miles together" for a month. Progress is the members'
    activity distance in the window."""

    club = models.ForeignKey(Club, on_delete=models.CASCADE, related_name='goals')
    title = models.CharField(max_length=80)
    target_m = models.FloatField()
    # Which activity kinds count; empty = all with a distance.
    kinds = models.JSONField(default=list, blank=True)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()

    class Meta:
        db_table = 'club_goals'
        ordering = ['-starts_at']


class Announcement(models.Model):
    club = models.ForeignKey(Club, on_delete=models.CASCADE, related_name='announcements')
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='+')
    text = models.TextField(max_length=1000)
    pinned = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'club_announcements'
        ordering = ['-pinned', '-created_at']


class RideSuggestion(models.Model):
    """Host an event > Suggest to a club. The club team approves it in the
    portal (Phase 10) or the admin; approved becomes a club event with the
    member as ride leader."""

    STATUSES = [('new', 'New'), ('approved', 'Approved'), ('declined', 'Declined')]
    member = models.ForeignKey(User, on_delete=models.CASCADE, related_name='ride_suggestions')
    club = models.ForeignKey(Club, on_delete=models.CASCADE, related_name='suggestions')
    # The proposed event fields, as sent by Host an event.
    proposal = models.JSONField()
    note = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=STATUSES, default='new')
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    event = models.OneToOneField('events.Event', on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='suggestion')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'ride_suggestions'
        ordering = ['-created_at']


class RideInvite(models.Model):
    """Fit Buddies > Invite to a ride. Delivered as a notification in Phase 6."""

    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='ride_invites_sent')
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='ride_invites')
    event = models.ForeignKey('events.Event', on_delete=models.CASCADE, related_name='invites')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'ride_invites'
        constraints = [models.UniqueConstraint(fields=['sender', 'recipient', 'event'], name='ride_invite_once')]


class Hide(models.Model):
    """A member hides someone from suggestions (not interested), or hides a
    post or activity from their feed (also while a report is reviewed).
    Blocking is safety.Block."""

    KINDS = [('not_interested', 'Not interested'), ('hidden_post', 'Hidden post'),
             ('hidden_activity', 'Hidden activity')]
    member = models.ForeignKey(User, on_delete=models.CASCADE, related_name='hides')
    kind = models.CharField(max_length=20, choices=KINDS)
    target_user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='+')
    target_post = models.ForeignKey('Post', on_delete=models.CASCADE, null=True, blank=True, related_name='+')
    target_activity = models.ForeignKey('activities.Activity', on_delete=models.CASCADE, null=True, blank=True,
                                        related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'hides'
        indexes = [models.Index(fields=['member', 'kind'])]


class Post(models.Model):
    """Composer posts (Core-Feed composer sheet)."""

    TYPES = [('moment', 'Moment'), ('checkin', 'Check-in'), ('shoutout', 'Shoutout')]
    MOODS = [
        ('recharged', 'Recharged'),
        ('steady', 'Steady'),
        ('tired', 'Tired'),
        ('sore', 'Sore'),
        ('stressed', 'Stressed'),
    ]
    AUDIENCES = [('followers', 'Followers'), ('club', 'Club'), ('me', 'Only me')]
    MAX_TEXT = 1000

    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='posts')
    type = models.CharField(max_length=10, choices=TYPES, default='moment')
    text = models.TextField(max_length=MAX_TEXT, blank=True)
    mood = models.CharField(max_length=10, choices=MOODS, blank=True)
    photo = models.ImageField(upload_to='post_photos/', blank=True, null=True)
    tagged = models.ManyToManyField(User, blank=True, related_name='tagged_in_posts')
    audience = models.CharField(max_length=10, choices=AUDIENCES, default='followers')
    club = models.ForeignKey(Club, on_delete=models.CASCADE, null=True, blank=True, related_name='posts')
    # The new-member "Introduce yourself" post (Core-FeedNew).
    is_intro = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'posts'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['author', '-created_at'])]

    def clean(self):
        if self.audience == 'club' and not self.club_id:
            raise ValidationError({'club': 'Pick a club for a club post.'})


class Prop(models.Model):
    """Props (kudos) on a post or an activity."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='props_given')
    post = models.ForeignKey(Post, on_delete=models.CASCADE, null=True, blank=True, related_name='props')
    activity = models.ForeignKey('activities.Activity', on_delete=models.CASCADE, null=True, blank=True,
                                 related_name='props')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'props'
        constraints = [
            models.UniqueConstraint(fields=['user', 'post'], condition=Q(post__isnull=False), name='prop_post_once'),
            models.UniqueConstraint(fields=['user', 'activity'], condition=Q(activity__isnull=False),
                                    name='prop_activity_once'),
            models.CheckConstraint(
                condition=(Q(post__isnull=False) & Q(activity__isnull=True))
                | (Q(post__isnull=True) & Q(activity__isnull=False)),
                name='prop_one_target',
            ),
        ]


class Comment(models.Model):
    MAX_TEXT = 500

    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='comments')
    post = models.ForeignKey(Post, on_delete=models.CASCADE, null=True, blank=True, related_name='comments')
    activity = models.ForeignKey('activities.Activity', on_delete=models.CASCADE, null=True, blank=True,
                                 related_name='comments')
    text = models.TextField(max_length=MAX_TEXT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'comments'
        ordering = ['created_at']
        constraints = [
            models.CheckConstraint(
                condition=(Q(post__isnull=False) & Q(activity__isnull=True))
                | (Q(post__isnull=True) & Q(activity__isnull=False)),
                name='comment_one_target',
            ),
        ]


class Wave(models.Model):
    """"Say hi" on suggested people and new club members. Becomes a
    notification in Phase 6."""

    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='waves_sent')
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='waves_received')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'waves'
        constraints = [models.UniqueConstraint(fields=['sender', 'recipient'], name='wave_once')]


class PrivacyZone(models.Model):
    """A saved place (home, work). Any track that starts or ends inside one
    is trimmed on the server before anyone else sees it."""

    LABELS = [('home', 'Home'), ('work', 'Work'), ('other', 'Other')]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='privacy_zones')
    label = models.CharField(max_length=10, choices=LABELS, default='home')
    latitude = models.FloatField()
    longitude = models.FloatField()
    radius_m = models.PositiveIntegerField(default=400)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'privacy_zones'
