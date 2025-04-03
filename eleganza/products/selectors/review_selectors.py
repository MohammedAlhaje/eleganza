from django.db.models import Avg, Count, Q, F, Sum, FloatField
from typing import List, Dict, Optional
from django.utils import timezone
from datetime import timedelta
from django.core.exceptions import ValidationError
from django.core.cache import cache
from ..models import ProductReview, Product
from ..constants import Defaults

def validate_product_id(product_id: int) -> None:
    """Validate product ID parameter"""
    if product_id <= 0:
        raise ValidationError("Product ID must be positive")

def validate_user_id(user_id: int) -> None:
    """Validate user ID parameter"""
    if user_id <= 0:
        raise ValidationError("User ID must be positive")

def validate_rating(rating: int) -> None:
    """Validate rating value"""
    if not (1 <= rating <= 5):
        raise ValidationError("Rating must be between 1 and 5")

@cache(60 * 15)  # Cache for 15 minutes
def get_product_reviews(
    product_id: int,
    *,
    only_approved: bool = True,
    min_rating: Optional[int] = None,
    recent_days: Optional[int] = None,
    include_user_info: bool = False,
    include_product_info: bool = False,
    limit: Optional[int] = None,
    order_by: str = '-created_at'
) -> List[ProductReview]:
    """
    Get filtered reviews for a product with optimized queries
    
    Args:
        product_id: Target product ID
        only_approved: Filter by approved status
        min_rating: Minimum rating to include (1-5)
        recent_days: Only reviews from last N days (1-365)
        include_user_info: Prefetch user data
        include_product_info: Prefetch product data
        limit: Maximum number of reviews to return
        order_by: Field to order by (prefix with '-' for descending)
        
    Returns:
        List of ProductReview instances
        
    Raises:
        ValidationError: For invalid parameters
    """
    validate_product_id(product_id)
    if min_rating is not None:
        validate_rating(min_rating)
    if recent_days is not None and not (1 <= recent_days <= 365):
        raise ValidationError("Recent days must be between 1 and 365")
    if limit is not None and limit <= 0:
        raise ValidationError("Limit must be positive")

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
    
    queryset = queryset.order_by(order_by)
    
    if limit:
        queryset = queryset[:limit]
    
    return list(queryset)

@cache(60 * 60)  # Cache for 1 hour
def get_review_stats(product_id: int) -> Dict[str, any]:
    """
    Get comprehensive review statistics for a product
    
    Args:
        product_id: Product to analyze
        
    Returns:
        Dictionary with:
        - average_rating (float)
        - review_count (int)
        - rating_distribution (dict {1-5: count})
        - helpful_percentage (float)
        
    Raises:
        ValidationError: For invalid product ID
    """
    validate_product_id(product_id)
    
    stats = ProductReview.objects.filter(
        product_id=product_id,
        is_approved=True
    ).aggregate(
        average_rating=Avg('rating'),
        review_count=Count('id'),
        helpful_votes=Sum('helpful_votes'),
        total_votes=Sum('helpful_votes') + Count('id'),  # Assuming all reviews get at least 1 view
        **{
            f'rating_{i}': Count('id', filter=Q(rating=i))
            for i in range(1, 6)
        }
    )
    
    return {
        'average_rating': round(stats['average_rating'] or 0, 1),
        'review_count': stats['review_count'],
        'rating_distribution': {
            i: stats[f'rating_{i}'] for i in range(1, 6)
        },
        'helpful_percentage': (
            (stats['helpful_votes'] / stats['total_votes'] * 100 
            if stats['total_votes'] else 0)
        )
    }

@cache(60 * 30)  # Cache for 30 minutes
def get_recent_reviews(
    *,
    limit: int = 5,
    min_rating: Optional[int] = None,
    with_product_info: bool = False,
    with_user_info: bool = False,
    days_back: Optional[int] = 30
) -> List[ProductReview]:
    """
    Get most recent reviews across all products
    
    Args:
        limit: Number of reviews to return (1-100)
        min_rating: Minimum rating to include (1-5)
        with_product_info: Prefetch product data
        with_user_info: Prefetch user data
        days_back: Only include reviews from last N days (1-365)
        
    Returns:
        List of ProductReview instances
        
    Raises:
        ValidationError: For invalid parameters
    """
    if not (1 <= limit <= 100):
        raise ValidationError("Limit must be between 1 and 100")
    if min_rating is not None:
        validate_rating(min_rating)
    if days_back is not None and not (1 <= days_back <= 365):
        raise ValidationError("Days back must be between 1 and 365")

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
    
    return list(queryset.order_by('-created_at')[:limit])

