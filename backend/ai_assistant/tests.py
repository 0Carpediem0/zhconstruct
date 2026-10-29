import json

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from complexes.models import ResidentialComplex, ResidentialComplexService
from providers.models import ServiceCategory
from tickets.models import Applicant, Ticket

from .services import analyze_complaint


@override_settings(OPENAI_API_KEY='', AI_ASSISTANT_ALLOW_FALLBACK=True)
class AiAssistantTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username='resident')
        self.complex = ResidentialComplex.objects.create(
            name='Sunny',
            slug='ai-sunny',
            address='Example street, 1',
        )
        self.applicant = Applicant.objects.create(
            residential_complex=self.complex,
            user=self.user,
            full_name='Anna Resident',
            apartment='42',
        )
        self.category = ServiceCategory.objects.create(
            name='Сантехника',
            slug='plumbing',
        )
        ResidentialComplexService.objects.create(
            residential_complex=self.complex,
            category=self.category,
        )
        self.categories = [
            {
                'category__id': self.category.pk,
                'category__name': self.category.name,
                'category__slug': self.category.slug,
            },
        ]

    def test_rules_fallback_extracts_urgent_plumbing_ticket(self):
        analysis = analyze_complaint(
            'В третьем подъезде прорвало трубу, вода течет на лестницу.',
            applicant=self.applicant,
            categories=self.categories,
        )

        self.assertEqual(analysis['priority'], Ticket.Priority.URGENT)
        self.assertEqual(analysis['category_slug'], 'plumbing')
        self.assertIn('третьем подъезде', analysis['location'])

    def test_resident_can_create_ai_ticket(self):
        self.client.force_login(self.user)
        analyze_response = self.client.post(
            reverse('ai_assistant:analyze'),
            data=json.dumps(
                {'message': 'В подъезде 2 течет труба, вода уже на полу.'}
            ),
            content_type='application/json',
        )
        self.assertEqual(analyze_response.status_code, 200)

        create_response = self.client.post(
            reverse('ai_assistant:create-ticket'),
            data=json.dumps(
                {
                    'message': 'В подъезде 2 течет труба, вода уже на полу.',
                    'analysis': analyze_response.json()['analysis'],
                }
            ),
            content_type='application/json',
        )

        self.assertEqual(create_response.status_code, 201)
        ticket = Ticket.objects.get(pk=create_response.json()['ticket_id'])
        self.assertEqual(ticket.source, Ticket.Source.AI)
        self.assertEqual(ticket.priority, Ticket.Priority.HIGH)

