from django.urls import path

from . import views

urlpatterns = [
    path('', views.PlusView.as_view()),
    path('verify/', views.VerifyView.as_view()),
    path('restore/', views.RestoreView.as_view()),
    path('webhooks/apple/', views.AppleWebhookView.as_view()),
    path('webhooks/google/', views.GoogleWebhookView.as_view()),
]
