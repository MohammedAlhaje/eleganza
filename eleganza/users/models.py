# models.py
import uuid
from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db.models import Q, Sum, Avg, F
from django.db.models.signals import pre_save, post_save, pre_delete
from django.dispatch import receiver
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from phonenumber_field.modelfields import PhoneNumberField
from django.conf import settings
from djmoney.models.fields import CurrencyField
from djmoney.settings import CURRENCY_CHOICES
from timezone_field import TimeZoneField
from django_countries.fields import CountryField
from .validators import (
    rename_avatar, 
    validate_avatar, 
    get_file_extension_validator
)

# region Soft Delete Implementation
class SoftDeleteQuerySet(models.QuerySet):
    """Custom QuerySet supporting soft delete operations"""
    def delete(self):
        """Soft delete - set deleted_at timestamp"""
        return self.update(deleted_at=timezone.now())

    def hard_delete(self):
        """Permanent deletion"""
        return super().delete()

    def alive(self):
        """Return only non-deleted items"""
        return self.filter(deleted_at__isnull=True)

    def dead(self):
        """Return only deleted items"""
        return self.filter(deleted_at__isnull=False)

class SoftDeleteManager(models.Manager):
    """Custom manager supporting soft delete filtering"""
    def __init__(self, *args, **kwargs):
        self.alive_only = kwargs.pop('alive_only', True)
        super().__init__(*args, **kwargs)

    def get_queryset(self):
        if self.alive_only:
            return SoftDeleteQuerySet(self.model).filter(deleted_at__isnull=True)
        return SoftDeleteQuerySet(self.model)

    def hard_delete(self):
        """Bypass soft delete for manager operations"""
        return self.get_queryset().hard_delete()

class SoftDeleteModel(models.Model):
    """
    Abstract model providing soft delete functionality with:
    - deleted_at timestamp field
    - default manager that filters out deleted instances
    - delete()/restore() methods
    - QuerySet with delete/hard_delete methods
    """
    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
        verbose_name=_("Deleted At"),
        help_text=_("Timestamp when object was soft-deleted")
    )

    objects = SoftDeleteManager()
    all_objects = SoftDeleteManager(alive_only=False)

    class Meta:
        abstract = True
        indexes = [
            models.Index(fields=['deleted_at'])
        ]

    def delete(self, using=None, keep_parents=False):
        """Soft delete implementation"""
        self.deleted_at = timezone.now()
        self.save(update_fields=['deleted_at'])

    def restore(self):
        """Restore a soft-deleted instance"""
        self.deleted_at = None
        self.save(update_fields=['deleted_at'])

    def hard_delete(self):
        """Permanent deletion"""
        super().delete()

    @property
    def is_deleted(self):
        """Check if instance is soft-deleted"""
        return self.deleted_at is not None

# endregion

class UserManager(BaseUserManager):
    """Custom user manager with soft delete awareness"""
    def create_user(self, username, password=None, **extra_fields):
        """Create user with proper soft delete handling"""
        extra_fields.setdefault('type', User.Types.CUSTOMER)
        return super().create_user(username, password, **extra_fields)

    def create_superuser(self, username, password=None, **extra_fields):
        """Create superuser with team member type"""
        extra_fields.setdefault('type', User.Types.TEAM_MEMBER)
        return super().create_superuser(username, password, **extra_fields)

    def get_queryset(self):
        """Exclude soft-deleted users by default"""
        return SoftDeleteQuerySet(self.model).filter(deleted_at__isnull=True)

class User(AbstractUser, SoftDeleteModel):
    """
    Custom user model supporting soft delete and different user types.
    Inherits from SoftDeleteModel for soft deletion capabilities.
    """
    class Types(models.TextChoices):
        CUSTOMER = "CUSTOMER", _("Customer")
        TEAM_MEMBER = "TEAM_MEMBER", _("Team Member")

    type = models.CharField(
        _("User Type"),
        max_length=50,
        choices=Types.choices,
        default=Types.CUSTOMER,
        db_index=True
    )
    email = models.EmailField(
        _("email address"), 
        blank=True, 
        null=True,  # Compatible with allauth
        unique=True,
        error_messages={
            'unique': _("A user with that email already exists."),
        }
    )
    objects = UserManager()

    class Meta:
        verbose_name = _("User")
        verbose_name_plural = _("Users")
        indexes = [
            models.Index(fields=['username']),
            models.Index(fields=['type']),
            models.Index(fields=['email']),
        ]

    def __str__(self):
        return self.username

    def delete(self, *args, **kwargs):
        """Handle user soft deletion with related data cleanup"""
        # Cancel active orders before deletion using string status values
        self.orders.filter(
            status__in=['pending', 'reserved']
        ).update(status='cancelled')
        super().delete(*args, **kwargs)

