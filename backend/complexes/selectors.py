from django.db.models import Q

from .models import ResidentialComplex


def visible_complexes_for(user):
    queryset = ResidentialComplex.objects.filter(is_active=True)
    if user.is_superuser:
        return queryset
    return queryset.filter(
        Q(memberships__user=user, memberships__is_active=True)
        | Q(
            provider_links__provider__memberships__user=user,
            provider_links__provider__memberships__is_active=True,
            provider_links__is_active=True,
        )
    ).distinct()
