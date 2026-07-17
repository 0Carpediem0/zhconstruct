from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from complexes.models import (
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

from .forms import TicketWebCreateForm
from .access import internal_user_required


def _ticket_queryset_for(user):
    return visible_tickets_for(
        user,
        Ticket.objects.select_related(
            'residential_complex',
            'applicant',
            'category',
            'provider',
            'assignee',
        ),
    )


def _role_labels(user):
    if user.is_superuser:
        return ['Администратор платформы']
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


def _base_context(request):
    return {
        'role_labels': _role_labels(request.user),
        'can_register_ticket': request.user.is_superuser
        or is_complex_staff_user(request.user),
    }


@internal_user_required
def home(request):
    tickets = _ticket_queryset_for(request.user)
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
        **_base_context(request),
        'summary': summary,
        'recent_tickets': tickets[:6],
        'status_counts': tickets.values('status').annotate(total=Count('id')),
    }
    return render(request, 'dashboard/home.html', context)


@internal_user_required
def ticket_list(request):
    tickets = filter_ticket_queryset(
        _ticket_queryset_for(request.user),
        request.GET,
    )
    paginator = Paginator(tickets, 20)
    page = paginator.get_page(request.GET.get('page'))
    query_parameters = request.GET.copy()
    query_parameters.pop('page', None)
    context = {
        **_base_context(request),
        'page': page,
        'query_string': query_parameters.urlencode(),
        'statuses': Ticket.Status.choices,
        'priorities': Ticket.Priority.choices,
        'sources': Ticket.Source.choices,
        'complexes': visible_complexes_for(request.user),
        'providers': visible_providers_for(request.user),
        'categories': ServiceCategory.objects.filter(is_active=True),
    }
    return render(request, 'dashboard/ticket_list.html', context)


@internal_user_required
def ticket_create(request):
    if not (
        request.user.is_superuser or is_complex_staff_user(request.user)
    ):
        raise PermissionDenied
    form = TicketWebCreateForm(request.POST or None, user=request.user)
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
        return redirect('dashboard:ticket-detail', pk=ticket.pk)
    return render(
        request,
        'dashboard/ticket_form.html',
        {**_base_context(request), 'form': form},
    )


@internal_user_required
def ticket_detail(request, pk):
    ticket = get_object_or_404(_ticket_queryset_for(request.user), pk=pk)
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

    context = {
        **_base_context(request),
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
        'routing_rule': ServiceRoutingRule.objects.filter(
            residential_complex=ticket.residential_complex,
            category=ticket.category,
            is_active=True,
        ).select_related('provider').first(),
    }
    return render(request, 'dashboard/ticket_detail.html', context)


@internal_user_required
@require_POST
def ticket_assign_provider(request, pk):
    ticket = get_object_or_404(_ticket_queryset_for(request.user), pk=pk)
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
    return redirect('dashboard:ticket-detail', pk=ticket.pk)


@internal_user_required
@require_POST
def ticket_assign_employee(request, pk):
    ticket = get_object_or_404(_ticket_queryset_for(request.user), pk=pk)
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
    return redirect('dashboard:ticket-detail', pk=ticket.pk)


@internal_user_required
@require_POST
def ticket_change_status(request, pk):
    ticket = get_object_or_404(_ticket_queryset_for(request.user), pk=pk)
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
    return redirect('dashboard:ticket-detail', pk=ticket.pk)


@internal_user_required
def directories(request):
    context = {
        **_base_context(request),
        'complexes': visible_complexes_for(request.user).prefetch_related(
            'provider_links__provider',
            'routing_rules__category',
            'routing_rules__provider',
        ),
        'providers': visible_providers_for(request.user),
        'categories': ServiceCategory.objects.filter(is_active=True),
    }
    return render(request, 'dashboard/directories.html', context)
