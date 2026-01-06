"""
Matching Views for GoodFit API
Views for discovering users, swiping, and managing matches
"""

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q, Exists, OuterRef
from django.contrib.auth import get_user_model

from apps.matching.models import UserProfile, Swipe, Match
from apps.matching.serializers import (
    UserProfileSerializer,
    UserProfileCreateUpdateSerializer,
    MatchedUserSerializer,
    SwipeSerializer,
    SwipeCreateSerializer,
    MatchSerializer,
)

User = get_user_model()


class UserProfileViewSet(viewsets.ModelViewSet):
    """
    ViewSet for user matching profiles
    """
    permission_classes = [IsAuthenticated]
    serializer_class = UserProfileSerializer

    def get_queryset(self):
        """Get user profiles"""
        return UserProfile.objects.filter(user=self.request.user)

    def get_serializer_class(self):
        """Use different serializer for create/update"""
        if self.action in ['create', 'update', 'partial_update']:
            return UserProfileCreateUpdateSerializer
        return UserProfileSerializer

    @action(detail=False, methods=['get'])
    def me(self, request):
        """Get current user's profile"""
        try:
            profile = UserProfile.objects.get(user=request.user)
            serializer = self.get_serializer(profile)
            return Response(serializer.data)
        except UserProfile.DoesNotExist:
            return Response(
                {'error': 'Profile not found. Please create your profile first.'},
                status=status.HTTP_404_NOT_FOUND
            )

    @action(detail=False, methods=['post', 'put'])
    def update_my_profile(self, request):
        """Create or update current user's profile"""
        try:
            profile = UserProfile.objects.get(user=request.user)
            serializer = UserProfileCreateUpdateSerializer(profile, data=request.data, partial=True)
        except UserProfile.DoesNotExist:
            serializer = UserProfileCreateUpdateSerializer(data=request.data)

        if serializer.is_valid():
            if hasattr(serializer, 'instance') and serializer.instance:
                # Update existing
                serializer.save()
            else:
                # Create new
                serializer.save(user=request.user)

            # Return full profile data
            profile = UserProfile.objects.get(user=request.user)
            return Response(UserProfileSerializer(profile).data)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'])
    def discover(self, request):
        """
        Discover compatible users for matching
        Implements matching algorithm based on:
        - Distance
        - Age preferences
        - Gender preferences
        - Fitness level compatibility
        - Shared activities/goals
        """
        try:
            current_profile = UserProfile.objects.get(user=request.user)
        except UserProfile.DoesNotExist:
            return Response(
                {'error': 'Please complete your profile first'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get users already swiped on
        swiped_user_ids = Swipe.objects.filter(from_user=request.user).values_list('to_user_id', flat=True)

        # Start with active profiles excluding current user and already swiped
        queryset = UserProfile.objects.filter(
            is_active=True
        ).exclude(
            user=request.user
        ).exclude(
            user_id__in=swiped_user_ids
        )

        # Filter by gender preferences
        if current_profile.preferred_gender:
            queryset = queryset.filter(gender__in=current_profile.preferred_gender)

        # Filter by age preferences
        queryset = queryset.filter(
            age__gte=current_profile.preferred_age_min,
            age__lte=current_profile.preferred_age_max
        )

        # Filter by mutual age preference
        queryset = queryset.filter(
            preferred_age_min__lte=current_profile.age if current_profile.age else 100,
            preferred_age_max__gte=current_profile.age if current_profile.age else 18
        )

        # Filter by distance if location is available
        if current_profile.latitude and current_profile.longitude:
            # Note: For production, use PostGIS for efficient geo queries
            # For now, we'll fetch and filter in Python
            profiles = list(queryset)
            filtered_profiles = []

            for profile in profiles:
                distance = profile.distance_from(current_profile.latitude, current_profile.longitude)
                if distance is not None and distance <= current_profile.preferred_distance_miles:
                    filtered_profiles.append(profile)

            # Score and sort by compatibility
            scored_profiles = []
            for profile in filtered_profiles:
                score = self._calculate_compatibility_score(current_profile, profile)
                scored_profiles.append((profile, score))

            # Sort by score (highest first)
            scored_profiles.sort(key=lambda x: x[1], reverse=True)

            # Return top matches
            top_profiles = [p[0] for p in scored_profiles[:50]]
            serializer = MatchedUserSerializer(top_profiles, many=True, context={'request': request})
            return Response(serializer.data)

        else:
            # No location - just return recent profiles
            queryset = queryset.order_by('-created_at')[:50]
            serializer = MatchedUserSerializer(queryset, many=True, context={'request': request})
            return Response(serializer.data)

    def _calculate_compatibility_score(self, profile1, profile2):
        """
        Calculate compatibility score between two profiles
        Higher score = better match
        """
        score = 0

        # Shared favorite activities (high weight)
        shared_activities = set(profile1.favorite_activities) & set(profile2.favorite_activities)
        score += len(shared_activities) * 10

        # Shared fitness goals (medium weight)
        shared_goals = set(profile1.fitness_goals) & set(profile2.fitness_goals)
        score += len(shared_goals) * 5

        # Shared "looking for" (medium weight)
        shared_looking_for = set(profile1.looking_for) & set(profile2.looking_for)
        score += len(shared_looking_for) * 5

        # Fitness level compatibility (lower weight)
        fitness_levels = {'beginner': 1, 'intermediate': 2, 'advanced': 3, 'elite': 4}
        level_diff = abs(fitness_levels.get(profile1.fitness_level, 1) - fitness_levels.get(profile2.fitness_level, 1))
        if level_diff == 0:
            score += 5  # Same level
        elif level_diff == 1:
            score += 3  # One level apart
        # else: 0 points for 2+ levels apart

        # Distance bonus (closer is better)
        if profile1.latitude and profile2.latitude:
            distance = profile2.distance_from(profile1.latitude, profile1.longitude)
            if distance is not None:
                if distance < 5:
                    score += 8  # Very close
                elif distance < 10:
                    score += 5  # Close
                elif distance < 20:
                    score += 2  # Moderate

        return score


class SwipeViewSet(viewsets.ModelViewSet):
    """
    ViewSet for swipes (likes/passes)
    """
    permission_classes = [IsAuthenticated]
    serializer_class = SwipeSerializer

    def get_queryset(self):
        """Get swipes made by current user"""
        return Swipe.objects.filter(from_user=self.request.user)

    def get_serializer_class(self):
        """Use different serializer for create"""
        if self.action == 'create':
            return SwipeCreateSerializer
        return SwipeSerializer

    def create(self, request, *args, **kwargs):
        """Create a swipe and check for mutual match"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        swipe = serializer.save()

        # Check if this created a match
        is_match = Match.objects.filter(
            Q(user1=request.user, user2=swipe.to_user) | Q(user1=swipe.to_user, user2=request.user),
            is_active=True
        ).exists()

        response_data = SwipeSerializer(swipe).data
        response_data['is_match'] = is_match

        if is_match:
            # Get the match details
            match = Match.objects.filter(
                Q(user1=request.user, user2=swipe.to_user) | Q(user1=swipe.to_user, user2=request.user),
                is_active=True
            ).first()
            response_data['match'] = MatchSerializer(match, context={'request': request}).data

        return Response(response_data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'])
    def my_likes(self, request):
        """Get users that current user has liked"""
        likes = Swipe.objects.filter(from_user=request.user, action='like')
        serializer = self.get_serializer(likes, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def likes_received(self, request):
        """Get users that have liked current user"""
        likes = Swipe.objects.filter(to_user=request.user, action='like')
        serializer = self.get_serializer(likes, many=True)
        return Response(serializer.data)


class MatchViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for matches
    """
    permission_classes = [IsAuthenticated]
    serializer_class = MatchSerializer

    def get_queryset(self):
        """Get matches for current user"""
        return Match.objects.filter(
            Q(user1=self.request.user) | Q(user2=self.request.user),
            is_active=True
        ).order_by('-matched_at')

    @action(detail=True, methods=['post'])
    def unmatch(self, request, pk=None):
        """Unmatch with a user"""
        match = self.get_object()

        # Verify current user is part of this match
        if request.user not in [match.user1, match.user2]:
            return Response(
                {'error': 'You are not part of this match'},
                status=status.HTTP_403_FORBIDDEN
            )

        match.unmatch(request.user)

        return Response(
            {'message': 'Successfully unmatched'},
            status=status.HTTP_200_OK
        )

    @action(detail=False, methods=['get'])
    def recent(self, request):
        """Get recent matches (last 7 days)"""
        from django.utils import timezone
        from datetime import timedelta

        seven_days_ago = timezone.now() - timedelta(days=7)
        recent_matches = self.get_queryset().filter(matched_at__gte=seven_days_ago)

        serializer = self.get_serializer(recent_matches, many=True)
        return Response(serializer.data)
