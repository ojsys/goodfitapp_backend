"""Move legacy 1:1 conversations into direct chats, and open ride chats for
existing RSVPs."""

from datetime import timedelta

from django.db import migrations


def forwards(apps, schema_editor):
    Conversation = apps.get_model('messaging', 'Conversation')
    Message = apps.get_model('messaging', 'Message')
    Chat = apps.get_model('chats', 'Chat')
    ChatMember = apps.get_model('chats', 'ChatMember')
    ChatMessage = apps.get_model('chats', 'ChatMessage')
    for c in Conversation.objects.all():
        lo, hi = sorted([c.participant1_id, c.participant2_id])
        chat, _ = Chat.objects.get_or_create(pair_key=f'{lo}:{hi}', defaults={'kind': 'direct'})
        last = None
        for m in Message.objects.filter(conversation=c).order_by('created_at'):
            last = ChatMessage.objects.create(chat=chat, sender_id=m.sender_id, body=m.text)
            ChatMessage.objects.filter(pk=last.pk).update(created_at=m.created_at)
        for uid in (lo, hi):
            ChatMember.objects.get_or_create(chat=chat, user_id=uid, defaults={'last_read_id': last.pk if last else 0})
        if last:
            Chat.objects.filter(pk=chat.pk).update(last_message_at=c.last_message_at or last.created_at)

    Event = apps.get_model('events', 'Event')
    EventRSVP = apps.get_model('events', 'EventRSVP')
    for e in Event.objects.filter(rsvps__status='going').distinct():
        end = e.end_time or (e.start_time + timedelta(minutes=e.duration_min or 180))
        chat, _ = Chat.objects.get_or_create(event=e, defaults={'kind': 'ride', 'closes_at': end + timedelta(hours=48)})
        for r in EventRSVP.objects.filter(event=e, status='going'):
            ChatMember.objects.get_or_create(chat=chat, user_id=r.user_id)


class Migration(migrations.Migration):
    dependencies = [
        ('chats', '0001_initial'),
        ('messaging', '0001_initial'),
        ('events', '0004_event_route_event_who_can_join'),
    ]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
