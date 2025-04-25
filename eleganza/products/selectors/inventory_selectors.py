# eleganza/products/selectors/inventory_selectors.py
from django.db.models import F, Q, Count, Sum, Value, FloatField, Avg
from django.db.models.functions import Coalesce, Cast
from typing import List, Dict, Optional
from django.utils import timezone
from datetime import timedelta
from django.core.exceptions import ValidationError
from eleganza.products.models import Inventory, InventoryHistory, ProductVariant
from eleganza.products.constants import Defaults
from eleganza.products.validators import validate_id, validate_threshold  # Centralized validator
from django.conf import settings


# Reusable annotations
STOCK_STATUS = Coalesce(F('stock_quantity'), Value(0))
LOW_STOCK_FLAG = Q(stock_quantity__lte=F('low_stock_threshold'))


def get_inventory_status_cache_key(variant_id: int) -> str:
    """Generate unique cache key per variant"""
    return f"inventory_status_{variant_id}"


def get_inventory_status(variant_id: int) -> Optional[Dict[str, any]]:
    """
    Get complete inventory status for a single variant with safe defaults.
    
    Args:
        variant_id: ID of the product variant
        
    Returns:
        Dictionary with inventory status or None if not found
    """
    validate_id(variant_id, "Variant ID")
    
    inventory = Inventory.objects.filter(
        variant_id=variant_id
    ).annotate(
        monthly_movement=Coalesce(
            Sum('history__new_stock' - 'history__old_stock', 
                filter=Q(history__timestamp__gte=timezone.now() - timedelta(days=30))),
            Value(0)
        ),
        sku=F('variant__sku'),
        current_stock=STOCK_STATUS,  # Reusable annotation
        low_stock_flag=LOW_STOCK_FLAG  # Reusable condition
    ).values(
        'current_stock',
        'low_stock_threshold',
        'last_restock',
        'monthly_movement',
        'sku',
        'low_stock_flag'
    ).first()
    
    if not inventory:
        return None
    
    return {
        **inventory,
        'variant_id': variant_id
    }

def get_low_stock_items(
    *,
    threshold: Optional[int] = None,
    only_active: bool = True,
    min_stock: int = 0,
    limit: Optional[int] = None,
    offset: int = 0  # Added pagination
) -> List[Dict[str, any]]:
    """
    Get items below stock threshold with product info.
    Uses reusable STOCK_STATUS annotation.
    """
    threshold = threshold or Defaults.LOW_STOCK_THRESHOLD
    validate_threshold(threshold)
    
    if min_stock < 0:
        raise ValidationError("Minimum stock cannot be negative")

    queryset = Inventory.objects.filter(
        stock_quantity__lte=threshold,
        stock_quantity__gte=min_stock
    ).select_related(
        'variant__product'
    ).annotate(
        product_name=F('variant__product__name'),
        sku=F('variant__sku'),
        current_stock=STOCK_STATUS  # Reusable annotation
    )
    
    if only_active:
        queryset = queryset.filter(variant__is_active=True)
    
    # Pagination support
    if limit:
        queryset = queryset[offset:offset + limit]
    
    return list(queryset.values(
        'variant_id',
        'sku',
        'product_name',
        'current_stock',
        'low_stock_threshold'
    ).order_by('current_stock'))

def get_inventory_history(
    variant_id: int,
    *,
    days_back: int = 30,
    limit: Optional[int] = None,
    offset: int = 0,  # Added pagination
    include_metadata: bool = False
) -> List[Dict[str, any]]:
    """
    Get inventory change history for a variant.
    Uses centralized days_back validation.
    """
    validate_id(variant_id, "Variant ID")
    
    if not (1 <= days_back <= 365):
        raise ValidationError("Days back must be between 1 and 365")
    
    history = InventoryHistory.objects.filter(
        inventory__variant_id=variant_id,
        timestamp__gte=timezone.now() - timedelta(days=days_back)
    )
    
    if include_metadata:
        history = history.select_related('inventory__variant')
    
    history = history.order_by('-timestamp')
    
    # Pagination support
    if limit:
        history = history[offset:offset + limit]
    
    base_values = [
        'timestamp',
        'old_stock',
        'new_stock',
        'notes'
    ]
    
    if include_metadata:
        return list(history.annotate(
            delta=F('new_stock') - F('old_stock'),
            sku=F('inventory__variant__sku')
        ).values(*base_values, 'sku'))
    
    return list(history.annotate(
        delta=F('new_stock') - F('old_stock')
    ).values(*base_values))


