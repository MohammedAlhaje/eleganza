from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from mptt.admin import DraggableMPTTAdmin
from .models import (
    ProductCategory,
    Product,
    Inventory,
    ProductImage,
    ProductReview
)
@admin.register(ProductCategory)
class ProductCategoryAdmin(DraggableMPTTAdmin):
    mptt_indent_field = "name"
    list_display = ('tree_actions', 'indented_title', 'featured_image_preview', 
                   'product_count', 'is_active')
    list_display_links = ('indented_title',)
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name', 'slug')
    list_filter = ('is_active',)
    readonly_fields = ('featured_image_preview',)
    actions = ['activate_categories', 'deactivate_categories']

    def featured_image_preview(self, obj):
        if obj.featured_image:
            return format_html('<img src="{}" style="max-height: 50px;"/>', obj.featured_image.url)
        return "-"
    featured_image_preview.short_description = _("Image Preview")

    def product_count(self, obj):
        return obj.products.count()
    product_count.short_description = _("Products")

    @admin.action(description=_("Activate selected categories"))
    def activate_categories(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} categories activated")

    @admin.action(description=_("Deactivate selected categories"))
    def deactivate_categories(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} categories deactivated")

class InventoryInline(admin.StackedInline):
    model = Inventory
    fields = ('stock_quantity', 'low_stock_threshold', 'available_stock')
    readonly_fields = ('available_stock',)
    extra = 1

    def available_stock(self, obj):
        return obj.available_stock
    available_stock.short_description = _("Available Stock")

class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1
    readonly_fields = ('image_preview',)
    fields = ('image', 'image_preview', 'caption', 'is_primary', 'sort_order')

    def image_preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" style="max-height: 50px;"/>', obj.image.url)
        return "-"
    image_preview.short_description = _("Preview")

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'sku', 'category', 'price_display', 
                   'discount_percent', 'is_featured', 'review_status')
    list_filter = ('category', 'is_featured', 'created_at')
    search_fields = ('name', 'sku', 'description')
    prepopulated_fields = {'slug': ('name',)}  # This auto-generates the slug
    readonly_fields = ('average_rating', 'review_count', 'discount_percent')
    inlines = [InventoryInline, ProductImageInline]
    actions = ['toggle_featured_status']
    autocomplete_fields = ['category']

    fieldsets = (
        (None, {'fields': ('name', 'slug', 'sku', 'category')}),
        (_("Pricing"), {'fields': ('original_price', 'selling_price')}),
        (_("Content"), {'fields': ('description',)}),
        (_("Status"), {'fields': ('is_featured',)}),
        (_("Ratings"), {'fields': ('average_rating', 'review_count')}),
    )

    def price_display(self, obj):
        return f"{obj.selling_price} (MSRP: {obj.original_price})"
    price_display.short_description = _("Pricing")

    def discount_percent(self, obj):
        return f"{obj.discount_percentage}%"
    discount_percent.short_description = _("Discount")

    def review_status(self, obj):
        return f"{obj.average_rating}/5 ({obj.review_count} reviews)"
    review_status.short_description = _("Rating")

    @admin.action(description=_("Toggle featured status"))
    def toggle_featured_status(self, request, queryset):
        for obj in queryset:
            obj.is_featured = not obj.is_featured
            obj.save()
        self.message_user(request, f"{queryset.count()} products updated")

@admin.register(ProductReview)
class ProductReviewAdmin(admin.ModelAdmin):
    list_display = ('product', 'user', 'rating_stars', 'is_approved', 'created_at')
    list_filter = ('rating', 'is_approved')
    search_fields = ('product__name', 'user__email', 'title')
    list_editable = ('is_approved',)
    actions = ['approve_reviews']

    def rating_stars(self, obj):
        return format_html(
            '<span style="color: #ffd700; font-size: 1.2em;">{}</span>',
            '★' * obj.rating + '☆' * (5 - obj.rating)
        )
    rating_stars.short_description = _("Rating")

    @admin.action(description=_("Approve selected reviews"))
    def approve_reviews(self, request, queryset):
        queryset.update(is_approved=True)
        for review in queryset:
            review.product.update_rating_stats()
        self.message_user(request, f"{queryset.count()} reviews approved")