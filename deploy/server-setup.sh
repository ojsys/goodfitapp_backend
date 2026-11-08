#!/usr/bin/env bash
# A Good Fit API: prepare its compartment on the server. Safe to re-run;
# re-running with a new domain moves the API to it.
# deploy.sh runs this for you:
#
#   bash server-setup.sh <domain> <email> [app folder]
#
# The shared server layer (Docker, Caddy, the `site` command) comes from
# server/bootstrap.sh. Everything for this app lives in its folder
# (default /opt/agoodfit); outside it there's only its Caddy site file and
# its cron file, both named after the app.
set -euo pipefail

DOMAIN="${1:?usage: server-setup.sh <domain> <email> [app folder]}"
EMAIL="${2:?usage: server-setup.sh <domain> <email> [app folder]}"
AGF_ROOT="${3:-/opt/agoodfit}"
APP="$(basename "$AGF_ROOT")"
HERE="$(cd "$(dirname "$0")" && pwd)"

say() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
[ "$(id -u)" = 0 ] || { echo "Run as root (or with sudo)."; exit 1; }

# ------------------------------------------------------------ server layer
ADMIN_EMAIL="$EMAIL" bash "$HERE/server/bootstrap.sh"

# ----------------------------------------------------------------- folders
say "Preparing $AGF_ROOT"
mkdir -p "$AGF_ROOT"/{app,backups,data/media,data/logs,data/postgres}
chown -R 1000:1000 "$AGF_ROOT/data/media" "$AGF_ROOT/data/logs"   # the app's uid in its container
chmod 700 "$AGF_ROOT/backups"

# -------------------------------------------------------------------- .env
set_env() {  # set_env KEY VALUE: replace the line, or add it
  local f="$AGF_ROOT/.env" tmp
  tmp="$(mktemp)"
  if grep -qE "^$1=" "$f"; then
    awk -v k="$1" -v v="$2" 'BEGIN{FS=OFS="="} $1==k{print k"="v; next} {print}' "$f" > "$tmp"
  else
    cat "$f" > "$tmp"; echo "$1=$2" >> "$tmp"
  fi
  cat "$tmp" > "$f"; rm -f "$tmp"
}

if [ -f "$AGF_ROOT/.env" ]; then
  say "Keeping existing $AGF_ROOT/.env (secrets unchanged)"
  AGF_PORT="$(grep -E '^AGF_PORT=' "$AGF_ROOT/.env" | cut -d= -f2)"
else
  AGF_PORT="$(/opt/server/bin/site next-port)"
  say "Creating $AGF_ROOT/.env with fresh secrets (port $AGF_PORT)"
  secret() { openssl rand -base64 64 | tr -dc 'A-Za-z0-9' | head -c 60; }
  fernet() { openssl rand -base64 32 | tr '+/' '-_'; }
  umask 077
  cat > "$AGF_ROOT/.env" <<ENV
# A Good Fit API on this server. Created by server-setup.sh on $(date -u +%F).
# Back this file up somewhere safe: without BIRTHDAY_ENCRYPTION_KEY stored
# birthdays can't be read, and without DB_PASSWORD the database can't be opened.

AGF_ROOT=$AGF_ROOT
AGF_PORT=$AGF_PORT

SECRET_KEY=$(secret)
CORS_ALLOWED_ORIGINS=

DB_NAME=agoodfit
DB_USER=agoodfit
DB_PASSWORD=$(secret)

# Set once and never change it.
BIRTHDAY_ENCRYPTION_KEY=${BIRTHDAY_ENCRYPTION_KEY:-$(fernet)}

# Sign-in providers (comma-separated client IDs)
APPLE_CLIENT_IDS=
GOOGLE_CLIENT_IDS=

# Email (password reset). Leave EMAIL_HOST_USER empty to log emails instead.
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
ADMIN_EMAIL=$EMAIL

# Create a route
ROUTING_URL_BIKE=https://routing.openstreetmap.de/routed-bike
ROUTING_URL_FOOT=https://routing.openstreetmap.de/routed-foot
ELEVATION_URL=https://api.opentopodata.org/v1/srtm30m
FREE_ROUTE_LIMIT=5

# Domain settings (rewritten by server-setup.sh when the domain changes)
ENV
  umask 022
fi

# Everything that depends on the domain is kept in step with it.
say "Domain: $DOMAIN"
set_env ALLOWED_HOSTS "$DOMAIN,localhost,127.0.0.1"
set_env CSRF_TRUSTED_ORIGINS "https://$DOMAIN"
set_env PUBLIC_BASE_URL "https://$DOMAIN"
set_env DEFAULT_FROM_EMAIL "A Good Fit <noreply@$DOMAIN>"
chmod 600 "$AGF_ROOT/.env"

# ------------------------------------------------------------- web address
/opt/server/bin/site add "$APP" "$DOMAIN" "$AGF_PORT" 25MB

# ----------------------------------------------------------------- backups
say "Scheduled jobs: nightly backup at 03:15 (kept 14 days), hourly ride reminders"
cat > "/etc/cron.d/$APP" <<CRON
# $APP: nightly backup (see $AGF_ROOT/app/deploy/backup.sh)
15 3 * * * root AGF_ROOT=$AGF_ROOT bash $AGF_ROOT/app/deploy/backup.sh >> $AGF_ROOT/data/logs/backup.log 2>&1
# $APP: day-before ride reminders (Phase 6)
5 * * * * root docker compose -f $AGF_ROOT/app/deploy/docker-compose.yml --env-file $AGF_ROOT/.env exec -T web python manage.py send_reminders >> $AGF_ROOT/data/logs/reminders.log 2>&1
CRON

say "Compartment ready: $AGF_ROOT · 127.0.0.1:$AGF_PORT · https://$DOMAIN"
