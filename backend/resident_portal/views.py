from django.contrib import messages
from django.contrib.auth import login, logout
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone

from providers.models import ServiceOffering
from tickets.models import Ticket
from tickets.services import apply_initial_routing

from .access import resident_required
from .forms import (
    ResidentAuthenticationForm,
    ResidentProfileForm,
    ResidentServiceOrderForm,
    ResidentTicketForm,
)
from .models import ServiceOrderDetails


SERVICE_STYLES = {
    'dog-walking': ('service-dog', 'Выгул собаки', 'Забота о питомце, пока вы заняты'),
    'trash-removal': ('service-trash', 'Вынос мусора', 'Заберём пакеты прямо от двери'),
    'entrance-cleaning': ('service-cleaning', 'Клининг', 'Уборка квартиры и общих зон'),
}
MARKET_SERVICE_SLUGS = tuple(SERVICE_STYLES)


def resident_login(request):
    if request.user.is_authenticated and getattr(
        request.user,
        'applicant_profile',
        None,
    ):
        return redirect('resident_portal:home')
    form = ResidentAuthenticationForm(request, data=request.POST or None)
    if request.method == 'POST' and form.is_valid():
        login(request, form.get_user())
        next_url = request.GET.get('next')
        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return redirect(next_url)
        return redirect('resident_portal:home')
    return render(request, 'resident_portal/login.html', {'form': form})


@require_POST
def resident_logout(request):
    logout(request)
    return redirect('resident_portal:login')


def _base_context(request, active_nav):
    return {
        'applicant': request.applicant,
        'complex': request.applicant.residential_complex,
        'active_nav': active_nav,
    }


@resident_required
def home(request):
    tickets = request.applicant.tickets.select_related('category', 'provider')
    context = {
        **_base_context(request, 'home'),
        'utility_account': getattr(request.applicant, 'utility_account', None),
        'news_items': request.applicant.residential_complex.resident_news.filter(
            is_published=True,
        )[:4],
        'recent_tickets': tickets[:3],
    }
    return render(request, 'resident_portal/home.html', context)


@resident_required
def payments(request):
    return render(
        request,
        'resident_portal/payments.html',
        {
            **_base_context(request, 'home'),
            'utility_account': getattr(request.applicant, 'utility_account', None),
        },
    )


@resident_required
def services(request):
    offerings = ServiceOffering.objects.filter(
        residential_complex=request.applicant.residential_complex,
        is_active=True,
        category__is_active=True,
        category__slug__in=MARKET_SERVICE_SLUGS,
        provider__is_active=True,
    ).select_related('category', 'provider')
    cards = []
    for offering in offerings:
        style, title, subtitle = SERVICE_STYLES.get(
            offering.category.slug,
            ('service-default', offering.title, offering.description),
        )
        cards.append(
            {
                'offering': offering,
                'style': style,
                'title': title,
                'subtitle': subtitle,
            },
        )
    cards.sort(
        key=lambda card: MARKET_SERVICE_SLUGS.index(
            card['offering'].category.slug,
        ),
    )
    return render(
        request,
        'resident_portal/services.html',
        {**_base_context(request, 'services'), 'service_cards': cards},
    )


@resident_required
def service_detail(request, offering_pk):
    offering = get_object_or_404(
        ServiceOffering.objects.select_related('category', 'provider'),
        pk=offering_pk,
        residential_complex=request.applicant.residential_complex,
        is_active=True,
        provider__is_active=True,
        category__is_active=True,
        category__slug__in=MARKET_SERVICE_SLUGS,
    )
    form = ResidentServiceOrderForm(
        request.POST or None,
        applicant=request.applicant,
        offering=offering,
        user=request.user,
    )
    if request.method == 'POST' and form.is_valid():
        try:
            ticket = form.save()
        except ValidationError as error:
            for field, errors in error.message_dict.items():
                target = field if field in form.fields else None
                for message in errors:
                    form.add_error(target, message)
        else:
            messages.success(request, f'Заказ №{ticket.pk} создан и передан в работу.')
            return redirect('resident_portal:ticket-detail', pk=ticket.pk)
    return render(
        request,
        'resident_portal/service_detail.html',
        {**_base_context(request, 'services'), 'offering': offering, 'form': form},
    )


@resident_required
def news(request):
    return render(
        request,
        'resident_portal/news.html',
        {
            **_base_context(request, 'news'),
            'news_items': request.applicant.residential_complex.resident_news.filter(
                is_published=True,
            ),
            'orders': request.applicant.tickets.filter(
                kind=Ticket.Kind.SERVICE_ORDER,
            ).select_related('category')[:5],
        },
    )


@resident_required
def ticket_list(request):
    return render(
        request,
        'resident_portal/tickets.html',
        {
            **_base_context(request, 'tickets'),
            'tickets': request.applicant.tickets.select_related('category', 'provider'),
        },
    )


@resident_required
def ticket_create(request):
    form = ResidentTicketForm(
        request.POST or None,
        applicant=request.applicant,
        kind=Ticket.Kind.APPEAL,
    )
    if request.method == 'POST' and form.is_valid():
        ticket = apply_initial_routing(form.save(), changed_by=request.user)
        messages.success(request, f'Обращение №{ticket.pk} отправлено.')
        return redirect('resident_portal:ticket-detail', pk=ticket.pk)
    return render(
        request,
        'resident_portal/ticket_form.html',
        {**_base_context(request, 'tickets'), 'form': form},
    )


@resident_required
def ticket_detail(request, pk):
    ticket = get_object_or_404(
        request.applicant.tickets.select_related(
            'category', 'provider', 'assignee', 'service_order__offering',
        ),
        pk=pk,
    )
    return render(
        request,
        'resident_portal/ticket_detail.html',
        {
            **_base_context(request, 'tickets'),
            'ticket': ticket,
            'resident_status': ticket.get_resident_status_display(),
            'history': ticket.status_history.all(),
        },
    )


@resident_required
@require_POST
def confirm_service_order(request, pk):
    ticket = get_object_or_404(
        request.applicant.tickets.select_related('service_order'),
        pk=pk,
        kind=Ticket.Kind.SERVICE_ORDER,
        status=Ticket.Status.COMPLETED,
    )
    order = get_object_or_404(
        ServiceOrderDetails,
        ticket=ticket,
        resident_confirmed_at__isnull=True,
    )
    order.resident_confirmed_at = timezone.now()
    order.save(update_fields=('resident_confirmed_at',))
    messages.success(request, 'Выполнение заказа подтверждено. Спасибо!')
    return redirect('resident_portal:ticket-detail', pk=ticket.pk)


@resident_required
def profile(request):
    form = ResidentProfileForm(request.POST or None, applicant=request.applicant)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Профиль сохранён.')
        return redirect('resident_portal:profile')
    return render(
        request,
        'resident_portal/profile.html',
        {
            **_base_context(request, 'profile'),
            'form': form,
            'orders_count': request.applicant.tickets.filter(
                kind=Ticket.Kind.SERVICE_ORDER,
            ).count(),
            'appeals_count': request.applicant.tickets.filter(
                kind=Ticket.Kind.APPEAL,
            ).count(),
        },
    )
