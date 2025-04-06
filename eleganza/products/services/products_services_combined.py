
#========================================
# eleganza/products/services/category_services.py
#========================================

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

#========================================
# eleganza/products/services/image_services.py
#========================================

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

#========================================
# eleganza/products/services/inventory_services.py
#========================================

from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db.models import QuerySet, F
from typing import Dict, Optional, Sequence
from eleganza.products.models import Inventory, InventoryHistory, ProductVariant
from eleganza.products.constants import Defaults
from eleganza.core.utils import chunked_queryset

@transaction.atomic
def update_inventory_stock(
    inventory_id: int,
    new_quantity: int,
    *,
    adjustment_reason: Optional[str] = None
) -> InventoryHistory:
    """
    Update inventory stock level with audit trail.
    
    Args:
        inventory_id: ID of inventory record
        new_quantity: New stock quantity (must be >= 0)
        adjustment_reason: Optional reason for adjustment
        
    Returns:
        Created InventoryHistory record
        
    Raises:
        ValidationError: For invalid operations
    """
    if new_quantity < 0:
        raise ValidationError("Stock quantity cannot be negative")

    try:
        inventory = Inventory.objects.select_for_update().select_related(
            'variant'
        ).get(pk=inventory_id)
        
        old_stock = inventory.stock_quantity
        
        if not inventory.variant.is_active:
            raise ValidationError("Cannot update inventory for inactive variant")
        
        inventory.stock_quantity = new_quantity
        inventory.last_restock = timezone.now()
        inventory.full_clean()
        inventory.save()
        
        history = InventoryHistory.objects.create(
            inventory=inventory,
            old_stock=old_stock,
            new_stock=new_quantity,
            notes=adjustment_reason
        )
        
        _check_variant_availability(inventory.variant_id)
        
        return history
        
    except Inventory.DoesNotExist:
        raise ValidationError(f"Inventory with ID {inventory_id} not found")

@transaction.atomic
def bulk_inventory_adjustment(
    adjustments: Dict[int, int],
    *,
    reason: Optional[str] = None
) -> Dict[str, int]:
    """
    Process multiple inventory updates efficiently.
    
    Args:
        adjustments: {inventory_id: quantity_change}
        reason: Optional adjustment reason
        
    Returns:
        {'success': count, 'failed': count}
        
    Raises:
        ValidationError: For invalid bulk operations
    """
    if not adjustments:
        raise ValidationError("No adjustments provided")
    
    if any(qty < 0 for qty in adjustments.values()):
        raise ValidationError("Negative quantities not allowed in bulk operation")

    results = {'success': 0, 'failed': 0}
    inventory_ids = list(adjustments.keys())
    
    with transaction.atomic():
        inventories = Inventory.objects.filter(
            id__in=inventory_ids
        ).select_for_update().select_related('variant')
        
        # Process in batches of 100
        for batch in chunked_queryset(inventories, 100):
            histories = []
            variants_to_check = set()
            
            for inv in batch:
                try:
                    new_qty = inv.stock_quantity + adjustments[inv.id]
                    if new_qty < 0:
                        results['failed'] += 1
                        continue
                        
                    histories.append(InventoryHistory(
                        inventory=inv,
                        old_stock=inv.stock_quantity,
                        new_stock=new_qty,
                        notes=reason
                    ))
                    inv.stock_quantity = new_qty
                    variants_to_check.add(inv.variant_id)
                    results['success'] += 1
                except Exception:
                    results['failed'] += 1
                    continue
            
            # Bulk updates
            Inventory.objects.bulk_update(
                [inv for inv in batch if inv in histories],
                ['stock_quantity', 'last_restock']
            )
            InventoryHistory.objects.bulk_create(histories)
            
            # Batch update variant statuses
            _bulk_check_variant_availability(variants_to_check)
    
    return results

