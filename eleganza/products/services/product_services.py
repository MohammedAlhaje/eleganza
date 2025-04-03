from django.db import transaction
from django.db.models import Case, When, Value, F
from django.core.exceptions import ValidationError
from typing import Sequence, Dict, Any, Union, List
from djmoney.money import Money
from django.db.models import QuerySet
from eleganza.products.models import Product, ProductVariant
from eleganza.products.constants import DiscountTypes
from eleganza.core.utils import chunked_queryset

@transaction.atomic
def calculate_product_final_price(product: Product) -> Money:
    """
    Calculate final price after applying discounts.
    
    Args:
        product: Product instance to calculate price for
        
    Returns:
        Calculated final price as Money object
        
    Raises:
        ValidationError: For invalid discount configurations
    """
    try:
        if product.discount_type == DiscountTypes.FIXED:
            if not product.discount_amount:
                raise ValidationError("Fixed discount requires amount")
            if product.discount_amount.currency != product.selling_price.currency:
                raise ValidationError("Currency mismatch in discount")
            return product.selling_price - product.discount_amount
            
        elif product.discount_type == DiscountTypes.PERCENTAGE:
            if not product.discount_percent:
                raise ValidationError("Percentage discount requires value")
            discount = product.selling_price.amount * (product.discount_percent / 100)
            return product.selling_price - Money(discount, product.selling_price.currency)
            
        return product.selling_price
        
    except Exception as e:
        raise ValidationError(f"Price calculation failed: {str(e)}")

@transaction.atomic
def update_product_pricing(product: Product) -> Product:
    """
    Update all price-related fields with validation.
    
    Args:
        product: Product instance to update
        
    Returns:
        Updated Product instance
        
    Raises:
        ValidationError: For invalid price configurations
    """
    try:
        if product.selling_price.amount <= 0:
            raise ValidationError("Price must be greater than zero")
        
        product.final_price = calculate_product_final_price(product)
        product.full_clean()
        product.save(update_fields=['final_price'])
        
        if product.has_variants:
            update_variant_prices(product.id)
            
        return product
        
    except Exception as e:
        raise ValidationError(str(e))

@transaction.atomic
def toggle_product_activation(product_id: int, is_active: bool) -> Product:
    """
    Activate/deactivate product and cascade to variants.
    
    Args:
        product_id: ID of product to update
        is_active: New activation status
        
    Returns:
        Updated Product instance
        
    Raises:
        ValidationError: If product doesn't exist
    """
    try:
        with transaction.atomic():
            product = Product.objects.select_for_update().get(pk=product_id)
            
            if product.is_active == is_active:
                return product
                
            product.is_active = is_active
            product.save(update_fields=['is_active'])
            
            ProductVariant.objects.filter(product=product).update(is_active=is_active)
                
            return product
            
    except Product.DoesNotExist:
        raise ValidationError(f"Product with ID {product_id} not found")

@transaction.atomic
def bulk_update_products(
    product_ids: Sequence[int],
    update_data: Dict[str, Any],
) -> int:
    """
    Bulk update products with optimized pricing recalculation.
    
    Args:
        product_ids: Sequence of product IDs
        update_data: Fields to update
        
    Returns:
        Number of successfully updated products
        
    Raises:
        ValidationError: For invalid operations
    """
    if not update_data:
        raise ValidationError("No update data provided")
        
    if 'selling_price' in update_data and update_data['selling_price'].amount <= 0:
        raise ValidationError("Price must be positive")

    with transaction.atomic():
        products = Product.objects.filter(
            id__in=product_ids
        ).select_for_update()
        
        # Validate existence
        found_ids = set(products.values_list('id', flat=True))
        if missing := set(product_ids) - found_ids:
            raise ValidationError(f"Invalid product IDs: {missing}")

        updated = products.update(**update_data)
        
        # Handle pricing updates
        if 'selling_price' in update_data or 'discount_type' in update_data:
            price_updates = []
            for product in products:
                try:
                    final_price = calculate_product_final_price(product)
                    price_updates.append(When(id=product.id, then=Value(final_price)))
                except Exception:
                    continue
            
            if price_updates:
                Product.objects.filter(id__in=found_ids).update(
                    final_price=Case(*price_updates, default=F('final_price')))
                
            # Batch update variants
            if any(p.has_variants for p in products):
                for batch in chunked_queryset(products, 50):
                    update_variant_prices([p.id for p in batch])
    
    return updated

def update_variant_prices(product_ids: Union[int, Sequence[int]]) -> int:
    """
    Update prices for variants of one or multiple products.
    Accepts either single product ID or sequence of product IDs.
    
    Args:
        product_ids: Either a single product ID or sequence of product IDs
        
    Returns:
        Number of variants updated
    """
    if isinstance(product_ids, int):
        product_ids = [product_ids]
    
    variants = ProductVariant.objects.filter(
        product_id__in=product_ids
    ).select_related('product').prefetch_related('attributes')
    
    updates = []
    for variant in variants:
        # Calculate new price modifier
        modifier_amount = sum(
            attr.value_modifier.amount 
            for attr in variant.attributes.all() 
            if hasattr(attr, 'value_modifier')
        )
        new_modifier = Money(modifier_amount, variant.product.selling_price.currency)
        
        # Check if update needed
        if variant.price_modifier != new_modifier:
            variant.price_modifier = new_modifier
            updates.append(variant)
    
    # Perform bulk update if needed
    if updates:
        ProductVariant.objects.bulk_update(updates, ['price_modifier'])
    
    return len(updates)