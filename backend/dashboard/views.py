from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from complexes.models import (
    ResidentialComplex,
    ResidentialComplexMembership,
    ResidentialComplexProvider,
    ServiceRoutingRule,
)
from complexes.selectors import visible_complexes_for
from providers.models import ProviderMembership, ServiceCategory
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
    ProviderLinkSetupForm,
    ResidentialComplexSetupForm,
    RoutingRuleSetupForm,
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


@internal_user_required
def implementation_complex_create(request):
    _require_platform_operator(request.user)
    form = ResidentialComplexSetupForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        residential_complex = form.save()
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
def implementation_complex(request, complex_slug):
    _require_platform_operator(request.user)
    residential_complex = get_object_or_404(
        ResidentialComplex.objects.filter(slug=complex_slug),
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
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'connect_provider' and provider_form.is_valid():
            provider_form.save()
            messages.success(request, 'Поставщик подключён к ЖК.')
            return redirect(
                'dashboard:implementation-complex',
                complex_slug=residential_complex.slug,
            )
        if action == 'save_routing' and routing_form.is_valid():
            routing_form.save()
            messages.success(request, 'Правило маршрутизации сохранено.')
            return redirect(
                'dashboard:implementation-complex',
                complex_slug=residential_complex.slug,
            )

    context = {
        **_base_context(request),
        'complex': residential_complex,
        'provider_links': residential_complex.provider_links.select_related(
            'provider',
        ).prefetch_related('service_categories'),
        'routing_rules': residential_complex.routing_rules.select_related(
            'category',
            'provider',
        ),
        'memberships': residential_complex.memberships.select_related('user'),
        'provider_form': provider_form,
        'routing_form': routing_form,
    }
    return render(request, 'dashboard/implementation_complex.html', context)


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
        'categories': ServiceCategory.objects.filter(is_active=True),
    }
    return render(request, 'dashboard/directories.html', context)
