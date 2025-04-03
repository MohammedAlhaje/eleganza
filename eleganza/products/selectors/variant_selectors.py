from django.db.models import Prefetch, Q, F, Count, Subquery, OuterRef, FloatField
from typing import List, Dict, Optional, Sequence
from django.core.exceptions import ValidationError
from django.core.cache import cache
from django.db.models.functions import Coalesce, Cast
from ..models import ProductVariant, ProductOption, Inventory
from ..constants import FieldLengths, Defaults

def validate_variant_id(variant_id: int) -> None:
    """Validate variant ID parameter"""
    if variant_id <= 0:
        raise ValidationError("Variant ID must be positive")

def validate_product_id(product_id: int) -> None:
    """Validate product ID parameter"""
    if product_id <= 0:
        raise ValidationError("Product ID must be positive")

def validate_option_ids(option_ids: List[int]) -> None:
    """Validate option IDs"""
    if not option_ids:
        raise ValidationError("Option IDs cannot be empty")
    if any(oid <= 0 for oid in option_ids):
        raise ValidationError("Option IDs must be positive")

def get_variants_for_product(
    product_id: int,
    *,
    only_active: bool = True,
    include_inventory: bool = True,
    include_options: bool = True,
    fields: Optional[List[str]] = None,
    limit: Optional[int] = None
) -> List[ProductVariant]:
    """
    Get variants for a product with configurable related data
    
    Args:
        product_id: Parent product ID
        only_active: Filter inactive variants
        include_inventory: Prefetch inventory data
        include_options: Prefetch option/attribute data
        fields: Specific fields to return (None for all)
        limit: Maximum variants to return
        
    Returns:
        List of ProductVariant instances
        
    Raises:
        ValidationError: For invalid parameters
    """
    validate_product_id(product_id)
    if limit is not None and limit <= 0:
        raise ValidationError("Limit must be positive")

    queryset = ProductVariant.objects.filter(product_id=product_id)
    
    if only_active:
        queryset = queryset.filter(is_active=True)
    
    if include_inventory:
        queryset = queryset.select_related('inventory')
    
    if include_options:
        option_qs = ProductOption.objects.select_related('attribute')
        if fields and 'options' not in fields:
            option_qs = option_qs.only('id', 'value', 'attribute__name')
        queryset = queryset.prefetch_related(
            Prefetch('options', queryset=option_qs)
        )
    
    if fields:
        queryset = queryset.only(*fields)
    
    if limit:
        queryset = queryset[:limit]
    
    return list(queryset.order_by('-is_default', 'sku'))

def get_variant_with_full_details(
    variant_id: int,
    *,
    include_inventory_history: bool = False,
    history_days: int = 30
) -> Optional[Dict[str, any]]:
    """
    Get single variant with complete related data
    
    Args:
        variant_id: Target variant ID
        include_inventory_history: Include inventory movement data
        history_days: Days of history to include (1-365)
        
    Returns:
        Dictionary with variant details and related data or None
        
    Raises:
        ValidationError: For invalid parameters
    """
    validate_variant_id(variant_id)
    if not (1 <= history_days <= 365):
        raise ValidationError("History days must be between 1 and 365")

    variant = ProductVariant.objects.filter(
        pk=variant_id
    ).select_related(
        'product',
        'inventory'
    ).prefetch_related(
        Prefetch('options',
               queryset=ProductOption.objects.select_related('attribute'))
    ).annotate(
        product_name=F('product__name'),
        product_slug=F('product__slug')
    ).values(
        'id',
        'sku',
        'is_default',
        'is_active',
        'price_modifier',
        'product_id',
        'product_name',
        'product_slug',
        'inventory__stock_quantity',
        'inventory__low_stock_threshold',
        'inventory__last_restock'
    ).first()
    
    if not variant:
        return None
    
    result = dict(variant)
    
    # Convert MoneyField to serializable format
    result['price_modifier'] = {
        'amount': float(variant['price_modifier'].amount),
        'currency': str(variant['price_modifier'].currency)
    }
    
    # Get options data
    options = ProductOption.objects.filter(
        variants=variant_id
    ).select_related('attribute').values(
        'id',
        'value',
        'attribute__name',
        'attribute__code'
    )
    result['options'] = list(options)
    
    # Include inventory history if requested
    if include_inventory_history:
        from .inventory_selectors import get_inventory_history
        result['inventory_history'] = get_inventory_history(
            variant_id,
            days_back=history_days
        )
    
    return result

