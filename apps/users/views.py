"""
Views for User authentication and management
"""

from rest_framework import generics, status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model

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
