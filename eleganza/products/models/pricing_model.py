from django.db import models
from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError
from django.db.models import Q, UniqueConstraint, CheckConstraint
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from eleganza.core.models import BaseModel
from ..constants import (
    PricingConstants,
    CurrencyConstants,
)
from .product_model import Product, ProductVariant
from .category_model import ProductCategory

# region Pricing System
class ProductPrice(BaseModel):
    """Temporal pricing system with currency support (supports price history)."""
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='prices',
        null=True,
        blank=True
    )
    variant = models.ForeignKey(
        ProductVariant,
        on_delete=models.CASCADE,
        related_name='prices',
        null=True,
        blank=True
    )
    amount = models.DecimalField(
        _("Amount"),
        max_digits=PricingConstants.PriceLimits.MAX_DIGITS,
        decimal_places=PricingConstants.PriceLimits.DECIMALS,
        validators=[MinValueValidator(PricingConstants.PriceLimits.MIN_VALUE)]
    )
    currency = models.CharField(
        _("Currency"),
        max_length=3,
        default=CurrencyConstants.DEFAULT,
        choices=CurrencyConstants.CHOICES
    )
    valid_from = models.DateTimeField(
        _("Valid From"),
        default=timezone.now
    )
    valid_until = models.DateTimeField(
        _("Valid Until"),
        null=True,
        blank=True
    )

    class Meta:
        verbose_name = _("Product Price")
        verbose_name_plural = _("Product Prices")
        constraints = [
            CheckConstraint(
                check=Q(product__isnull=True) | Q(variant__isnull=True),
                name='price_exclusive_product_or_variant'
            ),
            CheckConstraint(
                check=Q(valid_until__gt=models.F('valid_from')) | Q(valid_until__isnull=True),
                name='valid_price_period'
            )
        ]

    def clean(self):
        if not (self.product or self.variant):
            raise ValidationError(_("Price must be linked to a product or variant"))
        if self.product and self.variant:
            raise ValidationError(_("Cannot link price to both product and variant"))
        if self.valid_until and self.valid_until <= self.valid_from:
            raise ValidationError(_("Valid until must be after valid from"))

    def __str__(self):
        target = self.product or self.variant
        return f"{target.name} - {self.amount} {self.currency}"


class CostPrice(BaseModel):
    """Product cost tracking with vendor relationships"""
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='costs',
        null=True,
        blank=True
    )
    variant = models.ForeignKey(
        ProductVariant,
        on_delete=models.CASCADE,
        related_name='costs',
        null=True,
        blank=True
    )
    amount = models.DecimalField(
        _("Amount"),
        max_digits=PricingConstants.PriceLimits.MAX_DIGITS,
        decimal_places=PricingConstants.PriceLimits.DECIMALS,
        validators=[MinValueValidator(PricingConstants.PriceLimits.MIN_VALUE)]
    )
    vendor = models.ForeignKey(
        'vendors.Vendor',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_("Vendor")
    )
    valid_from = models.DateTimeField(
        _("Valid From"),
        default=timezone.now
    )

    class Meta:
        verbose_name = _("Cost Price")
        verbose_name_plural = _("Cost Prices")
        constraints = [
            CheckConstraint(
                check=Q(product__isnull=True) | Q(variant__isnull=True),
                name='cost_exclusive_product_or_variant'
            )
        ]

    def clean(self):
        if not (self.product or self.variant):
            raise ValidationError(_("Cost must be linked to a product or variant"))
        if self.product and self.variant:
            raise ValidationError(_("Cannot link cost to both product and variant"))

    def __str__(self):
        target = self.product or self.variant
        return f"Cost for {target.name}: {self.amount}"


class Discount(BaseModel):
    """Advanced discount system with multiple applicability rules"""
    DISCOUNT_TYPES = (
        ('percentage', _("Percentage")),
        ('fixed', _("Fixed Amount")),
    )

    name = models.CharField(
        _("Name"),
        max_length=255,
        unique=True
    )
    discount_type = models.CharField(
        _("Type"),
        max_length=20,
        choices=DISCOUNT_TYPES
    )
    amount = models.DecimalField(
        _("Amount"),
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(0.01)]
    )
    products = models.ManyToManyField(
        Product,
        blank=True,
        verbose_name=_("Applicable Products")
    )
    categories = models.ManyToManyField(
        ProductCategory,
        blank=True,
        verbose_name=_("Applicable Categories")
    )
    user_groups = models.ManyToManyField(
        'auth.Group',
        blank=True,
        verbose_name=_("Eligible User Groups")
    )
    valid_from = models.DateTimeField(_("Valid From"))
    valid_until = models.DateTimeField(
        _("Valid Until"),
        null=True,
        blank=True
    )
    min_purchase = models.DecimalField(
        _("Minimum Purchase"),
        max_digits=PricingConstants.PriceLimits.MAX_DIGITS,
        decimal_places=PricingConstants.PriceLimits.DECIMALS,
        null=True,
        blank=True,
        validators=[MinValueValidator(0.01)]
    )
    is_active = models.BooleanField(
        _("Active"),
        default=True
    )

    class Meta:
        verbose_name = _("Discount")
        verbose_name_plural = _("Discounts")
        indexes = [
            models.Index(fields=['valid_from', 'valid_until']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_discount_type_display()})"
# endregion
