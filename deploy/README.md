# Deploying the A Good Fit API to a VPS (Hostinger)

One script, run from your Mac. It uploads this folder to the server and runs
it with Docker. Everything for the app lives in **one folder on the server**
(default `/opt/agoodfit`), so other projects can share the same VPS.

## Before the first deploy (5 minutes)

1. **A VPS with Ubuntu 22.04 or 24.04.** In Hostinger's hPanel, pick the plain
   Ubuntu template (the "Ubuntu with Docker" one works too). Note the IP
   address and root password.
2. **DNS:** where your domain is managed, add an `A` record for the API
   hostname (e.g. `api.agoodfit.app`) pointing to the VPS IP.
3. **Firewall:** if you turned on Hostinger's VPS firewall, allow ports 22,
   80 and 443.
4. **SSH key** (optional, saves typing the password each time):
   `ssh-copy-id root@YOUR_IP`

## First deploy

```bash
cd backend
./deploy/deploy.sh setup
```

It asks for the server IP, the API domain, your email and the folder
(press Enter for `/opt/agoodfit`), then:

- installs Docker if it's missing
- creates `/opt/agoodfit` with a `.env` holding freshly generated secrets
- sets up HTTPS (Caddy gets a free certificate automatically; if the server
  already runs nginx, it adds a site there with certbot instead)
- builds and starts the API, Postgres and Redis, runs migrations
- schedules a nightly database backup

Then create your admin login:

```bash
./deploy/deploy.sh admin
```

Open `https://YOUR_API_DOMAIN/admin/`.

## Every deploy after that

```bash
./deploy/deploy.sh
```

Uploads the code in this folder, rebuilds, runs migrations, and waits until
the API is healthy. If anything fails it shows the logs.

## Everyday commands

| Command | What it does |
|---|---|
| `./deploy/deploy.sh status` | Containers and health |
| `./deploy/deploy.sh logs` | Follow the API logs (`logs db`, `logs nginx` for others) |
| `./deploy/deploy.sh env` | Edit the server's settings (`.env`), then restart |
| `./deploy/deploy.sh manage <cmd>` | Any `manage.py` command, e.g. `manage showmigrations` |
| `./deploy/deploy.sh backup` | Back up now and download it to `deploy/backups/` |
| `./deploy/deploy.sh restore dump.sql.gz` | Replace the server database (backs up first) |
| `./deploy/deploy.sh ssh` | Shell in the app folder |

## What's on the server

```
/opt/agoodfit/
├── .env              settings and secrets (keep a copy somewhere safe)
├── app/              the code (replaced on every deploy)
├── data/postgres/    the database
├── data/media/       uploaded photos
├── data/logs/        error and backup logs
└── backups/          nightly database dumps (14 days), weekly photo archives (4 weeks)
```

The server is split in two layers (details in `deploy/server/README.md`,
installed on the server as `/opt/server/README.md`):

- **Server layer**, shared by every app: Docker (container logs capped),
  Caddy on ports 80/443 doing HTTPS for every domain, and the `site`
  command (`site list`, `site add`, `site remove`, `site next-port`).
- **App compartments**: this API is `/opt/agoodfit`, on `127.0.0.1:8010`,
  with its own database, memory caps (about 1.5 GB in total) and its own
  files `/etc/caddy/sites/agoodfit.caddy` and `/etc/cron.d/agoodfit`.

A second API gets `/opt/<name>`, port 8020 (`site next-port`), its own
compose project, and `site add <name> api.other.com 8020`. Nothing in this
app's compartment changes.

### Changing the API's domain

Point the new name's DNS at the server, change `DOMAIN` in
`deploy/deploy.local`, and run `./deploy/deploy.sh setup`. The domain-
dependent settings are rewritten; secrets and data stay as they are.

## Settings worth filling in (`./deploy/deploy.sh env`)

- `APPLE_CLIENT_IDS`, `GOOGLE_CLIENT_IDS`: needed for Sign in with Apple / Google.
- `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`: password-reset emails. Until set,
  emails are written to the log instead of sent.
- `BIRTHDAY_ENCRYPTION_KEY`: **never change it** once members have signed up.

## Turning on push notifications

1. In the [Firebase console](https://console.firebase.google.com), create a project and add the iOS app
   (bundle ID) and the Android app (package name). Upload your APNs key (Apple Developer → Keys) under
   Project settings → Cloud Messaging.
2. Project settings → Service accounts → Generate new private key. That downloads a JSON file.
3. `./deploy/deploy.sh env` and add:
   ```
   FCM_PROJECT_ID=your-project-id
   FCM_CREDENTIALS_JSON={"type":"service_account", ... the whole file on one line ...}
   ```
4. Put `GoogleService-Info.plist` (iOS) and `google-services.json` (Android) into the app, as the app's
   README describes, and rebuild it.

Until then the app's Notifications screen works as usual; only the phone alerts are off.

## Moving data from the old cPanel server

1. In cPanel, *phpPgAdmin → Export* (or `pg_dump --no-owner --no-acl`) to get a `.sql` file.
2. Copy the old server's `BIRTHDAY_ENCRYPTION_KEY` into the new `.env`
   (`./deploy/deploy.sh env`), otherwise existing birthdays can't be read.
3. `./deploy/deploy.sh restore old-database.sql`. Migrations bring it up to date.
4. Copy old uploaded photos into `/opt/agoodfit/data/media/`.

## Pointing the app at the server

The app talks to `https://getlovelly.cloud` by default. If you use that
hostname for the VPS (move its DNS `A` record to the VPS IP), the app needs no
rebuild. For a different hostname, build with
`--dart-define=GOODFIT_API_HOST=https://YOUR_API_DOMAIN`.
