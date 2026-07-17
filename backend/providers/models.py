from django.conf import settings
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
