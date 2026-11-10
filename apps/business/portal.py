"""Serves the React business portal (built into portal/dist by Vite).

On the portal's own host (BUSINESS_HOST, business.getlovelly.cloud) every
page path returns the portal's index.html and the React router takes over;
/api/, /static/, /media/ and /admin/ work as on the API host. /business/ on
any host serves it too (local development, and before DNS is in place).
"""

import os

from django.conf import settings
from django.http import HttpResponse

INDEX = os.path.join(settings.BASE_DIR, 'portal', 'dist', 'index.html')
PASS = ('/api/', '/static/', '/media/', '/admin/', '/openapi', '/swagger', '/redoc', '/community-guidelines/',
        '/featured-events-policy/', '/download/', '/staff', '/tiles/')
_cache = {}


def index(request, *args, **kwargs):
    try:
        mtime = os.path.getmtime(INDEX)
        if _cache.get('mtime') != mtime:
            with open(INDEX, encoding='utf-8') as f:
                _cache.update(mtime=mtime, html=f.read())
        html = _cache['html']
    except OSError:
        return HttpResponse('The business portal isn’t built yet (cd portal && npm run build).', status=503,
                            content_type='text/plain; charset=utf-8')
    r = HttpResponse(html, content_type='text/html; charset=utf-8')
    r['Cache-Control'] = 'no-cache'
    r['X-Frame-Options'] = 'DENY'
    return r


class PortalHostMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = settings.BUSINESS_HOST
        if host and request.get_host().split(':')[0] == host and not request.path.startswith(PASS):
            return index(request)
        return self.get_response(request)
