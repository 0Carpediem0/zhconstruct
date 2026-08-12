from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from complexes.models import (
    ResidentialComplex,
    ResidentialComplexIntakeChannel,
    ResidentialComplexMembership,
    ResidentialComplexNotificationRule,
    ResidentialComplexProvider,
    ResidentialComplexService,
    ServiceRoutingRule,
)
from providers.models import (
    Provider,
    ProviderService,
    ServiceCategory,
    ServiceOffering,
)
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


class ResidentialComplexSetupForm(forms.ModelForm):
    """Минимальная форма подключения нового ЖК командой внедрения."""

    class Meta:
        model = ResidentialComplex
        fields = ('name', 'slug', 'address', 'management_company', 'timezone', 'is_active')
        labels = {
            'name': 'Название ЖК',
            'slug': 'Код в адресе страницы',
            'address': 'Адрес',
            'management_company': 'Управляющая организация',
            'timezone': 'Часовой пояс',
            'is_active': 'ЖК подключён',
        }


class ResidentialComplexProfileForm(forms.ModelForm):
    """Рабочая карточка ЖК и контакт ответственного со стороны заказчика."""

    class Meta:
        model = ResidentialComplex
        fields = (
            'name', 'slug', 'address', 'management_company', 'timezone',
            'contact_name', 'contact_email', 'contact_phone',
        )
        labels = {
            'name': 'Название ЖК',
            'slug': 'Код в адресе страницы',
            'address': 'Адрес',
            'management_company': 'Управляющая организация',
            'timezone': 'Часовой пояс',
            'contact_name': 'Ответственный за внедрение',
            'contact_email': 'Рабочая почта',
            'contact_phone': 'Телефон',
        }


class ComplexTeamMemberForm(forms.Form):
    first_name = forms.CharField(label='Имя', max_length=150)
    last_name = forms.CharField(label='Фамилия', max_length=150, required=False)
    email = forms.EmailField(label='Рабочая почта')
    role = forms.ChoiceField(
        label='Роль в ЖК',
        choices=ResidentialComplexMembership.Role.choices,
    )
    temporary_password = forms.CharField(
        label='Временный пароль',
        min_length=8,
        widget=forms.PasswordInput(render_value=True),
    )

    def __init__(self, *args, residential_complex, **kwargs):
        super().__init__(*args, **kwargs)
        self.residential_complex = residential_complex

    def clean_email(self):
        email = self.cleaned_data['email'].lower()
        user = get_user_model().objects.filter(email__iexact=email).first()
        if user and ResidentialComplexMembership.objects.filter(
            user=user,
            residential_complex=self.residential_complex,
        ).exists():
            raise ValidationError('Этот сотрудник уже добавлен в команду ЖК.')
        return email

    def save(self):
        User = get_user_model()
        email = self.cleaned_data['email']
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            base_username = email.split('@')[0]
            username = base_username
            suffix = 1
            while User.objects.filter(username=username).exists():
                suffix += 1
                username = f'{base_username}-{suffix}'
            user = User(
                username=username,
                email=email,
                first_name=self.cleaned_data['first_name'],
                last_name=self.cleaned_data['last_name'],
            )
            user.set_password(self.cleaned_data['temporary_password'])
            user.save()
        return ResidentialComplexMembership.objects.create(
            user=user,
            residential_complex=self.residential_complex,
            role=self.cleaned_data['role'],
        )


class IntakeChannelSetupForm(forms.ModelForm):
    class Meta:
        model = ResidentialComplexIntakeChannel
        fields = ('channel_type', 'description', 'is_enabled', 'is_verified')
        labels = {
            'channel_type': 'Канал',
            'description': 'Как подключён / примечание',
            'is_enabled': 'Принимать заявки',
            'is_verified': 'Соединение проверено',
        }
        widgets = {'description': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, residential_complex, **kwargs):
        super().__init__(*args, **kwargs)
        self.residential_complex = residential_complex

    def save(self):
        data = self.cleaned_data
        channel, _ = ResidentialComplexIntakeChannel.objects.update_or_create(
            residential_complex=self.residential_complex,
            channel_type=data['channel_type'],
            defaults={
                'description': data['description'],
                'is_enabled': data['is_enabled'],
                'is_verified': data['is_verified'],
                'last_verified_at': timezone.now() if data['is_verified'] else None,
            },
        )
        return channel


