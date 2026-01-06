"""
Messaging URLs for GoodFit API
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from apps.messaging.views import ConversationViewSet, MessageViewSet

router = DefaultRouter()
router.register(r'conversations', ConversationViewSet, basename='conversation')
router.register(r'messages', MessageViewSet, basename='message')

urlpatterns = [
    path('', include(router.urls)),
]
