# GoodFit Django Backend API

A robust Django REST API backend for the GoodFit fitness tracking application.

## 🚀 Features

- **JWT Authentication** - Secure token-based authentication
- **User Management** - Complete user profile, goals, stats, and preferences
- **Activity Tracking** - Log workouts with GPS route tracking
- **Daily Summaries** - Track daily metrics and goal progress
- **RESTful API** - Clean, well-documented API endpoints
- **Admin Panel** - Django admin for easy data management

---

## 📋 Prerequisites

Before you begin, ensure you have the following installed:

- **Python 3.10+** - [Download Python](https://www.python.org/downloads/)
- **PostgreSQL 14+** - [Download PostgreSQL](https://www.postgresql.org/download/)
- **pip** - Python package manager (comes with Python)
- **virtualenv** - For creating isolated Python environments

---

## 🛠️ Installation & Setup

### 1. Create Virtual Environment

```bash
# Navigate to backend directory
cd backend

# Create virtual environment
python -m venv venv

# Activate virtual environment
# On macOS/Linux:
source venv/bin/activate

# On Windows:
venv\Scripts\activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Setup PostgreSQL Database

```bash
# Login to PostgreSQL
psql postgres

# Create database
CREATE DATABASE goodfit_db;

# Create user (optional, or use existing postgres user)
CREATE USER goodfit_user WITH PASSWORD 'your_password';

# Grant privileges
GRANT ALL PRIVILEGES ON DATABASE goodfit_db TO goodfit_user;

# Exit PostgreSQL
\q
```

### 4. Configure Environment Variables

```bash
# Copy example env file
cp .env.example .env

# Edit .env file with your settings
nano .env
```

**Required environment variables:**
```
SECRET_KEY=your-secret-key-here
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

DB_NAME=goodfit_db
DB_USER=postgres
DB_PASSWORD=your_password
DB_HOST=localhost
DB_PORT=5432
```

**Generate a secure SECRET_KEY:**
```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### 5. Run Migrations

```bash
# Make migrations
python manage.py makemigrations

# Apply migrations
python manage.py migrate
```

### 6. Create Superuser

```bash
python manage.py createsuperuser
```

Follow the prompts to create an admin account.

### 7. Run Development Server

```bash
python manage.py runserver
```

The API will be available at: `http://localhost:8000`

---

## 📚 API Documentation

### Interactive API Docs

Once the server is running, visit:

- **Swagger UI**: http://localhost:8000/swagger/
- **ReDoc**: http://localhost:8000/redoc/
- **Django Admin**: http://localhost:8000/admin/

### Authentication Endpoints

#### Register
```http
POST /api/auth/register/
Content-Type: application/json

{
  "email": "user@example.com",
  "display_name": "John Doe",
  "password": "securepassword123",
  "password_confirm": "securepassword123"
}
```

**Response:**
```json
{
  "user": {
    "id": 1,
    "email": "user@example.com",
    "display_name": "John Doe",
    "goals": {...},
    "stats": {...},
    "preferences": {...}
  },
  "tokens": {
    "refresh": "...",
    "access": "..."
  },
  "message": "Registration successful"
}
```

#### Login
```http
POST /api/auth/login/
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "securepassword123"
}
```

#### Logout
```http
POST /api/auth/logout/
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "refresh_token": "<refresh_token>"
}
```

#### Refresh Token
```http
POST /api/auth/token/refresh/
Content-Type: application/json

{
  "refresh": "<refresh_token>"
}
```

### User Endpoints

#### Get Profile
```http
GET /api/auth/profile/
Authorization: Bearer <access_token>
```

#### Update Profile
```http
PATCH /api/auth/profile/update/
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "display_name": "New Name",
  "bio": "Fitness enthusiast"
}
```

#### Get/Update Goals
```http
GET /api/auth/goals/
PATCH /api/auth/goals/
Authorization: Bearer <access_token>
```

#### Get Stats
```http
GET /api/auth/stats/
Authorization: Bearer <access_token>
```

#### Get/Update Preferences
```http
GET /api/auth/preferences/
PATCH /api/auth/preferences/
Authorization: Bearer <access_token>
```

### Activity Endpoints

#### List Activities
```http
GET /api/activities/
Authorization: Bearer <access_token>

# Optional query parameters:
?type=Cycle
?start_date=2024-01-01
?end_date=2024-12-31
```

#### Create Activity
```http
POST /api/activities/
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "type": "Cycle",
  "title": "Morning Ride",
  "start_time": "2024-01-02T08:00:00Z",
  "duration": 60,
  "distance": 15000,
  "calories_burned": 450,
  "route": [
    {"latitude": 37.7749, "longitude": -122.4194, "altitude": 10},
    ...
  ]
}
```

#### Get Activity Detail
```http
GET /api/activities/<id>/
Authorization: Bearer <access_token>
```

#### Update Activity
```http
PATCH /api/activities/<id>/
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "notes": "Great ride today!"
}
```

#### Delete Activity
```http
DELETE /api/activities/<id>/
Authorization: Bearer <access_token>
```

#### Get Recent Activities
```http
GET /api/activities/recent/
Authorization: Bearer <access_token>
```

#### Get Activity Stats
```http
GET /api/activities/stats/
Authorization: Bearer <access_token>

# Optional: specify days
?days=30
```

---

## 🗄️ Database Models

### User
- Email-based authentication
- Profile information (display name, avatar, bio)
- Online status tracking
- Related models: UserGoals, UserStats, UserPreferences

### Activity
- Activity type (Run, Cycle, Walk, Swim, Yoga, Strength)
- Time tracking (start, end, duration)
- Performance metrics (distance, speed, pace, elevation)
- GPS route data (JSON array of coordinates)
- Automatic stats updating

### DailySummary
- Daily totals (steps, distance, calories, active minutes)
- Goal progress tracking
- Automatic calculation

---

## 🧪 Testing

### Run Tests
```bash
python manage.py test
```

### Create Test Data
```bash
# Create some test activities
python manage.py shell

from apps.users.models import User
from apps.activities.models import Activity
from datetime import datetime, timedelta
from django.utils import timezone

user = User.objects.first()

# Create a cycling activity
Activity.objects.create(
    user=user,
    type='Cycle',
    title='Morning Ride',
    start_time=timezone.now(),
    duration=60,
    distance=15000,
    calories_burned=450
)
```

---

## 🔒 Security Notes

### Production Checklist

1. **Change SECRET_KEY** - Generate a strong, unique secret key
2. **Set DEBUG=False** - Disable debug mode in production
3. **Configure ALLOWED_HOSTS** - Set to your domain names
4. **Use HTTPS** - Enable SSL/TLS encryption
5. **Secure Database** - Use strong passwords and restrict access
6. **Environment Variables** - Never commit .env file to version control
7. **CORS Settings** - Update CORS_ALLOWED_ORIGINS for your frontend domain

### JWT Token Security

- Access tokens expire after 7 days
- Refresh tokens expire after 30 days
- Tokens are automatically rotated on refresh
- Blacklisting enabled for revoked tokens

---

## 📦 Project Structure

```
backend/
├── goodfit_api/          # Main Django project
│   ├── settings.py       # Project settings
│   ├── urls.py           # URL routing
│   ├── wsgi.py           # WSGI application
│   └── asgi.py           # ASGI application
├── apps/
│   ├── users/            # User authentication & management
│   │   ├── models.py     # User, UserGoals, UserStats, UserPreferences
│   │   ├── serializers.py
│   │   ├── views.py
│   │   ├── urls.py
│   │   └── admin.py
│   └── activities/       # Activity tracking
│       ├── models.py     # Activity, DailySummary
│       ├── serializers.py
│       ├── views.py
│       ├── urls.py
│       └── admin.py
├── manage.py
├── requirements.txt
└── .env.example
```

---

## 🚀 Deployment

### Using Gunicorn (Production Server)

```bash
# Install Gunicorn
pip install gunicorn

# Run with Gunicorn
gunicorn goodfit_api.wsgi:application --bind 0.0.0.0:8000
```

### Using Docker (Optional)

Create `Dockerfile`:
```dockerfile
FROM python:3.10-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

CMD ["gunicorn", "goodfit_api.wsgi:application", "--bind", "0.0.0.0:8000"]
```

---

## 🐛 Troubleshooting

### Database Connection Error
```
django.db.utils.OperationalError: could not connect to server
```
**Solution:** Ensure PostgreSQL is running and credentials are correct in .env

### Migration Errors
```bash
# Reset migrations (development only)
python manage.py migrate --fake
python manage.py migrate
```

### JWT Token Errors
```
Authentication credentials were not provided
```
**Solution:** Include Authorization header: `Bearer <access_token>`

---

## 📝 License

MIT License - See LICENSE file for details

---

## 💡 Support

For issues or questions:
- Open an issue on GitHub
- Check API documentation at /swagger/
- Review Django logs for errors

---

**Happy Coding! 🚴‍♂️💪**
