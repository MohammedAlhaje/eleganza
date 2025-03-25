from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.core.validators import (
    MinValueValidator, 
    MaxValueValidator,
)
from django.core.exceptions import ValidationError
from django.conf import settings
from django.urls import reverse
from django.db.models import Avg
from eleganza.core.models import BaseModel
from mptt.models import MPTTModel, TreeForeignKey
from autoslug import AutoSlugField
from djmoney.models.fields import MoneyField
from django_cleanup import cleanup
from .validators import (
    ProductImageValidator,
    product_image_path,
    CategoryImageValidator,
    category_image_path
)

class ProductCategory(MPTTModel, BaseModel):
    """Hierarchical product category system with image validation"""
    name = models.CharField(
        _("Category Name"),
        max_length=100,
        unique=True,
        help_text=_("Unique name for product category")
    )
    parent = TreeForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='children',
        verbose_name=_("Parent Category"),
        help_text=_("Parent category for hierarchical organization")
    )
    slug = AutoSlugField(
        populate_from='name',  # Critical for auto-generation
        unique=True,
        verbose_name=_("Product URL Slug"),
        help_text=_("Unique URL identifier for the product"),
        editable=True  # Must be True for admin forms
    )
    description = models.TextField(
        _("Description"),
        blank=True,
        help_text=_("Detailed category description for SEO and informational purposes")
    )
    featured_image = models.ImageField(
        _("Featured Image"),
        upload_to=category_image_path,
        validators=[CategoryImageValidator()],
        blank=True,
        null=True,
        help_text=_("Representative image for the category (max 2000x2000px)")
    )
    is_active = models.BooleanField(
        _("Active"),
        default=True,
        help_text=_("Toggle category visibility in storefront")
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

    def get_absolute_url(self):
        return reverse('products:category-detail', kwargs={'slug': self.slug})

    def clean(self):
        if self.parent and self.parent.id == self.id:
            raise ValidationError(_("Category cannot be its own parent"))
        super().clean()

class ActiveStockReservationManager(models.Manager):
    """Custom manager for active stock reservations"""
    def get_queryset(self):
        return super().get_queryset().filter(
            is_active=True,
            expires_at__gt=timezone.now()
        )

@cleanup.select
class Product(BaseModel):
    """Core product model with enhanced validation"""
    name = models.CharField(
        _("Product Name"),
        max_length=255,
        db_index=True,
        help_text=_("Full product name for display purposes")
    )
    slug = AutoSlugField(
        populate_from='name',  # Critical for auto-generation
        unique=True,
        verbose_name=_("Product URL Slug"),
        help_text=_("Unique URL identifier for the product"),
        editable=True  # Must be True for admin forms
    )
    sku = models.CharField(
        _("SKU"),
        max_length=50,
        unique=True,
        db_index=True,
        help_text=_("Unique stock keeping unit identifier")
    )

    description = models.TextField(
        _("Description"),
        help_text=_("Detailed product description for customers")
    )
    # Maintain single category relationship
    category = models.ForeignKey(
        ProductCategory,
        on_delete=models.SET_NULL,
        null=True,
        related_name='products',
        verbose_name=_("Primary Category"),
        help_text=_("Main product category for navigation and filtering"),
        db_index=True
    )
    original_price = MoneyField(
        _("Original Price"),
        max_digits=14,
        decimal_places=2,
        default_currency=settings.DEFAULT_CURRENCY,
        help_text=_("Manufacturer's suggested retail price (MSRP)")
    )
    selling_price = MoneyField(
        _("Selling Price"),
        max_digits=14,
        decimal_places=2,
        default_currency=settings.DEFAULT_CURRENCY,
        help_text=_("Actual selling price to customers")
    )
    is_featured = models.BooleanField(
        _("Featured Product"),
        default=False,
        help_text=_("Prominently display this product in featured sections")
    )
    average_rating = models.DecimalField(
        _("Average Rating"),
        max_digits=3,
        decimal_places=1,
        default=0.0,
        editable=False
    )
    review_count = models.PositiveIntegerField(
        _("Review Count"),
        default=0,
        editable=False
    )
    is_active = models.BooleanField(
        _("Active"),
        default=True,
        help_text=_("Designates whether this product should be treated as active.")
    )
    class Meta:
        verbose_name = _("Product")
        verbose_name_plural = _("Products")
        ordering = ['-created_at']
        # constraints = [
        #     models.CheckConstraint(
        #         check=Q(selling_price_currency=F('original_price_currency')),
        #         name="consistent_pricing_currency"
        #     ),
        #     models.CheckConstraint(
        #         check=Q(selling_price_amount__lte=F('original_price_amount')),
        #         name="selling_price_lte_original"
        #     ),
        # ]
        indexes = [
            models.Index(fields=['sku']),
            models.Index(fields=['name']),
            models.Index(fields=['is_featured']),
            models.Index(fields=['average_rating']),
        ]

    def __str__(self):
        return f"{self.name} ({self.sku})"

    def get_absolute_url(self):
        return reverse('products:detail', kwargs={'slug': self.slug})

    @property
    def discount_percentage(self):
        if self.original_price.amount == 0:
            return 0
        discount = ((self.original_price.amount - self.selling_price.amount) / 
                   self.original_price.amount) * 100
        return round(discount, 2)

    def update_rating_stats(self):
        aggregates = self.reviews.filter(is_approved=True).aggregate(
            average=Avg('rating'),
            count=models.Count('id')
        )
        self.average_rating = aggregates['average'] or 0.0
        self.review_count = aggregates['count']
        self.save(update_fields=['average_rating', 'review_count'])

    def clean(self):
        if self.selling_price.currency != self.original_price.currency:
            raise ValidationError(_("Currencies must match for price comparison"))
        if self.selling_price > self.original_price:
            raise ValidationError(_("Selling price cannot exceed original price"))
        super().clean()

class Inventory(models.Model):
    """Enhanced inventory tracking with safety checks"""
    product = models.OneToOneField(
        Product,
        primary_key=True,
        on_delete=models.CASCADE,
        related_name='inventory'
    )
    stock_quantity = models.PositiveIntegerField(
        _("Total Stock"),
        default=0,
        validators=[MinValueValidator(0)],
        help_text=_("Total physical inventory available")
    )
    low_stock_threshold = models.PositiveIntegerField(
        _("Low Stock Threshold"),
        default=10,
        help_text=_("Minimum stock level before restock alert")
    )

    class Meta:
        verbose_name = _("Inventory")
        verbose_name_plural = _("Inventory Records")
        indexes = [
            models.Index(fields=['stock_quantity']),
        ]

    def __str__(self):
        return f"{self.product.name} Inventory"

    @property
    def available_stock(self):
        return max(self.stock_quantity - self.reservations.active().count(), 0)

    @property
    def needs_restock(self):
        return self.stock_quantity <= self.low_stock_threshold

@cleanup.select
class ProductImage(BaseModel):
    """Product images with improved upload handling"""
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='images'
    )
    image = models.ImageField(
        _("Image"),
        upload_to=product_image_path,
        validators=[ProductImageValidator()],
        help_text=_("High-quality product image (max 4000x4000px)")
    )
    caption = models.CharField(
        _("Caption"),
        max_length=255,
        blank=True,
        help_text=_("Alt text and image description for accessibility")
    )
    is_primary = models.BooleanField(
        _("Primary Image"),
        default=False,
        help_text=_("Main display image for product listings")
    )
    sort_order = models.PositiveIntegerField(
        _("Sort Order"),
        default=0,
        help_text=_("Display order in image galleries (lower numbers first)")
    )

    class Meta:
        ordering = ['-is_primary', 'sort_order']
        constraints = [
            models.UniqueConstraint(
                fields=['product', 'image'],
                name='unique_product_image'
            )
        ]
        verbose_name = _("Product Image")
        verbose_name_plural = _("Product Images")

    def __str__(self):
        return _("Image for %(product)s") % {'product': self.product.name}

    def save(self, *args, **kwargs):
        if self.is_primary:
            self.product.images.exclude(pk=self.pk).update(is_primary=False)
        super().save(*args, **kwargs)

