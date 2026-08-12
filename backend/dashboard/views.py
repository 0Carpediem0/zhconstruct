from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from complexes.models import (
    ComplexConfigurationEvent,
    ResidentialComplex,
    ResidentialComplexMembership,
    ResidentialComplexProvider,
    ServiceRoutingRule,
)
from complexes.onboarding import (
    build_readiness,
    launch_complex,
    run_implementation_test,
)
from complexes.selectors import visible_complexes_for
from providers.models import ProviderMembership, ServiceCategory, ServiceOffering
from providers.selectors import visible_providers_for
from tickets.filters import filter_ticket_queryset
from tickets.models import Ticket
from tickets.permissions import (
    can_assign_employee,
    can_assign_provider,
    can_transition_ticket,
    is_complex_staff_user,
    visible_tickets_for,
)
from tickets.services import apply_initial_routing, assign_employee, assign_provider

from .forms import (
    ComplexServiceSetupForm,
    ComplexTeamMemberForm,
    IntakeChannelSetupForm,
    NotificationRuleSetupForm,
    ProviderContractEditForm,
    ProviderLinkSetupForm,
    ResidentialComplexProfileForm,
    ResidentialComplexSetupForm,
    RoutingRuleSetupForm,
    ServiceOfferingSetupForm,
    TicketWebCreateForm,
)
from .access import internal_user_required


def _is_platform_operator(user):
    return user.is_superuser or user.platform_role == user.PlatformRole.IMPLEMENTER


def _workspace_complex_for(user, complex_slug):
    queryset = ResidentialComplex.objects.filter(slug=complex_slug, is_active=True)
    if not user.is_superuser:
        queryset = queryset.filter(
            memberships__user=user,
            memberships__role__in={
                ResidentialComplexMembership.Role.DISPATCHER,
                ResidentialComplexMembership.Role.MANAGER,
            },
            memberships__is_active=True,
        )
    return get_object_or_404(queryset.distinct())


def _ticket_queryset_for(user, workspace_complex=None):
    queryset = Ticket.objects.select_related(
        'residential_complex',
        'applicant',
        'category',
        'provider',
        'assignee',
        'service_order__offering',
    )
    if workspace_complex is not None:
        return visible_tickets_for(user, queryset).filter(
            residential_complex=workspace_complex,
        )
    if user.is_superuser:
        return queryset.none()
    return queryset.filter(
        Q(
            provider__memberships__user=user,
            provider__memberships__role=ProviderMembership.Role.MANAGER,
            provider__memberships__is_active=True,
        )
        | Q(assignee=user)
    ).distinct()


def _role_labels(user):
    if user.is_superuser:
        return ['Администратор платформы']
    if user.platform_role == user.PlatformRole.IMPLEMENTER:
        return ['Внедренец платформы']
    labels = list(
        user.residential_complex_memberships.filter(is_active=True).values_list(
            'role',
            flat=True,
        )
    )
    provider_labels = list(
        user.provider_memberships.filter(is_active=True).values_list('role', flat=True)
    )
    complex_role_names = {
        ResidentialComplexMembership.Role.DISPATCHER: 'Диспетчер',
        ResidentialComplexMembership.Role.MANAGER: 'Руководитель ЖК',
    }
    provider_role_names = {
        ProviderMembership.Role.MANAGER: 'Руководитель поставщика',
        ProviderMembership.Role.EMPLOYEE: 'Исполнитель',
    }
    resolved_labels = [
        complex_role_names[role]
        for role in labels
        if role in complex_role_names
    ]
    resolved_labels.extend(
        provider_role_names[role]
        for role in provider_labels
        if role in provider_role_names
    )
    return list(dict.fromkeys(resolved_labels))


def _base_context(request, workspace_complex=None):
    return {
        'role_labels': _role_labels(request.user),
        'workspace_complex': workspace_complex,
        'can_register_ticket': workspace_complex is not None
        and (
            request.user.is_superuser
            or ResidentialComplexMembership.objects.filter(
                user=request.user,
                residential_complex=workspace_complex,
                role__in={
                    ResidentialComplexMembership.Role.DISPATCHER,
                    ResidentialComplexMembership.Role.MANAGER,
                },
                is_active=True,
            ).exists()
        ),
    }


