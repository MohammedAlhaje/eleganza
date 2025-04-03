from django.db.models import Prefetch, Q, F, Count, Avg
from typing import Optional, List, Dict
from ..models import Product, ProductVariant, ProductReview, ProductCategory
from ..constants import Defaults

def get_products(
    *,
    category_id: Optional[int] = None,
    only_active: bool = True,
    include_variants: bool = False,
    include_review_stats: bool = False,
    discount_threshold: Optional[float] = None
) -> List[Product]:
    """
    Get products with flexible filtering and optimized queries
    
    Args:
        category_id: Filter by category
        only_active: Only include active products
        include_variants: Prefetch variants data
        include_review_stats: Include review aggregates
        discount_threshold: Minimum discount percentage/amount
        
    Returns:
        List of Product instances with related data
    """
    queryset = Product.objects.all()
    
    # Basic filtering
    if only_active:
        queryset = queryset.filter(is_active=True)
    
    if category_id:
        queryset = queryset.filter(category_id=category_id)
    
    # Discount filtering
    if discount_threshold:
        queryset = queryset.filter(
            Q(discount_percent__gte=discount_threshold) |
            Q(discount_amount__amount__gte=discount_threshold)
        )
    
    # Related data prefetching
    if include_variants:
        queryset = queryset.prefetch_related(
            Prefetch('variants', 
                   queryset=ProductVariant.objects.filter(is_active=True)
                   .select_related('inventory')))
    
    if include_review_stats:
        queryset = queryset.annotate(
            avg_rating=Avg('reviews__rating'),
            review_count=Count('reviews')
        )
    
    return list(queryset.order_by('-is_featured', 'name'))

def get_product_detail(
    product_id: int,
    *,
    with_variants: bool = True,
    with_reviews: bool = False
) -> Optional[Product]:
    """
    Get single product with optimized related data loading
    
    Args:
        product_id: ID of product to fetch
        with_variants: Include variants and inventory
        with_reviews: Include reviews and ratings
        
    Returns:
        Product instance with requested relations or None
    """
    queryset = Product.objects.filter(pk=product_id)
    
    if with_variants:
        queryset = queryset.prefetch_related(
            Prefetch('variants',
                   queryset=ProductVariant.objects.select_related('inventory')
                   .prefetch_related('options__attribute')))
    
    if with_reviews:
        queryset = queryset.prefetch_related(
            Prefetch('reviews',
                   queryset=ProductReview.objects.filter(is_approved=True)
                   .select_related('user')))
    
    return queryset.first()

def get_featured_products(limit: int = 8) -> List[Product]:
    """
    Get featured products with optimized query
    
    Args:
        limit: Maximum number of products to return
        
    Returns:
        List of featured Product instances
    """
    return list(Product.objects
               .filter(is_featured=True, is_active=True)
               .select_related('category')
               .prefetch_related('primary_image')
               .order_by('?')[:limit])

def get_products_by_price_range(
    min_price: float,
    max_price: float,
    currency: str = 'USD'
) -> List[Product]:
    """
    Get products within price range with inventory check
    
    Args:
        min_price: Minimum price threshold
        max_price: Maximum price threshold
        currency: Currency code for price comparison
        
    Returns:
        List of matching Product instances
    """
    return list(Product.objects
               .filter(
                   final_price__amount__gte=min_price,
                   final_price__amount__lte=max_price,
                   final_price__currency=currency,
                   is_active=True,
                   variants__inventory__stock_quantity__gt=0
               )
               .distinct()
               .order_by('final_price'))

def get_category_products(category_id: int) -> Dict[str, List[Product]]:
    """
    Get products organized by subcategories
    
    Args:
        category_id: Parent category ID
        
    Returns:
        Dictionary with category names as keys and product lists as values
    """
    categories = ProductCategory.objects.filter(
        Q(id=category_id) | Q(parent_id=category_id)
    ).prefetch_related(
        Prefetch('products',
               queryset=Product.objects.filter(is_active=True)
               .order_by('-is_featured'))
    )
    
    return {
        cat.name: list(cat.products.all())
        for cat in categories
    }

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
    """
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