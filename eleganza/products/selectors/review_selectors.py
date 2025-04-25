# eleganza/products/selectors/review_selectors.py
from django.db.models import Avg, Count, Q, F, Sum, FloatField
from typing import List, Dict, Optional
from django.utils import timezone
from datetime import timedelta
from django.db.models.functions import Trunc, Coalesce
from django.db.models import DateField, Value
from eleganza.products.models import ProductReview, Product
from eleganza.products.constants import Defaults
from eleganza.products.validators import (
    validate_id,
    validate_rating,
    validate_days_range,
)

# Reusable annotations and constants
BASE_REVIEW_STATS = {
    'avg_rating': Avg('rating'),
    'review_count': Count('id'),
    'helpful_percentage': Coalesce(
        Avg(F('helpful_votes') / (F('helpful_votes') + 1), 
        Value(0.0),
        output_field=FloatField()
    ) * 100)
}

RATING_DISTRIBUTION = {
    f'stars_{i}': Count('id', filter=Q(rating=i))
    for i in range(1, 6)
}

def get_reviews_cache_key(**kwargs) -> str:
    """Generate unique cache key based on query parameters"""
    from hashlib import md5
    return f"reviews_{md5(str(kwargs).encode()).hexdigest()}"


def get_product_reviews(
    product_id: int,
    *,
    only_approved: bool = True,
    min_rating: Optional[int] = None,
    recent_days: Optional[int] = None,
    include_user_info: bool = False,
    include_product_info: bool = False,
    limit: Optional[int] = None,
    offset: int = 0,
    order_by: str = '-created_at'
) -> List[ProductReview]:
    """
    Get filtered reviews for a product with optimized queries.
    Uses centralized validation and reusable annotations.
    """
    validate_id(product_id, "Product ID")
    if min_rating is not None:
        validate_rating(min_rating)
    if recent_days is not None:
        validate_days_range(recent_days)
    if limit is not None:
        validate_limit(limit)

    queryset = ProductReview.objects.filter(product_id=product_id)
    
    if only_approved:
        queryset = queryset.filter(is_approved=True)
    
    if min_rating:
        queryset = queryset.filter(rating__gte=min_rating)
    
    if recent_days:
        cutoff = timezone.now() - timedelta(days=recent_days)
        queryset = queryset.filter(created_at__gte=cutoff)
    
    if include_user_info:
        queryset = queryset.select_related('user')
    
    if include_product_info:
        queryset = queryset.select_related('product')
    
    # Pagination support
    queryset = queryset.order_by(order_by)
    if limit:
        queryset = queryset[offset:offset + limit]
    
    return list(queryset)


def get_review_stats(product_id: int) -> Dict[str, any]:
    """
    Get comprehensive review statistics for a product.
    Uses reusable BASE_REVIEW_STATS and RATING_DISTRIBUTION.
    """
    validate_id(product_id, "Product ID")
    
    stats = ProductReview.objects.filter(
        product_id=product_id,
        is_approved=True
    ).aggregate(
        **BASE_REVIEW_STATS,
        **RATING_DISTRIBUTION
    )
    
    return {
        'average_rating': round(stats['avg_rating'] or 0, 1),
        'review_count': stats['review_count'],
        'rating_distribution': {
            i: stats[f'stars_{i}'] for i in range(1, 6)
        },
        'helpful_percentage': stats['helpful_percentage']
    }


def get_recent_reviews(
    *,
    limit: int = 5,
    min_rating: Optional[int] = None,
    with_product_info: bool = False,
    with_user_info: bool = False,
    days_back: Optional[int] = None,
    offset: int = 0
) -> List[ProductReview]:
    """
    Get most recent reviews across all products.
    Uses centralized validation and pagination.
    """
    validate_limit(limit, max_value=100)
    if min_rating is not None:
        validate_rating(min_rating)
    if days_back is not None:
        validate_days_range(days_back)

    queryset = ProductReview.objects.filter(is_approved=True)
    
    if min_rating:
        queryset = queryset.filter(rating__gte=min_rating)
    
    if days_back:
        cutoff = timezone.now() - timedelta(days=days_back)
        queryset = queryset.filter(created_at__gte=cutoff)
    
    if with_product_info:
        queryset = queryset.select_related('product')
    
    if with_user_info:
        queryset = queryset.select_related('user')
    
    # Pagination support
    return list(queryset.order_by('-created_at')[offset:offset + limit])

def get_user_reviews(
    user_id: int,
    *,
    only_approved: bool = True,
    with_product_info: bool = False,
    limit: Optional[int] = None,
    offset: int = 0,
    min_rating: Optional[int] = None
) -> List[ProductReview]:
    """
    Get all reviews by a specific user.
    Uses reusable validation and pagination.
    """
    validate_id(user_id, "User ID")
    if limit is not None:
        validate_limit(limit)
    if min_rating is not None:
        validate_rating(min_rating)

    queryset = ProductReview.objects.filter(user_id=user_id)
    
    if only_approved:
        queryset = queryset.filter(is_approved=True)
    
    if min_rating:
        queryset = queryset.filter(rating__gte=min_rating)
    
    if with_product_info:
        queryset = queryset.select_related('product')
    
    # Pagination support
    queryset = queryset.order_by('-created_at')
    if limit:
        queryset = queryset[offset:offset + limit]
    
    return list(queryset)


