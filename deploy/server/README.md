# This server

A shared VPS that can host several apps side by side. Each one stays in
its own compartment, so adding, updating or removing one never touches
the others.

## How it's laid out

```
Internet ──► Caddy (ports 80/443, HTTPS for every domain)
               ├── api.getlovelly.cloud ──► 127.0.0.1:8010 ──► /opt/agoodfit
               └── (next app)           ──► 127.0.0.1:8020 ──► /opt/<app>
```

| Where | What |
|---|---|
| `/opt/server/` | This handbook and the `site` command. Shared. |
| `/opt/<app>/` | Everything for one app: code, `.env`, data, backups. |
| `/etc/caddy/sites/<app>.caddy` | That app's domain(s). One file per app. |
| `/etc/cron.d/<app>` | That app's scheduled jobs (backups). |
| `/var/log/caddy/<app>.log` | That app's web access log (rotated). |

## Rules every app follows

1. **Own folder:** `/opt/<app>`, nothing installed elsewhere.
2. **Own Docker Compose project** named `<app>`, with its own private network
   and its own database container. Apps never share a database.
3. **Private port only:** publish exactly one port, on `127.0.0.1`, from the
   series 8010, 8020, 8030... (`site next-port` gives the next free one).
   Never publish on `0.0.0.0`, never use 80/443.
4. **Domain through `site`:** `site add <app> <domain> <port>`.
5. **Memory limits** on every container (this VPS has about 4 GB), and
   capped logs (the Docker default here is 10 MB x 3 per container).

## The `site` command

```bash
site list                                     # apps, ports, domains
site next-port                                # free port for a new app
site add myapi api.example.com 8020           # HTTPS for a new app
site add myapi api.example.com,www.example.com 8020 50MB   # several domains, bigger uploads
site remove myapi                             # take a domain offline
```

Point the domain's DNS `A` record to this server first; Caddy then gets the
certificate by itself within a minute.

## Adding another API

1. `mkdir -p /opt/myapi` and put its code and a `docker-compose.yml` there,
   with `name: myapi` at the top and its port published as
   `"127.0.0.1:8020:<container port>"`.
2. `cd /opt/myapi && docker compose up -d`
3. `site add myapi api.example.com 8020`

`/opt/agoodfit/app/deploy/` is a complete example to copy (Dockerfile,
compose file with limits, backups, deploy script).

## Removing an app

```bash
site remove myapi
cd /opt/myapi && docker compose down     # add -v to delete its volumes
rm /etc/cron.d/myapi                     # if it had scheduled jobs
# then delete /opt/myapi once you have a backup
```

## Apps on this server

| App | Folder | Port | Domain | Deployed with |
|---|---|---|---|---|
| A Good Fit API | `/opt/agoodfit` | 8010 | api.getlovelly.cloud | `backend/deploy/deploy.sh` (from the Mac) |

`site list` always shows the live state.
