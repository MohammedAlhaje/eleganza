# admin.py
from django import forms
from django.contrib import admin
from django.contrib.admin import SimpleListFilter
from django.urls import reverse
from django.utils.html import format_html
from django.db import transaction
import nested_admin
from .models import (
    Product, ProductCategory, ProductAttribute, ProductOption,
    ProductVariant, Inventory, ProductImage,ProductReview
)

# --------------------------
# Custom Filters
# --------------------------
class ProductFilter(SimpleListFilter):
    title = 'Product'
    parameter_name = 'product'
    
    def lookups(self, request, model_admin):
        return [(p.id, p.name) for p in Product.objects.all()]
    
    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(variant__product__id=self.value())
        return queryset

# --------------------------
# Nested Inlines
# --------------------------


class VariantImageInline(nested_admin.NestedTabularInline):
    model = ProductImage
    extra = 0
    fields = ('image', 'is_primary', 'sort_order', 'caption')
    verbose_name = "Variant Image"

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "variant" and hasattr(request, '_product_'):
            kwargs["queryset"] = ProductVariant.objects.filter(
                product=request._product_
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

class ProductImageInline(nested_admin.NestedTabularInline):
    model = ProductImage
    extra = 0
    fields = ('image', 'is_primary', 'sort_order', 'caption')
    verbose_name = "Product Image"

class InventoryInline(nested_admin.NestedStackedInline):
    model = Inventory
    fields = ('stock_quantity', 'low_stock_threshold', 'last_restock')
    readonly_fields = ('last_restock',)

# --------------------------
# Variant System
# --------------------------
class ProductVariantFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        product = self.instance
        
        if not product or not product.pk:
            return

        try:
            product.refresh_from_db()
        except Product.DoesNotExist:
            return

        required_attrs = product.attributes.filter(is_required=True)
        
        for form in self.forms:
            if form.cleaned_data.get('DELETE', False):
                continue

            selected_options = form.cleaned_data.get('options', [])
            
            # Duplicate attribute check
            attributes_seen = set()
            duplicates = []
            for option in selected_options:
                attr_id = option.attribute.id
                if attr_id in attributes_seen:
                    duplicates.append(option.attribute.name)
                attributes_seen.add(attr_id)
            
            if duplicates:
                form.add_error('options', f"Duplicate attributes: {', '.join(set(duplicates))}")

            # Required attributes check
            missing = required_attrs.exclude(id__in=attributes_seen)
            if missing.exists():
                missing_names = missing.values_list('name', flat=True)
                form.add_error('options', f"Missing required: {', '.join(missing_names)}")

class ProductVariantInline(nested_admin.NestedStackedInline):
    model = ProductVariant
    formset = ProductVariantFormSet
    fields = ('sku', 'options', 'price_modifier', 'is_default', 'is_active')
    filter_horizontal = ('options',)
    extra = 0
    inlines = [InventoryInline, VariantImageInline]
    
    def get_formset(self, request, obj=None, **kwargs):
        if obj:
            request._product_ = obj
        return super().get_formset(request, obj, **kwargs)

# --------------------------
# Product Admin
# --------------------------
@admin.register(Product)
class ProductAdmin(nested_admin.NestedModelAdmin):
    list_display = ('name', 'sku', 'category', 'is_active', 'stock_summary')
    filter_horizontal = ('attributes',)
    prepopulated_fields = {'slug': ('name',)}
    inlines = [ProductVariantInline, ProductImageInline]
    search_fields = ('name', 'sku')
    list_filter = ('category', 'is_active')
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'slug', 'sku', 'category', 'description')
        }),
        ('Pricing', {
            'fields': (
                'original_price',
                'selling_price',
                'discount_type',
                'discount_amount',
                'discount_percent'
            )
        }),
        ('Variants', {
            'fields': ('has_variants', 'attributes')
        }),
        ('Status', {
            'fields': ('is_featured', 'is_active')
        }),
    )

    def stock_summary(self, obj):
        return format_html(
            '<a class="button" href="{}?product={}">Stock Report</a>',
            reverse('admin:products_inventory_changelist'),
            obj.id
        )
    stock_summary.short_description = "Inventory"

# --------------------------
# Inventory Admin
# --------------------------
@admin.register(Inventory)
class InventoryAdmin(nested_admin.NestedModelAdmin):
    list_display = ('product_name', 'variant_name', 'stock_quantity', 
                     'needs_restock')
    list_filter = (ProductFilter, 'variant__product__category')
    search_fields = ('variant__product__name', 'variant__sku')

    def product_name(self, obj):
        return obj.variant.product.name
    product_name.short_description = "Product"
    product_name.admin_order_field = 'variant__product__name'

    def variant_name(self, obj):
        return obj.variant.get_variant_name()
    variant_name.short_description = "Variant"

# --------------------------
# Variant Admin
# --------------------------
@admin.register(ProductVariant)
class ProductVariantAdmin(nested_admin.NestedModelAdmin):
    list_display = ('sku', 'product', 'get_variant_name', 'price', 'stock_status')
    list_filter = ('product', 'is_active')
    search_fields = ('sku', 'product__name')
    filter_horizontal = ('options',)
    inlines = [InventoryInline, VariantImageInline]

    def get_variant_name(self, obj):
        return obj.get_variant_name()
    get_variant_name.short_description = "Variant"

    def stock_status(self, obj):
        return obj.inventory.stock_status() if hasattr(obj, 'inventory') else 'N/A'
    stock_status.short_description = "Stock Status"

    def price(self, obj):
        return obj.final_price
    price.short_description = "Price"

# --------------------------
# Supporting Admins
# --------------------------
@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'parent', 'is_active')
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name',)

@admin.register(ProductAttribute)
class ProductAttributeAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'is_required')
    search_fields = ('name', 'code')
    prepopulated_fields = {'code': ('name',)}

@admin.register(ProductOption)
class ProductOptionAdmin(admin.ModelAdmin):
    list_display = ('attribute', 'value', 'sort_order', 'is_active')
    list_filter = ('attribute', 'is_active')
    search_fields = ('value',)
    ordering = ('attribute__name', 'sort_order')

@admin.register(ProductReview)
class ProductReviewAdmin(admin.ModelAdmin):
    list_display = ('product', 'user', 'rating', 'is_approved')
    list_filter = ('rating', 'is_approved')
    search_fields = ('product__name', 'user__email')
