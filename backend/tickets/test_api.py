from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

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

from .models import Applicant, Ticket


class TicketAPITests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.resident = user_model.objects.create_user(username='resident')
        self.other_resident = user_model.objects.create_user(username='other-resident')
        self.dispatcher = user_model.objects.create_user(username='dispatcher')
        self.provider_manager = user_model.objects.create_user(username='provider-manager')
        self.employee = user_model.objects.create_user(username='employee')
        self.other_employee = user_model.objects.create_user(username='other-employee')

        self.residential_complex = ResidentialComplex.objects.create(
            name='Sunny',
            slug='sunny-api',
            address='Example street, 1',
        )
        self.other_complex = ResidentialComplex.objects.create(
            name='Northern',
            slug='northern-api',
            address='Another street, 2',
        )
        ResidentialComplexMembership.objects.create(
            user=self.dispatcher,
            residential_complex=self.residential_complex,
            role=ResidentialComplexMembership.Role.DISPATCHER,
        )
        self.applicant = Applicant.objects.create(
            residential_complex=self.residential_complex,
            full_name='Anna Applicant',
        )
        self.other_applicant = Applicant.objects.create(
            residential_complex=self.residential_complex,
            full_name='Ivan Applicant',
        )
        self.other_complex_applicant = Applicant.objects.create(
            residential_complex=self.other_complex,
            full_name='Hidden Applicant',
        )

        self.category = ServiceCategory.objects.create(
            name='Cleaning API',
            slug='cleaning-api',
        )
        self.provider = Provider.objects.create(
            name='Clean Home API',
            slug='clean-home-api',
        )
        ProviderService.objects.create(
            provider=self.provider,
            category=self.category,
        )
        ProviderMembership.objects.create(
            user=self.provider_manager,
            provider=self.provider,
            role=ProviderMembership.Role.MANAGER,
        )
        ProviderMembership.objects.create(
            user=self.employee,
            provider=self.provider,
            role=ProviderMembership.Role.EMPLOYEE,
        )
        ProviderMembership.objects.create(
            user=self.other_employee,
            provider=self.provider,
            role=ProviderMembership.Role.EMPLOYEE,
        )
        provider_link = ResidentialComplexProvider.objects.create(
            residential_complex=self.residential_complex,
            provider=self.provider,
            source=ResidentialComplexProvider.Source.PLATFORM,
        )
        provider_link.service_categories.add(self.category)

        self.own_ticket = self.create_ticket(
            applicant=self.applicant,
            title='Own ticket',
        )
        self.other_resident_ticket = self.create_ticket(
            applicant=self.other_applicant,
            title='Other resident ticket',
        )
        self.assigned_ticket = self.create_ticket(
            applicant=self.other_applicant,
            title='Assigned employee ticket',
            provider=self.provider,
            assignee=self.employee,
            ticket_status=Ticket.Status.ASSIGNED,
        )
        self.other_employee_ticket = self.create_ticket(
            applicant=self.applicant,
            title='Other employee ticket',
            provider=self.provider,
            assignee=self.other_employee,
            ticket_status=Ticket.Status.ASSIGNED,
        )
        self.other_complex_ticket = self.create_ticket(
            applicant=self.other_complex_applicant,
            residential_complex=self.other_complex,
            title='Hidden complex ticket',
        )

        self.client = APIClient()

    def create_ticket(
        self,
        *,
        applicant,
        title,
        residential_complex=None,
        provider=None,
        assignee=None,
        ticket_status=Ticket.Status.NEW,
    ):
        ticket = Ticket(
            residential_complex=residential_complex or self.residential_complex,
            applicant=applicant,
            title=title,
            description='API test ticket.',
            category=self.category,
            provider=provider,
            assignee=assignee,
            status=ticket_status,
        )
        ticket.full_clean()
        ticket.save()
        return ticket

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

    def ticket_ids(self, response):
        return {item['id'] for item in response.data}

    def test_authentication_is_required(self):
        response = self.client.get(reverse('ticket-list'))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_resident_cannot_access_internal_ticket_api(self):
        self.authenticate(self.resident)

        response = self.client.get(reverse('ticket-list'))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_hidden_ticket_cannot_be_retrieved_by_id(self):
        self.authenticate(self.resident)

        response = self.client.get(
            reverse('ticket-detail', args=(self.other_resident_ticket.pk,)),
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_ticket_cannot_be_patched_around_workflow(self):
        self.authenticate(self.dispatcher)

        response = self.client.patch(
            reverse('ticket-detail', args=(self.own_ticket.pk,)),
            {'status': Ticket.Status.COMPLETED},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_dispatcher_sees_all_tickets_of_own_complex(self):
        self.authenticate(self.dispatcher)

        response = self.client.get(reverse('ticket-list'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn(self.other_complex_ticket.pk, self.ticket_ids(response))
        self.assertEqual(len(response.data), 4)

    def test_provider_manager_sees_all_provider_tickets(self):
        self.authenticate(self.provider_manager)

        response = self.client.get(reverse('ticket-list'))

        self.assertSetEqual(
            self.ticket_ids(response),
            {self.assigned_ticket.pk, self.other_employee_ticket.pk},
        )

    def test_employee_sees_only_assigned_personal_ticket(self):
        self.authenticate(self.employee)

        response = self.client.get(reverse('ticket-list'))

        self.assertSetEqual(self.ticket_ids(response), {self.assigned_ticket.pk})

    def test_resident_cannot_create_ticket_through_internal_api(self):
        self.authenticate(self.resident)
        payload = {
            'residential_complex': self.residential_complex.pk,
            'applicant': self.applicant.pk,
            'title': 'New API ticket',
            'description': 'Created by resident.',
            'category': self.category.pk,
            'priority': Ticket.Priority.HIGH,
        }

        response = self.client.post(reverse('ticket-list'), payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_dispatcher_can_create_ticket_for_resident_of_own_complex(self):
        self.authenticate(self.dispatcher)
        payload = {
            'residential_complex': self.residential_complex.pk,
            'applicant': self.other_applicant.pk,
            'title': 'Dispatcher ticket',
            'description': 'Created after a phone call.',
            'category': self.category.pk,
        }

        response = self.client.post(reverse('ticket-list'), payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            Ticket.objects.get(pk=response.data['id']).applicant,
            self.other_applicant,
        )

    def test_direct_rule_routes_new_ticket_in_same_api_request(self):
        rule = ServiceRoutingRule(
            residential_complex=self.residential_complex,
            category=self.category,
            mode=ServiceRoutingRule.Mode.DIRECT,
            provider=self.provider,
        )
        rule.full_clean()
        rule.save()
        self.authenticate(self.dispatcher)

        response = self.client.post(
            reverse('ticket-list'),
            {
                'residential_complex': self.residential_complex.pk,
                'applicant': self.applicant.pk,
                'title': 'Direct cleaning ticket',
                'description': 'Route immediately.',
                'category': self.category.pk,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], Ticket.Status.ASSIGNED)
        self.assertEqual(response.data['provider']['id'], self.provider.pk)
        self.assertEqual(
            Ticket.objects.get(pk=response.data['id']).status,
            Ticket.Status.ASSIGNED,
        )

    def test_provider_cannot_register_ticket(self):
        self.authenticate(self.provider_manager)
        payload = {
            'residential_complex': self.residential_complex.pk,
            'applicant': self.applicant.pk,
            'title': 'Provider-created ticket',
            'description': 'Should be rejected.',
            'category': self.category.pk,
        }

        response = self.client.post(reverse('ticket-list'), payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_external_user_cannot_create_ticket_for_applicant(self):
        self.authenticate(self.resident)
        payload = {
            'residential_complex': self.residential_complex.pk,
            'applicant': self.other_applicant.pk,
            'title': 'Foreign ticket',
            'description': 'Should be rejected.',
            'category': self.category.pk,
        }

        response = self.client.post(reverse('ticket-list'), payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_dispatcher_assigns_provider_and_creates_history(self):
        self.authenticate(self.dispatcher)
        url = reverse('ticket-assign-provider', args=(self.own_ticket.pk,))

        response = self.client.post(
            url,
            {'provider': self.provider.pk, 'comment': 'Manual routing.'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.own_ticket.refresh_from_db()
        self.assertEqual(self.own_ticket.provider, self.provider)
        self.assertEqual(self.own_ticket.status, Ticket.Status.ASSIGNED)
        self.assertEqual(self.own_ticket.status_history.count(), 1)

    def test_resident_cannot_assign_provider(self):
        self.authenticate(self.resident)
        url = reverse('ticket-assign-provider', args=(self.own_ticket.pk,))

        response = self.client.post(
            url,
            {'provider': self.provider.pk},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_provider_manager_assigns_employee(self):
        self.authenticate(self.provider_manager)
        url = reverse('ticket-assign-employee', args=(self.assigned_ticket.pk,))

        response = self.client.post(
            url,
            {'employee': self.other_employee.pk},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assigned_ticket.refresh_from_db()
        self.assertEqual(self.assigned_ticket.assignee, self.other_employee)

    def test_employee_changes_status_through_workflow(self):
        self.authenticate(self.employee)
        url = reverse('ticket-change-status', args=(self.assigned_ticket.pk,))

        accepted = self.client.post(
            url,
            {'status': Ticket.Status.ACCEPTED},
            format='json',
        )
        in_progress = self.client.post(
            url,
            {'status': Ticket.Status.IN_PROGRESS},
            format='json',
        )

        self.assertEqual(accepted.status_code, status.HTTP_200_OK)
        self.assertEqual(in_progress.status_code, status.HTTP_200_OK)
        self.assigned_ticket.refresh_from_db()
        self.assertEqual(self.assigned_ticket.status, Ticket.Status.IN_PROGRESS)
        self.assertEqual(self.assigned_ticket.status_history.count(), 2)

    def test_invalid_transition_returns_bad_request(self):
        self.authenticate(self.employee)
        url = reverse('ticket-change-status', args=(self.assigned_ticket.pk,))

        response = self.client.post(
            url,
            {'status': Ticket.Status.COMPLETED},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assigned_ticket.refresh_from_db()
        self.assertEqual(self.assigned_ticket.status, Ticket.Status.ASSIGNED)

    def test_ticket_list_can_be_filtered_by_status(self):
        self.authenticate(self.dispatcher)

        response = self.client.get(
            reverse('ticket-list'),
            {'status': Ticket.Status.ASSIGNED},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertSetEqual(
            self.ticket_ids(response),
            {self.assigned_ticket.pk, self.other_employee_ticket.pk},
        )

    def test_visible_ticket_history_can_be_requested(self):
        self.assigned_ticket.transition_to(
            Ticket.Status.ACCEPTED,
            changed_by=self.employee,
        )
        self.authenticate(self.employee)

        response = self.client.get(
            reverse('ticket-history', args=(self.assigned_ticket.pk,)),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['to_status'], Ticket.Status.ACCEPTED)

    def test_resident_cannot_access_internal_reference_lists(self):
        self.authenticate(self.resident)

        complexes_response = self.client.get(reverse('residential-complex-list'))
        providers_response = self.client.get(reverse('provider-list'))

        self.assertEqual(complexes_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(providers_response.status_code, status.HTTP_403_FORBIDDEN)
