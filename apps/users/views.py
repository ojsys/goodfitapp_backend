"""
Views for User authentication and management
"""

from rest_framework import generics, status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model
from google.oauth2 import id_token
from google.auth.transport import requests

from .serializers import (
    RegisterSerializer, LoginSerializer, UserProfileSerializer,
    ChangePasswordSerializer, UpdateProfileSerializer,
    UserGoalsSerializer, UserStatsSerializer, UserPreferencesSerializer
)
from .models import UserGoals, UserStats, UserPreferences

User = get_user_model()


class RegisterView(generics.CreateAPIView):
    """User registration endpoint"""

    permission_classes = [permissions.AllowAny]
    serializer_class = RegisterSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        # Generate tokens
        refresh = RefreshToken.for_user(user)

        # Get user profile
        profile_serializer = UserProfileSerializer(user)

        return Response({
            'user': profile_serializer.data,
            'tokens': {
                'refresh': str(refresh),
                'access': str(refresh.access_token),
            },
            'message': 'Registration successful'
        }, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    """User login endpoint"""

    permission_classes = [permissions.AllowAny]
    serializer_class = LoginSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data['user']

        # Update online status
        user.online_status = 'online'
        user.save()

        # Generate tokens
        refresh = RefreshToken.for_user(user)

        # Get user profile
        profile_serializer = UserProfileSerializer(user)

        return Response({
            'user': profile_serializer.data,
            'tokens': {
                'refresh': str(refresh),
                'access': str(refresh.access_token),
            },
            'message': 'Login successful'
        }, status=status.HTTP_200_OK)


class LogoutView(APIView):
    """User logout endpoint"""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        try:
            # Update online status
            request.user.online_status = 'offline'
            request.user.save()

            # Blacklist refresh token
            refresh_token = request.data.get('refresh_token')
            if refresh_token:
                token = RefreshToken(refresh_token)
                token.blacklist()

            return Response({
                'message': 'Logout successful'
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({
                'error': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)


class ProfileView(generics.RetrieveUpdateAPIView):
    """Get and update user profile"""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = UserProfileSerializer

    def get_object(self):
        return self.request.user


class UpdateProfileView(generics.UpdateAPIView):
    """Update user profile information"""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = UpdateProfileSerializer

    def get_object(self):
        return self.request.user


class ChangePasswordView(APIView):
    """Change user password"""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response({
            'message': 'Password changed successfully'
        }, status=status.HTTP_200_OK)


class UserGoalsView(generics.RetrieveUpdateAPIView):
    """Get and update user goals"""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = UserGoalsSerializer

    def get_object(self):
        goals, created = UserGoals.objects.get_or_create(user=self.request.user)
        return goals


class UserStatsView(generics.RetrieveAPIView):
    """Get user statistics"""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = UserStatsSerializer

    def get_object(self):
        stats, created = UserStats.objects.get_or_create(user=self.request.user)
        return stats


class UserPreferencesView(generics.RetrieveUpdateAPIView):
    """Get and update user preferences"""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = UserPreferencesSerializer

    def get_object(self):
        preferences, created = UserPreferences.objects.get_or_create(user=self.request.user)
        return preferences


class OnlineStatusView(APIView):
    """Update user online status"""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        status_value = request.data.get('status', 'online')

        if status_value not in ['online', 'offline', 'away']:
            return Response({
                'error': 'Invalid status. Must be online, offline, or away'
            }, status=status.HTTP_400_BAD_REQUEST)

        request.user.online_status = status_value
        request.user.save()

        return Response({
            'message': f'Status updated to {status_value}',
            'status': status_value
        }, status=status.HTTP_200_OK)


class GoogleLoginView(APIView):
    """Google Sign-In authentication endpoint"""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        """
        Authenticate user with Google ID token
        Expected request body: {"id_token": "google_id_token_here"}
        """
        google_id_token = request.data.get('id_token')

        if not google_id_token:
            return Response({
                'error': 'Google ID token is required'
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Verify the Google ID token
            # Note: In production, you should specify your Google OAuth client ID
            # For now, we'll skip client ID verification for local development
            idinfo = id_token.verify_oauth2_token(
                google_id_token,
                requests.Request()
            )

            # Extract user information from Google token
            google_id = idinfo.get('sub')
            email = idinfo.get('email')
            first_name = idinfo.get('given_name', '')
            last_name = idinfo.get('family_name', '')
            profile_picture = idinfo.get('picture')

            if not email:
                return Response({
                    'error': 'Email not provided by Google'
                }, status=status.HTTP_400_BAD_REQUEST)

            # Get or create user
            user, created = User.objects.get_or_create(
                email=email,
                defaults={
                    'display_name': f"{first_name} {last_name}".strip() or email.split('@')[0],
                    'first_name': first_name,
                    'last_name': last_name,
                }
            )

            # For Google Sign-In users, set a random unusable password if newly created
            if created:
                user.set_unusable_password()
                user.save()

            # Update profile picture if provided and user doesn't have one
            if profile_picture and not user.avatar_url:
                user.avatar_url = profile_picture
                user.save()

            # Update online status
            user.online_status = 'online'
            user.save()

            # Generate JWT tokens
            refresh = RefreshToken.for_user(user)

            # Get user profile
            profile_serializer = UserProfileSerializer(user)

            return Response({
                'user': profile_serializer.data,
                'tokens': {
                    'refresh': str(refresh),
                    'access': str(refresh.access_token),
                },
                'message': 'Google login successful',
                'is_new_user': created
            }, status=status.HTTP_200_OK)

        except ValueError as e:
            # Invalid token
            return Response({
                'error': f'Invalid Google token: {str(e)}'
            }, status=status.HTTP_401_UNAUTHORIZED)
        except Exception as e:
            return Response({
                'error': f'Authentication failed: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
