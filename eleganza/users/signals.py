import logging
from datetime import timedelta
from io import BytesIO
from uuid import uuid4
from django.db import models
from django.db.models import F, Sum
from django.db.models.signals import (
    pre_save,
    post_save,
    pre_delete
)
from django.dispatch import receiver
from django.core.files.base import ContentFile
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from PIL import Image

from .models import (
    User,
    CustomerProfile,
    TeamMemberProfile,
    OrderItem,
    Payment,
    ProductImage,
    ShoppingCart,
    Order,
    ProfitAllocation,
    PasswordHistory
)
from .validators import AvatarConfig

logger = logging.getLogger(__name__)

# region User Signals
@receiver(post_save, sender=User)
def handle_user_creation(sender, instance, created, **kwargs):
    """
    Create associated profile and shopping cart when a new user is created.
    Handles both Customer and Team Member profile types.
    """
    try:
        if created:
            if instance.type == User.Types.CUSTOMER:
                CustomerProfile.objects.create(user=instance)
                ShoppingCart.objects.create(customer=instance)
                logger.info(f"Created customer profile and cart for {instance.username}")
            elif instance.type == User.Types.TEAM_MEMBER:
                TeamMemberProfile.objects.create(user=instance)
                logger.info(f"Created team member profile for {instance.username}")
    except Exception as e:
        logger.error(f"Failed to create user profiles for {instance.username}: {str(e)}")
        raise ValidationError(
            _("User profile creation failed. Please contact support.")
        ) from e

@receiver(pre_save, sender=User)
def handle_user_soft_deletion(sender, instance, **kwargs):
    """
    Anonymize user data and handle related entities during soft deletion.
    - Cancels active orders
    - Anonymizes username
    - Disables authentication
    """
    if not instance.pk or instance._state.adding:
        return

    try:
        original = User.objects.get(pk=instance.pk)
        if original.deleted_at is None and instance.deleted_at is not None:
            # Anonymization
            instance.username = f"deleted_user_{instance.pk}"
            instance.set_unusable_password()
            instance.is_active = False
            
            # Cancel active orders
            instance.orders.filter(
                status__in=[Order.Status.PENDING, Order.Status.RESERVED]
            ).update(status=Order.Status.CANCELLED)
            logger.info(f"Soft-deleted user {original.username}")
            
    except User.DoesNotExist:
        logger.warning(f"Attempted to handle non-existent user {instance.pk}")
        pass
# endregion

# region Profile Signals
@receiver(pre_save, sender=CustomerProfile)
@receiver(pre_save, sender=TeamMemberProfile)
def process_profile_avatar(sender, instance, **kwargs):
    """
    Convert uploaded avatars to WEBP format:
    - Maintains consistent image format
    - Optimizes file size
    - Handles transparency conversion
    """
    if not instance.avatar:
        return

    # Skip processing if already in WEBP format
    current_ext = instance.avatar.name.split('.')[-1].lower()
    if current_ext == AvatarConfig.OUTPUT_EXTENSION:
        return

    try:
        with Image.open(instance.avatar) as img:
            # Convert RGBA/LA to RGB for WEBP compatibility
            if img.mode in ('RGBA', 'LA'):
                img = img.convert('RGB')

            # Optimize WEBP conversion
            buffer = BytesIO()
            img.save(
                buffer,
                format='WEBP',
                quality=85,  # Optimal quality/size balance
                method=6,    # Default compression method
                lossless=False
            )
            buffer.seek(0)

            # Generate unique filename
            new_name = f"{uuid4()}.{AvatarConfig.OUTPUT_EXTENSION}"
            instance.avatar.save(
                new_name,
                ContentFile(buffer.getvalue()),
                save=False
            )
            logger.debug(f"Converted avatar for {instance.user.username} to WEBP")

    except Exception as e:
        logger.error(f"Avatar conversion failed for {instance.user}: {str(e)}")
        instance.avatar = None
        raise ValidationError(
            _("Image processing failed. Please try another file.")
        ) from e

@receiver(post_save, sender=User)
def update_user_profile(sender, instance, **kwargs):
    """Ensure profile updates are saved when user is updated"""
    if hasattr(instance, 'profile'):
        instance.profile.save()
        logger.debug(f"Updated profile for {instance.username}")
# endregion

# region Password Security Signals
@receiver(post_save, sender=User)
def manage_password_history(sender, instance, created, **kwargs):
    """
    Maintain password history for security compliance:
    - Stores password hashes
    - Enforces history limits
    - Handles initial password creation
    """
    try:
        if created:
            PasswordHistory.objects.create(
                user=instance,
                password_hash=instance.password
            )
            logger.info(f"Initial password stored for {instance.username}")
        else:
            # Enforce password history retention policy
            history = instance.password_history.order_by('-created_at')
            
            # Count-based retention
            if history.count() > settings.PASSWORD_HISTORY_LIMIT:
                keep_ids = history.values_list('pk', flat=True)[:settings.PASSWORD_HISTORY_LIMIT]
                deleted_count = instance.password_history.exclude(pk__in=keep_ids).delete()[0]
                logger.debug(f"Pruned {deleted_count} old passwords for {instance.username}")
            
            # Time-based retention (optional)
            if hasattr(settings, 'PASSWORD_REUSE_TIMEDELTA'):
                cutoff = timezone.now() - settings.PASSWORD_REUSE_TIMEDELTA
                deleted_count = instance.password_history.filter(
                    created_at__lt=cutoff
                ).delete()[0]
                logger.debug(f"Pruned {deleted_count} expired passwords for {instance.username}")
                
    except Exception as e:
        logger.error(f"Password history management failed for {instance.username}: {str(e)}")
        raise

