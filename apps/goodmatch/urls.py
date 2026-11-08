from django.urls import path

from . import views

app_name = 'goodmatch'

urlpatterns = [
    path('', views.StateView.as_view(), name='state'),
    path('decide/', views.DecideView.as_view(), name='decide'),
    path('profile/', views.ProfileView.as_view(), name='profile'),
    path('<int:pk>/suggest/', views.SuggestView.as_view(), name='suggest'),
    path('<int:pk>/met/', views.MetView.as_view(), name='met'),
    path('<int:pk>/keep/', views.KeepView.as_view(), name='keep'),
    path('<int:pk>/open/', views.OpenView.as_view(), name='open'),
    path('<int:pk>/move-on/', views.MoveOnView.as_view(), name='move-on'),
]
