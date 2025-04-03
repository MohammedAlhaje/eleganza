from django.db.models import F, Q, Count, Sum, Value
from django.db.models.functions import Coalesce
from typing import List, Dict, Optional
from ..models import Inventory, InventoryHistory, ProductVariant
from ..constants import Defaults

def get_inventory_status(variant_id: int) -> Optional[Dict[str, any]]:
    """
    Get complete inventory status for a single variant
    
    Args:
        variant_id: ID of the product variant
        
    Returns:
        Dictionary with:
        - current_stock
        - low_stock_flag
        - last_restock_date
        - monthly_movement (avg)
        or None if not found
    """
    inventory = Inventory.objects.filter(
        variant_id=variant_id
    ).annotate(
        monthly_movement=Coalesce(
            Sum('history__new_stock' - 'history__old_stock', 
                filter=Q(history__timestamp__gte=timezone.now() - timedelta(days=30))),
            Value(0)
        )
    ).values(
        'stock_quantity',
        'low_stock_threshold',
        'last_restock',
        'monthly_movement'
    ).first()
    
    if not inventory:
        return None
    
    return {
        **inventory,
        'low_stock_flag': inventory['stock_quantity'] <= inventory['low_stock_threshold'],
        'variant_sku': ProductVariant.objects.get(pk=variant_id).sku
    }

def get_low_stock_items(
    *,
    threshold: Optional[int] = None,
    only_active: bool = True
) -> List[Dict[str, any]]:
    """
    Get items below stock threshold with product info
    
    Args:
        threshold: Custom threshold (uses default if None)
        only_active: Only include active variants
        
    Returns:
        List of dictionaries with:
        - variant_id
        - sku
        - product_name
        - current_stock
        - threshold
    """
    threshold = threshold or Defaults.LOW_STOCK_THRESHOLD
    
    queryset = Inventory.objects.filter(
        stock_quantity__lte=threshold
    ).select_related(
        'variant__product'
    ).annotate(
        product_name=F('variant__product__name'),
        sku=F('variant__sku')
    )
    
    if only_active:
        queryset = queryset.filter(variant__is_active=True)
    
    return list(queryset.values(
        'variant_id',
        'sku',
        'product_name',
        'stock_quantity',
        'low_stock_threshold'
    ).order_by('stock_quantity'))

def get_inventory_history(
    variant_id: int,
    *,
    days_back: int = 30,
    limit: Optional[int] = None
) -> List[Dict[str, any]]:
    """
    Get inventory change history for a variant
    
    Args:
        variant_id: ID of the variant
        days_back: Number of days to look back
        limit: Maximum records to return
        
    Returns:
        List of historical records with:
        - date
        - old_stock
        - new_stock
        - delta
        - notes
    """
    history = InventoryHistory.objects.filter(
        inventory__variant_id=variant_id,
        timestamp__gte=timezone.now() - timedelta(days=days_back)
    ).order_by('-timestamp')
    
    if limit:
        history = history[:limit]
    
    return list(history.annotate(
        delta=F('new_stock') - F('old_stock'),
        date=F('timestamp')
    ).values(
        'date',
        'old_stock',
        'new_stock',
        'delta',
        'notes'
    ))

def get_inventory_summary() -> Dict[str, any]:
    """
    Get store-wide inventory summary statistics
    
    Returns:
        Dictionary with:
        - total_items: Count of all inventory items
        - out_of_stock: Count of items with 0 stock
        - low_stock: Count below threshold
        - average_stock: Mean inventory level
        - total_value: Estimated inventory value
    """
    from django.db.models import Avg
    from django.db import connection
    
    # Basic counts
    stats = Inventory.objects.aggregate(
        total_items=Count('id'),
        out_of_stock=Count('id', filter=Q(stock_quantity=0)),
        low_stock=Count('id', filter=Q(stock_quantity__lte=Defaults.LOW_STOCK_THRESHOLD)),
        average_stock=Avg('stock_quantity')
    )
    
    # Value calculation (using raw SQL for efficiency)
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT SUM(i.stock_quantity * p.selling_price_amount) 
            FROM products_inventory i
            JOIN products_productvariant v ON i.variant_id = v.id
            JOIN products_product p ON v.product_id = p.id
        """)
        total_value = cursor.fetchone()[0] or 0
    
    return {
        **stats,
        'total_value': total_value
    }

def get_variant_inventories(
    product_id: int,
    *,
    only_in_stock: bool = False
) -> List[Dict[str, any]]:
    """
    Get inventory status for all variants of a product
    
    Args:
        product_id: ID of the parent product
        only_in_stock: Only include variants with stock > 0
        
    Returns:
        List of variant inventories with:
        - variant_id
        - sku
        - options
        - stock
        - last_updated
    """
    queryset = Inventory.objects.filter(
        variant__product_id=product_id
    ).select_related(
        'variant'
    ).prefetch_related(
        'variant__options__attribute'
    )
    
    if only_in_stock:
        queryset = queryset.filter(stock_quantity__gt=0)
    
    inventories = []
    for inv in queryset:
        inventories.append({
            'variant_id': inv.variant_id,
            'sku': inv.variant.sku,
            'options': [
                f"{opt.attribute.name}: {opt.value}" 
                for opt in inv.variant.options.all()
            ],
            'stock': inv.stock_quantity,
            'last_updated': inv.last_restock
        })
    
    return inventories

def get_restock_candidates(
    *,
    min_sales_velocity: float = 5.0,
    max_weeks_of_stock: int = 2
) -> List[Dict[str, any]]:
    """
    Get variants needing restock based on sales velocity
    
    Args:
        min_sales_velocity: Minimum weekly sales to consider
        max_weeks_of_stock: Maximum weeks of inventory to maintain
        
    Returns:
        List of dictionaries with:
        - variant_id
        - sku
        - current_stock
        - weekly_sales
        - weeks_remaining
    """
    from django.db.models import FloatField
    from django.db.models.functions import Cast
    
    queryset = Inventory.objects.annotate(
        weekly_sales=Coalesce(
            Sum('history__old_stock' - 'history__new_stock',
                filter=Q(
                    history__timestamp__gte=timezone.now() - timedelta(days=21),
                    history__new_stock__lt=F('history__old_stock')
                )) / 3,  # 3 weeks average
            Value(0.0, output_field=FloatField())
        ),
        weeks_remaining=Cast('stock_quantity', FloatField()) / 
                       (F('weekly_sales') + 0.1)  # Avoid division by zero
    ).filter(
        weekly_sales__gte=min_sales_velocity,
        weeks_remaining__lte=max_weeks_of_stock
    ).select_related('variant')
    
    return list(queryset.annotate(
        sku=F('variant__sku')
    ).values(
        'variant_id',
        'sku',
        'stock_quantity',
        'weekly_sales',
        'weeks_remaining'
    ).order_by('weeks_remaining'))