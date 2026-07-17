from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction


class Applicant(models.Model):
    """Заявитель хранится отдельно от сотрудников, имеющих доступ в систему."""

    residential_complex = models.ForeignKey(
        'complexes.ResidentialComplex',
        on_delete=models.CASCADE,
        related_name='applicants',
    )
    full_name = models.CharField(max_length=255)
    phone = models.CharField(max_length=32, blank=True)
    email = models.EmailField(blank=True)
    apartment = models.CharField(max_length=32, blank=True)
    external_id = models.CharField(max_length=255, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('full_name', 'apartment')
        constraints = [
            models.UniqueConstraint(
                fields=('residential_complex', 'external_id'),
                condition=models.Q(external_id__isnull=False),
                name='unique_applicant_external_id_per_complex',
            ),
        ]

    def __str__(self):
        details = f', кв. {self.apartment}' if self.apartment else ''
        return f'{self.full_name}{details}'


class Ticket(models.Model):
    """Заявка жителя — центральная бизнес-сущность платформы.

    Источник заявки не влияет на её дальнейшую обработку: сообщение из
    жительского интерфейса, результат ИИ-классификации и импорт приводятся к
    одной модели и проходят одинаковый workflow.
    """

    class Status(models.TextChoices):
        NEW = 'new', 'Новая'
        AWAITING_ASSIGNMENT = 'awaiting_assignment', 'Ожидает назначения'
        ASSIGNED = 'assigned', 'Назначена поставщику'
        ACCEPTED = 'accepted', 'Принята поставщиком'
        IN_PROGRESS = 'in_progress', 'В работе'
        COMPLETED = 'completed', 'Выполнена'
        CANCELLED = 'cancelled', 'Отменена'

    class Priority(models.TextChoices):
        LOW = 'low', 'Низкий'
        NORMAL = 'normal', 'Обычный'
        HIGH = 'high', 'Высокий'
        URGENT = 'urgent', 'Срочный'

    class Source(models.TextChoices):
        DIRECT = 'direct', 'От жителя'
        AI = 'ai', 'Обработана ИИ'
        IMPORT = 'import', 'Импортирована'
        INTEGRATION = 'integration', 'Внешняя интеграция'

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
    applicant = models.ForeignKey(
        Applicant,
        on_delete=models.PROTECT,
        related_name='tickets',
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

        if (
            self.applicant_id
            and self.residential_complex_id
            and self.applicant.residential_complex_id != self.residential_complex_id
        ):
            errors['applicant'] = 'Заявитель относится к другому жилому комплексу.'

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
