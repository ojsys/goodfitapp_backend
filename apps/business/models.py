"""Business accounts, the people who can act for them, featured placements
and what members did with them (counts only)."""

from django.conf import settings
from django.db import models
from django.utils import timezone

User = settings.AUTH_USER_MODEL


class BusinessAccount(models.Model):
    CATEGORIES = [
        ('yoga', 'Yoga or Pilates studio'), ('gym', 'Gym or fitness studio'), ('shop', 'Run or bike shop'),
        ('cafe', 'Cafe or healthy food'), ('wellness', 'Wellness services'), ('other', 'Other'),
    ]
    STATUSES = [('pending', 'Waiting for verification'), ('verified', 'Verified'), ('rejected', 'Not approved')]
    PLANS = [('none', 'No plan'), ('partner', 'Partner')]
    PLAN_STATUSES = [('', '—'), ('active', 'Active'), ('past_due', 'Payment failed'), ('canceled', 'Canceled')]

    name = models.CharField(max_length=120)
    category = models.CharField(max_length=10, choices=CATEGORIES, default='other')
    address = models.CharField(max_length=200, blank=True)
    website = models.CharField(max_length=200, blank=True, help_text='Website or Instagram')
    work_email = models.EmailField(blank=True)
    status = models.CharField(max_length=10, choices=STATUSES, default='pending')
    verified_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=300, blank=True, help_text='Shown to the business if not approved')
    # GoodCo, the parent company: Partner capabilities, no billing, free featured events.
    is_house = models.BooleanField(default=False)
    plan = models.CharField(max_length=10, choices=PLANS, default='none')
    plan_status = models.CharField(max_length=10, choices=PLAN_STATUSES, blank=True)
    plan_renews_at = models.DateTimeField(null=True, blank=True)
    # Partners can start and run a club.
    club = models.OneToOneField('social.Club', on_delete=models.SET_NULL, null=True, blank=True,
                                related_name='business')
    agreed_at = models.DateTimeField(null=True, blank=True, help_text='Community Guidelines and Featured Events Policy')
    stripe_customer_id = models.CharField(max_length=80, blank=True)
    stripe_payment_method = models.CharField(max_length=80, blank=True)
    stripe_subscription_id = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def verified(self):
        return self.status == 'verified' or self.is_house

    @property
    def partner(self):
        return self.is_house or (self.plan == 'partner' and self.plan_status in ('active', 'past_due'))

    @property
    def initials(self):
        if self.club_id and self.club.initials:
            return self.club.initials
        words = [w for w in self.name.replace('&', ' ').split() if w[:1].isalnum()]
        return (words[0][0] if words else '?').upper()


class BusinessMember(models.Model):
    """Someone who can sign in to the portal for this account. Club teams
    also get in through their club role (social.ClubMembership)."""
    ROLES = [('owner', 'Owner'), ('admin', 'Admin'), ('organizer', 'Organizer'), ('ride_leader', 'Ride leader')]
    account = models.ForeignKey(BusinessAccount, on_delete=models.CASCADE, related_name='members')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='business_memberships')
    role = models.CharField(max_length=12, choices=ROLES, default='owner')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['account', 'user'], name='business_member_once')]


class BusinessLog(models.Model):
    """Portal actions for accounts without a club (club accounts use the
    club's team log)."""
    account = models.ForeignKey(BusinessAccount, on_delete=models.CASCADE, related_name='log')
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='+')
    action = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class TeamInvite(models.Model):
    """Invites go to the member in the app and must be accepted."""
    STATUSES = [('pending', 'Pending'), ('accepted', 'Accepted'), ('declined', 'Declined'), ('cancelled', 'Cancelled')]
    club = models.ForeignKey('social.Club', on_delete=models.CASCADE, related_name='team_invites')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='team_invites')
    role = models.CharField(max_length=12, choices=BusinessMember.ROLES[1:], default='ride_leader')
    invited_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='+')
    status = models.CharField(max_length=10, choices=STATUSES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    answered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']


class FeaturedPlacement(models.Model):
    # price (cents), days on the app, where it shows.
    PACKAGES = {
        'spotlight': {'name': 'Spotlight', 'price': 4900, 'days': 3, 'where': ['events'],
                      'line': '3 days on Events', 'detail': 'Top slot on the Events tab'},
        'boost': {'name': 'Boost', 'price': 12900, 'days': 7, 'where': ['events', 'home'],
                  'line': '7 days on Events and Home', 'detail': 'Events plus a card in Home feeds'},
        'partner': {'name': 'Partner', 'price': 29900, 'days': 7, 'where': ['events', 'home', 'hub'],
                    'line': 'Up to 4 events a month',
                    'detail': 'Events, Home and the Community hub, start and run a club, plus a monthly report'},
    }
    PARTNER_EVENTS_A_MONTH = 4
    STATUSES = [('draft', 'Draft'), ('in_review', 'In review'), ('approved', 'Approved'),
                ('rejected', 'Not approved'), ('cancelled', 'Cancelled')]
    PAYMENTS = [('', 'Not charged yet'), ('charged', 'Charged'), ('house', 'House account (free)'),
                ('included', 'Included in Partner'), ('not_billed', 'Approved without billing (Stripe off)'),
                ('failed', 'Charge failed')]

    account = models.ForeignKey(BusinessAccount, on_delete=models.CASCADE, related_name='placements')
    event = models.OneToOneField('events.Event', on_delete=models.CASCADE, related_name='placement')
    package = models.CharField(max_length=10, choices=[(k, v['name']) for k, v in PACKAGES.items()],
                               default='spotlight')
    # Targeting: neighborhoods and declared interests only. Never dating
    # status, age or health data.
    neighborhoods = models.JSONField(default=list, blank=True)
    interests = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=10, choices=STATUSES, default='draft')
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    price_cents = models.PositiveIntegerField(default=0)
    payment = models.CharField(max_length=10, choices=PAYMENTS, blank=True)
    stripe_payment_intent = models.CharField(max_length=80, blank=True)
    review_note = models.CharField(max_length=300, blank=True, help_text='Shown to the business if not approved')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='+')
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.event.title} ({self.get_package_display()}, {self.shown_status})'

    @property
    def spec(self):
        return self.PACKAGES[self.package]

    @property
    def shown_status(self):
        """Draft, In review, Scheduled, Live, Ended, Not approved, Cancelled."""
        if self.status != 'approved':
            return self.status
        now = timezone.now()
        if self.ends_at and now >= self.ends_at:
            return 'ended'
        if self.starts_at and now < self.starts_at:
            return 'scheduled'
        return 'live'


class FeaturedImpression(models.Model):
    """One row per member per day a placement was on screen: views are
    member-days, a tap marks the row. Only counts ever leave the server."""
    placement = models.ForeignKey(FeaturedPlacement, on_delete=models.CASCADE, related_name='impressions')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='+')
    day = models.DateField()
    surface = models.CharField(max_length=8, default='events')
    tapped = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['placement', 'user', 'day'], name='impression_once_a_day')]
        indexes = [models.Index(fields=['placement', 'day'])]


class NameFlag(models.Model):
    """A community ride that uses a club's name without being run by it."""
    STATUSES = [('open', 'Open'), ('asked', 'Asked to rename'), ('allowed', 'Allowed')]
    club = models.ForeignKey('social.Club', on_delete=models.CASCADE, related_name='name_flags')
    event = models.ForeignKey('events.Event', on_delete=models.CASCADE, related_name='name_flags')
    status = models.CharField(max_length=8, choices=STATUSES, default='open')
    decided_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['club', 'event'], name='name_flag_once')]
