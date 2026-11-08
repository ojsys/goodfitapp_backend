#!/bin/sh
# Runs before the web server starts: wait for Postgres, migrate, collect static.
set -e

if [ "${SKIP_STARTUP_TASKS:-0}" != "1" ]; then
  echo "Waiting for the database..."
  i=0
  until python -c "import django; django.setup(); from django.db import connection; connection.ensure_connection()" 2>/dev/null; do
    i=$((i+1))
    if [ "$i" -ge 30 ]; then echo "Database not reachable after 60s"; exit 1; fi
    sleep 2
  done
  python manage.py migrate --noinput
  python manage.py collectstatic --noinput -v 0
  python manage.py check --deploy --fail-level ERROR
fi

exec "$@"
