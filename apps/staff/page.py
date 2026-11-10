"""Serves the React staff dashboard (portal/dist/staff.html) at /staff/."""

import os

from django.conf import settings
from django.http import HttpResponse

INDEX = os.path.join(settings.BASE_DIR, 'portal', 'dist', 'staff.html')
_cache = {}


def index(request, *args, **kwargs):
    try:
        mtime = os.path.getmtime(INDEX)
        if _cache.get('mtime') != mtime:
            with open(INDEX, encoding='utf-8') as f:
                _cache.update(mtime=mtime, html=f.read())
        html = _cache['html']
    except OSError:
        return HttpResponse('The staff dashboard isn’t built yet (cd portal && npm run build).', status=503,
                            content_type='text/plain; charset=utf-8')
    r = HttpResponse(html, content_type='text/html; charset=utf-8')
    r['Cache-Control'] = 'no-cache'
    r['X-Frame-Options'] = 'DENY'
    r['X-Robots-Tag'] = 'noindex'
    return r
