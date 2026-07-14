from django.contrib import admin

from .models import (
    ResidentialComplex,
    ResidentialComplexMembership,
    ResidentialComplexProvider,
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
    list_display = ('name', 'address', 'is_active')
    list_filter = ('is_active',)
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
