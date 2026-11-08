from django.urls import path

from . import views as v

A = 'a/<int:acct>/'
urlpatterns = [
    path('session/', v.SessionView.as_view()),
    path('login/', v.LoginView.as_view()),
    path('logout/', v.LogoutView.as_view()),
    path('signup/', v.SignupView.as_view()),
    path(A + 'overview/', v.OverviewView.as_view()),
    path(A + 'options/', v.OptionsView.as_view()),
    path(A + 'reach/', v.ReachView.as_view()),
    path(A + 'featured/', v.FeaturedListView.as_view()),
    path(A + 'featured/<int:pk>/', v.FeaturedView.as_view()),
    path(A + 'featured/<int:pk>/submit/', v.SubmitView.as_view()),
    path(A + 'featured/<int:pk>/results/', v.ResultsView.as_view()),
    path(A + 'suggestions/', v.SuggestionsView.as_view()),
    path(A + 'suggestions/<int:pk>/<str:action>/', v.SuggestionActionView.as_view()),
    path(A + 'flags/<int:pk>/<str:action>/', v.FlagActionView.as_view()),
    path(A + 'team/', v.TeamView.as_view()),
    path(A + 'team/invite/', v.InviteView.as_view()),
    path(A + 'team/grid/', v.GridView.as_view()),
    path(A + 'team/<int:uid>/', v.TeamMemberView.as_view()),
    path(A + 'billing/', v.BillingView.as_view()),
    path(A + 'billing/<str:kind>/', v.BillingView.as_view()),
    path(A + 'settings/', v.SettingsView.as_view()),
    path('stripe/webhook/', v.StripeWebhookView.as_view()),
    path('featured/<int:pk>/seen/', v.SeenView.as_view()),
    path('featured/<int:pk>/tap/', v.TapView.as_view()),
    path('invites/<int:pk>/<str:action>/', v.InviteAnswerView.as_view()),
]
