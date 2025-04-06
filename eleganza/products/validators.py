# eleganza/products/validators.py
from django.core.exceptions import ValidationError
from typing import Optional, List

def validate_id(value: int, name: str = "ID") -> None:
    """Validate that an ID is a positive integer."""
    if value <= 0:
        raise ValidationError(f"{name} must be positive")

def validate_price_range(min_price: float, max_price: float) -> None:
    """Validate price range parameters."""
    if min_price < 0 or max_price < 0:
        raise ValidationError("Prices cannot be negative")
    if min_price > max_price:
        raise ValidationError("Min price cannot exceed max price")

def validate_rating(rating: int) -> None:
    """Validate rating is between 1 and 5."""
    if not (1 <= rating <= 5):
        raise ValidationError("Rating must be between 1 and 5")

def validate_days_range(days: int, min_days: int = 1, max_days: int = 365) -> None:
    """Validate days fall within a range (e.g., for query time windows)."""
    if not (min_days <= days <= max_days):
        raise ValidationError(f"Days must be between {min_days} and {max_days}")

def validate_option_ids(option_ids: List[int]) -> None:
    """Validate a list of product option IDs."""
    if not option_ids:
        raise ValidationError("Option IDs cannot be empty")
    if any(oid <= 0 for oid in option_ids):
        raise ValidationError("Option IDs must be positive")

def validate_category_depth(depth: Optional[int]) -> None:
    """Validate depth parameter for category queries."""
    if depth is not None and (depth < 1 or depth > 10):
        raise ValidationError("Depth must be between 1 and 10")