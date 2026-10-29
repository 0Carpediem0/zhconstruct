from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Сотрудник, имеющий доступ к служебному контуру платформы.

    Рабочие роли зависят от организации: пользователь может представлять ЖК
    или поставщика. Заявители хранятся отдельно в ``tickets.Applicant`` и не
    получают учётную запись только из-за факта обращения.
    """

    class PlatformRole(models.TextChoices):
        NONE = '', 'Нет платформенной роли'
        IMPLEMENTER = 'implementer', 'Внедренец'

    # Платформенная роль не подменяет членство в ЖК или организации-поставщике.
    # Внедренец настраивает арендаторов, но не получает доступ к их заявкам.
    platform_role = models.CharField(
        max_length=24,
        choices=PlatformRole.choices,
        blank=True,
        default=PlatformRole.NONE,
    )
