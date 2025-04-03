from django.db.models import Prefetch, Q, F, Count, Avg, Min, Max
from typing import Optional, List, Dict
from django.core.exceptions import ValidationError
from django.core.cache import cache
from ..models import Product, ProductVariant, ProductReview, ProductCategory
from ..constants import Defaults

def validate_product_id(product_id: int) -> None:
    """Validate product ID parameter"""
    if product_id <= 0:
        raise ValidationError("Product ID must be positive")

def validate_price_range(min_price: float, max_price: float) -> None:
    """Validate price range parameters"""
    if min_price < 0 or max_price < 0:
        raise ValidationError("Prices cannot be negative")
    if min_price > max_price:
        raise ValidationError("Min price cannot exceed max price")

@cache(60 * 60)  # Cache for 1 hour
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
    limit: Optional[int] = None
) -> List[Product]:
    """
    Get products with flexible filtering and optimized queries
    
    Args:
        category_id: Filter by category
        only_active: Only include active products
        include_variants: Prefetch variants data
        include_review_stats: Include review aggregates
        discount_threshold: Minimum discount percentage/amount
        only_in_stock: Only include products with available inventory
        only_featured: Only include featured products
        fields: Specific fields to return (None for all)
        limit: Maximum number of products to return
        
    Returns:
        List of Product instances with requested data
        
    Raises:
        ValidationError: For invalid parameters
    """
    if category_id is not None and category_id <= 0:
        raise ValidationError("Category ID must be positive")
    if discount_threshold is not None and discount_threshold < 0:
        raise ValidationError("Discount threshold must be positive")
    if limit is not None and limit <= 0:
        raise ValidationError("Limit must be positive")

    queryset = Product.objects.all()
    
    # Basic filtering
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
                   queryset=variant_qs.select_related('inventory')))
    
    if include_review_stats:
        queryset = queryset.annotate(
            avg_rating=Avg('reviews__rating', filter=Q(reviews__is_approved=True)),
            review_count=Count('reviews', filter=Q(reviews__is_approved=True))
        )
    
    # Field limiting
    if fields:
        queryset = queryset.only(*fields)
    
    # Ordering and limiting
    queryset = queryset.order_by('-is_featured', 'name')
    if limit:
        queryset = queryset[:limit]
    
    return list(queryset)

def get_product_detail(
    product_id: int,
    *,
    with_variants: bool = True,
    with_reviews: bool = False,
    with_category: bool = False,
    review_limit: Optional[int] = None
) -> Optional[Product]:
    """
    Get single product with optimized related data loading
    
    Args:
        product_id: ID of product to fetch
        with_variants: Include variants and inventory
        with_reviews: Include reviews and ratings
        with_category: Include category details
        review_limit: Maximum reviews to include
        
    Returns:
        Product instance with requested relations or None
        
    Raises:
        ValidationError: For invalid product ID
    """
    validate_product_id(product_id)
    
    queryset = Product.objects.filter(pk=product_id)
    
    # Variant prefetch
    if with_variants:
        variant_qs = ProductVariant.objects.select_related('inventory')
        if with_reviews:
            variant_qs = variant_qs.prefetch_related('options__attribute')
        queryset = queryset.prefetch_related(
            Prefetch('variants', queryset=variant_qs)
        )
    
    # Review prefetch
    if with_reviews:
        review_qs = ProductReview.objects.filter(is_approved=True)
        if review_limit:
            review_qs = review_qs[:review_limit]
        queryset = queryset.prefetch_related(
            Prefetch('reviews', 
                   queryset=review_qs.select_related('user')))
    
    # Category select
    if with_category:
        queryset = queryset.select_related('category')
    
    return queryset.first()

