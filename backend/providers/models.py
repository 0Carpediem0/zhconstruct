from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class ServiceCategory(models.Model):
    """Справочник типов работ, не привязанный к конкретному поставщику."""

    name = models.CharField(max_length=150, unique=True)
    slug = models.SlugField(max_length=160, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('name',)
        verbose_name = 'service category'
        verbose_name_plural = 'service categories'

    def __str__(self):
        return self.name


class Provider(models.Model):
    """Организация, способная принимать и выполнять заявки жителей.

    ``is_platform_partner`` отделяет поставщиков общего каталога внедренцев
    от организаций, которые отдельный ЖК добавил самостоятельно.
    """

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=270, unique=True)
    tax_id = models.CharField(max_length=32, unique=True, null=True, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=32, blank=True)
    is_platform_partner = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    service_categories = models.ManyToManyField(
        ServiceCategory,
        through='ProviderService',
        related_name='providers',
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('name',)

    def __str__(self):
        return self.name


class ProviderService(models.Model):
    """Глобальная компетенция поставщика.

    Эта модель отвечает на вопрос «что поставщик умеет делать вообще».
    Конкретный набор услуг, разрешённый договором с отдельным ЖК, хранится в
    ``ResidentialComplexProvider.service_categories``.
    """

    provider = models.ForeignKey(
        Provider,
        on_delete=models.CASCADE,
        related_name='services',
    )
    category = models.ForeignKey(
        ServiceCategory,
        on_delete=models.PROTECT,
        related_name='provider_services',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('provider__name', 'category__name')
        constraints = [
            models.UniqueConstraint(
                fields=('provider', 'category'),
                name='unique_provider_service',
            ),
        ]

    def __str__(self):
        return f'{self.provider}: {self.category}'


class ServiceOffering(models.Model):
    """Коммерческое предложение поставщика для жителей конкретного ЖК.

    Категория описывает тип работ, а предложение — то, что житель реально
    видит и заказывает: название, цену, длительность и доступное время.
    """

    residential_complex = models.ForeignKey(
        'complexes.ResidentialComplex',
        on_delete=models.CASCADE,
        related_name='service_offerings',
    )
    provider = models.ForeignKey(
        Provider,
        on_delete=models.PROTECT,
        related_name='service_offerings',
    )
    category = models.ForeignKey(
        ServiceCategory,
        on_delete=models.PROTECT,
        related_name='offerings',
    )
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    duration_minutes = models.PositiveIntegerField(default=120)
    capacity_per_slot = models.PositiveIntegerField(default=1)
    available_weekdays = models.JSONField(default=list)
    available_from = models.TimeField()
    available_until = models.TimeField()
    minimum_lead_hours = models.PositiveIntegerField(default=12)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('category__name', 'price', 'title')
        constraints = [
            models.UniqueConstraint(
                fields=('residential_complex', 'provider', 'category'),
                name='unique_provider_offering_per_complex_category',
            ),
            models.CheckConstraint(
                condition=models.Q(price__gte=0),
                name='service_offering_price_not_negative',
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.available_from and self.available_until:
            if self.available_from >= self.available_until:
                errors['available_until'] = 'Время окончания должно быть позже начала.'
        invalid_weekdays = set(self.available_weekdays or ()) - set(range(7))
        if invalid_weekdays or not self.available_weekdays:
            errors['available_weekdays'] = 'Выберите хотя бы один корректный день недели.'

        if self.residential_complex_id and self.provider_id and self.category_id:
            from complexes.models import ResidentialComplexProvider, ServiceRoutingRule

            connected = ResidentialComplexProvider.objects.filter(
                residential_complex_id=self.residential_complex_id,
                provider_id=self.provider_id,
                service_categories__id=self.category_id,
                is_active=True,
                provider__services__category_id=self.category_id,
                provider__services__is_active=True,
            ).exists()
            if not connected:
                errors['provider'] = (
                    'Поставщик не подключён к этому ЖК для выбранной категории.'
                )
            direct_route = ServiceRoutingRule.objects.filter(
                residential_complex_id=self.residential_complex_id,
                category_id=self.category_id,
                provider_id=self.provider_id,
                mode=ServiceRoutingRule.Mode.DIRECT,
                is_active=True,
            ).exists()
            if not direct_route:
                errors['provider'] = (
                    'Для витрины сначала настройте прямой маршрут к этому поставщику.'
                )
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.residential_complex}: {self.title} — {self.provider}'


class ProviderMembership(models.Model):
    """Роль пользователя внутри конкретной организации-поставщика.

    Отдельная модель вместо поля ``User.provider`` позволяет пользователю
    работать с несколькими организациями и иметь в них разные полномочия.
    """

    class Role(models.TextChoices):
        MANAGER = 'manager', 'Руководитель поставщика'
        EMPLOYEE = 'employee', 'Исполнитель'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='provider_memberships',
    )
    provider = models.ForeignKey(
        Provider,
        on_delete=models.CASCADE,
        related_name='memberships',
    )
    role = models.CharField(max_length=20, choices=Role.choices)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('provider__name', 'user__username')
        constraints = [
            models.UniqueConstraint(
                fields=('user', 'provider'),
                name='unique_provider_membership',
            ),
        ]

    def __str__(self):
        return f'{self.user} — {self.provider} ({self.get_role_display()})'
