from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class UtilityAccount(models.Model):
    """Лицевой счёт жителя для будущей интеграции с расчётной системой."""

    applicant = models.OneToOneField(
        'tickets.Applicant',
        on_delete=models.CASCADE,
        related_name='utility_account',
    )
    account_number = models.CharField(max_length=64)
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount_due = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    due_date = models.DateField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.applicant}: {self.account_number}'


class NewsPost(models.Model):
    """Новость, которую видят только жители выбранного ЖК."""

    residential_complex = models.ForeignKey(
        'complexes.ResidentialComplex',
        on_delete=models.CASCADE,
        related_name='resident_news',
    )
    title = models.CharField(max_length=255)
    summary = models.TextField()
    is_published = models.BooleanField(default=True)
    published_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-published_at',)

    def __str__(self):
        return self.title


class ServiceOrderDetails(models.Model):
    """Зафиксированные условия коммерческого заказа жителя."""

    ticket = models.OneToOneField(
        'tickets.Ticket',
        on_delete=models.CASCADE,
        related_name='service_order',
    )
    offering = models.ForeignKey(
        'providers.ServiceOffering',
        on_delete=models.PROTECT,
        related_name='orders',
    )
    scheduled_date = models.DateField()
    scheduled_start = models.TimeField()
    scheduled_end = models.TimeField()
    quoted_price = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='RUB')
    resident_comment = models.TextField(blank=True)
    resident_confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-scheduled_date', '-scheduled_start')
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quoted_price__gte=0),
                name='service_order_price_not_negative',
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.ticket_id and self.ticket.kind != self.ticket.Kind.SERVICE_ORDER:
            errors['ticket'] = 'Коммерческие детали можно добавить только заказу услуги.'
        if self.ticket_id and self.offering_id:
            if self.ticket.residential_complex_id != self.offering.residential_complex_id:
                errors['offering'] = 'Предложение относится к другому ЖК.'
            if self.ticket.category_id != self.offering.category_id:
                errors['offering'] = 'Категория предложения не совпадает с заявкой.'
            if self.ticket.provider_id and self.ticket.provider_id != self.offering.provider_id:
                errors['offering'] = 'Назначен другой поставщик.'
        if self.scheduled_start and self.scheduled_end:
            if self.scheduled_start >= self.scheduled_end:
                errors['scheduled_end'] = 'Окончание заказа должно быть позже начала.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'Заказ №{self.ticket_id} на {self.scheduled_date}'
