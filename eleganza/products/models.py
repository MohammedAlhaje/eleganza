# models.py
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from django.conf import settings
from django.urls import reverse
from django.db.models import (
    Avg, Q, Count, F, Subquery, Sum,
    OuterRef, DecimalField, Case, When
)
from django.db import transaction
from django.db.models.functions import Coalesce
from decimal import Decimal
from eleganza.core.models import BaseModel
from mptt.models import MPTTModel, TreeForeignKey
from autoslug import AutoSlugField
from djmoney.models.fields import MoneyField, Money
from django_cleanup import cleanup
from imagekit.models import ProcessedImageField
from imagekit.processors import Transpose, ResizeToFit
from django.dispatch import receiver
from django.db.models.signals import post_save, post_delete
from .validators import (
    ProductImageValidator, 
    product_image_path, 
    ProductImageConfig,
    category_image_path,
    CategoryImageValidator,
    CategoryImageConfig
)

# --------------------------
# Category System
# --------------------------
class ProductCategory(MPTTModel, BaseModel):
    """Hierarchical product categorization with MPTT optimization"""
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
        populate_from='name',
        unique=True,
        verbose_name=_("Category URL Slug"),
        help_text=_("Unique URL identifier for the category"),
        editable=True
    )
    description = models.TextField(
        _("Description"),
        blank=True,
        help_text=_("Detailed category description for SEO and informational purposes")
    )
    featured_image = ProcessedImageField(
        verbose_name=_("Featured Image"),
        upload_to=category_image_path,
        processors=[
            Transpose(),
            ResizeToFit(CategoryImageConfig.MAX_DIMENSION, CategoryImageConfig.MAX_DIMENSION)
        ],
        format='WEBP',
        options={'quality': CategoryImageConfig.QUALITY},
        validators=[CategoryImageValidator()],
        blank=True,
        null=True,
        help_text=_("Representative image for the category (max %(dim)sx%(dim)s)") % {
            'dim': CategoryImageConfig.MAX_DIMENSION
        }
    )
    is_active = models.BooleanField(
        _("Active"),
        default=True,
        db_index=True,
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
        """Validate category hierarchy integrity"""
        if self.parent and self.parent.id == self.id:
            raise ValidationError(_("Category cannot be its own parent"))
        super().clean()


# --------------------------
# Variant System Core
# --------------------------
class ProductAttribute(models.Model):
    """Defines variant characteristics (Color, Size, etc.)"""
    name = models.CharField(
        _("Attribute Name"),
        max_length=100,
        unique=True,
        help_text=_("Customer-facing name (e.g., 'Color', 'Size')")
    )
    code = models.SlugField(
        _("Attribute Code"),
        max_length=100,
        unique=True,
        help_text=_("Internal identifier (e.g., 'color', 'size')")
    )
    is_required = models.BooleanField(
        _("Required"),
        default=True,
        help_text=_("Must this attribute be specified for all variants?")
    )

    class Meta:
        ordering = ['name']
        verbose_name = _("Product Attribute")
        verbose_name_plural = _("Product Attributes")
        indexes = [
            models.Index(fields=['code']),
        ]

    def __str__(self):
        return f"{self.name} ({self.code})"

    def clean(self):
        """Normalize attribute code format"""
        self.code = self.code.lower().strip()
        super().clean()


class ProductOption(models.Model):
    """Specific values for product attributes"""
    attribute = models.ForeignKey(
        ProductAttribute,
        on_delete=models.CASCADE,
        related_name='options',
        verbose_name=_("Attribute")
    )
    value = models.CharField(
        _("Option Value"),
        max_length=100,
        help_text=_("Display value (e.g., 'Red', 'XXL')")
    )
    sort_order = models.PositiveIntegerField(
        _("Sort Order"),
        default=0,
        help_text=_("Display order in selectors (lower first)")
    )
    is_active = models.BooleanField(
        _("Active"),
        default=True,
        help_text=_("Toggle option visibility")
    )

    class Meta:
        unique_together = ('attribute', 'value')
        ordering = ['attribute__name', 'sort_order', 'value']
        verbose_name = _("Product Option")
        verbose_name_plural = _("Product Options")

    def __str__(self):
        return f"{self.attribute.name}: {self.value}"

    def clean(self):
        """Normalize option value format"""
        self.value = self.value.strip()
        super().clean()


# --------------------------
# Product Core
# --------------------------
class Product(BaseModel):
    """Central product model with variant support"""
    DISCOUNT_TYPE_CHOICES = [
        ('none', _('No Discount')),
        ('fixed', _('Fixed Amount')),
        ('percentage', _('Percentage')),
    ]

    # Identification
    name = models.CharField(
        _("Product Name"),
        max_length=255,
        db_index=True,
        help_text=_("Full product name")
    )
    slug = models.SlugField(
        _("URL Slug"),
        unique=True,
        help_text=_("Unique product URL identifier")
    )
    sku = models.CharField(
        _("SKU"),
        max_length=50,
        unique=True,
        db_index=True,
        help_text=_("Base stock keeping unit")
    )
    description = models.TextField(
        _("Description"),
        help_text=_("Detailed product description")
    )
    category = models.ForeignKey(
        ProductCategory,
        on_delete=models.SET_NULL,
        null=True,
        related_name='products',
        verbose_name=_("Category")
    )

    # Pricing
    original_price = MoneyField(
        _("Original Price"),
        max_digits=14,
        decimal_places=2,
        default_currency=settings.DEFAULT_CURRENCY,
        help_text=_("Manufacturer's suggested price")
    )
    selling_price = MoneyField(
        _("Selling Price"),
        max_digits=14,
        decimal_places=2,
        default_currency=settings.DEFAULT_CURRENCY,
        help_text=_("Base price before discounts")
    )
    final_price = MoneyField(
        _("Final Price"),
        max_digits=14,
        decimal_places=2,
        default_currency=settings.DEFAULT_CURRENCY,
        editable=False,
        help_text=_("Calculated price after discounts")
    )
    discount_type = models.CharField(
        _("Discount Type"),
        max_length=10,
        choices=DISCOUNT_TYPE_CHOICES,
        default='none'
    )
    discount_amount = MoneyField(
        _("Discount Amount"),
        max_digits=14,
        decimal_places=2,
        default_currency=settings.DEFAULT_CURRENCY,
        default=Money(0, settings.DEFAULT_CURRENCY),
        null=True,
        blank=True,
        help_text=_("Fixed amount discount")
    )
    discount_percent = models.DecimalField(
        _("Discount Percentage"),
        max_digits=5,
        decimal_places=2,
        default=0.0,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(99.99)],
        help_text=_("Percentage discount")
    )

    # Variant Configuration
    has_variants = models.BooleanField(
        _("Has Variants"),
        default=False,
        db_index=True,
        help_text=_("Enable product variants")
    )
    attributes = models.ManyToManyField(
        ProductAttribute,
        related_name='products',
        blank=True,
        verbose_name=_("Variant Attributes"),
        help_text=_("Attributes defining variants")
    )

    # Status
    is_featured = models.BooleanField(
        _("Featured"),
        default=False,
        db_index=True,
        help_text=_("Feature in prominent areas")
    )
    is_active = models.BooleanField(
        _("Active"),
        default=True,
        db_index=True,
        help_text=_("Product visibility")
    )

    # Ratings
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

    class Meta:
        verbose_name = _("Product")
        verbose_name_plural = _("Products")
        ordering = ['-created_at']
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
    
    def validate_currency(self, field_name, value):
        if value.currency != settings.DEFAULT_CURRENCY:
            raise ValidationError({
                field_name: _("Currency must be %(currency)s") % {
                    'currency': settings.DEFAULT_CURRENCY
                }
            })
        
    def clean(self):
        """Validate pricing logic and discount calculations"""
        super().clean()
        
        # Validate base price
        if self.selling_price.amount <= 0:
            raise ValidationError({'selling_price': _("Price must be greater than 0")})

        # Validate discount configuration
        if self.discount_type != 'none':
            if self.discount_type == 'fixed' and not self.discount_amount:
                raise ValidationError({'discount_amount': _("Required for fixed discount")})
            if self.discount_type == 'percentage' and not self.discount_percent:
                raise ValidationError({'discount_percent': _("Required for percentage discount")})

        # Calculate final price with proper money handling
        if self.discount_type == 'none':
            self.final_price = self.selling_price
        elif self.discount_type == 'fixed':
            if self.discount_amount.currency != self.selling_price.currency:
                raise ValidationError(_("Currency mismatch between price and discount"))
            self.final_price = self.selling_price - self.discount_amount
        elif self.discount_type == 'percentage':
            discount = self.selling_price * (Decimal(self.discount_percent) / Decimal(100))
            self.final_price = self.selling_price - discount

        # Validate final price integrity
        if self.final_price.amount <= 0:
            raise ValidationError(_("Final price must be greater than 0"))
        if self.final_price > self.selling_price:
            raise ValidationError(_("Final price cannot exceed original selling price"))
        
        self.validate_currency('discount_amount', self.discount_amount)

    def save(self, *args, **kwargs):
        """Handle product deactivation cascading to variants"""
        if self.pk:
            original = Product.objects.get(pk=self.pk)
            if not original.is_active and self.is_active:  # Reactivation case
                self.variants.update(is_active=True)
        super().save(*args, **kwargs)

    def update_rating_stats(self):
        """Recalculate rating aggregates from approved reviews"""
        stats = self.reviews.filter(is_approved=True).aggregate(
            average=Avg('rating'),
            count=Count('id')
        )
        self.average_rating = stats.get('average') or 0.0
        self.review_count = stats.get('count') or 0
        self.save(update_fields=['average_rating', 'review_count'])

        
    def get_available_variants(self):
        """Simplified variant availability check"""
        return self.variants.filter(
            is_active=True,
            inventory__stock_quantity__gt=0
        ).select_related('inventory')  # Add this

    @property
    def has_discount(self):
        """Check if any discount is applied"""
        return self.discount_type != 'none'

    @property
    def discount_value(self):
        """Get formatted discount value for display"""
        if self.discount_type == 'fixed':
            return self.discount_amount
        if self.discount_type == 'percentage':
            return f"{self.discount_percent}%"
        return None


