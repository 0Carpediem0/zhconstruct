from django.contrib import admin

from .models import Provider, ProviderMembership, ProviderService, ServiceCategory


class ProviderServiceInline(admin.TabularInline):
    model = ProviderService
    extra = 0


class ProviderMembershipInline(admin.TabularInline):
    model = ProviderMembership
    extra = 0
    autocomplete_fields = ('user',)


@admin.register(ServiceCategory)
class ServiceCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name', 'description')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Provider)
class ProviderAdmin(admin.ModelAdmin):
    list_display = ('name', 'tax_id', 'is_platform_partner', 'is_active')
    list_filter = ('is_platform_partner', 'is_active')
    search_fields = ('name', 'tax_id', 'email', 'phone')
    prepopulated_fields = {'slug': ('name',)}
    inlines = (ProviderServiceInline, ProviderMembershipInline)


@admin.register(ProviderMembership)
class ProviderMembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'provider', 'role', 'is_active')
    list_filter = ('role', 'is_active')
    search_fields = ('user__username', 'user__email', 'provider__name')
    autocomplete_fields = ('user', 'provider')
