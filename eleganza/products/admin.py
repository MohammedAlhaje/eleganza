from django.contrib import admin
from django import forms
from django.db import transaction
from .models import Product, ProductCategory, ProductVariant, Inventory
from .services import category_services, product_services, inventory_services
from .selectors import inventory_selectors
from django.core.exceptions import ValidationError

# ------------------
# Minimal Product Admin
# ------------------
class ProductAdminForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = '__all__'

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    form = ProductAdminForm
    list_display = ('name', 'sku', 'price', 'is_active')
    actions = ['activate_products', 'deactivate_products']

    def save_model(self, request, obj, form, change):
        """Use service for create/update"""
        try:
            if change:  # Existing product
                product_services.update_product_pricing(obj)
            else:       # New product
                super().save_model(request, obj, form, change)
                product_services.update_product_pricing(obj)
        except ValidationError as e:
            form.add_error(None, e)

    @admin.action(description="Activate Products")
    def activate_products(self, request, queryset):
        for product in queryset:
            product_services.toggle_product_activation(product.id, True)

    @admin.action(description="Deactivate Products")
    def deactivate_products(self, request, queryset):
        for product in queryset:
            product_services.toggle_product_activation(product.id, False)

# ------------------
# Simple Category Admin
# ------------------
@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'parent', 'is_active')
    
    def save_model(self, request, obj, form, change):
        """Use category service for create/update"""
        try:
            if change:
                category_services.update_category(obj.id, form.cleaned_data)
            else:
                category_services.create_category(
                    name=obj.name,
                    parent_id=obj.parent.id if obj.parent else None,
                    is_active=obj.is_active
                )
        except ValidationError as e:
            form.add_error(None, e)

# ------------------
# Inventory Admin with Selectors
# ------------------
@admin.register(Inventory)
class InventoryAdmin(admin.ModelAdmin):
    list_display = ('variant', 'stock_status')
    
    def stock_status(self, obj):
        """Use selector for inventory data"""
        status = inventory_selectors.get_inventory_status(obj.variant_id)
        return f"{status['current_stock']} (Threshold: {status['low_stock_threshold']})"