from django.db.models import Q, Prefetch, Avg
from .models import ProductReview, ReviewVote

class ReviewSelector:
    """Advanced selectors for retrieving review and vote data"""

    @staticmethod
    def get_approved_reviews(product_id: int) -> list[ProductReview]:
        """Retrieve approved reviews with votes (UC-R05, R08)"""
        return ProductReview.objects.filter(
            product_id=product_id,
            is_approved=True
        ).select_related('user').prefetch_related(
            Prefetch('votes', queryset=ReviewVote.objects.select_related('user'))
        ).order_by('-helpful_count', '-created_at')

    @staticmethod
    def get_user_reviews(user_id: int, include_pending: bool = False) -> list[ProductReview]:
        """Retrieve user reviews with/without pending reviews (UC-R05)"""
        query = Q(user_id=user_id)
        if not include_pending:
            query &= Q(is_approved=True)
        return ProductReview.objects.filter(query).prefetch_related('product')

    @staticmethod
    def has_user_voted(review_id: int, user_id: int) -> bool:
        """Check if a user has voted on a review (UC-R06, R07)"""
        return ReviewVote.objects.filter(review_id=review_id, user_id=user_id).exists()

    @staticmethod
    def calculate_average_rating(product_id: int) -> float:
        """Calculate the average rating of approved reviews"""
        result = ProductReview.objects.filter(
            product_id=product_id,
            is_approved=True
        ).aggregate(avg_rating=Avg('rating'))
        return round(result['avg_rating'] or 0.0, 2)

    @staticmethod
    def get_review_details(review_id: int) -> ProductReview:
        """Retrieve review details with votes"""
        return ProductReview.objects.select_related('user', 'product').prefetch_related(
            'votes__user'
        ).get(id=review_id)