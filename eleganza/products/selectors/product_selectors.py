# eleganza/products/selectors/product_selectors.py
from django.db.models import Prefetch, Q, F, Count, Avg, Min, Max
from django.db.models.functions import Coalesce
from typing import Optional, List, Dict
from django.core.exceptions import ValidationError
from django.db.models import Value, FloatField

from eleganza.products.models import Product, ProductVariant, ProductReview, ProductCategory
from eleganza.products.constants import Defaults
from eleganza.products.validators import (
    validate_id,
    validate_price_range,
    validate_rating,
)

# Reusable annotations
REVIEW_STATS = {
    'avg_rating': Avg('reviews__rating', filter=Q(reviews__is_approved=True)),
    'review_count': Count('reviews', filter=Q(reviews__is_approved=True))
}

DISCOUNT_FILTER = Q(
    Q(discount_percent__gt=0) |
    Q(discount_amount__amount__gt=0)
)

def get_products_cache_key(**kwargs) -> str:
    """Generate unique cache key based on query parameters"""
    from hashlib import md5
    return f"products_{md5(str(kwargs).encode()).hexdigest()}"


def get_products(
    *,
    category_id: Optional[int] = None,
    only_active: bool = True,
    include_variants: bool = False,
    include_review_stats: bool = False,
    discount_threshold: Optional[float] = None,
    only_in_stock: bool = False,
    only_featured: bool = False,
    fields: Optional[List[str]] = None,
    limit: Optional[int] = None,
    offset: int = 0
) -> List[Product]:
    """
    Get products with flexible filtering and optimized queries.
    Uses reusable REVIEW_STATS annotations.
    """
    if category_id is not None:
        validate_id(category_id, "Category ID")
    if discount_threshold is not None and discount_threshold < 0:
        raise ValidationError("Discount threshold must be positive")
    if limit is not None and limit <= 0:
        raise ValidationError("Limit must be positive")

    queryset = Product.objects.all()
    
    # Base filtering
    if only_active:
        queryset = queryset.filter(is_active=True)
    if only_featured:
        queryset = queryset.filter(is_featured=True)
    if category_id:
        queryset = queryset.filter(category_id=category_id)
    
    # Inventory filtering
    if only_in_stock:
        queryset = queryset.filter(
            variants__inventory__stock_quantity__gt=0
        ).distinct()
    
    # Discount filtering
    if discount_threshold:
        queryset = queryset.filter(
            Q(discount_percent__gte=discount_threshold) |
            Q(discount_amount__amount__gte=discount_threshold)
        )
    
    # Related data prefetching
    if include_variants:
        variant_qs = ProductVariant.objects.filter(is_active=True)
        if only_in_stock:
            variant_qs = variant_qs.filter(inventory__stock_quantity__gt=0)
            
        queryset = queryset.prefetch_related(
            Prefetch('variants', 
                   queryset=variant_qs.select_related('inventory'))
        )
    
    if include_review_stats:
        queryset = queryset.annotate(**REVIEW_STATS)
    
    # Field limiting
    if fields:
        queryset = queryset.only(*fields)
    
    # Pagination support
    queryset = queryset.order_by('-is_featured', 'name')
    if limit:
        queryset = queryset[offset:offset + limit]
    
    return list(queryset)

def get_product_detail(
    product_id: int,
    *,
    with_variants: bool = True,
    with_reviews: bool = False,
    with_category: bool = False,
    review_limit: Optional[int] = None,
    review_offset: int = 0
) -> Optional[Product]:
    """
    Get single product with optimized related data loading.
    Uses centralized ID validation.
    """
    validate_id(product_id, "Product ID")
    
    queryset = Product.objects.filter(pk=product_id)
    
    # Variant prefetch
    if with_variants:
        variant_qs = ProductVariant.objects.select_related('inventory')
        if with_reviews:
            variant_qs = variant_qs.prefetch_related('options__attribute')
        queryset = queryset.prefetch_related(
            Prefetch('variants', queryset=variant_qs)
        )
    
    # Review prefetch with pagination
    if with_reviews:
        review_qs = ProductReview.objects.filter(is_approved=True)
        if review_limit:
            review_qs = review_qs[review_offset:review_offset + review_limit]
        queryset = queryset.prefetch_related(
            Prefetch('reviews', 
                   queryset=review_qs.select_related('user')))
    
    # Category select
    if with_category:
        queryset = queryset.select_related('category')
    
    return queryset.first()