def _redirect_to_ticket(ticket, workspace_complex=None):
    if workspace_complex is not None:
        return redirect(
            'dashboard:complex-ticket-detail',
            complex_slug=workspace_complex.slug,
            pk=ticket.pk,
        )
    return redirect('dashboard:ticket-detail', pk=ticket.pk)


def _require_platform_operator(user):
    if not _is_platform_operator(user):
        raise PermissionDenied


def _require_implementer(user):
    if user.platform_role != user.PlatformRole.IMPLEMENTER:
        raise PermissionDenied


@internal_user_required
def implementation_complex_create(request):
    _require_implementer(request.user)
    form = ResidentialComplexSetupForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        residential_complex = form.save()
        ComplexConfigurationEvent.objects.create(
            residential_complex=residential_complex,
            actor=request.user,
            event_type=ComplexConfigurationEvent.Type.PROFILE,
            description='Создан контур нового ЖК.',
        )
        messages.success(request, f'ЖК «{residential_complex.name}» подключён.')
        return redirect(
            'dashboard:implementation-complex',
            complex_slug=residential_complex.slug,
        )
    return render(
        request,
        'dashboard/implementation_complex_form.html',
        {**_base_context(request), 'form': form},
    )


@internal_user_required
def implementation_complex(request, complex_slug, section='overview'):
    _require_platform_operator(request.user)
    sections = {
        'overview': 'Обзор',
        'profile': 'Данные ЖК',
        'team': 'Команда',
        'channels': 'Каналы заявок',
        'services': 'Услуги',
        'providers': 'Поставщики',
        'routing': 'Маршрутизация',
        'catalog': 'Витрина услуг',
        'launch': 'Проверка и запуск',
        'audit': 'История',
    }
    if section not in sections:
        raise PermissionDenied
    residential_complex = get_object_or_404(
        ResidentialComplex.objects.filter(slug=complex_slug),
    )
    profile_form = ResidentialComplexProfileForm(
        request.POST or None,
        instance=residential_complex,
        prefix='profile',
    )
    team_form = ComplexTeamMemberForm(
        request.POST or None,
        residential_complex=residential_complex,
        prefix='team',
    )
    channel_form = IntakeChannelSetupForm(
        request.POST or None,
        residential_complex=residential_complex,
        prefix='channel',
    )
    service_form = ComplexServiceSetupForm(
        request.POST or None,
        residential_complex=residential_complex,
        prefix='service',
    )
    notification_form = NotificationRuleSetupForm(
        request.POST or None,
        residential_complex=residential_complex,
        prefix='notification',
    )
    provider_form = ProviderLinkSetupForm(
        request.POST or None,
        residential_complex=residential_complex,
        prefix='provider',
    )
    routing_form = RoutingRuleSetupForm(
        request.POST or None,
        residential_complex=residential_complex,
        prefix='routing',
    )
    offering_form = ServiceOfferingSetupForm(
        request.POST or None,
        residential_complex=residential_complex,
        prefix='offering',
    )
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'save_profile' and profile_form.is_valid():
            residential_complex = profile_form.save()
            _record_configuration_event(
                residential_complex, request.user,
                ComplexConfigurationEvent.Type.PROFILE,
                'Обновлены реквизиты и контактные данные ЖК.',
            )
            messages.success(request, 'Карточка ЖК сохранена.')
            return _redirect_to_implementation_section(residential_complex, 'team')
        if action == 'add_team_member' and team_form.is_valid():
            membership = team_form.save()
            _record_configuration_event(
                residential_complex, request.user,
                ComplexConfigurationEvent.Type.TEAM,
                f'В команду добавлен {membership.user.get_full_name() or membership.user.username}.',
            )
            messages.success(request, 'Сотрудник добавлен в команду ЖК.')
            return _redirect_after_wizard_save(
                request, residential_complex, current='team', next_section='channels',
            )
        if action == 'save_channel' and channel_form.is_valid():
            channel = channel_form.save()
            _record_configuration_event(
                residential_complex, request.user,
                ComplexConfigurationEvent.Type.CHANNEL,
                f'Настроен канал «{channel.get_channel_type_display()}».',
            )
            messages.success(request, 'Канал поступления заявок сохранён.')
            return _redirect_after_wizard_save(
                request, residential_complex, current='channels', next_section='services',
            )
        if action == 'save_notification' and notification_form.is_valid():
            rule = notification_form.save()
            _record_configuration_event(
                residential_complex, request.user,
                ComplexConfigurationEvent.Type.CHANNEL,
                f'Настроено уведомление «{rule.get_event_display()}».',
            )
            messages.success(request, 'Правило уведомлений сохранено.')
            return _redirect_to_implementation_section(residential_complex, 'channels')
        if action == 'save_service' and service_form.is_valid():
            service = service_form.save()
            _record_configuration_event(
                residential_complex, request.user,
                ComplexConfigurationEvent.Type.SERVICE,
                f'Настроена услуга «{service.category.name}».',
            )
            messages.success(request, 'Параметры услуги сохранены.')
            return _redirect_after_wizard_save(
                request, residential_complex, current='services', next_section='providers',
            )
        if action == 'connect_provider' and provider_form.is_valid():
            link = provider_form.save()
            _record_configuration_event(
                residential_complex, request.user,
                ComplexConfigurationEvent.Type.PROVIDER,
                f'Подключён поставщик «{link.provider.name}».',
            )
            messages.success(request, 'Поставщик подключён к ЖК.')
            return _redirect_after_wizard_save(
                request, residential_complex, current='providers', next_section='routing',
            )
        if action == 'save_routing' and routing_form.is_valid():
            rule = routing_form.save()
            _record_configuration_event(
                residential_complex, request.user,
                ComplexConfigurationEvent.Type.ROUTING,
                f'Сохранён маршрут для услуги «{rule.category.name}».',
            )
            messages.success(request, 'Правило маршрутизации сохранено.')
            return _redirect_after_wizard_save(
                request, residential_complex, current='routing', next_section='catalog',
            )
        if action == 'save_offering' and offering_form.is_valid():
            offering = offering_form.save()
            _record_configuration_event(
                residential_complex, request.user,
                ComplexConfigurationEvent.Type.SERVICE,
                f'Опубликовано предложение «{offering.title}» за {offering.price} ₽.',
            )
            messages.success(request, 'Карточка услуги для жителей сохранена.')
            return _redirect_after_wizard_save(
                request, residential_complex, current='catalog', next_section='launch',
            )
        if action == 'run_test':
            test_run = run_implementation_test(residential_complex, request.user)
            if test_run.is_successful:
                messages.success(request, 'Тест пройден: маршруты работают ожидаемо.')
            else:
                messages.error(request, 'Тест не пройден. Проверьте список результатов.')
            return _redirect_to_implementation_section(residential_complex, 'launch')
        if action == 'launch_complex':
            launched, _ = launch_complex(residential_complex, request.user)
            if launched:
                messages.success(request, 'ЖК запущен и переведён в рабочий режим.')
            else:
                messages.error(request, 'До запуска нужно закрыть обязательные пункты.')
            return _redirect_to_implementation_section(residential_complex, 'launch')

    readiness = build_readiness(residential_complex)

    context = {
        **_base_context(request),
        'complex': residential_complex,
        'sections': sections,
        'active_section': section,
        'readiness': readiness,
        'provider_links': residential_complex.provider_links.select_related(
            'provider',
        ).prefetch_related('service_categories'),
        'routing_rules': residential_complex.routing_rules.select_related(
            'category',
            'provider',
        ),
        'service_offerings': ServiceOffering.objects.filter(
            residential_complex=residential_complex,
        ).select_related('provider', 'category'),
        'memberships': residential_complex.memberships.select_related('user'),
        'channels': residential_complex.intake_channels.all(),
        'notification_rules': residential_complex.notification_rules.all(),
        'service_settings': residential_complex.service_settings.select_related('category'),
        'latest_test': residential_complex.implementation_test_runs.first(),
        'events': residential_complex.configuration_events.select_related('actor')[:100],
        'profile_form': profile_form,
        'team_form': team_form,
        'channel_form': channel_form,
        'notification_form': notification_form,
        'service_form': service_form,
        'provider_form': provider_form,
        'routing_form': routing_form,
        'offering_form': offering_form,
    }
    return render(request, 'dashboard/implementation_complex.html', context)