class UserProfile(models.Model):
    """
    Abstract base profile model shared by all user types.
    Contains common fields for both customers and team members.
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='%(class)s_profile',
        verbose_name=_("User")
    )
    phone = PhoneNumberField(
        _("Phone Number"),
        unique=False,
        blank=True,
        null=True,
        help_text=_("User's phone number in international format (e.g. +12125552368)")
    )
    is_phone_verified = models.BooleanField(
        _("Phone Verified"),
        default=False,
        help_text=_("Flag indicating if the user's phone number has been verified")
    )

    # Consent Management
    data_consent = models.BooleanField(
        _("Data Consent"),
        default=False,
        help_text=_("Consent for data processing under privacy regulations")
    )
    data_consent_at = models.DateTimeField(
        _("Data Consent Date"),
        blank=True,
        null=True,
        help_text=_("Timestamp when data consent was given")
    )
    marketing_consent = models.BooleanField(
        _("Marketing Consent"),
        default=False,
        help_text=_("Consent to receive marketing communications")
    )
    marketing_consent_at = models.DateTimeField(
        _("Marketing Consent Date"),
        blank=True,
        null=True,
        help_text=_("Timestamp when marketing consent was given")
    )

    # Preferences
    timezone = TimeZoneField(
        _("Timezone"),
        default='UTC',
        help_text=_("User's preferred timezone for system interactions")
    )
    language = models.CharField(
        _("Language"),
        max_length=10,
        default='en',
        choices=settings.LANGUAGES,
        help_text=_("User's preferred interface language (ISO 639-1 code)")
    )
    default_currency = CurrencyField(
        _("Default Currency"),
        default='USD',
        choices=CURRENCY_CHOICES,
        help_text=_("Preferred currency for transactions and pricing")
    )

    # Security
    failed_login_attempts = models.PositiveIntegerField(
        _("Failed Login Attempts"),
        default=0,
        help_text=_("Count of consecutive failed login attempts")
    )
    locked_until = models.DateTimeField(
        _("Locked Until"),
        blank=True,
        null=True,
        help_text=_("Timestamp when account lock expires")
    )
    password_updated_at = models.DateTimeField(
        _("Password Updated At"),
        blank=True,
        null=True,
        help_text=_("Timestamp of last password change")
    )

    # Profile Information
    date_of_birth = models.DateField(
        _("Date of Birth"),
        blank=True,
        null=True,
        help_text=_("Birth date for age verification purposes")
    )
    avatar = models.ImageField(
        _("Avatar"),
        upload_to=rename_avatar,
        blank=True,
        null=True,
        default="avatars/default.webp",
        validators=[validate_avatar, get_file_extension_validator()],
        help_text=_("Profile image. Allowed formats: JPG/PNG/WEBP. Max size: 2MB")
    )

    # Timestamps
    created_at = models.DateTimeField(_("Created At"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)

    class Meta:
        abstract = True
        verbose_name = _("User Profile")
        verbose_name_plural = _("User Profiles")

    def __str__(self):
        return _("%(username)s's Profile") % {'username': self.user.username}

class CustomerProfile(UserProfile):
    """
    Customer-specific profile extensions including:
    - Preferred contact method
    - Loyalty program points
    - Shopping preferences
    """
    PREFERRED_CONTACT_CHOICES = [
        ('email', _("Email")),
        ('phone', _("Phone")),
        ('social', _("Social Media"))
    ]

    preferred_contact_method = models.CharField(
        _("Preferred Contact Method"),
        max_length=20,
        choices=PREFERRED_CONTACT_CHOICES,
        default='phone',
        help_text=_("Primary method for order notifications and communications")
    )
    loyalty_points = models.PositiveIntegerField(
        _("Loyalty Points"),
        default=0,
        help_text=_("Accumulated points in customer loyalty program")
    )

    class Meta:
        verbose_name = _("Customer Profile")
        verbose_name_plural = _("Customer Profiles")

    @property
    def wishlist_items(self):
        """Get all items in customer's wishlist"""
        return self.wishlist.select_related('product')

    @property
    def active_cart(self):
        """Get the user's active shopping cart"""
        return self.user.cart.prefetch_related('items__product')

