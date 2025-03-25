from django.contrib import admin
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.urls import reverse
from django.utils.html import format_html
from django.db.models import Prefetch
from django.contrib.auth import get_user_model
from .models import Order, OrderItem, Cart, CartItem

User = get_user_model()

class OrderItemInline(admin.TabularInline):
    """Inline admin for order items with inventory validation"""
    model = OrderItem
    extra = 0
    min_num = 1
    classes = ('collapse',)
    raw_id_fields = ('product',)
    readonly_fields = ('subtotal_display',)
    fields = ('product', 'quantity', 'price', 'subtotal_display')
    verbose_name = _("Order Line Item")

    def subtotal_display(self, instance):
        return f"{instance.subtotal.currency} {instance.subtotal.amount}"
    subtotal_display.short_description = _("Subtotal")

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    """Admin interface for order management with financial controls"""
    list_display = (
        'id',
        'customer_email',
        'status_badge',
        'total_price',
        'payment_status',
        'created_at'
    )
    list_filter = (
        'status',
        ('customer', admin.RelatedOnlyFieldListFilter),
        'created_at',
    )
    search_fields = (
        'tracking_number',
        'customer__email',
        'id'
    )
    raw_id_fields = ('customer', 'shipping_address', 'billing_address')
    readonly_fields = (
        'payment_status',
        'paid_amount',
        'timeline',
        'currency',
        'created_at',
        'updated_at'
    )
    fieldsets = (
        (None, {
            'fields': (
                'status',
                'customer',
                'currency',
                ('total_price', 'tax_amount', 'shipping_cost'),
                'paid_amount',
                'payment_status',
            )
        }),
        (_("Fulfillment Details"), {
            'fields': (
                'shipping_address',
                'billing_address',
                'tracking_number'
            ),
            'classes': ('collapse',)
        }),
        (_("Audit Information"), {
            'fields': (
                'created_at',
                'updated_at',
                'timeline'
            ),
            'classes': ('collapse',)
        }),
    )
    inlines = (OrderItemInline,)
    actions = ['mark_as_completed', 'cancel_orders']
    ordering = ('-created_at',)
    list_select_related = ('customer',)

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related(
            Prefetch('items', queryset=OrderItem.objects.select_related('product')))
    
    def customer_email(self, obj):
        return obj.customer.email
    customer_email.short_description = _("Customer Email")

    def status_badge(self, obj):
        status_colors = {
            'draft': '#6c757d',
            'pending': '#0d6efd',
            'reserved': '#fd7e14',
            'confirmed': '#198754',
            'completed': '#6f42c1',
            'cancelled': '#dc3545'
        }
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; border-radius: 10px">{}</span>',
            status_colors.get(obj.status, 'gray'),
            obj.get_status_display()
        )
    status_badge.short_description = _("Status")

    def timeline(self, obj):
        return format_html(
            '<div style="line-height: 1.8">'
            '<strong>Created:</strong> {}<br>'
            '<strong>Last Updated:</strong> {}<br>'
            '<strong>Age:</strong> {} days'
            '</div>',
            obj.created_at.strftime("%Y-%m-%d %H:%M"),
            obj.updated_at.strftime("%Y-%m-%d %H:%M"),
            (timezone.now() - obj.created_at).days
        )
    timeline.short_description = _("Timeline")

    @admin.action(description=_("Mark shipped orders as completed"))
    def mark_as_completed(self, request, queryset):
        updated = queryset.filter(status=Order.Status.SHIPPED)\
                         .update(status=Order.Status.COMPLETED)
        self.message_user(request, _("Successfully completed %d orders") % updated)

    @admin.action(description=_("Cancel selected orders"))
    def cancel_orders(self, request, queryset):
        for order in queryset.exclude(status__in=[Order.Status.COMPLETED, Order.Status.REFUNDED]):
            order.release_stock()
        self.message_user(request, _("Cancelled %d orders") % queryset.count())

    def save_model(self, request, obj, form, change):
        if change:
            original = Order.objects.get(pk=obj.pk)
            if original.status != obj.status:
                obj.full_clean()  # Validate status transition
        super().save_model(request, obj, form, change)

class CartItemInline(admin.TabularInline):
    """Inline admin for cart items with stock validation"""
    model = CartItem
    extra = 0
    raw_id_fields = ('product',)
    readonly_fields = ('subtotal_display',)
    fields = ('product', 'quantity', 'subtotal_display')
    verbose_name = _("Cart Item")

    def subtotal_display(self, instance):
        return f"{instance.subtotal.currency} {instance.subtotal.amount}"
    subtotal_display.short_description = _("Subtotal")

@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    """Admin interface for shopping cart management"""
    list_display = ('id', 'user_email', 'item_count', 'created_at')
    search_fields = ('user__email', 'session_key', 'id')
    raw_id_fields = ('user',)
    inlines = (CartItemInline,)
    readonly_fields = ('created_at', 'updated_at')
    list_select_related = ('user',)

    def user_email(self, obj):
        return obj.user.email if obj.user else _("Anonymous")
    user_email.short_description = _("User Email")

    def item_count(self, obj):
        return obj.items.count()
    item_count.short_description = _("Items")

@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
    """Admin interface for cart item management"""
    list_display = ('product', 'cart_owner', 'quantity', 'subtotal')
    raw_id_fields = ('product', 'cart')
    readonly_fields = ('subtotal',)
    list_select_related = ('product', 'cart__user')

    def cart_owner(self, obj):
        return obj.cart.user.email if obj.cart.user else _("Anonymous")
    cart_owner.short_description = _("Cart Owner")

    def subtotal(self, obj):
        return f"{obj.subtotal.currency} {obj.subtotal.amount}"
    subtotal.short_description = _("Subtotal")