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