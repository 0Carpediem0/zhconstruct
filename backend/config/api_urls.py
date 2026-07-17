from rest_framework.routers import DefaultRouter

from complexes.views import ResidentialComplexViewSet
from providers.views import ProviderViewSet, ServiceCategoryViewSet
from tickets.views import TicketViewSet


router = DefaultRouter()
router.register(
    'residential-complexes',
    ResidentialComplexViewSet,
    basename='residential-complex',
)
router.register('providers', ProviderViewSet, basename='provider')
router.register('service-categories', ServiceCategoryViewSet, basename='service-category')
router.register('tickets', TicketViewSet, basename='ticket')

urlpatterns = router.urls