def check_low_stock_items(
    threshold: int = Defaults.LOW_STOCK_THRESHOLD,
    *,
    only_active: bool = True
) -> QuerySet[Inventory]:
    """
    Get inventory items below stock threshold.
    
    Args:
        threshold: Low stock threshold
        only_active: Filter active variants only
        
    Returns:
        QuerySet of low stock items with related data
    """
    queryset = Inventory.objects.filter(
        stock_quantity__lte=threshold
    ).select_related(
        'variant__product'
    ).order_by('stock_quantity')
    
    if only_active:
        queryset = queryset.filter(variant__is_active=True)
        
    return queryset

@transaction.atomic
def transfer_inventory_stock(
    source_id: int,
    destination_id: int,
    quantity: int,
    *,
    reason: Optional[str] = None
) -> Dict[str, InventoryHistory]:
    """
    Transfer stock between inventory locations.
    
    Args:
        source_id: Source inventory ID
        destination_id: Destination inventory ID  
        quantity: Positive quantity to transfer
        reason: Optional transfer reason
        
    Returns:
        {'source': history, 'destination': history}
        
    Raises:
        ValidationError: For invalid transfers
    """
    if quantity <= 0:
        raise ValidationError("Transfer quantity must be positive")
    
    try:
        with transaction.atomic():
            # Lock both records
            inventories = Inventory.objects.select_for_update().filter(
                id__in=[source_id, destination_id]
            ).select_related('variant')
            
            if len(inventories) != 2:
                raise ValidationError("One or more inventory records not found")
            
            source = next(i for i in inventories if i.id == source_id)
            destination = next(i for i in inventories if i.id == destination_id)
            
            # Validate
            if source.stock_quantity < quantity:
                raise ValidationError("Insufficient stock for transfer")
            if source.variant_id != destination.variant_id:
                raise ValidationError("Cannot transfer between different variants")
            
            # Process transfer
            source_history = update_inventory_stock(
                source_id,
                source.stock_quantity - quantity,
                adjustment_reason=f"Transfer out: {reason}"
            )
            
            destination_history = update_inventory_stock(
                destination_id,
                destination.stock_quantity + quantity,
                adjustment_reason=f"Transfer in: {reason}"
            )
            
            return {
                'source': source_history,
                'destination': destination_history
            }
            
    except Exception as e:
        raise ValidationError(f"Transfer failed: {str(e)}")

# -- Private Helpers -- #

def _check_variant_availability(variant_id: int) -> None:
    """Update single variant's active status based on stock"""
    variant = ProductVariant.objects.get(pk=variant_id)
    new_status = variant.inventory.stock_quantity > 0
    
    if variant.is_active != new_status:
        variant.is_active = new_status
        variant.save(update_fields=['is_active'])

def _bulk_check_variant_availability(variant_ids: set[int]) -> None:
    """Bulk update variant availability statuses"""
    if not variant_ids:
        return
    
    # Get current stock status for all variants
    stock_status = {
        inv.variant_id: inv.stock_quantity > 0
        for inv in Inventory.objects.filter(
            variant_id__in=variant_ids
        ).only('variant_id', 'stock_quantity')
    }
    
    # Identify variants needing updates
    to_update = []
    for variant in ProductVariant.objects.filter(id__in=variant_ids):
        new_status = stock_status.get(variant.id, False)
        if variant.is_active != new_status:
            variant.is_active = new_status
            to_update.append(variant)
    
    # Bulk update
    if to_update:
        ProductVariant.objects.bulk_update(to_update, ['is_active'])

#========================================
# eleganza/products/services/product_services.py
#========================================

from django.db import transaction
from django.db.models import Case, When, Value, F
from django.core.exceptions import ValidationError
from typing import Sequence, Dict, Any, Union, List
from djmoney.money import Money
from django.db.models import QuerySet
from eleganza.products.models import Product, ProductVariant
from eleganza.products.constants import DiscountTypes
from eleganza.core.utils import chunked_queryset