def get_inventory_summary() -> Dict[str, any]:
    """
    Get store-wide inventory summary statistics.
    Uses Coalesce for safe aggregation.
    """
    stats = Inventory.objects.aggregate(
        total_items=Count('id'),
        out_of_stock=Count('id', filter=Q(stock_quantity=0)),
        low_stock=Count('id', filter=LOW_STOCK_FLAG),  # Reusable condition
        average_stock=Coalesce(Avg('stock_quantity'), Value(0))
    )
    
    total_value = Inventory.objects.filter(
        stock_quantity__gt=0
    ).annotate(
        product_price=Coalesce(F('variant__product__selling_price_amount'), Value(0)),
        value=F('stock_quantity') * F('product_price')
    ).aggregate(
        total_value=Coalesce(Sum('value'), Value(0, output_field=FloatField()))
    )['total_value']
    
    return {
        **stats,
        'total_value': total_value,
        'currency': settings.DEFAULT_CURRENCY
    }

def get_variant_inventories(
    product_id: int,
    *,
    only_in_stock: bool = False,
    only_active: bool = True,
    include_options: bool = True,
    limit: Optional[int] = None,
    offset: int = 0  # Added pagination
) -> List[Dict[str, any]]:
    """
    Get inventory status for all variants of a product.
    Uses centralized ID validation.
    """
    validate_id(product_id, "Product ID")
    
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
    
    # Pagination support
    if limit:
        queryset = queryset[offset:offset + limit]
    
    return [
        {
            'variant_id': inv.variant_id,
            'sku': inv.variant.sku,
            'stock': inv.stock_quantity or 0,  # Safe default
            'last_updated': inv.last_restock,
            'is_active': inv.variant.is_active,
            'low_stock': inv.stock_quantity <= (inv.low_stock_threshold or 0),
            **({'options': [
                f"{opt.attribute.name}: {opt.value}" 
                for opt in inv.variant.options.all()
            ]} if include_options else {})
        }
        for inv in queryset
    ]

def get_restock_candidates(
    *,
    min_sales_velocity: float = 5.0,
    max_weeks_of_stock: int = 2,
    min_stock: int = 0,
    limit: Optional[int] = None,
    offset: int = 0  # Added pagination
) -> List[Dict[str, any]]:
    """
    Get variants needing restock based on sales velocity.
    Uses Coalesce for safe division.
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
                )) / 3,
            Value(0.0)
        ),
        weeks_remaining=Cast('stock_quantity', FloatField()) / 
                       Coalesce(F('weekly_sales'), Value(0.1)),  # Safe division
        product_name=F('variant__product__name'),
        sku=F('variant__sku')
    ).filter(
        weekly_sales__gte=min_sales_velocity,
        weeks_remaining__lte=max_weeks_of_stock,
        stock_quantity__gt=min_stock,
        variant__is_active=True
    ).select_related('variant__product')
    
    # Pagination support
    if limit:
        queryset = queryset[offset:offset + limit]
    
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
    limit: Optional[int] = None,
    offset: int = 0  # Added pagination
) -> Dict[str, List[Dict[str, any]]]:
    """
    Get combined low stock and restock alerts.
    Reuses other selector functions.
    """
    return {
        'low_stock': get_low_stock_items(
            threshold=threshold,
            limit=limit,
            offset=offset
        ),
        'needs_restock': get_restock_candidates(
            min_sales_velocity=min_sales_velocity,
            limit=limit,
            offset=offset
        )
    }