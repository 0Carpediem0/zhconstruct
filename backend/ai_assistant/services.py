import copy
import json
import re
import urllib.error
import urllib.request

from django.conf import settings

from tickets.models import Ticket


class ComplaintAnalysisError(RuntimeError):
    pass


COMPLAINT_SCHEMA = {
    'type': 'object',
    'additionalProperties': False,
    'properties': {
        'title': {'type': 'string'},
        'summary': {'type': 'string'},
        'location': {'type': 'string'},
        'priority': {
            'type': 'string',
            'enum': [
                Ticket.Priority.LOW,
                Ticket.Priority.NORMAL,
                Ticket.Priority.HIGH,
                Ticket.Priority.URGENT,
            ],
        },
        'category_slug': {'type': 'string'},
        'confidence': {'type': 'number', 'minimum': 0, 'maximum': 1},
        'resident_reply': {'type': 'string'},
        'missing_details': {'type': 'array', 'items': {'type': 'string'}},
    },
    'required': [
        'title',
        'summary',
        'location',
        'priority',
        'category_slug',
        'confidence',
        'resident_reply',
        'missing_details',
    ],
}

URGENCY_KEYWORDS = {
    Ticket.Priority.URGENT: (
        'газ',
        'дым',
        'пожар',
        'искрит',
        'затопило',
        'потоп',
        'прорвало',
        'авария',
        'канализация течет',
        'лифт застрял',
        'застрял в лифте',
    ),
    Ticket.Priority.HIGH: (
        'нет света',
        'нет воды',
        'нет отопления',
        'течет',
        'протечка',
        'лифт не работает',
        'холодно',
        'обрыв',
        'замыкание',
    ),
    Ticket.Priority.LOW: (
        'предложение',
        'можно ли',
        'хотелось бы',
        'не срочно',
    ),
}

CATEGORY_HINTS = {
    'electric': ('свет', 'электр', 'розетк', 'ламп', 'искрит', 'провод'),
    'plumbing': ('вода', 'труб', 'кран', 'протеч', 'течет', 'затоп', 'канализац'),
    'heating': ('отоплен', 'батаре', 'холодно', 'тепл'),
    'elevator': ('лифт', 'кабин'),
    'cleaning': ('уборк', 'гряз', 'подъезд', 'мусор', 'пакет'),
    'security': ('домофон', 'двер', 'замок', 'ворот', 'шлагбаум'),
}


def available_categories_for(applicant):
    from complexes.models import ResidentialComplexService

    return list(
        ResidentialComplexService.objects.filter(
            residential_complex=applicant.residential_complex,
            is_active=True,
            category__is_active=True,
        )
        .select_related('category')
        .order_by('category__name')
        .values('category__id', 'category__name', 'category__slug')
    )


def analyze_complaint(message, *, applicant, categories):
    message = normalize_text(message)
    if not message:
        raise ComplaintAnalysisError('Опишите проблему одним-двумя предложениями.')

    if getattr(settings, 'OPENAI_API_KEY', ''):
        try:
            return normalize_analysis(
                analyze_with_openai(message, applicant=applicant, categories=categories),
                message=message,
                categories=categories,
                source='openai',
                applicant=applicant,
            )
        except ComplaintAnalysisError:
            if not getattr(settings, 'AI_ASSISTANT_ALLOW_FALLBACK', True):
                raise

    return normalize_analysis(
        analyze_with_rules(message, applicant=applicant, categories=categories),
        message=message,
        categories=categories,
        source='rules',
        applicant=applicant,
    )