@transaction.atomic
def calculate_product_final_price(product: Product) -> Money:
    """
    Calculate final price after applying discounts.
    
    Args:
        product: Product instance to calculate price for
        
    Returns:
        Calculated final price as Money object
        
    Raises:
        ValidationError: For invalid discount configurations
    """
    try:
        if product.discount_type == DiscountTypes.FIXED:
            if not product.discount_amount:
                raise ValidationError("Fixed discount requires amount")
            if product.discount_amount.currency != product.selling_price.currency:
                raise ValidationError("Currency mismatch in discount")
            return product.selling_price - product.discount_amount
            
        elif product.discount_type == DiscountTypes.PERCENTAGE:
            if not product.discount_percent:
                raise ValidationError("Percentage discount requires value")
            discount = product.selling_price.amount * (product.discount_percent / 100)
            return product.selling_price - Money(discount, product.selling_price.currency)
            
        return product.selling_price
        
    except Exception as e:
        raise ValidationError(f"Price calculation failed: {str(e)}")

@transaction.atomic
def update_product_pricing(product: Product) -> Product:
    """
    Update all price-related fields with validation.
    
    Args:
        product: Product instance to update
        
    Returns:
        Updated Product instance
        
    Raises:
        ValidationError: For invalid price configurations
    """
    try:
        if product.selling_price.amount <= 0:
            raise ValidationError("Price must be greater than zero")
        
        product.final_price = calculate_product_final_price(product)
        product.full_clean()
        product.save(update_fields=['final_price'])
        
        if product.has_variants:
            update_variant_prices(product.id)
            
        return product
        
    except Exception as e:
        raise ValidationError(str(e))

@transaction.atomic
def toggle_product_activation(product_id: int, is_active: bool) -> Product:
    """
    Activate/deactivate product and cascade to variants.
    
    Args:
        product_id: ID of product to update
        is_active: New activation status
        
    Returns:
        Updated Product instance
        
    Raises:
        ValidationError: If product doesn't exist
    """
    try:
        with transaction.atomic():
            product = Product.objects.select_for_update().get(pk=product_id)
            
            if product.is_active == is_active:
                return product
                
            product.is_active = is_active
            product.save(update_fields=['is_active'])
            
            ProductVariant.objects.filter(product=product).update(is_active=is_active)
                
            return product
            
    except Product.DoesNotExist:
        raise ValidationError(f"Product with ID {product_id} not found")

@transaction.atomic
def bulk_update_products(
    product_ids: Sequence[int],
    update_data: Dict[str, Any],
) -> int:
    """
    Bulk update products with optimized pricing recalculation.
    
    Args:
        product_ids: Sequence of product IDs
        update_data: Fields to update
        
    Returns:
        Number of successfully updated products
        
    Raises:
        ValidationError: For invalid operations
    """
    if not update_data:
        raise ValidationError("No update data provided")
        
    if 'selling_price' in update_data and update_data['selling_price'].amount <= 0:
        raise ValidationError("Price must be positive")

    with transaction.atomic():
        products = Product.objects.filter(
            id__in=product_ids
        ).select_for_update()
        
        # Validate existence
        found_ids = set(products.values_list('id', flat=True))
        if missing := set(product_ids) - found_ids:
            raise ValidationError(f"Invalid product IDs: {missing}")

        updated = products.update(**update_data)
        
        # Handle pricing updates
        if 'selling_price' in update_data or 'discount_type' in update_data:
            price_updates = []
            for product in products:
                try:
                    final_price = calculate_product_final_price(product)
                    price_updates.append(When(id=product.id, then=Value(final_price)))
                except Exception:
                    continue
            
            if price_updates:
                Product.objects.filter(id__in=found_ids).update(
                    final_price=Case(*price_updates, default=F('final_price')))
                
            # Batch update variants
            if any(p.has_variants for p in products):
                for batch in chunked_queryset(products, 50):
                    update_variant_prices([p.id for p in batch])
    
    return updated