# --------------------------
# Variant System
# --------------------------
class ProductVariant(BaseModel):
    """Concrete product variant implementation"""
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='variants',
        verbose_name=_("Parent Product")
    )
    sku = models.CharField(
        _("Variant SKU"),
        max_length=50,
        unique=True,
        db_index=True,
        help_text=_("Unique variant identifier")
    )
    options = models.ManyToManyField(
        ProductOption,
        related_name='variants',
        verbose_name=_("Selected Options"),
        help_text=_("Chosen attribute values")
    )
    price_modifier = MoneyField(
        _("Price Modifier"),
        max_digits=14,
        decimal_places=2,
        default=Money(0, settings.DEFAULT_CURRENCY),
        default_currency=settings.DEFAULT_CURRENCY,
        help_text=_("Price adjustment from base")
    )
    is_default = models.BooleanField(
        _("Default Variant"),
        default=False,
        help_text=_("Primary display variant")
    )
    is_active = models.BooleanField(
        _("Active"),
        default=True,
        db_index=True,
        help_text=_("Variant visibility")
    )

    class Meta:
        verbose_name = _("Product Variant")
        verbose_name_plural = _("Product Variants")
        unique_together = ('product', 'sku')
        indexes = [
            models.Index(fields=['sku', 'is_active']),
            models.Index(fields=['is_default']),
            models.Index(fields=['is_active']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['product', 'options'],
                name='unique_variant_options'
            )
        ]

    def __str__(self):
        return f"{self.product.name} - {self.get_variant_name()}"

    def get_variant_name(self):
        """Generate display name from selected options"""
        return " / ".join(
            f"{opt.attribute.name}: {opt.value}" 
            for opt in self.options.all().order_by('attribute__name')
        )

    def clean(self):
        """Validate variant configuration integrity"""
        super().clean()
        
        # Skip validation if product is not saved
        if not self.product_id:
            return
        
        # Validate attribute membership
        product_attrs = set(self.product.attributes.values_list('id', flat=True))
        variant_attrs = {opt.attribute.id for opt in self.options.all()}
        
        if variant_attrs - product_attrs:
            raise ValidationError(_("Variant contains attributes not defined for product"))

        # Validate required attributes
        missing_attrs = self.product.attributes.filter(
            is_required=True
        ).exclude(
            id__in=variant_attrs
        ).values_list('name', flat=True)
        
        if missing_attrs:
            raise ValidationError(
                _("Missing required attributes: %(attrs)s") % {'attrs': ", ".join(missing_attrs)}
            )

        # Validate price modifier currency
        if self.price_modifier.currency != self.product.selling_price.currency:
            raise ValidationError(_("Price modifier currency must match product currency"))

        # Validate final variant price
        if (self.product.selling_price + self.price_modifier).amount <= 0:
            raise ValidationError(_("Variant price must be greater than 0"))

    @property
    def final_price(self):
        """Calculate final price including modifier"""
        return self.product.final_price + self.price_modifier