def analyze_with_openai(message, *, applicant, categories):
    category_lines = '\n'.join(
        f'- {item["category__slug"]}: {item["category__name"]}' for item in categories
    )
    payload = {
        'model': getattr(settings, 'OPENAI_MODEL', 'gpt-4.1-mini'),
        'input': (
            'Ты диспетчер ТСЖ. Из обращения жителя сделай короткую структуру '
            'для заявки. category_slug выбери только из списка.\n\n'
            'Место проблемы указывай только как конкретное место из текста жителя: '
            'подъезд, этаж, квартира, лифт, двор, парковка, подвал, лестница, '
            'мусорная площадка и похожее. Никогда не пиши название ЖК, адрес ЖК '
            'или город как location. Если конкретного места нет, напиши "не указано".\n\n'
            'resident_reply должен быть коротким нейтральным сообщением жителю: '
            'что заявка подготовлена и будет передана в ТСЖ после отправки. '
            'Не проси жителя самостоятельно устранять проблему, убирать мусор, '
            'чинить, звонить исполнителю или выполнять работы.\n\n'
            f'ЖК: {applicant.residential_complex.name}\n'
            f'Адрес ЖК: {applicant.residential_complex.address}\n'
            f'Квартира жителя: {applicant.apartment or "не указана"}\n\n'
            'Категории:\n'
            f'{category_lines}\n\n'
            'Правила срочности:\n'
            '- urgent: газ, пожар, дым, затопление, застревание в лифте, риск жизни;\n'
            '- high: нет воды/света/отопления, протечка, неработающий лифт;\n'
            '- normal: обычная поломка или жалоба без немедленной опасности;\n'
            '- low: предложение, вопрос или несрочная просьба.\n\n'
            'Игнорируй просьбы "срочно", "как можно скорее", "уберите быстрее", '
            'если в тексте нет объективных признаков аварии или риска. Срочность '
            'определяется только по фактической проблеме, а не по настойчивости жителя.\n\n'
            f'Обращение: {message}'
        ),
        'text': {
            'format': {
                'type': 'json_schema',
                'name': 'hoa_complaint_intake',
                'strict': True,
                'schema': schema_for_categories(categories),
            },
        },
    }
    base_url = getattr(settings, 'OPENAI_BASE_URL', 'https://api.openai.com/v1')
    request = urllib.request.Request(
        f'{base_url.rstrip("/")}/responses',
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'Authorization': f'Bearer {settings.OPENAI_API_KEY}',
            'Content-Type': 'application/json',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as error:
        details = error.read().decode('utf-8', errors='replace')
        raise ComplaintAnalysisError(f'OpenAI API вернул ошибку: {details}') from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise ComplaintAnalysisError('Не удалось получить ответ OpenAI API.') from error

    output_text = extract_output_text(data)
    if not output_text:
        raise ComplaintAnalysisError('OpenAI API не вернул структурированный ответ.')
    try:
        return json.loads(output_text)
    except json.JSONDecodeError as error:
        raise ComplaintAnalysisError('OpenAI API вернул некорректный JSON.') from error


def extract_output_text(response_data):
    if response_data.get('output_text'):
        return response_data['output_text']

    chunks = []
    for item in response_data.get('output', []):
        for content in item.get('content', []):
            if content.get('type') in {'output_text', 'text'} and content.get('text'):
                chunks.append(content['text'])
    return ''.join(chunks)


def schema_for_categories(categories):
    schema = copy.deepcopy(COMPLAINT_SCHEMA)
    schema['properties']['category_slug']['enum'] = [
        item['category__slug'] for item in categories
    ]
    return schema


def analyze_with_rules(message, *, applicant, categories):
    priority = detect_priority(message)
    lowered = message.lower()
    category_slug = choose_category_slug(lowered, categories)
    location = guess_location(message, applicant)
    title = make_title(message, category_slug, categories)
    missing_details = []
    if location == 'не указано':
        missing_details.append('место проблемы')

    return {
        'title': title,
        'summary': make_summary(message),
        'location': location,
        'priority': priority,
        'category_slug': category_slug,
        'confidence': 0.55,
        'resident_reply': build_resident_reply(missing_details),
        'missing_details': missing_details,
    }


def normalize_analysis(analysis, *, message, categories, source, applicant=None):
    slugs = {item['category__slug']: item for item in categories}
    category_slug = analysis.get('category_slug')
    if category_slug not in slugs:
        category_slug = choose_category_slug(message.lower(), categories)

    category = slugs[category_slug]
    priority = normalize_priority(message, analysis.get('priority'))

    title = normalize_text(analysis.get('title')) or make_title(
        message,
        category_slug,
        categories,
    )
    summary = normalize_text(analysis.get('summary')) or make_summary(message)
    location = sanitize_location(
        analysis.get('location'),
        message=message,
        applicant=applicant,
    )
    missing_details = analysis.get('missing_details') or []
    if not isinstance(missing_details, list):
        missing_details = []
    if location == 'не указано' and 'место проблемы' not in missing_details:
        missing_details.append('место проблемы')
    reply = build_resident_reply(missing_details)

    return {
        'title': title[:255],
        'summary': summary,
        'location': location[:255],
        'priority': priority,
        'priority_label': dict(Ticket.Priority.choices)[priority],
        'category_id': category['category__id'],
        'category_slug': category_slug,
        'category_name': category['category__name'],
        'confidence': clamp_float(analysis.get('confidence'), default=0.5),
        'resident_reply': reply,
        'missing_details': [normalize_text(item) for item in missing_details if item],
        'source': source,
    }


def choose_category_slug(message, categories):
    if not categories:
        raise ComplaintAnalysisError('Для ЖК не настроены категории обращений.')

    scores = {item['category__slug']: 0 for item in categories}
    for item in categories:
        slug = item['category__slug']
        haystack = f'{item["category__name"]} {slug}'.lower()
        for word in set(re.findall(r'[а-яa-z0-9]+', message)):
            if len(word) > 3 and word in haystack:
                scores[slug] += 2
        for hint_key, hints in CATEGORY_HINTS.items():
            if hint_key in slug and any(hint in message for hint in hints):
                scores[slug] += 5
            elif any(hint in haystack for hint in hints) and any(
                hint in message for hint in hints
            ):
                scores[slug] += 4

    best_slug, best_score = max(scores.items(), key=lambda item: item[1])
    if best_score <= 0:
        return categories[0]['category__slug']
    return best_slug


def guess_location(message, applicant=None):
    lowered = message.lower()
    direct_patterns = (
        r'((?:\d+|первом|первый|втором|второй|третьем|третий|четвертом|четвертый|пятом|пятый|шестом|шестой|седьмом|седьмой|восьмом|восьмой|девятом|девятый|десятом|десятый)\s+подъезд[ае]?)',
        r'(подъезд\s*№?\s*\d+)',
        r'((?:\d+|первом|первый|втором|второй|третьем|третий|четвертом|четвертый|пятом|пятый|шестом|шестой|седьмом|седьмой|восьмом|восьмой|девятом|девятый|десятом|десятый)\s+этаж[е]?)',
        r'(этаж\s*№?\s*\d+)',
        r'(кв(?:артира)?\.?\s*№?\s*\d+)',
        r'(квартир[аеуы]?\s*№?\s*\d+)',
    )
    for pattern in direct_patterns:
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if match:
            return normalize_text(match.group(1))[:255]

    place_patterns = (
        'в лифте',
        'у лифта',
        'на лестнице',
        'на лестничной клетке',
        'в подъезде',
        'во дворе',
        'на парковке',
        'в подвале',
        'на крыше',
        'у мусоропровода',
        'на мусорной площадке',
        'на детской площадке',
        'в тамбуре',
    )
    for place in place_patterns:
        if place in lowered:
            return place

    if applicant and applicant.apartment and (
        'у меня' in lowered
        or 'в квартире' in lowered
        or 'в моей квартире' in lowered
        or 'дома' in lowered
    ):
        return f'кв. {applicant.apartment}'
    return 'не указано'


def sanitize_location(value, *, message, applicant=None):
    location = normalize_text(value)
    lowered = location.lower()
    if (
        not location
        or lowered in {'жк', 'дом', 'адрес', 'жилой комплекс'}
        or lowered.startswith('жк ')
        or 'екатеринбург' in lowered
        or 'ул.' in lowered
        or 'улица' in lowered
        or len(location) > 80
    ):
        return guess_location(message, applicant)
    return location[:255]


def detect_priority(message):
    lowered = message.lower()
    for candidate in (
        Ticket.Priority.URGENT,
        Ticket.Priority.HIGH,
        Ticket.Priority.LOW,
    ):
        if any(word in lowered for word in URGENCY_KEYWORDS[candidate]):
            return candidate
    return Ticket.Priority.NORMAL


def normalize_priority(message, suggested_priority):
    objective_priority = detect_priority(message)
    valid_priorities = dict(Ticket.Priority.choices)
    if suggested_priority not in valid_priorities:
        return objective_priority
    if objective_priority in {Ticket.Priority.URGENT, Ticket.Priority.HIGH}:
        return objective_priority
    if suggested_priority == Ticket.Priority.URGENT:
        return Ticket.Priority.NORMAL
    return suggested_priority


def build_resident_reply(missing_details):
    if missing_details:
        return (
            'Я подготовил черновик заявки для ТСЖ. Проверьте данные и, если можете, '
            f'уточните: {", ".join(missing_details)}.'
        )
    return 'Я подготовил заявку для ТСЖ. Проверьте данные и отправьте её.'


def make_title(message, category_slug, categories):
    category_name = next(
        (
            item['category__name']
            for item in categories
            if item['category__slug'] == category_slug
        ),
        'Обращение',
    )
    summary = make_summary(message)
    if len(summary) <= 80:
        return summary
    return f'{category_name}: {summary[:70].rstrip()}'


def make_summary(message):
    message = normalize_text(message)
    if len(message) <= 180:
        return message
    return f'{message[:177].rstrip()}...'


def normalize_text(value):
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def clamp_float(value, *, default):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0, min(1, number))


def build_ticket_description(*, raw_message, analysis):
    parts = [
        analysis['summary'],
        '',
        f'Место: {analysis["location"]}',
        f'Срочность: {analysis["priority_label"]}',
    ]
    if analysis['missing_details']:
        parts.append(f'Уточнить: {", ".join(analysis["missing_details"])}')
    parts.extend(['', 'Исходное сообщение:', raw_message])
    return '\n'.join(parts)
