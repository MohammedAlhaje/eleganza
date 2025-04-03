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