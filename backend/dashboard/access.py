from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from tickets.permissions import has_internal_access


def internal_user_required(view_function):
    """Не пускает в служебный кабинет пользователей без рабочей роли."""

    @wraps(view_function)
    @login_required
    def wrapped(request, *args, **kwargs):
        if not has_internal_access(request.user):
            raise PermissionDenied(
                'Кабинет доступен только сотрудникам ЖК и поставщиков.',
            )
        return view_function(request, *args, **kwargs)

    return wrapped
