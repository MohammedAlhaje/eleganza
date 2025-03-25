import logging
from django.db import transaction
from django.db.models.signals import (
    post_save,
    post_delete,
    pre_save
)
from django.dispatch import receiver
from django.core.exceptions import ValidationError
from .models import (
    Product,
    ProductReview,
    Inventory,
    ProductImage
)

logger = logging.getLogger(__name__)

@receiver([post_save, post_delete], sender=ProductReview)
def update_product_rating_stats(sender, instance, **kwargs):
    """
    Update product rating statistics when reviews change.
    Handles both creation/deletion and approval status changes.
    Uses atomic transaction for data consistency.
    """
    try:
        with transaction.atomic():
            logger.info(
                f"Updating rating stats for product {instance.product_id}"
            )
            instance.product.update_rating_stats()
    except Exception as e:
        logger.error(
            f"Failed updating rating stats for product {instance.product_id}: {str(e)}",
            exc_info=True
        )
        raise

@receiver(post_save, sender=Product)
def create_inventory_for_new_product(sender, instance, created, **kwargs):
    """
    Automatically create inventory record for new products.
    Ensures every product has an inventory tracking entry.
    """
    if created:
        try:
            Inventory.objects.create(product=instance)
            logger.info(f"Created inventory for new product {instance.sku}")
        except Exception as e:
            logger.error(
                f"Failed creating inventory for product {instance.sku}: {str(e)}",
                exc_info=True
            )
            raise

@receiver(pre_save, sender=ProductImage)
def handle_primary_image_change(sender, instance, **kwargs):
    """
    Ensure only one primary image exists per product.
    Automatically demotes previous primary image when new one is set.
    """
    if instance.is_primary:
        # Update existing primary images atomically
        ProductImage.objects.filter(
            product=instance.product,
            is_primary=True
        ).exclude(pk=instance.pk).update(is_primary=False)