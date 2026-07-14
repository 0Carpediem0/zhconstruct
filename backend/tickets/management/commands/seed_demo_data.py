from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from complexes.models import (
    ResidentialComplex,
    ResidentialComplexMembership,
    ResidentialComplexProvider,
)
from providers.models import (
    Provider,
    ProviderMembership,
    ProviderService,
    ServiceCategory,
)
from tickets.models import Ticket


class Command(BaseCommand):
    help = 'Создаёт локальные демонстрационные данные для Django Admin.'

    def add_arguments(self, parser):
        # Пароль передаётся только при запуске и не хранится в репозитории.
        parser.add_argument('--admin-password', required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        user_model = get_user_model()

        admin, _ = user_model.objects.get_or_create(
            username='admin',
            defaults={'email': 'admin@local.test'},
        )
        admin.is_staff = True
        admin.is_superuser = True
        admin.set_password(options['admin_password'])
        admin.save()

        resident, _ = user_model.objects.get_or_create(username='demo-resident')
        dispatcher, _ = user_model.objects.get_or_create(username='demo-dispatcher')
        employee, _ = user_model.objects.get_or_create(username='demo-employee')

        residential_complex, _ = ResidentialComplex.objects.get_or_create(
            slug='sunny-demo',
            defaults={
                'name': 'ЖК Солнечный',
                'address': 'г. Екатеринбург, ул. Демонстрационная, д. 1',
            },
        )
        category, _ = ServiceCategory.objects.get_or_create(
            slug='entrance-cleaning',
            defaults={
                'name': 'Уборка подъезда',
                'description': 'Влажная уборка и обслуживание общих зон.',
            },
        )
        provider, _ = Provider.objects.get_or_create(
            slug='clean-home-demo',
            defaults={
                'name': 'Чистый дом',
                'email': 'provider@local.test',
                'phone': '+7 900 000-00-00',
                'is_platform_partner': True,
            },
        )

        ProviderService.objects.update_or_create(
            provider=provider,
            category=category,
            defaults={'is_active': True},
        )
        ProviderMembership.objects.update_or_create(
            user=employee,
            provider=provider,
            defaults={
                'role': ProviderMembership.Role.EMPLOYEE,
                'is_active': True,
            },
        )
        ResidentialComplexMembership.objects.update_or_create(
            user=resident,
            residential_complex=residential_complex,
            defaults={
                'role': ResidentialComplexMembership.Role.RESIDENT,
                'is_active': True,
            },
        )
        ResidentialComplexMembership.objects.update_or_create(
            user=dispatcher,
            residential_complex=residential_complex,
            defaults={
                'role': ResidentialComplexMembership.Role.DISPATCHER,
                'is_active': True,
            },
        )
        provider_link, _ = ResidentialComplexProvider.objects.update_or_create(
            residential_complex=residential_complex,
            provider=provider,
            defaults={
                'source': ResidentialComplexProvider.Source.PLATFORM,
                'is_preferred': True,
                'is_active': True,
            },
        )
        provider_link.service_categories.add(category)

        ticket = Ticket.objects.filter(
            residential_complex=residential_complex,
            source=Ticket.Source.IMPORT,
            external_id='demo-ticket-1',
        ).first()
        if ticket is None:
            ticket = Ticket(
                residential_complex=residential_complex,
                customer=resident,
                title='Требуется уборка подъезда',
                description='После ремонтных работ на первом этаже осталась пыль.',
                category=category,
                provider=provider,
                assignee=employee,
                priority=Ticket.Priority.HIGH,
                source=Ticket.Source.IMPORT,
                external_id='demo-ticket-1',
            )
            ticket.full_clean()
            ticket.save()
            ticket.transition_to(
                Ticket.Status.ASSIGNED,
                changed_by=dispatcher,
                comment='Поставщик выбран диспетчером.',
            )
            ticket.transition_to(
                Ticket.Status.ACCEPTED,
                changed_by=employee,
                comment='Поставщик принял заявку.',
            )
            ticket.transition_to(
                Ticket.Status.IN_PROGRESS,
                changed_by=employee,
                comment='Исполнитель приступил к работе.',
            )

        self.stdout.write(self.style.SUCCESS('Демонстрационные данные готовы.'))
        self.stdout.write('Django Admin: http://localhost:8000/admin/')
        self.stdout.write('Логин: admin')
