from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from django.conf import settings
from django.urls import reverse
from django.db.models import Q
from eleganza.core.models import BaseModel
from mptt.models import MPTTModel, TreeForeignKey
from autoslug import AutoSlugField
from djmoney.models.fields import MoneyField, Money
from django_cleanup import cleanup
from eleganza.core.image_utils import WebPField
from eleganza.products.constants import (
    DiscountTypes,
    FieldLengths,
    Defaults
)

class ProductCategory(MPTTModel, BaseModel):
    """Hierarchical product category structure"""
    name = models.CharField(
        _("Category Name"),
        max_length=FieldLengths.CATEGORY_NAME,
        unique=True
    )
    parent = TreeForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='children'
    )
    slug = AutoSlugField(
        populate_from='name',
        unique=True,
        editable=True
    )
    description = models.TextField(
        _("Description"),
        blank=True
    )
    featured_image = WebPField(
        # Standard Django params
        verbose_name=_("Featured Image"),
        blank=True,
        null=True,
        help_text=_("Will be automatically converted to WebP format"),
        
        # Custom params
        UPLOAD_DIR='products/categories/',
        MAX_SIZE_MB=5,
        QUALITY=90
    )

    is_active = models.BooleanField(
        _("Active"),
        default=True,
        db_index=True
    )

    class MPTTMeta:
        order_insertion_by = ['name']
        verbose_name = _("Product Category")
        verbose_name_plural = _("Product Categories")

    class Meta:
        indexes = [
            models.Index(fields=['slug']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        if self.parent and self.parent.id == self.id:
            raise ValidationError(_("Category cannot be its own parent"))
        super().clean()

    def get_absolute_url(self):
        return reverse('products:category-detail', kwargs={'slug': self.slug})

class ProductAttribute(models.Model):
    """Defines characteristics for variants"""
    name = models.CharField(
        _("Attribute Name"),
        max_length=FieldLengths.ATTRIBUTE_NAME,
        unique=True
    )
    code = models.SlugField(
        _("Attribute Code"),
        max_length=FieldLengths.ATTRIBUTE_NAME,
        unique=True
    )
    is_required = models.BooleanField(
        _("Required"),
        default=True
    )

    class Meta:
        ordering = ['name']
        indexes = [models.Index(fields=['code'])]

    def __str__(self):
        return f"{self.name} ({self.code})"

    def clean(self):
        self.code = self.code.lower().strip()
        super().clean()

class ProductOption(models.Model):
    """Specific values for attributes"""
    attribute = models.ForeignKey(
        ProductAttribute,
        on_delete=models.CASCADE,
        related_name='options'
    )
    value = models.CharField(
        _("Option Value"),
        max_length=FieldLengths.OPTION_VALUE
    )
    sort_order = models.PositiveIntegerField(
        _("Sort Order"),
        default=Defaults.SORT_ORDER
    )
    is_active = models.BooleanField(
        _("Active"),
        default=True
    )

    class Meta:
        unique_together = ('attribute', 'value')
        ordering = ['attribute__name', 'sort_order', 'value']

    def __str__(self):
        return f"{self.attribute.name}: {self.value}"

    def clean(self):
        self.value = self.value.strip()
        super().clean()

class Product(BaseModel):
    """Core product model - data structure only"""
    name = models.CharField(
        _("Product Name"),
        max_length=FieldLengths.PRODUCT_NAME,
        db_index=True
    )
    slug = models.SlugField(
        _("URL Slug"),
        unique=True
    )
    sku = models.CharField(
        _("SKU"),
        max_length=FieldLengths.SKU,
        unique=True,
        db_index=True
    )
    description = models.TextField(
        _("Description")
    )
    category = models.ForeignKey(
        ProductCategory,
        on_delete=models.SET_NULL,
        null=True,
        related_name='products'
    )
    original_price = MoneyField(
        _("Original Price"),
        max_digits=Defaults.PRICE_MAX_DIGITS,
        decimal_places=Defaults.PRICE_DECIMALS,
        default_currency=settings.DEFAULT_CURRENCY
    )
    selling_price = MoneyField(
        _("Selling Price"),
        max_digits=Defaults.PRICE_MAX_DIGITS,
        decimal_places=Defaults.PRICE_DECIMALS,
        default_currency=settings.DEFAULT_CURRENCY
    )
    final_price = MoneyField(
        _("Final Price"),
        max_digits=Defaults.PRICE_MAX_DIGITS,
        decimal_places=Defaults.PRICE_DECIMALS,
        default_currency=settings.DEFAULT_CURRENCY,
        editable=False
    )
    discount_type = models.CharField(
        _("Discount Type"),
        max_length=DiscountTypes.MAX_LENGTH,
        choices=DiscountTypes.CHOICES,
        default=DiscountTypes.NONE,
    )
    discount_amount = MoneyField(
        _("Discount Amount"),
        max_digits=Defaults.PRICE_MAX_DIGITS,
        decimal_places=Defaults.PRICE_DECIMALS,
        default_currency=settings.DEFAULT_CURRENCY,
        default=Money(0, settings.DEFAULT_CURRENCY),
        null=True,
        blank=True
    )
    discount_percent = models.DecimalField(
        _("Discount Percentage"),
        max_digits=5,
        decimal_places=2,
        default=0.0,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    has_variants = models.BooleanField(
        _("Has Variants"),
        default=False,
        db_index=True
    )
    attributes = models.ManyToManyField(
        ProductAttribute,
        related_name='products',
        blank=True
    )
    is_featured = models.BooleanField(
        _("Featured"),
        default=False,
        db_index=True
    )
    is_active = models.BooleanField(
        _("Active"),
        default=True,
        db_index=True
    )
    average_rating = models.DecimalField(
        _("Average Rating"),
        max_digits=Defaults.RATING_MAX_DIGITS,
        decimal_places=Defaults.RATING_DECIMALS,
        default=0.0,
        editable=False
    )
    review_count = models.PositiveIntegerField(
        _("Review Count"),
        default=0,
        editable=False
    )

    class Meta:
        indexes = [
            models.Index(fields=['sku']),
            models.Index(fields=['name']),
            models.Index(fields=['is_featured']),
            models.Index(fields=['average_rating']),
        ]

    def __str__(self):
        return f"{self.name} ({self.sku})"

    def clean(self):
        super().clean()
        if self.selling_price.amount <= 0:
            raise ValidationError({'selling_price': _("Price must be greater than 0")})
        if self.discount_type == DiscountTypes.FIXED and not self.discount_amount:
            raise ValidationError({'discount_amount': _("Fixed discount requires amount")})
        if self.discount_type == DiscountTypes.PERCENTAGE and not self.discount_percent:
            raise ValidationError({'discount_percent': _("Percentage discount requires value")})

    def get_absolute_url(self):
        return reverse('products:detail', kwargs={'slug': self.slug})

class ProductVariant(BaseModel):
    """Variant model - data structure only"""
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='variants'
    )
    sku = models.CharField(
        _("Variant SKU"),
        max_length=FieldLengths.SKU,
        unique=True,
        db_index=True
    )
    options = models.ManyToManyField(
        ProductOption,
        related_name='variants'
    )
    price_modifier = MoneyField(
        _("Price Modifier"),
        max_digits=Defaults.PRICE_MAX_DIGITS,
        decimal_places=Defaults.PRICE_DECIMALS,
        default=Money(0, settings.DEFAULT_CURRENCY),
        default_currency=settings.DEFAULT_CURRENCY
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
        indexes = [
            models.Index(fields=['sku', 'is_active']),
            models.Index(fields=['is_default']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return f"{self.product.name}"

    def clean(self):
        super().clean()
        if self.product_id and self.price_modifier.currency != self.product.selling_price.currency:
            raise ValidationError(_("Currency mismatch"))

class Inventory(models.Model):
    """Inventory model - data structure only"""
    variant = models.OneToOneField(
        ProductVariant,
        on_delete=models.CASCADE,
        related_name='inventory',
        primary_key=True
    )
    stock_quantity = models.PositiveIntegerField(
        _("Total Stock"),
        default=Defaults.STOCK_QUANTITY,
        validators=[MinValueValidator(0)]
    )
    low_stock_threshold = models.PositiveIntegerField(
        _("Low Stock Alert"),
        default=Defaults.LOW_STOCK_THRESHOLD
    )
    last_restock = models.DateTimeField(
        _("Last Restock"),
        auto_now_add=True,
        null=True,
        blank=True
    )

    class Meta:
        verbose_name = _("Inventory")
        verbose_name_plural = _("Inventory Records")

    def __str__(self):
        return f"Inventory for {self.variant}"

class InventoryHistory(models.Model):
    """Inventory change history - data structure only"""
    inventory = models.ForeignKey(
        Inventory,
        on_delete=models.CASCADE,
        related_name='history'
    )
    old_stock = models.IntegerField(
        _("Previous Stock")
    )
    new_stock = models.IntegerField(
        _("New Stock")
    )
    timestamp = models.DateTimeField(
        _("Change Time"),
        auto_now_add=True
    )

    class Meta:
        ordering = ['-timestamp']
        verbose_name = _("Inventory History")

    def __str__(self):
        return f"Stock change for {self.inventory}"

@cleanup.select
class ProductImage(BaseModel):
    """Product images - data structure only"""
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='images',
        null=True,
        blank=True
    )
    variant = models.ForeignKey(
        ProductVariant,
        on_delete=models.CASCADE,
        related_name='images',
        null=True,
        blank=True
    )
    image = WebPField(
        # Standard Django params
        verbose_name=_("Prodcuts Image"),
        blank=True,
        null=True,
        help_text=_("Will be automatically converted to WebP format"),
        
        # Custom params
        UPLOAD_DIR='products/images/',
        MAX_SIZE_MB=5,
        QUALITY=90
    )

    is_primary = models.BooleanField(
        _("Primary Image"),
        default=False
    )
    sort_order = models.PositiveIntegerField(
        _("Sort Order"),
        default=Defaults.SORT_ORDER
    )
    caption = models.CharField(
        _("Caption"),
        max_length=FieldLengths.IMAGE_CAPTION,
        blank=True
    )

    class Meta:
        ordering = ['-is_primary', 'sort_order']
        constraints = [
            models.UniqueConstraint(
                fields=['product', 'image'],
                name='unique_product_image',
                condition=Q(variant__isnull=True)),
        ]

    def __str__(self):
        return _("Image for %(target)s") % {'target': self.product or self.variant}

    def clean(self):
        if not (self.product or self.variant):
            raise ValidationError(_("Must link to a product or variant"))
        if self.product and self.variant:
            raise ValidationError(_("Cannot link to both product and variant"))

class ProductReview(BaseModel):
    """Review model - data structure only"""
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='reviews'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='reviews'
    )
    rating = models.PositiveSmallIntegerField(
        _("Rating"),
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    title = models.CharField(
        _("Review Title"),
        max_length=FieldLengths.REVIEW_TITLE
    )
    comment = models.TextField(
        _("Review Comment")
    )
    is_approved = models.BooleanField(
        _("Approved"),
        default=False,
        db_index=True
    )
    helpful_votes = models.PositiveIntegerField(
        _("Helpful Votes"),
        default=0,
        editable=False
    )

    class Meta:
        unique_together = ('product', 'user')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['rating', 'is_approved']),
        ]

    def __str__(self):
        return _("%(user)s's review of %(product)s") % {
            'user': self.user.get_short_name(),
            'product': self.product.name
        }