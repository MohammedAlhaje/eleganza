# orders/models.py
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.validators import MinValueValidator
from django.db.models import Sum, F
from django.conf import settings
from eleganza.core.models import BaseModel
from djmoney.models.fields import MoneyField
from djmoney.money import Money
import uuid

class Order(BaseModel):
    class Status(models.TextChoices):
        PENDING = 'pending', _("Pending")
        RESERVED = 'reserved', _("Reserved")
        CONFIRMED = 'confirmed', _("Confirmed")
        COMPLETED = 'completed', _("Completed")
        CANCELLED = 'cancelled', _("Cancelled")

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='orders',
        limit_choices_to={'type': 'CUSTOMER'}
    )
    status = models.CharField(
        _("Order Status"),
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True
    )
    total_amount = MoneyField(
        _("Total Amount"),
        max_digits=14,
        decimal_places=2,
        default_currency=settings.DEFAULT_CURRENCY
    )
    shipping_address = models.ForeignKey(
        'users.Address',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    tracking_number = models.CharField(
        _("Tracking Number"),
        max_length=255,
        blank=True
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at', 'status']),
            models.Index(fields=['customer']),
        ]
        verbose_name = _("Order")
        verbose_name_plural = _("Orders")

    def __str__(self):
        return f"Order #{self.id} - {self.customer.username}"

    @property
    def items(self):
        return self.order_items.select_related('product')

    @property
    def paid_amount(self):
        return self.payments.filter(status='completed').aggregate(
            total=Sum('amount')
        )['total'] or Money(0, settings.DEFAULT_CURRENCY)

    @property
    def remaining_balance(self):
        return self.total_amount - self.paid_amount

class OrderItem(BaseModel):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='order_items'
    )
    product = models.ForeignKey(
        'products.Product',
        on_delete=models.PROTECT
    )
    quantity = models.PositiveIntegerField(
        _("Quantity"),
        validators=[MinValueValidator(1)]
    )
    price = MoneyField(
        _("Unit Price"),
        max_digits=10,
        decimal_places=2
    )

    class Meta:
        verbose_name = _("Order Item")
        verbose_name_plural = _("Order Items")

    def __str__(self):
        return f"{self.quantity}x {self.product.name}"

    @property
    def subtotal(self):
        return self.price * self.quantity

    def clean(self):
        if not self.price:
            self.price = self.product.selling_price
        super().clean()

class ShoppingCart(BaseModel):
    customer = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='cart',
        limit_choices_to={'type': 'CUSTOMER'}
    )
    session_key = models.CharField(
        _("Session Key"),
        max_length=40,
        blank=True
    )

    class Meta:
        verbose_name = _("Shopping Cart")
        verbose_name_plural = _("Shopping Carts")

    @property
    def total_items(self):
        return self.items.count()

    @property
    def subtotal(self):
        return sum(item.subtotal for item in self.items.all())

class CartItem(BaseModel):
    cart = models.ForeignKey(
        ShoppingCart,
        on_delete=models.CASCADE,
        related_name='items'
    )
    product = models.ForeignKey(
        'products.Product',
        on_delete=models.CASCADE
    )
    quantity = models.PositiveIntegerField(
        _("Quantity"),
        default=1,
        validators=[MinValueValidator(1)]
    )

    class Meta:
        unique_together = ('cart', 'product')
        verbose_name = _("Cart Item")
        verbose_name_plural = _("Cart Items")

    @property
    def subtotal(self):
        return self.product.selling_price * self.quantity

    def __str__(self):
        return f"{self.quantity}x {self.product.name}"
