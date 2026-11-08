"""Project-level views."""

from django.urls import reverse
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@api_view(['GET'])
@permission_classes([AllowAny])
def api_root(request):
    """Index of the API.

    Without this, `/api/` returns a bare 404, which reads as "the deployment is
    broken" when in fact only the paths beneath it are routed. Returning JSON
    keeps the response useful to a client rather than only to a browser.
    """
    def absolute(path):
        return request.build_absolute_uri(path)

    return Response({
        'name': 'GoodFit API',
        'version': 'v1',
        'status': 'ok',
        'endpoints': {
            'auth': absolute('/api/auth/'),
            'activities': absolute('/api/activities/'),
            'events': absolute('/api/events/'),
            'matching': absolute('/api/matching/'),
            'messaging': absolute('/api/messaging/'),
        },
        'docs': {
            'swagger': request.build_absolute_uri(reverse('schema-swagger-ui')),
            'redoc': request.build_absolute_uri(reverse('schema-redoc')),
        },
    })


@api_view(['GET'])
@permission_classes([AllowAny])
@authentication_classes([])
def health(request):
    """For the container health check and uptime monitors: 200 when the
    database answers, 503 when it doesn't."""
    from django.db import connection
    try:
        with connection.cursor() as c:
            c.execute('SELECT 1')
    except Exception:
        return Response({'status': 'db_unavailable'}, status=503)
    return Response({'status': 'ok'})
