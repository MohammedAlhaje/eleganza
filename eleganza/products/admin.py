from django.contrib import admin
from django import forms
from django.db import transaction
from django.utils.html import format_html
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.contrib.admin import SimpleListFilter

from .models import (
    Product,
    ProductCategory,
    ProductVariant,
    Inventory,
    ProductAttribute,
    ProductOption,
    ProductImage,
    ProductReview
)
from .services import (
    category_services,
    product_services,
    inventory_services
)
from .selectors import inventory_selectors
from django.core.exceptions import ValidationError

# ======================
# Custom Filters
# ======================
class LowStockFilter(SimpleListFilter):
    title = _('stock status')
    parameter_name = 'stock_status'

    def lookups(self, request, model_admin):
        return (
            ('low', _('Low stock')),
            ('out', _('Out of stock')),
            ('ok', _('In stock')),
        )

    def queryset(self, request, queryset):
        if self.value() == 'low':
            return queryset.filter(
                stock_quantity__lte=F('low_stock_threshold'),
                stock_quantity__gt=0
            )
        elif self.value() == 'out':
            return queryset.filter(stock_quantity=0)
        elif self.value() == 'ok':
            return queryset.filter(stock_quantity__gt=F('low_stock_threshold'))
        return queryset

# ======================
# Inlines
# ======================
class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 0
    fields = ('sku', 'display_options', 'price_modifier', 'is_default', 'is_active')
    readonly_fields = ('display_options',)
    show_change_link = True

    def display_options(self, obj):
        return obj.display_options
    display_options.short_description = _("Options")

class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1
    fields = ('image', 'is_primary', 'sort_order', 'caption')
    readonly_fields = ('image_preview',)

    def image_preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" height="50" />', obj.image.url)
        return "-"
    image_preview.short_description = _("Preview")

class InventoryInline(admin.StackedInline):
    model = Inventory
    extra = 0
    fields = ('stock_quantity', 'low_stock_threshold', 'status')
    readonly_fields = ('status',)

# ======================
# Forms
# ======================
class ProductAdminForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = '__all__'
    
    def clean(self):
        cleaned_data = super().clean()
        # Add any additional product-level validation here
        return cleaned_data

# ======================
# ModelAdmins
# ======================
@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    form = ProductAdminForm
    list_display = (
        'name',
        'sku',
        'category',
        'price_display',
        'has_discount',
        'active_status',
        'review_summary'
    )
    list_filter = (
        'category',
        'is_active',
        'is_featured',
        'has_variants'
    )
    search_fields = (
        'name',
        'sku',
        'description'
    )
    list_select_related = ('category',)
    inlines = [ProductVariantInline, ProductImageInline]
    actions = ['activate_products', 'deactivate_products', 'toggle_featured']
    readonly_fields = (
        'final_price',
        'average_rating',
        'review_count'
    )
    fieldsets = (
        (None, {
            'fields': (
                'name',
                'slug',
                'sku',
                'description',
                'category'
            )
        }),
        (_("Pricing"), {
            'fields': (
                'original_price',
                'selling_price',
                'final_price',
                'discount_type',
                'discount_amount',
                'discount_percent'
            )
        }),
        (_("Attributes"), {
            'fields': (
                'has_variants',
                'attributes'
            )
        }),
        (_("Status"), {
            'fields': (
                'is_featured',
                'is_active'
            )
        }),
        (_("Ratings"), {
            'fields': (
                'average_rating',
                'review_count'
            )
        })
    )

    def price_display(self, obj):
        return obj.price
    price_display.short_description = _("Price")

    def active_status(self, obj):
        return _("Active") if obj.is_active else _("Inactive")
    active_status.short_description = _("Status")

    def review_summary(self, obj):
        return f"{obj.average_rating}/5 ({obj.review_count})"
    review_summary.short_description = _("Rating")

    def save_model(self, request, obj, form, change):
        """Handle product save using service layer"""
        try:
            with transaction.atomic():
                if change:
                    product_services.update_product_pricing(obj)
                else:
                    super().save_model(request, obj, form, change)
                    product_services.update_product_pricing(obj)
        except ValidationError as e:
            form.add_error(None, e)

    @admin.action(description=_("Activate selected products"))
    def activate_products(self, request, queryset):
        for product in queryset:
            product_services.toggle_product_activation(product.id, True)
        self.message_user(request, _("Successfully activated products"))

    @admin.action(description=_("Deactivate selected products"))
    def deactivate_products(self, request, queryset):
        for product in queryset:
            product_services.toggle_product_activation(product.id, False)
        self.message_user(request, _("Successfully deactivated products"))

    @admin.action(description=_("Toggle featured status"))
    def toggle_featured(self, request, queryset):
        for product in queryset:
            product.is_featured = not product.is_featured
            product.save()
        self.message_user(request, _("Successfully toggled featured status"))