# --------------------------
# Inventory Management
# --------------------------
class Inventory(models.Model):
    """Variant-specific inventory tracking without reservations"""
    variant = models.OneToOneField(
        ProductVariant,
        on_delete=models.CASCADE,
        related_name='inventory',
        primary_key=True,
        help_text=_("Linked variant")
    )
    stock_quantity = models.PositiveIntegerField(
        _("Total Stock"),
        default=0,
        validators=[MinValueValidator(0)],
        help_text=_("Physical inventory count")
    )
    low_stock_threshold = models.PositiveIntegerField(
        _("Low Stock Alert"),
        default=5,
        help_text=_("Restock trigger level")
    )
    last_restock = models.DateTimeField(
        _("Last Restock"),
        auto_now_add=True,  # Automatically set on first save
        null=True,
        blank=True
    )

    class Meta:
        verbose_name = _("Inventory")
        verbose_name_plural = _("Inventory Records")

    def __str__(self):
        return f"Inventory for {self.variant}"

    @property
    def needs_restock(self):
        """Check if stock needs replenishment"""
        return self.stock_quantity <= self.low_stock_threshold

    @property
    def available_stock(self):
        """Direct stock quantity without reservations"""
        return self.stock_quantity

    def stock_status(self):
        """Human-readable stock status"""
        if self.available_stock <= 0:
            return "Out of Stock"
        elif self.needs_restock:
            return "Low Stock"
        return "In Stock"


