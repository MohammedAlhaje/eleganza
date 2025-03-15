from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _
from .models import User, PasswordHistory, Address

# Custom User Admin
@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Custom admin interface for User model"""
    list_display = (
        'username', 'email', 'display_name', 'is_phone_verified',
        'is_active', 'is_staff', 'created_at', 'deleted_at'
    )
    list_filter = (
        'is_active', 'is_staff', 'is_superuser', 'data_consent',
        'marketing_consent', 'is_phone_verified', 'deleted_at'
    )
    search_fields = ('username', 'email', 'display_name', 'phone')
    ordering = ('-created_at',)
    
    fieldsets = (
        (None, {
            'fields': ('username', 'password')
        }),
        (_('Personal Info'), {
            'fields': (
                'display_name', 'email', 'phone', 'avatar',
                'date_of_birth', 'is_phone_verified', 'phone_verified_at'
            )
        }),
        (_('Preferences'), {
            'fields': ('timezone', 'language', 'default_currency')
        }),
        (_('Consents'), {
            'fields': (
                'data_consent', 'data_consent_at',
                'marketing_consent', 'marketing_consent_at'
            )
        }),
        (_('Security'), {
            'fields': (
                'failed_login_attempts', 'locked_until',
                'password_updated_at'
            )
        }),
        (_('Permissions'), {
            'fields': (
                'is_active', 'is_staff', 'is_superuser',
                'groups', 'user_permissions'
            )
        }),
        (_('Important dates'), {
            'fields': ('last_login', 'created_at', 'updated_at', 'deleted_at')
        }),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': (
                'username', 'email', 'password1', 'password2',
                'display_name', 'phone'
            )
        }),
    )
    
    readonly_fields = (
        'created_at', 'updated_at', 'deleted_at',
        'password_updated_at', 'phone_verified_at',
        'data_consent_at', 'marketing_consent_at', 'version'
    )
    
    def get_queryset(self, request):
        """Show only non-deleted users by default"""
        qs = self.model.objects.get_queryset()
        ordering = self.get_ordering(request)
        if ordering:
            qs = qs.order_by(*ordering)
        return qs

    def delete_model(self, request, obj):
        """Override to use soft delete"""
        obj.delete()


@admin.register(PasswordHistory)
class PasswordHistoryAdmin(admin.ModelAdmin):
    """Admin interface for PasswordHistory model"""
    list_display = ('user', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('password_hash', 'created_at')
    
    def has_add_permission(self, request):
        """Prevent manual addition of password history"""
        return False
    
    def has_change_permission(self, request, obj=None):
        """Prevent modification of password history"""
        return False


class AddressInline(admin.TabularInline):
    """Inline admin for Address model"""
    model = Address
    extra = 1
    readonly_fields = ('version', 'deleted_at')
    fields = (
        'street', 'city', 'state', 'postal_code',
        'country', 'is_default', 'version', 'deleted_at'
    )


# Register Address model separately as well
@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    """Admin interface for Address model"""
    list_display = (
        'user', 'street', 'city', 'state',
        'postal_code', 'country', 'is_default', 'deleted_at'
    )
    list_filter = ('country', 'is_default', 'deleted_at')
    search_fields = (
        'user__username', 'user__email',
        'street', 'city', 'postal_code'
    )
    readonly_fields = ('version', 'deleted_at')