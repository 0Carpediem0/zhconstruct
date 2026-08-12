from datetime import time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from complexes.models import (
    ResidentialComplex,
    ResidentialComplexProvider,
    ResidentialComplexService,
    ServiceRoutingRule,
)
from providers.models import (
    Provider,
    ProviderMembership,
    ProviderService,
    ServiceCategory,
    ServiceOffering,
)
from tickets.models import Applicant, Ticket
from tickets.services import assign_employee

from .models import NewsPost, ServiceOrderDetails, UtilityAccount


class ResidentPortalTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.complex = ResidentialComplex.objects.create(
            name='ЖК Тестовый',
            slug='test-complex',
            address='г. Екатеринбург, ул. Тестовая, д. 1',
        )
        self.other_complex = ResidentialComplex.objects.create(
            name='ЖК Другой',
            slug='other-complex',
            address='г. Екатеринбург, ул. Другая, д. 2',
        )
        self.user = user_model.objects.create_user(
            username='resident',
            password='resident-password',
        )
        self.staff = user_model.objects.create_user(
            username='staff-without-resident-profile',
            password='staff-password',
        )
        self.applicant = Applicant.objects.create(
            user=self.user,
            residential_complex=self.complex,
            full_name='Иван Жилец',
            apartment='17',
        )
        self.other_applicant = Applicant.objects.create(
            residential_complex=self.other_complex,
            full_name='Другой Жилец',
            apartment='1',
        )
        self.category = ServiceCategory.objects.create(
            name='Клининг',
            slug='entrance-cleaning',
            description='Уборка квартиры.',
        )
        ResidentialComplexService.objects.create(
            residential_complex=self.complex,
            category=self.category,
            auto_assignment_enabled=True,
        )
        self.provider = Provider.objects.create(name='Чистый дом', slug='clean-home')
        ProviderMembership.objects.create(
            user=self.staff,
            provider=self.provider,
            role=ProviderMembership.Role.EMPLOYEE,
        )
        ProviderService.objects.create(provider=self.provider, category=self.category)
        provider_link = ResidentialComplexProvider.objects.create(
            residential_complex=self.complex,
            provider=self.provider,
            is_active=True,
        )
        provider_link.service_categories.add(self.category)
        ServiceRoutingRule.objects.create(
            residential_complex=self.complex,
            category=self.category,
            mode=ServiceRoutingRule.Mode.DIRECT,
            provider=self.provider,
        )
        self.offering = ServiceOffering.objects.create(
            residential_complex=self.complex,
            provider=self.provider,
            category=self.category,
            title='Поддерживающая уборка',
            description='Уборка квартиры до 60 м².',
            price='3500.00',
            duration_minutes=120,
            capacity_per_slot=1,
            available_weekdays=list(range(7)),
            available_from=time(8),
            available_until=time(20),
            minimum_lead_hours=1,
        )

    def login(self):
        return self.client.post(
            reverse('resident_portal:login'),
            {'username': 'resident', 'password': 'resident-password'},
        )

    def test_anonymous_resident_is_redirected_to_resident_login(self):
        response = self.client.get(reverse('resident_portal:home'))
        self.assertRedirects(response, reverse('resident_portal:login'))

    def test_only_user_with_applicant_profile_can_log_in(self):
        response = self.login()
        self.assertRedirects(response, reverse('resident_portal:home'))
        self.client.logout()

        response = self.client.post(
            reverse('resident_portal:login'),
            {'username': self.staff.username, 'password': 'staff-password'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Этот вход предназначен для жителей')

    def test_resident_can_log_in_by_email(self):
        self.user.email = 'resident@example.test'
        self.user.save(update_fields=('email',))
        response = self.client.post(
            reverse('resident_portal:login'),
            {'username': self.user.email, 'password': 'resident-password'},
        )
        self.assertRedirects(response, reverse('resident_portal:home'))

    def test_login_does_not_redirect_to_external_site(self):
        response = self.client.post(
            f"{reverse('resident_portal:login')}?next=https://example.org/steal",
            {'username': 'resident', 'password': 'resident-password'},
        )
        self.assertRedirects(response, reverse('resident_portal:home'))

    def test_resident_pages_render_own_complex_data(self):
        UtilityAccount.objects.create(
            applicant=self.applicant,
            account_number='TEST-17',
            amount_due='1500.00',
            due_date='2026-08-20',
        )
        NewsPost.objects.create(
            residential_complex=self.complex,
            title='Новость тестового дома',
            summary='Только для этого ЖК.',
        )
        self.login()

        for route_name in ('home', 'payments', 'services', 'news', 'tickets', 'profile'):
            with self.subTest(route_name=route_name):
                response = self.client.get(reverse(f'resident_portal:{route_name}'))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, self.complex.name)

        response = self.client.get(reverse('resident_portal:services'))
        self.assertContains(response, 'Клининг')
        self.assertNotContains(response, 'Сантехника')

    def test_service_order_is_created_for_resident_and_routed_directly(self):
        self.login()
        scheduled_date = timezone.localdate() + timedelta(days=2)
        response = self.client.post(
            reverse('resident_portal:service-detail', args=[self.offering.pk]),
            {
                'scheduled_date': scheduled_date.isoformat(),
                'scheduled_start': '10:00',
                'resident_comment': 'Позвонить за десять минут.',
            },
        )
        ticket = Ticket.objects.get(title='Поддерживающая уборка')
        self.assertRedirects(
            response,
            reverse('resident_portal:ticket-detail', args=[ticket.pk]),
        )
        self.assertEqual(ticket.applicant, self.applicant)
        self.assertEqual(ticket.residential_complex, self.complex)
        self.assertEqual(ticket.kind, Ticket.Kind.SERVICE_ORDER)
        self.assertEqual(ticket.provider, self.provider)
        self.assertEqual(ticket.status, Ticket.Status.ASSIGNED)
        self.assertEqual(ticket.service_order.offering, self.offering)
        self.assertEqual(str(ticket.service_order.quoted_price), '3500.00')
        self.assertEqual(ticket.service_order.scheduled_date, scheduled_date)

    def test_busy_service_slot_cannot_exceed_offering_capacity(self):
        self.login()
        scheduled_date = timezone.localdate() + timedelta(days=2)
        order_url = reverse(
            'resident_portal:service-detail',
            args=[self.offering.pk],
        )
        payload = {
            'scheduled_date': scheduled_date.isoformat(),
            'scheduled_start': '10:00',
            'resident_comment': '',
        }
        self.client.post(order_url, payload)
        response = self.client.post(order_url, payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Это время уже занято')
        self.assertEqual(ServiceOrderDetails.objects.count(), 1)

    def test_resident_can_confirm_only_completed_own_service_order(self):
        self.login()
        scheduled_date = timezone.localdate() + timedelta(days=2)
        self.client.post(
            reverse('resident_portal:service-detail', args=[self.offering.pk]),
            {
                'scheduled_date': scheduled_date.isoformat(),
                'scheduled_start': '12:00',
                'resident_comment': '',
            },
        )
        ticket = Ticket.objects.get(title=self.offering.title)
        confirm_url = reverse(
            'resident_portal:confirm-service-order',
            args=[ticket.pk],
        )
        self.assertEqual(self.client.post(confirm_url).status_code, 404)
        ticket.transition_to(Ticket.Status.ACCEPTED, changed_by=self.staff)
        ticket = assign_employee(ticket, employee=self.staff)
        ticket.transition_to(Ticket.Status.IN_PROGRESS, changed_by=self.staff)
        ticket.transition_to(Ticket.Status.COMPLETED, changed_by=self.staff)
        response = self.client.post(confirm_url)
        self.assertRedirects(
            response,
            reverse('resident_portal:ticket-detail', args=[ticket.pk]),
        )
        ticket.service_order.refresh_from_db()
        self.assertIsNotNone(ticket.service_order.resident_confirmed_at)
        self.assertEqual(
            ticket.get_resident_status_display(),
            'Выполнено и подтверждено',
        )

    def test_appeal_is_created_for_resident(self):
        self.login()
        response = self.client.post(
            reverse('resident_portal:ticket-create'),
            {
                'category': self.category.pk,
                'title': 'Не горит лампа',
                'description': 'На лестничной площадке темно.',
            },
        )
        ticket = Ticket.objects.get(title='Не горит лампа')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ticket.kind, Ticket.Kind.APPEAL)
        self.assertEqual(ticket.applicant, self.applicant)

    def test_resident_cannot_open_another_residents_ticket(self):
        other_ticket = Ticket.objects.create(
            residential_complex=self.other_complex,
            applicant=self.other_applicant,
            category=self.category,
            title='Чужая заявка',
            description='Не должна быть видна.',
        )
        self.login()
        response = self.client.get(
            reverse('resident_portal:ticket-detail', args=[other_ticket.pk]),
        )
        self.assertEqual(response.status_code, 404)

    def test_profile_can_be_updated(self):
        self.login()
        response = self.client.post(
            reverse('resident_portal:profile'),
            {
                'full_name': 'Иван Обновлённый',
                'phone': '+7 900 111-22-33',
                'email': 'resident@example.test',
            },
        )
        self.assertRedirects(response, reverse('resident_portal:profile'))
        self.applicant.refresh_from_db()
        self.user.refresh_from_db()
        self.assertEqual(self.applicant.full_name, 'Иван Обновлённый')
        self.assertEqual(self.user.email, 'resident@example.test')
