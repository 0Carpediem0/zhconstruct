from django.core.exceptions import ValidationError
from django.db import transaction

from complexes.models import (
    ResidentialComplexProvider,
    ResidentialComplexService,
    ServiceRoutingRule,
)

from .models import Ticket


@transaction.atomic
def apply_initial_routing(ticket, *, changed_by=None):
    """Автоматически выбирает поставщика, когда конфигурация даёт один ответ.

    Явное правило внедренца имеет приоритет. Без него система использует
    единственного доступного поставщика либо единственного предпочтительного.
    Неоднозначная конфигурация безопасно оставляет заявку диспетчеру ЖК.
    """

    service_setting = ResidentialComplexService.objects.filter(
        residential_complex_id=ticket.residential_complex_id,
        category_id=ticket.category_id,
    ).first()
    # Старые ЖК без отдельной настройки услуги продолжают работать как раньше.
    # Если настройка уже создана, она становится главным выключателем автоматики.
    if service_setting and (
        not service_setting.is_active
        or not service_setting.auto_assignment_enabled
    ):
        return ticket

    rule = (
        ServiceRoutingRule.objects.select_related('provider')
        .filter(
            residential_complex_id=ticket.residential_complex_id,
            category_id=ticket.category_id,
            is_active=True,
        )
        .first()
    )
    provider = None
    comment = ''
    if rule:
        if rule.mode == ServiceRoutingRule.Mode.MANUAL:
            return ticket
        provider = rule.provider
        comment = 'Поставщик назначен по прямому правилу маршрутизации ЖК.'
    else:
        links = list(
            ResidentialComplexProvider.objects.filter(
                residential_complex_id=ticket.residential_complex_id,
                service_categories=ticket.category,
                provider__services__category=ticket.category,
                provider__services__is_active=True,
                provider__is_active=True,
                is_active=True,
                auto_assignment_enabled=True,
            )
            .select_related('provider')
            .distinct()
        )
        preferred_links = [link for link in links if link.is_preferred]
        if len(preferred_links) == 1:
            provider = preferred_links[0].provider
            comment = 'Назначен единственный предпочтительный поставщик ЖК.'
        elif len(links) == 1:
            provider = links[0].provider
            comment = 'Назначен единственный доступный поставщик услуги.'

    if provider is None:
        return ticket

    return assign_provider(
        ticket,
        provider=provider,
        changed_by=changed_by,
        comment=comment,
    )


@transaction.atomic
def assign_provider(ticket, *, provider, changed_by, comment=''):
    """Назначает поставщика и переводит новую заявку в ``assigned``."""

    locked_ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
    if locked_ticket.status not in {
        Ticket.Status.NEW,
        Ticket.Status.AWAITING_ASSIGNMENT,
    }:
        raise ValidationError(
            {'status': 'Provider can only be assigned to an unassigned ticket.'}
        )

    locked_ticket.provider = provider
    locked_ticket.assignee = None
    locked_ticket.full_clean()
    locked_ticket.save(update_fields=('provider', 'assignee', 'updated_at'))
    locked_ticket.transition_to(
        Ticket.Status.ASSIGNED,
        changed_by=changed_by,
        comment=comment or 'Provider assigned.',
    )
    return locked_ticket


@transaction.atomic
def assign_employee(ticket, *, employee):
    """Назначает исполнителя, не подменяя отдельное изменение статуса."""

    locked_ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
    if locked_ticket.status not in {Ticket.Status.ASSIGNED, Ticket.Status.ACCEPTED}:
        raise ValidationError(
            {'status': 'Employee can only be assigned to an active provider ticket.'}
        )

    locked_ticket.assignee = employee
    locked_ticket.full_clean()
    locked_ticket.save(update_fields=('assignee', 'updated_at'))
    return locked_ticket
