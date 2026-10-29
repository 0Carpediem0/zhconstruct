from rest_framework.viewsets import ReadOnlyModelViewSet

from .selectors import visible_complexes_for
from .serializers import ResidentialComplexSerializer


class ResidentialComplexViewSet(ReadOnlyModelViewSet):
    """Показывает только ЖК, с которыми связан текущий пользователь."""

    serializer_class = ResidentialComplexSerializer

    def get_queryset(self):
        return visible_complexes_for(self.request.user).prefetch_related(
            'routing_rules__category',
            'routing_rules__provider',
        )
