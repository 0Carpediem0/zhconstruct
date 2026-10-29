from django.contrib import admin

from .models import (
    ComplexConfigurationEvent,
    ImplementationTestRun,
    ResidentialComplex,
    ResidentialComplexIntakeChannel,
    ResidentialComplexMembership,
    ResidentialComplexNotificationRule,
    ResidentialComplexProvider,
    ResidentialComplexService,
    ServiceRoutingRule,
)


class ResidentialComplexProviderInline(admin.TabularInline):
    model = ResidentialComplexProvider
    extra = 0


class ResidentialComplexMembershipInline(admin.TabularInline):
    model = ResidentialComplexMembership
    extra = 0
    autocomplete_fields = ('user',)


@admin.register(ResidentialComplex)
class ResidentialComplexAdmin(admin.ModelAdmin):
    list_display = ('name', 'address', 'lifecycle_status', 'is_active')
    list_filter = ('lifecycle_status', 'is_active')
    search_fields = ('name', 'address')
    prepopulated_fields = {'slug': ('name',)}
    inlines = (
        ResidentialComplexProviderInline,
        ResidentialComplexMembershipInline,
    )


@admin.register(ResidentialComplexProvider)
class ResidentialComplexProviderAdmin(admin.ModelAdmin):
    list_display = (
        'residential_complex',
        'provider',
        'source',
        'is_preferred',
        'is_active',
    )
    list_filter = ('source', 'is_preferred', 'is_active')
    search_fields = ('residential_complex__name', 'provider__name')
    autocomplete_fields = ('residential_complex', 'provider')
    filter_horizontal = ('service_categories',)


@admin.register(ResidentialComplexMembership)
class ResidentialComplexMembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'residential_complex', 'role', 'is_active')
    list_filter = ('role', 'is_active')
    search_fields = (
        'user__username',
        'user__email',
        'residential_complex__name',
    )
    autocomplete_fields = ('user', 'residential_complex')


@admin.register(ServiceRoutingRule)
class ServiceRoutingRuleAdmin(admin.ModelAdmin):
    list_display = (
        'residential_complex',
        'category',
        'mode',
        'provider',
        'is_active',
    )
    list_filter = ('mode', 'is_active', 'residential_complex')
    search_fields = (
        'residential_complex__name',
        'category__name',
        'provider__name',
    )
    autocomplete_fields = ('residential_complex', 'category', 'provider')


@admin.register(ResidentialComplexIntakeChannel)
class ResidentialComplexIntakeChannelAdmin(admin.ModelAdmin):
    list_display = (
        'residential_complex', 'channel_type', 'is_enabled', 'is_verified',
    )
    list_filter = ('channel_type', 'is_enabled', 'is_verified')
    autocomplete_fields = ('residential_complex',)


@admin.register(ResidentialComplexService)
class ResidentialComplexServiceAdmin(admin.ModelAdmin):
    list_display = (
        'residential_complex', 'category', 'auto_assignment_enabled', 'is_active',
    )
    list_filter = ('auto_assignment_enabled', 'is_active')
    autocomplete_fields = ('residential_complex', 'category')


@admin.register(ResidentialComplexNotificationRule)
class ResidentialComplexNotificationRuleAdmin(admin.ModelAdmin):
    list_display = ('residential_complex', 'event', 'recipient', 'is_enabled')
    list_filter = ('event', 'recipient', 'is_enabled')
    autocomplete_fields = ('residential_complex',)


@admin.register(ImplementationTestRun)
class ImplementationTestRunAdmin(admin.ModelAdmin):
    list_display = ('residential_complex', 'is_successful', 'started_by', 'created_at')
    list_filter = ('is_successful',)
    readonly_fields = ('results', 'created_at')


@admin.register(ComplexConfigurationEvent)
class ComplexConfigurationEventAdmin(admin.ModelAdmin):
    list_display = ('residential_complex', 'event_type', 'actor', 'created_at')
    list_filter = ('event_type',)
    search_fields = ('residential_complex__name', 'description', 'actor__username')
    readonly_fields = ('created_at',)
