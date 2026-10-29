from rest_framework import serializers

from .models import User


class UserSummarySerializer(serializers.ModelSerializer):
    """Безопасное краткое представление пользователя без email и прав."""

    class Meta:
        model = User
        fields = ('id', 'username', 'first_name', 'last_name')
