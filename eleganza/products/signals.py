# products/signals.py
from django.db.models.signals import pre_save, post_save, pre_delete
from django.dispatch import receiver
from .models import Product, ProductImage, ProductCategory
from django.core.exceptions import ValidationError
from django.utils.text import slugify

@receiver(pre_save, sender=Product)
def product_pre_save(sender, instance, **kwargs):
    """Automatically generate slug and validate pricing"""
    if not instance.slug:
        instance.slug = slugify(instance.name)
    
    # Ensure unique slug
    if Product.objects.filter(slug=instance.slug).exclude(id=instance.id).exists():
        instance.slug = f"{instance.slug}-{instance.sku}"

@receiver(post_save, sender=ProductImage)
def handle_primary_image(sender, instance, **kwargs):
    """Ensure only one primary image exists per product"""
    if instance.is_primary:
        ProductImage.objects.filter(product=instance.product) \
            .exclude(pk=instance.pk) \
            .update(is_primary=False)

@receiver(pre_save, sender=ProductCategory)
def category_pre_save(sender, instance, **kwargs):
    """Generate category slug and validate hierarchy"""
    if not instance.slug:
        instance.slug = slugify(instance.name)
    
    # Prevent circular parent relationships
    if instance.parent and instance.parent.id == instance.id:
        raise ValidationError("Category cannot be its own parent")

@receiver(pre_delete, sender=Product)
def product_pre_delete(sender, instance, **kwargs):
    """
    Handle product deletion:
    - Cancel related orders
    - Clear inventory reservations
    """
    from orders.models import OrderItem  # Avoid circular import
    
    # Cancel pending order items
    OrderItem.objects.filter(
        product=instance,
        order__status__in=['pending', 'reserved']
    ).update(status='cancelled')
    
    # Release reserved stock
    instance.reserved_stock = 0
    instance.save(update_fields=['reserved_stock'])