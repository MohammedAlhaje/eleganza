from django.db import transaction
from django.db.models import Avg, Count, F
from django.core.exceptions import ValidationError
from typing import Optional, Dict, List
from eleganza.products.models import ProductReview, Product
from eleganza.users.models import User
from eleganza.products.constants import Defaults


@transaction.atomic
def submit_product_review(
    product_id: int,
    user_id: int,
    rating: int,
    title: str,
    comment: str,
    *,
    auto_approve: bool = False
) -> ProductReview:
    """
    Submit and process a new product review with validation.
    
    Args:
        product_id: ID of the product being reviewed
        user_id: ID of the user submitting the review
        rating: Rating value (1-5)
        title: Review title
        comment: Review text content
        auto_approve: Whether to automatically approve the review
        
    Returns:
        The created ProductReview instance
        
    Raises:
        ValidationError: For invalid review data
        ValueError: If product/user doesn't exist
    """
    try:
        # Validate rating
        if not (1 <= rating <= 5):
            raise ValidationError("Rating must be between 1-5")
        
        # Check for existing review
        if ProductReview.objects.filter(product_id=product_id, user_id=user_id).exists():
            raise ValidationError("You've already reviewed this product")
        
        with transaction.atomic():
            # Create the review
            review = ProductReview.objects.create(
                product_id=product_id,
                user_id=user_id,
                rating=rating,
                title=title.strip(),
                comment=comment.strip(),
                is_approved=auto_approve
            )
            
            # Update product ratings if auto-approved
            if auto_approve:
                _update_product_rating_stats(product_id)
            
            
            return review
            
    except Product.DoesNotExist:
        raise ValueError(f"Product with ID {product_id} not found")
    except User.DoesNotExist:
        raise ValueError(f"User with ID {user_id} not found")

@transaction.atomic
def approve_review(
    review_id: int,
    *,
    moderator_id: Optional[int] = None
) -> ProductReview:
    """
    Approve a product review and update product ratings.
    
    Args:
        review_id: ID of the review to approve
        moderator_id: Optional ID of approving moderator
        
    Returns:
        The approved ProductReview instance
        
    Raises:
        ValueError: If review doesn't exist
    """
    try:
        with transaction.atomic():
            review = ProductReview.objects.select_for_update().get(pk=review_id)
            
            if review.is_approved:
                return review
                
            review.is_approved = True
            review.save(update_fields=['is_approved'])
            
            # Update product stats
            _update_product_rating_stats(review.product_id)
            
            
            return review
            
    except ProductReview.DoesNotExist:
        raise ValueError(f"Review with ID {review_id} not found")


@transaction.atomic
def update_review_helpfulness(
    review_id: int,
    is_helpful: bool,
    *,
    user_id: Optional[int] = None
) -> ProductReview:
    """
    Update review helpfulness votes.
    
    Args:
        review_id: ID of the review
        is_helpful: Whether the vote is helpful or not
        user_id: Optional ID of voting user
        
    Returns:
        Updated ProductReview instance
        
    Raises:
        ValueError: If review doesn't exist
    """
    try:
        with transaction.atomic():
            review = ProductReview.objects.select_for_update().get(pk=review_id)
            
            if is_helpful:
                review.helpful_votes = F('helpful_votes') + 1
            else:
                review.helpful_votes = F('helpful_votes') - 1
                
            review.save(update_fields=['helpful_votes'])
            review.refresh_from_db()
            
            # Prevent negative votes
            if review.helpful_votes < 0:
                review.helpful_votes = 0
                review.save(update_fields=['helpful_votes'])
            
            
            return review
            
    except ProductReview.DoesNotExist:
        raise ValueError(f"Review with ID {review_id} not found")

# -- Private Helpers -- #

def _update_product_rating_stats(product_id: int) -> None:
    """Recalculate and update product rating statistics"""
    stats = ProductReview.objects.filter(
        product_id=product_id,
        is_approved=True
    ).aggregate(
        avg_rating=Avg('rating'),
        review_count=Count('id')
    )
    
    Product.objects.filter(pk=product_id).update(
        average_rating=stats['avg_rating'] or 0,
        review_count=stats['review_count']
    )
