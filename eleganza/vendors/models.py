# vendors/models.py
from django.conf import settings
from django.db import models
from model_utils.models import TimeStampedModel

class Vendor(TimeStampedModel):
    """Model representing a vendor/seller"""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='vendor_profile',
        verbose_name='User Account'
    )
    business_name = models.CharField(
        max_length=255,
        unique=True,
        verbose_name='Business Name'
    )
    tax_id = models.CharField(
        max_length=100,
        unique=True,
        verbose_name='Tax Identification Number'
    )
    commission_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=15.00,
        verbose_name='Commission Rate (%)'
    )
    verified_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Verification Date'
    )
    rating = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=0.00,
        verbose_name='Average Rating'
    )

    class Meta:
        verbose_name = 'Vendor'
        verbose_name_plural = 'Vendors'
        ordering = ['-created']

    def __str__(self):
        return f"{self.business_name} ({self.user.email})"


class SellerRating(TimeStampedModel):
    """Model for user ratings of vendors"""
    vendor = models.ForeignKey(
        Vendor,
        on_delete=models.CASCADE,
        related_name='ratings',
        verbose_name='Rated Vendor'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='given_ratings',
        verbose_name='Rating User'
    )
    rating = models.PositiveSmallIntegerField(
        choices=[(i, f'{i} Stars') for i in range(1, 6)],
        verbose_name='Rating (1-5)'
    )
    review = models.TextField(
        blank=True,
        verbose_name='Detailed Review'
    )
    is_verified_purchase = models.BooleanField(
        default=False,
        verbose_name='Verified Purchase'
    )

    class Meta:
        verbose_name = 'Seller Rating'
        verbose_name_plural = 'Seller Ratings'
        unique_together = ('vendor', 'user')
        ordering = ['-created']

    def __str__(self):
        return f"{self.rating}/5 for {self.vendor} by {self.user}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.update_vendor_rating()

    def update_vendor_rating(self):
        avg_rating = self.vendor.ratings.aggregate(
            avg=models.Avg('rating')
        )['avg'] or 0
        self.vendor.rating = round(avg_rating, 2)
        self.vendor.save()