class TeamMemberProfile(UserProfile):
    """
    Team member profile with department assignment
    and profit sharing percentage.
    """
    DEPARTMENT_CHOICES = [
        ('sales', _("Sales")),
        ('support', _("Customer Support")),
        ('warehouse', _("Warehouse")),
        ('management', _("Management"))
    ]

    department = models.CharField(
        _("Department"),
        max_length=20,
        choices=DEPARTMENT_CHOICES,
        default='sales',
        db_index=True,
        help_text=_("Department assignment for role-based access")
    )
    profit_percentage = models.DecimalField(
        _("Profit Percentage"),
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text=_("Percentage of order profits allocated to this team member")
    )

    class Meta:
        verbose_name = _("Team Member Profile")
        verbose_name_plural = _("Team Member Profiles")

    def clean(self):
        """Validate total profit percentages don't exceed 100%"""
        super().clean()
        if not self.pk:  # New instance
            total = TeamMemberProfile.objects.aggregate(
                total=Sum('profit_percentage')
            )['total'] or 0
            if total + self.profit_percentage > 100:
                raise ValidationError(
                    _("Total profit percentage across all team members cannot exceed 100%")
                )

class PasswordHistory(models.Model):
    """
    Tracks historical password hashes to prevent password reuse.
    Related to :model:`User`
    """
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='password_history',
        verbose_name=_("User")
    )
    password_hash = models.CharField(
        _("Password Hash"),
        max_length=255,
        help_text=_("Hashed representation of the password")
    )
    created_at = models.DateTimeField(
        _("Created At"),
        auto_now_add=True,
        help_text=_("Timestamp when password was set")
    )

    class Meta:
        verbose_name = _("Password History")
        verbose_name_plural = _("Password Histories")
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
        ]

    def __str__(self):
        return _("Password history for %(user)s at %(time)s") % {
            'user': self.user.username,
            'time': self.created_at.strftime("%Y-%m-%d %H:%M")
        }

class Address(models.Model):
    """
    Customer shipping/billing address information.
    Related to :model:`User`
    """
    customer = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='addresses',
        limit_choices_to={'type': User.Types.CUSTOMER},
        verbose_name=_("Customer")
    )
    street = models.CharField(
        _("Street Address"),
        max_length=255,
        help_text=_("Street name and number")
    )
    city = models.CharField(
        _("City"),
        max_length=100,
        help_text=_("City or locality name")
    )
    postal_code = models.CharField(
        _("Postal Code"),
        max_length=20,
        help_text=_("Postal or ZIP code")
    )
    country = CountryField(
        _("Country"),
        help_text=_("Country code (ISO 3166-1 alpha-2)")
    )
    is_primary = models.BooleanField(
        _("Primary Address"),
        default=False,
        help_text=_("Mark as default shipping/billing address")
    )

    class Meta:
        verbose_name = _("Address")
        verbose_name_plural = _("Addresses")
        ordering = ['-is_primary']
        unique_together = ('customer', 'street', 'city', 'postal_code')
        indexes = [
            models.Index(fields=['customer', 'is_primary']),
        ]

    def save(self, *args, **kwargs):
        """Ensure only one primary address per customer"""
        if self.is_primary:
            self.customer.addresses.exclude(pk=self.pk).update(is_primary=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.street}, {self.city}, {self.country.code}"

class ProductCategory(models.Model):
    """
    Hierarchical product category system with slug-based URLs.
    Supports nested categories through parent-child relationships.
    """
    name = models.CharField(
        _("Category Name"),
        max_length=100,
        unique=True,
        help_text=_("Display name for product category")
    )
    parent = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='children',
        verbose_name=_("Parent Category"),
        help_text=_("Parent category for nested hierarchies")
    )
    slug = models.SlugField(
        _("Slug"),
        unique=True,
        max_length=150,
        help_text=_("URL-friendly identifier (auto-generated)")
    )
    description = models.TextField(
        _("Description"),
        blank=True,
        help_text=_("Detailed category description for SEO and filtering")
    )

    class Meta:
        verbose_name = _("Product Category")
        verbose_name_plural = _("Product Categories")
        ordering = ['name']
        indexes = [
            models.Index(fields=['slug']),
            models.Index(fields=['parent']),
        ]

    def __str__(self):
        return self.name

