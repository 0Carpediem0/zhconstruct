from django.utils import timezone

from .models import (
    ComplexConfigurationEvent,
    ImplementationTestRun,
    ResidentialComplex,
    ResidentialComplexMembership,
    ResidentialComplexProvider,
    ServiceRoutingRule,
)


def resolve_configured_route(residential_complex, category):
    """Показывает ожидаемый маршрут без создания настоящей заявки."""

    rule = ServiceRoutingRule.objects.filter(
        residential_complex=residential_complex,
        category=category,
        is_active=True,
    ).select_related('provider').first()
    if rule:
        if rule.mode == ServiceRoutingRule.Mode.MANUAL:
            return None, 'Заявка попадёт диспетчеру по явному правилу.'
        return rule.provider, 'Прямой маршрут настроен явно.'

    links = list(
        ResidentialComplexProvider.objects.filter(
            residential_complex=residential_complex,
            service_categories=category,
            provider__services__category=category,
            provider__services__is_active=True,
            provider__is_active=True,
            is_active=True,
            auto_assignment_enabled=True,
        ).select_related('provider').distinct()
    )
    preferred = [link for link in links if link.is_preferred]
    if len(preferred) == 1:
        return preferred[0].provider, 'Выбран единственный предпочтительный поставщик.'
    if len(links) == 1:
        return links[0].provider, 'Выбран единственный доступный поставщик.'
    if not links:
        return None, 'Нет доступного поставщика — заявка попадёт диспетчеру.'
    return None, 'Несколько поставщиков без приоритета — заявка попадёт диспетчеру.'


def build_readiness(residential_complex):
    """Собирает единый чек-лист, на котором основаны обзор и запуск ЖК."""

    profile_ready = all(
        (
            residential_complex.name,
            residential_complex.address,
            residential_complex.management_company,
            residential_complex.timezone,
            residential_complex.contact_name,
            residential_complex.contact_email,
        )
    )
    team = residential_complex.memberships.filter(is_active=True)
    team_ready = (
        team.filter(role=ResidentialComplexMembership.Role.MANAGER).exists()
        and team.filter(role=ResidentialComplexMembership.Role.DISPATCHER).exists()
    )
    channels_ready = residential_complex.intake_channels.filter(
        is_enabled=True,
        is_verified=True,
    ).exists()
    services = residential_complex.service_settings.filter(is_active=True)
    services_ready = services.exists()
    routes_ready = services_ready and all(
        (
            not setting.auto_assignment_enabled
            or resolve_configured_route(residential_complex, setting.category)[0]
            or setting.fallback == setting.Fallback.DISPATCHER
        )
        for setting in services.select_related('category')
    )
    latest_test = residential_complex.implementation_test_runs.first()
    test_ready = bool(latest_test and latest_test.is_successful)

    items = [
        {'key': 'profile', 'label': 'Карточка ЖК заполнена', 'complete': profile_ready, 'section': 'profile'},
        {'key': 'team', 'label': 'Назначены руководитель и диспетчер', 'complete': team_ready, 'section': 'team'},
        {'key': 'channels', 'label': 'Проверен канал поступления заявок', 'complete': channels_ready, 'section': 'channels'},
        {'key': 'services', 'label': 'Включены услуги для ЖК', 'complete': services_ready, 'section': 'services'},
        {'key': 'routing', 'label': 'Для услуг определено назначение', 'complete': routes_ready, 'section': 'routing'},
        {'key': 'test', 'label': 'Тестовый прогон выполнен успешно', 'complete': test_ready, 'section': 'launch'},
    ]
    completed = sum(item['complete'] for item in items)
    return {
        'items': items,
        'completed': completed,
        'total': len(items),
        'percent': round(completed / len(items) * 100),
        'can_launch': completed == len(items),
    }


def run_implementation_test(residential_complex, user):
    """Имитирует по одной заявке каждой активной услуги без записи в очередь."""

    results = []
    successful = True
    for setting in residential_complex.service_settings.filter(
        is_active=True,
    ).select_related('category'):
        provider, explanation = resolve_configured_route(
            residential_complex,
            setting.category,
        )
        is_ok = bool(provider) or setting.fallback == setting.Fallback.DISPATCHER
        successful = successful and is_ok
        results.append(
            {
                'category': setting.category.name,
                'destination': provider.name if provider else 'Диспетчер ЖК',
                'explanation': explanation,
                'success': is_ok,
            }
        )
    if not results:
        successful = False
        results.append(
            {
                'category': 'Нет услуг',
                'destination': '—',
                'explanation': 'Сначала включите хотя бы одну услугу.',
                'success': False,
            }
        )

    test_run = ImplementationTestRun.objects.create(
        residential_complex=residential_complex,
        started_by=user,
        is_successful=successful,
        results=results,
    )
    ComplexConfigurationEvent.objects.create(
        residential_complex=residential_complex,
        actor=user,
        event_type=ComplexConfigurationEvent.Type.TEST,
        description=(
            'Тестовый прогон завершён успешно.'
            if successful
            else 'Тестовый прогон обнаружил незавершённые настройки.'
        ),
    )
    return test_run


def launch_complex(residential_complex, user):
    readiness = build_readiness(residential_complex)
    if not readiness['can_launch']:
        return False, readiness
    residential_complex.lifecycle_status = ResidentialComplex.LifecycleStatus.ACTIVE
    residential_complex.launched_at = timezone.now()
    residential_complex.save(update_fields=('lifecycle_status', 'launched_at', 'updated_at'))
    ComplexConfigurationEvent.objects.create(
        residential_complex=residential_complex,
        actor=user,
        event_type=ComplexConfigurationEvent.Type.LAUNCH,
        description='ЖК переведён в рабочий режим.',
    )
    return True, readiness
