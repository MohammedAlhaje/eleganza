from django.db import models
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _
from eleganza.core.models import BaseModel
from ..constants import (
    FieldLimits,
    ValidationPatterns,
)
from .product_model import Product

class Tag(BaseModel):
    """Flexible product tagging system"""
    name = models.CharField(
        _("Name"),
        max_length=FieldLimits.ATTRIBUTE_NAME,
        unique=True,
        validators=[
            RegexValidator(
                ValidationPatterns.PRODUCT_NAME,
                _("Tag name contains invalid characters")
            )
        ]
    )
    slug = models.SlugField(
        _("Slug"),
        unique=True,
        max_length=FieldLimits.ATTRIBUTE_NAME
    )

    class Meta:
        verbose_name = _("Tag")
        verbose_name_plural = _("Tags")
        indexes = [
            models.Index(fields=['name']),
            models.Index(fields=['slug']),
        ]

    def __str__(self):
        return self.name

class ProductTag(models.Model):
    """Through model for product-tag relationships"""
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='product_tags'
    )
    tag = models.ForeignKey(
        Tag,
        on_delete=models.CASCADE,
        related_name='product_tags'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('product', 'tag')
        ordering = ['-created_at']
        verbose_name = _("Product Tag")
        verbose_name_plural = _("Product Tags")

    def __str__(self):
        return f"{self.product.name} - {self.tag.name}"
