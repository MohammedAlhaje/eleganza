from django.db import transaction
from django.core.exceptions import ValidationError
from django.db.models import Q  # Import Q for filtering queries
from .models import ProductImage

@transaction.atomic
def create_product_image(
    image,
    product_id: int = None,
    variant_id: int = None,
    is_primary: bool = False,
    sort_order: int = 0
) -> ProductImage:
    """UC-M01: Create a new product image with proper validation"""
    if product_id and variant_id:
        raise ValidationError("Cannot associate with both product and variant simultaneously")
    
    image = ProductImage(
        image=image,
        product_id=product_id,
        variant_id=variant_id,
        is_primary=is_primary,
        sort_order=sort_order
    )
    
    image.full_clean()
    image.save()
    
    # If the image is primary, disable other primary images
    if is_primary:
        set_primary_product_image(image.id)
    
    return image

@transaction.atomic
def update_product_image(image_id: int, **kwargs) -> ProductImage:
    """UC-M02: Update product image details"""
    image = ProductImage.objects.get(id=image_id)
    
    if 'product_id' in kwargs and 'variant_id' in kwargs:
        raise ValidationError("Cannot associate with both product and variant simultaneously")
    
    for field, value in kwargs.items():
        setattr(image, field, value)
    
    image.full_clean()
    image.save()
    
    if kwargs.get('is_primary', False):
        set_primary_product_image(image.id)
    
    return image

@transaction.atomic
def delete_product_image(image_id: int) -> None:
    """UC-M03: Delete a product image"""
    ProductImage.objects.get(id=image_id).delete()

@transaction.atomic
def set_primary_product_image(image_id: int) -> None:
    """UC-M04: Set a product image as primary"""
    image = ProductImage.objects.get(id=image_id)
    target = image.product or image.variant
    
    # Disable all other primary images associated with the same product or variant
    ProductImage.objects.filter(
        Q(product=target) | Q(variant=target)
    ).exclude(id=image_id).update(is_primary=False)
    
    image.is_primary = True
    image.save()