def update_variant_prices(product_ids: Union[int, Sequence[int]]) -> int:
    """
    Update prices for variants of one or multiple products.
    Accepts either single product ID or sequence of product IDs.
    
    Args:
        product_ids: Either a single product ID or sequence of product IDs
        
    Returns:
        Number of variants updated
    """
    if isinstance(product_ids, int):
        product_ids = [product_ids]
    
    variants = ProductVariant.objects.filter(
        product_id__in=product_ids
    ).select_related('product').prefetch_related('attributes')
    
    updates = []
    for variant in variants:
        # Calculate new price modifier
        modifier_amount = sum(
            attr.value_modifier.amount 
            for attr in variant.attributes.all() 
            if hasattr(attr, 'value_modifier')
        )
        new_modifier = Money(modifier_amount, variant.product.selling_price.currency)
        
        # Check if update needed
        if variant.price_modifier != new_modifier:
            variant.price_modifier = new_modifier
            updates.append(variant)
    
    # Perform bulk update if needed
    if updates:
        ProductVariant.objects.bulk_update(updates, ['price_modifier'])
    
    return len(updates)

#========================================
# eleganza/products/services/products_services_combined.py
#========================================


#========================================
# eleganza/products/services/category_services.py
#========================================

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

#========================================
# eleganza/products/services/image_services.py
#========================================

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

#========================================
# eleganza/products/services/inventory_services.py
#========================================

from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db.models import QuerySet, F
from typing import Dict, Optional, Sequence
from eleganza.products.models import Inventory, InventoryHistory, ProductVariant
from eleganza.products.constants import Defaults
from eleganza.core.utils import chunked_queryset

@transaction.atomic
def update_inventory_stock(
    inventory_id: int,
    new_quantity: int,
    *,
    adjustment_reason: Optional[str] = None
) -> InventoryHistory:
    """
    Update inventory stock level with audit trail.
    
    Args:
        inventory_id: ID of inventory record
        new_quantity: New stock quantity (must be >= 0)
        adjustment_reason: Optional reason for adjustment
        
    Returns:
        Created InventoryHistory record
        
    Raises:
        ValidationError: For invalid operations
    """
    if new_quantity < 0:
        raise ValidationError("Stock quantity cannot be negative")

    try:
        inventory = Inventory.objects.select_for_update().select_related(
            'variant'
        ).get(pk=inventory_id)
        
        old_stock = inventory.stock_quantity
        
        if not inventory.variant.is_active:
            raise ValidationError("Cannot update inventory for inactive variant")
        
        inventory.stock_quantity = new_quantity
        inventory.last_restock = timezone.now()
        inventory.full_clean()
        inventory.save()
        
        history = InventoryHistory.objects.create(
            inventory=inventory,
            old_stock=old_stock,
            new_stock=new_quantity,
            notes=adjustment_reason
        )
        
        _check_variant_availability(inventory.variant_id)
        
        return history
        
    except Inventory.DoesNotExist:
        raise ValidationError(f"Inventory with ID {inventory_id} not found")

