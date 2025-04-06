# eleganza/products/services/category_services.py

from django.db import transaction
from django.db.models import Count
from django.core.exceptions import ValidationError
from mptt.exceptions import InvalidMove
from eleganza.products.models import ProductCategory, Product
from typing import Optional, Dict, Any, Iterable

def create_category(
    name: str,
    parent_id: Optional[int] = None,
    **kwargs
) -> ProductCategory:
    """
    Create new category with hierarchy validation
    
    Args:
        name: Category name
        parent_id: Optional parent category ID
        **kwargs: Additional category fields
        
    Returns:
        Created ProductCategory instance
        
    Raises:
        ValidationError: For invalid parent or duplicate name
    """
    try:
        with transaction.atomic():
            parent = None
            if parent_id:
                parent = ProductCategory.objects.get(pk=parent_id)
                
            category = ProductCategory(
                name=name,
                parent=parent,
                **kwargs
            )
            
            category.full_clean()
            category.save()
            
            return category
            
    except ProductCategory.DoesNotExist:
        raise ValidationError(f"Parent category with ID {parent_id} not found")
    except ValidationError as e:
        raise ValidationError(e.message_dict)

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
        ValidationError: If category doesn't exist
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
        raise ValidationError(f"Category with ID {category_id} not found")

def update_category(
    category_id: int,
    update_data: Dict[str, Any]
) -> ProductCategory:
    """
    Update category properties with validation
    
    Args:
        category_id: ID of category to update
        update_data: Dictionary of field=value pairs
        
    Returns:
        Updated ProductCategory instance
        
    Raises:
        ValidationError: For invalid updates
    """
    try:
        with transaction.atomic():
            category = ProductCategory.objects.get(pk=category_id)
            
            # Handle parent changes separately
            if 'parent_id' in update_data:
                move_category(
                    category_id=category_id,
                    new_parent_id=update_data.pop('parent_id')
                )
                
            for field, value in update_data.items():
                setattr(category, field, value)
                
            category.full_clean()
            category.save()
            
            return category
            
    except ProductCategory.DoesNotExist:
        raise ValidationError(f"Category with ID {category_id} not found")

def delete_category(category_id: int) -> None:
    """
    Delete category and handle product reassignment
    
    Args:
        category_id: ID of category to delete
        
    Raises:
        ValidationError: If category doesn't exist
    """
    try:
        with transaction.atomic():
            category = ProductCategory.objects.get(pk=category_id)
            parent = category.parent
            
            # Move products to parent or root
            Product.objects.filter(category=category).update(category=parent)
            
            # Delete category and rebuild tree
            category.delete()
            ProductCategory.objects.rebuild()
            
    except ProductCategory.DoesNotExist:
        raise ValidationError(f"Category with ID {category_id} not found")

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
        ValidationError: If category doesn't exist or invalid update fields
    """
    if not update_fields:
        raise ValidationError("No update fields provided")
        
    if not ProductCategory.objects.filter(pk=category_id).exists():
        raise ValidationError(f"Category with ID {category_id} not found")
    
    # Validate fields
    valid_fields = {f.name for f in Product._meta.get_fields()}
    for field in update_fields:
        if field not in valid_fields:
            raise ValidationError(f"Invalid field '{field}' for Product model")
    
    # Batch processing for large categories
    updated_count = 0
    products = Product.objects.filter(category_id=category_id).only('id')
    
    for batch in chunked_queryset(products, batch_size):
        updated_count += Product.objects.filter(
            id__in=[p.id for p in batch]
        ).update(**update_fields)
        
    return updated_count



# Helpers ------------------------------------------------------------------

def chunked_queryset(queryset, size: int):
    """Helper for batching large querysets"""
    start = 0
    while True:
        batch = list(queryset[start:start + size])
        if not batch:
            break
        yield batch
        start += size