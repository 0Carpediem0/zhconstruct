from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from complexes.models import (
    ResidentialComplex,
    ResidentialComplexMembership,
    ResidentialComplexProvider,
    ServiceRoutingRule,
)
from providers.models import (
    Provider,
    ProviderMembership,
    ProviderService,
    ServiceCategory,
)
from tickets.models import Applicant, Ticket


class Command(BaseCommand):
    help = 'Создаёт локальные демонстрационные данные для Django Admin.'

    def add_arguments(self, parser):
        # Пароль передаётся только при запуске и не хранится в репозитории.
        parser.add_argument('--admin-password', required=True)
        parser.add_argument('--demo-password')

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

        dispatcher, _ = user_model.objects.get_or_create(username='demo-dispatcher')
        north_dispatcher, _ = user_model.objects.get_or_create(
            username='demo-dispatcher-north',
        )
        implementer, _ = user_model.objects.get_or_create(username='demo-implementer')
        employee, _ = user_model.objects.get_or_create(username='demo-employee')
        provider_manager, _ = user_model.objects.get_or_create(
            username='demo-provider-manager',
        )
        demo_users = (
            (dispatcher, 'Мария', 'Диспетчерова'),
            (north_dispatcher, 'Ольга', 'Северова'),
            (implementer, 'Виктор', 'Внедренец'),
            (employee, 'Алексей', 'Мастер'),
            (provider_manager, 'Игорь', 'Руководитель'),
        )
        for user, first_name, last_name in demo_users:
            user.first_name = first_name
            user.last_name = last_name
            if options.get('demo_password'):
                user.set_password(options['demo_password'])
            user.save()
        implementer.platform_role = user_model.PlatformRole.IMPLEMENTER
        implementer.save(update_fields=('platform_role',))

        residential_complex, _ = ResidentialComplex.objects.get_or_create(
            slug='sunny-demo',
            defaults={
                'name': 'ЖК Солнечный',
                'address': 'г. Екатеринбург, ул. Демонстрационная, д. 1',
            },
        )
        north_complex, _ = ResidentialComplex.objects.get_or_create(
            slug='northern-demo',
            defaults={
                'name': 'ЖК Северный',
                'address': 'г. Екатеринбург, ул. Северная, д. 10',
            },
        )
        applicant, _ = Applicant.objects.update_or_create(
            residential_complex=residential_complex,
            external_id='demo-applicant-anna',
            defaults={
                'full_name': 'Анна Смирнова',
                'phone': '+7 900 000-00-01',
                'email': 'anna@example.test',
                'apartment': '42',
                'is_active': True,
            },
        )
        north_applicant, _ = Applicant.objects.update_or_create(
            residential_complex=north_complex,
            external_id='demo-applicant-north',
            defaults={
                'full_name': 'Елена Петрова',
                'phone': '+7 900 000-00-02',
                'apartment': '15',
                'is_active': True,
            },
        )
        category, _ = ServiceCategory.objects.get_or_create(
            slug='entrance-cleaning',
            defaults={
                'name': 'Уборка подъезда',
                'description': 'Влажная уборка и обслуживание общих зон.',
            },
        )
        electricity_category, _ = ServiceCategory.objects.get_or_create(
            slug='electricity-demo',
            defaults={
                'name': 'Электрика',
                'description': 'Освещение, проводка и электрооборудование.',
            },
        )
        plumbing_category, _ = ServiceCategory.objects.get_or_create(
            slug='plumbing-demo',
            defaults={
                'name': 'Сантехника',
                'description': 'Водоснабжение, отопление и устранение протечек.',
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
        for extra_category in (electricity_category, plumbing_category):
            ProviderService.objects.update_or_create(
                provider=provider,
                category=extra_category,
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
        ProviderMembership.objects.update_or_create(
            user=provider_manager,
            provider=provider,
            defaults={
                'role': ProviderMembership.Role.MANAGER,
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
        ResidentialComplexMembership.objects.update_or_create(
            user=north_dispatcher,
            residential_complex=north_complex,
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
        provider_link.service_categories.add(
            category,
            electricity_category,
            plumbing_category,
        )
        ServiceRoutingRule.objects.update_or_create(
            residential_complex=residential_complex,
            category=category,
            defaults={
                'mode': ServiceRoutingRule.Mode.DIRECT,
                'provider': provider,
                'is_active': True,
            },
        )

        ticket = Ticket.objects.filter(
            residential_complex=residential_complex,
            source=Ticket.Source.IMPORT,
            external_id='demo-ticket-1',
        ).first()
        if ticket is None:
            ticket = Ticket(
                residential_complex=residential_complex,
                applicant=applicant,
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

        new_ticket = Ticket.objects.filter(
            residential_complex=residential_complex,
            source=Ticket.Source.DIRECT,
            external_id='demo-ticket-new',
        ).first()
        if new_ticket is None:
            new_ticket = Ticket(
                residential_complex=residential_complex,
                applicant=applicant,
                title='Не работает освещение на этаже',
                description='На третьем этаже вечером полностью отсутствует свет.',
                category=electricity_category,
                priority=Ticket.Priority.URGENT,
                source=Ticket.Source.DIRECT,
                external_id='demo-ticket-new',
            )
            new_ticket.full_clean()
            new_ticket.save()

        assigned_ticket = Ticket.objects.filter(
            residential_complex=residential_complex,
            source=Ticket.Source.IMPORT,
            external_id='demo-ticket-assigned',
        ).first()
        if assigned_ticket is None:
            assigned_ticket = Ticket(
                residential_complex=residential_complex,
                applicant=applicant,
                title='Протечка в подвальном помещении',
                description='Возле стояка появилась вода, требуется осмотр специалиста.',
                category=plumbing_category,
                provider=provider,
                priority=Ticket.Priority.HIGH,
                source=Ticket.Source.IMPORT,
                external_id='demo-ticket-assigned',
            )
            assigned_ticket.full_clean()
            assigned_ticket.save()
            assigned_ticket.transition_to(
                Ticket.Status.ASSIGNED,
                changed_by=dispatcher,
                comment='Заявка направлена в обслуживающую организацию.',
            )

        completed_ticket = Ticket.objects.filter(
            residential_complex=residential_complex,
            source=Ticket.Source.IMPORT,
            external_id='demo-ticket-completed',
        ).first()
        if completed_ticket is None:
            completed_ticket = Ticket(
                residential_complex=residential_complex,
                applicant=applicant,
                title='Уборка после ремонтных работ',
                description='Необходимо убрать строительную пыль в холле первого этажа.',
                category=category,
                provider=provider,
                assignee=employee,
                priority=Ticket.Priority.NORMAL,
                source=Ticket.Source.IMPORT,
                external_id='demo-ticket-completed',
            )
            completed_ticket.full_clean()
            completed_ticket.save()
            for next_status, status_comment in (
                (Ticket.Status.ASSIGNED, 'Поставщик назначен.'),
                (Ticket.Status.ACCEPTED, 'Заявка принята в работу.'),
                (Ticket.Status.IN_PROGRESS, 'Исполнитель начал уборку.'),
                (Ticket.Status.COMPLETED, 'Работы завершены и проверены.'),
            ):
                completed_ticket.transition_to(
                    next_status,
                    changed_by=employee,
                    comment=status_comment,
                )

        demo_ticket_ids = {
            'demo-ticket-1',
            'demo-ticket-new',
            'demo-ticket-assigned',
            'demo-ticket-completed',
        }
        Ticket.objects.filter(
            residential_complex=residential_complex,
            external_id__in=demo_ticket_ids,
        ).update(applicant=applicant)
        # После перехода со старой модели User скрываем только осиротевший
        # демонстрационный дубль, не затрагивая реальные карточки заявителей.
        Applicant.objects.filter(
            residential_complex=residential_complex,
            full_name=applicant.full_name,
            external_id__startswith='legacy-user-',
            tickets__isnull=True,
        ).exclude(pk=applicant.pk).update(is_active=False)

        Ticket.objects.update_or_create(
            residential_complex=north_complex,
            source=Ticket.Source.IMPORT,
            external_id='demo-ticket-north',
            defaults={
                'applicant': north_applicant,
                'title': 'Не работает домофон',
                'description': 'Домофон у первого подъезда не отвечает.',
                'category': electricity_category,
                'priority': Ticket.Priority.NORMAL,
                'status': Ticket.Status.NEW,
                'provider': None,
                'assignee': None,
            },
        )

        self.stdout.write(self.style.SUCCESS('Демонстрационные данные готовы.'))
        self.stdout.write('Django Admin: http://localhost:8000/admin/')
        self.stdout.write('Логин: admin')
        if options.get('demo_password'):
            self.stdout.write(
                'Демо-логины: demo-dispatcher, demo-dispatcher-north, '
                'demo-implementer, demo-provider-manager, demo-employee'
            )
