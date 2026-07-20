from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from complexes.models import (
    ComplexConfigurationEvent,
    ResidentialComplex,
    ResidentialComplexMembership,
    ResidentialComplexNotificationRule,
    ResidentialComplexService,
)
from providers.models import ServiceCategory


class ImplementationWizardTests(TestCase):
    """Проверяет мастер как единый сценарий, а не только отдельные формы."""

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.implementer = User.objects.create_user(
            username='implementer',
            password='test-password',
            platform_role=User.PlatformRole.IMPLEMENTER,
        )
        cls.complex = ResidentialComplex.objects.create(
            name='ЖК Тестовый',
            slug='test-complex',
            address='г. Екатеринбург, ул. Тестовая, 1',
        )
        cls.category = ServiceCategory.objects.create(
            name='Клининг',
            slug='cleaning-test',
        )

    def setUp(self):
        self.client.force_login(self.implementer)

    def section_url(self, section):
        return reverse(
            'dashboard:implementation-complex-section',
            kwargs={'complex_slug': self.complex.slug, 'section': section},
        )

    def test_all_wizard_sections_are_available_to_implementer(self):
        for section in (
            'overview', 'profile', 'team', 'channels', 'services',
            'providers', 'routing', 'launch', 'audit',
        ):
            with self.subTest(section=section):
                response = self.client.get(self.section_url(section))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'Мастер внедрения')

    def test_configuration_actions_create_tenant_scoped_data_and_audit(self):
        self.client.post(
            self.section_url('profile'),
            {
                'action': 'save_profile',
                'profile-name': 'ЖК Тестовый',
                'profile-slug': 'test-complex',
                'profile-address': 'г. Екатеринбург, ул. Тестовая, 1',
                'profile-management_company': 'ТСЖ Тестовое',
                'profile-timezone': 'Asia/Yekaterinburg',
                'profile-contact_name': 'Анна Иванова',
                'profile-contact_email': 'anna@example.com',
                'profile-contact_phone': '+7 900 000-00-00',
            },
        )
        response = self.client.post(
            self.section_url('channels'),
            {
                'action': 'save_channel',
                'channel-channel_type': 'manual',
                'channel-description': 'Регистрация диспетчером',
                'channel-is_enabled': 'on',
                'channel-is_verified': 'on',
            },
        )
        self.assertRedirects(response, self.section_url('channels'))
        self.assertTrue(
            self.complex.intake_channels.filter(
                channel_type='manual',
                is_verified=True,
            ).exists()
        )
        response = self.client.post(
            self.section_url('channels'),
            {
                'action': 'save_notification',
                'notification-event': 'unassigned',
                'notification-recipient': 'dispatchers',
                'notification-is_enabled': 'on',
            },
        )
        self.assertRedirects(response, self.section_url('channels'))
        self.assertTrue(
            ResidentialComplexNotificationRule.objects.filter(
                residential_complex=self.complex,
                event='unassigned',
                recipient='dispatchers',
                is_enabled=True,
            ).exists()
        )
        self.assertGreaterEqual(
            ComplexConfigurationEvent.objects.filter(
                residential_complex=self.complex,
            ).count(),
            3,
        )

    def test_launch_is_enabled_only_after_required_setup_and_test(self):
        self.complex.management_company = 'ТСЖ Тестовое'
        self.complex.contact_name = 'Анна Иванова'
        self.complex.contact_email = 'anna@example.com'
        self.complex.save()
        User = get_user_model()
        for username, role in (
            ('manager', ResidentialComplexMembership.Role.MANAGER),
            ('dispatcher', ResidentialComplexMembership.Role.DISPATCHER),
        ):
            user = User.objects.create_user(username=username)
            ResidentialComplexMembership.objects.create(
                user=user,
                residential_complex=self.complex,
                role=role,
            )
        self.complex.intake_channels.create(
            channel_type='manual',
            is_enabled=True,
            is_verified=True,
        )
        ResidentialComplexService.objects.create(
            residential_complex=self.complex,
            category=self.category,
            auto_assignment_enabled=False,
            fallback=ResidentialComplexService.Fallback.DISPATCHER,
        )

        self.client.post(self.section_url('launch'), {'action': 'run_test'})
        response = self.client.post(
            self.section_url('launch'),
            {'action': 'launch_complex'},
        )
        self.assertRedirects(response, self.section_url('launch'))
        self.complex.refresh_from_db()
        self.assertEqual(
            self.complex.lifecycle_status,
            ResidentialComplex.LifecycleStatus.ACTIVE,
        )
        self.assertIsNotNone(self.complex.launched_at)
