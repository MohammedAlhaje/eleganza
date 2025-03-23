# payment/models.py
import uuid
from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django.core.validators import MinValueValidator
from eleganza.core.models import BaseModel
from djmoney.models.fields import MoneyField


class PaymentMethod(BaseModel):
    """Stores customer payment methods (credit cards, PayPal, etc.)"""
    class PaymentType(models.TextChoices):
        CREDIT_CARD = 'credit_card', _('Credit Card')
        DEBIT_CARD = 'debit_card', _('Debit Card')
        PAYPAL = 'paypal', _('PayPal')
        BANK_TRANSFER = 'bank_transfer', _('Bank Transfer')
        CRYPTO = 'crypto', _('Cryptocurrency')
        WALLET = 'wallet', _('Account Wallet')

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='payment_methods',
        limit_choices_to={'type': 'CUSTOMER'}
    )
    payment_type = models.CharField(
        _("Payment Type"),
        max_length=20,
        choices=PaymentType.choices
    )
    is_default = models.BooleanField(
        _("Default Method"),
        default=False
    )
    metadata = models.JSONField(
        _("Payment Metadata"),
        default=dict,
        help_text=_("Encrypted payment details")
    )
    last_four = models.CharField(
        _("Last Four Digits"),
        max_length=4,
        blank=True
    )
    expiry_date = models.DateField(
        _("Expiration Date"),
        null=True,
        blank=True
    )

    class Meta:
        verbose_name = _("Payment Method")
        verbose_name_plural = _("Payment Methods")
        ordering = ['-is_default', '-created_at']

    def __str__(self):
        return f"{self.get_payment_type_display()} ({self.customer})"

class Payment(BaseModel):
    """Main payment transaction model"""
    class Status(models.TextChoices):
        PENDING = 'pending', _('Pending')
        COMPLETED = 'completed', _('Completed')
        FAILED = 'failed', _('Failed')
        REFUNDED = 'refunded', _('Refunded')
        PARTIALLY_REFUNDED = 'partially_refunded', _('Partially Refunded')

    order = models.ForeignKey(
        'orders.Order',
        on_delete=models.PROTECT,
        related_name='payments'
    )
    payment_method = models.ForeignKey(
        PaymentMethod,
        on_delete=models.PROTECT,
        related_name='transactions'
    )
    amount = MoneyField(
        _("Amount"),
        max_digits=14,
        decimal_places=2,
        default_currency=settings.DEFAULT_CURRENCY
    )
    status = models.CharField(
        _("Status"),
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )
    transaction_id = models.UUIDField(
        _("Transaction ID"),
        default=uuid.uuid4,
        editable=False,
        unique=True
    )
    idempotency_key = models.CharField(
        _("Idempotency Key"),
        max_length=255,
        unique=True,
        blank=True
    )
    failure_reason = models.TextField(
        _("Failure Reason"),
        blank=True
    )
    gateway_response = models.JSONField(
        _("Gateway Response"),
        default=dict,
        blank=True
    )

    class Meta:
        verbose_name = _("Payment")
        verbose_name_plural = _("Payments")
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['transaction_id']),
        ]

    def __str__(self):
        return f"Payment {self.transaction_id} ({self.amount})"

class Refund(BaseModel):
    """Track payment refunds"""
    payment = models.ForeignKey(
        Payment,
        on_delete=models.PROTECT,
        related_name='refunds'
    )
    amount = MoneyField(
        _("Refund Amount"),
        max_digits=14,
        decimal_places=2,
        default_currency=settings.DEFAULT_CURRENCY
    )
    reason = models.TextField(
        _("Refund Reason"),
        blank=True
    )
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='processed_refunds'
    )

    class Meta:
        verbose_name = _("Refund")
        verbose_name_plural = _("Refunds")

    def __str__(self):
        return f"Refund for {self.payment}"

class Subscription(BaseModel):
    """Recurring payment subscriptions"""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='subscriptions'
    )
    payment_method = models.ForeignKey(
        PaymentMethod,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    amount = MoneyField(
        _("Recurring Amount"),
        max_digits=14,
        decimal_places=2,
        default_currency=settings.DEFAULT_CURRENCY
    )
    interval = models.CharField(
        _("Billing Interval"),
        max_length=20,
        choices=[
            ('daily', _('Daily')),
            ('weekly', _('Weekly')),
            ('monthly', _('Monthly')),
            ('yearly', _('Yearly'))
        ],
        default='monthly'
    )
    next_billing_date = models.DateTimeField(
        _("Next Billing Date")
    )
    is_active = models.BooleanField(
        _("Active"),
        default=True
    )

    class Meta:
        verbose_name = _("Subscription")
        verbose_name_plural = _("Subscriptions")

    def __str__(self):
        return f"{self.user}'s {self.interval} subscription"