from django.db import models
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _
from eleganza.core.models import BaseModel
from ..constants import (
    FieldLimits,
    ValidationPatterns,
)
from .category import ProductCategory

class ProductAttribute(BaseModel):
    """Defines product attributes like size, color, etc."""
    name = models.CharField(
        _("Name"),
        max_length=FieldLimits.ATTRIBUTE_NAME,
        unique=True,
        validators=[
            RegexValidator(
                ValidationPatterns.PRODUCT_NAME,
                _("Attribute name contains invalid characters")
            )
        ]
    )
    code = models.SlugField(
        _("Code"),
        max_length=FieldLimits.ATTRIBUTE_NAME,
        unique=True
    )
    is_required = models.BooleanField(
        _("Required"),
        default=True
    )

    class Meta:
        ordering = ['name']
        indexes = [models.Index(fields=['code'])]
        verbose_name = _("Product Attribute")
        verbose_name_plural = _("Product Attributes")

    def __str__(self):
        return f"{self.name} ({self.code})"

class ProductOption(BaseModel):
    """Defines possible values for product attributes"""
    attribute = models.ForeignKey(
        ProductAttribute,
        on_delete=models.CASCADE,
        related_name='options',
        verbose_name=_("Attribute")
    )
    value = models.CharField(
        _("Value"),
        max_length=FieldLimits.OPTION_VALUE,
        validators=[
            RegexValidator(
                ValidationPatterns.PRODUCT_NAME,
                _("Option value contains invalid characters")
            )
        ]
    )
    sort_order = models.PositiveIntegerField(
        _("Sort Order"),
        default=0
    )
    is_active = models.BooleanField(
        _("Active"),
        default=True
    )

    class Meta:
        unique_together = ('attribute', 'value')
        ordering = ['attribute__name', 'sort_order', 'value']
        verbose_name = _("Product Option")
        verbose_name_plural = _("Product Options")

    def __str__(self):
        return f"{self.attribute.name}: {self.value}"

class Product(BaseModel):
    """Central product entity with full relationships"""
    STATUS_CHOICES = (
        ('active', _("Active")),
        ('draft', _("Draft")),
        ('archived', _("Archived")),
    )

    name = models.CharField(
        _("Name"),
        max_length=FieldLimits.PRODUCT_NAME,
        db_index=True,
        validators=[
            RegexValidator(
                ValidationPatterns.PRODUCT_NAME,
                _("Product name contains invalid characters")
            )
        ]
    )
    slug = models.SlugField(
        _("Slug"),
        unique=True,
        max_length=FieldLimits.PRODUCT_NAME
    )
    sku = models.CharField(
        _("SKU"),
        max_length=FieldLimits.SKU,
        unique=True,
        db_index=True,
        validators=[
            RegexValidator(
                ValidationPatterns.SKU,
                _("Invalid SKU format")
            )
        ]
    )
    description = models.TextField(_("Description"))
    category = models.ForeignKey(
        ProductCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='products',
        verbose_name=_("Category")
    )
    attributes = models.ManyToManyField(
        ProductAttribute,
        related_name='products',
        blank=True,
        verbose_name=_("Attributes")
    )
    is_featured = models.BooleanField(
        _("Featured"),
        default=False,
        db_index=True
    )
    status = models.CharField(
        _("Status"),
        max_length=20,
        choices=STATUS_CHOICES,
        default='active',
        db_index=True
    )
    average_rating = models.DecimalField(
        _("Average Rating"),
        max_digits=3,
        decimal_places=2,
        default=0.0,
        editable=False
    )
    review_count = models.PositiveIntegerField(
        _("Review Count"),
        default=0,
        editable=False
    )

    class Meta:
        verbose_name = _("Product")
        verbose_name_plural = _("Products")
        indexes = [
            models.Index(fields=['sku']),
            models.Index(fields=['name']),
            models.Index(fields=['is_featured']),
            models.Index(fields=['average_rating']),
        ]

    def __str__(self):
        return f"{self.name} (SKU: {self.sku})"

class ProductVariant(BaseModel):
    """Concrete product variations with specific options"""
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='variants',
        verbose_name=_("Product")
    )
    sku = models.CharField(
        _("SKU"),
        max_length=FieldLimits.SKU,
        db_index=True,
        validators=[
            RegexValidator(
                ValidationPatterns.SKU,
                _("Invalid SKU format")
            )
        ]
    )
    options = models.ManyToManyField(
        ProductOption,
        related_name='variants',
        verbose_name=_("Options")
    )
    is_default = models.BooleanField(
        _("Default Variant"),
        default=False
    )
    is_active = models.BooleanField(
        _("Active"),
        default=True,
        db_index=True
    )

    class Meta:
        unique_together = ('product', 'sku')
        verbose_name = _("Product Variant")
        verbose_name_plural = _("Product Variants")
        indexes = [
            models.Index(fields=['sku']),
            models.Index(fields=['is_default']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return f"{self.product.name} - {self.sku}"
# endregion