def _record_configuration_event(residential_complex, actor, event_type, description):
    ComplexConfigurationEvent.objects.create(
        residential_complex=residential_complex,
        actor=actor,
        event_type=event_type,
        description=description,
    )


def _redirect_to_implementation_section(residential_complex, section):
    return redirect(
        'dashboard:implementation-complex-section',
        complex_slug=residential_complex.slug,
        section=section,
    )


def _redirect_after_wizard_save(
    request,
    residential_complex,
    *,
    current,
    next_section,
):
    """Оставляет внедренца добавлять элементы или переводит к следующему шагу."""

    section = next_section if request.POST.get('continue') == '1' else current
    return _redirect_to_implementation_section(residential_complex, section)


@internal_user_required
def home(request, complex_slug=None):
    if complex_slug is None and _is_platform_operator(request.user):
        complexes = ResidentialComplex.objects.filter(is_active=True).prefetch_related(
            'provider_links__provider',
            'routing_rules__category',
            'memberships',
        )
        return render(
            request,
            'dashboard/implementation_home.html',
            {
                **_base_context(request),
                'complexes': complexes,
            },
        )

    workspace_complex = None
    if complex_slug is not None:
        workspace_complex = _workspace_complex_for(request.user, complex_slug)
    elif is_complex_staff_user(request.user):
        memberships = ResidentialComplexMembership.objects.filter(
            user=request.user,
            role__in={
                ResidentialComplexMembership.Role.DISPATCHER,
                ResidentialComplexMembership.Role.MANAGER,
            },
            is_active=True,
            residential_complex__is_active=True,
        ).select_related('residential_complex')
        if memberships.count() == 1:
            return redirect(
                'dashboard:complex-home',
                complex_slug=memberships.get().residential_complex.slug,
            )
        return render(
            request,
            'dashboard/workspace_select.html',
            {**_base_context(request), 'memberships': memberships},
        )

    tickets = _ticket_queryset_for(request.user, workspace_complex)
    active_statuses = {
        Ticket.Status.ASSIGNED,
        Ticket.Status.ACCEPTED,
        Ticket.Status.IN_PROGRESS,
    }
    summary = tickets.aggregate(
        total=Count('id'),
        new=Count(
            'id',
            filter=Q(status__in={Ticket.Status.NEW, Ticket.Status.AWAITING_ASSIGNMENT}),
        ),
        active=Count('id', filter=Q(status__in=active_statuses)),
        completed=Count('id', filter=Q(status=Ticket.Status.COMPLETED)),
    )
    context = {
        **_base_context(request, workspace_complex),
        'summary': summary,
        'recent_tickets': tickets[:6],
        'status_counts': tickets.values('status').annotate(total=Count('id')),
    }
    return render(request, 'dashboard/home.html', context)


