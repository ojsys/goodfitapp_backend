from django.contrib import admin

from .models import Chat, ChatMember, ChatMessage


@admin.register(Chat)
class ChatAdmin(admin.ModelAdmin):
    list_display = ['id', 'kind', 'event', 'closes_at', 'last_message_at']
    list_filter = ['kind']


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ['id', 'chat', 'sender', 'body', 'attachment', 'created_at', 'removed_at']
    raw_id_fields = ['sender', 'chat']


admin.site.register(ChatMember)
