#!/usr/bin/env bash
# Server layer, shared by every app on this VPS. Safe to re-run.
#
#   - Docker (with capped container logs)
#   - Caddy: the only thing on ports 80/443; HTTPS for every app's domain
#   - /opt/server: the `site` command and the server handbook
#
# Apps never install into the server's own folders: each gets /opt/<app>.
set -euo pipefail

say() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
[ "$(id -u)" = 0 ] || { echo "Run as root."; exit 1; }
HERE="$(cd "$(dirname "$0")" && pwd)"
export DEBIAN_FRONTEND=noninteractive

need=()
for p in curl rsync openssl ca-certificates gnupg; do dpkg -s "$p" >/dev/null 2>&1 || need+=("$p"); done
[ ${#need[@]} -eq 0 ] || { apt-get update -qq && apt-get install -y -qq "${need[@]}"; }

# ------------------------------------------------------------------ Docker
if ! command -v docker >/dev/null 2>&1; then
  say "Installing Docker"
  curl -fsSL https://get.docker.com | sh
fi
docker compose version >/dev/null 2>&1 || apt-get install -y -qq docker-compose-plugin
# Default log cap for every container on the server, so no app can fill the
# disk with logs. Only written when no daemon config exists yet.
if [ ! -f /etc/docker/daemon.json ]; then
  say "Capping container logs (10 MB x 3 per container)"
  mkdir -p /etc/docker
  printf '{\n  "log-driver": "json-file",\n  "log-opts": {"max-size": "10m", "max-file": "3"}\n}\n' > /etc/docker/daemon.json
  systemctl restart docker
fi
systemctl enable --now docker >/dev/null 2>&1 || true

# ------------------------------------------------------------------- Caddy
owner_of() { { ss -ltnp "( sport = :$1 )" 2>/dev/null | grep -oE 'users:\(\("[^"]+' | head -1 | cut -d'"' -f2; } || true; }
WEB="$(owner_of 443)"; [ -n "$WEB" ] || WEB="$(owner_of 80)"
if [ -n "$WEB" ] && [ "$WEB" != caddy ]; then
  echo "Ports 80/443 belong to '$WEB'. This setup expects Caddy to own them." >&2
  echo "Forward each app's domain to its 127.0.0.1 port there instead." >&2
  exit 3
fi
if ! command -v caddy >/dev/null 2>&1; then
  say "Installing Caddy (automatic HTTPS)"
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq && apt-get install -y -qq caddy
fi
mkdir -p /etc/caddy/sites /var/log/caddy
chown caddy:caddy /var/log/caddy 2>/dev/null || true
# The main Caddyfile only holds server-wide options; sites live in their own
# files. Replaces the package's default welcome page on first run.
if ! grep -qF '# Server-wide Caddy' /etc/caddy/Caddyfile 2>/dev/null; then
  say "Writing the server-wide Caddyfile"
  [ -f /etc/caddy/Caddyfile ] && cp /etc/caddy/Caddyfile "/etc/caddy/Caddyfile.orig-$(date +%s)"
  {
    echo "# Server-wide Caddy. Each app has one file in /etc/caddy/sites/,"
    echo "# managed with the \`site\` command (see /opt/server/README.md)."
    if [ -n "${ADMIN_EMAIL:-}" ]; then
      printf '{\n\t# Let'"'"'s Encrypt account and expiry notices\n\temail %s\n}\n' "$ADMIN_EMAIL"
    fi
    echo
    echo "import /etc/caddy/sites/*.caddy"
  } > /etc/caddy/Caddyfile
fi
systemctl enable caddy >/dev/null 2>&1 || true

# --------------------------------------------------------------- toolkit
say "Installing the server toolkit in /opt/server"
mkdir -p /opt/server/bin
install -m 755 "$HERE/site.sh" /opt/server/bin/site
ln -sf /opt/server/bin/site /usr/local/bin/site
install -m 644 "$HERE/README.md" /opt/server/README.md

# Open web ports if a firewall is on (never turns one on).
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null
fi
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null
chown -R caddy:caddy /var/log/caddy
if systemctl is-active --quiet caddy; then systemctl reload caddy; else systemctl restart caddy; fi