@transaction.atomic
def bulk_inventory_adjustment(
    adjustments: Dict[int, int],
    *,
    reason: Optional[str] = None
) -> Dict[str, int]:
    """
    Process multiple inventory updates efficiently.
    
    Args:
        adjustments: {inventory_id: quantity_change}
        reason: Optional adjustment reason
        
    Returns:
        {'success': count, 'failed': count}
        
    Raises:
        ValidationError: For invalid bulk operations
    """
    if not adjustments:
        raise ValidationError("No adjustments provided")
    
    if any(qty < 0 for qty in adjustments.values()):
        raise ValidationError("Negative quantities not allowed in bulk operation")

    results = {'success': 0, 'failed': 0}
    inventory_ids = list(adjustments.keys())
    
    with transaction.atomic():
        inventories = Inventory.objects.filter(
            id__in=inventory_ids
        ).select_for_update().select_related('variant')
        
        # Process in batches of 100
        for batch in chunked_queryset(inventories, 100):
            histories = []
            variants_to_check = set()
            
            for inv in batch:
                try:
                    new_qty = inv.stock_quantity + adjustments[inv.id]
                    if new_qty < 0:
                        results['failed'] += 1
                        continue
                        
                    histories.append(InventoryHistory(
                        inventory=inv,
                        old_stock=inv.stock_quantity,
                        new_stock=new_qty,
                        notes=reason
                    ))
                    inv.stock_quantity = new_qty
                    variants_to_check.add(inv.variant_id)
                    results['success'] += 1
                except Exception:
                    results['failed'] += 1
                    continue
            
            # Bulk updates
            Inventory.objects.bulk_update(
                [inv for inv in batch if inv in histories],
                ['stock_quantity', 'last_restock']
            )
            InventoryHistory.objects.bulk_create(histories)
            
            # Batch update variant statuses
            _bulk_check_variant_availability(variants_to_check)
    
    return results

def check_low_stock_items(
    threshold: int = Defaults.LOW_STOCK_THRESHOLD,
    *,
    only_active: bool = True
) -> QuerySet[Inventory]:
    """
    Get inventory items below stock threshold.
    
    Args:
        threshold: Low stock threshold
        only_active: Filter active variants only
        
    Returns:
        QuerySet of low stock items with related data
    """
    queryset = Inventory.objects.filter(
        stock_quantity__lte=threshold
    ).select_related(
        'variant__product'
    ).order_by('stock_quantity')
    
    if only_active:
        queryset = queryset.filter(variant__is_active=True)
        
    return queryset

@transaction.atomic
def transfer_inventory_stock(
    source_id: int,
    destination_id: int,
    quantity: int,
    *,
    reason: Optional[str] = None
) -> Dict[str, InventoryHistory]:
    """
    Transfer stock between inventory locations.
    
    Args:
        source_id: Source inventory ID
        destination_id: Destination inventory ID  
        quantity: Positive quantity to transfer
        reason: Optional transfer reason
        
    Returns:
        {'source': history, 'destination': history}
        
    Raises:
        ValidationError: For invalid transfers
    """
    if quantity <= 0:
        raise ValidationError("Transfer quantity must be positive")
    
    try:
        with transaction.atomic():
            # Lock both records
            inventories = Inventory.objects.select_for_update().filter(
                id__in=[source_id, destination_id]
            ).select_related('variant')
            
            if len(inventories) != 2:
                raise ValidationError("One or more inventory records not found")
            
            source = next(i for i in inventories if i.id == source_id)
            destination = next(i for i in inventories if i.id == destination_id)
            
            # Validate
            if source.stock_quantity < quantity:
                raise ValidationError("Insufficient stock for transfer")
            if source.variant_id != destination.variant_id:
                raise ValidationError("Cannot transfer between different variants")
            
            # Process transfer
            source_history = update_inventory_stock(
                source_id,
                source.stock_quantity - quantity,
                adjustment_reason=f"Transfer out: {reason}"
            )
            
            destination_history = update_inventory_stock(
                destination_id,
                destination.stock_quantity + quantity,
                adjustment_reason=f"Transfer in: {reason}"
            )
            
            return {
                'source': source_history,
                'destination': destination_history
            }
            
    except Exception as e:
        raise ValidationError(f"Transfer failed: {str(e)}")

# -- Private Helpers -- #

def _check_variant_availability(variant_id: int) -> None:
    """Update single variant's active status based on stock"""
    variant = ProductVariant.objects.get(pk=variant_id)
    new_status = variant.inventory.stock_quantity > 0
    
    if variant.is_active != new_status:
        variant.is_active = new_status
        variant.save(update_fields=['is_active'])

