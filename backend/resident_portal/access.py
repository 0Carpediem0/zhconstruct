from functools import wraps

from django.shortcuts import redirect


def resident_required(view_function):
    """Пускает только жителя с активной карточкой заявителя."""

    @wraps(view_function)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('resident_portal:login')
        applicant = getattr(request.user, 'applicant_profile', None)
        if applicant is None or not applicant.is_active:
            return redirect('resident_portal:login')
        request.applicant = applicant
        return view_function(request, *args, **kwargs)

    return wrapped
