from django.contrib import admin

from .models import NewsPost, ServiceOrderDetails, UtilityAccount


@admin.register(UtilityAccount)
class UtilityAccountAdmin(admin.ModelAdmin):
    list_display = ('applicant', 'account_number', 'amount_due', 'due_date')
    search_fields = ('applicant__full_name', 'account_number')


@admin.register(NewsPost)
class NewsPostAdmin(admin.ModelAdmin):
    list_display = ('title', 'residential_complex', 'published_at', 'is_published')
    list_filter = ('residential_complex', 'is_published')


@admin.register(ServiceOrderDetails)
class ServiceOrderDetailsAdmin(admin.ModelAdmin):
    list_display = (
        'ticket', 'offering', 'scheduled_date', 'scheduled_start',
        'quoted_price', 'resident_confirmed_at',
    )
    list_filter = ('scheduled_date', 'offering__provider')