@internal_user_required
def ticket_list(request, complex_slug=None):
    if complex_slug is None and (
        _is_platform_operator(request.user) or is_complex_staff_user(request.user)
    ):
        return redirect('dashboard:home')
    workspace_complex = (
        _workspace_complex_for(request.user, complex_slug)
        if complex_slug is not None
        else None
    )
    tickets = filter_ticket_queryset(
        _ticket_queryset_for(request.user, workspace_complex),
        request.GET,
    )
    paginator = Paginator(tickets, 20)
    page = paginator.get_page(request.GET.get('page'))
    query_parameters = request.GET.copy()
    query_parameters.pop('page', None)
    context = {
        **_base_context(request, workspace_complex),
        'page': page,
        'query_string': query_parameters.urlencode(),
        'statuses': Ticket.Status.choices,
        'priorities': Ticket.Priority.choices,
        'sources': Ticket.Source.choices,
        'complexes': (
            ResidentialComplex.objects.filter(pk=workspace_complex.pk)
            if workspace_complex
            else visible_complexes_for(request.user)
        ),
        'providers': visible_providers_for(request.user),
        'categories': ServiceCategory.objects.filter(is_active=True),
    }
    return render(request, 'dashboard/ticket_list.html', context)


@internal_user_required
def ticket_create(request, complex_slug=None):
    if complex_slug is None:
        return redirect('dashboard:home')
    workspace_complex = _workspace_complex_for(request.user, complex_slug)
    if not (request.user.is_superuser or is_complex_staff_user(request.user)):
        raise PermissionDenied
    form = TicketWebCreateForm(
        request.POST or None,
        user=request.user,
        residential_complex=workspace_complex,
    )
    if request.method == 'POST' and form.is_valid():
        ticket = form.save()
        ticket = apply_initial_routing(ticket, changed_by=request.user)
        if ticket.status == Ticket.Status.ASSIGNED:
            messages.success(
                request,
                f'Заявка №{ticket.pk} зарегистрирована и сразу направлена '
                f'поставщику «{ticket.provider.name}».',
            )
        else:
            messages.success(
                request,
                f'Заявка №{ticket.pk} зарегистрирована в очереди ТСЖ.',
            )
        return redirect(
            'dashboard:complex-ticket-detail',
            complex_slug=workspace_complex.slug,
            pk=ticket.pk,
        )
    return render(
        request,
        'dashboard/ticket_form.html',
        {**_base_context(request, workspace_complex), 'form': form},
    )


