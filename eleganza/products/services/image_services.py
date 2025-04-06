from django.db import transaction
from django.core.exceptions import ValidationError
from typing import Optional, Sequence
from eleganza.products.models import ProductImage
from eleganza.products.constants import FieldLengths

@transaction.atomic
def set_primary_image(image_id: int) -> ProductImage:
    """
    Set an image as primary and clear previous primary status.
    """
    try:
        with transaction.atomic():
            image = ProductImage.objects.select_for_update().select_related(
                'product', 'variant'
            ).get(pk=image_id)

            if not (image.product or image.variant):
                raise ValidationError("Image must be linked to a product or variant")
            if image.product and image.variant:
                raise ValidationError("Image cannot be linked to both product and variant")

            target = image.product or image.variant
            target_type = 'product' if image.product else 'variant'

            ProductImage.objects.filter(
                **{target_type: target},
                is_primary=True
            ).update(is_primary=False)

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
    Creates a new product image with automatic WebP conversion.
    WebPField now handles all validation during model save.
    """
    if not (product_id or variant_id):
        raise ValidationError("Must specify either product_id or variant_id")
    if product_id and variant_id:
        raise ValidationError("Cannot specify both product_id and variant_id")

    image = ProductImage(
        image=image_file,  # Raw file - WebPField handles conversion
        product_id=product_id,
        variant_id=variant_id,
        caption=caption[:FieldLengths.IMAGE_CAPTION] if caption else '',
        is_primary=is_primary
    )

    try:
        image.full_clean()  # Triggers WebPField validation
        image.save()        # Actual conversion happens here
        
        if is_primary:
            set_primary_image(image.id)
            
        return image
    except Exception as e:
        raise ValidationError(f"Image processing failed: {str(e)}")

@transaction.atomic
def delete_product_image(image_id: int) -> None:
    """
    Delete a product image (no changes needed).
    django-cleanup will handle file deletion.
    """
    try:
        with transaction.atomic():
            image = ProductImage.objects.select_for_update().select_related(
                'product', 'variant'
            ).get(pk=image_id)

            was_primary = image.is_primary
            target = image.product or image.variant
            target_type = 'product' if image.product else 'variant'

            image.delete()

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
    Batch update image sort orders (no changes needed).
    """
    if len(image_ids) != len(new_order):
        raise ValidationError("image_ids and new_order must be same length")

    with transaction.atomic():
        images = ProductImage.objects.select_for_update().filter(
            id__in=image_ids
        )
        
        if missing := set(image_ids) - {img.id for img in images}:
            raise ValidationError(f"Invalid image IDs: {missing}")

        order_mapping = dict(zip(image_ids, new_order))
        updates = []
        for image in images:
            new_sort = order_mapping[image.id]
            if image.sort_order != new_sort:
                image.sort_order = new_sort
                updates.append(image)
        
        if updates:
            ProductImage.objects.bulk_update(updates, ['sort_order'])