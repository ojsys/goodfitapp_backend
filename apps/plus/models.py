"""A Good Fit Plus subscriptions (App Store, Google Play, or given by the team)."""

from django.conf import settings
from django.db import models
from django.utils import timezone


class Subscription(models.Model):
    STORES = [('apple', 'App Store'), ('google', 'Google Play'), ('comp', 'Given by the team'),
              ('test', 'Test purchase')]
    PRODUCTS = [('monthly', 'Monthly'), ('yearly', 'Yearly'), ('comp', 'Complimentary')]
    STATUSES = [
        ('trial', 'Free trial'),
        ('active', 'Active'),
        ('grace', 'Grace period (payment failing, still Plus)'),
        ('on_hold', 'On hold (payment failed)'),
        ('pending', 'Pending payment'),
        ('expired', 'Expired'),
        ('refunded', 'Refunded or revoked'),
        ('replaced', 'Replaced by a newer purchase'),
    ]
    # These keep Plus until access_until.
    GRANTS = ('trial', 'active', 'grace')

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='subscriptions')
    store = models.CharField(max_length=10, choices=STORES)
    product = models.CharField(max_length=10, choices=PRODUCTS, default='monthly')
    store_product_id = models.CharField(max_length=120, blank=True)
    # App Store originalTransactionId, Play purchase token, or our own id.
    original_id = models.CharField(max_length=400, blank=True)
    status = models.CharField(max_length=10, choices=STATUSES, default='active')
    started_at = models.DateTimeField(default=timezone.now)
    # When the current paid (or trial) period ends: "renews at".
    expires_at = models.DateTimeField(null=True, blank=True, help_text='Blank: no end (team-given Plus)')
    # Plus lasts until here (the end of a grace period, else expires_at).
    access_until = models.DateTimeField(null=True, blank=True)
    will_renew = models.BooleanField(default=True)
    environment = models.CharField(max_length=20, blank=True, help_text='Production or Sandbox')
    note = models.CharField(max_length=200, blank=True)
    # Store events can arrive out of order; ignore anything older.
    last_event_at = models.DateTimeField(null=True, blank=True)
    last_event = models.CharField(max_length=60, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        constraints = [
            models.UniqueConstraint(fields=['store', 'original_id'], condition=~models.Q(original_id=''),
                                    name='plus_unique_store_purchase'),
        ]

    def __str__(self):
        return f'{self.user} · {self.get_store_display()} · {self.status}'

    @property
    def grants(self):
        if self.status not in self.GRANTS:
            return False
        end = self.access_until or self.expires_at
        return end is None or end > timezone.now()

    def save(self, *args, **kwargs):
        if self.store == 'comp':
            self.product = 'comp'
            self.will_renew = False
            if self.status not in ('active', 'expired', 'refunded'):
                self.status = 'active'
        if self.status != 'grace':
            self.access_until = self.expires_at
        super().save(*args, **kwargs)
