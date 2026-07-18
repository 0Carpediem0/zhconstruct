from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

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


class DashboardScenarioTests(TestCase):
    """Проверяет основные кликабельные сценарии веб-кабинета для каждой роли."""

    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.resident = user_model.objects.create_user(
            username='resident',
            password='test-password',
            first_name='Анна',
        )
        cls.other_resident = user_model.objects.create_user(
            username='other-resident',
            password='test-password',
        )
        cls.dispatcher = user_model.objects.create_user(
            username='dispatcher',
            password='test-password',
        )
        cls.provider_manager = user_model.objects.create_user(
            username='provider-manager',
            password='test-password',
        )
        cls.employee = user_model.objects.create_user(
            username='employee',
            password='test-password',
        )

        cls.complex = ResidentialComplex.objects.create(
            name='ЖК Северный',
            slug='severny',
            address='Екатеринбург, ул. Тестовая, 1',
        )
        ResidentialComplexMembership.objects.create(
            user=cls.dispatcher,
            residential_complex=cls.complex,
            role=ResidentialComplexMembership.Role.DISPATCHER,
        )
        cls.applicant = Applicant.objects.create(
            residential_complex=cls.complex,
            full_name='Анна Жительница',
            apartment='42',
        )
        cls.other_applicant = Applicant.objects.create(
            residential_complex=cls.complex,
            full_name='Иван Житель',
            apartment='7',
        )

        cls.category = ServiceCategory.objects.create(
            name='Сантехника',
            slug='plumbing',
        )
        cls.provider = Provider.objects.create(
            name='ДомСервис',
            slug='dom-service',
        )
        ProviderService.objects.create(
            provider=cls.provider,
            category=cls.category,
        )
        cls.provider_link = ResidentialComplexProvider.objects.create(
            residential_complex=cls.complex,
            provider=cls.provider,
            source=ResidentialComplexProvider.Source.PLATFORM,
        )
        cls.provider_link.service_categories.add(cls.category)
        ProviderMembership.objects.create(
            user=cls.provider_manager,
            provider=cls.provider,
            role=ProviderMembership.Role.MANAGER,
        )
        ProviderMembership.objects.create(
            user=cls.employee,
            provider=cls.provider,
            role=ProviderMembership.Role.EMPLOYEE,
        )

        cls.ticket = Ticket.objects.create(
            residential_complex=cls.complex,
            applicant=cls.applicant,
            title='Протекает кран',
            description='Капает вода на кухне.',
            category=cls.category,
        )
        cls.other_ticket = Ticket.objects.create(
            residential_complex=cls.complex,
            applicant=cls.other_applicant,
            title='Засорилась раковина',
            description='Вода не уходит.',
            category=cls.category,
        )

    def test_anonymous_user_is_redirected_to_russian_login_page(self):
        response = self.client.get(reverse('dashboard:home'))

        self.assertRedirects(
            response,
            f"{reverse('dashboard:login')}?next={reverse('dashboard:home')}",
        )
        login_page = self.client.get(reverse('dashboard:login'))
        self.assertContains(login_page, 'Добро пожаловать')

    def test_resident_cannot_open_internal_dashboard(self):
        self.client.force_login(self.resident)

        self.assertEqual(
            self.client.get(reverse('dashboard:ticket-list')).status_code,
            403,
        )

    def test_resident_credentials_are_rejected_by_internal_login(self):
        response = self.client.post(
            reverse('dashboard:login'),
            {'username': 'resident', 'password': 'test-password'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Кабинет не предназначен для жителей')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_dispatcher_can_register_ticket_from_web_form(self):
        self.client.force_login(self.dispatcher)

        response = self.client.post(
            reverse(
                'dashboard:complex-ticket-create',
                args=[self.complex.slug],
            ),
            {
                'residential_complex': self.complex.pk,
                'applicant': self.applicant.pk,
                'title': 'Не горит лампа',
                'description': 'Не работает освещение у лифта.',
                'category': self.category.pk,
                'priority': Ticket.Priority.HIGH,
            },
        )

        created_ticket = Ticket.objects.get(title='Не горит лампа')
        self.assertRedirects(
            response,
            reverse(
                'dashboard:complex-ticket-detail',
                args=[self.complex.slug, created_ticket.pk],
            ),
        )
        self.assertEqual(created_ticket.applicant, self.applicant)
        self.assertEqual(created_ticket.source, Ticket.Source.DIRECT)

    def test_dispatcher_can_assign_provider(self):
        self.client.force_login(self.dispatcher)

        response = self.client.post(
            reverse(
                'dashboard:complex-ticket-assign-provider',
                args=[self.complex.slug, self.ticket.pk],
            ),
            {'provider_link': self.provider_link.pk, 'comment': 'Передано подрядчику'},
        )

        self.assertRedirects(
            response,
            reverse(
                'dashboard:complex-ticket-detail',
                args=[self.complex.slug, self.ticket.pk],
            ),
        )
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.provider, self.provider)
        self.assertEqual(self.ticket.status, Ticket.Status.ASSIGNED)
        self.assertEqual(self.ticket.status_history.count(), 1)

    def test_web_registration_uses_direct_routing_rule(self):
        rule = ServiceRoutingRule(
            residential_complex=self.complex,
            category=self.category,
            mode=ServiceRoutingRule.Mode.DIRECT,
            provider=self.provider,
        )
        rule.full_clean()
        rule.save()
        self.client.force_login(self.dispatcher)

        response = self.client.post(
            reverse(
                'dashboard:complex-ticket-create',
                args=[self.complex.slug],
            ),
            {
                'residential_complex': self.complex.pk,
                'applicant': self.applicant.pk,
                'title': 'Прямая заявка на клининг',
                'description': 'Не требует ручного назначения.',
                'category': self.category.pk,
                'priority': Ticket.Priority.NORMAL,
            },
        )

        ticket = Ticket.objects.get(title='Прямая заявка на клининг')
        self.assertRedirects(
            response,
            reverse(
                'dashboard:complex-ticket-detail',
                args=[self.complex.slug, ticket.pk],
            ),
        )
        self.assertEqual(ticket.provider, self.provider)
        self.assertEqual(ticket.status, Ticket.Status.ASSIGNED)
        self.assertEqual(ticket.status_history.count(), 1)

    def test_provider_manager_can_assign_employee(self):
        self.ticket.provider = self.provider
        self.ticket.status = Ticket.Status.ASSIGNED
        self.ticket.full_clean()
        self.ticket.save()
        self.client.force_login(self.provider_manager)

        response = self.client.post(
            reverse('dashboard:ticket-assign-employee', args=[self.ticket.pk]),
            {'employee': self.employee.pk},
        )

        self.assertRedirects(
            response,
            reverse('dashboard:ticket-detail', args=[self.ticket.pk]),
        )
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.assignee, self.employee)

    def test_employee_can_move_assigned_ticket_through_workflow(self):
        self.ticket.provider = self.provider
        self.ticket.assignee = self.employee
        self.ticket.status = Ticket.Status.ASSIGNED
        self.ticket.full_clean()
        self.ticket.save()
        self.client.force_login(self.employee)

        for status in (
            Ticket.Status.ACCEPTED,
            Ticket.Status.IN_PROGRESS,
            Ticket.Status.COMPLETED,
        ):
            response = self.client.post(
                reverse('dashboard:ticket-change-status', args=[self.ticket.pk]),
                {'status': status},
            )
            self.assertEqual(response.status_code, 302)

        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Ticket.Status.COMPLETED)
        self.assertEqual(self.ticket.status_history.count(), 3)

    def test_directory_page_respects_dispatcher_scope(self):
        unrelated_complex = ResidentialComplex.objects.create(
            name='Чужой ЖК',
            slug='unrelated',
            address='Другой адрес',
        )
        self.client.force_login(self.dispatcher)

        response = self.client.get(
            reverse('dashboard:complex-directories', args=[self.complex.slug]),
        )

        self.assertContains(response, self.complex.name)
        self.assertNotContains(response, unrelated_complex.name)

    def test_provider_employee_cannot_open_manual_registration(self):
        self.client.force_login(self.employee)

        response = self.client.get(reverse('dashboard:ticket-create'))

        self.assertRedirects(response, reverse('dashboard:home'))

    def test_provider_workspace_does_not_show_registration_action(self):
        self.client.force_login(self.provider_manager)

        response = self.client.get(reverse('dashboard:home'))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Регистрация заявки')

    def test_dispatcher_root_redirects_to_own_complex_workspace(self):
        self.client.force_login(self.dispatcher)

        response = self.client.get(reverse('dashboard:home'))

        self.assertRedirects(
            response,
            reverse('dashboard:complex-home', args=[self.complex.slug]),
        )

    def test_complex_cannot_open_another_complex_workspace(self):
        other_complex = ResidentialComplex.objects.create(
            name='ЖК Закрытый',
            slug='closed-complex',
            address='Закрытый адрес',
        )
        self.client.force_login(self.dispatcher)

        response = self.client.get(
            reverse('dashboard:complex-home', args=[other_complex.slug]),
        )

        self.assertEqual(response.status_code, 404)

    def test_implementer_sees_configuration_but_not_common_ticket_queue(self):
        implementer = get_user_model().objects.create_user(
            username='implementer',
            platform_role=get_user_model().PlatformRole.IMPLEMENTER,
        )
        self.client.force_login(implementer)

        response = self.client.get(reverse('dashboard:home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.complex.name)
        self.assertContains(response, 'Настроить')
        self.assertNotContains(response, self.ticket.title)
        self.assertEqual(
            self.client.get(
                reverse('dashboard:complex-home', args=[self.complex.slug]),
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                reverse(
                    'dashboard:implementation-complex',
                    args=[self.complex.slug],
                ),
            ).status_code,
            200,
        )
