from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from .models import Provider, ProviderMembership, ProviderService, ServiceCategory


class ProviderModelTests(TestCase):
    def setUp(self):
        self.provider = Provider.objects.create(
            name='Clean Home',
            slug='clean-home',
        )
        self.category = ServiceCategory.objects.create(
            name='Cleaning',
            slug='cleaning',
        )

    def test_provider_can_offer_service_category(self):
        ProviderService.objects.create(
            provider=self.provider,
            category=self.category,
        )

        self.assertQuerySetEqual(
            self.provider.service_categories.all(),
            [self.category],
        )

    def test_provider_service_must_be_unique(self):
        ProviderService.objects.create(
            provider=self.provider,
            category=self.category,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            ProviderService.objects.create(
                provider=self.provider,
                category=self.category,
            )

    def test_user_can_have_contextual_provider_role(self):
        user = get_user_model().objects.create_user(username='employee')
        membership = ProviderMembership.objects.create(
            user=user,
            provider=self.provider,
            role=ProviderMembership.Role.EMPLOYEE,
        )

        self.assertEqual(membership.role, ProviderMembership.Role.EMPLOYEE)
        self.assertEqual(user.provider_memberships.get(), membership)

    def test_provider_membership_must_be_unique(self):
        user = get_user_model().objects.create_user(username='manager')
        ProviderMembership.objects.create(
            user=user,
            provider=self.provider,
            role=ProviderMembership.Role.MANAGER,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            ProviderMembership.objects.create(
                user=user,
                provider=self.provider,
                role=ProviderMembership.Role.EMPLOYEE,
            )