def get_variants_by_options(
    product_id: int,
    option_ids: List[int],
    *,
    only_in_stock: bool = False,
    only_active: bool = True,
    limit: Optional[int] = None
) -> List[ProductVariant]:
    """
    Find variants matching specific option combinations
    
    Args:
        product_id: Parent product ID
        option_ids: List of ProductOption IDs
        only_in_stock: Filter to items with inventory
        only_active: Only include active variants
        limit: Maximum variants to return
        
    Returns:
        List of matching ProductVariant instances
        
    Raises:
        ValidationError: For invalid parameters
    """
    validate_product_id(product_id)
    validate_option_ids(option_ids)
    if limit is not None and limit <= 0:
        raise ValidationError("Limit must be positive")

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
    
    if only_active:
        queryset = queryset.filter(is_active=True)
    
    queryset = queryset.prefetch_related(
        Prefetch('options',
               queryset=ProductOption.objects.select_related('attribute'))
    )
    
    if limit:
        queryset = queryset[:limit]
    
    return list(queryset)

@cache(60 * 30)  # Cache for 30 minutes
def get_default_variant(
    product_id: int,
    *,
    only_in_stock: bool = False
) -> Optional[ProductVariant]:
    """
    Get the default variant for a product
    
    Args:
        product_id: Parent product ID
        only_in_stock: Only return if variant has inventory
        
    Returns:
        Default ProductVariant or None
        
    Raises:
        ValidationError: For invalid product ID
    """
    validate_product_id(product_id)

    queryset = ProductVariant.objects.filter(
        product_id=product_id,
        is_default=True
    ).select_related('inventory')
    
    if only_in_stock:
        queryset = queryset.filter(
            inventory__stock_quantity__gt=0
        )
    
    return queryset.first()

def get_variant_inventory_status(
    variant_id: int,
    *,
    include_historical: bool = False,
    historical_days: int = 30
) -> Dict[str, any]:
    """
    Get comprehensive inventory status for a variant
    
    Args:
        variant_id: Target variant ID
        include_historical: Include recent movement data
        historical_days: Days of history to include (1-365)
        
    Returns:
        Dictionary with:
        - variant_id
        - sku
        - current_stock
        - low_stock_threshold
        - last_restock
        - historical_changes (if requested)
        
    Raises:
        ValidationError: For invalid parameters
    """
    validate_variant_id(variant_id)
    if not (1 <= historical_days <= 365):
        raise ValidationError("Historical days must be between 1 and 365")

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
            variant['id'],
            days_back=historical_days
        )
    
    return result

@cache(60 * 60)  # Cache for 1 hour
def get_variants_with_low_stock(
    product_id: Optional[int] = None,
    *,
    threshold: Optional[int] = None,
    limit: Optional[int] = None
) -> List[Dict[str, any]]:
    """
    Get variants below stock threshold
    
    Args:
        product_id: Optional parent product filter
        threshold: Custom low stock threshold
        limit: Maximum results to return
        
    Returns:
        List of dictionaries with:
        - variant_id
        - sku
        - product_name
        - current_stock
        - threshold
        
    Raises:
        ValidationError: For invalid parameters
    """
    if product_id is not None:
        validate_product_id(product_id)
    if threshold is not None and threshold <= 0:
        raise ValidationError("Threshold must be positive")
    if limit is not None and limit <= 0:
        raise ValidationError("Limit must be positive")

    threshold = threshold or Defaults.LOW_STOCK_THRESHOLD
    
    queryset = ProductVariant.objects.filter(
        inventory__stock_quantity__lte=threshold,
        is_active=True
    ).select_related(
        'product',
        'inventory'
    )
    
    if product_id:
        queryset = queryset.filter(product_id=product_id)
    
    queryset = queryset.annotate(
        product_name=F('product__name'),
        current_stock=F('inventory__stock_quantity'),
        threshold=F('inventory__low_stock_threshold')
    ).values(
        'id',
        'sku',
        'product_name',
        'current_stock',
        'threshold'
    ).order_by('current_stock')
    
    if limit:
        queryset = queryset[:limit]
    
    return list(queryset)

