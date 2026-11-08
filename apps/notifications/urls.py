from django.urls import path

from . import views

app_name = 'notifications'

urlpatterns = [
    path('', views.NotificationsView.as_view(), name='list'),
    path('unread/', views.UnreadView.as_view(), name='unread'),
    path('read-all/', views.ReadAllView.as_view(), name='read-all'),
    path('<int:pk>/read/', views.ReadOneView.as_view(), name='read'),
    path('settings/', views.SettingsView.as_view(), name='settings'),
    path('devices/', views.DevicesView.as_view(), name='devices'),
]
