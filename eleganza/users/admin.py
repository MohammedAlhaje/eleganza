# admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.translation import gettext_lazy as _
from .models import *

class SoftDeleteAdmin(admin.ModelAdmin):
    """
    Base admin class for soft-deletable models
    """
    list_display = ('__str__', 'is_deleted', 'created_at')
    list_filter = ('deleted_at',)
    actions = ['restore_selected']
    readonly_fields = ('deleted_at',)  # Removed created/updated_at

    def get_queryset(self, request):
        return self.model.all_objects.all()

    def restore_selected(self, request, queryset):
        queryset.update(deleted_at=None)
    restore_selected.short_description = _("Restore selected items")

    def is_deleted(self, obj):
        return obj.is_deleted
    is_deleted.boolean = True
    is_deleted.short_description = _("Deleted")

# region User Administration
class ProfileInline(admin.StackedInline):
    """Base profile inline"""
    extra = 0
    max_num = 1
    can_delete = False

class CustomerProfileInline(ProfileInline):
    model = CustomerProfile
    fields = ('preferred_contact_method', 'loyalty_points')
    fk_name = 'user'

class TeamMemberProfileInline(ProfileInline):
    model = TeamMemberProfile
    fields = ('department', 'profit_percentage')
    fk_name = 'user'

class CustomUserAdmin(UserAdmin, SoftDeleteAdmin):
    """Custom admin interface for User model"""
    inlines = (CustomerProfileInline, TeamMemberProfileInline)
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        (_('Permissions'), {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
        }),
        (_('Important dates'), {'fields': ('last_login', 'date_joined', 'deleted_at')}),
        (_('User Type'), {'fields': ('type',)}),
    )
    list_display = ('username', 'type', 'is_active', 'is_deleted')
    list_filter = ('type', 'is_active', 'deleted_at')
    search_fields = ('username',)
    ordering = ('-date_joined',)
    readonly_fields = ('deleted_at', 'last_login', 'date_joined')  # Corrected fields

    def get_inline_instances(self, request, obj=None):
        if obj and obj.type == User.Types.CUSTOMER:
            return [CustomerProfileInline(self.model, self.admin_site)]
        elif obj and obj.type == User.Types.TEAM_MEMBER:
            return [TeamMemberProfileInline(self.model, self.admin_site)]
        return []

admin.site.register(User, CustomUserAdmin)

@admin.register(CustomerProfile)
class CustomerProfileAdmin(admin.ModelAdmin):
    """Admin for Customer Profiles"""
    list_display = ('user', 'preferred_contact_method', 'loyalty_points')
    search_fields = ('user__username',)
    autocomplete_fields = ('user',)

@admin.register(PasswordHistory)
class PasswordHistoryAdmin(admin.ModelAdmin):
    """Admin for password history"""
    list_display = ('user', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('user__username',)
    readonly_fields = ('password_hash',)
    ordering = ('-created_at',)
# endregion

# region Product Administration
class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1
    fields = ('image', 'caption', 'is_primary')
    readonly_fields = ('created_at',)

@admin.register(Product)
class ProductAdmin(SoftDeleteAdmin):
    list_display = ('name', 'sku', 'available_stock', 'selling_price', 'category')
    list_filter = ('category', 'deleted_at')
    search_fields = ('name', 'sku', 'description')
    inlines = (ProductImageInline,)
    fieldsets = (
        (None, {'fields': ('name', 'sku', 'description')}),
        (_('Pricing'), {'fields': ('original_price', 'selling_price')}),
        (_('Inventory'), {'fields': ('stock_quantity', 'reserved_stock')}),
        (_('Classification'), {'fields': ('category',)}),
        (_('Metadata'), {'fields': ('deleted_at', 'created_at', 'updated_at')}),
    )
    readonly_fields = ('available_stock',)

@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'parent')
    search_fields = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}
    list_filter = ('parent',)

@admin.register(ProductReview)
class ProductReviewAdmin(admin.ModelAdmin):
    list_display = ('product', 'customer', 'rating', 'created_at')
    list_filter = ('rating', 'created_at')
    search_fields = ('product__name', 'customer__username')
    readonly_fields = ('created_at', 'updated_at')
# endregion

# region Order Administration
class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    fields = ('product', 'quantity', 'price', 'subtotal')
    readonly_fields = ('subtotal',)
    autocomplete_fields = ('product',)

@admin.register(Order)
class OrderAdmin(SoftDeleteAdmin):
    list_display = ('id', 'customer', 'status', 'total_amount', 'created_at')
    list_filter = ('status', 'deleted_at')
    search_fields = ('customer__username', 'id')
    inlines = (OrderItemInline,)
    fieldsets = (
        (None, {'fields': ('customer', 'status')}),
        (_('Financials'), {'fields': ('total_amount',)}),
        (_('Metadata'), {'fields': ('deleted_at', 'created_at', 'updated_at')}),
    )
    autocomplete_fields = ('customer',)

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('transaction_id', 'order', 'amount', 'status', 'created_at')
    list_filter = ('status', 'payment_method')
    search_fields = ('transaction_id', 'order__id')
    readonly_fields = ('created_at',)
    autocomplete_fields = ('order',)

@admin.register(ProfitAllocation)
class ProfitAllocationAdmin(admin.ModelAdmin):
    list_display = ('team_member', 'order', 'amount', 'allocated_at')
    list_filter = ('allocated_at', 'team_member__teammemberprofile_profile__department')  # Corrected path
    search_fields = ('team_member__username', 'order__id')
    readonly_fields = ('allocated_at',)
    autocomplete_fields = ('team_member', 'order')
# endregion

# region Customer Administration
@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = ('customer', 'street', 'city', 'country', 'is_primary')
    list_filter = ('country', 'is_primary')
    search_fields = ('customer__username', 'street', 'city')
    list_editable = ('is_primary',)

@admin.register(Wishlist)
class WishlistAdmin(admin.ModelAdmin):
    list_display = ('customer', 'product', 'added_at')
    search_fields = ('customer__user__username', 'product__name')
    autocomplete_fields = ('customer', 'product')

@admin.register(ShoppingCart)
class ShoppingCartAdmin(admin.ModelAdmin):
    list_display = ('customer', 'total_items', 'subtotal', 'updated_at')
    search_fields = ('customer__username',)
    readonly_fields = ('total_items', 'subtotal')

@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
    list_display = ('cart', 'product', 'quantity', 'subtotal')
    search_fields = ('cart__customer__username', 'product__name')
    autocomplete_fields = ('cart', 'product')
# endregion