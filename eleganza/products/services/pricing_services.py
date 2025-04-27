from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db.models import Q
from .models import ProductPrice, CostPrice, Discount

# ──────────────────────────────────────────────────
# Product Pricing Services (ProductPrice)
# ──────────────────────────────────────────────────

@transaction.atomic
def create_product_price(
    amount: float,
    currency: str,
    product_id: int = None,
    variant_id: int = None,
    valid_from=None,
    valid_until=None
) -> ProductPrice:
    """UC-PR01: Create a new price for a product or variant"""
    if product_id and variant_id:
        raise ValidationError("Cannot associate with both product and variant simultaneously")
    
    price = ProductPrice(
        amount=amount,
        currency=currency,
        valid_from=valid_from or timezone.now(),
        valid_until=valid_until
    )
    
    if product_id:
        price.product_id = product_id
    elif variant_id:
        price.variant_id = variant_id
    
    price.full_clean()
    price.save()
    return price

@transaction.atomic
def update_product_price(price_id: int, **kwargs) -> ProductPrice:
    """UC-PR02: Update an existing price"""
    price = ProductPrice.objects.get(id=price_id)
    
    if 'product_id' in kwargs and 'variant_id' in kwargs:
        raise ValidationError("Cannot associate with both product and variant simultaneously")
    
    for field, value in kwargs.items():
        setattr(price, field, value)
    
    price.full_clean()
    price.save()
    return price

@transaction.atomic
def delete_product_price(price_id: int) -> None:
    """UC-PR03: Delete a price"""
    ProductPrice.objects.get(id=price_id).delete()

# ──────────────────────────────────────────────────
# Product Cost Services (CostPrice)
# ──────────────────────────────────────────────────

@transaction.atomic
def create_cost_price(
    amount: float,
    product_id: int = None,
    variant_id: int = None,
    vendor_id: int = None,
    valid_from=None
) -> CostPrice:
    """UC-PR04: Create a new cost"""
    if product_id and variant_id:
        raise ValidationError("Cannot associate with both product and variant simultaneously")
    
    cost = CostPrice(
        amount=amount,
        valid_from=valid_from or timezone.now(),
        vendor_id=vendor_id
    )
    
    if product_id:
        cost.product_id = product_id
    elif variant_id:
        cost.variant_id = variant_id
    
    cost.full_clean()
    cost.save()
    return cost

@transaction.atomic
def update_cost_price(cost_id: int, **kwargs) -> CostPrice:
    """UC-PR05: Update an existing cost"""
    cost = CostPrice.objects.get(id=cost_id)
    
    if 'product_id' in kwargs and 'variant_id' in kwargs:
        raise ValidationError("Cannot associate with both product and variant simultaneously")
    
    for field, value in kwargs.items():
        setattr(cost, field, value)
    
    cost.full_clean()
    cost.save()
    return cost

@transaction.atomic
def delete_cost_price(cost_id: int) -> None:
    """UC-PR06: Delete a cost"""
    CostPrice.objects.get(id=cost_id).delete()

# ──────────────────────────────────────────────────
# Discount Services (Discount)
# ──────────────────────────────────────────────────

@transaction.atomic
def create_discount(
    name: str,
    discount_type: str,
    amount: float,
    valid_from=None,
    valid_until=None,
    min_purchase: float = None
) -> Discount:
    """UC-PR07: Create a new discount"""
    discount = Discount(
        name=name,
        discount_type=discount_type,
        amount=amount,
        valid_from=valid_from or timezone.now(),
        valid_until=valid_until,
        min_purchase=min_purchase
    )
    discount.full_clean()
    discount.save()
    return discount

@transaction.atomic
def update_discount(discount_id: int, **kwargs) -> Discount:
    """UC-PR08: Update an existing discount"""
    discount = Discount.objects.get(id=discount_id)
    
    for field, value in kwargs.items():
        setattr(discount, field, value)
    
    discount.full_clean()
    discount.save()
    return discount

@transaction.atomic
def toggle_discount_status(discount_id: int) -> Discount:
    """UC-PR09: Toggle the status of a discount"""
    discount = Discount.objects.get(id=discount_id)
    discount.is_active = not discount.is_active
    discount.save()
    return discount

@transaction.atomic
def delete_discount(discount_id: int) -> None:
    """UC-PR10: Delete a discount"""
    Discount.objects.get(id=discount_id).delete()