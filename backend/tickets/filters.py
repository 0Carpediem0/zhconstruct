from django.db.models import Q
from django.utils.dateparse import parse_date


def filter_ticket_queryset(queryset, parameters):
    """Общие фильтры для REST API и веб-таблицы заявок."""

    text_filters = {
        'status': 'status',
        'priority': 'priority',
        'source': 'source',
    }
    for parameter, field in text_filters.items():
        value = parameters.get(parameter)
        if value:
            queryset = queryset.filter(**{field: value})

    id_filters = {
        'residential_complex': 'residential_complex_id',
        'category': 'category_id',
        'provider': 'provider_id',
        'assignee': 'assignee_id',
    }
    for parameter, field in id_filters.items():
        value = parameters.get(parameter)
        if value and value.isdecimal():
            queryset = queryset.filter(**{field: value})

    created_from = parse_date(parameters.get('created_from', ''))
    created_to = parse_date(parameters.get('created_to', ''))
    if created_from:
        queryset = queryset.filter(created_at__date__gte=created_from)
    if created_to:
        queryset = queryset.filter(created_at__date__lte=created_to)

    search_query = parameters.get('q', '').strip()
    if search_query:
        queryset = queryset.filter(
            Q(title__icontains=search_query)
            | Q(description__icontains=search_query)
            | Q(external_id__icontains=search_query)
            | Q(applicant__full_name__icontains=search_query)
            | Q(applicant__phone__icontains=search_query)
            | Q(applicant__apartment__icontains=search_query)
            | Q(provider__name__icontains=search_query)
        )
    return queryset
