from django.db import transaction
from django.core.exceptions import ValidationError, PermissionDenied
from django.utils.translation import gettext_lazy as _
from django.db.models import Avg
from .models import ProductReview, ReviewVote

class ReviewService:
    """Comprehensive services for managing reviews and votes"""

    # ------------------- Review Management ------------------- #
    @classmethod
    @transaction.atomic
    def submit_review(
        cls,
        user_id: int,
        product_id: int,
        rating: int,
        title: str,
        comment: str
    ) -> ProductReview:
        """UC-R01: Submit a new review"""
        if ProductReview.objects.filter(user_id=user_id, product_id=product_id).exists():
            raise ValidationError(_("You have already reviewed this product"))
        
        if not 1 <= rating <= 5:
            raise ValidationError(_("Rating must be between 1 and 5"))
        
        return ProductReview.objects.create(
            user_id=user_id,
            product_id=product_id,
            rating=rating,
            title=title,
            comment=comment
        )

    @classmethod
    @transaction.atomic
    def edit_review(
        cls,
        review_id: int,
        user_id: int,
        **kwargs
    ) -> ProductReview:
        """UC-R03: Edit an unapproved review"""
        review = ProductReview.objects.get(id=review_id)
        
        if review.user_id != user_id:
            raise PermissionDenied(_("You are not authorized to edit this review"))
        if review.is_approved:
            raise ValidationError(_("Cannot edit an approved review"))
        
        for field, value in kwargs.items():
            setattr(review, field, value)
        review.save()
        return review

    @classmethod
    @transaction.atomic
    def approve_review(cls, review_id: int) -> ProductReview:
        """UC-R02: Approve a review"""
        review = ProductReview.objects.get(id=review_id)
        review.is_approved = True
        review.save()
        
        # Update product statistics
        product = review.product
        approved_reviews = product.reviews.filter(is_approved=True)
        product.average_rating = approved_reviews.aggregate(Avg('rating'))['rating__avg'] or 0.0
        product.review_count = approved_reviews.count()
        product.save()
        return review

    @classmethod
    @transaction.atomic
    def delete_review(
        cls,
        review_id: int,
        user_id: int,
        is_admin: bool = False
    ) -> None:
        """UC-R04: Delete a review"""
        review = ProductReview.objects.get(id=review_id)
        
        if not (is_admin or review.user_id == user_id):
            raise PermissionDenied(_("You are not authorized to delete this review"))
        
        product = review.product
        review.delete()
        
        # Update statistics if the review was approved
        if review.is_approved:
            approved_reviews = product.reviews.filter(is_approved=True)
            product.average_rating = approved_reviews.aggregate(Avg('rating'))['rating__avg'] or 0.0
            product.review_count = approved_reviews.count()
            product.save()

    # ------------------- Vote Management ------------------- #
    @classmethod
    @transaction.atomic
    def mark_helpful(cls, review_id: int, user_id: int) -> None:
        """UC-R06: Mark a review as helpful"""
        review = ProductReview.objects.get(id=review_id)
        
        if ReviewVote.objects.filter(review=review, user_id=user_id).exists():
            raise ValidationError(_("You have already voted on this review"))
        
        ReviewVote.objects.create(review=review, user_id=user_id)
        review.helpful_count += 1
        review.save()

    @classmethod
    @transaction.atomic
    def unmark_helpful(cls, review_id: int, user_id: int) -> None:
        """UC-R07: Unmark a review as helpful"""
        review = ProductReview.objects.get(id=review_id)
        
        try:
            vote = ReviewVote.objects.get(review=review, user_id=user_id)
        except ReviewVote.DoesNotExist:
            raise ValidationError(_("You have not voted on this review"))
        
        vote.delete()
        review.helpful_count -= 1
        review.save()