@internal_user_required
def ticket_detail(request, pk, complex_slug=None):
    if complex_slug is None and _is_platform_operator(request.user):
        return redirect('dashboard:home')
    workspace_complex = (
        _workspace_complex_for(request.user, complex_slug)
        if complex_slug is not None
        else None
    )
    ticket = get_object_or_404(
        _ticket_queryset_for(request.user, workspace_complex),
        pk=pk,
    )
    provider_links = ResidentialComplexProvider.objects.filter(
        residential_complex=ticket.residential_complex,
        service_categories=ticket.category,
        provider__services__category=ticket.category,
        provider__services__is_active=True,
        provider__is_active=True,
        is_active=True,
    ).select_related('provider').distinct()
    employees = get_user_model().objects.none()
    if ticket.provider_id:
        employees = get_user_model().objects.filter(
            provider_memberships__provider=ticket.provider,
            provider_memberships__role=ProviderMembership.Role.EMPLOYEE,
            provider_memberships__is_active=True,
            is_active=True,
        ).distinct()

    transitions = []
    allowed_statuses = Ticket.ALLOWED_STATUS_TRANSITIONS.get(ticket.status, set())
    for value, label in Ticket.Status.choices:
        if value not in allowed_statuses:
            continue
        if can_transition_ticket(request.user, ticket, value):
            if value in {Ticket.Status.IN_PROGRESS, Ticket.Status.COMPLETED} and not (
                ticket.assignee_id
            ):
                continue
            transitions.append((value, label))

    routing_rule = ServiceRoutingRule.objects.filter(
        residential_complex=ticket.residential_complex,
        category=ticket.category,
        is_active=True,
    ).select_related('provider').first()
    if routing_rule and routing_rule.mode == ServiceRoutingRule.Mode.DIRECT:
        routing_description = f'Сразу поставщику: {routing_rule.provider.name}'
    elif routing_rule and routing_rule.mode == ServiceRoutingRule.Mode.MANUAL:
        routing_description = 'Явно оставлять диспетчеру ЖК'
    else:
        routing_description = (
            'Автовыбор единственного или предпочтительного поставщика'
        )

    context = {
        **_base_context(request, workspace_complex),
        'ticket': ticket,
        'provider_links': provider_links,
        'employees': employees,
        'can_assign_provider': can_assign_provider(request.user, ticket)
        and ticket.status
        in {Ticket.Status.NEW, Ticket.Status.AWAITING_ASSIGNMENT},
        'can_assign_employee': can_assign_employee(request.user, ticket)
        and ticket.status in {Ticket.Status.ASSIGNED, Ticket.Status.ACCEPTED},
        'transitions': transitions,
        'history': ticket.status_history.select_related('changed_by'),
        'routing_rule': routing_rule,
        'routing_description': routing_description,
    }
    return render(request, 'dashboard/ticket_detail.html', context)


@internal_user_required
@require_POST
def ticket_assign_provider(request, pk, complex_slug=None):
    workspace_complex = (
        _workspace_complex_for(request.user, complex_slug)
        if complex_slug is not None
        else None
    )
    ticket = get_object_or_404(
        _ticket_queryset_for(request.user, workspace_complex),
        pk=pk,
    )
    if not can_assign_provider(request.user, ticket):
        raise PermissionDenied
    provider_link = get_object_or_404(
        ResidentialComplexProvider.objects.select_related('provider'),
        pk=request.POST.get('provider_link'),
        residential_complex=ticket.residential_complex,
        service_categories=ticket.category,
        provider__services__category=ticket.category,
        provider__services__is_active=True,
        is_active=True,
    )
    try:
        assign_provider(
            ticket,
            provider=provider_link.provider,
            changed_by=request.user,
            comment=request.POST.get('comment', ''),
        )
        messages.success(request, 'Поставщик назначен.')
    except ValidationError as error:
        messages.error(request, '; '.join(error.messages))
    return _redirect_to_ticket(ticket, workspace_complex)


