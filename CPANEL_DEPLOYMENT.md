# Deploying the GoodFit API to cPanel

cPanel runs Python apps under **Phusion Passenger**, not gunicorn. The existing
`Procfile`, `build.sh` and `render.yaml` are for Render and are ignored here —
leave them if you still deploy there, or delete them if you do not.

## What is in the repo for cPanel

| File | Purpose |
|---|---|
| `passenger_wsgi.py` | Entry point Passenger imports. Loads `.env`, selects settings. |
| `goodfit_api/settings/cpanel.py` | Settings tuned for shared hosting. |
| `.env.cpanel.example` | Template for the real `.env`. |
| `deploy_cpanel.sh` | Install, check, migrate, collectstatic, restart. |
| `check_env.py` | Diagnostic: shows how `.env` resolves and tests the DB connection. |

## 1. Create the PostgreSQL database

cPanel → **PostgreSQL Databases**:

1. Create a database, e.g. `goodfit`.
2. Create a user and a strong password.
3. **Add the user to the database with ALL PRIVILEGES.**

cPanel prefixes both names with your account, so `goodfit` becomes
`cpaneluser_goodfit`. Use the full prefixed names in `.env`.

`DB_HOST` is `localhost` — the database is on the same machine.

## 2. Create the Python application

cPanel → **Setup Python App** → Create Application:

- **Python version:** 3.10 or newer
- **Application root:** e.g. `goodfitapp/backend`
- **Application URL:** the domain or subdomain for the API
- **Application startup file:** `passenger_wsgi.py`
- **Application Entry point:** `application`

cPanel creates a virtualenv and shows the command to enter it. Copy that line —
you need it every time you use Terminal.

## 3. Upload the code

Upload the `backend/` directory to the application root, or clone with Git
Version Control. Do **not** upload `venv/`, `.venv/`, `db.sqlite3` or `.env`.

## 4. Configure the environment

Copy `.env.cpanel.example` to `.env` in the application root and fill it in.
Generate a real secret key:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Set `STATIC_ROOT` and `MEDIA_ROOT` to absolute paths under your document root
so Apache serves them directly:

```
STATIC_ROOT=/home/cpaneluser/public_html/static
MEDIA_ROOT=/home/cpaneluser/public_html/media
```

## 5. Deploy

In cPanel Terminal, enter the virtualenv (the command from step 2), then:

```bash
cd ~/goodfitapp/backend
./deploy_cpanel.sh
```

That installs dependencies, runs `check --deploy`, migrates, collects static
files and restarts the app.

Create your admin user once:

```bash
python manage.py createsuperuser
```

## 6. Point the mobile app at it

In `mygoodfit_app/lib/services/api_service.dart`, change `baseUrl` from
`http://127.0.0.1:8000/api` to `https://api.yourdomain.com/api`.

iOS blocks plain HTTP by default, so the API must be served over HTTPS
(cPanel's AutoSSL is enough).

## Redeploying

Upload changed files, then re-run `./deploy_cpanel.sh`, or if only Python code
changed:

```bash
touch tmp/restart.txt
```

Passenger reloads on the next request.

---

## Things that commonly go wrong

**"DisallowedHost" errors.** Add the domain to `ALLOWED_HOSTS` (no scheme).

**Admin login fails with a CSRF error.** Add the origin to
`CSRF_TRUSTED_ORIGINS` *with* the scheme: `https://api.yourdomain.com`.

**Endless redirects.** cPanel already forces HTTPS and Django is redirecting
too. Keep `SECURE_SSL_REDIRECT=False` (the cPanel default here).

**Static files or the admin look unstyled.** `collectstatic` has not run, or
`STATIC_ROOT` is not under the document root. WhiteNoise is still enabled as a
fallback, so this usually means the path is wrong.

**Uploaded profile photos 404.** `MEDIA_ROOT` must be inside the document root.
Unlike development, Django does not serve media when `DEBUG=False` — Apache
does, straight off disk.

**Changes do not appear.** Passenger caches the loaded app. `touch tmp/restart.txt`.

**`UnicodeEncodeError: 'ascii' codec can't encode character`.** Passenger starts
the process with an ASCII stdout, so *anything* non-ASCII written to a log
crashes the worker. `passenger_wsgi.py` now forces UTF-8 on stdout and stderr,
and the settings modules are plain ASCII with no startup banners. If you add
`print()` calls or log user-supplied text, this is the protection that keeps a
name like `Jose` with an accent from taking the site down.

**`ModuleNotFoundError` for a package you installed.** You installed it outside
the app's virtualenv. Re-enter it with the command from Setup Python App.

**`ValueError: Port could not be cast to integer value as '<your password>'`**
A value has landed in the wrong key in `.env` — typically the password ending
up where the port belongs. Run the diagnostic:

```bash
python check_env.py
```

It prints every setting as Django actually resolves it (password masked) and
flags stray quotes, surrounding whitespace and embedded line breaks, then tries
a real database connection. Common causes:

The usual cause is a **`#` in the database password**. When the connection was
assembled into a URL, `#` began the URL *fragment*, so everything after it —
including `@host:port/name` — was discarded, leaving the password sitting where
the port should be. Other characters that used to break the URL: `@ : / %`.

This no longer applies: the settings build a plain dict and never assemble a
URL, so any password character is safe and needs no escaping.

Other things the diagnostic catches:

* The password pasted across two lines, so the second line became the next
  key's value.
* Values wrapped in quotes — `.env` needs `DB_PORT=5432`, not `DB_PORT="5432"`.

Note that passwords containing `@ : / # %` are fine now: the settings build the
connection as a plain dict and never assemble a URL, so nothing needs escaping.

---

## Two production defects fixed while preparing this

Both were live in `production.py` and would have surfaced only after deploying:

1. **`Argon2PasswordHasher` was first in `PASSWORD_HASHERS` but `argon2-cffi`
   was not in `requirements.txt`.** Django raises when hashing or verifying a
   password with a hasher whose library is missing, so **every login and signup
   would have failed**. The list now starts with PBKDF2 and only promotes
   Argon2 when the package imports.

2. **`CACHES` pointed at Redis, which is not installed and is rarely available
   on shared cPanel.** Any cache use would error. Redis is now used only when
   `REDIS_URL` is set *and* the client imports; otherwise it falls back to
   local memory.

Also added `SECURE_PROXY_SSL_HEADER`, without which Django behind Apache
considers every request insecure and `SECURE_SSL_REDIRECT` loops forever.

## Still to decide

**Media storage is local disk.** Uploaded avatars live on the cPanel filesystem,
which is fine for one server but is lost if you migrate hosts and is not backed
up with your database. Object storage (S3 or similar) is the durable option —
`production.py` has commented scaffolding for it.
