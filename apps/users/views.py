"""
Views for User authentication and management
"""

from rest_framework import generics, status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model

from .serializers import (
    UserProfileSerializer,
    ChangePasswordSerializer, UpdateProfileSerializer,
    UserGoalsSerializer, UserStatsSerializer, UserPreferencesSerializer
)
from .models import UserGoals, UserStats, UserPreferences

User = get_user_model()


class LogoutView(APIView):
    """User logout endpoint"""

    permission_classes = [permissions.IsAuthenticated]
    # Usable mid-sign-up (resume, photo step, log out).
    allow_pending_member = True

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
    # Usable mid-sign-up (resume, photo step, log out).
    allow_pending_member = True
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


class AvatarUploadView(APIView):
    """Upload or remove the signed-in user's profile photo.

    POST with multipart form-data under `avatar`. DELETE removes the current
    photo. Responds with the resolved `photo_url` so the client can show the
    new image straight away.
    """

    permission_classes = [permissions.IsAuthenticated]
    # Usable mid-sign-up (resume, photo step, log out).
    allow_pending_member = True
    parser_classes = [MultiPartParser, FormParser]

    MAX_BYTES = 5 * 1024 * 1024
    ALLOWED_TYPES = {'image/jpeg', 'image/png', 'image/heic', 'image/webp'}

    def post(self, request):
        upload = request.FILES.get('avatar')
        if upload is None:
            return Response(
                {'detail': 'No file was provided under "avatar".'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if upload.size > self.MAX_BYTES:
            return Response(
                {'detail': 'Image must be 5 MB or smaller.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        content_type = (upload.content_type or '').lower()
        if content_type not in self.ALLOWED_TYPES:
            return Response(
                {'detail': 'Use a JPEG, PNG, WebP or HEIC image.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = request.user
        # Drop the previous file so uploads do not pile up in media storage.
        if user.avatar:
            user.avatar.delete(save=False)

        user.avatar = upload
        user.save(update_fields=['avatar', 'updated_at'])

        return Response(
            {'photo_url': user.photo_url(request)},
            status=status.HTTP_200_OK,
        )

    def delete(self, request):
        user = request.user
        if user.avatar:
            user.avatar.delete(save=False)
            user.avatar = None
            user.save(update_fields=['avatar', 'updated_at'])
        return Response({'photo_url': user.photo_url(request)})