@internal_user_required
@require_POST
def ticket_assign_employee(request, pk, complex_slug=None):
    workspace_complex = (
        _workspace_complex_for(request.user, complex_slug)
        if complex_slug is not None
        else None
    )
    ticket = get_object_or_404(
        _ticket_queryset_for(request.user, workspace_complex),
        pk=pk,
    )
    if not can_assign_employee(request.user, ticket):
        raise PermissionDenied
    employee = get_object_or_404(
        get_user_model().objects.filter(is_active=True),
        pk=request.POST.get('employee'),
        provider_memberships__provider=ticket.provider,
        provider_memberships__is_active=True,
    )
    try:
        assign_employee(ticket, employee=employee)
        messages.success(request, 'Исполнитель назначен.')
    except ValidationError as error:
        messages.error(request, '; '.join(error.messages))
    return _redirect_to_ticket(ticket, workspace_complex)


@internal_user_required
@require_POST
def ticket_change_status(request, pk, complex_slug=None):
    workspace_complex = (
        _workspace_complex_for(request.user, complex_slug)
        if complex_slug is not None
        else None
    )
    ticket = get_object_or_404(
        _ticket_queryset_for(request.user, workspace_complex),
        pk=pk,
    )
    new_status = request.POST.get('status')
    if not can_transition_ticket(request.user, ticket, new_status):
        raise PermissionDenied
    try:
        ticket.transition_to(
            new_status,
            changed_by=request.user,
            comment=request.POST.get('comment', ''),
        )
        messages.success(request, 'Статус заявки обновлён.')
    except ValidationError as error:
        messages.error(request, '; '.join(error.messages))
    return _redirect_to_ticket(ticket, workspace_complex)


@internal_user_required
def directories(request, complex_slug=None):
    if complex_slug is None and (
        _is_platform_operator(request.user) or is_complex_staff_user(request.user)
    ):
        return redirect('dashboard:home')
    workspace_complex = (
        _workspace_complex_for(request.user, complex_slug)
        if complex_slug is not None
        else None
    )
    complexes = (
        ResidentialComplex.objects.filter(pk=workspace_complex.pk)
        if workspace_complex
        else visible_complexes_for(request.user)
    )
    context = {
        **_base_context(request, workspace_complex),
        'complexes': complexes.prefetch_related(
            'provider_links__provider',
            'routing_rules__category',
            'routing_rules__provider',
        ),
        'providers': (
            visible_providers_for(request.user).filter(
                residential_complex_links__residential_complex=workspace_complex,
                residential_complex_links__is_active=True,
            ).distinct()
            if workspace_complex
            else visible_providers_for(request.user)
        ),
        'provider_links': (
            ResidentialComplexProvider.objects.filter(
                residential_complex=workspace_complex,
            ).select_related('provider').prefetch_related('service_categories')
            if workspace_complex
            else ResidentialComplexProvider.objects.none()
        ),
        'categories': ServiceCategory.objects.filter(is_active=True),
    }
    return render(request, 'dashboard/directories.html', context)


@internal_user_required
def complex_provider_edit(request, complex_slug, link_pk):
    """Позволяет ЖК менять только собственный договор с поставщиком."""

    workspace_complex = _workspace_complex_for(request.user, complex_slug)
    link = get_object_or_404(
        ResidentialComplexProvider.objects.select_related(
            'provider',
            'residential_complex',
        ),
        pk=link_pk,
        residential_complex=workspace_complex,
    )
    form = ProviderContractEditForm(request.POST or None, instance=link)
    if request.method == 'POST' and form.is_valid():
        form.save()
        _record_configuration_event(
            workspace_complex,
            request.user,
            ComplexConfigurationEvent.Type.PROVIDER,
            f'ЖК обновил условия работы с поставщиком «{link.provider.name}».',
        )
        messages.success(request, 'Настройки поставщика сохранены.')
        return redirect(
            'dashboard:complex-directories',
            complex_slug=workspace_complex.slug,
        )
    return render(
        request,
        'dashboard/complex_provider_form.html',
        {
            **_base_context(request, workspace_complex),
            'complex': workspace_complex,
            'provider_link': link,
            'form': form,
        },
    )