@cache(60 * 30)  # Cache for 30 minutes
def get_featured_products(
    limit: int = 8,
    *,
    only_in_stock: bool = True,
    min_rating: Optional[float] = None,
    fields: Optional[List[str]] = None
) -> List[Product]:
    """
    Get featured products with optimized query
    
    Args:
        limit: Maximum number of products to return
        only_in_stock: Only include products with inventory
        min_rating: Minimum average rating
        fields: Specific fields to return (None for all)
        
    Returns:
        List of featured Product instances
        
    Raises:
        ValidationError: For invalid parameters
    """
    if limit <= 0:
        raise ValidationError("Limit must be positive")
    if min_rating is not None and (min_rating < 0 or min_rating > 5):
        raise ValidationError("Rating must be between 0 and 5")

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
            avg_rating=Avg('reviews__rating', filter=Q(reviews__is_approved=True))
        ).filter(avg_rating__gte=min_rating)
    
    if fields:
        queryset = queryset.only(*fields)
    
    return list(queryset.order_by('?')[:limit])

def get_products_by_price_range(
    min_price: float,
    max_price: float,
    currency: str = 'USD',
    *,
    only_in_stock: bool = True,
    only_active: bool = True,
    limit: Optional[int] = None
) -> List[Product]:
    """
    Get products within price range with inventory check
    
    Args:
        min_price: Minimum price threshold
        max_price: Maximum price threshold
        currency: Currency code for price comparison
        only_in_stock: Only include available products
        only_active: Only include active products
        limit: Maximum number of products to return
        
    Returns:
        List of matching Product instances
        
    Raises:
        ValidationError: For invalid parameters
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
    
    if limit:
        queryset = queryset[:limit]
    
    return list(queryset.order_by('final_price'))

def get_category_products(
    category_id: int,
    *,
    include_subcategories: bool = False,
    only_featured: bool = False,
    only_active: bool = True,
    fields: Optional[List[str]] = None,
    limit: Optional[int] = None
) -> Dict[str, List[Product]]:
    """
    Get products organized by subcategories
    
    Args:
        category_id: Parent category ID
        include_subcategories: Include products from child categories
        only_featured: Only include featured products
        only_active: Only include active products
        fields: Specific fields to return (None for all)
        limit: Maximum products per category
        
    Returns:
        Dictionary with category names as keys and product lists as values
        
    Raises:
        ValidationError: For invalid category ID
    """
    validate_product_id(category_id)
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
    if limit:
        product_qs = product_qs[:limit]
    
    categories = categories.prefetch_related(
        Prefetch('products', 
               queryset=product_qs.order_by('-is_featured'))
    )
    
    return {
        cat.name: list(cat.products.all())
        for cat in categories
    }

@cache(60 * 60)  # Cache for 1 hour
def get_product_review_stats(product_id: int) -> Dict[str, float]:
    """
    Get aggregated review statistics for a product
    
    Args:
        product_id: Product to analyze
        
    Returns:
        Dictionary with:
        - average_rating
        - review_count
        - rating_distribution (1-5 stars)
        
    Raises:
        ValidationError: For invalid product ID
    """
    validate_product_id(product_id)
    
    stats = ProductReview.objects.filter(
        product_id=product_id,
        is_approved=True
    ).aggregate(
        avg_rating=Avg('rating'),
        review_count=Count('id'),
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
    limit: Optional[int] = None
) -> List[Product]:
    """
    Get products with significant discounts
    
    Args:
        min_discount: Minimum discount percentage/amount
        only_active: Only include active products
        only_in_stock: Only include available products
        limit: Maximum number of products to return
        
    Returns:
        List of discounted Product instances
        
    Raises:
        ValidationError: For invalid parameters
    """
    if min_discount <= 0:
        raise ValidationError("Discount threshold must be positive")
    if limit is not None and limit <= 0:
        raise ValidationError("Limit must be positive")

    queryset = Product.objects.filter(
        Q(discount_percent__gte=min_discount) |
        Q(discount_amount__amount__gte=min_discount),
        is_active=only_active
    )
    
    if only_in_stock:
        queryset = queryset.filter(
            variants__inventory__stock_quantity__gt=0
        ).distinct()
    
    if limit:
        queryset = queryset[:limit]
    
    return list(queryset.order_by('-discount_percent'))