from django.db.models import F, QuerySet
from django.utils import timezone
from .models import Inventory, InventoryHistory

def get_inventory_by_variant(variant_id: int) -> Inventory:
    """UC-INV03: Retrieve inventory details for a variant"""
    return Inventory.objects.get(variant_id=variant_id)

def get_inventory_history(inventory_id: int) -> QuerySet:
    """UC-INH02: Retrieve inventory adjustment history"""
    return InventoryHistory.objects.filter(
        inventory_id=inventory_id
    ).annotate(
        delta=F('new_stock') - F('old_stock')
    ).order_by('-timestamp')

def get_low_stock_items(threshold: int = None) -> QuerySet:
    """Retrieve items with low stock"""
    queryset = Inventory.objects.filter(
        stock_quantity__lt=F('low_stock_threshold')
    )
    if threshold:
        queryset = queryset.filter(stock_quantity__lt=threshold)
    return queryset

def get_recent_restocks(days: int = 7) -> QuerySet:
    """Retrieve recent restock operations"""
    return Inventory.objects.filter(
        last_restock__gte=timezone.now() - timezone.timedelta(days=days)
    )