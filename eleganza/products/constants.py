from django.utils.translation import gettext_lazy as _
from typing import Final, ClassVar

class DiscountTypes:
    NONE: Final[str] = 'none'
    FIXED: Final[str] = 'fixed'
    PERCENTAGE: Final[str] = 'percentage'
    MAX_LENGTH: Final[int] = 10
    CHOICES: ClassVar[list[tuple[str, str]]] = [
        (NONE, _('No Discount')),
        (FIXED, _('Fixed Amount')),
        (PERCENTAGE, _('Percentage')),
    ]

class FieldLengths:
    CATEGORY_NAME: Final[int] = 100
    PRODUCT_NAME: Final[int] = 255
    SKU: Final[int] = 50
    ATTRIBUTE_NAME: Final[int] = 100
    OPTION_VALUE: Final[int] = 100
    REVIEW_TITLE: Final[int] = 255
    IMAGE_CAPTION: Final[int] = 255

class Defaults:
    LOW_STOCK_THRESHOLD: Final[int] = 5
    PRICE_DECIMALS: Final[int] = 2
    PRICE_MAX_DIGITS: Final[int] = 14
    RATING_DECIMALS: Final[int] = 1
    RATING_MAX_DIGITS: Final[int] = 3
    SORT_ORDER: Final[int] = 0
    STOCK_QUANTITY: Final[int] = 0