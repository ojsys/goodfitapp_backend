from django.urls import path

from . import views

app_name = 'safety'

urlpatterns = [
    path('reports/', views.ReportView.as_view(), name='reports'),
    path('blocks/', views.BlockListView.as_view(), name='blocks'),
    path('blocks/<int:pk>/', views.BlockView.as_view(), name='block'),
    path('hide/<str:kind>/<int:pk>/', views.HideView.as_view(), name='hide'),
]
