"""
Messaging Serializers for GoodFit API
"""

from rest_framework import serializers
from django.contrib.auth import get_user_model
from apps.messaging.models import Conversation, Message, MessageReadReceipt

User = get_user_model()


class MessageSerializer(serializers.ModelSerializer):
    """Serializer for messages"""

    sender_name = serializers.CharField(source='sender.display_name', read_only=True)
    sender_photo = serializers.CharField(source='sender.profile_photo', read_only=True)
    is_mine = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = [
            'id',
            'conversation',
            'sender',
            'sender_name',
            'sender_photo',
            'text',
            'message_type',
            'is_read',
            'read_at',
            'is_mine',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'sender', 'sender_name', 'sender_photo', 'is_read', 'read_at', 'created_at', 'updated_at']

    def get_is_mine(self, obj):
        """Check if message was sent by current user"""
        request = self.context.get('request')
        if request and request.user:
            return obj.sender == request.user
        return False


class MessageCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating messages"""

    class Meta:
        model = Message
        fields = ['conversation', 'text', 'message_type']

    def create(self, validated_data):
        """Create message with current user as sender"""
        request = self.context.get('request')
        validated_data['sender'] = request.user
        return super().create(validated_data)


class ConversationSerializer(serializers.ModelSerializer):
    """Serializer for conversations"""

    participant1_name = serializers.CharField(source='participant1.display_name', read_only=True)
    participant1_photo = serializers.CharField(source='participant1.profile_photo', read_only=True)
    participant2_name = serializers.CharField(source='participant2.display_name', read_only=True)
    participant2_photo = serializers.CharField(source='participant2.profile_photo', read_only=True)

    other_participant = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()
    last_message_is_mine = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            'id',
            'participant1',
            'participant1_name',
            'participant1_photo',
            'participant2',
            'participant2_name',
            'participant2_photo',
            'other_participant',
            'match',
            'is_active',
            'last_message_text',
            'last_message_at',
            'last_message_is_mine',
            'unread_count',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_other_participant(self, obj):
        """Get the other participant's details"""
        request = self.context.get('request')
        if request and request.user:
            other = obj.get_other_participant(request.user)
            return {
                'id': other.id,
                'display_name': other.display_name,
                'profile_photo': other.profile_photo,
            }
        return None

    def get_unread_count(self, obj):
        """Get count of unread messages for current user"""
        request = self.context.get('request')
        if request and request.user:
            return obj.messages.filter(is_read=False).exclude(sender=request.user).count()
        return 0

    def get_last_message_is_mine(self, obj):
        """Check if last message was sent by current user"""
        request = self.context.get('request')
        if request and request.user and obj.last_message_sender:
            return obj.last_message_sender == request.user
        return False


class ConversationDetailSerializer(ConversationSerializer):
    """Detailed conversation serializer with recent messages"""

    recent_messages = serializers.SerializerMethodField()

    class Meta(ConversationSerializer.Meta):
        fields = ConversationSerializer.Meta.fields + ['recent_messages']

    def get_recent_messages(self, obj):
        """Get last 50 messages in the conversation"""
        messages = obj.messages.all().order_by('-created_at')[:50]
        # Reverse to show oldest first
        messages = list(reversed(messages))
        return MessageSerializer(messages, many=True, context=self.context).data


class ConversationCreateSerializer(serializers.Serializer):
    """Serializer for creating a conversation with another user"""

    other_user_id = serializers.IntegerField()
    initial_message = serializers.CharField(max_length=1000, required=False)

    def validate_other_user_id(self, value):
        """Validate that the other user exists"""
        try:
            User.objects.get(id=value)
        except User.DoesNotExist:
            raise serializers.ValidationError("User not found")
        return value

    def create(self, validated_data):
        """Create or get conversation and optionally send initial message"""
        request = self.context.get('request')
        other_user_id = validated_data['other_user_id']
        initial_message_text = validated_data.get('initial_message')

        other_user = User.objects.get(id=other_user_id)
        conversation, created = Conversation.get_or_create_for_users(request.user, other_user)

        # Send initial message if provided
        if initial_message_text and created:
            Message.objects.create(
                conversation=conversation,
                sender=request.user,
                text=initial_message_text
            )

        return conversation
