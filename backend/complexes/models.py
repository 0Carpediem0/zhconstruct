from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class ResidentialComplex(models.Model):
    """Жилой комплекс и основная граница изоляции данных арендатора.

    Каждая будущая заявка принадлежит ровно одному ЖК. Через эту связь мы
    ограничиваем видимость заявок, поставщиков и сотрудников.
    """

    class LifecycleStatus(models.TextChoices):
        SETUP = 'setup', 'Настраивается'
        ACTIVE = 'active', 'Работает'
        SUSPENDED = 'suspended', 'Приостановлен'

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=270, unique=True)
    address = models.TextField()
    management_company = models.CharField(max_length=255, blank=True)
    timezone = models.CharField(max_length=64, default='Asia/Yekaterinburg')
    contact_name = models.CharField(max_length=255, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=32, blank=True)
    lifecycle_status = models.CharField(
        max_length=16,
        choices=LifecycleStatus.choices,
        default=LifecycleStatus.SETUP,
    )
    launched_at = models.DateTimeField(null=True, blank=True)
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
    auto_assignment_enabled = models.BooleanField(default=True)
    contract_number = models.CharField(max_length=100, blank=True)
    contract_valid_until = models.DateField(null=True, blank=True)
    contact_name = models.CharField(max_length=255, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=32, blank=True)
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


class ResidentialComplexIntakeChannel(models.Model):
    """Канал, через который обработанные обращения попадают в конкретный ЖК."""

    class Type(models.TextChoices):
        MANUAL = 'manual', 'Ручная регистрация'
        API = 'api', 'API'
        AI = 'ai', 'ИИ-обработка обращений'
        ONE_C = '1c', '1С:ЖКХ'

    residential_complex = models.ForeignKey(
        ResidentialComplex,
        on_delete=models.CASCADE,
        related_name='intake_channels',
    )
    channel_type = models.CharField(max_length=16, choices=Type.choices)
    description = models.TextField(blank=True)
    is_enabled = models.BooleanField(default=True)
    is_verified = models.BooleanField(default=False)
    last_verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('channel_type',)
        constraints = [
            models.UniqueConstraint(
                fields=('residential_complex', 'channel_type'),
                name='unique_intake_channel_per_complex',
            ),
        ]

    def __str__(self):
        return f'{self.residential_complex}: {self.get_channel_type_display()}'


class ResidentialComplexService(models.Model):
    """Параметры оказания одной услуги внутри конкретного ЖК."""

    class Priority(models.TextChoices):
        LOW = 'low', 'Низкий'
        NORMAL = 'normal', 'Обычный'
        HIGH = 'high', 'Высокий'
        URGENT = 'urgent', 'Срочный'

    class Fallback(models.TextChoices):
        DISPATCHER = 'dispatcher', 'Передать диспетчеру'
        HOLD = 'hold', 'Оставить без назначения'

    residential_complex = models.ForeignKey(
        ResidentialComplex,
        on_delete=models.CASCADE,
        related_name='service_settings',
    )
    category = models.ForeignKey(
        'providers.ServiceCategory',
        on_delete=models.PROTECT,
        related_name='complex_settings',
    )
    default_priority = models.CharField(
        max_length=16,
        choices=Priority.choices,
        default=Priority.NORMAL,
    )
    response_time_minutes = models.PositiveIntegerField(default=1440)
    working_hours = models.CharField(max_length=100, default='Круглосуточно')
    auto_assignment_enabled = models.BooleanField(default=True)
    fallback = models.CharField(
        max_length=16,
        choices=Fallback.choices,
        default=Fallback.DISPATCHER,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('category__name',)
        constraints = [
            models.UniqueConstraint(
                fields=('residential_complex', 'category'),
                name='unique_service_setting_per_complex',
            ),
        ]

    def __str__(self):
        return f'{self.residential_complex}: {self.category}'


class ResidentialComplexNotificationRule(models.Model):
    """Кому сообщать о ключевых событиях операционного процесса ЖК."""

    class Event(models.TextChoices):
        NEW = 'new', 'Поступила новая заявка'
        UNASSIGNED = 'unassigned', 'Заявка осталась без назначения'
        OVERDUE = 'overdue', 'Нарушен срок реакции'
        COMPLETED = 'completed', 'Заявка завершена'

    class Recipient(models.TextChoices):
        DISPATCHERS = 'dispatchers', 'Диспетчеры ЖК'
        MANAGERS = 'managers', 'Руководители ЖК'
        PROVIDER_MANAGERS = 'provider_managers', 'Руководитель поставщика'

    residential_complex = models.ForeignKey(
        ResidentialComplex,
        on_delete=models.CASCADE,
        related_name='notification_rules',
    )
    event = models.CharField(max_length=24, choices=Event.choices)
    recipient = models.CharField(max_length=24, choices=Recipient.choices)
    is_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('event', 'recipient')
        constraints = [
            models.UniqueConstraint(
                fields=('residential_complex', 'event', 'recipient'),
                name='unique_notification_rule_per_complex',
            ),
        ]


class ImplementationTestRun(models.Model):
    """Результат безопасной проверки маршрутов перед рабочим запуском."""

    residential_complex = models.ForeignKey(
        ResidentialComplex,
        on_delete=models.CASCADE,
        related_name='implementation_test_runs',
    )
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='implementation_test_runs',
    )
    is_successful = models.BooleanField(default=False)
    results = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)


class ComplexConfigurationEvent(models.Model):
    """Журнал действий внедренцев, необходимый для поддержки и аудита."""

    class Type(models.TextChoices):
        PROFILE = 'profile', 'Данные ЖК'
        TEAM = 'team', 'Команда'
        CHANNEL = 'channel', 'Канал заявок'
        SERVICE = 'service', 'Услуга'
        PROVIDER = 'provider', 'Поставщик'
        ROUTING = 'routing', 'Маршрутизация'
        TEST = 'test', 'Тестовый запуск'
        LAUNCH = 'launch', 'Запуск ЖК'

    residential_complex = models.ForeignKey(
        ResidentialComplex,
        on_delete=models.CASCADE,
        related_name='configuration_events',
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='complex_configuration_events',
    )
    event_type = models.CharField(max_length=20, choices=Type.choices)
    description = models.CharField(max_length=500)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)
