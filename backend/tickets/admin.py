from django.contrib import admin

from .models import Applicant, Ticket, TicketStatusHistory


@admin.register(Applicant)
class ApplicantAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'residential_complex', 'apartment', 'phone', 'is_active')
    list_filter = ('residential_complex', 'is_active')
    search_fields = ('full_name', 'phone', 'email', 'apartment', 'external_id')
    autocomplete_fields = ('residential_complex',)


class TicketStatusHistoryInline(admin.TabularInline):
    """История доступна для аудита, но не редактируется вручную."""

    model = TicketStatusHistory
    extra = 0
    can_delete = False
    readonly_fields = (
        'from_status',
        'to_status',
        'changed_by',
        'comment',
        'created_at',
    )

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'title',
        'residential_complex',
        'category',
        'provider',
        'assignee',
        'status',
        'priority',
        'created_at',
    )
    list_filter = ('status', 'priority', 'source', 'residential_complex')
    search_fields = (
        'title',
        'description',
        'external_id',
        'applicant__full_name',
        'applicant__phone',
        'provider__name',
    )
    autocomplete_fields = (
        'residential_complex',
        'applicant',
        'category',
        'provider',
        'assignee',
    )
    # Статус нельзя редактировать как обычное поле: иначе будет потеряна
    # история. Позже смена статуса появится как отдельное действие/API.
    readonly_fields = ('status', 'created_at', 'updated_at')
    inlines = (TicketStatusHistoryInline,)


@admin.register(TicketStatusHistory)
class TicketStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ('ticket', 'from_status', 'to_status', 'changed_by', 'created_at')
    list_filter = ('from_status', 'to_status')
    search_fields = ('ticket__title', 'comment', 'changed_by__username')
    readonly_fields = (
        'ticket',
        'from_status',
        'to_status',
        'changed_by',
        'comment',
        'created_at',
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