@cache(60 * 60)  # Cache for 1 hour
def get_variant_price_range(product_id: int) -> Optional[Dict[str, float]]:
    """
    Get min/max pricing for a product's variants
    
    Args:
        product_id: Parent product ID
        
    Returns:
        Dictionary with:
        - min_price
        - max_price
        - currency
        or None if no variants
        
    Raises:
        ValidationError: For invalid product ID
    """
    validate_product_id(product_id)

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
    only_in_stock: bool = False,
    only_active: bool = True,
    include_pricing: bool = True
) -> Dict[str, List[Dict[str, any]]]:
    """
    Group variants by attribute option
    
    Args:
        product_id: Parent product ID
        attribute_id: Target attribute ID
        only_in_stock: Filter to available variants
        only_active: Only include active variants
        include_pricing: Include price modifier in results
        
    Returns:
        Dictionary {option_value: [variant_data]}
        
    Raises:
        ValidationError: For invalid parameters
    """
    validate_product_id(product_id)
    if attribute_id <= 0:
        raise ValidationError("Attribute ID must be positive")

    variants = ProductVariant.objects.filter(
        product_id=product_id,
        options__attribute_id=attribute_id
    )
    
    if only_in_stock:
        variants = variants.filter(inventory__stock_quantity__gt=0)
    if only_active:
        variants = variants.filter(is_active=True)
    
    variants = variants.prefetch_related(
        'options'
    ).annotate(
        option_value=Subquery(
            ProductOption.objects.filter(
                attribute_id=attribute_id,
                variants=OuterRef('pk')
            ).values('value')[:1]
        ),
        in_stock=Q(inventory__stock_quantity__gt=0)
    )
    
    result = {}
    for variant in variants:
        value = variant.option_value
        if value not in result:
            result[value] = []
        
        variant_data = {
            'id': variant.id,
            'sku': variant.sku,
            'in_stock': variant.in_stock,
            'is_default': variant.is_default
        }
        
        if include_pricing:
            variant_data['price_modifier'] = {
                'amount': float(variant.price_modifier.amount),
                'currency': str(variant.price_modifier.currency)
            }
        
        result[value].append(variant_data)
    
    return result

def get_variant_availability(
    variant_ids: Sequence[int],
    *,
    threshold: Optional[int] = None
) -> Dict[int, Dict[str, any]]:
    """
    Get availability status for multiple variants
    
    Args:
        variant_ids: Sequence of variant IDs
        threshold: Custom low stock threshold
        
    Returns:
        Dictionary with variant IDs as keys and status info as values
    """
    if not variant_ids:
        return {}
    
    threshold = threshold or Defaults.LOW_STOCK_THRESHOLD
    
    variants = ProductVariant.objects.filter(
        id__in=variant_ids
    ).select_related('inventory').values(
        'id',
        'inventory__stock_quantity',
        'inventory__low_stock_threshold'
    )
    
    return {
        v['id']: {
            'in_stock': v['inventory__stock_quantity'] > 0,
            'low_stock': v['inventory__stock_quantity'] <= threshold,
            'stock_quantity': v['inventory__stock_quantity']
        }
        for v in variants
    }