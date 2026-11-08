"""
URL Configuration for GoodFit API
"""

from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView, TemplateView

from apps.business import policies
from apps.business.portal import index as portal_index
from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi

from apps.social import share

from . import api_docs
from .views import api_root, health

# API Documentation Schema (groups, request bodies and auth: api_docs.py)
schema_view = get_schema_view(
    api_docs.INFO,
    public=True,
    permission_classes=(permissions.AllowAny,),
)

urlpatterns = [
    # Landing Page
    path('', TemplateView.as_view(template_name='landing.html'), name='landing'),
    re_path(r'^business(?:/.*)?$', portal_index, name='business-portal'),
    path('community-guidelines/', policies.guidelines, name='community-guidelines'),
    path('featured-events-policy/', policies.featured_policy, name='featured-policy'),

    # Admin
    path('admin/', admin.site.urls),
    # Password reset link from the email (Phase 1).
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='auth/reset_confirm.html', success_url='/reset/done/'), name='password_reset_confirm'),
    path('reset/done/', TemplateView.as_view(template_name='auth/reset_done.html'), name='password_reset_done'),

    # API Documentation
    path('docs/', schema_view.with_ui('swagger', cache_timeout=300), name='schema-swagger-ui'),
    path('redoc/', schema_view.with_ui('redoc', cache_timeout=300), name='schema-redoc'),
    re_path(r'^openapi(?P<format>\.json|\.yaml)$', schema_view.without_ui(cache_timeout=300), name='schema-json'),
    path('swagger/', RedirectView.as_view(url='/docs/', permanent=True)),

    # API Endpoints
    # /api/ has no resource of its own. Return a JSON index rather than a bare
    # 404, so the path reports status and links on to the docs.
    path('api/', api_root, name='api-root'),
    path('api/health/', health, name='health'),
    path('api/auth/', include('apps.users.urls')),
    path('api/activities/', include('apps.activities.urls')),
    path('api/events/', include('apps.events.urls')),
    path('api/matching/', include('apps.matching.urls')),
    path('api/messaging/', include('apps.messaging.urls')),
    path('api/social/', include('apps.social.urls')),
    path('api/routes/', include('apps.routes.urls')),
    path('api/chats/', include('apps.chats.urls')),
    path('api/safety/', include('apps.safety.urls')),
    path('api/notifications/', include('apps.notifications.urls')),
    path('api/performance/', include('apps.performance.urls')),
    path('api/match/', include('apps.goodmatch.urls')),
    path('api/plus/', include('apps.plus.urls')),
    path('api/business/', include('apps.business.urls')),
    # Share sheet (Phase 6) and the public pages its links open.
    path('api/share/recipients/', share.RecipientsView.as_view(), name='share-recipients'),
    path('api/share/send/', share.SendView.as_view(), name='share-send'),
    path('api/share/<str:kind>/<int:pk>/', share.ShareCardView.as_view(), name='share-card'),
    path('u/<int:pk>', share.public_profile, name='public-profile'),
    path('c/<int:pk>', share.public_club, name='public-club'),
    path('join/<str:code>', share.public_invite, name='public-invite'),
    path('e/<int:pk>', share.public_event, name='public-event'),
    path('a/<int:pk>', share.public_activity, name='public-activity'),
    path('r/<int:pk>', share.public_route, name='public-route'),
    path('s/<int:pk>', share.public_segment, name='public-segment'),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
