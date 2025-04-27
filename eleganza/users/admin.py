from django.contrib import admin
from django.contrib.auth.admin import UserAdmin, GroupAdmin
from django.contrib.auth.models import Group, Permission
from django.utils.translation import gettext_lazy as _
from django.contrib.admin.widgets import AdminFileWidget
from django.utils.safestring import mark_safe
from django.db import models
from django.urls import reverse
from django.utils.html import format_html
from .models import User, CustomerProfile, TeamMemberProfile, Address, PasswordHistory,ContactMethod


@admin.register(ContactMethod)
class ContactMethodAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name', 'code')
    prepopulated_fields = {'code': ('name',)}  # Auto-slug on add
    list_editable = ('is_active',)
    ordering = ('name',)
    date_hierarchy = 'created_at'
    
    fieldsets = (
        (None, {
            'fields': ('name', 'code', 'is_active')
        }),
        (_('Metadata'), {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    readonly_fields = ('created_at', 'updated_at')

    def get_readonly_fields(self, request, obj=None):
        """Make code read-only ONLY during editing"""
        if obj:  # Existing object
            return self.readonly_fields + ('code',)
        return self.readonly_fields

    def get_prepopulated_fields(self, request, obj=None):
        """Only enable auto-slug when creating new objects"""
        if obj:  # Editing existing
            return {}
        return {'code': ('name',)}


class AdminImageWidget(AdminFileWidget):
    def render(self, name, value, attrs=None, renderer=None):
        output = []
        if value and getattr(value, "url", None):
            output.append(f'<a href="{value.url}" target="_blank">'
                          f'<img src="{value.url}" style="max-height: 150px; max-width: 150px;" />'
                          f'</a>')
        output.append(super().render(name, value, attrs, renderer))
        return mark_safe(''.join(output))

class ProfileInline(admin.StackedInline):
    extra = 0
    max_num = 1
    formfield_overrides = {
        models.ImageField: {'widget': AdminImageWidget}
    }

class CustomerProfileInline(ProfileInline):
    model = CustomerProfile
    fields = ('phone', 'timezone', 'language', 'avatar',
              'loyalty_points', 'newsletter_subscribed',
              'preferred_contact_method', 'default_currency')

class TeamMemberProfileInline(ProfileInline):
    model = TeamMemberProfile
    fields = ('phone', 'timezone', 'language', 'avatar',
              'department', 'can_approve_orders',
              'default_currency', 'profit_percentage')

class AddressInline(admin.TabularInline):
    model = Address
    extra = 0
    fields = ('street', 'city', 'postal_code', 'country', 'is_primary')
    ordering = ('-is_primary', 'city')

class PasswordHistoryInline(admin.TabularInline):
    model = PasswordHistory
    extra = 0
    readonly_fields = ('password', 'created_at')
    fields = ('password', 'created_at')
    ordering = ('-created_at',)
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    inlines = [CustomerProfileInline, TeamMemberProfileInline, 
               AddressInline, PasswordHistoryInline]
    list_display = ('username', 'display_name', 'email', 'type', 
                   'is_active', 'is_staff', 'created_at')
    list_filter = ('type', 'is_active', 'is_staff', 'is_superuser')
    search_fields = ('username', 'email', 'display_name', 'uuid')
    ordering = ('-created_at',)
    readonly_fields = ('uuid', 'last_login', 'created_at', 'updated_at', 'password')
    autocomplete_fields = ('groups', 'user_permissions')
    list_select_related = True
    fieldsets = (
        (None, {'fields': ('username', 'email', 'password')}),
        (_('Profile'), {'fields': ('display_name',)}),
        (_('Permissions'), {
            'fields': ('type', 'is_active', 'is_staff', 
                      'is_superuser', 'groups', 'user_permissions'),
        }),
        (_('Important dates'), {'fields': ('last_login', 'created_at', 'updated_at')}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'email', 'display_name', 'type',
                      'password1', 'password2'),
        }),
    )

    def get_fieldsets(self, request, obj=None):
        fieldsets = super().get_fieldsets(request, obj)
        if obj:
            password_url = reverse('admin:auth_user_password_change', args=[obj.id])
            description = format_html(
                '<a href="{}">{}</a>',
                password_url,
                _("Change password using this form.")
            )
            if fieldsets:
                fieldsets = list(fieldsets)
                fieldsets[0][1]['description'] = description
        return fieldsets

    def get_inline_instances(self, request, obj=None):
        if obj:
            if obj.type == User.Types.CUSTOMER:
                return [CustomerProfileInline(self.model, self.admin_site),
                        AddressInline(self.model, self.admin_site),
                        PasswordHistoryInline(self.model, self.admin_site)]
            elif obj.type == User.Types.TEAM_MEMBER:
                return [TeamMemberProfileInline(self.model, self.admin_site),
                        PasswordHistoryInline(self.model, self.admin_site)]
        return []

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related(
            'addresses', 'password_history'
        )

@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = ('user', 'city', 'country', 'is_primary')
    list_filter = ('country', 'is_primary')
    search_fields = ('city', 'street', 'postal_code')
    raw_id_fields = ('user',)

@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    search_fields = ['codename', 'name']
    list_filter = ['content_type']
    list_display = ('name', 'codename', 'content_type')

@admin.register(PasswordHistory)
class PasswordHistoryAdmin(admin.ModelAdmin):
    list_display = ('user', 'created_at')
    readonly_fields = ('user', 'password', 'created_at')
    search_fields = ('user__email', 'user__uuid')
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

admin.site.unregister(Group)
@admin.register(Group)
class CustomGroupAdmin(GroupAdmin):
    search_fields = ['name']