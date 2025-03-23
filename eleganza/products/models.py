import os
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from django.conf import settings
from eleganza.core.models import BaseModel
from django.db.models import Q

def product_image_upload_path(instance, filename):
    """Generate upload path for product images"""
    return os.path.join(
        'products',
        str(instance.product.id),
        'images',
        filename
    )

class ProductCategory(BaseModel):
    """
    Hierarchical product category system with MPTT support
    """
    name = models.CharField(
        _("Category Name"),
        max_length=100,
        unique=True
    )
    parent = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='children'
    )
    slug = models.SlugField(
        _("Slug"),
        unique=True,
        max_length=150
    )
    description = models.TextField(
        _("Description"),
        blank=True
    )
    featured_image = models.ImageField(
        _("Featured Image"),
        upload_to='categories/',
        blank=True,
        null=True
    )

    class Meta:
        verbose_name = _("Product Category")
        verbose_name_plural = _("Product Categories")
        ordering = ['name']

    def __str__(self):
        return self.name

    def clean(self):
        # Prevent circular parent relationships
        if self.parent and self.parent.id == self.id:
            raise ValidationError(_("Category cannot be its own parent"))

class Product(BaseModel):
    """
    Core product model with inventory tracking and pricing
    """
    slug = models.SlugField(
        _("Slug"),
        max_length=255,
        unique=True
    )
    sku = models.CharField(
        _("SKU"),
        max_length=50,
        unique=True
    )
    name = models.CharField(
        _("Product Name"),
        max_length=255,
        db_index=True
    )
    description = models.TextField(_("Description"))
    category = models.ForeignKey(
        ProductCategory,
        on_delete=models.SET_NULL,
        null=True,
        related_name='products'
    )
    original_price = models.DecimalField(
        _("Original Price"),
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    selling_price = models.DecimalField(
        _("Selling Price"),
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    stock_quantity = models.PositiveIntegerField(
        _("Stock Quantity"),
        default=0
    )
    reserved_stock = models.PositiveIntegerField(
        _("Reserved Stock"),
        default=0
    )
    is_featured = models.BooleanField(
        _("Featured Product"),
        default=False
    )

    class Meta:
        verbose_name = _("Product")
        verbose_name_plural = _("Products")
        constraints = [
            models.CheckConstraint(
                check=Q(reserved_stock__lte=models.F('stock_quantity')),
                name="reserved_stock_lte_stock"
            ),
            models.CheckConstraint(
                check=Q(selling_price__lte=models.F('original_price')),
                name="selling_price_lte_original"
            ),
        ]
        indexes = [
            models.Index(fields=['sku']),
            models.Index(fields=['name']),
            models.Index(fields=['is_featured']),
        ]

    def __str__(self):
        return f"{self.name} ({self.sku})"

    @property
    def available_stock(self):
        return max(self.stock_quantity - self.reserved_stock, 0)

    @property
    def discount_percentage(self):
        if self.original_price == 0:
            return 0
        return round(
            ((self.original_price - self.selling_price) / self.original_price) * 100,
            2
        )

    def clean(self):
        if self.selling_price > self.original_price:
            raise ValidationError(
                _("Selling price cannot exceed original price")
            )

class ProductImage(BaseModel):
    """
    Product images with primary image designation
    """
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='images'
    )
    image = models.ImageField(
        _("Image"),
        upload_to=product_image_upload_path
    )
    caption = models.CharField(
        _("Caption"),
        max_length=255,
        blank=True
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
        ordering = ['-is_primary', 'sort_order']
        unique_together = ('product', 'image')

    def __str__(self):
        return _("Image for %(product)s") % {'product': self.product.name}

class ProductReview(BaseModel):
    """
    Customer product reviews with ratings
    """
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
        max_length=255
    )
    comment = models.TextField(_("Review Comment"))
    is_approved = models.BooleanField(
        _("Approved"),
        default=False
    )

    class Meta:
        unique_together = ('product', 'user')
        ordering = ['-created_at']
        verbose_name = _("Product Review")
        verbose_name_plural = _("Product Reviews")

    def __str__(self):
        return _("%(user)s's review of %(product)s") % {
            'user': self.user.username,
            'product': self.product.name
        }