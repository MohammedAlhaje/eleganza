import logging
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.core.validators import MinValueValidator, MaxValueValidator
from django.conf import settings
from django.db.models import Sum, F, Q, CheckConstraint
from django.urls import reverse
from django.core.exceptions import ValidationError
from eleganza.core.models import BaseModel, AuditLog
from eleganza.users.models import User
from djmoney.models.fields import MoneyField
from djmoney.money import Money
from djmoney.models.fields import CurrencyField
from djmoney.models.validators import MinMoneyValidator

logger = logging.getLogger(__name__)

class OrderManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().select_related(
            'customer', 'shipping_address', 'billing_address'
        ).prefetch_related('items')

    def abandoned(self):
        return self.filter(
            status='pending',
            created_at__lt=timezone.now() - timezone.timedelta(hours=24))
    
    def needs_fulfillment(self):
        return self.filter(status='confirmed')

class OrderError(Exception):
    """Base exception for order-related errors"""

class InventoryShortageError(OrderError):
    """Raised when insufficient stock is available"""

class InvalidStatusTransitionError(OrderError):
    """Raised when invalid status transition is attempted"""

class Order(BaseModel):
    """
    Represents a customer order with lifecycle management.
    Integrates with payments, inventory, and auditing systems.
    """
    class Status(models.TextChoices):
        DRAFT = 'draft', _("Draft")
        PENDING = 'pending', _("Pending")
        RESERVED = 'reserved', _("Reserved (Stock Reserved)")
        CONFIRMED = 'confirmed', _("Confirmed (Payment Received)")
        FULFILLMENT = 'fulfillment', _("In Fulfillment")
        SHIPPED = 'shipped', _("Shipped")
        COMPLETED = 'completed', _("Completed")
        CANCELLED = 'cancelled', _("Cancelled")
        REFUNDED = 'refunded', _("Refunded")

    STATUS_TRANSITIONS = {
        Status.DRAFT: [Status.PENDING, Status.CANCELLED],
        Status.PENDING: [Status.RESERVED, Status.CANCELLED],
        Status.RESERVED: [Status.CONFIRMED, Status.CANCELLED],
        Status.CONFIRMED: [Status.FULFILLMENT, Status.REFUNDED],
        Status.FULFILLMENT: [Status.SHIPPED, Status.CANCELLED],
        Status.SHIPPED: [Status.COMPLETED],
        Status.COMPLETED: [],
        Status.CANCELLED: [Status.DRAFT],
        Status.REFUNDED: []
    }

    status = models.CharField(
        _("Order Status"),
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='orders',
        limit_choices_to={'type': 'CUSTOMER'},
        verbose_name=_("Customer")
    )
    total_price = MoneyField(
        _("Total Price"),
        max_digits=14,
        decimal_places=2,
        default_currency=settings.DEFAULT_CURRENCY,
        currency_field_name='currency',  # Correct parameter name
        validators=[
        MinMoneyValidator(0)
        ],
        help_text=_("Calculated total including taxes and shipping")
    )
    tax_amount = MoneyField(
        _("Tax Amount"),
        max_digits=10,
        decimal_places=2,
        default_currency=settings.DEFAULT_CURRENCY,
        currency_field_name='currency',
        default=0
    )
    shipping_cost = MoneyField(
        _("Shipping Cost"),
        max_digits=10,
        decimal_places=2,
        default_currency=settings.DEFAULT_CURRENCY,
        currency_field_name='currency',
        default=0
    )
    shipping_address = models.ForeignKey(
        'users.Address',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        limit_choices_to={'user__type': User.Types.CUSTOMER},
        verbose_name=_("Shipping Address")
    )
    billing_address = models.ForeignKey(
        'users.Address',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='billing_orders',
        verbose_name=_("Billing Address")
    )
    tracking_number = models.CharField(
        _("Tracking Number"),
        max_length=255,
        blank=True,
        db_index=True
    )
    currency = CurrencyField(
        _("Currency"),
        max_length=3,
        choices=settings.CURRENCY_CHOICES,
        default=settings.DEFAULT_CURRENCY,
        editable=False
    )

    objects = OrderManager()

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at', 'status'])
        ]
        verbose_name = _("Order")
        verbose_name_plural = _("Orders")

    def __str__(self):
        return f"Order #{self.id} ({self.get_status_display()})"

    def get_absolute_url(self):
        return reverse('orders:detail', kwargs={'pk': self.pk})

    def calculate_total(self):
        """
        Calculates order total including items, taxes, and shipping.
        Atomic calculation to prevent race conditions.
        """
        with transaction.atomic():
            items_total = self.items.aggregate(
                total=Sum(F('price_amount') * F('quantity'))
            ).get('total') or 0
            
            return Money(
                items_total + 
                self.tax_amount.amount + 
                self.shipping_cost.amount,
                self.currency
            )

    def clean(self):
        # Validate currency consistency
        currencies = {
            self.total_price.currency,
            self.tax_amount.currency,
            self.shipping_cost.currency
        }
        if len(currencies) > 1 or self.currency not in currencies:
            raise ValidationError(_("All monetary values must use the same currency"))
        
        # Validate status transitions
        if self.pk:
            original = Order.objects.get(pk=self.pk)
            if original.status != self.status:
                allowed = self.STATUS_TRANSITIONS.get(original.status, [])
                if self.status not in allowed:
                    raise InvalidStatusTransitionError(
                        f"Invalid transition from {original.status} to {self.status}"
                    )

        super().clean()

    def reserve_stock(self):
        """Reserve inventory for all order items atomically"""
        if self.status not in [Order.Status.DRAFT, Order.Status.PENDING]:
            return

        with transaction.atomic():
            # Lock inventory rows
            items = self.items.select_related('product__inventory').select_for_update()
            
            for item in items:
                inventory = item.product.inventory
                if inventory.available_stock < item.quantity:
                    raise InventoryShortageError(
                        f"Insufficient stock for {item.product.sku}"
                    )
                inventory.stock_quantity -= item.quantity
                inventory.save()
                
            self.status = Order.Status.RESERVED
            self.save()

    def release_stock(self):
        """Release reserved inventory atomically"""
        if self.status != Order.Status.RESERVED:
            return

        with transaction.atomic():
            # Lock inventory rows
            items = self.items.select_related('product__inventory').select_for_update()
            
            for item in items:
                inventory = item.product.inventory
                inventory.stock_quantity += item.quantity
                inventory.save()
                
            self.status = Order.Status.CANCELLED
            self.save()

    @property
    def paid_amount(self):
        return self.payments.filter(status='completed').aggregate(
            total=Sum('amount_amount')
        ).get('total') or Money(0, self.currency)

    @property
    def payment_status(self):
        if self.paid_amount >= self.total_price:
            return _("Paid in full")
        return _("Pending payment")

