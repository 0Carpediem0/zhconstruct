from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('Платформа ЖКонстракт', {'fields': ('platform_role',)}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Платформа ЖКонстракт', {'fields': ('platform_role',)}),
    )
    list_display = UserAdmin.list_display + ('platform_role',)