class ProductReview(BaseModel):
    """Enhanced reviews with signals integration"""
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
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text=_("Rating from 1 (worst) to 5 (best)")
    )
    title = models.CharField(
        _("Review Title"),
        max_length=255,
        help_text=_("Brief summary of your experience")
    )
    comment = models.TextField(
        _("Review Comment"),
        help_text=_("Detailed feedback about the product")
    )
    is_approved = models.BooleanField(
        _("Approved"),
        default=False,
        help_text=_("Approved reviews are visible publicly")
    )
    helpful_votes = models.PositiveIntegerField(
        _("Helpful Votes"),
        default=0,
        editable=False
    )

    class Meta:
        unique_together = ('product', 'user')
        ordering = ['-created_at']
        verbose_name = _("Product Review")
        verbose_name_plural = _("Product Reviews")
        indexes = [
            models.Index(fields=['rating']),
            models.Index(fields=['is_approved']),
        ]

    def __str__(self):
        return _("%(user)s's review of %(product)s") % {
            'user': self.user.username,
            'product': self.product.name
        }

    def clean(self):
        if self._state.adding and ProductReview.objects.filter(product=self.product, user=self.user).exists():
            raise ValidationError(_("You've already reviewed this product"))
        super().clean()

    def approve(self):
        self.is_approved = True
        self.save()
        self.product.update_rating_stats()