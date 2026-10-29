from django.db.models import Q
from rest_framework.permissions import BasePermission

from complexes.models import ResidentialComplexMembership
from providers.models import ProviderMembership

from .models import Ticket


COMPLEX_STAFF_ROLES = {
    ResidentialComplexMembership.Role.DISPATCHER,
    ResidentialComplexMembership.Role.MANAGER,
}


def has_internal_access(user):
    """Разрешает кабинет только сотрудникам ЖК и организаций-поставщиков."""

    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return True
    if user.platform_role == user.PlatformRole.IMPLEMENTER:
        return True
    return (
        ResidentialComplexMembership.objects.filter(
            user=user,
            role__in=COMPLEX_STAFF_ROLES,
            is_active=True,
        ).exists()
        or ProviderMembership.objects.filter(
            user=user,
            role__in={
                ProviderMembership.Role.MANAGER,
                ProviderMembership.Role.EMPLOYEE,
            },
            is_active=True,
        ).exists()
    )


class IsInternalUser(BasePermission):
    """Закрывает служебный API от жителей и других внешних пользователей."""

    message = 'Служебный API доступен только сотрудникам ЖК и поставщиков.'

    def has_permission(self, request, view):
        return has_internal_access(request.user)


def is_complex_staff(user, residential_complex_id):
    return ResidentialComplexMembership.objects.filter(
        user=user,
        residential_complex_id=residential_complex_id,
        role__in=COMPLEX_STAFF_ROLES,
        is_active=True,
    ).exists()


def is_complex_staff_user(user):
    """Проверяет наличие хотя бы одной активной роли сотрудника ЖК."""

    return ResidentialComplexMembership.objects.filter(
        user=user,
        role__in=COMPLEX_STAFF_ROLES,
        is_active=True,
    ).exists()


def is_provider_manager(user, provider_id):
    if provider_id is None:
        return False
    return ProviderMembership.objects.filter(
        user=user,
        provider_id=provider_id,
        role=ProviderMembership.Role.MANAGER,
        is_active=True,
    ).exists()


def visible_tickets_for(user, queryset=None):
    """Формирует единое правило видимости заявок для всех API-действий."""

    queryset = queryset if queryset is not None else Ticket.objects.all()
    if user.is_superuser:
        return queryset

    return queryset.filter(
        Q(
            residential_complex__memberships__user=user,
            residential_complex__memberships__role__in=COMPLEX_STAFF_ROLES,
            residential_complex__memberships__is_active=True,
        )
        | Q(
            provider__memberships__user=user,
            provider__memberships__role=ProviderMembership.Role.MANAGER,
            provider__memberships__is_active=True,
        )
        | Q(assignee=user)
    ).distinct()


def can_register_ticket(user, residential_complex_id):
    return user.is_superuser or is_complex_staff(user, residential_complex_id)


def can_assign_provider(user, ticket):
    return user.is_superuser or is_complex_staff(
        user,
        ticket.residential_complex_id,
    )


def can_assign_employee(user, ticket):
    return user.is_superuser or is_provider_manager(user, ticket.provider_id)


def can_transition_ticket(user, ticket, new_status):
    """Проверяет полномочия поверх допустимого workflow модели Ticket."""

    if user.is_superuser or is_complex_staff(user, ticket.residential_complex_id):
        return True

    provider_statuses = {
        Ticket.Status.ACCEPTED,
        Ticket.Status.IN_PROGRESS,
        Ticket.Status.COMPLETED,
        Ticket.Status.CANCELLED,
    }
    if is_provider_manager(user, ticket.provider_id):
        return new_status in provider_statuses

    employee_statuses = {
        Ticket.Status.ACCEPTED,
        Ticket.Status.IN_PROGRESS,
        Ticket.Status.COMPLETED,
    }
    return ticket.assignee_id == user.pk and new_status in employee_statuses
