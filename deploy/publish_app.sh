#!/usr/bin/env bash
# Put a test build of the member app on the server's download page
# (https://<domain>/download/) without redeploying.
#
#   ./deploy/publish_app.sh android ../mygoodfit_app/build/app/outputs/flutter-apk/app-release.apk 1.0.0+1
#   ./deploy/publish_app.sh testflight https://testflight.apple.com/join/XXXXXXXX
#
# Keeps the last 5 Android builds; the page always offers the newest.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
[ -f "$HERE/deploy.local" ] && source "$HERE/deploy.local"
SERVER="${SERVER:?set SERVER in deploy/deploy.local}"
AGF_ROOT="${AGF_ROOT:-/opt/agoodfit}"
DIR="$AGF_ROOT/data/media/downloads"
kind="${1:?usage: publish_app.sh android <apk> <version> | testflight <url>}"

case "$kind" in
  android)
    apk="${2:?apk path}"; version="${3:?version, e.g. 1.0.0+1}"
    [ -f "$apk" ] || { echo "No such file: $apk" >&2; exit 1; }
    sha=$(shasum -a 256 "$apk" | cut -d' ' -f1)
    bytes=$(wc -c < "$apk" | tr -d ' ')
    name="agoodfit-${version//+/-}-${sha:0:8}.apk"
    ssh "$SERVER" "mkdir -p '$DIR' && chown 1000:1000 '$DIR'"
    scp -q "$apk" "$SERVER:$DIR/$name"
    ssh "$SERVER" "python3 - '$DIR' '$name' '$version' '$sha' '$bytes'" <<'PY'
import json, os, sys, datetime
d, name, version, sha, size = sys.argv[1:]
p = os.path.join(d, 'latest.json')
try:
    data = json.load(open(p))
except Exception:
    data = {}
data['android'] = {'file': name, 'version': version, 'sha256': sha, 'bytes': int(size),
                   'date': datetime.date.today().strftime('%b %-d, %Y')}
json.dump(data, open(p, 'w'))
apks = sorted((f for f in os.listdir(d) if f.endswith('.apk')), key=lambda f: os.path.getmtime(os.path.join(d, f)))
for old in apks[:-5]:
    os.remove(os.path.join(d, old))
PY
    ssh "$SERVER" "chown -R 1000:1000 '$DIR' && chmod 644 '$DIR'/*"
    echo "Published $name"
    ;;
  testflight)
    url="${2:?TestFlight public link}"
    ssh "$SERVER" "mkdir -p '$DIR' && python3 - '$DIR' '$url'" <<'PY'
import json, os, sys
d, url = sys.argv[1:]
p = os.path.join(d, 'latest.json')
try:
    data = json.load(open(p))
except Exception:
    data = {}
data['ios'] = {'testflight': url}
json.dump(data, open(p, 'w'))
PY
    echo "TestFlight link set"
    ;;
  *) echo "usage: publish_app.sh android <apk> <version> | testflight <url>" >&2; exit 1 ;;
esac
DOMAIN="${DOMAIN:-api.getlovelly.cloud}"
echo "Download page: https://$DOMAIN/download/"