@receiver(pre_save, sender=User)
def enforce_password_policy(sender, instance, **kwargs):
    """
    Enforce password security policies:
    - Prevent password reuse
    - Validate against historical hashes
    """
    if not instance.pk or instance._password is None:
        return

    try:
        original = User.objects.get(pk=instance.pk)
        if original.password == instance.password:
            return  # No password change detected
    except User.DoesNotExist:
        return

    try:
        # Build historical hash query
        queryset = instance.password_history.all()
        
        # Apply time-based filtering if configured
        if hasattr(settings, 'PASSWORD_REUSE_TIMEDELTA'):
            cutoff = timezone.now() - settings.PASSWORD_REUSE_TIMEDELTA
            queryset = queryset.filter(created_at__gte=cutoff)
        
        # Get relevant historical hashes
        existing_hashes = queryset.order_by('-created_at') \
            .values_list('password_hash', flat=True)[:settings.PASSWORD_HISTORY_LIMIT]

        if instance.password in existing_hashes:
            logger.warning(f"Password reuse attempt detected for {instance.username}")
            raise ValidationError({
                'password': _("You cannot reuse your previous %(limit)d passwords") % {
                    'limit': settings.PASSWORD_HISTORY_LIMIT
                }
            })

        # Store previous password in history
        PasswordHistory.objects.create(
            user=instance,
            password_hash=original.password
        )
        logger.info(f"Updated password history for {instance.username}")

    except Exception as e:
        logger.error(f"Password policy enforcement failed for {instance.username}: {str(e)}")
        raise
# endregion

# region Order Management Signals
@receiver(pre_save, sender=OrderItem)
def validate_inventory(sender, instance, **kwargs):
    """
    Ensure sufficient stock before creating order items:
    - Checks available inventory
    - Prevents over-selling
    """
    if not instance.pk:  # New order item only
        if instance.quantity > instance.product.available_stock:
            logger.error(f"Insufficient stock for {instance.product.sku}")
            raise ValidationError({
                'quantity': _("Only %(available)s units available for %(product)s") % {
                    'available': instance.product.available_stock,
                    'product': instance.product.name
                }
            })

@receiver(post_save, sender=OrderItem)
def update_inventory(sender, instance, created, **kwargs):
    """
    Maintain real-time inventory tracking:
    - Updates reserved stock on order creation
    - Handles inventory adjustments
    """
    if created:
        try:
            product = instance.product
            product.reserved_stock += instance.quantity
            product.save(update_fields=['reserved_stock'])
            logger.info(f"Reserved {instance.quantity} units of {product.sku}")
        except Exception as e:
            logger.error(f"Inventory update failed for {instance.product.sku}: {str(e)}")
            raise
# endregion

# region Payment Processing Signals
@receiver(post_save, sender=Payment)
def handle_payment_fulfillment(sender, instance, **kwargs):
    """
    Complete order fulfillment and profit allocation:
    - Updates order status
    - Calculates profit distribution
    - Handles team member allocations
    """
    if instance.status == 'completed':
        try:
            order = instance.order
            order.status = Order.Status.COMPLETED
            order.save(update_fields=['status'])
            logger.info(f"Completed order #{order.id}")

            # Calculate total profit with aggregation
            total_profit = order.items.aggregate(
                total_profit=Sum(
                    (models.F('price') - models.F('product__original_price')) *
                    models.F('quantity')
                )
            )['total_profit'] or 0

            if total_profit > 0:
                active_members = TeamMemberProfile.objects.filter(
                    user__is_active=True
                ).select_related('user')
                total_percentage = sum(m.profit_percentage for m in active_members)

                if total_percentage > 0:
                    for member in active_members:
                        allocation = (total_profit * member.profit_percentage) / total_percentage
                        ProfitAllocation.objects.create(
                            order=order,
                            team_member=member.user,
                            amount=allocation
                        )
                    logger.info(f"Allocated profits for order #{order.id}")

        except Exception as e:
            logger.error(f"Payment processing failed for order #{instance.order.id}: {str(e)}")
            instance.status = 'failed'
            instance.save(update_fields=['status'])
            raise
# endregion

# region Product Signals
@receiver(post_save, sender=ProductImage)
def manage_primary_image(sender, instance, **kwargs):
    """
    Maintain single primary image per product:
    - Automatically demotes previous primary images
    - Ensures consistent primary image selection
    """
    if instance.is_primary:
        try:
            ProductImage.objects.filter(
                product=instance.product
            ).exclude(pk=instance.pk).update(is_primary=False)
            logger.debug(f"Updated primary image for {instance.product.sku}")
        except Exception as e:
            logger.error(f"Primary image update failed for {instance.product.sku}: {str(e)}")
            raise
# endregion