class Product(SoftDeleteModel):
    """
    Core product model with inventory tracking and pricing.
    Inherits soft delete capabilities from SoftDeleteModel.
    """
    sku = models.CharField(
        _("SKU"),
        max_length=50,
        unique=True,
        help_text=_("Stock Keeping Unit (unique product identifier)")
    )
    name = models.CharField(
        _("Product Name"),
        max_length=255,
        db_index=True,
        help_text=_("Public-facing product name")
    )
    description = models.TextField(
        _("Description"),
        help_text=_("Detailed product description and features")
    )
    category = models.ForeignKey(
        ProductCategory,
        on_delete=models.SET_NULL,
        null=True,
        related_name='products',
        verbose_name=_("Category"),
        help_text=_("Primary product classification")
    )
    original_price = models.DecimalField(
        _("Original Price"),
        max_digits=10,
        decimal_places=2,
        help_text=_("Manufacturer's suggested retail price (MSRP)")
    )
    selling_price = models.DecimalField(
        _("Selling Price"),
        max_digits=10,
        decimal_places=2,
        help_text=_("Actual customer-facing price")
    )
    stock_quantity = models.PositiveIntegerField(
        _("Stock Quantity"),
        default=0,
        help_text=_("Available units in inventory")
    )
    reserved_stock = models.PositiveIntegerField(
        _("Reserved Stock"),
        default=0,
        help_text=_("Units reserved in active carts/orders")
    )

    # Timestamps
    created_at = models.DateTimeField(_("Created At"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)

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
            models.UniqueConstraint(
                fields=['sku'],
                condition=Q(deleted_at__isnull=True),
                name='unique_active_sku'
            )
        ]
        indexes = [
            models.Index(fields=['sku']),
            models.Index(fields=['name']),
            models.Index(fields=['category']),
        ]

    def clean(self):
        """Validate selling price doesn't exceed original price"""
        super().clean()
        if self.selling_price > self.original_price:
            raise ValidationError(
                _("Selling price cannot exceed original price")
            )

    @property
    def available_stock(self):
        """Calculate available stock for purchase"""
        return max(self.stock_quantity - self.reserved_stock, 0)

    @property
    def average_rating(self):
        """Calculate average product rating from reviews"""
        return self.reviews.aggregate(
            avg_rating=Avg('rating')
        )['avg_rating'] or 0.0

    @property
    def primary_image(self):
        """Get the main product image for display"""
        return self.images.filter(is_primary=True).first()

    def __str__(self):
        return f"{self.name} ({self.sku})"

class ProductImage(models.Model):
    """
    Product images with primary image designation.
    Related to :model:`Product`
    """
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='images',
        verbose_name=_("Product")
    )
    image = models.ImageField(
        _("Image"),
        upload_to='products/',
        help_text=_("High-quality product image")
    )
    caption = models.CharField(
        _("Caption"),
        max_length=255,
        blank=True,
        help_text=_("Optional image description for accessibility")
    )
    is_primary = models.BooleanField(
        _("Primary Image"),
        default=False,
        help_text=_("Designate as main product image")
    )
    created_at = models.DateTimeField(_("Created At"), auto_now_add=True)

    class Meta:
        verbose_name = _("Product Image")
        verbose_name_plural = _("Product Images")
        ordering = ['-is_primary']
        indexes = [
            models.Index(fields=['product', 'is_primary']),
        ]

    def save(self, *args, **kwargs):
        """Ensure only one primary image per product"""
        if self.is_primary:
            self.product.images.exclude(pk=self.pk).update(is_primary=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return _("Image for %(product)s") % {'product': self.product.name}

class ProductReview(models.Model):
    """
    Customer product reviews with ratings.
    Related to :model:`Product` and :model:`User`
    """
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='reviews',
        verbose_name=_("Product")
    )
    customer = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        limit_choices_to={'type': User.Types.CUSTOMER},
        verbose_name=_("Customer")
    )
    rating = models.PositiveSmallIntegerField(
        _("Rating"),
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text=_("Quality rating from 1 (worst) to 5 (best)")
    )
    title = models.CharField(
        _("Review Title"),
        max_length=255,
        help_text=_("Brief summary of the review")
    )
    comment = models.TextField(
        _("Review Comment"),
        help_text=_("Detailed product feedback")
    )
    created_at = models.DateTimeField(_("Created At"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)

    class Meta:
        verbose_name = _("Product Review")
        verbose_name_plural = _("Product Reviews")
        unique_together = ('product', 'customer')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['product', 'rating']),
            models.Index(fields=['customer']),
        ]

    def __str__(self):
        return _("%(customer)s's review of %(product)s") % {
            'customer': self.customer.username,
            'product': self.product.name
        }

