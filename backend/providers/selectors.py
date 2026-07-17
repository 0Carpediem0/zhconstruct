from django.db.models import Q

from .models import Provider


def visible_providers_for(user):
    queryset = Provider.objects.filter(is_active=True).prefetch_related(
        'service_categories',
    )
    if user.is_superuser:
        return queryset
    return queryset.filter(
        Q(memberships__user=user, memberships__is_active=True)
        | Q(
            residential_complex_links__residential_complex__memberships__user=user,
            residential_complex_links__residential_complex__memberships__is_active=True,
            residential_complex_links__is_active=True,
        )
    ).distinct()
