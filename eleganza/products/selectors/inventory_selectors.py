from django.db.models import F, Q, Count, Sum, Value, FloatField, Avg
from django.db.models.functions import Coalesce
from typing import List, Dict, Optional
from django.core.exceptions import ValidationError
from django.views.decorators.cache import cache_page
from django.utils import timezone
from datetime import timedelta
from ..models import Inventory, InventoryHistory, ProductVariant
from ..constants import Defaults
from django.conf import settings


def validate_inventory_id(inventory_id: int) -> None:
    """Validate inventory ID parameter"""
    if inventory_id <= 0:
        raise ValidationError("Inventory ID must be positive")

def validate_variant_id(variant_id: int) -> None:
    """Validate variant ID parameter"""
    if variant_id <= 0:
        raise ValidationError("Variant ID must be positive")

@cache_page(60 * 15)  # Cache for 15 minutes
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
        
    Raises:
        ValidationError: If variant_id is invalid
    """
    validate_variant_id(variant_id)
    
    inventory = Inventory.objects.filter(
        variant_id=variant_id
    ).annotate(
        monthly_movement=Coalesce(
            Sum('history__new_stock' - 'history__old_stock', 
                filter=Q(history__timestamp__gte=timezone.now() - timedelta(days=30))),
            Value(0)
        ),
        sku=F('variant__sku')
    ).values(
        'stock_quantity',
        'low_stock_threshold',
        'last_restock',
        'monthly_movement',
        'sku'
    ).first()
    
    if not inventory:
        return None
    
    return {
        **inventory,
        'low_stock_flag': inventory['stock_quantity'] <= inventory['low_stock_threshold'],
        'variant_id': variant_id
    }

def get_low_stock_items(
    *,
    threshold: Optional[int] = None,
    only_active: bool = True,
    min_stock: int = 0,
    limit: Optional[int] = None
) -> List[Dict[str, any]]:
    """
    Get items below stock threshold with product info
    
    Args:
        threshold: Custom threshold (uses default if None)
        only_active: Only include active variants
        min_stock: Minimum stock quantity to include
        limit: Maximum number of items to return
        
    Returns:
        List of dictionaries with:
        - variant_id
        - sku
        - product_name
        - current_stock
        - threshold
    """
    threshold = threshold or Defaults.LOW_STOCK_THRESHOLD
    
    if threshold <= 0:
        raise ValidationError("Threshold must be positive")
    if min_stock < 0:
        raise ValidationError("Minimum stock cannot be negative")
    
    queryset = Inventory.objects.filter(
        stock_quantity__lte=threshold,
        stock_quantity__gte=min_stock
    ).select_related(
        'variant__product'
    ).annotate(
        product_name=F('variant__product__name'),
        sku=F('variant__sku')
    )
    
    if only_active:
        queryset = queryset.filter(variant__is_active=True)
    
    if limit:
        queryset = queryset[:limit]
    
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
    limit: Optional[int] = None,
    include_metadata: bool = False
) -> List[Dict[str, any]]:
    """
    Get inventory change history for a variant
    
    Args:
        variant_id: ID of the variant
        days_back: Number of days to look back (1-365)
        limit: Maximum records to return
        include_metadata: Include variant info in results
        
    Returns:
        List of historical records with:
        - date
        - old_stock
        - new_stock
        - delta
        - notes
        - variant_info (if include_metadata=True)
        
    Raises:
        ValidationError: For invalid parameters
    """
    validate_variant_id(variant_id)
    
    if not (1 <= days_back <= 365):
        raise ValidationError("Days back must be between 1 and 365")
    
    history = InventoryHistory.objects.filter(
        inventory__variant_id=variant_id,
        timestamp__gte=timezone.now() - timedelta(days=days_back)
    )
    
    if include_metadata:
        history = history.select_related('inventory__variant')
    
    history = history.order_by('-timestamp')
    
    if limit:
        history = history[:limit]
    
    if include_metadata:
        return list(history.annotate(
            delta=F('new_stock') - F('old_stock'),
            date=F('timestamp'),
            sku=F('inventory__variant__sku')
        ).values(
            'date',
            'old_stock',
            'new_stock',
            'delta',
            'notes',
            'sku'
        ))
    else:
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

@cache_page(60 * 60)  # Cache for 1 hour
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
    # Basic counts
    stats = Inventory.objects.aggregate(
        total_items=Count('id'),
        out_of_stock=Count('id', filter=Q(stock_quantity=0)),
        low_stock=Count('id', filter=Q(
            stock_quantity__gt=0,
            stock_quantity__lte=Defaults.LOW_STOCK_THRESHOLD
        )),
        average_stock=Avg('stock_quantity')
    )
    
    # Calculate total value using ORM
    total_value = Inventory.objects.filter(
        stock_quantity__gt=0
    ).annotate(
        product_price=F('variant__product__selling_price_amount'),
        value=F('stock_quantity') * F('product_price')
    ).aggregate(
        total_value=Coalesce(Sum('value'), Value(0, output_field=FloatField()))
    )['total_value']
    
    return {
        **stats,
        'total_value': total_value,
        'currency': settings.DEFAULT_CURRENCY  #default currency
    }
def get_variant_inventories(
    product_id: int,
    *,
    only_in_stock: bool = False,
    only_active: bool = True,
    include_options: bool = True
) -> List[Dict[str, any]]:
    """
    Get inventory status for all variants of a product
    
    Args:
        product_id: ID of the parent product
        only_in_stock: Only include variants with stock > 0
        only_active: Only include active variants
        include_options: Include variant options data
        
    Returns:
        List of variant inventories with:
        - variant_id
        - sku
        - options (if include_options)
        - stock
        - last_updated
        - is_active
        
    Raises:
        ValidationError: For invalid product ID
    """
    if product_id <= 0:
        raise ValidationError("Product ID must be positive")
    
    queryset = Inventory.objects.filter(
        variant__product_id=product_id
    ).select_related('variant')
    
    if only_in_stock:
        queryset = queryset.filter(stock_quantity__gt=0)
    if only_active:
        queryset = queryset.filter(variant__is_active=True)
    
    if include_options:
        queryset = queryset.prefetch_related(
            'variant__options__attribute'
        )
    
    inventories = []
    for inv in queryset:
        inventory_data = {
            'variant_id': inv.variant_id,
            'sku': inv.variant.sku,
            'stock': inv.stock_quantity,
            'last_updated': inv.last_restock,
            'is_active': inv.variant.is_active,
            'low_stock': inv.stock_quantity <= inv.low_stock_threshold
        }
        
        if include_options:
            inventory_data['options'] = [
                f"{opt.attribute.name}: {opt.value}" 
                for opt in inv.variant.options.all()
            ]
        
        inventories.append(inventory_data)
    
    return inventories

def get_restock_candidates(
    *,
    min_sales_velocity: float = 5.0,
    max_weeks_of_stock: int = 2,
    min_stock: int = 0,
    limit: Optional[int] = None
) -> List[Dict[str, any]]:
    """
    Get variants needing restock based on sales velocity
    
    Args:
        min_sales_velocity: Minimum weekly sales to consider
        max_weeks_of_stock: Maximum weeks of inventory to maintain
        min_stock: Current stock must be above this value
        limit: Maximum number of results to return
        
    Returns:
        List of dictionaries with:
        - variant_id
        - sku
        - current_stock
        - weekly_sales
        - weeks_remaining
        - product_name
        
    Raises:
        ValidationError: For invalid parameters
    """
    if min_sales_velocity < 0:
        raise ValidationError("Sales velocity cannot be negative")
    if max_weeks_of_stock <= 0:
        raise ValidationError("Weeks of stock must be positive")
    if min_stock < 0:
        raise ValidationError("Minimum stock cannot be negative")
    
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
                       (F('weekly_sales') + 0.1),  # Avoid division by zero
        product_name=F('variant__product__name'),
        sku=F('variant__sku')
    ).filter(
        weekly_sales__gte=min_sales_velocity,
        weeks_remaining__lte=max_weeks_of_stock,
        stock_quantity__gt=min_stock,
        variant__is_active=True
    ).select_related('variant__product')
    
    if limit:
        queryset = queryset[:limit]
    
    return list(queryset.values(
        'variant_id',
        'sku',
        'stock_quantity',
        'weekly_sales',
        'weeks_remaining',
        'product_name'
    ).order_by('weeks_remaining'))

def get_inventory_alerts(
    *,
    threshold: Optional[int] = None,
    min_sales_velocity: float = 5.0,
    limit: Optional[int] = None
) -> Dict[str, List[Dict[str, any]]]:
    """
    Get combined low stock and restock alerts
    
    Args:
        threshold: Low stock threshold
        min_sales_velocity: Minimum sales for restock candidates
        limit: Max alerts per type
        
    Returns:
        Dictionary with:
        - low_stock: List of low stock items
        - needs_restock: List of restock candidates
    """
    return {
        'low_stock': get_low_stock_items(
            threshold=threshold,
            limit=limit
        ),
        'needs_restock': get_restock_candidates(
            min_sales_velocity=min_sales_velocity,
            limit=limit
        )
    }