def get_most_helpful_reviews(
    product_id: int,
    *,
    limit: int = 3,
    min_helpful_votes: int = 5,
    min_rating: Optional[int] = None
) -> List[ProductReview]:
    """
    Get reviews with the most helpful votes.
    Uses centralized validation and reusable filters.
    """
    validate_id(product_id, "Product ID")
    validate_limit(limit, max_value=20)
    if min_helpful_votes < 0:
        raise ValidationError("Helpful votes cannot be negative")
    if min_rating is not None:
        validate_rating(min_rating)

    queryset = ProductReview.objects.filter(
        product_id=product_id,
        is_approved=True,
        helpful_votes__gte=min_helpful_votes
    )
    
    if min_rating:
        queryset = queryset.filter(rating__gte=min_rating)
    
    return list(queryset.order_by('-helpful_votes', '-created_at')[:limit])


def get_review_histogram(
    product_id: int,
    *,
    time_period: str = 'monthly',  # 'daily', 'weekly', 'monthly'
    limit: Optional[int] = None,
    offset: int = 0
) -> List[Dict[str, any]]:
    """
    Get review count over time for trend analysis.
    Uses centralized validation and Trunc date functions.
    """
    validate_id(product_id, "Product ID")
    if time_period not in ['daily', 'weekly', 'monthly']:
        raise ValidationError("Invalid time period")
    if limit is not None:
        validate_limit(limit)

    trunc_map = {
        'daily': 'day',
        'weekly': 'week',
        'monthly': 'month'
    }
    
    queryset = ProductReview.objects.filter(
        product_id=product_id,
        is_approved=True
    ).annotate(
        period=Trunc('created_at', trunc_map[time_period], output_field=DateField())
    ).values(
        'period'
    ).annotate(
        review_count=Count('id'),
        average_rating=Avg('rating')
    ).order_by('period')
    
    # Pagination support
    if limit:
        queryset = queryset[offset:offset + limit]
    
    return list(queryset)

def get_review_engagement_stats() -> Dict[str, any]:
    """
    Get store-wide review engagement metrics.
    Uses reusable BASE_REVIEW_STATS annotations.
    """
    stats = ProductReview.objects.aggregate(
        **BASE_REVIEW_STATS
    )
    
    # If tracking admin responses
    if hasattr(ProductReview, 'response_text'):
        stats['response_rate'] = ProductReview.objects.filter(
            response_text__isnull=False
        ).count() / stats['review_count'] * 100 if stats['review_count'] else 0
    
    return stats

def get_pending_reviews(
    *,
    limit: Optional[int] = None,
    days_old: Optional[int] = None,
    min_rating: Optional[int] = None,
    offset: int = 0
) -> List[ProductReview]:
    """
    Get reviews awaiting moderation.
    Uses centralized validation and pagination.
    """
    if limit is not None:
        validate_limit(limit)
    if days_old is not None and days_old <= 0:
        raise ValidationError("Days old must be positive")
    if min_rating is not None:
        validate_rating(min_rating)

    queryset = ProductReview.objects.filter(
        is_approved=False
    ).select_related(
        'user',
        'product'
    )
    
    if days_old:
        cutoff = timezone.now() - timedelta(days=days_old)
        queryset = queryset.filter(created_at__lte=cutoff)
    
    if min_rating:
        queryset = queryset.filter(rating__gte=min_rating)
    
    # Pagination support
    queryset = queryset.order_by('created_at')
    if limit:
        queryset = queryset[offset:offset + limit]
    
    return list(queryset)

def get_review_summary_by_category(
    category_id: int,
    *,
    include_subcategories: bool = False
) -> Dict[str, Dict[str, float]]:
    """
    Get review statistics aggregated by product category.
    Uses reusable BASE_REVIEW_STATS annotations.
    """
    validate_id(category_id, "Category ID")
    
    # Get category tree
    categories = ProductCategory.objects.filter(id=category_id)
    if include_subcategories:
        categories = categories.get_descendants(include_self=True)
    
    # Get stats for each category
    results = {}
    for category in categories:
        stats = ProductReview.objects.filter(
            product__category=category,
            is_approved=True
        ).aggregate(
            **BASE_REVIEW_STATS
        )
        
        results[category.name] = {
            'average_rating': stats['avg_rating'] or 0,
            'review_count': stats['review_count'],
            'helpful_percentage': stats['helpful_percentage'] or 0
        }
    
    return results