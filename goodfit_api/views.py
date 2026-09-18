"""Project-level views."""

from django.urls import reverse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@api_view(['GET'])
@permission_classes([AllowAny])
def api_root(request):
    """Index of the API.

    Without this, `/api/` returns a bare 404, which reads as "the deployment is
    broken" when in fact only the endpoints below it are routed. Hitting the
    index should make it obvious that the API is up and what it offers.
    """
    def url(name):
        return request.build_absolute_uri(reverse(name))

    return Response({
        'name': 'GoodFit API',
        'version': 'v1',
        'status': 'ok',
        'endpoints': {
            'auth': request.build_absolute_uri('/api/auth/'),
            'activities': request.build_absolute_uri('/api/activities/'),
            'events': request.build_absolute_uri('/api/events/'),
            'matching': request.build_absolute_uri('/api/matching/'),
            'messaging': request.build_absolute_uri('/api/messaging/'),
        },
        'docs': {
            'swagger': url('schema-swagger-ui'),
            'redoc': url('schema-redoc'),
        },
    })