@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'parent', 'is_active', 'product_count')
    list_filter = ('is_active', ('parent', admin.RelatedOnlyFieldListFilter))
    search_fields = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}  # Auto-generate slug from name
    actions = ['activate_categories', 'deactivate_categories']
    fields = ('name', 'slug', 'parent', 'description', 'featured_image', 'is_active')  # Explicit fields

    def product_count(self, obj):
        return obj.products.count()
    product_count.short_description = _("Products")

    def get_readonly_fields(self, request, obj=None):
        # Make slug readonly when editing existing category
        if obj:  # Editing existing object
            return ('slug',)
        return ()  # Not readonly when creating new

    def save_model(self, request, obj, form, change):
        """
        Handle both creation and updates through the service layer
        """
        try:
            if change:
                # For updates, remove slug from cleaned_data as it's readonly
                update_data = form.cleaned_data.copy()
                update_data.pop('slug', None)
                
                updated_category = category_services.update_category(
                    category_id=obj.id,
                    update_data=update_data
                )
                form.instance = updated_category
            else:
                # For new categories, let the service handle creation
                new_category = category_services.create_category(
                    name=form.cleaned_data['name'],
                    parent_id=form.cleaned_data['parent'].id if form.cleaned_data['parent'] else None,
                    is_active=form.cleaned_data['is_active'],
                    description=form.cleaned_data['description'],
                    featured_image=form.cleaned_data['featured_image']
                )
                form.instance = new_category
        except ValidationError as e:
            form.add_error(None, e)
            raise

    @admin.action(description=_("Activate selected categories"))
    def activate_categories(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, _("Successfully activated %d categories") % updated)

    @admin.action(description=_("Deactivate selected categories"))
    def deactivate_categories(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, _("Successfully deactivated %d categories") % updated)   

        
@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = (
        'full_sku',
        'product_link',
        'final_price',
        'stock_status',
        'is_active'
    )
    list_filter = ('is_active', 'is_default')
    search_fields = (
        'sku',
        'product__name',
        'product__sku'
    )
    list_select_related = ('product',)
    inlines = [InventoryInline]
    raw_id_fields = ('product',)

    def product_link(self, obj):
        url = reverse('admin:products_product_change', args=[obj.product.id])
        return format_html('<a href="{}">{}</a>', url, obj.product.name)
    product_link.short_description = _("Product")

    def stock_status(self, obj):
        if hasattr(obj, 'inventory'):
            return obj.inventory.status
        return _("No inventory")
    stock_status.short_description = _("Stock Status")

@admin.register(Inventory)
class InventoryAdmin(admin.ModelAdmin):
    list_display = (
        'variant',
        'stock_quantity',
        'low_stock_threshold',
        'status',
        'last_restock'
    )
    list_filter = (LowStockFilter,)
    search_fields = (
        'variant__sku',
        'variant__product__name'
    )
    readonly_fields = ('status', 'is_low_stock')
    actions = ['restock_inventory']

    def status(self, obj):
        """Human-readable stock status"""
        if obj.stock_quantity == 0:
            return "Out of Stock"
        elif obj.stock_quantity <= obj.low_stock_threshold:
            return "Low Stock"
        return "In Stock"
    status.short_description = _("Status")

    @admin.action(description=_("Restock selected inventory"))
    def restock_inventory(self, request, queryset):
        for inventory in queryset:
            inventory_services.restock_inventory(
                inventory.variant_id,
                quantity=inventory.low_stock_threshold * 2
            )
        self.message_user(request, _("Successfully restocked inventory"))

@admin.register(ProductAttribute)
class ProductAttributeAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'code',
        'is_required',
        'active_options_count'
    )
    search_fields = ('name', 'code')
    list_filter = ('is_required',)

@admin.register(ProductOption)
class ProductOptionAdmin(admin.ModelAdmin):
    list_display = (
        'attribute',
        'value',
        'sort_order',
        'is_active',
        'variants_count'
    )
    list_filter = (
        'attribute',
        'is_active'
    )
    search_fields = ('value',)
    list_select_related = ('attribute',)

@admin.register(ProductImage)
class ProductImageAdmin(admin.ModelAdmin):
    list_display = (
        'image_preview',
        'target_name',
        'is_primary',
        'sort_order'
    )
    list_filter = ('is_primary',)
    search_fields = (
        'product__name',
        'variant__product__name'
    )
    readonly_fields = ('image_preview',)

    def image_preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" height="50" />', obj.image.url)
        return "-"
    image_preview.short_description = _("Preview")

@admin.register(ProductReview)
class ProductReviewAdmin(admin.ModelAdmin):
    list_display = (
        'product',
        'user',
        'stars',
        'is_approved',
        'created_at'
    )
    list_filter = (
        'is_approved',
        'rating'
    )
    search_fields = (
        'product__name',
        'user__email',
        'title'
    )
    list_select_related = ('product', 'user')
    actions = ['approve_reviews', 'disapprove_reviews']

    def stars(self, obj):
        return "★" * obj.rating + "☆" * (5 - obj.rating)
    stars.short_description = _("Rating")

    @admin.action(description=_("Approve selected reviews"))
    def approve_reviews(self, request, queryset):
        queryset.update(is_approved=True)
        self.message_user(request, _("Successfully approved reviews"))

    @admin.action(description=_("Disapprove selected reviews"))
    def disapprove_reviews(self, request, queryset):
        queryset.update(is_approved=False)
        self.message_user(request, _("Successfully disapproved reviews"))