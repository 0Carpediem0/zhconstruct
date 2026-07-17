from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from providers.models import Provider, ProviderService, ServiceCategory

from .models import (
    ResidentialComplex,
    ResidentialComplexMembership,
    ResidentialComplexProvider,
)


class ResidentialComplexModelTests(TestCase):
    def setUp(self):
        self.residential_complex = ResidentialComplex.objects.create(
            name='Sunny',
            slug='sunny',
            address='Example street, 1',
        )
        self.provider = Provider.objects.create(
            name='Clean Home',
            slug='clean-home',
        )
        self.category = ServiceCategory.objects.create(
            name='Cleaning',
            slug='cleaning',
        )
        ProviderService.objects.create(
            provider=self.provider,
            category=self.category,
        )

    def test_complex_can_connect_provider_for_specific_services(self):
        link = ResidentialComplexProvider.objects.create(
            residential_complex=self.residential_complex,
            provider=self.provider,
            source=ResidentialComplexProvider.Source.PLATFORM,
        )
        link.service_categories.add(self.category)

        self.assertQuerySetEqual(
            self.residential_complex.providers.all(),
            [self.provider],
        )
        self.assertQuerySetEqual(link.service_categories.all(), [self.category])

    def test_provider_connection_must_be_unique_for_complex(self):
        ResidentialComplexProvider.objects.create(
            residential_complex=self.residential_complex,
            provider=self.provider,
            source=ResidentialComplexProvider.Source.RESIDENTIAL_COMPLEX,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            ResidentialComplexProvider.objects.create(
                residential_complex=self.residential_complex,
                provider=self.provider,
                source=ResidentialComplexProvider.Source.PLATFORM,
            )

    def test_user_can_have_different_roles_in_different_complexes(self):
        user = get_user_model().objects.create_user(username='dispatcher')
        another_complex = ResidentialComplex.objects.create(
            name='Northern',
            slug='northern',
            address='Another street, 2',
        )

        ResidentialComplexMembership.objects.create(
            user=user,
            residential_complex=self.residential_complex,
            role=ResidentialComplexMembership.Role.DISPATCHER,
        )
        ResidentialComplexMembership.objects.create(
            user=user,
            residential_complex=another_complex,
            role=ResidentialComplexMembership.Role.MANAGER,
        )

        memberships = user.residential_complex_memberships.order_by('role')
        self.assertEqual(memberships.count(), 2)
        self.assertSetEqual(
            set(memberships.values_list('role', flat=True)),
            {
                ResidentialComplexMembership.Role.DISPATCHER,
                ResidentialComplexMembership.Role.MANAGER,
            },
        )

    def test_complex_membership_must_be_unique(self):
        user = get_user_model().objects.create_user(username='dispatcher-unique')
        ResidentialComplexMembership.objects.create(
            user=user,
            residential_complex=self.residential_complex,
            role=ResidentialComplexMembership.Role.DISPATCHER,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            ResidentialComplexMembership.objects.create(
                user=user,
                residential_complex=self.residential_complex,
                role=ResidentialComplexMembership.Role.MANAGER,
            )
