#!/usr/bin/env bash
# Deploy the A Good Fit API to your VPS, from your Mac.
#
#   ./deploy/deploy.sh setup          first time: prepare the server, then deploy
#   ./deploy/deploy.sh                deploy the code in this folder (same as "update")
#   ./deploy/deploy.sh admin          create a Django admin login
#   ./deploy/deploy.sh status         containers and health
#   ./deploy/deploy.sh logs           follow the API logs (Ctrl-C to stop)
#   ./deploy/deploy.sh manage <cmd>   run any manage.py command on the server
#   ./deploy/deploy.sh backup         back up now and download it to deploy/backups/
#   ./deploy/deploy.sh restore <file.sql[.gz]>   replace the server database with a dump
#   ./deploy/deploy.sh env            edit the server's .env, then restart
#   ./deploy/deploy.sh ssh            open a shell in the app folder
#
# Server details are asked once and kept in deploy/deploy.local (not committed).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$(dirname "$HERE")"
CONF="$HERE/deploy.local"

say() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31m%s\033[0m\n' "$*"; exit 1; }

# ------------------------------------------------------------------ config
if [ ! -f "$CONF" ]; then
  echo "First run: tell me about the server (saved to deploy/deploy.local)."
  read -rp "  Server IP or hostname: " ip
  read -rp "  SSH user [root]: " user; user="${user:-root}"
  read -rp "  API domain (e.g. api.agoodfit.app): " domain
  read -rp "  Your email (HTTPS certificates, error mail): " email
  read -rp "  App folder on the server [/opt/agoodfit]: " root; root="${root:-/opt/agoodfit}"
  cat > "$CONF" <<EOF
SERVER=$user@$ip
DOMAIN=$domain
EMAIL=$email
AGF_ROOT=$root
EOF
fi
# shellcheck disable=SC1090
. "$CONF"
[ -n "${SERVER:-}" ] && [ -n "${DOMAIN:-}" ] || die "deploy/deploy.local is missing SERVER or DOMAIN."
AGF_ROOT="${AGF_ROOT:-/opt/agoodfit}"
case "$AGF_ROOT" in /|/root|/home|/opt|/srv|/var|/usr|/etc|"") die "AGF_ROOT must be a dedicated folder, e.g. /opt/agoodfit";; esac

# One SSH connection for the whole run, so a password is asked at most once.
SOCK="/tmp/agf-ssh-%C"
SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o ControlMaster=auto -o "ControlPath=$SOCK" -o ControlPersist=120 -o ServerAliveInterval=30)
# Optional in deploy.local: SSH_PORT=2222, SSH_KEY=~/.ssh/other_key
[ -n "${SSH_PORT:-}" ] && SSH_OPTS+=(-p "$SSH_PORT")
[ -n "${SSH_KEY:-}" ] && SSH_OPTS+=(-i "${SSH_KEY/#\~/$HOME}")
SUDO=""; [ "${SERVER%%@*}" = root ] || SUDO="sudo"
remote()   { ssh "${SSH_OPTS[@]}" "$SERVER" "$@"; }
remote_t() { ssh -t "${SSH_OPTS[@]}" "$SERVER" "$@"; }
compose="$SUDO docker compose -f $AGF_ROOT/app/deploy/docker-compose.yml --env-file $AGF_ROOT/.env"

sync_code() {
  say "Uploading code to $SERVER:$AGF_ROOT/app"
  remote "$SUDO mkdir -p $AGF_ROOT/app && $SUDO chown \$(id -u):\$(id -g) $AGF_ROOT/app"
  rsync -az --delete --no-owner --no-group -e "ssh ${SSH_OPTS[*]}" \
    --exclude '.git/' --exclude 'venv/' --exclude '.venv/' --exclude '__pycache__/' \
    --exclude '*.pyc' --exclude '.env' --exclude '.env.local' --exclude 'media/' \
    --exclude 'staticfiles/' --exclude 'logs/' --exclude '*.log' --exclude '*.bak' \
    --exclude 'deploy/deploy.local' --exclude 'deploy/backups/' --exclude '.DS_Store' \
    "$BACKEND/" "$SERVER:$AGF_ROOT/app/"
}

