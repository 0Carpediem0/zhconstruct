import json

from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_POST

from resident_portal.access import resident_required
from tickets.models import Ticket
from tickets.services import apply_initial_routing

from .services import (
    ComplaintAnalysisError,
    analyze_complaint,
    available_categories_for,
    build_ticket_description,
    normalize_text,
)


def _context(request):
    return {
        'applicant': request.applicant,
        'complex': request.applicant.residential_complex,
        'active_nav': 'tickets',
    }


def _json_body(request):
    try:
        return json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return {}


@resident_required
def chat(request):
    return render(request, 'ai_assistant/chat.html', _context(request))


@resident_required
@require_POST
def analyze(request):
    body = _json_body(request)
    message = normalize_text(body.get('message'))
    if len(message) < 5:
        return JsonResponse(
            {'error': 'Опишите проблему чуть подробнее.'},
            status=400,
        )
    if len(message) > 4000:
        return JsonResponse(
            {'error': 'Сообщение слишком длинное. Сократите его до 4000 символов.'},
            status=400,
        )

    categories = available_categories_for(request.applicant)
    if not categories:
        return JsonResponse(
            {'error': 'Для вашего ЖК пока не настроены темы обращений.'},
            status=400,
        )

    try:
        analysis = analyze_complaint(
            message,
            applicant=request.applicant,
            categories=categories,
        )
    except ComplaintAnalysisError as error:
        return JsonResponse({'error': str(error)}, status=502)

    request.session['ai_last_message'] = message
    request.session['ai_last_analysis'] = analysis
    return JsonResponse({'analysis': analysis})


@resident_required
@require_POST
def create_ticket(request):
    body = _json_body(request)
    message = normalize_text(body.get('message'))

    if len(message) < 5:
        return JsonResponse({'error': 'Нет текста обращения.'}, status=400)

    categories = available_categories_for(request.applicant)
    if not categories:
        return JsonResponse(
            {'error': 'Для вашего ЖК пока не настроены темы обращений.'},
            status=400,
        )
    session_message = request.session.get('ai_last_message')
    analysis = request.session.get('ai_last_analysis')
    if session_message != message or not isinstance(analysis, dict):
        try:
            analysis = analyze_complaint(
                message,
                applicant=request.applicant,
                categories=categories,
            )
        except ComplaintAnalysisError as error:
            return JsonResponse({'error': str(error)}, status=502)
    category_id = analysis['category_id']

    ticket = Ticket(
        residential_complex=request.applicant.residential_complex,
        applicant=request.applicant,
        title=analysis['title'],
        description=build_ticket_description(
            raw_message=message,
            analysis=analysis,
        ),
        category_id=category_id,
        source=Ticket.Source.AI,
        priority=analysis['priority'],
        kind=Ticket.Kind.APPEAL,
    )
    try:
        ticket.full_clean()
        ticket.save()
        ticket = apply_initial_routing(ticket, changed_by=request.user)
    except ValidationError as error:
        return JsonResponse(
            {'error': '; '.join(error.messages)},
            status=400,
        )

    request.session.pop('ai_last_message', None)
    request.session.pop('ai_last_analysis', None)
    return JsonResponse(
        {
            'ticket_id': ticket.pk,
            'ticket_url': reverse('resident_portal:ticket-detail', args=(ticket.pk,)),
        },
        status=201,
    )