def get_featured_products(
    limit: int = 8,
    *,
    only_in_stock: bool = True,
    min_rating: Optional[float] = None,
    fields: Optional[List[str]] = None,
    offset: int = 0
) -> List[Product]:
    """
    Get featured products with optimized query.
    Uses reusable REVIEW_STATS annotations.
    """
    if limit <= 0:
        raise ValidationError("Limit must be positive")
    if min_rating is not None:
        validate_rating(min_rating)

    queryset = Product.objects.filter(
        is_featured=True,
        is_active=True
    ).select_related('category')
    
    if only_in_stock:
        queryset = queryset.filter(
            variants__inventory__stock_quantity__gt=0
        ).distinct()
    
    if min_rating:
        queryset = queryset.annotate(
            avg_rating=REVIEW_STATS['avg_rating']
        ).filter(avg_rating__gte=min_rating)
    
    if fields:
        queryset = queryset.only(*fields)
    
    # Pagination support
    return list(queryset.order_by('?')[offset:offset + limit])

def get_products_by_price_range(
    min_price: float,
    max_price: float,
    currency: str = 'USD',
    *,
    only_in_stock: bool = True,
    only_active: bool = True,
    limit: Optional[int] = None,
    offset: int = 0
) -> List[Product]:
    """
    Get products within price range with inventory check.
    Uses centralized price validation.
    """
    validate_price_range(min_price, max_price)
    if limit is not None and limit <= 0:
        raise ValidationError("Limit must be positive")

    queryset = Product.objects.filter(
        final_price__amount__gte=min_price,
        final_price__amount__lte=max_price,
        final_price__currency=currency,
    )
    
    if only_active:
        queryset = queryset.filter(is_active=True)
    if only_in_stock:
        queryset = queryset.filter(
            variants__inventory__stock_quantity__gt=0
        ).distinct()
    
    # Pagination support
    queryset = queryset.order_by('final_price')
    if limit:
        queryset = queryset[offset:offset + limit]
    
    return list(queryset)

def get_category_products(
    category_id: int,
    *,
    include_subcategories: bool = False,
    only_featured: bool = False,
    only_active: bool = True,
    fields: Optional[List[str]] = None,
    limit: Optional[int] = None,
    offset: int = 0
) -> Dict[str, List[Product]]:
    """
    Get products organized by subcategories.
    Uses reusable annotations and validators.
    """
    validate_id(category_id, "Category ID")
    if limit is not None and limit <= 0:
        raise ValidationError("Limit must be positive")

    # Build category filter
    if include_subcategories:
        categories = ProductCategory.objects.filter(
            Q(id=category_id) | Q(parent_id=category_id)
        )
    else:
        categories = ProductCategory.objects.filter(id=category_id)
    
    # Prefetch products with filtering
    product_qs = Product.objects.all()
    if only_active:
        product_qs = product_qs.filter(is_active=True)
    if only_featured:
        product_qs = product_qs.filter(is_featured=True)
    if fields:
        product_qs = product_qs.only(*fields)
    
    # Pagination support
    if limit:
        product_qs = product_qs[offset:offset + limit]
    
    categories = categories.prefetch_related(
        Prefetch('products', 
               queryset=product_qs.order_by('-is_featured')))
    
    return {
        cat.name: list(cat.products.all())
        for cat in categories
    }


def get_product_review_stats(product_id: int) -> Dict[str, float]:
    """
    Get aggregated review statistics for a product.
    Uses reusable rating distribution logic.
    """
    validate_id(product_id, "Product ID")
    
    stats = ProductReview.objects.filter(
        product_id=product_id,
        is_approved=True
    ).aggregate(
        **REVIEW_STATS,
        **{
            f'stars_{i}': Count('id', filter=Q(rating=i))
            for i in range(1, 6)
        }
    )
    
    return {
        'average_rating': stats['avg_rating'] or 0,
        'review_count': stats['review_count'],
        'rating_distribution': {
            i: stats[f'stars_{i}'] for i in range(1, 6)
        }
    }

def get_products_with_discounts(
    min_discount: float = 10.0,
    *,
    only_active: bool = True,
    only_in_stock: bool = True,
    limit: Optional[int] = None,
    offset: int = 0
) -> List[Product]:
    """
    Get products with significant discounts.
    Uses reusable DISCOUNT_FILTER.
    """
    if min_discount <= 0:
        raise ValidationError("Discount threshold must be positive")
    if limit is not None and limit <= 0:
        raise ValidationError("Limit must be positive")

    queryset = Product.objects.filter(
        DISCOUNT_FILTER,
        is_active=only_active
    )
    
    if only_in_stock:
        queryset = queryset.filter(
            variants__inventory__stock_quantity__gt=0
        ).distinct()
    
    # Pagination support
    queryset = queryset.order_by('-discount_percent')
    if limit:
        queryset = queryset[offset:offset + limit]
    
    return list(queryset)