start() {
  say "Building and starting (migrations run automatically)"
  remote "$compose up -d --build --remove-orphans && $SUDO docker image prune -f >/dev/null"
  say "Waiting for the API to report healthy"
  for _ in $(seq 1 40); do
    state="$(remote "$SUDO docker inspect -f '{{.State.Health.Status}}' \$($compose ps -q web) 2>/dev/null" || true)"
    [ "$state" = healthy ] && break
    [ "$state" = unhealthy ] && break
    sleep 3
  done
  if [ "$state" != healthy ]; then
    remote "$compose logs --tail 60 web" || true
    die "The API didn't become healthy (state: ${state:-unknown}). Logs are above."
  fi
  if curl -fsS --max-time 10 "https://$DOMAIN/api/health/" >/dev/null 2>&1; then
    say "Live: https://$DOMAIN/api/   (admin: https://$DOMAIN/admin/)"
  else
    printf '\nThe API is running on the server, but https://%s isn'"'"'t answering yet.\n' "$DOMAIN"
    printf 'Check that the DNS A record for %s points to the server IP; the certificate is issued automatically once it does.\n' "$DOMAIN"
  fi
}

cmd="${1:-update}"; shift || true
case "$cmd" in
  setup)
    sync_code
    say "Preparing the server"
    remote_t "$SUDO bash $AGF_ROOT/app/deploy/server-setup.sh '$DOMAIN' '${EMAIL:-}' '$AGF_ROOT'"
    start
    echo; echo "Next: ./deploy/deploy.sh admin   (create your admin login)"
    ;;
  update|deploy|push)
    remote "test -f $AGF_ROOT/.env" || die "The server isn't set up yet. Run: ./deploy/deploy.sh setup"
    sync_code
    start
    ;;
  admin)     remote_t "$compose exec web python manage.py createsuperuser" ;;
  manage)    remote_t "$compose exec web python manage.py $*" ;;
  status)
    remote "$compose ps --format 'table {{.Service}}\t{{.Status}}'"
    printf '\nhttps://%s/api/health/ -> %s\n' "$DOMAIN" "$(curl -sS --max-time 10 "https://$DOMAIN/api/health/" 2>&1 || true)"
    ;;
  logs)      remote_t "$compose logs -f --tail 100 ${1:-web}" ;;
  ssh)       remote_t "cd $AGF_ROOT && exec \$SHELL -l" ;;
  env)
    remote_t "$SUDO \${EDITOR:-nano} $AGF_ROOT/.env"
    remote "$compose up -d"
    ;;
  backup)
    remote "$SUDO AGF_ROOT=$AGF_ROOT bash $AGF_ROOT/app/deploy/backup.sh"
    latest="$(remote "$SUDO sh -c 'ls -1t $AGF_ROOT/backups/db-*.sql.gz' | head -1")"
    mkdir -p "$HERE/backups"
    rsync -az --rsync-path="$SUDO rsync" -e "ssh ${SSH_OPTS[*]}" "$SERVER:$latest" "$HERE/backups/"
    say "Downloaded deploy/backups/$(basename "$latest")"
    ;;
  restore)
    file="${1:?usage: deploy.sh restore <dump.sql or dump.sql.gz>}"
    [ -f "$file" ] || die "No such file: $file"
    read -rp "This replaces ALL data in the server database. Type the domain ($DOMAIN) to continue: " ok
    [ "$ok" = "$DOMAIN" ] || die "Cancelled."
    say "Backing up the current database first"
    remote "$SUDO AGF_ROOT=$AGF_ROOT bash $AGF_ROOT/app/deploy/backup.sh"
    name="restore-$(date +%s)-$(basename "$file")"
    rsync -a -e "ssh ${SSH_OPTS[*]}" "$file" "$SERVER:/tmp/$name"
    say "Restoring"
    cat_cmd="cat"; case "$file" in *.gz) cat_cmd="gunzip -c";; esac
    remote "set -e; $compose stop web nginx
      $compose exec -T db sh -c 'dropdb -U \$POSTGRES_USER --if-exists \$POSTGRES_DB && createdb -U \$POSTGRES_USER \$POSTGRES_DB'
      $cat_cmd /tmp/$name | $compose exec -T db sh -c 'psql -q -v ON_ERROR_STOP=0 -U \$POSTGRES_USER -d \$POSTGRES_DB' >/dev/null
      rm -f /tmp/$name"
    start
    ;;
  *) sed -n '2,16p' "$0"; exit 1 ;;
esac
