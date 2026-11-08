from django.urls import path

from . import profile, community_views as cv
from . import views

app_name = 'social'

urlpatterns = [
    path('home/', views.HomeView.as_view(), name='home'),
    path('feed/', views.FeedView.as_view(), name='feed'),
    path('checklist/', views.ChecklistView.as_view(), name='checklist'),
    path('posts/', views.PostCreateView.as_view(), name='post-create'),
    path('posts/<int:pk>/', views.PostDetailView.as_view(), name='post-detail'),
    path('<str:kind>/<int:pk>/props/', views.PropsView.as_view(), name='props'),
    path('<str:kind>/<int:pk>/comments/', views.CommentsView.as_view(), name='comments'),
    path('comments/<int:pk>/', views.CommentDeleteView.as_view(), name='comment-delete'),
    path('crew/', views.CrewView.as_view(), name='crew'),
    path('clubs/<int:pk>/join/', views.ClubJoinView.as_view(), name='club-join'),
    path('me/profile/', profile.MyProfileView.as_view(), name='my-profile'),
    path('people/<int:pk>/', profile.PersonView.as_view(), name='person'),
    path('people/<int:pk>/followers/', profile.FollowListView.as_view(which='followers'), name='followers'),
    path('people/<int:pk>/following/', profile.FollowListView.as_view(which='following'), name='following'),
    path('people/<int:pk>/follow/', views.FollowView.as_view(), name='follow'),
    path('people/<int:pk>/wave/', views.WaveView.as_view(), name='wave'),
    path('privacy-zones/', views.PrivacyZonesView.as_view(), name='privacy-zones'),
    path('privacy-zones/<int:pk>/', views.PrivacyZoneDeleteView.as_view(), name='privacy-zone-delete'),
    # Phase 3: Community.
    path('community/', cv.HubView.as_view(), name='hub'),
    path('clubs/<int:pk>/', cv.ClubView.as_view(), name='club'),
    path('clubs/<int:pk>/members/', cv.ClubMembersView.as_view(), name='club-members'),
    path('clubs/<int:pk>/leaderboard/', cv.ClubLeaderboardView.as_view(), name='club-leaderboard'),
    path('events/', cv.EventsBrowseView.as_view(), name='events'),
    path('events/host/', cv.HostEventView.as_view(), name='host-event'),
    path('buddies/', cv.BuddiesView.as_view(), name='buddies'),
    path('buddies/<int:pk>/hide/', cv.BuddyHideView.as_view(), name='buddy-hide'),
    path('buddies/<int:pk>/invite/', cv.BuddyInviteView.as_view(), name='buddy-invite'),
    path('me/location/', cv.LocationView.as_view(), name='location'),
]
