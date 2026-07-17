from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import PermissionDenied, ValidationError

from complexes.models import ResidentialComplex, ResidentialComplexMembership
from providers.models import ServiceCategory
from tickets.models import Applicant, Ticket
from tickets.permissions import (
    COMPLEX_STAFF_ROLES,
    can_register_ticket,
    has_internal_access,
)


class InternalAuthenticationForm(AuthenticationForm):
    """Отклоняет вход, если у пользователя нет служебной роли."""

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not has_internal_access(user):
            raise ValidationError(
                'Вход доступен только сотрудникам ЖК и поставщиков.',
                code='internal_access_required',
            )


class TicketWebCreateForm(forms.ModelForm):
    """Русская форма создания заявки с выборками в рамках прав пользователя."""

    class Meta:
        model = Ticket
        fields = (
            'residential_complex',
            'applicant',
            'title',
            'description',
            'category',
            'priority',
        )
        labels = {
            'residential_complex': 'Жилой комплекс',
            'applicant': 'Заявитель',
            'title': 'Краткое название',
            'description': 'Описание проблемы',
            'category': 'Категория услуги',
            'priority': 'Приоритет',
        }
        widgets = {
            'title': forms.TextInput(
                attrs={'placeholder': 'Например: не работает освещение'},
            ),
            'description': forms.Textarea(
                attrs={
                    'rows': 5,
                    'placeholder': 'Опишите, что случилось и где именно',
                },
            ),
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

        memberships = ResidentialComplexMembership.objects.filter(
            user=user,
            is_active=True,
        )
        if user.is_superuser:
            complexes = ResidentialComplex.objects.filter(is_active=True)
        else:
            complexes = ResidentialComplex.objects.filter(
                memberships__in=memberships,
                is_active=True,
            ).distinct()
        self.fields['residential_complex'].queryset = complexes
        self.fields['category'].queryset = ServiceCategory.objects.filter(
            is_active=True,
        )

        is_complex_staff = user.is_superuser or memberships.filter(
            role__in=COMPLEX_STAFF_ROLES,
        ).exists()
        if not is_complex_staff:
            raise PermissionDenied(
                'Ручная регистрация доступна только сотрудникам ЖК.',
            )

        applicants = Applicant.objects.filter(
            residential_complex__in=complexes,
            is_active=True,
        ).distinct()
        self.fields['applicant'].queryset = applicants
        self.fields['applicant'].required = True

        for field in self.fields.values():
            current_class = field.widget.attrs.get('class', '')
            field.widget.attrs['class'] = f'{current_class} form-control'.strip()

    def clean(self):
        cleaned_data = super().clean()
        residential_complex = cleaned_data.get('residential_complex')
        applicant = cleaned_data.get('applicant')
        if residential_complex and applicant and not can_register_ticket(
            self.user,
            residential_complex.pk,
        ):
            self.add_error('applicant', 'Нельзя зарегистрировать этого заявителя.')
        if (
            residential_complex
            and applicant
            and applicant.residential_complex_id != residential_complex.pk
        ):
            self.add_error('applicant', 'Заявитель относится к другому ЖК.')
        self.instance.source = Ticket.Source.DIRECT
        return cleaned_data

    def save(self, commit=True):
        ticket = super().save(commit=False)
        ticket.source = Ticket.Source.DIRECT
        if commit:
            ticket.save()
        return ticket