def _bulk_check_variant_availability(variant_ids: set[int]) -> None:
    """Bulk update variant availability statuses"""
    if not variant_ids:
        return
    
    # Get current stock status for all variants
    stock_status = {
        inv.variant_id: inv.stock_quantity > 0
        for inv in Inventory.objects.filter(
            variant_id__in=variant_ids
        ).only('variant_id', 'stock_quantity')
    }
    
    # Identify variants needing updates
    to_update = []
    for variant in ProductVariant.objects.filter(id__in=variant_ids):
        new_status = stock_status.get(variant.id, False)
        if variant.is_active != new_status:
            variant.is_active = new_status
            to_update.append(variant)
    
    # Bulk update
    if to_update:
        ProductVariant.objects.bulk_update(to_update, ['is_active'])


#========================================
# eleganza/products/services/review_services.py
#========================================

from django.db import transaction
from django.db.models import Avg, Count, F
from django.core.exceptions import ValidationError
from typing import Optional, Dict, List
from eleganza.products.models import ProductReview, Product
from eleganza.users.models import User
from eleganza.products.constants import Defaults


@transaction.atomic
def submit_product_review(
    product_id: int,
    user_id: int,
    rating: int,
    title: str,
    comment: str,
    *,
    auto_approve: bool = False
) -> ProductReview:
    """
    Submit and process a new product review with validation.
    
    Args:
        product_id: ID of the product being reviewed
        user_id: ID of the user submitting the review
        rating: Rating value (1-5)
        title: Review title
        comment: Review text content
        auto_approve: Whether to automatically approve the review
        
    Returns:
        The created ProductReview instance
        
    Raises:
        ValidationError: For invalid review data
        ValidationError: If product/user doesn't exist
    """
    try:
        # Validate rating
        if not (1 <= rating <= 5):
            raise ValidationError("Rating must be between 1-5")
        
        # Check for existing review
        if ProductReview.objects.filter(product_id=product_id, user_id=user_id).exists():
            raise ValidationError("You've already reviewed this product")
        
        with transaction.atomic():
            # Create the review
            review = ProductReview.objects.create(
                product_id=product_id,
                user_id=user_id,
                rating=rating,
                title=title.strip(),
                comment=comment.strip(),
                is_approved=auto_approve
            )
            
            # Update product ratings if auto-approved
            if auto_approve:
                _update_product_rating_stats(product_id)
            
            
            return review
            
    except Product.DoesNotExist:
        raise ValidationError(f"Product with ID {product_id} not found")
    except User.DoesNotExist:
        raise ValidationError(f"User with ID {user_id} not found")

@transaction.atomic
def approve_review(
    review_id: int,
    *,
    moderator_id: Optional[int] = None
) -> ProductReview:
    """
    Approve a product review and update product ratings.
    
    Args:
        review_id: ID of the review to approve
        moderator_id: Optional ID of approving moderator
        
    Returns:
        The approved ProductReview instance
        
    Raises:
        ValidationError: If review doesn't exist
    """
    try:
        with transaction.atomic():
            review = ProductReview.objects.select_for_update().get(pk=review_id)
            
            if review.is_approved:
                return review
                
            review.is_approved = True
            review.save(update_fields=['is_approved'])
            
            # Update product stats
            _update_product_rating_stats(review.product_id)
            
            
            return review
            
    except ProductReview.DoesNotExist:
        raise ValidationError(f"Review with ID {review_id} not found")


@transaction.atomic
def update_review_helpfulness(
    review_id: int,
    is_helpful: bool,
    *,
    user_id: Optional[int] = None
) -> ProductReview:
    """
    Update review helpfulness votes.
    
    Args:
        review_id: ID of the review
        is_helpful: Whether the vote is helpful or not
        user_id: Optional ID of voting user
        
    Returns:
        Updated ProductReview instance
        
    Raises:
        ValidationError: If review doesn't exist
    """
    try:
        with transaction.atomic():
            review = ProductReview.objects.select_for_update().get(pk=review_id)
            
            if is_helpful:
                review.helpful_votes = F('helpful_votes') + 1
            else:
                review.helpful_votes = F('helpful_votes') - 1
                
            review.save(update_fields=['helpful_votes'])
            review.refresh_from_db()
            
            # Prevent negative votes
            if review.helpful_votes < 0:
                review.helpful_votes = 0
                review.save(update_fields=['helpful_votes'])
            
            
            return review
            
    except ProductReview.DoesNotExist:
        raise ValidationError(f"Review with ID {review_id} not found")

