from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction


class Ticket(models.Model):
    """Заявка жителя — центральная бизнес-сущность платформы.

    Источник заявки не влияет на её дальнейшую обработку: сообщение из
    жительского интерфейса, результат ИИ-классификации и импорт приводятся к
    одной модели и проходят одинаковый workflow.
    """

    class Status(models.TextChoices):
        NEW = 'new', 'New'
        AWAITING_ASSIGNMENT = 'awaiting_assignment', 'Awaiting assignment'
        ASSIGNED = 'assigned', 'Assigned to provider'
        ACCEPTED = 'accepted', 'Accepted by provider'
        IN_PROGRESS = 'in_progress', 'In progress'
        COMPLETED = 'completed', 'Completed'
        CANCELLED = 'cancelled', 'Cancelled'

    class Priority(models.TextChoices):
        LOW = 'low', 'Low'
        NORMAL = 'normal', 'Normal'
        HIGH = 'high', 'High'
        URGENT = 'urgent', 'Urgent'

    class Source(models.TextChoices):
        DIRECT = 'direct', 'Direct from resident'
        AI = 'ai', 'AI processed'
        IMPORT = 'import', 'Imported'
        INTEGRATION = 'integration', 'External integration'

    # Карта является единственным местом, где описан допустимый жизненный
    # цикл. API, фоновые задачи и интеграции должны использовать
    # ``transition_to``, а не присваивать status напрямую.
    ALLOWED_STATUS_TRANSITIONS = {
        Status.NEW: {Status.AWAITING_ASSIGNMENT, Status.ASSIGNED, Status.CANCELLED},
        Status.AWAITING_ASSIGNMENT: {Status.ASSIGNED, Status.CANCELLED},
        Status.ASSIGNED: {
            Status.ACCEPTED,
            Status.AWAITING_ASSIGNMENT,
            Status.CANCELLED,
        },
        Status.ACCEPTED: {Status.IN_PROGRESS, Status.CANCELLED},
        Status.IN_PROGRESS: {Status.COMPLETED, Status.CANCELLED},
        Status.COMPLETED: set(),
        Status.CANCELLED: set(),
    }

    residential_complex = models.ForeignKey(
        'complexes.ResidentialComplex',
        on_delete=models.PROTECT,
        related_name='tickets',
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='created_tickets',
    )
    title = models.CharField(max_length=255)
    description = models.TextField()
    category = models.ForeignKey(
        'providers.ServiceCategory',
        on_delete=models.PROTECT,
        related_name='tickets',
    )
    provider = models.ForeignKey(
        'providers.Provider',
        on_delete=models.PROTECT,
        related_name='tickets',
        null=True,
        blank=True,
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='assigned_tickets',
        null=True,
        blank=True,
    )
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.NEW,
    )
    priority = models.CharField(
        max_length=16,
        choices=Priority.choices,
        default=Priority.NORMAL,
    )
    source = models.CharField(
        max_length=16,
        choices=Source.choices,
        default=Source.DIRECT,
    )
    # Идентификатор нужен для идемпотентного импорта: повторная доставка
    # одной заявки из ИИ или внешней системы не должна создать дубликат.
    external_id = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-created_at',)
        indexes = [
            models.Index(fields=('residential_complex', 'status')),
            models.Index(fields=('provider', 'status')),
            models.Index(fields=('assignee', 'status')),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=('residential_complex', 'source', 'external_id'),
                condition=models.Q(external_id__isnull=False),
                name='unique_external_ticket_per_complex_source',
            ),
        ]

    def __str__(self):
        return f'#{self.pk or "new"}: {self.title}'

    def clean(self):
        """Проверяет связи, которые нельзя выразить обычным внешним ключом."""

        super().clean()
        errors = {}

        if self.customer_id and self.residential_complex_id:
            from complexes.models import ResidentialComplexMembership

            customer_belongs_to_complex = (
                ResidentialComplexMembership.objects.filter(
                    user_id=self.customer_id,
                    residential_complex_id=self.residential_complex_id,
                    role=ResidentialComplexMembership.Role.RESIDENT,
                    is_active=True,
                ).exists()
            )
            if not customer_belongs_to_complex:
                errors['customer'] = 'Customer is not an active resident of this complex.'

        provider_link = None
        if self.provider_id and self.residential_complex_id:
            from complexes.models import ResidentialComplexProvider

            provider_link = ResidentialComplexProvider.objects.filter(
                residential_complex_id=self.residential_complex_id,
                provider_id=self.provider_id,
                is_active=True,
            ).first()
            if provider_link is None:
                errors['provider'] = 'Provider is not connected to this complex.'
            elif self.category_id and not provider_link.service_categories.filter(
                pk=self.category_id,
            ).exists():
                errors['category'] = 'Category is not enabled for this provider contract.'
            elif self.category_id:
                from providers.models import ProviderService

                provider_offers_category = ProviderService.objects.filter(
                    provider_id=self.provider_id,
                    category_id=self.category_id,
                    is_active=True,
                ).exists()
                if not provider_offers_category:
                    errors['category'] = 'Provider does not offer this active service.'

        if self.assignee_id:
            if not self.provider_id:
                errors['assignee'] = 'Assignee cannot be selected without a provider.'
            else:
                from providers.models import ProviderMembership

                employee_belongs_to_provider = ProviderMembership.objects.filter(
                    user_id=self.assignee_id,
                    provider_id=self.provider_id,
                    is_active=True,
                ).exists()
                if not employee_belongs_to_provider:
                    errors['assignee'] = 'Assignee is not an active provider employee.'

        provider_required_statuses = {
            self.Status.ASSIGNED,
            self.Status.ACCEPTED,
            self.Status.IN_PROGRESS,
            self.Status.COMPLETED,
        }
        if self.status in provider_required_statuses and not self.provider_id:
            errors['status'] = 'This status requires an assigned provider.'

        assignee_required_statuses = {self.Status.IN_PROGRESS, self.Status.COMPLETED}
        if self.status in assignee_required_statuses and not self.assignee_id:
            errors['status'] = 'This status requires an assigned employee.'

        if errors:
            raise ValidationError(errors)

    def transition_to(self, new_status, *, changed_by=None, comment=''):
        """Атомарно меняет статус и записывает историю перехода.

        Блокировка строки защищает от ситуации, когда 1С, веб-кабинет и
        фоновая задача одновременно пытаются изменить одну заявку.
        """

        if self.pk is None:
            raise ValidationError({'status': 'Unsaved ticket cannot change status.'})

        with transaction.atomic():
            locked_ticket = type(self).objects.select_for_update().get(pk=self.pk)
            previous_status = locked_ticket.status
            allowed_statuses = self.ALLOWED_STATUS_TRANSITIONS.get(
                previous_status,
                set(),
            )

            if new_status not in allowed_statuses:
                raise ValidationError(
                    {
                        'status': (
                            f'Transition from {previous_status} to {new_status} '
                            'is not allowed.'
                        ),
                    }
                )

            locked_ticket.status = new_status
            locked_ticket.full_clean()
            locked_ticket.save(update_fields=('status', 'updated_at'))

            history = TicketStatusHistory.objects.create(
                ticket=locked_ticket,
                from_status=previous_status,
                to_status=new_status,
                changed_by=changed_by,
                comment=comment,
            )

        # Синхронизируем вызывающий объект с версией, сохранённой под
        # блокировкой, чтобы последующий код не видел устаревший status.
        self.status = locked_ticket.status
        self.updated_at = locked_ticket.updated_at
        return history


class TicketStatusHistory(models.Model):
    """Неизменяемый журнал фактически выполненных переходов заявки."""

    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name='status_history',
    )
    from_status = models.CharField(max_length=32, choices=Ticket.Status.choices)
    to_status = models.CharField(max_length=32, choices=Ticket.Status.choices)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='ticket_status_changes',
        null=True,
        blank=True,
    )
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at', '-pk')
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(from_status=models.F('to_status')),
                name='ticket_history_statuses_must_differ',
            ),
        ]

    def __str__(self):
        return f'{self.ticket}: {self.from_status} → {self.to_status}'