class Wishlist(models.Model):
    """
    Customer wishlist items.
    Related to :model:`CustomerProfile` and :model:`Product`
    """
    customer = models.ForeignKey(
        CustomerProfile,
        on_delete=models.CASCADE,
        related_name='wishlist',
        verbose_name=_("Customer")
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        verbose_name=_("Product")
    )
    added_at = models.DateTimeField(
        _("Added At"),
        auto_now_add=True,
        help_text=_("Timestamp when item was added to wishlist")
    )

    class Meta:
        verbose_name = _("Wishlist Item")
        verbose_name_plural = _("Wishlist Items")
        unique_together = ('customer', 'product')
        ordering = ['-added_at']
        indexes = [
            models.Index(fields=['customer', 'added_at']),
        ]

    def __str__(self):
        return _("%(customer)s's wishlist item: %(product)s") % {
            'customer': self.customer.user.username,
            'product': self.product.name
        }

class ShoppingCart(models.Model):
    """
    Customer shopping cart with items.
    Related to :model:`User`
    """
    customer = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='cart',
        limit_choices_to={'type': User.Types.CUSTOMER},
        verbose_name=_("Customer")
    )
    created_at = models.DateTimeField(
        _("Created At"),
        auto_now_add=True,
        help_text=_("Timestamp when cart was created")
    )
    updated_at = models.DateTimeField(
        _("Updated At"),
        auto_now=True,
        help_text=_("Timestamp of last cart modification")
    )

    class Meta:
        verbose_name = _("Shopping Cart")
        verbose_name_plural = _("Shopping Carts")
        indexes = [
            models.Index(fields=['customer']),
        ]

    @property
    def total_items(self):
        """Count of unique items in cart"""
        return self.items.count()

    @property
    def subtotal(self):
        """Calculate total cart value before taxes/shipping"""
        return self.items.aggregate(
            subtotal=Sum(F('quantity') * F('product__selling_price'))
        )['subtotal'] or 0

    def __str__(self):
        return _("%(customer)s's shopping cart") % {'customer': self.customer.username}

class CartItem(models.Model):
    """
    Individual items within a shopping cart.
    Related to :model:`ShoppingCart` and :model:`Product`
    """
    cart = models.ForeignKey(
        ShoppingCart,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name=_("Shopping Cart")
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        verbose_name=_("Product")
    )
    quantity = models.PositiveIntegerField(
        _("Quantity"),
        default=1,
        validators=[MinValueValidator(1)],
        help_text=_("Number of units to purchase")
    )
    added_at = models.DateTimeField(
        _("Added At"),
        auto_now_add=True,
        help_text=_("Timestamp when item was added to cart")
    )

    class Meta:
        verbose_name = _("Cart Item")
        verbose_name_plural = _("Cart Items")
        unique_together = ('cart', 'product')
        ordering = ['-added_at']
        indexes = [
            models.Index(fields=['cart', 'added_at']),
        ]

    @property
    def subtotal(self):
        """Calculate line item total"""
        return self.product.selling_price * self.quantity

    def __str__(self):
        return _("%(quantity)s x %(product)s in cart") % {
            'quantity': self.quantity,
            'product': self.product.name
        }

class Order(SoftDeleteModel):
    """
    Customer order with status tracking.
    Inherits soft delete capabilities from SoftDeleteModel.
    """
    class Status(models.TextChoices):
        PENDING = 'pending', _("Pending")
        RESERVED = 'reserved', _("Reserved")
        CONFIRMED = 'confirmed', _("Confirmed")
        COMPLETED = 'completed', _("Completed")
        CANCELLED = 'cancelled', _("Cancelled")

    customer = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='orders',
        limit_choices_to={'type': User.Types.CUSTOMER},
        verbose_name=_("Customer")
    )
    status = models.CharField(
        _("Order Status"),
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True
    )
    total_amount = models.DecimalField(
        _("Total Amount"),
        max_digits=10,
        decimal_places=2,
        help_text=_("Final amount including taxes and shipping")
    )
    created_at = models.DateTimeField(_("Created At"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)

    class Meta:
        verbose_name = _("Order")
        verbose_name_plural = _("Orders")
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at', 'status']),
            models.Index(fields=['customer']),
        ]

    @property
    def items(self):
        """Get all order items with product details"""
        return self.order_items.select_related('product')

    def clean(self):
        """Validate order status transitions"""
        if self.pk:
            original = Order.objects.get(pk=self.pk)
            allowed_transitions = {
                'pending': ['reserved', 'cancelled'],
                'reserved': ['confirmed', 'cancelled'],
                'confirmed': ['completed', 'cancelled'],
                'completed': [],
                'cancelled': []
            }
            if self.status not in allowed_transitions.get(original.status, []):
                raise ValidationError(
                    _("Invalid status transition from %(old)s to %(new)s") % {
                        'old': original.status,
                        'new': self.status
                    }
                )

    def __str__(self):
        return _("Order #%(id)s - %(customer)s") % {
            'id': self.id,
            'customer': self.customer.username
        }

