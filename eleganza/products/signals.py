# signals.py
import logging
from django.db import transaction
from django.db.models.signals import post_save, post_delete, pre_save, m2m_changed
from django.dispatch import receiver
from typing import Type, Any, Optional
from .models import (
    Product, 
    ProductReview, 
    ProductVariant, 
    Inventory, 
    InventoryHistory,
    ProductImage,
    ProductCategory
)

logger = logging.getLogger(__name__)

# ======================
# PRODUCT REVIEW SIGNALS
# ======================

@receiver([post_save, post_delete], sender=ProductReview)
def update_product_rating_stats(
    sender: Type[ProductReview],
    instance: ProductReview,
    **kwargs: Any
) -> None:
    """
    Optimized rating recalculation with:
    - Change detection
    - Atomic transactions
    - Error handling
    - Performance logging
    """
    # Skip if flagged to bypass (useful for bulk operations)
    if getattr(instance, '_disable_signals', False):
        return

    try:
        with transaction.atomic():
            product = instance.product
            original_rating = product.average_rating
            
            # Only recalculate if relevant fields changed
            if hasattr(instance, 'tracker') and not instance._state.adding:
                changed_fields = instance.tracker.changed()
                if not any(f in changed_fields for f in ['rating', 'is_approved']):
                    return

            product.update_rating_stats()
            
            logger.debug(
                f"Updated ratings for product {product.sku} | "
                f"Old: {original_rating} | New: {product.average_rating}"
            )
    except Exception as e:
        logger.error(
            f"Rating update failed for product {instance.product_id}: {str(e)}",
            exc_info=True
        )
        raise

# ======================
# PRODUCT VARIANT SIGNALS
# ======================

@receiver(post_save, sender=ProductVariant)
def handle_variant_changes(
    sender: Type[ProductVariant],
    instance: ProductVariant,
    created: bool,
    **kwargs: Any
) -> None:
    """
    Handle variant-related operations:
    - Auto-create inventory record
    - Update parent product's has_variants flag
    - Sync active status with parent
    """
    try:
        with transaction.atomic():
            # Create inventory record for new variants
            if created:
                Inventory.objects.get_or_create(variant=instance)
                logger.debug(f"Created inventory for new variant {instance.sku}")
            
            # Update parent product's has_variants flag
            product = instance.product
            has_variants = product.variants.exists()
            if product.has_variants != has_variants:
                product.has_variants = has_variants
                product.save(update_fields=['has_variants'])
                logger.debug(f"Updated has_variants for product {product.sku} to {has_variants}")
            
            # Sync active status with parent product
            if not instance.product.is_active and instance.is_active:
                instance.is_active = False
                instance.save(update_fields=['is_active'])
                logger.debug(f"Deactivated variant {instance.sku} due to parent product status")
                
    except Exception as e:
        logger.error(
            f"Variant signal failed for {instance.sku}: {str(e)}",
            exc_info=True
        )
        raise

# ======================
# INVENTORY SIGNALS
# ======================

@receiver(post_save, sender=Inventory)
def track_inventory_changes(
    sender: Type[Inventory],
    instance: Inventory,
    created: bool,
    **kwargs: Any
) -> None:
    """
    Track all inventory changes in InventoryHistory
    with before/after values and timestamps
    """
    try:
        if created:
            # Initial stock entry
            InventoryHistory.objects.create(
                inventory=instance,
                old_stock=0,
                new_stock=instance.stock_quantity
            )
            logger.debug(f"Initial inventory record created for {instance.variant.sku}")
        else:
            # Stock change detection
            dirty_fields = instance.get_dirty_fields()
            if 'stock_quantity' in dirty_fields:
                InventoryHistory.objects.create(
                    inventory=instance,
                    old_stock=dirty_fields['stock_quantity'],
                    new_stock=instance.stock_quantity
                )
                logger.debug(
                    f"Inventory change for {instance.variant.sku}: "
                    f"{dirty_fields['stock_quantity']} → {instance.stock_quantity}"
                )
    except Exception as e:
        logger.error(
            f"Inventory tracking failed for {instance.variant.sku}: {str(e)}",
            exc_info=True
        )
        raise

# ======================
# PRODUCT SIGNALS
# ======================

