# Django Settings Guide

## 📁 Settings Structure

The Django settings have been separated into multiple files for better organization and security:

```
backend/goodfit_api/settings/
├── __init__.py           # Auto-loads correct settings based on DJANGO_ENV
├── base.py              # Common settings shared across all environments
├── development.py       # Development-specific settings
└── production.py        # Production-specific settings
```

---

## 🔄 How It Works

The settings are automatically loaded based on the `DJANGO_ENV` environment variable:

- `DJANGO_ENV=development` → Loads `development.py`
- `DJANGO_ENV=production` → Loads `production.py`
- No `DJANGO_ENV` set → Defaults to `development`

---

## 🛠️ Development Settings

### File: `goodfit_api/settings/development.py`

**Key Features:**
- ✅ `DEBUG = True` - Detailed error pages
- ✅ `ALLOWED_HOSTS = ['*']` - Accept all hosts
- ✅ `CORS_ALLOW_ALL_ORIGINS = True` - CORS enabled for all
- ✅ Database: `goodfit_dev_db` - Development database
- ✅ Browsable API - REST Framework browsable API enabled
- ✅ Console email backend - Emails printed to console
- ✅ Local memory cache - Simple caching for dev
- ✅ Detailed logging - DEBUG level logging

**Security:**
- 🔓 SSL redirect disabled
- 🔓 Secure cookies disabled
- 🔓 CORS open to all origins

**Usage:**
```bash
# Method 1: Set environment variable
export DJANGO_ENV=development
python manage.py runserver

# Method 2: Use in .env file
# Add to .env: DJANGO_ENV=development
python manage.py runserver
```

---

## 🚀 Production Settings

### File: `goodfit_api/settings/production.py`

**Key Features:**
- ✅ `DEBUG = False` - No detailed errors
- ✅ `ALLOWED_HOSTS` - Only specific domains allowed
- ✅ `CORS_ALLOWED_ORIGINS` - Only specific origins
- ✅ Database: Production database or DATABASE_URL
- ✅ JSON-only API - No browsable API
- ✅ SMTP email backend - Real email sending
- ✅ Redis cache - Production caching
- ✅ Production logging - WARNING level, file logging

**Security:**
- 🔒 SSL redirect enabled
- 🔒 Secure cookies enabled
- 🔒 HSTS enabled (1 year)
- 🔒 CORS restricted to specific domains
- 🔒 XSS protection enabled
- 🔒 Clickjacking protection
- 🔒 Stronger password hashers (Argon2)

**Usage:**
```bash
# Set environment variable
export DJANGO_ENV=production
python manage.py runserver

# Or in .env file
# DJANGO_ENV=production
```

---

## 📝 Base Settings

### File: `goodfit_api/settings/base.py`

Contains settings common to all environments:

- Installed apps
- Middleware configuration
- Template settings
- URL configuration
- Password validators
- Internationalization
- Static files configuration
- REST Framework configuration
- JWT settings
- CORS methods and headers

---

## 🔧 Environment Variables

### Development (.env)

```bash
# Environment
DJANGO_ENV=development

# Django
SECRET_KEY=your-secret-key
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# Database
DB_NAME=goodfit_dev_db
DB_USER=Apple
DB_PASSWORD=
DB_HOST=localhost
DB_PORT=5432
```

### Production (.env)

```bash
# Environment
DJANGO_ENV=production

# Django
SECRET_KEY=VERY-LONG-RANDOM-STRING
DEBUG=False
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com

# Database (Option 1: DATABASE_URL)
DATABASE_URL=postgresql://user:pass@host:5432/dbname

# Database (Option 2: Individual settings)
DB_NAME=goodfit_production_db
DB_USER=goodfit_user
DB_PASSWORD=STRONG-PASSWORD
DB_HOST=your-db-host.com
DB_PORT=5432

# Email
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password
DEFAULT_FROM_EMAIL=noreply@yourdomain.com
ADMIN_EMAIL=admin@yourdomain.com

# Redis
REDIS_URL=redis://your-redis-host:6379/1

# CORS
CORS_ALLOWED_ORIGINS=https://yourdomain.com,https://app.yourdomain.com
```

---

## 🎯 Common Commands

### Run Development Server
```bash
export DJANGO_ENV=development
export DJANGO_SETTINGS_MODULE=goodfit_api.settings
python manage.py runserver
```

### Run Production Server (with Gunicorn)
```bash
export DJANGO_ENV=production
export DJANGO_SETTINGS_MODULE=goodfit_api.settings
gunicorn goodfit_api.wsgi:application
```

