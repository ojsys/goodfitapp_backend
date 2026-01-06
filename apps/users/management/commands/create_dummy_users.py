"""
Management command to create dummy users for testing the matching system
"""

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from apps.users.models import UserGoals, UserStats, UserPreferences
from apps.matching.models import UserProfile
import random

User = get_user_model()


DUMMY_USERS = [
    {
        'email': 'sarah.wilson@example.com',
        'display_name': 'Sarah',
        'first_name': 'Sarah',
        'last_name': 'Wilson',
        'avatar_url': 'https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=400',
        'bio': 'Yoga enthusiast and marathon runner. Love early morning workouts!',
        'online_status': 'online',
        'profile': {
            'age': 28,
            'gender': 'female',
            'location_city': 'San Francisco',
            'location_state': 'CA',
            'latitude': 37.7749,
            'longitude': -122.4194,
            'fitness_level': 'intermediate',
            'favorite_activities': ['Run', 'Yoga', 'Cycle'],
            'fitness_goals': ['Weight Loss', 'Build Endurance', 'Stay Healthy'],
            'looking_for': ['running_buddy', 'yoga_partner'],
            'prompt_question': 'Ask me about my favorite post-run smoothie recipe! 🥤',
        }
    },
    {
        'email': 'mike.johnson@example.com',
        'display_name': 'Mike',
        'first_name': 'Mike',
        'last_name': 'Johnson',
        'avatar_url': 'https://images.unsplash.com/photo-1568602471122-7832951cc4c5?w=400',
        'bio': 'Cyclist and gym rat. Always up for a challenge!',
        'online_status': 'online',
        'profile': {
            'age': 32,
            'gender': 'male',
            'location_city': 'San Francisco',
            'location_state': 'CA',
            'latitude': 37.7849,
            'longitude': -122.4094,
            'fitness_level': 'advanced',
            'favorite_activities': ['Cycle', 'Strength', 'Run'],
            'fitness_goals': ['Build Muscle', 'Improve Speed', 'Competition Prep'],
            'looking_for': ['gym_buddy', 'cycling_partner'],
            'prompt_question': 'Challenge me to a cycling race! 🚴',
        }
    },
    {
        'email': 'emma.davis@example.com',
        'display_name': 'Emma',
        'first_name': 'Emma',
        'last_name': 'Davis',
        'avatar_url': 'https://images.unsplash.com/photo-1438761681033-6461ffad8d80?w=400',
        'bio': 'Swimmer and yoga lover. Finding balance in fitness and life.',
        'online_status': 'offline',
        'profile': {
            'age': 26,
            'gender': 'female',
            'location_city': 'San Francisco',
            'location_state': 'CA',
            'latitude': 37.7649,
            'longitude': -122.4294,
            'fitness_level': 'intermediate',
            'favorite_activities': ['Swim', 'Yoga', 'Walk'],
            'fitness_goals': ['Stay Healthy', 'Flexibility', 'Mental Wellness'],
            'looking_for': ['swimming_partner', 'yoga_partner'],
            'prompt_question': 'Pool sessions or yoga flow? Why not both! 🏊‍♀️🧘',
        }
    },
    {
        'email': 'david.chen@example.com',
        'display_name': 'David',
        'first_name': 'David',
        'last_name': 'Chen',
        'avatar_url': 'https://images.unsplash.com/photo-1547425260-76bcadfb4f2c?w=400',
        'bio': 'Trail runner and outdoor enthusiast. Mountains over gyms any day!',
        'online_status': 'online',
        'profile': {
            'age': 30,
            'gender': 'male',
            'location_city': 'San Francisco',
            'location_state': 'CA',
            'latitude': 37.7949,
            'longitude': -122.3994,
            'fitness_level': 'advanced',
            'favorite_activities': ['Run', 'Cycle', 'Walk'],
            'fitness_goals': ['Build Endurance', 'Trail Running', 'Adventure'],
            'looking_for': ['running_buddy', 'hiking_partner'],
            'prompt_question': 'Let\'s explore new trails together! ⛰️',
        }
    },
    {
        'email': 'lisa.martinez@example.com',
        'display_name': 'Lisa',
        'first_name': 'Lisa',
        'last_name': 'Martinez',
        'avatar_url': 'https://images.unsplash.com/photo-1487412720507-e7ab37603c6f?w=400',
        'bio': 'Strength training coach. Empowering others to be their strongest self!',
        'online_status': 'offline',
        'profile': {
            'age': 29,
            'gender': 'female',
            'location_city': 'San Francisco',
            'location_state': 'CA',
            'latitude': 37.7549,
            'longitude': -122.4394,
            'fitness_level': 'elite',
            'favorite_activities': ['Strength', 'Walk', 'Yoga'],
            'fitness_goals': ['Build Muscle', 'Coaching', 'Community'],
            'looking_for': ['gym_buddy', 'training_partner'],
            'prompt_question': 'Deadlifts and deep talks? I\'m in! 💪',
        }
    },
    {
        'email': 'alex.kim@example.com',
        'display_name': 'Alex',
        'first_name': 'Alex',
        'last_name': 'Kim',
        'avatar_url': 'https://images.unsplash.com/photo-1506794778202-cad84cf45f1d?w=400',
        'bio': 'Triathlete in training. Swim, bike, run, repeat!',
        'online_status': 'online',
        'profile': {
            'age': 27,
            'gender': 'non_binary',
            'location_city': 'San Francisco',
            'location_state': 'CA',
            'latitude': 37.7849,
            'longitude': -122.4294,
            'fitness_level': 'advanced',
            'favorite_activities': ['Swim', 'Cycle', 'Run'],
            'fitness_goals': ['Competition Prep', 'Build Endurance', 'Speed Training'],
            'looking_for': ['triathlon_buddy', 'training_partner'],
            'prompt_question': 'Training for my first Ironman! 🏊🚴🏃',
        }
    },
    {
        'email': 'jessica.brown@example.com',
        'display_name': 'Jessica',
        'first_name': 'Jessica',
        'last_name': 'Brown',
        'avatar_url': 'https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=400',
        'bio': 'Morning walker and meditation enthusiast. Slow and steady wins the race.',
        'online_status': 'offline',
        'profile': {
            'age': 35,
            'gender': 'female',
            'location_city': 'San Francisco',
            'location_state': 'CA',
            'latitude': 37.7449,
            'longitude': -122.4494,
            'fitness_level': 'beginner',
            'favorite_activities': ['Walk', 'Yoga', 'Swim'],
            'fitness_goals': ['Stay Healthy', 'Mental Wellness', 'Consistency'],
            'looking_for': ['walking_buddy', 'accountability_partner'],
            'prompt_question': 'Coffee walk and good vibes? ☕🚶‍♀️',
        }
    },
    {
        'email': 'ryan.patel@example.com',
        'display_name': 'Ryan',
        'first_name': 'Ryan',
        'last_name': 'Patel',
        'avatar_url': 'https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=400',
        'bio': 'CrossFit enthusiast and nutrition nerd. Let\'s get those gains!',
        'online_status': 'online',
        'profile': {
            'age': 31,
            'gender': 'male',
            'location_city': 'San Francisco',
            'location_state': 'CA',
            'latitude': 37.8049,
            'longitude': -122.3894,
            'fitness_level': 'advanced',
            'favorite_activities': ['Strength', 'Run', 'Cycle'],
            'fitness_goals': ['Build Muscle', 'Competition Prep', 'Functional Fitness'],
            'looking_for': ['gym_buddy', 'crossfit_partner'],
            'prompt_question': 'Burpees and PRs? Let\'s gooo! 🔥',
        }
    },
]


