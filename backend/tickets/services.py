from django.core.exceptions import ValidationError
from django.db import transaction

from complexes.models import ServiceRoutingRule

from .models import Ticket


@transaction.atomic
def apply_initial_routing(ticket, *, changed_by=None):
    """Применяет внедренческое правило и при необходимости обходит очередь ТСЖ."""

    rule = (
        ServiceRoutingRule.objects.select_related('provider')
        .filter(
            residential_complex_id=ticket.residential_complex_id,
            category_id=ticket.category_id,
            mode=ServiceRoutingRule.Mode.DIRECT,
            provider__isnull=False,
            is_active=True,
        )
        .first()
    )
    if not rule:
        return ticket

    return assign_provider(
        ticket,
        provider=rule.provider,
        changed_by=changed_by,
        comment=(
            'Поставщик назначен автоматически по правилу прямой '
            'маршрутизации ЖК.'
        ),
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
