# GoodFit API - Render Deployment Guide

## Prerequisites
- A Render account (https://render.com)
- Your GitHub repository with the backend code

## Deployment Steps

### 1. Push Code to GitHub
Make sure all your code is committed and pushed to GitHub.

### 2. Create New Web Service on Render

1. Log in to Render
2. Click "New +" and select "Web Service"
3. Connect your GitHub repository
4. Configure the service:
   - **Name**: goodfit-api (or your preferred name)
   - **Region**: Choose closest to your users
   - **Branch**: main
   - **Root Directory**: backend
   - **Runtime**: Python 3
   - **Build Command**: `./build.sh`
   - **Start Command**: `gunicorn goodfit_api.wsgi:application`

### 3. Set Environment Variables

In the Render dashboard, add these environment variables:

**Required:**
- `DJANGO_SETTINGS_MODULE` = `goodfit_api.settings.production`
- `SECRET_KEY` = (Generate a secure random key)
- `PYTHON_VERSION` = `3.14.0`
- `DJANGO_DEBUG` = `False`

**Optional:**
- `ALLOWED_HOSTS` = `your-app-name.onrender.com`
- `CORS_ALLOW_ALL_ORIGINS` = `True`

### 4. Create PostgreSQL Database

1. In Render, click "New +" and select "PostgreSQL"
2. Name it `goodfit-db`
3. Select the free plan (or paid for production)
4. Note the database connection details

### 5. Link Database to Web Service

1. Go to your web service settings
2. Add environment variable:
   - `DATABASE_URL` = (Copy from your PostgreSQL database info)

Or use Render's auto-linking feature in the web service settings.

### 6. Deploy

1. Render will automatically deploy when you push to GitHub
2. First deployment may take 5-10 minutes
3. Monitor the build logs for any errors

### 7. Run Initial Migrations

After first deployment, use Render Shell to run:

```bash
python manage.py migrate
python manage.py createsuperuser
```

### 8. Test Your API

Visit your Render URL:
- Landing page: `https://your-app-name.onrender.com/`
- API docs: `https://your-app-name.onrender.com/swagger/`
- Admin: `https://your-app-name.onrender.com/admin/`

## Updating Environment Variables

To update environment variables after deployment:
1. Go to your web service dashboard
2. Click "Environment"
3. Add/edit variables
4. Service will automatically redeploy

## Monitoring

- **Logs**: Available in Render dashboard under "Logs" tab
- **Metrics**: View CPU, memory usage in "Metrics" tab
- **Health Checks**: Render automatically monitors your service

## Common Issues

### Build Fails
- Check Python version matches requirements
- Ensure all dependencies are in requirements.txt
- Review build logs for specific errors

### Database Connection Errors
- Verify DATABASE_URL is correctly set
- Check database is running
- Ensure migrations were run

### Static Files Not Loading
- WhiteNoise should handle this automatically
- Verify `collectstatic` ran in build.sh
- Check STATIC_ROOT and STATIC_URL settings

## Production Checklist

- [ ] SECRET_KEY is a strong random value
- [ ] DEBUG = False
- [ ] ALLOWED_HOSTS configured
- [ ] Database backups enabled
- [ ] HTTPS enabled (automatic on Render)
- [ ] Environment variables secured
- [ ] Migrations run successfully
- [ ] Superuser created
- [ ] Test all API endpoints

## Support

For issues:
- Check Render docs: https://render.com/docs
- Review Django deployment guide: https://docs.djangoproject.com/en/stable/howto/deployment/

