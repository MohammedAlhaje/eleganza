import logging
from django.db import transaction
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from typing import Type, Any
from .models import ProductReview, ProductVariant, Inventory

logger = logging.getLogger(__name__)

# --------------------------
# Product Review Signals
# --------------------------
@receiver([post_save, post_delete], sender=ProductReview)
def update_product_rating_stats(
    sender: Type[ProductReview],
    instance: ProductReview,
    **kwargs: Any
) -> None:
    """
    Optimized rating recalculation with change detection and atomic transaction.
    """
    # Skip if flagged to bypass
    if getattr(instance, 'skip_rating_signal', False):
        return

    try:
        with transaction.atomic():
            product = instance.product
            original_rating = product.average_rating
            
            # Only recalculate if relevant fields changed
            if not instance._state.adding:  # Existing instance
                if not any(field in ['rating', 'is_approved'] for field in instance.tracker.changed()):
                    return

            product.update_rating_stats()
            
            logger.info(
                f"Updated ratings for product {product.sku} | "
                f"Old: {original_rating} | New: {product.average_rating}"
            )
    except Exception as e:
        logger.error(
            f"Rating update failed for product {instance.product_id}: {str(e)}",
            exc_info=True
        )
        raise

# --------------------------
# Product Variant Signals
# --------------------------
@receiver(post_save, sender=ProductVariant)
def create_inventory_for_new_variant(sender, instance, created, **kwargs):
    """Simplified inventory creation"""
    if created:
        Inventory.objects.get_or_create(variant=instance)
