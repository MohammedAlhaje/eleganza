from django.db import models
from django.core.validators import MinValueValidator
from django.utils.translation import gettext_lazy as _
from eleganza.core.models import BaseModel
from eleganza.products.constants import (
    InventoryConstants
)
from .product import ProductVariant

class Inventory(BaseModel):
    """Real-time stock tracking system"""
    variant = models.OneToOneField(
        ProductVariant,
        on_delete=models.CASCADE,
        related_name='inventory',
        verbose_name=_("Variant")
    )
    stock_quantity = models.PositiveIntegerField(
        _("Stock Quantity"),
        default=InventoryConstants.DEFAULT_STOCK,
        validators=[MinValueValidator(0)]
    )
    low_stock_threshold = models.PositiveIntegerField(
        _("Low Stock Threshold"),
        default=InventoryConstants.LOW_STOCK_THRESHOLD
    )
    last_restock = models.DateTimeField(
        _("Last Restock"),
        auto_now_add=True
    )

    class Meta:
        verbose_name = _("Inventory")
        verbose_name_plural = _("Inventory Records")

    def __str__(self):
        return f"Inventory for {self.variant.sku}"

class InventoryHistory(models.Model):
    """Complete audit trail of stock movements"""
    inventory = models.ForeignKey(
        Inventory,
        on_delete=models.CASCADE,
        related_name='history',
        verbose_name=_("Inventory")
    )
    old_stock = models.IntegerField(_("Previous Stock"))
    new_stock = models.IntegerField(_("New Stock"))
    timestamp = models.DateTimeField(
        _("Timestamp"),
        auto_now_add=True
    )
    notes = models.CharField(
        _("Notes"),
        max_length=255,
        blank=True
    )

    class Meta:
        verbose_name = _("Inventory History")
        verbose_name_plural = _("Inventory History Records")
        ordering = ['-timestamp']

    def __str__(self):
        return f"Stock change for {self.inventory.variant.sku}"
