from django.db import models
from django.core.validators import MinValueValidator, RegexValidator, MaxValueValidator
from django.utils.translation import gettext_lazy as _
from eleganza.core.models import BaseModel
from ..constants import (
    FieldLimits,
    ValidationPatterns,
)
from .product_model import Product

class ProductReview(BaseModel):
    """Customer review and rating system"""

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='reviews',
        verbose_name=_("Product")
    )
    user = models.ForeignKey(
        'users.User',
        on_delete=models.CASCADE,
        related_name='reviews',
        verbose_name=_("User")
    )
    rating = models.PositiveSmallIntegerField(
        _("Rating"),
        validators=[
            MinValueValidator(1),
            MaxValueValidator(5)
        ]
    )
    title = models.CharField(
        _("Title"),
        max_length=FieldLimits.REVIEW_TITLE,
        validators=[
            RegexValidator(
                ValidationPatterns.PRODUCT_NAME,
                _("Title contains invalid characters")
            )
        ]
    )
    comment = models.TextField(_("Comment"))
    is_approved = models.BooleanField(
        _("Approved"),
        default=False,
        db_index=True
    )
    helpful_count = models.PositiveIntegerField(
        _("Helpful Count"),
        default=0,
        editable=False,
        help_text=_("Number of users who found this review helpful.")
    )

    class Meta:
        unique_together = ('product', 'user')
        verbose_name = _("Product Review")
        verbose_name_plural = _("Product Reviews")
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username}'s review of {self.product.name}"

class ReviewVote(BaseModel):
    """Tracks user votes on reviews"""
    review = models.ForeignKey(
        ProductReview,
        on_delete=models.CASCADE,
        related_name='votes',
        verbose_name=_("Review")
    )
    user = models.ForeignKey(
        'users.User',
        on_delete=models.CASCADE,
        related_name='review_votes',
        verbose_name=_("User")
    )

    class Meta:
        unique_together = ('review', 'user')  # Prevents duplicate votes
        verbose_name = _("Review Vote")
        verbose_name_plural = _("Review Votes")

    def __str__(self):
        return f"{self.user.username} voted on {self.review.title}"