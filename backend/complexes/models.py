from django.conf import settings
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
        PLATFORM = 'platform', 'Platform catalog'
        RESIDENTIAL_COMPLEX = 'complex', 'Residential complex'

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


class ResidentialComplexMembership(models.Model):
    """Контекстная роль пользователя в конкретном жилом комплексе."""

    class Role(models.TextChoices):
        RESIDENT = 'resident', 'Resident'
        DISPATCHER = 'dispatcher', 'Dispatcher'
        MANAGER = 'manager', 'Manager'

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
