from django.db.models import Avg, Count, Q, F, Subquery, OuterRef
from typing import List, Dict, Optional
from ..models import ProductReview, Product
from django.utils import timezone
from datetime import timedelta
from ..constants import Defaults

def get_product_reviews(
    product_id: int,
    *,
    only_approved: bool = True,
    min_rating: Optional[int] = None,
    recent_days: Optional[int] = None,
    include_user_info: bool = False
) -> List[ProductReview]:
    """
    Get filtered reviews for a product with optimized queries
    
    Args:
        product_id: Target product ID
        only_approved: Filter by approved status
        min_rating: Minimum rating to include
        recent_days: Only reviews from last N days
        include_user_info: Prefetch user data
        
    Returns:
        List of ProductReview instances
    """
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
    
    return list(queryset.order_by('-created_at'))

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
    """
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
            if stats['total_votes'] else 0
        ))
    }

def get_recent_reviews(
    *,
    limit: int = 5,
    min_rating: Optional[int] = None,
    with_product_info: bool = False
) -> List[ProductReview]:
    """
    Get most recent reviews across all products
    
    Args:
        limit: Number of reviews to return
        min_rating: Minimum rating to include
        with_product_info: Prefetch product data
        
    Returns:
        List of ProductReview instances
    """
    queryset = ProductReview.objects.filter(is_approved=True)
    
    if min_rating:
        queryset = queryset.filter(rating__gte=min_rating)
    
    if with_product_info:
        queryset = queryset.select_related('product')
    
    return list(queryset.order_by('-created_at')[:limit])

def get_user_reviews(
    user_id: int,
    *,
    only_approved: bool = True,
    with_product_info: bool = False
) -> List[ProductReview]:
    """
    Get all reviews by a specific user
    
    Args:
        user_id: Target user ID
        only_approved: Filter by approval status
        with_product_info: Prefetch product data
        
    Returns:
        List of ProductReview instances
    """
    queryset = ProductReview.objects.filter(user_id=user_id)
    
    if only_approved:
        queryset = queryset.filter(is_approved=True)
    
    if with_product_info:
        queryset = queryset.select_related('product')
    
    return list(queryset.order_by('-created_at'))

def get_most_helpful_reviews(
    product_id: int,
    *,
    limit: int = 3,
    min_helpful_votes: int = 5
) -> List[ProductReview]:
    """
    Get reviews with the most helpful votes
    
    Args:
        product_id: Target product ID
        limit: Number of reviews to return
        min_helpful_votes: Minimum votes to qualify
        
    Returns:
        List of ProductReview instances
    """
    return list(ProductReview.objects.filter(
        product_id=product_id,
        is_approved=True,
        helpful_votes__gte=min_helpful_votes
    ).order_by(
        '-helpful_votes',
        '-created_at'
    )[:limit])

def get_review_histogram(
    product_id: int,
    *,
    time_period: str = 'monthly'  # 'daily', 'weekly', 'monthly'
) -> List[Dict[str, any]]:
    """
    Get review count over time for trend analysis
    
    Args:
        product_id: Target product ID
        time_period: Grouping interval
        
    Returns:
        List of dictionaries with:
        - period_start (date)
        - review_count (int)
        - average_rating (float)
    """
    from django.db.models.functions import Trunc
    from django.db.models import DateField
    
    trunc_map = {
        'daily': 'day',
        'weekly': 'week',
        'monthly': 'month'
    }
    
    return list(ProductReview.objects.filter(
        product_id=product_id,
        is_approved=True
    ).annotate(
        period=Trunc('created_at', trunc_map[time_period], output_field=DateField())
    ).values(
        'period'
    ).annotate(
        review_count=Count('id'),
        average_rating=Avg('rating')
    ).order_by('period'))

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
        ).count() / stats['total_reviews'] * 100
    
    return stats

def get_pending_reviews(*, limit: Optional[int] = None) -> List[ProductReview]:
    """
    Get reviews awaiting moderation
    
    Args:
        limit: Maximum number to return
        
    Returns:
        List of unapproved ProductReview instances
    """
    queryset = ProductReview.objects.filter(
        is_approved=False
    ).select_related(
        'user',
        'product'
    ).order_by('created_at')
    
    if limit:
        queryset = queryset[:limit]
    
    return list(queryset)