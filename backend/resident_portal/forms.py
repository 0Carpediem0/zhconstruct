from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from complexes.models import ResidentialComplexService
from tickets.models import Ticket
from tickets.services import assign_provider

from .models import ServiceOrderDetails


class ResidentAuthenticationForm(AuthenticationForm):
    username = forms.CharField(label='Логин или электронная почта')
    password = forms.CharField(label='Пароль', widget=forms.PasswordInput)

    def clean_username(self):
        """Позволяет использовать email без отдельного механизма авторизации."""

        value = self.cleaned_data['username'].strip()
        if '@' not in value:
            return value
        usernames = get_user_model().objects.filter(
            email__iexact=value,
        ).values_list('username', flat=True)[:2]
        matches = list(usernames)
        return matches[0] if len(matches) == 1 else value

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        applicant = getattr(user, 'applicant_profile', None)
        if applicant is None or not applicant.is_active:
            raise ValidationError(
                'Этот вход предназначен для жителей. Обратитесь в управляющую организацию.',
                code='resident_access_required',
            )


class ResidentTicketForm(forms.ModelForm):
    class Meta:
        model = Ticket
        fields = ('category', 'title', 'description')
        labels = {
            'category': 'Тема обращения',
            'title': 'Коротко опишите задачу',
            'description': 'Подробности',
        }
        widgets = {
            'title': forms.TextInput(attrs={'placeholder': 'Например: забрать пакеты сегодня'}),
            'description': forms.Textarea(
                attrs={'rows': 5, 'placeholder': 'Укажите удобное время и важные детали'},
            ),
        }

    def __init__(self, *args, applicant, kind, category=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.applicant = applicant
        self.kind = kind
        categories = ResidentialComplexService.objects.filter(
            residential_complex=applicant.residential_complex,
            is_active=True,
            category__is_active=True,
        ).values_list('category_id', flat=True)
        self.fields['category'].queryset = self.fields['category'].queryset.filter(
            pk__in=categories,
        )
        if category is not None:
            self.fields['category'].queryset = self.fields['category'].queryset.filter(
                pk=category.pk,
            )
            self.fields['category'].initial = category
            self.fields['category'].widget = forms.HiddenInput()

    def save(self, commit=True):
        ticket = super().save(commit=False)
        ticket.residential_complex = self.applicant.residential_complex
        ticket.applicant = self.applicant
        ticket.kind = self.kind
        ticket.source = Ticket.Source.DIRECT
        ticket.priority = Ticket.Priority.NORMAL
        if commit:
            ticket.full_clean()
            ticket.save()
        return ticket


class ResidentServiceOrderForm(forms.Form):
    scheduled_date = forms.DateField(
        label='Дата',
        widget=forms.DateInput(attrs={'type': 'date'}),
    )
    scheduled_start = forms.ChoiceField(label='Время начала')
    resident_comment = forms.CharField(
        label='Комментарий исполнителю',
        required=False,
        widget=forms.Textarea(
            attrs={
                'rows': 4,
                'placeholder': 'Домофон, пожелания по уборке и другие детали',
            },
        ),
    )

    def __init__(self, *args, applicant, offering, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.applicant = applicant
        self.offering = offering
        self.user = user
        complex_timezone = ZoneInfo(applicant.residential_complex.timezone)
        self.local_now = timezone.now().astimezone(complex_timezone)
        self.fields['scheduled_date'].widget.attrs['min'] = self.local_now.date().isoformat()

        choices = []
        current = datetime.combine(
            self.local_now.date(),
            offering.available_from,
        )
        last_start = datetime.combine(
            self.local_now.date(),
            offering.available_until,
        ) - timedelta(minutes=offering.duration_minutes)
        while current <= last_start:
            value = current.strftime('%H:%M')
            choices.append((value, value))
            current += timedelta(minutes=30)
        self.fields['scheduled_start'].choices = choices

    def clean(self):
        cleaned_data = super().clean()
        scheduled_date = cleaned_data.get('scheduled_date')
        scheduled_start_value = cleaned_data.get('scheduled_start')
        if not scheduled_date or not scheduled_start_value:
            return cleaned_data

        scheduled_start = datetime.strptime(scheduled_start_value, '%H:%M').time()
        starts_at = datetime.combine(
            scheduled_date,
            scheduled_start,
            tzinfo=self.local_now.tzinfo,
        )
        ends_at = starts_at + timedelta(minutes=self.offering.duration_minutes)

        if scheduled_date.weekday() not in self.offering.available_weekdays:
            self.add_error('scheduled_date', 'В этот день услуга не оказывается.')
        earliest = self.local_now + timedelta(hours=self.offering.minimum_lead_hours)
        if starts_at < earliest:
            self.add_error(
                'scheduled_date',
                f'Заказ нужно оформить минимум за {self.offering.minimum_lead_hours} ч.',
            )

        busy_orders = ServiceOrderDetails.objects.filter(
            offering=self.offering,
            scheduled_date=scheduled_date,
            scheduled_start__lt=ends_at.time(),
            scheduled_end__gt=scheduled_start,
        ).exclude(ticket__status=Ticket.Status.CANCELLED).count()
        if busy_orders >= self.offering.capacity_per_slot:
            self.add_error('scheduled_start', 'Это время уже занято. Выберите другое.')

        cleaned_data['scheduled_start_time'] = scheduled_start
        cleaned_data['scheduled_end_time'] = ends_at.time()
        return cleaned_data

    @transaction.atomic
    def save(self):
        # Блокировка предложения закрывает гонку двух жителей за последний
        # свободный слот: второй запрос увидит уже сохранённый первый заказ.
        locked_offering = self.offering.__class__.objects.select_for_update().get(
            pk=self.offering.pk,
        )
        busy_orders = ServiceOrderDetails.objects.filter(
            offering=locked_offering,
            scheduled_date=self.cleaned_data['scheduled_date'],
            scheduled_start__lt=self.cleaned_data['scheduled_end_time'],
            scheduled_end__gt=self.cleaned_data['scheduled_start_time'],
        ).exclude(ticket__status=Ticket.Status.CANCELLED).count()
        if busy_orders >= locked_offering.capacity_per_slot:
            raise ValidationError(
                {'scheduled_start': 'Это время уже занято. Выберите другое.'},
            )

        ticket = Ticket(
            residential_complex=self.applicant.residential_complex,
            applicant=self.applicant,
            title=locked_offering.title,
            description=(
                self.cleaned_data['resident_comment']
                or 'Заказ оформлен через кабинет жителя.'
            ),
            category=locked_offering.category,
            kind=Ticket.Kind.SERVICE_ORDER,
            source=Ticket.Source.DIRECT,
            priority=Ticket.Priority.NORMAL,
        )
        ticket.full_clean()
        ticket.save()
        ticket = assign_provider(
            ticket,
            provider=locked_offering.provider,
            changed_by=self.user,
            comment='Поставщик назначен по выбранному предложению на витрине ЖК.',
        )
        details = ServiceOrderDetails(
            ticket=ticket,
            offering=locked_offering,
            scheduled_date=self.cleaned_data['scheduled_date'],
            scheduled_start=self.cleaned_data['scheduled_start_time'],
            scheduled_end=self.cleaned_data['scheduled_end_time'],
            quoted_price=locked_offering.price,
            resident_comment=self.cleaned_data['resident_comment'],
        )
        details.full_clean()
        details.save()
        return ticket


class ResidentProfileForm(forms.Form):
    full_name = forms.CharField(label='Имя и фамилия', max_length=255)
    phone = forms.CharField(label='Телефон', max_length=32, required=False)
    email = forms.EmailField(label='Электронная почта', required=False)

    def __init__(self, *args, applicant, **kwargs):
        self.applicant = applicant
        initial = kwargs.setdefault('initial', {})
        initial.update(
            full_name=applicant.full_name,
            phone=applicant.phone,
            email=applicant.email,
        )
        super().__init__(*args, **kwargs)

    def save(self):
        for field in ('full_name', 'phone', 'email'):
            setattr(self.applicant, field, self.cleaned_data[field])
        self.applicant.save(update_fields=('full_name', 'phone', 'email', 'updated_at'))
        user = self.applicant.user
        if user and self.cleaned_data['email']:
            user.email = self.cleaned_data['email']
            user.save(update_fields=('email',))
        return self.applicant
