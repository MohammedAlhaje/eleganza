from django.db.models import Prefetch, Q, F, Count, Subquery, OuterRef
from typing import List, Dict, Optional
from .models import ProductVariant, ProductOption, Inventory
from .constants import FieldLengths

def get_variants_for_product(
    product_id: int,
    *,
    only_active: bool = True,
    include_inventory: bool = True,
    include_options: bool = True
) -> List[ProductVariant]:
    """
    Get variants for a product with configurable related data
    
    Args:
        product_id: Parent product ID
        only_active: Filter inactive variants
        include_inventory: Prefetch inventory data
        include_options: Prefetch option/attribute data
        
    Returns:
        List of ProductVariant instances
    """
    queryset = ProductVariant.objects.filter(product_id=product_id)
    
    if only_active:
        queryset = queryset.filter(is_active=True)
    
    if include_inventory:
        queryset = queryset.select_related('inventory')
    
    if include_options:
        queryset = queryset.prefetch_related(
            Prefetch('options',
                   queryset=ProductOption.objects.select_related('attribute'))
        )
    
    return list(queryset.order_by('-is_default', 'sku'))

def get_variant_with_full_details(variant_id: int) -> Optional[ProductVariant]:
    """
    Get single variant with complete related data
    
    Args:
        variant_id: Target variant ID
        
    Returns:
        ProductVariant instance with:
        - Product
        - Inventory
        - Options/Attributes
        or None if not found
    """
    return ProductVariant.objects.filter(
        pk=variant_id
    ).select_related(
        'product',
        'inventory'
    ).prefetch_related(
        Prefetch('options',
               queryset=ProductOption.objects.select_related('attribute'))
    ).first()

def get_variants_by_options(
    product_id: int,
    option_ids: List[int],
    *,
    only_in_stock: bool = False
) -> List[ProductVariant]:
    """
    Find variants matching specific option combinations
    
    Args:
        product_id: Parent product ID
        option_ids: List of ProductOption IDs
        only_in_stock: Filter to items with inventory
        
    Returns:
        List of matching ProductVariant instances
    """
    queryset = ProductVariant.objects.filter(
        product_id=product_id,
        options__in=option_ids
    ).annotate(
        option_count=Count('options')
    ).filter(
        option_count=len(option_ids)  # Must have all specified options
    ).distinct()
    
    if only_in_stock:
        queryset = queryset.filter(
            inventory__stock_quantity__gt=0
        )
    
    return list(queryset.prefetch_related(
        Prefetch('options',
               queryset=ProductOption.objects.select_related('attribute'))
    ))

def get_default_variant(product_id: int) -> Optional[ProductVariant]:
    """
    Get the default variant for a product
    
    Args:
        product_id: Parent product ID
        
    Returns:
        Default ProductVariant or None
    """
    return ProductVariant.objects.filter(
        product_id=product_id,
        is_default=True
    ).select_related('inventory').first()

def get_variant_inventory_status(
    variant_id: int,
    *,
    include_historical: bool = False
) -> Dict[str, any]:
    """
    Get comprehensive inventory status for a variant
    
    Args:
        variant_id: Target variant ID
        include_historical: Include recent movement data
        
    Returns:
        Dictionary with:
        - variant_id
        - sku
        - current_stock
        - low_stock_threshold
        - last_restock
        - historical_changes (if requested)
    """
    variant = ProductVariant.objects.filter(
        pk=variant_id
    ).select_related(
        'inventory'
    ).annotate(
        sku=F('sku')
    ).values(
        'id',
        'sku',
        'inventory__stock_quantity',
        'inventory__low_stock_threshold',
        'inventory__last_restock'
    ).first()
    
    if not variant:
        return None
    
    result = {
        'variant_id': variant['id'],
        'sku': variant['sku'],
        'current_stock': variant['inventory__stock_quantity'],
        'low_stock_threshold': variant['inventory__low_stock_threshold'],
        'last_restock': variant['inventory__last_restock']
    }
    
    if include_historical:
        from .inventory_selectors import get_inventory_history
        result['historical_changes'] = get_inventory_history(
            variant['inventory_id'],
            days_back=30
        )
    
    return result

def get_variants_with_low_stock(
    product_id: Optional[int] = None,
    *,
    threshold: Optional[int] = None
) -> List[Dict[str, any]]:
    """
    Get variants below stock threshold
    
    Args:
        product_id: Optional parent product filter
        threshold: Custom low stock threshold
        
    Returns:
        List of dictionaries with:
        - variant_id
        - sku
        - product_name
        - current_stock
        - threshold
    """
    queryset = ProductVariant.objects.filter(
        inventory__stock_quantity__lte=threshold or Defaults.LOW_STOCK_THRESHOLD,
        is_active=True
    ).select_related(
        'product',
        'inventory'
    )
    
    if product_id:
        queryset = queryset.filter(product_id=product_id)
    
    return list(queryset.annotate(
        product_name=F('product__name'),
        current_stock=F('inventory__stock_quantity'),
        threshold=F('inventory__low_stock_threshold')
    ).values(
        'id',
        'sku',
        'product_name',
        'current_stock',
        'threshold'
    ).order_by('current_stock'))

def get_variant_price_range(product_id: int) -> Dict[str, float]:
    """
    Get min/max pricing for a product's variants
    
    Args:
        product_id: Parent product ID
        
    Returns:
        Dictionary with:
        - min_price
        - max_price
        - currency
    """
    from django.db.models import Min, Max
    result = ProductVariant.objects.filter(
        product_id=product_id,
        is_active=True
    ).aggregate(
        min_price=Min('price_modifier'),
        max_price=Max('price_modifier')
    )
    
    if not result['min_price']:
        return None
        
    return {
        'min_price': float(result['min_price'].amount),
        'max_price': float(result['max_price'].amount),
        'currency': str(result['min_price'].currency)
    }

def get_variants_by_attribute(
    product_id: int,
    attribute_id: int,
    *,
    only_in_stock: bool = False
) -> Dict[str, List[Dict[str, any]]]:
    """
    Group variants by attribute option
    
    Args:
        product_id: Parent product ID
        attribute_id: Target attribute ID
        only_in_stock: Filter to available variants
        
    Returns:
        Dictionary {option_value: [variant_data]}
    """
    variants = ProductVariant.objects.filter(
        product_id=product_id,
        options__attribute_id=attribute_id
    )
    
    if only_in_stock:
        variants = variants.filter(inventory__stock_quantity__gt=0)
    
    variants = variants.prefetch_related(
        'options'
    ).annotate(
        option_value=Subquery(
            ProductOption.objects.filter(
                attribute_id=attribute_id,
                variants=OuterRef('pk')
            ).values('value')[:1]
        )
    )
    
    result = {}
    for variant in variants:
        value = variant.option_value
        if value not in result:
            result[value] = []
        
        result[value].append({
            'id': variant.id,
            'sku': variant.sku,
            'price_modifier': variant.price_modifier.amount,
            'in_stock': variant.inventory.stock_quantity > 0
        })
    
    return result