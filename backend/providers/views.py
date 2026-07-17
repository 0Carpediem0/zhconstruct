from rest_framework.viewsets import ReadOnlyModelViewSet

from .models import ServiceCategory
from .selectors import visible_providers_for
from .serializers import ProviderSerializer, ServiceCategorySerializer


class ServiceCategoryViewSet(ReadOnlyModelViewSet):
    serializer_class = ServiceCategorySerializer
    queryset = ServiceCategory.objects.filter(is_active=True)


class ProviderViewSet(ReadOnlyModelViewSet):
    """Ограничивает каталог организациями, доступными пользователю."""

    serializer_class = ProviderSerializer

    def get_queryset(self):
        return visible_providers_for(self.request.user)
