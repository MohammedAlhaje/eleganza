from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import Inventory, InventoryHistory

# ──────────────────────────────────────────────────
# Main Inventory Management Services
# ──────────────────────────────────────────────────

@transaction.atomic
def initialize_inventory(variant_id: int) -> Inventory:
    """UC-INV01: Initialize initial stock for a product variant"""
    if Inventory.objects.filter(variant_id=variant_id).exists():
        raise ValidationError("Stock is already initialized for this variant")
    
    return Inventory.objects.create(
        variant_id=variant_id,
        stock_quantity=0,
        low_stock_threshold=5,
    )

@transaction.atomic
def adjust_stock(
    inventory_id: int,
    new_quantity: int,
    change_type: str,
    notes: str = ""
) -> InventoryHistory:
    """UC-INV02: Adjust stock quantity and record history"""
    inventory = Inventory.objects.get(id=inventory_id)
    
    if new_quantity < 0:
        raise ValidationError("Quantity cannot be negative")
    
    old_stock = inventory.stock_quantity
    inventory.stock_quantity = new_quantity
    
    # Update last restock time if the change type is RESTOCK
    if change_type == InventoryHistory.ChangeType.RESTOCK and new_quantity > old_stock:
        inventory.last_restock = timezone.now()
    
    inventory.save()
    
    # Create history record
    history = InventoryHistory.objects.create(
        inventory=inventory,
        old_stock=old_stock,
        new_stock=new_quantity,
        change_type=change_type,
        notes=notes
    )
    
    # Send low stock alert if necessary (UC-INV04)
    if new_quantity < inventory.low_stock_threshold:
        send_low_stock_alert(inventory)
    
    return history

def send_low_stock_alert(inventory: Inventory) -> None:
    """UC-INV04: Send low stock alert"""
    # Implement notification sending (email, internal alert, etc.)
    pass

# ──────────────────────────────────────────────────
# Helper Services
# ──────────────────────────────────────────────────

@transaction.atomic
def bulk_restock(variant_ids: list[int], quantity: int) -> None:
    """Restock inventory for multiple variants"""
    for variant_id in variant_ids:
        inventory = Inventory.objects.get(variant_id=variant_id)
        adjust_stock(
            inventory.id,
            inventory.stock_quantity + quantity,
            InventoryHistory.ChangeType.RESTOCK,
            notes="Bulk restock"
        )