class Command(BaseCommand):
    help = 'Create dummy users for testing the matching system'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing dummy users before creating new ones',
        )

    def handle(self, *args, **options):
        if options['clear']:
            self.stdout.write('Clearing existing dummy users...')
            User.objects.filter(email__endswith='@example.com').delete()
            self.stdout.write(self.style.SUCCESS('Cleared existing dummy users'))

        self.stdout.write('Creating dummy users...')

        for user_data in DUMMY_USERS:
            profile_data = user_data.pop('profile')

            # Check if user already exists
            user, created = User.objects.get_or_create(
                email=user_data['email'],
                defaults={
                    'display_name': user_data['display_name'],
                    'first_name': user_data['first_name'],
                    'last_name': user_data['last_name'],
                    'avatar_url': user_data['avatar_url'],
                    'bio': user_data['bio'],
                    'online_status': user_data['online_status'],
                }
            )

            if created:
                # Set a default password
                user.set_password('password123')
                user.save()

                # Create UserGoals
                UserGoals.objects.create(
                    user=user,
                    selected_goals=profile_data['fitness_goals'],
                    daily_step_goal=random.randint(8000, 12000),
                    weekly_workout_goal=random.randint(3, 7),
                    daily_calorie_goal=random.randint(400, 800),
                )

                # Create UserStats
                UserStats.objects.create(
                    user=user,
                    current_streak=random.randint(0, 15),
                    longest_streak=random.randint(5, 30),
                    total_workouts=random.randint(20, 200),
                    total_minutes=random.randint(1000, 10000),
                    total_calories=random.randint(5000, 50000),
                    total_distance=random.uniform(50000, 500000),  # in meters
                )

                # Create UserPreferences
                UserPreferences.objects.create(user=user)

                # Create UserProfile
                UserProfile.objects.create(
                    user=user,
                    age=profile_data['age'],
                    gender=profile_data['gender'],
                    location_city=profile_data['location_city'],
                    location_state=profile_data['location_state'],
                    latitude=profile_data['latitude'],
                    longitude=profile_data['longitude'],
                    fitness_level=profile_data['fitness_level'],
                    favorite_activities=profile_data['favorite_activities'],
                    fitness_goals=profile_data['fitness_goals'],
                    looking_for=profile_data['looking_for'],
                    prompt_question=profile_data['prompt_question'],
                    is_active=True,
                )

                self.stdout.write(
                    self.style.SUCCESS(f'Created user: {user.display_name} ({user.email})')
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f'User already exists: {user.display_name} ({user.email})')
                )

        self.stdout.write(self.style.SUCCESS('\nDummy users creation completed!'))
        self.stdout.write(self.style.SUCCESS(f'Total users: {User.objects.count()}'))
        self.stdout.write(self.style.SUCCESS('\nYou can now test the matching system!'))
