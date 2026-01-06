"""
Messaging Views for GoodFit API
Views for conversations and messages
"""

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q, Count, Max
from django.shortcuts import get_object_or_404

from apps.messaging.models import Conversation, Message, MessageReadReceipt
from apps.messaging.serializers import (
    ConversationSerializer,
    ConversationDetailSerializer,
    ConversationCreateSerializer,
    MessageSerializer,
    MessageCreateSerializer,
)


class ConversationViewSet(viewsets.ModelViewSet):
    """
    ViewSet for conversations
    """
    permission_classes = [IsAuthenticated]
    serializer_class = ConversationSerializer

    def get_queryset(self):
        """Get conversations for current user"""
        user = self.request.user
        return Conversation.objects.filter(
            Q(participant1=user) | Q(participant2=user),
            is_active=True
        ).select_related(
            'participant1',
            'participant2',
            'last_message_sender'
        )

    def get_serializer_class(self):
        """Use different serializer for detail view and create"""
        if self.action == 'retrieve':
            return ConversationDetailSerializer
        elif self.action == 'create':
            return ConversationCreateSerializer
        return ConversationSerializer

    def create(self, request, *args, **kwargs):
        """Create or get a conversation with another user"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        conversation = serializer.save()

        # Return conversation details
        output_serializer = ConversationDetailSerializer(conversation, context={'request': request})
        return Response(output_serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def mark_as_read(self, request, pk=None):
        """Mark all messages in conversation as read"""
        conversation = self.get_object()

        # Verify user is participant
        if request.user not in [conversation.participant1, conversation.participant2]:
            return Response(
                {'error': 'You are not a participant in this conversation'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Mark all unread messages from other user as read
        unread_messages = conversation.messages.filter(is_read=False).exclude(sender=request.user)
        count = 0
        for message in unread_messages:
            message.mark_as_read()
            count += 1

        # Update or create read receipt
        receipt, created = MessageReadReceipt.objects.get_or_create(
            conversation=conversation,
            user=request.user
        )
        last_message = conversation.messages.last()
        if last_message:
            receipt.last_read_message = last_message
            receipt.save()

        return Response({
            'message': f'Marked {count} messages as read',
            'count': count
        })

    @action(detail=False, methods=['get'])
    def unread_count(self, request):
        """Get total unread message count across all conversations"""
        user = request.user
        conversations = self.get_queryset()

        total_unread = 0
        for conversation in conversations:
            unread = conversation.messages.filter(is_read=False).exclude(sender=user).count()
            total_unread += unread

        return Response({'unread_count': total_unread})


class MessageViewSet(viewsets.ModelViewSet):
    """
    ViewSet for messages
    """
    permission_classes = [IsAuthenticated]
    serializer_class = MessageSerializer

    def get_queryset(self):
        """Get messages for conversations user is part of"""
        user = self.request.user

        # Get conversation ID from query params
        conversation_id = self.request.query_params.get('conversation')

        queryset = Message.objects.select_related('sender', 'conversation')

        if conversation_id:
            # Verify user is participant in this conversation
            try:
                conversation = Conversation.objects.get(
                    id=conversation_id,
                    is_active=True
                )
                if user not in [conversation.participant1, conversation.participant2]:
                    return Message.objects.none()

                queryset = queryset.filter(conversation_id=conversation_id)
            except Conversation.DoesNotExist:
                return Message.objects.none()
        else:
            # Get all messages from user's conversations
            user_conversations = Conversation.objects.filter(
                Q(participant1=user) | Q(participant2=user),
                is_active=True
            ).values_list('id', flat=True)

            queryset = queryset.filter(conversation_id__in=user_conversations)

        return queryset.order_by('-created_at')

    def get_serializer_class(self):
        """Use different serializer for create"""
        if self.action == 'create':
            return MessageCreateSerializer
        return MessageSerializer

    def create(self, request, *args, **kwargs):
        """Send a message"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Verify user is participant in the conversation
        conversation_id = serializer.validated_data['conversation'].id
        try:
            conversation = Conversation.objects.get(id=conversation_id)
            if request.user not in [conversation.participant1, conversation.participant2]:
                return Response(
                    {'error': 'You are not a participant in this conversation'},
                    status=status.HTTP_403_FORBIDDEN
                )
        except Conversation.DoesNotExist:
            return Response(
                {'error': 'Conversation not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        message = serializer.save()

        # Return message details
        output_serializer = MessageSerializer(message, context={'request': request})
        return Response(output_serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def mark_read(self, request, pk=None):
        """Mark a specific message as read"""
        message = self.get_object()

        # Can only mark messages you received as read
        if message.sender == request.user:
            return Response(
                {'error': 'Cannot mark your own message as read'},
                status=status.HTTP_400_BAD_REQUEST
            )

        message.mark_as_read()

        return Response({'message': 'Message marked as read'})

    @action(detail=False, methods=['post'])
    def send(self, request):
        """
        Send a message to a conversation
        Alternative endpoint with cleaner interface
        """
        conversation_id = request.data.get('conversation_id')
        text = request.data.get('text')
        message_type = request.data.get('message_type', 'text')

        if not conversation_id or not text:
            return Response(
                {'error': 'conversation_id and text are required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            conversation = Conversation.objects.get(id=conversation_id)
            if request.user not in [conversation.participant1, conversation.participant2]:
                return Response(
                    {'error': 'You are not a participant in this conversation'},
                    status=status.HTTP_403_FORBIDDEN
                )
        except Conversation.DoesNotExist:
            return Response(
                {'error': 'Conversation not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        message = Message.objects.create(
            conversation=conversation,
            sender=request.user,
            text=text,
            message_type=message_type
        )

        serializer = MessageSerializer(message, context={'request': request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)