# -- Private Helpers -- #

def _update_product_rating_stats(product_id: int) -> None:
    """Recalculate and update product rating statistics"""
    stats = ProductReview.objects.filter(
        product_id=product_id,
        is_approved=True
    ).aggregate(
        avg_rating=Avg('rating'),
        review_count=Count('id')
    )
    
    Product.objects.filter(pk=product_id).update(
        average_rating=stats['avg_rating'] or 0,
        review_count=stats['review_count']
    )


#========================================
# eleganza/products/services/variant_services.py
#========================================

from django.db import transaction
from django.core.exceptions import ValidationError
from django.db.models import Q, F
from typing import Optional, List, Dict, Any, Sequence
from djmoney.money import Money
from eleganza.products.models import Product, ProductVariant, Inventory, ProductOption
from eleganza.products.constants import Defaults
from eleganza.core.utils import chunked_queryset

@transaction.atomic
def create_product_variant(
    product_id: int,
    sku: str,
    options: List[int],
    price_modifier: Money,
    *,
    is_default: bool = False
) -> ProductVariant:
    """
    Creates a new product variant with complete setup in a single transaction.
    
    Args:
        product_id: Parent product ID
        sku: Unique variant SKU
        options: List of ProductOption IDs
        price_modifier: Price adjustment
        is_default: Whether to set as default variant
        
    Returns:
        Created ProductVariant instance
        
    Raises:
        ValidationError: For invalid configurations
    """
    try:
        # Validate options exist and belong to product
        valid_options = ProductOption.objects.filter(
            id__in=options,
            attribute__products=product_id
        )
        if len(valid_options) != len(options):
            invalid_ids = set(options) - set(valid_options.values_list('id', flat=True))
            raise ValidationError(
                f"Invalid options for product: {invalid_ids}",
                code="invalid_options"
            )

        with transaction.atomic():
            # Create variant
            variant = ProductVariant.objects.create(
                product_id=product_id,
                sku=sku,
                price_modifier=price_modifier,
                is_default=is_default
            )
            
            # Set options (M2M requires save first)
            variant.options.set(options)
            
            # Create inventory record
            Inventory.objects.create(variant=variant)
            
            # Handle default status
            if is_default:
                _set_as_default_variant(variant.id)
            
            return variant
            
    except Product.DoesNotExist:
        raise ValidationError(f"Product with ID {product_id} not found", code="product_not_found")
    except ProductOption.DoesNotExist:
        raise ValidationError("One or more option IDs are invalid", code="invalid_option_ids")

@transaction.atomic
def update_variant(
    variant_id: int,
    *,
    sku: Optional[str] = None,
    price_modifier: Optional[Money] = None,
    options: Optional[List[int]] = None,
    is_active: Optional[bool] = None
) -> ProductVariant:
    """
    Updates variant properties with complete validation.
    
    Args:
        variant_id: Variant ID to update
        sku: New SKU (optional)
        price_modifier: New price adjustment (optional)
        options: New option IDs (optional)
        is_active: New active status (optional)
        
    Returns:
        Updated ProductVariant instance
        
    Raises:
        ValidationError: For invalid updates
    """
    try:
        with transaction.atomic():
            variant = ProductVariant.objects.select_for_update().get(pk=variant_id)
            
            # Track changes for validation
            changes = {}
            if sku is not None and sku != variant.sku:
                changes['sku'] = sku
            if price_modifier is not None and price_modifier != variant.price_modifier:
                changes['price_modifier'] = price_modifier
            if is_active is not None and is_active != variant.is_active:
                changes['is_active'] = is_active
            
            # Apply updates
            if changes:
                for field, value in changes.items():
                    setattr(variant, field, value)
                variant.full_clean()
                variant.save()
            
            # Handle option updates
            if options is not None:
                _update_variant_options(variant, options)
            
            return variant
            
    except ProductVariant.DoesNotExist:
        raise ValidationError(f"Variant with ID {variant_id} not found", code="variant_not_found")

