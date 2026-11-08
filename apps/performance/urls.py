from django.urls import path

from . import views

app_name = 'performance'

urlpatterns = [
    path('segments/nearby/', views.NearbyView.as_view(), name='nearby'),
    path('segments/<int:pk>/', views.SegmentView.as_view(), name='segment'),
    path('preview/', views.PreviewView.as_view(), name='preview'),
    path('challenges/', views.ChallengesView.as_view(), name='challenges'),
    path('challenges/<int:pk>/join/', views.JoinView.as_view(), name='join'),
    path('training/', views.TrainingView.as_view(), name='training'),
]
