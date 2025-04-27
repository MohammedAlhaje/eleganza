from django.db import models
from django.core.validators import FileExtensionValidator
from django.core.exceptions import ValidationError
from django.db.models import Q,CheckConstraint
from django.utils.translation import gettext_lazy as _
from eleganza.core.models import BaseModel
from ..constants import (
    ImageConstants,
)
from .product_model import Product, ProductVariant


class ProductImage(BaseModel):
    """Comprehensive product image management"""
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='images',
        null=True,
        blank=True,
        verbose_name=_("Product")
    )
    variant = models.ForeignKey(
        ProductVariant,
        on_delete=models.CASCADE,
        related_name='images',
        null=True,
        blank=True,
        verbose_name=_("Variant")
    )
    image = models.ImageField(
        _("Image"),
        upload_to=ImageConstants.UPLOAD_PATHS['PRODUCT'],
        validators=[
            FileExtensionValidator(ImageConstants.ALLOWED_FORMATS),
        ]
    )
    is_primary = models.BooleanField(
        _("Primary Image"),
        default=False
    )
    sort_order = models.PositiveIntegerField(
        _("Sort Order"),
        default=0
    )

    class Meta:
        verbose_name = _("Product Image")
        verbose_name_plural = _("Product Images")
        ordering = ['-is_primary', 'sort_order']
        constraints = [
            CheckConstraint(
                # Check that either product or variant is set, but not both
                # This is a custom constraint to ensure that an image is linked to either a product or a variant, but not both.
                check=(
                    (Q(product__isnull=False) & Q(variant__isnull=True)) |
                    (Q(product__isnull=True) & Q(variant__isnull=False))
                ),
                name='product_xor_variant'
            ),
        ]

    def clean(self):
        if self.product and self.variant:
            raise ValidationError(_("Image cannot be linked to both product and variant"))
        if not self.product and not self.variant:
            raise ValidationError(_("Image must be linked to product or variant"))

    def __str__(self):
        return f"Image for {self.product.name if self.product else self.variant.sku}"