def get_user_reviews(
    user_id: int,
    *,
    only_approved: bool = True,
    with_product_info: bool = False,
    limit: Optional[int] = None,
    min_rating: Optional[int] = None
) -> List[ProductReview]:
    """
    Get all reviews by a specific user
    
    Args:
        user_id: Target user ID
        only_approved: Filter by approval status
        with_product_info: Prefetch product data
        limit: Maximum reviews to return
        min_rating: Minimum rating to include (1-5)
        
    Returns:
        List of ProductReview instances
        
    Raises:
        ValidationError: For invalid parameters
    """
    validate_user_id(user_id)
    if limit is not None and limit <= 0:
        raise ValidationError("Limit must be positive")
    if min_rating is not None:
        validate_rating(min_rating)

    queryset = ProductReview.objects.filter(user_id=user_id)
    
    if only_approved:
        queryset = queryset.filter(is_approved=True)
    
    if min_rating:
        queryset = queryset.filter(rating__gte=min_rating)
    
    if with_product_info:
        queryset = queryset.select_related('product')
    
    queryset = queryset.order_by('-created_at')
    
    if limit:
        queryset = queryset[:limit]
    
    return list(queryset)

@cache(60 * 60)  # Cache for 1 hour
def get_most_helpful_reviews(
    product_id: int,
    *,
    limit: int = 3,
    min_helpful_votes: int = 5,
    min_rating: Optional[int] = None
) -> List[ProductReview]:
    """
    Get reviews with the most helpful votes
    
    Args:
        product_id: Target product ID
        limit: Number of reviews to return (1-20)
        min_helpful_votes: Minimum votes to qualify
        min_rating: Minimum rating to include (1-5)
        
    Returns:
        List of ProductReview instances
        
    Raises:
        ValidationError: For invalid parameters
    """
    validate_product_id(product_id)
    if not (1 <= limit <= 20):
        raise ValidationError("Limit must be between 1 and 20")
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
    
    return list(queryset.order_by(
        '-helpful_votes',
        '-created_at'
    )[:limit])

@cache(60 * 60 * 4)  # Cache for 4 hours
def get_review_histogram(
    product_id: int,
    *,
    time_period: str = 'monthly',  # 'daily', 'weekly', 'monthly'
    limit: Optional[int] = None
) -> List[Dict[str, any]]:
    """
    Get review count over time for trend analysis
    
    Args:
        product_id: Target product ID
        time_period: Grouping interval
        limit: Maximum periods to return
        
    Returns:
        List of dictionaries with:
        - period_start (date)
        - review_count (int)
        - average_rating (float)
        
    Raises:
        ValidationError: For invalid parameters
    """
    validate_product_id(product_id)
    if time_period not in ['daily', 'weekly', 'monthly']:
        raise ValidationError("Invalid time period")
    if limit is not None and limit <= 0:
        raise ValidationError("Limit must be positive")

    from django.db.models.functions import Trunc
    from django.db.models import DateField
    
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
    
    if limit:
        queryset = queryset[:limit]
    
    return list(queryset)

@cache(60 * 60 * 12)  # Cache for 12 hours
def get_review_engagement_stats() -> Dict[str, any]:
    """
    Get store-wide review engagement metrics
    
    Returns:
        Dictionary with:
        - total_reviews
        - avg_rating
        - helpful_percentage
        - response_rate (if replies are tracked)
    """
    stats = ProductReview.objects.aggregate(
        total_reviews=Count('id'),
        avg_rating=Avg('rating'),
        helpful_percentage=Avg(
            F('helpful_votes') / (F('helpful_votes') + 1),  # +1 to avoid division by zero
            output_field=FloatField()
        ) * 100
    )
    
    # If you track admin responses:
    if hasattr(ProductReview, 'response_text'):
        stats['response_rate'] = ProductReview.objects.filter(
            response_text__isnull=False
        ).count() / stats['total_reviews'] * 100 if stats['total_reviews'] else 0
    
    return stats

def get_pending_reviews(
    *,
    limit: Optional[int] = None,
    days_old: Optional[int] = None,
    min_rating: Optional[int] = None
) -> List[ProductReview]:
    """
    Get reviews awaiting moderation
    
    Args:
        limit: Maximum number to return
        days_old: Only reviews older than N days
        min_rating: Minimum rating to include
        
    Returns:
        List of unapproved ProductReview instances
        
    Raises:
        ValidationError: For invalid parameters
    """
    if limit is not None and limit <= 0:
        raise ValidationError("Limit must be positive")
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
    
    queryset = queryset.order_by('created_at')
    
    if limit:
        queryset = queryset[:limit]
    
    return list(queryset)

def get_review_summary_by_category(
    category_id: int,
    *,
    include_subcategories: bool = False
) -> Dict[str, Dict[str, float]]:
    """
    Get review statistics aggregated by product category
    
    Args:
        category_id: Root category ID
        include_subcategories: Include child categories
        
    Returns:
        Dictionary with category names as keys and review stats as values
    """
    from django.db.models import Subquery, OuterRef
    
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
            avg_rating=Avg('rating'),
            review_count=Count('id'),
            helpful_percentage=Avg(
                F('helpful_votes') / (F('helpful_votes') + 1),
                output_field=FloatField()
            ) * 100
        )
        
        results[category.name] = {
            'average_rating': stats['avg_rating'] or 0,
            'review_count': stats['review_count'],
            'helpful_percentage': stats['helpful_percentage'] or 0
        }
    
    return results