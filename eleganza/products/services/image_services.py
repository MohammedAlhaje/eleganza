from django.db import transaction
from django.core.exceptions import ValidationError
from typing import Optional, Sequence
from eleganza.products.models import ProductImage
from eleganza.products.constants import FieldLengths
from eleganza.products.validators import ProductImageValidator

# Initialize the validator from core
image_validator = ProductImageValidator()

@transaction.atomic
def set_primary_image(image_id: int) -> ProductImage:
    """
    Set an image as primary and clear previous primary status for its related object.
    
    Args:
        image_id: ID of the image to set as primary
        
    Returns:
        The updated ProductImage instance
        
    Raises:
        ValidationError: If image doesn't exist or has invalid relationships
    """
    try:
        with transaction.atomic():
            # Lock the image and related objects
            image = ProductImage.objects.select_for_update().select_related(
                'product', 'variant'
            ).get(pk=image_id)

            # Validate relationships
            if not (image.product or image.variant):
                raise ValidationError("Image must be linked to a product or variant")
            if image.product and image.variant:
                raise ValidationError("Image cannot be linked to both product and variant")

            target = image.product or image.variant
            target_type = 'product' if image.product else 'variant'

            # Clear existing primary images for this target
            ProductImage.objects.filter(
                **{target_type: target},
                is_primary=True
            ).update(is_primary=False)

            # Set new primary image
            image.is_primary = True
            image.save(update_fields=['is_primary'])
            
            return image

    except ProductImage.DoesNotExist:
        raise ValidationError(f"Image with ID {image_id} not found")

@transaction.atomic
def create_product_image(
    image_file,
    *,
    product_id: Optional[int] = None,
    variant_id: Optional[int] = None,
    caption: Optional[str] = None,
    is_primary: bool = False
) -> ProductImage:
    """
    Create a new product image with validation from core configuration.
    
    Args:
        image_file: Uploaded image file
        product_id: Optional linked product ID
        variant_id: Optional linked variant ID
        caption: Optional image caption (max 255 chars)
        is_primary: Whether to set as primary image
        
    Returns:
        Created ProductImage instance
        
    Raises:
        ValidationError: For invalid parameters or failed validation
    """
    # Validate relationships
    if not (product_id or variant_id):
        raise ValidationError("Must specify either product_id or variant_id")
    if product_id and variant_id:
        raise ValidationError("Cannot specify both product_id and variant_id")

    # Use core validator for image processing
    try:
        validated_file = image_validator.validate(image_file)
    except Exception as e:
        raise ValidationError(str(e))

    # Create the image
    image = ProductImage(
        image=validated_file,
        product_id=product_id,
        variant_id=variant_id,
        caption=caption[:FieldLengths.IMAGE_CAPTION] if caption else '',
        is_primary=is_primary
    )

    with transaction.atomic():
        image.save()
        
        if is_primary:
            set_primary_image(image.id)
            
        return image

@transaction.atomic
def delete_product_image(image_id: int) -> None:
    """
    Delete a product image and handle primary image reassignment if needed.
    
    Args:
        image_id: ID of the image to delete
        
    Raises:
        ValidationError: If image doesn't exist
    """
    try:
        with transaction.atomic():
            # Lock the image and related objects
            image = ProductImage.objects.select_for_update().select_related(
                'product', 'variant'
            ).get(pk=image_id)

            was_primary = image.is_primary
            target = image.product or image.variant
            target_type = 'product' if image.product else 'variant'

            # Delete the image (django-cleanup will handle file deletion)
            image.delete()

            # Reassign primary if this was the primary image
            if was_primary and target:
                new_primary = ProductImage.objects.filter(
                    **{target_type: target}
                ).order_by('created_at').first()
                
                if new_primary:
                    set_primary_image(new_primary.id)

    except ProductImage.DoesNotExist:
        raise ValidationError(f"Image with ID {image_id} not found")

@transaction.atomic
def bulk_update_image_order(
    image_ids: Sequence[int],
    new_order: Sequence[int]
) -> None:
    """
    Batch update image sort orders while maintaining data consistency.
    
    Args:
        image_ids: Sequence of image IDs in the desired order
        new_order: Corresponding sort order values
        
    Raises:
        ValidationError: For invalid operations or mismatched inputs
    """
    if len(image_ids) != len(new_order):
        raise ValidationError("image_ids and new_order must be same length")

    with transaction.atomic():
        # Lock all affected images
        images = ProductImage.objects.select_for_update().filter(
            id__in=image_ids
        )
        
        # Verify we found all requested images
        found_ids = {img.id for img in images}
        if missing := set(image_ids) - found_ids:
            raise ValidationError(f"Invalid image IDs: {missing}")

        # Create order mapping and apply updates
        order_mapping = dict(zip(image_ids, new_order))
        updates = []
        for image in images:
            new_sort = order_mapping[image.id]
            if image.sort_order != new_sort:
                image.sort_order = new_sort
                updates.append(image)
        
        if updates:
            ProductImage.objects.bulk_update(updates, ['sort_order'])