"""
URL Configuration for GoodFit API
"""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView
from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi

# API Documentation Schema
schema_view = get_schema_view(
    openapi.Info(
        title="GoodFit API",
        default_version='v1',
        description="REST API for GoodFit - Fitness Tracking & Social Platform",
        terms_of_service="https://www.goodfit.com/terms/",
        contact=openapi.Contact(email="support@goodfit.com"),
        license=openapi.License(name="MIT License"),
    ),
    public=True,
    permission_classes=(permissions.AllowAny,),
)

urlpatterns = [
    # Landing Page
    path('', TemplateView.as_view(template_name='landing.html'), name='landing'),

    # Admin
    path('admin/', admin.site.urls),

    # API Documentation
    path('swagger/', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
    path('redoc/', schema_view.with_ui('redoc', cache_timeout=0), name='schema-redoc'),

    # API Endpoints
    path('api/auth/', include('apps.users.urls')),
    path('api/activities/', include('apps.activities.urls')),
    path('api/events/', include('apps.events.urls')),
    path('api/matching/', include('apps.matching.urls')),
    path('api/messaging/', include('apps.messaging.urls')),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