class ComplexServiceSetupForm(forms.ModelForm):
    class Meta:
        model = ResidentialComplexService
        fields = (
            'category', 'default_priority', 'response_time_minutes',
            'working_hours', 'auto_assignment_enabled', 'fallback', 'is_active',
        )
        labels = {
            'category': 'Категория услуги',
            'default_priority': 'Приоритет по умолчанию',
            'response_time_minutes': 'Норматив реакции, минут',
            'working_hours': 'Время работы',
            'auto_assignment_enabled': 'Пробовать назначить автоматически',
            'fallback': 'Если назначить не удалось',
            'is_active': 'Услуга доступна в ЖК',
        }

    def __init__(self, *args, residential_complex, **kwargs):
        super().__init__(*args, **kwargs)
        self.residential_complex = residential_complex
        self.fields['category'].queryset = ServiceCategory.objects.filter(is_active=True)

    def save(self):
        data = self.cleaned_data
        setting, _ = ResidentialComplexService.objects.update_or_create(
            residential_complex=self.residential_complex,
            category=data['category'],
            defaults={key: data[key] for key in (
                'default_priority', 'response_time_minutes', 'working_hours',
                'auto_assignment_enabled', 'fallback', 'is_active',
            )},
        )
        return setting


class NotificationRuleSetupForm(forms.ModelForm):
    class Meta:
        model = ResidentialComplexNotificationRule
        fields = ('event', 'recipient', 'is_enabled')
        labels = {
            'event': 'Когда уведомлять',
            'recipient': 'Получатели',
            'is_enabled': 'Правило включено',
        }

    def __init__(self, *args, residential_complex, **kwargs):
        super().__init__(*args, **kwargs)
        self.residential_complex = residential_complex

    def save(self):
        data = self.cleaned_data
        rule, _ = ResidentialComplexNotificationRule.objects.update_or_create(
            residential_complex=self.residential_complex,
            event=data['event'],
            recipient=data['recipient'],
            defaults={'is_enabled': data['is_enabled']},
        )
        return rule


class ProviderLinkSetupForm(forms.Form):
    provider = forms.ModelChoiceField(
        queryset=Provider.objects.filter(is_active=True),
        label='Поставщик',
    )
    service_categories = forms.ModelMultipleChoiceField(
        queryset=ServiceCategory.objects.filter(is_active=True),
        label='Разрешённые категории',
    )
    is_preferred = forms.BooleanField(
        required=False,
        label='Предпочтительный для автоназначения',
    )
    auto_assignment_enabled = forms.BooleanField(
        required=False,
        initial=True,
        label='Разрешить автоназначение',
    )
    contract_number = forms.CharField(required=False, label='Номер договора')
    contract_valid_until = forms.DateField(
        required=False,
        label='Договор действует до',
        widget=forms.DateInput(attrs={'type': 'date'}),
    )
    contact_name = forms.CharField(required=False, label='Контактное лицо')
    contact_email = forms.EmailField(required=False, label='Почта поставщика')
    contact_phone = forms.CharField(required=False, label='Телефон поставщика')

    def __init__(self, *args, residential_complex, **kwargs):
        super().__init__(*args, **kwargs)
        self.residential_complex = residential_complex

    def clean(self):
        cleaned_data = super().clean()
        provider = cleaned_data.get('provider')
        categories = cleaned_data.get('service_categories')
        if provider and categories is not None:
            offered_ids = set(
                ProviderService.objects.filter(
                    provider=provider,
                    is_active=True,
                ).values_list('category_id', flat=True)
            )
            unsupported = [
                category.name
                for category in categories
                if category.pk not in offered_ids
            ]
            if unsupported:
                self.add_error(
                    'service_categories',
                    'Поставщик не оказывает: ' + ', '.join(unsupported),
                )
        return cleaned_data

    def save(self):
        data = self.cleaned_data
        link, created = ResidentialComplexProvider.objects.get_or_create(
            residential_complex=self.residential_complex,
            provider=data['provider'],
            defaults={
                'source': ResidentialComplexProvider.Source.PLATFORM,
                'is_preferred': data['is_preferred'],
                'auto_assignment_enabled': data['auto_assignment_enabled'],
                'contract_number': data['contract_number'],
                'contract_valid_until': data['contract_valid_until'],
                'contact_name': data['contact_name'],
                'contact_email': data['contact_email'],
                'contact_phone': data['contact_phone'],
                'is_active': True,
            },
        )
        if not created:
            # Повторное подключение в этой форме означает расширение договора.
            # Пустые поля не должны стирать уже сохранённые реквизиты поставщика.
            link.is_active = True
            link.is_preferred = link.is_preferred or data['is_preferred']
            link.auto_assignment_enabled = (
                link.auto_assignment_enabled or data['auto_assignment_enabled']
            )
            for field_name in (
                'contract_number', 'contract_valid_until', 'contact_name',
                'contact_email', 'contact_phone',
            ):
                value = data[field_name]
                if value:
                    setattr(link, field_name, value)
            link.save()

        # Категории добавляются к договору, а не заменяют ранее выбранные.
        link.service_categories.add(*data['service_categories'])
        return link


