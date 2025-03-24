# payments/admin.py
from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.db.models import Sum
from .models import Wallet, PaymentMethod, Transaction, Payment
from .models import PaymentMethodType, TransactionType

class TransactionInline(admin.TabularInline):
    model = Transaction
    extra = 0
    readonly_fields = ('reference', 'transaction_type', 'amount', 'payment_method_link', 'created_at')
    fields = ('created_at', 'transaction_type', 'amount', 'reference', 'payment_method_link')
    
    def payment_method_link(self, obj):
        url = reverse('admin:payments_paymentmethod_change', args=[obj.payment_method.id])
        return format_html('<a href="{}">{}</a>', url, obj.payment_method)
    payment_method_link.short_description = 'Payment Method'

@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ('user_email', 'balance_with_currency', 'created_date')
    list_filter = ('currency',)
    search_fields = ('user__email', 'user__uuid')
    readonly_fields = ('user', 'currency')
    
    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = 'User Email'
    user_email.admin_order_field = 'user__email'
    
    def balance_with_currency(self, obj):
        return f"{obj.currency} {obj.balance}"
    balance_with_currency.short_description = 'Balance'
    
    def created_date(self, obj):
        # If using django's auto-created timestamp:
        return obj.user.date_joined
        # If you have a created_at field in Wallet model:
        # return obj.created_at
    created_date.short_description = 'Created Date'

@admin.register(PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    list_display = ('user_email', 'method_type', 'wallet_balance', 'cash_identifier', 'cash_handler')
    list_filter = ('method_type',)
    search_fields = ('user__email', 'cash_identifier')
    readonly_fields = ('cash_identifier',)
    raw_id_fields = ('user', 'wallet', 'cash_handled_by')
    
    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = 'User Email'
    user_email.admin_order_field = 'user__email'
    
    def wallet_balance(self, obj):
        if obj.method_type == PaymentMethodType.WALLET and obj.wallet:
            return f"{obj.wallet.currency} {obj.wallet.balance}"
        return '-'
    wallet_balance.short_description = 'Wallet Balance'
    
    def cash_handler(self, obj):
        if obj.cash_handled_by:
            return obj.cash_handled_by.email
        return '-'
    cash_handler.short_description = 'Cash Handler'

@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'transaction_type', 'amount_with_currency', 'payment_method_link', 'order_link')
    list_filter = ('transaction_type', 'created_at')
    search_fields = ('reference', 'order__id')
    readonly_fields = ('reference', 'created_at')
    raw_id_fields = ('payment_method', 'order', 'related_transaction')
    
    def amount_with_currency(self, obj):
        return str(obj.amount)
    amount_with_currency.short_description = 'Amount'
    
    def payment_method_link(self, obj):
        url = reverse('admin:payments_paymentmethod_change', args=[obj.payment_method.id])
        return format_html('<a href="{}">{}</a>', url, obj.payment_method)
    payment_method_link.short_description = 'Payment Method'
    
    def order_link(self, obj):
        if obj.order:
            url = reverse('admin:orders_order_change', args=[obj.order.id])
            return format_html('<a href="{}">Order #{}</a>', url, obj.order.id)
        return '-'
    order_link.short_description = 'Order'

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('id', 'order_id', 'method_type', 'amount_with_currency', 'status', 'created_at')
    list_filter = ('status', 'method__method_type')
    search_fields = ('id', 'order__id')
    readonly_fields = ('created_at', 'status')
    raw_id_fields = ('order', 'method')
    actions = ['process_payments', 'refund_payments']
    
    def method_type(self, obj):
        return obj.method.get_method_type_display()
    method_type.short_description = 'Payment Method Type'
    
    def amount_with_currency(self, obj):
        return str(obj.amount)
    amount_with_currency.short_description = 'Amount'
    
    def order_id(self, obj):
        return f"Order #{obj.order.id}"
    order_id.short_description = 'Order'
    
    def process_payments(self, request, queryset):
        for payment in queryset:
            try:
                payment.process()
            except Exception as e:
                self.message_user(request, f"Error processing payment {payment.id}: {str(e)}", level='ERROR')
    process_payments.short_description = "Process selected payments"
    
    def refund_payments(self, request, queryset):
        for payment in queryset:
            if payment.status == 'completed':
                payment.status = 'refunded'
                payment.save()
    refund_payments.short_description = "Mark selected payments as refunded"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'method', 
            'method__wallet', 
            'order'
        )