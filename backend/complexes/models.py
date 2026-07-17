from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class ResidentialComplex(models.Model):
    """Жилой комплекс и основная граница изоляции данных арендатора.

    Каждая будущая заявка принадлежит ровно одному ЖК. Через эту связь мы
    ограничиваем видимость заявок, поставщиков и сотрудников.
    """

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=270, unique=True)
    address = models.TextField()
    is_active = models.BooleanField(default=True)
    providers = models.ManyToManyField(
        'providers.Provider',
        through='ResidentialComplexProvider',
        related_name='residential_complexes',
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('name',)
        verbose_name = 'residential complex'
        verbose_name_plural = 'residential complexes'

    def __str__(self):
        return self.name


class ResidentialComplexProvider(models.Model):
    """Подключение поставщика к конкретному ЖК.

    Сам факт наличия ``ProviderService`` ещё не разрешает отправлять заявки
    поставщику. Для этого нужен активный договор с ЖК и категория должна быть
    включена в ``service_categories`` данного подключения.
    """

    class Source(models.TextChoices):
        # Источник нужен для разделения каталога внедренцев и собственных
        # подрядчиков ЖК без создания двух разных типов поставщиков.
        PLATFORM = 'platform', 'Каталог платформы'
        RESIDENTIAL_COMPLEX = 'complex', 'Добавлен жилым комплексом'

    residential_complex = models.ForeignKey(
        ResidentialComplex,
        on_delete=models.CASCADE,
        related_name='provider_links',
    )
    provider = models.ForeignKey(
        'providers.Provider',
        on_delete=models.CASCADE,
        related_name='residential_complex_links',
    )
    service_categories = models.ManyToManyField(
        'providers.ServiceCategory',
        related_name='residential_complex_provider_links',
        blank=True,
    )
    source = models.CharField(max_length=20, choices=Source.choices)
    is_preferred = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('residential_complex__name', 'provider__name')
        constraints = [
            models.UniqueConstraint(
                fields=('residential_complex', 'provider'),
                name='unique_complex_provider',
            ),
        ]

    def __str__(self):
        return f'{self.residential_complex} — {self.provider}'


class ServiceRoutingRule(models.Model):
    """Правило первичной маршрутизации категории услуги внутри конкретного ЖК.

    Если правила нет или выбран ручной режим, заявка попадает в очередь ТСЖ.
    Прямой режим сразу назначает согласованного при внедрении поставщика.
    """

    class Mode(models.TextChoices):
        MANUAL = 'manual', 'Через диспетчера ТСЖ'
        DIRECT = 'direct', 'Сразу поставщику'

    residential_complex = models.ForeignKey(
        ResidentialComplex,
        on_delete=models.CASCADE,
        related_name='routing_rules',
    )
    category = models.ForeignKey(
        'providers.ServiceCategory',
        on_delete=models.PROTECT,
        related_name='routing_rules',
    )
    mode = models.CharField(max_length=16, choices=Mode.choices, default=Mode.MANUAL)
    provider = models.ForeignKey(
        'providers.Provider',
        on_delete=models.PROTECT,
        related_name='direct_routing_rules',
        null=True,
        blank=True,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('residential_complex__name', 'category__name')
        constraints = [
            models.UniqueConstraint(
                fields=('residential_complex', 'category'),
                name='unique_routing_rule_per_complex_category',
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.mode == self.Mode.DIRECT and not self.provider_id:
            errors['provider'] = 'Для прямой маршрутизации выберите поставщика.'
        if self.mode == self.Mode.MANUAL and self.provider_id:
            errors['provider'] = 'В ручном режиме поставщик заранее не назначается.'

        if self.provider_id and self.residential_complex_id and self.category_id:
            contract = ResidentialComplexProvider.objects.filter(
                residential_complex_id=self.residential_complex_id,
                provider_id=self.provider_id,
                provider__is_active=True,
                service_categories__id=self.category_id,
                is_active=True,
            ).exists()
            if not contract:
                errors['provider'] = (
                    'Поставщик не подключён к ЖК для выбранной категории.'
                )
            else:
                from providers.models import ProviderService

                offers_service = ProviderService.objects.filter(
                    provider_id=self.provider_id,
                    category_id=self.category_id,
                    is_active=True,
                ).exists()
                if not offers_service:
                    errors['provider'] = 'У поставщика нет активной услуги этой категории.'

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f'{self.residential_complex}: {self.category} — '
            f'{self.get_mode_display()}'
        )


class ResidentialComplexMembership(models.Model):
    """Контекстная роль пользователя в конкретном жилом комплексе."""

    class Role(models.TextChoices):
        DISPATCHER = 'dispatcher', 'Диспетчер'
        MANAGER = 'manager', 'Руководитель ЖК'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='residential_complex_memberships',
    )
    residential_complex = models.ForeignKey(
        ResidentialComplex,
        on_delete=models.CASCADE,
        related_name='memberships',
    )
    role = models.CharField(max_length=20, choices=Role.choices)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('residential_complex__name', 'user__username')
        constraints = [
            models.UniqueConstraint(
                fields=('user', 'residential_complex'),
                name='unique_complex_membership',
            ),
        ]

    def __str__(self):
        return (
            f'{self.user} — {self.residential_complex} '
            f'({self.get_role_display()})'
        )
