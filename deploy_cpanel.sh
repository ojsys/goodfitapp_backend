#!/usr/bin/env bash
#
# Post-upload deploy step for cPanel.
#
# Run from the application root, inside the virtualenv cPanel created for the
# app (the "Setup Python App" page shows the exact `source .../activate`
# command to paste into Terminal first).
#
#   ./deploy_cpanel.sh
#
set -o errexit
set -o nounset
set -o pipefail

export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-goodfit_api.settings.cpanel}"

echo "==> Installing dependencies"
pip install --upgrade pip
pip install -r requirements.txt

echo "==> Checking configuration"
# Fails loudly on a bad SECRET_KEY, unreachable database or missing setting,
# before any migration runs.
python manage.py check --deploy

echo "==> Applying migrations"
python manage.py migrate --no-input

echo "==> Collecting static files"
python manage.py collectstatic --no-input

echo "==> Restarting the application"
mkdir -p tmp
touch tmp/restart.txt

echo "==> Done. Passenger will pick up the new code on the next request."
