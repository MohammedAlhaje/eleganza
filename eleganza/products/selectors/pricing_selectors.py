from django.db.models import Q, QuerySet
from django.utils import timezone
from .models import ProductPrice, CostPrice, Discount

def get_current_price(product_id: int = None, variant_id: int = None) -> ProductPrice:
    """UC-PR11: Retrieve the current price"""
    now = timezone.now()
    query = Q(valid_from__lte=now) & (Q(valid_until__gt=now) | Q(valid_until__isnull=True))
    
    if product_id:
        return ProductPrice.objects.filter(
            query,
            product_id=product_id
        ).order_by('-valid_from').first()
    
    if variant_id:
        return ProductPrice.objects.filter(
            query,
            variant_id=variant_id
        ).order_by('-valid_from').first()

def get_current_cost(product_id: int = None, variant_id: int = None) -> CostPrice:
    """UC-PR12: Retrieve the current cost"""
    if product_id:
        return CostPrice.objects.filter(
            product_id=product_id
        ).order_by('-valid_from').first()
    
    if variant_id:
        return CostPrice.objects.filter(
            variant_id=variant_id
        ).order_by('-valid_from').first()

def get_active_discounts() -> QuerySet:
    """UC-PR13: Retrieve active discounts"""
    now = timezone.now()
    return Discount.objects.filter(
        Q(valid_until__gte=now) | Q(valid_until__isnull=True),
        is_active=True,
        valid_from__lte=now
    )

def get_product_discounts(product_id: int) -> QuerySet:
    """Retrieve discounts applied to a product"""
    return get_active_discounts().filter(
        Q(products__id=product_id) |
        Q(categories__products__id=product_id)
    ).distinct()