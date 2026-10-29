from django import template


register = template.Library()


@register.filter
def status_class(value):
    return {
        'new': 'status-new',
        'awaiting_assignment': 'status-waiting',
        'assigned': 'status-assigned',
        'accepted': 'status-accepted',
        'in_progress': 'status-progress',
        'completed': 'status-completed',
        'cancelled': 'status-cancelled',
    }.get(value, 'status-neutral')


@register.filter
def priority_class(value):
    return {
        'low': 'priority-low',
        'normal': 'priority-normal',
        'high': 'priority-high',
        'urgent': 'priority-urgent',
    }.get(value, 'priority-normal')


@register.filter
def initials(user):
    first_name = (user.first_name or '').strip()
    last_name = (user.last_name or '').strip()
    if first_name or last_name:
        return f'{first_name[:1]}{last_name[:1]}'.upper()
    return user.username[:2].upper()
