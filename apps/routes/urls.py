from django.urls import path

from . import views

app_name = 'routes'

urlpatterns = [
    path('', views.RoutesView.as_view(), name='routes'),
    path('snap/', views.SnapView.as_view(), name='snap'),
    path('<int:pk>/', views.RouteDetailView.as_view(), name='route'),
    path('<int:pk>/save/', views.RouteSaveView.as_view(), name='save'),
]