class ProviderContractEditForm(forms.ModelForm):
    """Настройки договора, которыми ЖК управляет без изменения общего каталога."""

    class Meta:
        model = ResidentialComplexProvider
        fields = (
            'service_categories', 'is_preferred', 'auto_assignment_enabled',
            'contract_number', 'contract_valid_until', 'contact_name',
            'contact_email', 'contact_phone', 'is_active',
        )
        labels = {
            'service_categories': 'Услуги по договору',
            'is_preferred': 'Предпочтительный для автоназначения',
            'auto_assignment_enabled': 'Разрешить автоназначение',
            'contract_number': 'Номер договора',
            'contract_valid_until': 'Договор действует до',
            'contact_name': 'Контактное лицо',
            'contact_email': 'Рабочая почта',
            'contact_phone': 'Телефон',
            'is_active': 'Поставщик доступен для ЖК',
        }
        widgets = {
            'contract_valid_until': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['service_categories'].queryset = ServiceCategory.objects.filter(
            provider_services__provider=self.instance.provider,
            provider_services__is_active=True,
            is_active=True,
        ).distinct()


class RoutingRuleSetupForm(forms.Form):
    category = forms.ModelChoiceField(
        queryset=ServiceCategory.objects.filter(is_active=True),
        label='Категория услуги',
    )
    mode = forms.ChoiceField(
        choices=ServiceRoutingRule.Mode.choices,
        label='Маршрут',
    )
    provider = forms.ModelChoiceField(
        queryset=Provider.objects.none(),
        required=False,
        label='Поставщик для прямого маршрута',
    )

    def __init__(self, *args, residential_complex, **kwargs):
        super().__init__(*args, **kwargs)
        self.residential_complex = residential_complex
        self.fields['provider'].queryset = Provider.objects.filter(
            residential_complex_links__residential_complex=residential_complex,
            residential_complex_links__is_active=True,
            is_active=True,
        ).distinct()

    def clean(self):
        cleaned_data = super().clean()
        category = cleaned_data.get('category')
        mode = cleaned_data.get('mode')
        provider = cleaned_data.get('provider')
        if mode == ServiceRoutingRule.Mode.DIRECT and not provider:
            self.add_error('provider', 'Для прямого маршрута выберите поставщика.')
        if category and mode:
            candidate = ServiceRoutingRule(
                residential_complex=self.residential_complex,
                category=category,
                mode=mode,
                provider=(
                    provider if mode == ServiceRoutingRule.Mode.DIRECT else None
                ),
            )
            try:
                candidate.full_clean(
                    exclude=('id',),
                    validate_unique=False,
                    validate_constraints=False,
                )
            except ValidationError as error:
                for field, errors in error.message_dict.items():
                    target = field if field in self.fields else None
                    for message in errors:
                        self.add_error(target, message)
        return cleaned_data

    def save(self):
        provider = self.cleaned_data.get('provider')
        if self.cleaned_data['mode'] == ServiceRoutingRule.Mode.MANUAL:
            provider = None
        candidate = ServiceRoutingRule(
            residential_complex=self.residential_complex,
            category=self.cleaned_data['category'],
            mode=self.cleaned_data['mode'],
            provider=provider,
            is_active=True,
        )
        candidate.full_clean(
            exclude=('id',),
            validate_unique=False,
            validate_constraints=False,
        )
        rule, _ = ServiceRoutingRule.objects.update_or_create(
            residential_complex=self.residential_complex,
            category=self.cleaned_data['category'],
            defaults={
                'mode': self.cleaned_data['mode'],
                'provider': provider,
                'is_active': True,
            },
        )
        return rule


class ServiceOfferingSetupForm(forms.ModelForm):
    """Создаёт карточку услуги, которую увидит житель конкретного ЖК."""

    WEEKDAYS = (
        ('0', 'Понедельник'),
        ('1', 'Вторник'),
        ('2', 'Среда'),
        ('3', 'Четверг'),
        ('4', 'Пятница'),
        ('5', 'Суббота'),
        ('6', 'Воскресенье'),
    )
    available_weekdays = forms.MultipleChoiceField(
        choices=WEEKDAYS,
        label='Дни оказания услуги',
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = ServiceOffering
        fields = (
            'provider', 'category', 'title', 'description', 'price',
            'duration_minutes', 'available_weekdays', 'available_from',
            'available_until', 'capacity_per_slot', 'minimum_lead_hours', 'is_active',
        )
        labels = {
            'provider': 'Поставщик',
            'category': 'Категория',
            'title': 'Название для жителя',
            'description': 'Описание услуги',
            'price': 'Стоимость, ₽',
            'duration_minutes': 'Продолжительность, минут',
            'capacity_per_slot': 'Заказов на одно время',
            'available_from': 'Заказы с',
            'available_until': 'Заказы до',
            'minimum_lead_hours': 'За сколько часов можно заказать',
            'is_active': 'Показывать жителям',
        }
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
            'available_from': forms.TimeInput(attrs={'type': 'time'}),
            'available_until': forms.TimeInput(attrs={'type': 'time'}),
        }

    def __init__(self, *args, residential_complex, **kwargs):
        super().__init__(*args, **kwargs)
        self.residential_complex = residential_complex
        self.fields['provider'].queryset = Provider.objects.filter(
            residential_complex_links__residential_complex=residential_complex,
            residential_complex_links__is_active=True,
            is_active=True,
        ).distinct()
        self.fields['category'].queryset = ServiceCategory.objects.filter(
            complex_settings__residential_complex=residential_complex,
            complex_settings__is_active=True,
            is_active=True,
        ).distinct()

    def clean_available_weekdays(self):
        return [int(value) for value in self.cleaned_data['available_weekdays']]

    def clean(self):
        cleaned_data = super().clean()
        required = (
            'provider', 'category', 'price', 'duration_minutes',
            'available_weekdays', 'available_from', 'available_until',
        )
        if all(cleaned_data.get(field) is not None for field in required):
            candidate = ServiceOffering(
                residential_complex=self.residential_complex,
                **cleaned_data,
            )
            try:
                candidate.full_clean(
                    exclude=('id',),
                    validate_unique=False,
                    validate_constraints=False,
                )
            except ValidationError as error:
                for field, errors in error.message_dict.items():
                    target = field if field in self.fields else None
                    for message in errors:
                        self.add_error(target, message)
        return cleaned_data

    def save(self):
        data = self.cleaned_data.copy()
        provider = data.pop('provider')
        category = data.pop('category')
        offering, _ = ServiceOffering.objects.update_or_create(
            residential_complex=self.residential_complex,
            provider=provider,
            category=category,
            defaults=data,
        )
        offering.full_clean()
        offering.save()
        return offering


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

    def __init__(self, *args, user, residential_complex=None, **kwargs):
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
        if residential_complex is not None:
            complexes = complexes.filter(pk=residential_complex.pk)
            self.fields['residential_complex'].initial = residential_complex
            self.fields['residential_complex'].widget = forms.HiddenInput()
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
