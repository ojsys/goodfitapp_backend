#!/usr/bin/env bash
# site: give an app on this server a public HTTPS domain.
#
# Every app runs in its own folder under /opt and listens on a private
# 127.0.0.1 port. Caddy owns ports 80/443 for the whole server and forwards
# each domain to its app. One file per app in /etc/caddy/sites/.
#
#   site add <app> <domain>[,<domain2>] <port> [max upload, e.g. 25MB]
#   site remove <app>
#   site list
#   site next-port          first free app port (8010, 8020, 8030, ...)
set -euo pipefail

SITES=/etc/caddy/sites
die() { echo "site: $*" >&2; exit 1; }
reload() {
  caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null 2>&1 \
    || { caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile; die "Caddy config is invalid; nothing reloaded."; }
  # Validating as root can create log files Caddy (its own user) can't open.
  mkdir -p /var/log/caddy && chown -R caddy:caddy /var/log/caddy
  if systemctl is-active --quiet caddy; then systemctl reload caddy; else systemctl restart caddy; fi
  sleep 2
  systemctl is-active --quiet caddy || { journalctl -u caddy --no-pager -n 5 -o cat; die "Caddy isn't running."; }
}
used_ports() {
  { grep -hoE 'reverse_proxy 127\.0\.0\.1:[0-9]+' "$SITES"/*.caddy 2>/dev/null | cut -d: -f2
    ss -ltnH 2>/dev/null | awk '{print $4}' | grep -oE '[0-9]+$'; } | sort -un
}

cmd="${1:-list}"; shift || true
case "$cmd" in
  add)
    app="${1:?usage: site add <app> <domain> <port> [max upload]}"
    domains="${2:?usage: site add <app> <domain> <port> [max upload]}"
    port="${3:?usage: site add <app> <domain> <port> [max upload]}"
    max="${4:-25MB}"
    [[ "$app" =~ ^[a-z0-9][a-z0-9-]*$ ]] || die "app name: lowercase letters, digits and dashes"
    [[ "$port" =~ ^[0-9]+$ ]] || die "port must be a number"
    other="$(grep -lE "reverse_proxy 127\.0\.0\.1:$port\$" "$SITES"/*.caddy 2>/dev/null | grep -v "/$app.caddy" || true)"
    [ -z "$other" ] || die "port $port is already used by $(basename "$other" .caddy)"
    mkdir -p "$SITES"
    cat > "$SITES/$app.caddy" <<CADDY
# $app -> 127.0.0.1:$port   (managed by: site add $app ...)
${domains//,/, } {
	encode gzip
	request_body {
		max_size $max
	}
	reverse_proxy 127.0.0.1:$port
	log {
		output file /var/log/caddy/$app.log {
			roll_size 10MiB
			roll_keep 5
		}
	}
}
CADDY
    reload
    echo "site: ${domains//,/, } -> 127.0.0.1:$port ($app)"
    ;;
  remove)
    app="${1:?usage: site remove <app>}"
    [ -f "$SITES/$app.caddy" ] || die "no site called $app"
    rm "$SITES/$app.caddy"
    reload
    echo "site: removed $app"
    ;;
  list)
    printf '%-16s %-8s %s\n' APP PORT DOMAINS
    for f in "$SITES"/*.caddy; do
      [ -e "$f" ] || continue
      d="$(grep -m1 -E '^[^#[:space:]].*\{$' "$f" | sed 's/ {$//')"
      p="$(grep -oE 'reverse_proxy 127\.0\.0\.1:[0-9]+' "$f" | cut -d: -f2)"
      printf '%-16s %-8s %s\n' "$(basename "$f" .caddy)" "$p" "$d"
    done
    ;;
  next-port)
    p=8010
    while used_ports | grep -qx "$p"; do p=$((p + 10)); done
    echo "$p"
    ;;
  *) sed -n '2,13p' "$0"; exit 1 ;;
esac
