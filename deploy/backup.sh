#!/usr/bin/env bash
# Database backup (daily via cron) and a weekly copy of uploaded photos.
# Run on the server:  AGF_ROOT=/opt/agoodfit bash backup.sh
set -euo pipefail
AGF_ROOT="${AGF_ROOT:-/opt/agoodfit}"
cd "$AGF_ROOT/app/deploy"

stamp="$(date -u +%Y%m%d-%H%M%S)"
out="$AGF_ROOT/backups/db-$stamp.sql.gz"
# Credentials come from the db container itself (.env isn't shell-safe).
docker compose --env-file "$AGF_ROOT/.env" exec -T db \
  sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-acl' | gzip > "$out.part"
# A failed dump must not leave a file that looks like a good backup.
[ "$(gunzip -c "$out.part" | head -c 200 | grep -c 'PostgreSQL database dump')" = 1 ] \
  || { rm -f "$out.part"; echo "$(date -u +%FT%TZ) BACKUP FAILED"; exit 1; }
mv "$out.part" "$out"
echo "$(date -u +%FT%TZ) database -> $out ($(du -h "$out" | cut -f1))"

# Photos: once a week (Sundays), or when asked with --media.
if [ "$(date -u +%u)" = 7 ] || [ "${1:-}" = "--media" ]; then
  tar -czf "$AGF_ROOT/backups/media-$stamp.tar.gz" -C "$AGF_ROOT/data" media
  echo "$(date -u +%FT%TZ) media -> $AGF_ROOT/backups/media-$stamp.tar.gz"
fi

find "$AGF_ROOT/backups" -name 'db-*.sql.gz' -mtime +14 -delete
find "$AGF_ROOT/backups" -name 'media-*.tar.gz' -mtime +28 -delete