# --------------------------
# Inventory History
# --------------------------

class InventoryHistory(models.Model):
    inventory = models.ForeignKey(Inventory, on_delete=models.CASCADE, related_name='history')
    old_stock = models.IntegerField(_("Previous Stock"))
    new_stock = models.IntegerField(_("New Stock"))
    timestamp = models.DateTimeField(_("Change Time"), auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name = _("Inventory History")


# --------------------------
# Product Media
# --------------------------
@cleanup.select
class ProductImage(BaseModel):
    """Product imagery with processing and validation"""
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='images',
        null=True,
        blank=True,
        help_text=_("General product images")
    )
    variant = models.ForeignKey(
        ProductVariant,
        on_delete=models.CASCADE,
        related_name='images',
        null=True,
        blank=True,
        help_text=_("Variant-specific images")
    )
    image = ProcessedImageField(
        verbose_name=_("Product Image"),
        upload_to=product_image_path,
        processors=[
            Transpose(),
            ResizeToFit(ProductImageConfig.MAX_DIMENSION, ProductImageConfig.MAX_DIMENSION)
        ],
        format='WEBP',
        options={'quality': ProductImageConfig.QUALITY},
        validators=[ProductImageValidator()],
        help_text=_("High-quality product image")
    )
    is_primary = models.BooleanField(
        _("Primary Image"),
        default=False,
        help_text=_("Main display image")
    )
    sort_order = models.PositiveIntegerField(
        _("Sort Order"),
        default=0,
        help_text=_("Display priority (lower first)")
    )
    caption = models.CharField(
        _("Caption"),
        max_length=255,
        blank=True,
        help_text=_("Accessibility description")
    )

    class Meta:
        ordering = ['-is_primary', 'sort_order']
        constraints = [
            models.UniqueConstraint(
                fields=['product', 'image'],
                name='unique_product_image',
                condition=Q(variant__isnull=True)
            ),
            models.UniqueConstraint(
                fields=['variant', 'image'],
                name='unique_variant_image',
                condition=Q(product__isnull=True)
            )
        ]
        verbose_name = _("Product Image")
        verbose_name_plural = _("Product Images")

    def __str__(self):
        return _("Image for %(target)s") % {'target': self.product or self.variant}

    def clean(self):
        """Validate media relationships"""
        if not (self.product or self.variant):
            raise ValidationError(_("Must link to a product or variant"))
        if self.product and self.variant:
            raise ValidationError(_("Cannot link to both product and variant"))

    def save(self, *args, **kwargs):
        """Atomic update to prevent multiple primary images"""
        if self.is_primary:
            with transaction.atomic():
                target = self.product or self.variant
                target.images.select_for_update().exclude(pk=self.pk).update(is_primary=False)
        super().save(*args, **kwargs)


# --------------------------
# Reviews & Ratings
# --------------------------
class ProductReview(BaseModel):
    """User-submitted product reviews"""
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='reviews',
        verbose_name=_("Product")
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='reviews',
        verbose_name=_("User")
    )
    rating = models.PositiveSmallIntegerField(
        _("Rating"),
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text=_("1 (Poor) to 5 (Excellent)")
    )
    title = models.CharField(
        _("Review Title"),
        max_length=255,
        help_text=_("Brief summary")
    )
    comment = models.TextField(
        _("Review Comment"),
        help_text=_("Detailed feedback")
    )
    is_approved = models.BooleanField(
        _("Approved"),
        default=False,
        db_index=True,
        help_text=_("Public visibility")
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
            models.Index(fields=['rating', 'is_approved']),
        ]

    def __str__(self):
        return _("%(user)s's review of %(product)s") % {
            'user': self.user.get_short_name(),
            'product': self.product.name
        }

    def approve(self):
        """Approve review and update product stats"""
        self.is_approved = True
        self.save()
