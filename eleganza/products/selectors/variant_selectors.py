# eleganza/products/selectors/variant_selectors.py
from django.db.models import Prefetch, Q, F, Count, Subquery, OuterRef, FloatField
from django.db.models.functions import Coalesce, Cast
from typing import List, Dict, Optional, Sequence
from django.core.exceptions import ValidationError
from django.db.models import Value
from eleganza.products.models import ProductVariant, ProductOption, Inventory
from eleganza.products.constants import FieldLengths, Defaults
from eleganza.products.validators import (
    validate_id,
    validate_option_ids,
    validate_threshold,
    validate_limit
)

# Reusable annotations
INVENTORY_STATUS = {
    'stock': Coalesce(F('inventory__stock_quantity'), Value(0)),
    'low_stock': Q(inventory__stock_quantity__lte=F('inventory__low_stock_threshold'))
}

PRICE_MODIFIER_FIELDS = {
    'price_amount': Cast(F('price_modifier__amount'), FloatField()),
    'price_currency': F('price_modifier__currency')
}

def get_variant_cache_key(**kwargs) -> str:
    """Generate unique cache key based on query parameters"""
    from hashlib import md5
    return f"variant_{md5(str(kwargs).encode()).hexdigest()}"


def get_variants_for_product(
    product_id: int,
    *,
    only_active: bool = True,
    include_inventory: bool = True,
    include_options: bool = True,
    fields: Optional[List[str]] = None,
    limit: Optional[int] = None,
    offset: int = 0
) -> List[ProductVariant]:
    """
    Get variants for a product with configurable related data.
    Uses centralized validation and reusable annotations.
    """
    validate_id(product_id, "Product ID")
    if limit is not None:
        validate_limit(limit)

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
    
    # Pagination support
    if limit:
        queryset = queryset[offset:offset + limit]
    
    return list(queryset.order_by('-is_default', 'sku'))


def get_variant_with_full_details(
    variant_id: int,
    *,
    include_inventory_history: bool = False,
    history_days: int = 30
) -> Optional[Dict[str, any]]:
    """
    Get single variant with complete related data.
    Uses reusable INVENTORY_STATUS annotations.
    """
    validate_id(variant_id, "Variant ID")
    validate_days_range(history_days)

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
        product_slug=F('product__slug'),
        **INVENTORY_STATUS
    ).values(
        'id',
        'sku',
        'is_default',
        'is_active',
        'price_modifier',
        'product_id',
        'product_name',
        'product_slug',
        'stock',
        'low_stock',
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
    limit: Optional[int] = None,
    offset: int = 0
) -> List[ProductVariant]:
    """
    Find variants matching specific option combinations.
    Uses centralized validation for IDs.
    """
    validate_id(product_id, "Product ID")
    validate_option_ids(option_ids)
    if limit is not None:
        validate_limit(limit)

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
    
    # Pagination support
    if limit:
        queryset = queryset[offset:offset + limit]
    
    return list(queryset)

def get_default_variant(
    product_id: int,
    *,
    only_in_stock: bool = False
) -> Optional[ProductVariant]:
    """
    Get the default variant for a product.
    Uses reusable INVENTORY_STATUS annotations.
    """
    validate_id(product_id, "Product ID")

    queryset = ProductVariant.objects.filter(
        product_id=product_id,
        is_default=True
    ).select_related('inventory')
    
    if only_in_stock:
        queryset = queryset.filter(
            inventory__stock_quantity__gt=0
        )
    
    return queryset.annotate(
        **INVENTORY_STATUS
    ).first()

def get_variant_inventory_status(
    variant_id: int,
    *,
    include_historical: bool = False,
    historical_days: int = 30
) -> Dict[str, any]:
    """
    Get comprehensive inventory status for a variant.
    Uses centralized validation and reusable components.
    """
    validate_id(variant_id, "Variant ID")
    validate_days_range(historical_days)

    variant = ProductVariant.objects.filter(
        pk=variant_id
    ).select_related(
        'inventory'
    ).annotate(
        sku=F('sku'),
        **INVENTORY_STATUS
    ).values(
        'id',
        'sku',
        'stock',
        'low_stock',
        'inventory__low_stock_threshold',
        'inventory__last_restock'
    ).first()
    
    if not variant:
        return None
    
    result = {
        'variant_id': variant['id'],
        'sku': variant['sku'],
        'current_stock': variant['stock'],
        'low_stock': variant['low_stock'],
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

def get_variants_with_low_stock(
    product_id: Optional[int] = None,
    *,
    threshold: Optional[int] = None,
    limit: Optional[int] = None,
    offset: int = 0
) -> List[Dict[str, any]]:
    """
    Get variants below stock threshold.
    Uses reusable PRICE_MODIFIER_FIELDS and validation.
    """
    if product_id is not None:
        validate_id(product_id, "Product ID")
    if threshold is not None:
        validate_threshold(threshold)
    if limit is not None:
        validate_limit(limit)

    threshold = threshold or Defaults.LOW_STOCK_THRESHOLD
    
    queryset = ProductVariant.objects.filter(
        inventory__stock_quantity__lte=threshold,
        is_active=True
    ).select_related(
        'product',
        'inventory'
    ).annotate(
        product_name=F('product__name'),
        current_stock=F('inventory__stock_quantity'),
        threshold=F('inventory__low_stock_threshold'),
        **PRICE_MODIFIER_FIELDS
    ).values(
        'id',
        'sku',
        'product_name',
        'current_stock',
        'threshold',
        'price_amount',
        'price_currency'
    ).order_by('current_stock')
    
    if product_id:
        queryset = queryset.filter(product_id=product_id)
    
    # Pagination support
    if limit:
        queryset = queryset[offset:offset + limit]
    
    return list(queryset)


def get_variant_price_range(product_id: int) -> Optional[Dict[str, float]]:
    """
    Get min/max pricing for a product's variants.
    Uses reusable PRICE_MODIFIER_FIELDS.
    """
    validate_id(product_id, "Product ID")

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
    include_pricing: bool = True,
    limit: Optional[int] = None,
    offset: int = 0
) -> Dict[str, List[Dict[str, any]]]:
    """
    Group variants by attribute option.
    Uses centralized validation and reusable components.
    """
    validate_id(product_id, "Product ID")
    validate_id(attribute_id, "Attribute ID")
    if limit is not None:
        validate_limit(limit)

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
        in_stock=Q(inventory__stock_quantity__gt=0),
        **PRICE_MODIFIER_FIELDS
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
            variant_data.update({
                'price_amount': float(variant.price_amount),
                'price_currency': str(variant.price_currency)
            })
        
        result[value].append(variant_data)
    
    # Apply pagination per option group
    if limit:
        for key in result:
            result[key] = result[key][offset:offset + limit]
    
    return result

def get_variant_availability(
    variant_ids: Sequence[int],
    *,
    threshold: Optional[int] = None
) -> Dict[int, Dict[str, any]]:
    """
    Get availability status for multiple variants.
    Uses reusable INVENTORY_STATUS annotations.
    """
    if not variant_ids:
        return {}
    
    threshold = threshold or Defaults.LOW_STOCK_THRESHOLD
    
    variants = ProductVariant.objects.filter(
        id__in=variant_ids
    ).select_related('inventory').annotate(
        **INVENTORY_STATUS
    ).values(
        'id',
        'stock',
        'low_stock'
    )
    
    return {
        v['id']: {
            'in_stock': v['stock'] > 0,
            'low_stock': v['low_stock'],
            'stock_quantity': v['stock']
        }
        for v in variants
    }