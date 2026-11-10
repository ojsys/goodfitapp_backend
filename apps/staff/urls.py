from django.urls import path

from . import views as v

urlpatterns = [
    path('session/', v.SessionView.as_view()),
    path('login/', v.LoginView.as_view()),
    path('logout/', v.LogoutView.as_view()),
    path('overview/', v.OverviewView.as_view()),
    path('log/', v.LogView.as_view()),
    path('models/', v.ModelsView.as_view()),
    path('models/<str:label>/', v.ModelListView.as_view()),
    path('models/<str:label>/options/', v.OptionsView.as_view()),
    path('models/<str:label>/<str:pk>/', v.ModelDetailView.as_view()),
    path('members/<int:pk>/<str:action>/', v.MemberActionView.as_view()),
    path('reports/', v.ReportsView.as_view()),
    path('reports/<int:pk>/decide/', v.ReportDecideView.as_view()),
    path('featured/', v.PlacementsView.as_view()),
    path('featured/<int:pk>/<str:action>/', v.PlacementActView.as_view()),
    path('businesses/', v.BusinessesView.as_view()),
    path('businesses/<int:pk>/<str:action>/', v.BusinessActView.as_view()),
    path('support/', v.SupportView.as_view()),
    path('support/<int:pk>/', v.SupportActView.as_view()),
    path('team/', v.TeamView.as_view()),
    path('team/<int:pk>/', v.TeamMemberView.as_view()),
]
