"""Test builds of the member app, outside the stores: /download/.

Builds live in MEDIA_ROOT/downloads/ with a latest.json written by
deploy/publish_app.sh, so a new build goes up without a redeploy.
"""

import json
import os

from django.conf import settings
from django.shortcuts import render


def _latest():
    try:
        with open(os.path.join(settings.MEDIA_ROOT, 'downloads', 'latest.json'), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _build(b):
    if not b:
        return None
    return dict(b, url=f'{settings.MEDIA_URL.rstrip("/")}/downloads/{b["file"]}',
                mb=f'{b.get("bytes", 0) / 1048576:.0f}')


def download(request):
    d = _latest()
    android = _build(d.get('android'))
    ipa = _build(d.get('ios_ipa'))  # unsigned, for sideloading with the tester's own Apple ID
    ios = d.get('ios')  # {"testflight": "https://testflight.apple.com/join/..."} once there's an Apple account
    r = render(request, 'download.html', {'android': android, 'ipa': ipa, 'ios': ios,
                                          'page': request.build_absolute_uri()})
    r['Cache-Control'] = 'no-cache'
    return r
