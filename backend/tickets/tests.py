from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from complexes.models import (
    ResidentialComplex,
    ResidentialComplexProvider,
    ServiceRoutingRule,
)
from providers.models import (
    Provider,
    ProviderMembership,
    ProviderService,
    ServiceCategory,
)

from .models import Applicant, Ticket
from .services import apply_initial_routing


class TicketModelTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.employee = user_model.objects.create_user(username='employee')
        self.dispatcher = user_model.objects.create_user(username='dispatcher')
        self.outsider = user_model.objects.create_user(username='outsider')

        self.residential_complex = ResidentialComplex.objects.create(
            name='Sunny',
            slug='sunny',
            address='Example street, 1',
        )
        self.applicant = Applicant.objects.create(
            residential_complex=self.residential_complex,
            full_name='Anna Resident',
            apartment='42',
        )
        self.other_complex = ResidentialComplex.objects.create(
            name='Northern',
            slug='northern-domain',
            address='Another street, 2',
        )
        self.outside_applicant = Applicant.objects.create(
            residential_complex=self.other_complex,
            full_name='Outside Applicant',
        )

        self.category = ServiceCategory.objects.create(
            name='Cleaning',
            slug='cleaning',
        )
        self.other_category = ServiceCategory.objects.create(
            name='Waste removal',
            slug='waste-removal',
        )
        self.provider = Provider.objects.create(
            name='Clean Home',
            slug='clean-home',
        )
        self.other_provider = Provider.objects.create(
            name='Other Provider',
            slug='other-provider',
        )
        ProviderService.objects.create(
            provider=self.provider,
            category=self.category,
        )
        ProviderService.objects.create(
            provider=self.provider,
            category=self.other_category,
        )
        ProviderMembership.objects.create(
            user=self.employee,
            provider=self.provider,
            role=ProviderMembership.Role.EMPLOYEE,
        )

        self.provider_link = ResidentialComplexProvider.objects.create(
            residential_complex=self.residential_complex,
            provider=self.provider,
            source=ResidentialComplexProvider.Source.PLATFORM,
        )
        self.provider_link.service_categories.add(self.category)

    def make_ticket(self, **overrides):
        data = {
            'residential_complex': self.residential_complex,
            'applicant': self.applicant,
            'title': 'Clean the entrance',
            'description': 'Wet cleaning is required.',
            'category': self.category,
        }
        data.update(overrides)
        return Ticket(**data)

    def test_valid_ticket_passes_domain_validation(self):
        ticket = self.make_ticket(
            provider=self.provider,
            status=Ticket.Status.ASSIGNED,
        )

        ticket.full_clean()

    def test_applicant_must_belong_to_ticket_complex(self):
        ticket = self.make_ticket(applicant=self.outside_applicant)

        with self.assertRaises(ValidationError) as error:
            ticket.full_clean()

        self.assertIn('applicant', error.exception.message_dict)

    def test_provider_must_be_connected_to_ticket_complex(self):
        ticket = self.make_ticket(
            provider=self.other_provider,
            status=Ticket.Status.ASSIGNED,
        )

        with self.assertRaises(ValidationError) as error:
            ticket.full_clean()

        self.assertIn('provider', error.exception.message_dict)

    def test_category_must_be_enabled_in_complex_provider_contract(self):
        ticket = self.make_ticket(
            category=self.other_category,
            provider=self.provider,
            status=Ticket.Status.ASSIGNED,
        )

        with self.assertRaises(ValidationError) as error:
            ticket.full_clean()

        self.assertIn('category', error.exception.message_dict)

    def test_provider_must_offer_category_enabled_by_contract(self):
        unsupported_category = ServiceCategory.objects.create(
            name='Dog walking',
            slug='dog-walking',
        )
        self.provider_link.service_categories.add(unsupported_category)
        ticket = self.make_ticket(
            category=unsupported_category,
            provider=self.provider,
            status=Ticket.Status.ASSIGNED,
        )

        with self.assertRaises(ValidationError) as error:
            ticket.full_clean()

        self.assertIn('category', error.exception.message_dict)

    def test_assignee_must_be_provider_employee(self):
        ticket = self.make_ticket(
            provider=self.provider,
            assignee=self.outsider,
            status=Ticket.Status.IN_PROGRESS,
        )

        with self.assertRaises(ValidationError) as error:
            ticket.full_clean()

        self.assertIn('assignee', error.exception.message_dict)

    def test_status_transition_is_recorded_in_history(self):
        ticket = self.make_ticket(
            provider=self.provider,
            assignee=self.employee,
        )
        ticket.full_clean()
        ticket.save()

        history = ticket.transition_to(
            Ticket.Status.ASSIGNED,
            changed_by=self.dispatcher,
            comment='Provider selected manually.',
        )

        self.assertEqual(ticket.status, Ticket.Status.ASSIGNED)
        self.assertEqual(history.from_status, Ticket.Status.NEW)
        self.assertEqual(history.to_status, Ticket.Status.ASSIGNED)
        self.assertEqual(history.changed_by, self.dispatcher)
        self.assertEqual(ticket.status_history.count(), 1)

    def test_forbidden_status_transition_does_not_change_ticket(self):
        ticket = self.make_ticket(
            provider=self.provider,
            assignee=self.employee,
        )
        ticket.full_clean()
        ticket.save()

        with self.assertRaises(ValidationError):
            ticket.transition_to(
                Ticket.Status.COMPLETED,
                changed_by=self.dispatcher,
            )

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.NEW)
        self.assertFalse(ticket.status_history.exists())

    def test_in_progress_status_requires_assignee(self):
        ticket = self.make_ticket(
            provider=self.provider,
            status=Ticket.Status.IN_PROGRESS,
        )

        with self.assertRaises(ValidationError) as error:
            ticket.full_clean()

        self.assertIn('status', error.exception.message_dict)

    def test_external_id_prevents_duplicate_import(self):
        ticket_data = {
            'residential_complex': self.residential_complex,
            'applicant': self.applicant,
            'title': 'Imported ticket',
            'description': 'Imported from another system.',
            'category': self.category,
            'source': Ticket.Source.INTEGRATION,
            'external_id': 'external-42',
        }
        Ticket.objects.create(**ticket_data)

        with self.assertRaises(IntegrityError), transaction.atomic():
            Ticket.objects.create(**ticket_data)

    def test_same_external_id_is_allowed_for_different_sources(self):
        first_ticket = self.make_ticket(
            source=Ticket.Source.AI,
            external_id='external-42',
        )
        second_ticket = self.make_ticket(
            source=Ticket.Source.INTEGRATION,
            external_id='external-42',
        )

        first_ticket.save()
        second_ticket.save()

        self.assertNotEqual(first_ticket.pk, second_ticket.pk)

    def test_ticket_stays_in_tsj_queue_without_direct_rule(self):
        ticket = self.make_ticket()
        ticket.full_clean()
        ticket.save()

        apply_initial_routing(ticket, changed_by=self.dispatcher)

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.NEW)
        self.assertIsNone(ticket.provider)
        self.assertFalse(ticket.status_history.exists())

    def test_direct_rule_assigns_provider_without_tsj_approval(self):
        rule = ServiceRoutingRule(
            residential_complex=self.residential_complex,
            category=self.category,
            mode=ServiceRoutingRule.Mode.DIRECT,
            provider=self.provider,
        )
        rule.full_clean()
        rule.save()
        ticket = self.make_ticket()
        ticket.full_clean()
        ticket.save()

        apply_initial_routing(ticket)

        ticket.refresh_from_db()
        self.assertEqual(ticket.provider, self.provider)
        self.assertEqual(ticket.status, Ticket.Status.ASSIGNED)
        history = ticket.status_history.get()
        self.assertIn('автоматически', history.comment)
        self.assertIsNone(history.changed_by)

    def test_direct_rule_rejects_provider_without_matching_contract(self):
        rule = ServiceRoutingRule(
            residential_complex=self.residential_complex,
            category=self.category,
            mode=ServiceRoutingRule.Mode.DIRECT,
            provider=self.other_provider,
        )

        with self.assertRaises(ValidationError) as error:
            rule.full_clean()

        self.assertIn('provider', error.exception.message_dict)
