from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """Единый пользователь платформы без жёстко закреплённой роли.

    Роли зависят от контекста: один пользователь может быть диспетчером в
    одном ЖК, жителем в другом и сотрудником поставщика. Эти связи хранятся в
    membership-моделях приложений ``complexes`` и ``providers``.
    """

    pass
