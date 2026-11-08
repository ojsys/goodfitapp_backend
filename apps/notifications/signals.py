"""What creates notifications. Kept here so the apps that cause them don't
need to know about notifications."""

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from apps.events.models import Event
from apps.social.models import Announcement, Comment, Follow, Prop, RideInvite, Wave

from .services import B, T, _name, notify, notify_grouped_props


def _thing(prop_or_comment):
    """(owner, label, link, key) for the post or activity it's on."""
    if prop_or_comment.post_id:
        p = prop_or_comment.post
        return p.author, 'post', '/home', f'post:{p.id}'
    a = prop_or_comment.activity
    return a.user, a.title or 'activity', f'/activity/{a.id}', f'activity:{a.id}'


@receiver(post_save, sender=Prop)
def on_prop(sender, instance, created, **kw):
    if not created:
        return
    owner, label, link, key = _thing(instance)
    notify_grouped_props(owner, instance.user, label, link, f'props:{key}')


@receiver(post_save, sender=Comment)
def on_comment(sender, instance, created, **kw):
    if not created:
        return
    owner, _, link, _ = _thing(instance)
    text = instance.text if len(instance.text) <= 90 else instance.text[:88].rstrip() + '…'
    notify(owner, 'comment', [B(_name(instance.author)), T(f' commented: “{text}”')], actor=instance.author,
           link=link)


@receiver(post_save, sender=Follow)
def on_follow(sender, instance, created, **kw):
    if created:
        notify(instance.followee, 'follow', [B(_name(instance.follower)), T(' started following you.')],
               actor=instance.follower, link=f'/people/{instance.follower_id}')


@receiver(post_save, sender=Wave)
def on_wave(sender, instance, created, **kw):
    if created:
        notify(instance.recipient, 'wave', [B(_name(instance.sender)), T(' waved at you. Say hi back?')],
               actor=instance.sender, link=f'/people/{instance.sender_id}')


@receiver(post_save, sender=RideInvite)
def on_invite(sender, instance, created, **kw):
    if not created:
        return
    from apps.users.age_gate import safe_zone
    e = instance.event
    day = e.start_time.astimezone(safe_zone(instance.recipient.timezone)).strftime('%A')
    notify(instance.recipient, 'ride_invite',
           [B(_name(instance.sender)), T(' invited you to the '), B(e.title), T(f' on {day}.')],
           actor=instance.sender, link=f'/events/{e.id}')


@receiver(post_save, sender=Announcement)
def on_announcement(sender, instance, created, **kw):
    if not created:
        return
    from apps.social.models import ClubMembership
    club = instance.club
    verb = ' pinned an announcement in ' if instance.pinned else ' posted an announcement in '
    for m in ClubMembership.objects.filter(club=club).select_related('user'):
        notify(m.user, 'announcement', [B(_name(instance.author) if instance.author else club.name), T(verb),
                                         B(club.name), T('.')], actor=instance.author, link=f'/clubs/{club.id}')


# ------------------------------------------------- ride changes and cancels

@receiver(pre_save, sender=Event)
def remember_event(sender, instance, **kw):
    if instance.pk:
        old = Event.objects.filter(pk=instance.pk).values('start_time', 'location_name', 'is_cancelled').first()
        instance._agf_old = old


@receiver(post_save, sender=Event)
def on_event_change(sender, instance, created, **kw):
    old = getattr(instance, '_agf_old', None)
    if created or not old:
        return
    from apps.users.age_gate import safe_zone
    changes = []
    if instance.is_cancelled and not old['is_cancelled']:
        changes.append('Cancelled. Sorry, see you at the next one.')
    else:
        if old['start_time'] != instance.start_time:
            changes.append('start')
        if old['location_name'] != instance.location_name:
            changes.append(f'Now meeting at {instance.location_name}.')
    if not changes:
        return
    for r in instance.rsvps.filter(status='going').select_related('user'):
        u = r.user
        if u.id == instance.host_id:
            continue
        lines = []
        for c in changes:
            if c == 'start':
                t = instance.start_time.astimezone(safe_zone(u.timezone))
                lines.append(f'Roll-out is now {t:%A} at {t:%-I:%M %p}.')
            else:
                lines.append(c)
        notify(u, 'ride_update', [B(instance.title), T(' · ' + ' '.join(lines))], link=f'/events/{instance.id}',
               push_title=instance.title)
