from django.db import transaction
from django.core.exceptions import ValidationError
from mptt.exceptions import InvalidMove
from eleganza.products.models import ProductCategory, Product
from typing import Optional, Dict, Any

def move_category(
    category_id: int,
    new_parent_id: Optional[int] = None,
    *,
    user_id: Optional[int] = None
) -> ProductCategory:
    """
    Change category hierarchy position with transaction safety
    
    Args:
        category_id: ID of the category to move
        new_parent_id: ID of the new parent category (None for root)
        user_id: Optional user ID for audit purposes
        
    Returns:
        The moved ProductCategory instance
        
    Raises:
        ValueError: If category doesn't exist
        ValidationError: If move is invalid
    """
    try:
        with transaction.atomic():
            category = ProductCategory.objects.select_for_update().get(pk=category_id)
            
            try:
                category.parent_id = new_parent_id
                category.save()
                     
                return category
                
            except InvalidMove as e:
                raise ValidationError(str(e))
                
    except ProductCategory.DoesNotExist:
        raise ValueError(f"Category with ID {category_id} not found")


def bulk_update_category_products(
    category_id: int,
    update_fields: Dict[str, Any],
    *,
    batch_size: int = 1000
) -> int:
    """
    Bulk update all products in a category with efficient querying
    
    Args:
        category_id: ID of the target category
        update_fields: Dictionary of field=value pairs to update
        batch_size: Number of products to update per batch
        
    Returns:
        Number of products updated
        
    Raises:
        ValueError: If category doesn't exist or invalid update fields
    """
    if not update_fields:
        raise ValueError("No update fields provided")
        
    if not ProductCategory.objects.filter(pk=category_id).exists():
        raise ValueError(f"Category with ID {category_id} not found")
    
    # Validate fields
    valid_fields = {f.name for f in Product._meta.get_fields()}
    for field in update_fields:
        if field not in valid_fields:
            raise ValueError(f"Invalid field '{field}' for Product model")
    
    # Batch processing for large categories
    updated_count = 0
    products = Product.objects.filter(category_id=category_id).only('id')
    
    for batch in chunked_queryset(products, batch_size):
        updated_count += Product.objects.filter(
            id__in=[p.id for p in batch]
        ).update(**update_fields)
        
    return updated_count


# -- Private Helpers -- #
def chunked_queryset(queryset, size: int):
    """Helper for batching large querysets"""
    start = 0
    while True:
        batch = list(queryset[start:start + size])
        if not batch:
            break
        yield batch
        start += size