@receiver(post_save, sender=Product)
def handle_product_status_change(
    sender: Type[Product],
    instance: Product,
    **kwargs: Any
) -> None:
    """
    Cascade product status changes to variants:
    - Reactivation (if product becomes active)
    - Deactivation (if product becomes inactive)
    """
    try:
        if instance.pk:  # Only for existing products
            original = Product.objects.get(pk=instance.pk)
            if original.is_active != instance.is_active:
                instance.variants.update(is_active=instance.is_active)
                logger.debug(
                    f"Cascaded {'activation' if instance.is_active else 'deactivation'} "
                    f"to {instance.variants.count()} variants of {instance.sku}"
                )
    except Exception as e:
        logger.error(
            f"Product status sync failed for {instance.sku}: {str(e)}",
            exc_info=True
        )
        raise

@receiver(m2m_changed, sender=Product.attributes.through)
def validate_attribute_changes(
    sender: Type[Product],
    instance: Product,
    action: str,
    pk_set: set,
    **kwargs: Any
) -> None:
    """
    Validate attribute changes against existing variants:
    - Prevent removal of attributes used by variants
    - Ensure required attributes aren't removed
    """
    if action in ['pre_remove', 'pre_clear']:
        try:
            # Get attributes being removed
            removed_attrs = (instance.attributes.filter(pk__in=pk_set) 
                           if action == 'pre_remove' 
                           else instance.attributes.all())
            
            # Check if any variants use these attributes
            conflict_variants = instance.variants.filter(
                options__attribute__in=removed_attrs
            ).distinct()
            
            if conflict_variants.exists():
                variant_list = ", ".join(v.sku for v in conflict_variants[:5])
                if conflict_variants.count() > 5:
                    variant_list += f" (+{conflict_variants.count() - 5} more)"
                
                raise ValidationError(
                    _("Cannot remove attributes used by variants: %(skus)s") % 
                    {'skus': variant_list}
                )
                
        except Exception as e:
            logger.error(
                f"Attribute validation failed for product {instance.sku}: {str(e)}",
                exc_info=True
            )
            raise

# ======================
# PRODUCT IMAGE SIGNALS
# ======================

@receiver(pre_save, sender=ProductImage)
def handle_primary_image_change(
    sender: Type[ProductImage],
    instance: ProductImage,
    **kwargs: Any
) -> None:
    """
    Ensure only one primary image exists per product/variant
    Runs before save to prevent race conditions
    """
    try:
        if instance.is_primary and (instance.product or instance.variant):
            target = instance.product or instance.variant
            target.images.exclude(pk=instance.pk).update(is_primary=False)
            logger.debug(f"Updated primary image for {target}")
    except Exception as e:
        logger.error(
            f"Primary image update failed: {str(e)}",
            exc_info=True
        )
        raise

# ======================
# CATEGORY SIGNALS
# ======================

@receiver(post_save, sender=ProductCategory)
def update_category_tree(
    sender: Type[ProductCategory],
    instance: ProductCategory,
    **kwargs: Any
) -> None:
    """
    Maintain category tree integrity:
    - Rebuild MPTT tree if parent changes
    - Update product counts
    """
    try:
        # Rebuild tree if parent changed
        if hasattr(instance, '_mptt_meta'):
            if instance._mptt_fields_changed():
                ProductCategory.objects.rebuild()
                logger.debug("Rebuilt category tree after hierarchy change")
    except Exception as e:
        logger.error(
            f"Category tree update failed: {str(e)}",
            exc_info=True
        )
        raise

# ======================
# SIGNAL CONNECTIONS
# ======================

def connect_signals():
    """Explicit signal connection (alternative to @receiver)"""
    post_save.connect(update_product_rating_stats, sender=ProductReview)
    post_delete.connect(update_product_rating_stats, sender=ProductReview)
    post_save.connect(handle_variant_changes, sender=ProductVariant)
    post_save.connect(track_inventory_changes, sender=Inventory)
    post_save.connect(handle_product_status_change, sender=Product)
    m2m_changed.connect(validate_attribute_changes, sender=Product.attributes.through)
    pre_save.connect(handle_primary_image_change, sender=ProductImage)
    post_save.connect(update_category_tree, sender=ProductCategory)

# For explicit connection (call in apps.py)
# connect_signals()