class OrderItem(BaseModel):
    """
    Individual line items within an order with price snapshot.
    Maintains historical pricing data and integrates with inventory.
    """
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name=_("Parent Order")
    )
    product = models.ForeignKey(
        'products.Product',
        on_delete=models.PROTECT,
        limit_choices_to=Q(is_active=True) & Q(inventory__available_stock__gt=0),
        verbose_name=_("Product")
    )
    quantity = models.PositiveIntegerField(
        _("Quantity"),
        validators=[
            MinValueValidator(1),
            MaxValueValidator(1000)
        ]
    )
    price = MoneyField(
        _("Unit Price"),
        max_digits=10,
        decimal_places=2,
        help_text=_("Snapshot of price at time of order")
    )

    class Meta:
        verbose_name = _("Order Item")
        verbose_name_plural = _("Order Items")
        constraints = [
            CheckConstraint(
                check=Q(quantity__gte=1),
                name="min_order_item_quantity"
            )
        ]

    def __str__(self):
        return f"{self.quantity}x {self.product.name}"

    @property
    def subtotal(self):
        return self.price * self.quantity

    def clean(self):
        if not self.price:
            self.price = self.product.selling_price
            
        if self.product.inventory.available_stock < self.quantity:
            raise ValidationError(
                _("Insufficient stock available for %(product)s") % {
                    'product': self.product.name
                }
            )
        super().clean()

class Cart(BaseModel):
    """
    Shopping cart supporting both authenticated users and anonymous sessions.
    Integrates with product inventory and currency systems.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        limit_choices_to={'type': 'CUSTOMER'},
        verbose_name=_("User")
    )
    session_key = models.CharField(
        _("Session Key"),
        max_length=40,
        blank=True,
        db_index=True
    )
    currency = models.CharField(
        _("Currency"),
        max_length=3,
        choices=settings.CURRENCY_CHOICES,
        default=settings.DEFAULT_CURRENCY
    )

    class Meta:
        verbose_name = _("Shopping Cart")
        verbose_name_plural = _("Shopping Carts")
        indexes = [
            models.Index(fields=['user', 'session_key']),
        ]

    def __str__(self):
        identifier = self.user.username if self.user else self.session_key
        return f"Cart for {identifier}"

    @property
    def total(self):
        return sum(item.subtotal for item in self.items.all())

    def merge(self, session_cart):
        """Merge anonymous session cart into user cart"""
        with transaction.atomic():
            for item in session_cart.items.all():
                existing = self.items.filter(product=item.product).first()
                if existing:
                    existing.quantity += item.quantity
                    existing.save()
                else:
                    item.cart = self
                    item.save()
            session_cart.delete()

class CartItem(BaseModel):
    """
    Individual cart items with real-time inventory validation.
    Enforces maximum quantities based on available stock.
    """
    cart = models.ForeignKey(
        Cart,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name=_("Parent Cart")
    )
    product = models.ForeignKey(
        'products.Product',
        on_delete=models.CASCADE,
        limit_choices_to=Q(is_active=True) & Q(inventory__stock_quantity__gt=0),
        verbose_name=_("Product")
    )
    quantity = models.PositiveIntegerField(
        _("Quantity"),
        default=1,
        validators=[
            MinValueValidator(1),
            MaxValueValidator(50)
        ]
    )

    class Meta:
        verbose_name = _("Cart Item")
        verbose_name_plural = _("Cart Items")
        constraints = [
            models.UniqueConstraint(
                fields=['cart', 'product'],
                name='unique_product_per_cart'
            )
        ]

    def __str__(self):
        return f"{self.quantity}x {self.product.name}"

    @property
    def subtotal(self):
        return self.product.selling_price * self.quantity

    def clean(self):
        max_quantity = self.product.inventory.available_stock
        if self.quantity > max_quantity:
            raise ValidationError(
                _("Only %(max)s available in stock") % {'max': max_quantity}
            )
        super().clean()