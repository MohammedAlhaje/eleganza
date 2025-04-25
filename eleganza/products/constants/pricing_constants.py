from decimal import Decimal
from django.utils.translation import gettext_lazy as _

class DiscountTypes:
    """Discount type configurations"""
    NONE = 'none'
    FIXED = 'fixed'
    PERCENTAGE = 'percentage'
    MAX_LENGTH = 10  # Max length for discount type field
    
    CHOICES = [
        (NONE, _('No Discount')),
        (FIXED, _('Fixed Amount')),
        (PERCENTAGE, _('Percentage')),
    ]

class PriceLimits:
    """General pricing constraints"""
    DECIMALS = 2          # Decimal places
    MAX_DIGITS = 14       # Max digits allowed
    MIN_VALUE = Decimal('0.01')  # Minimum allowed price
    MAX_VALUE = Decimal('9999999.99')  # Maximum allowed price