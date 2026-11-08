"""Day-before ride reminders. Run hourly (the server's cron does):

    python manage.py send_reminders

"Halloween Glow Walk is Saturday at 6:00 PM. 31 people are going."
Each member gets one reminder per ride, however often this runs.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.events.models import Event
from apps.notifications.models import Notification
from apps.notifications.services import B, T, notify
from apps.users.age_gate import safe_zone


class Command(BaseCommand):
    help = 'Send day-before reminders for rides people are going to.'

    def handle(self, *args, **opts):
        now = timezone.now()
        sent = 0
        soon = Event.objects.filter(is_cancelled=False, is_active=True, start_time__gte=now + timedelta(hours=20),
                                    start_time__lt=now + timedelta(hours=28))
        for e in soon:
            going = list(e.rsvps.filter(status='going').select_related('user'))
            for r in going:
                key = f'reminder:{e.id}'
                if Notification.objects.filter(recipient=r.user, group_key=key).exists():
                    continue
                t = e.start_time.astimezone(safe_zone(r.user.timezone))
                others = len(going) - 1
                tail = f' {len(going)} people are going.' if others > 0 else ''
                if notify(r.user, 'ride_reminder', [B(e.title), T(f' is {t:%A} at {t:%-I:%M %p}.{tail}')],
                          link=f'/events/{e.id}', group_key=key, push_title='Tomorrow'):
                    sent += 1
        self.stdout.write(f'{sent} reminder(s) sent')
