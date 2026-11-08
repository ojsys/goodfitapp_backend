"""RSVP opens the ride chat; cancelling leaves it."""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.events.models import EventRSVP


@receiver(post_save, sender=EventRSVP)
def rsvp_saved(sender, instance, **kwargs):
    from .services import join_ride_chat, leave_ride_chat
    if instance.status == 'going':
        join_ride_chat(instance.event, instance.user)
    else:
        leave_ride_chat(instance.event, instance.user)


@receiver(post_delete, sender=EventRSVP)
def rsvp_deleted(sender, instance, **kwargs):
    from .services import leave_ride_chat
    leave_ride_chat(instance.event, instance.user)