### Run Migrations
```bash
# Development
export DJANGO_ENV=development
python manage.py migrate

# Production
export DJANGO_ENV=production
python manage.py migrate
```

### Create Superuser
```bash
# Development
export DJANGO_ENV=development
python manage.py createsuperuser

# Production
export DJANGO_ENV=production
python manage.py createsuperuser
```

### Collect Static Files (Production)
```bash
export DJANGO_ENV=production
python manage.py collectstatic --noinput
```

---

## 🔍 Testing Settings

### Check Which Settings Are Loaded
```bash
export DJANGO_ENV=development
python manage.py check
# Output: "🔧 Running in DEVELOPMENT mode"

export DJANGO_ENV=production
python manage.py check
# Output: "🚀 Running in PRODUCTION mode"
```

### Django Shell
```bash
export DJANGO_ENV=development
python manage.py shell

# In shell:
from django.conf import settings
print(settings.DEBUG)  # True
print(settings.DATABASES)
```

---

## 📊 Comparison Table

| Feature | Development | Production |
|---------|-------------|------------|
| **DEBUG** | True | False |
| **ALLOWED_HOSTS** | All (`*`) | Specific domains |
| **CORS** | All origins | Specific origins |
| **Database** | goodfit_dev_db | Production DB |
| **Cache** | Local memory | Redis |
| **Email** | Console | SMTP |
| **Logging** | DEBUG level | WARNING level |
| **API** | Browsable | JSON only |
| **SSL** | Disabled | Required |
| **Secure Cookies** | No | Yes |
| **HSTS** | No | Yes (1 year) |

---

## 🛡️ Security Checklist for Production

Before deploying to production:

- [ ] Change `SECRET_KEY` to a strong random string
- [ ] Set `DEBUG = False`
- [ ] Configure `ALLOWED_HOSTS` with your domains
- [ ] Set up real database (not SQLite)
- [ ] Configure SMTP email settings
- [ ] Set up Redis for caching
- [ ] Configure `CORS_ALLOWED_ORIGINS`
- [ ] Enable HTTPS/SSL
- [ ] Set up error logging (Sentry recommended)
- [ ] Configure static files storage (S3 recommended)
- [ ] Set up database backups
- [ ] Configure firewall rules
- [ ] Enable database encryption
- [ ] Set up monitoring and alerts

---

## 🚨 Common Issues

### Issue: Settings Not Loading
**Symptom:** `ImproperlyConfigured: settings are not configured`

**Solution:**
```bash
# Make sure BOTH variables are set:
export DJANGO_SETTINGS_MODULE=goodfit_api.settings
export DJANGO_ENV=development
```

### Issue: Wrong Environment Loading
**Symptom:** Production running with DEBUG=True

**Solution:**
```bash
# Check environment variable
echo $DJANGO_ENV

# Should output: production
# If not, set it:
export DJANGO_ENV=production
```

### Issue: Database Connection Error
**Symptom:** `OperationalError: could not connect to server`

**Solution:**
- Check if PostgreSQL is running
- Verify database credentials in .env
- Ensure database exists
- Check firewall rules

### Issue: CORS Errors in Production
**Symptom:** `CORS header 'Access-Control-Allow-Origin' missing`

**Solution:**
- Add your frontend domain to `CORS_ALLOWED_ORIGINS` in .env
- Never use `CORS_ALLOW_ALL_ORIGINS = True` in production
- Ensure frontend uses HTTPS in production

---

## 📚 Additional Resources

### Django Settings Best Practices
- [Django Settings Documentation](https://docs.djangoproject.com/en/stable/topics/settings/)
- [12-Factor App Methodology](https://12factor.net/)
- [Django Deployment Checklist](https://docs.djangoproject.com/en/stable/howto/deployment/checklist/)

### Deployment Platforms
- [Heroku](https://devcenter.heroku.com/articles/django-app-configuration)
- [Digital Ocean App Platform](https://docs.digitalocean.com/products/app-platform/)
- [Railway](https://docs.railway.app/deploy/django)
- [AWS Elastic Beanstalk](https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/create-deploy-python-django.html)

---

## ✅ Quick Reference

### Development
```bash
# Start development server
export DJANGO_ENV=development
export DJANGO_SETTINGS_MODULE=goodfit_api.settings
python manage.py runserver

# Features: Debug on, CORS all, browsable API
```

### Production
```bash
# Start production server
export DJANGO_ENV=production
export DJANGO_SETTINGS_MODULE=goodfit_api.settings
gunicorn goodfit_api.wsgi:application --bind 0.0.0.0:8000

# Features: Debug off, CORS restricted, JSON only
```

---

**Note:** Always use `.env` files for sensitive data and never commit them to version control!