@receiver(pre_save, sender=Order)
def calculate_order_total(sender, instance, **kwargs):
    """Calculate order total before saving"""
    if not instance.total_amount:
        instance.total_amount = instance.order_items.aggregate(
            total=Sum(F('quantity') * F('price'))
        )['total'] or 0

class OrderItem(models.Model):
    """
    Individual items within an order.
    Related to :model:`Order` and :model:`Product`
    """
    order = models.ForeignKey(
        Order,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='order_items',
        verbose_name=_("Order")
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        verbose_name=_("Product")
    )
    quantity = models.PositiveIntegerField(
        _("Quantity"),
        validators=[MinValueValidator(1)],
        help_text=_("Number of units ordered")
    )
    price = models.DecimalField(
        _("Unit Price"),
        max_digits=10,
        decimal_places=2,
        help_text=_("Price per unit at time of purchase")
    )

    class Meta:
        verbose_name = _("Order Item")
        verbose_name_plural = _("Order Items")
        indexes = [
            models.Index(fields=['order']),
        ]

    @property
    def subtotal(self):
        """Calculate line item total"""
        return self.quantity * self.price

    def __str__(self):
        return _("%(quantity)s x %(product)s") % {
            'quantity': self.quantity,
            'product': self.product.name
        }

class Payment(models.Model):
    """
    Payment transaction details for orders.
    Related to :model:`Order`
    """
    order = models.ForeignKey(
        Order,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payments',
        verbose_name=_("Order")
    )
    amount = models.DecimalField(
        _("Amount"),
        max_digits=10,
        decimal_places=2,
        help_text=_("Transaction amount processed")
    )
    transaction_id = models.CharField(
        _("Transaction ID"),
        max_length=255,
        unique=True,
        help_text=_("Payment gateway reference ID")
    )
    payment_method = models.CharField(
        _("Payment Method"),
        max_length=50,
        help_text=_("Payment processor used (e.g., Stripe, PayPal)")
    )
    status = models.CharField(
        _("Payment Status"),
        max_length=20,
        default='pending',
        choices=[
            ('pending', _("Pending")),
            ('completed', _("Completed")),
            ('failed', _("Failed")),
            ('refunded', _("Refunded"))
        ]
    )
    created_at = models.DateTimeField(_("Created At"), auto_now_add=True)

    class Meta:
        verbose_name = _("Payment")
        verbose_name_plural = _("Payments")
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['transaction_id']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return _("Payment %(id)s for Order #%(order_id)s") % {
            'id': self.transaction_id,
            'order_id': self.order.id if self.order else 'N/A'
        }

class ProfitAllocation(models.Model):
    """
    Profit distribution to team members from completed orders.
    Related to :model:`Order` and :model:`User`
    """
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='profit_allocations',
        verbose_name=_("Order")
    )
    team_member = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        limit_choices_to={'type': User.Types.TEAM_MEMBER},
        verbose_name=_("Team Member")
    )
    amount = models.DecimalField(
        _("Allocation Amount"),
        max_digits=10,
        decimal_places=2,
        help_text=_("Profit amount allocated to team member")
    )
    allocated_at = models.DateTimeField(
        _("Allocated At"),
        auto_now_add=True,
        help_text=_("Timestamp of profit allocation")
    )

    class Meta:
        verbose_name = _("Profit Allocation")
        verbose_name_plural = _("Profit Allocations")
        ordering = ['-allocated_at']
        indexes = [
            models.Index(fields=['order', 'team_member']),
        ]

    def __str__(self):
        return _("%(amount)s allocated to %(member)s") % {
            'amount': self.amount,
            'member': self.team_member.username
        }
