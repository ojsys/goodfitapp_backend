from django.urls import path

from . import views

app_name = 'chats'

urlpatterns = [
    path('', views.InboxView.as_view(), name='inbox'),
    path('unread/', views.UnreadView.as_view(), name='unread'),
    path('direct/', views.DirectView.as_view(), name='direct'),
    path('messages/<int:pk>/', views.MessageView.as_view(), name='message'),
    path('messages/<int:pk>/location/', views.LiveLocationView.as_view(), name='live-location'),
    path('<int:pk>/', views.ChatView.as_view(), name='chat'),
    path('<int:pk>/messages/', views.MessagesView.as_view(), name='messages'),
    path('<int:pk>/read/', views.ReadView.as_view(), name='read'),
]
