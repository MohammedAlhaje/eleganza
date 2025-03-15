# admin.py
from allauth.account.decorators import secure_admin_login
from django.conf import settings
from django.contrib import admin
from django.contrib.admin import ModelAdmin
from django.contrib.auth import admin as auth_admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from .forms import UserAdminChangeForm, UserAdminCreationForm
from .models import User, Address, PasswordHistory

if settings.DJANGO_ADMIN_FORCE_ALLAUTH:
    # Force the `admin` sign in process to go through the `django-allauth` workflow
    admin.autodiscover()
    admin.site.login = secure_admin_login(admin.site.login)  # type: ignore[method-assign]


class AddressInline(admin.TabularInline):
    """Inline admin for user addresses."""
    model = Address
    extra = 0
    fields = ('street', 'city', 'state', 'postal_code', 'country', 'is_default')
    readonly_fields = ('version',)
    can_delete = True
    show_change_link = True


class PasswordHistoryInline(admin.TabularInline):
    """Inline admin for password history."""
    model = PasswordHistory
    extra = 0
    readonly_fields = ('password_hash', 'created_at')
    fields = ('password_hash', 'created_at')
    can_delete = False
    max_num = 0  # Don't allow adding new password history entries manually


@admin.register(User)
class UserAdmin(auth_admin.UserAdmin):
    """Admin configuration for the User model."""
    form = UserAdminChangeForm
    add_form = UserAdminCreationForm
    inlines = [AddressInline, PasswordHistoryInline]
    
    def avatar_preview(self, obj):
        """Display user avatar thumbnail in admin."""
        if obj.avatar:
            return format_html('<img src="{}" width="50" height="50" style="border-radius: 50%;" />', obj.avatar.url)
        return "No Avatar"
    
    avatar_preview.short_description = "Avatar"
    
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        (_("Personal info"), {"fields": ("email", "phone", "avatar", "avatar_preview", "date_of_birth")}),
        (_("Verification"), {
            "fields": (
                "is_email_verified", "email_verified_at",
                "is_phone_verified", "phone_verified_at"
            ),
        }),
        (_("Consent"), {
            "fields": (
                "data_consent", "data_consent_at",
                "marketing_consent", "marketing_consent_at"
            ),
        }),
        (_("Preferences"), {
            "fields": ("timezone", "language", "default_currency"),
        }),
        (_("Security"), {
            "fields": (
                "mfa_enabled", "mfa_secret",
                "failed_login_attempts", "locked_until",
                "password_updated_at"
            ),
        }),
        (_("Permissions"), {
            "fields": (
                "is_active", "is_staff", "is_superuser",
                "groups", "user_permissions",
            ),
        }),
        (_("Timestamps"), {
            "fields": (
                "last_login", "date_joined", 
                "created_at", "updated_at", "deleted_at"
            ),
        }),
    )
    
    readonly_fields = [
        "avatar_preview", "email_verified_at", "phone_verified_at", 
        "data_consent_at", "marketing_consent_at", "password_updated_at",
        "created_at", "updated_at", "version"
    ]
    
    list_display = [
        "username", "email", "is_email_verified", 
        "avatar_preview", "is_active", "is_staff", "is_superuser"
    ]
    
    list_filter = [
        "is_active", "is_staff", "is_superuser", 
        "is_email_verified", "is_phone_verified",
        "mfa_enabled", "data_consent", "marketing_consent"
    ]
    
    search_fields = ["username", "email", "phone"]
    ordering = ["-date_joined"]


@admin.register(Address)
class AddressAdmin(ModelAdmin):
    """Admin configuration for the Address model."""
    list_display = ["user", "street", "city", "state", "postal_code", "country", "is_default"]
    list_filter = ["country", "is_default"]
    search_fields = ["user__username", "user__email", "street", "city", "postal_code"]
    readonly_fields = ["version"]
    
    fieldsets = (
        (None, {"fields": ("user", "is_default")}),
        (_("Address Details"), {"fields": ("street", "city", "state", "postal_code", "country")}),
        (_("Metadata"), {"fields": ("version", "deleted_at")}),
    )