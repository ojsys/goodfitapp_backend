from django.apps import AppConfig


class ChatsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.chats'
    label = 'chats'

    def ready(self):
        from . import signals  # noqa: F401