@transaction.atomic
def set_default_variant(variant_id: int) -> ProductVariant:
    """
    Atomically sets a variant as default and clears previous default.
    
    Args:
        variant_id: Variant ID to promote
        
    Returns:
        Updated ProductVariant instance
        
    Raises:
        ValidationError: If variant doesn't exist or is invalid
    """
    try:
        with transaction.atomic():
            variant = ProductVariant.objects.select_for_update().get(pk=variant_id)
            
            if variant.is_default:
                return variant
                
            if not variant.is_active:
                raise ValidationError(
                    "Cannot set inactive variant as default",
                    code="inactive_default"
                )
                
            # Clear previous default
            ProductVariant.objects.filter(
                product=variant.product,
                is_default=True
            ).exclude(pk=variant_id).update(is_default=False)
            
            # Set new default
            variant.is_default = True
            variant.save(update_fields=['is_default'])
            
            return variant
            
    except ProductVariant.DoesNotExist:
        raise ValidationError(f"Variant with ID {variant_id} not found", code="variant_not_found")

@transaction.atomic
def bulk_update_variants(
    variant_ids: Sequence[int],
    update_data: Dict[str, Any]
) -> Dict[str, int]:
    """
    Efficiently updates multiple variants with proper locking.
    
    Args:
        variant_ids: Sequence of variant IDs
        update_data: Field=value mappings
        
    Returns:
        {'updated': count, 'skipped': count}
        
    Raises:
        ValidationError: For invalid operations
    """
    if not update_data:
        raise ValidationError("No update data provided", code="empty_update")
        
    results = {'updated': 0, 'skipped': 0}
    
    with transaction.atomic():
        # Lock all variants first
        variants = ProductVariant.objects.select_for_update().filter(
            id__in=variant_ids
        ).select_related('product')
        
        # Validate existence
        found_ids = {v.id for v in variants}
        if missing := set(variant_ids) - found_ids:
            raise ValidationError(
                f"Invalid variant IDs: {missing}",
                code="invalid_variant_ids"
            )
        
        # Process in batches
        for batch in chunked_queryset(variants, 100):
            updates = []
            for variant in batch:
                try:
                    # Apply updates
                    for field, value in update_data.items():
                        setattr(variant, field, value)
                    variant.full_clean()
                    updates.append(variant)
                    results['updated'] += 1
                except Exception:
                    results['skipped'] += 1
                    continue
            
            # Bulk update
            if updates:
                fields_to_update = list(update_data.keys())
                if 'is_default' in fields_to_update:
                    fields_to_update.remove('is_default')
                    for variant in updates:
                        if variant.is_default:
                            set_default_variant(variant.id)
                
                ProductVariant.objects.bulk_update(updates, fields_to_update)
    
    return results

# -- Private Helpers -- #

def _update_variant_options(variant: ProductVariant, option_ids: List[int]) -> None:
    """Validates and updates variant options"""
    valid_options = ProductOption.objects.filter(
        id__in=option_ids,
        attribute__products=variant.product_id
    )
    if len(valid_options) != len(option_ids):
        invalid_ids = set(option_ids) - set(valid_options.values_list('id', flat=True))
        raise ValidationError(
            f"Invalid options for product: {invalid_ids}",
            code="invalid_options"
        )
    
    variant.options.set(option_ids)

def _set_as_default_variant(variant_id: int) -> None:
    """Wrapper for setting default variant"""
    set_default_variant(variant_id)
