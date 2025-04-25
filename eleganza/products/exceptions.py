from typing import Optional, List

class ErrorCodes:
    """Centralized error code constants"""
    PRODUCT_NOT_FOUND = "PRODUCT_NOT_FOUND"
    INVALID_DATA = "INVALID_PRODUCT_DATA"
    CREATION_FAILED = "PRODUCT_CREATION_FAILED"

class ProductServiceError(Exception):
    """Base exception for product operations."""
    def __init__(
        self, 
        message: str, 
        errors: Optional[List[str]] = None, 
        code: Optional[str] = None
    ):
        super().__init__(message)
        self.errors = errors or []
        self.code = code

    def __str__(self):
        error_details = f" - Errors: {', '.join(self.errors)}" if self.errors else ""
        code_details = f" [Code: {self.code}]" if self.code else ""
        return f"{self.__class__.__name__}: {super().__str__()}{error_details}{code_details}"

class ProductNotFoundError(ProductServiceError):
    """Raised when a requested product doesn't exist."""
    def __init__(self, product_id: str, errors: Optional[List[str]] = None):
        message = f"Product {product_id} not found"
        super().__init__(
            message=message,
            errors=errors or [f"product_id={product_id}: error=not_found"],
            code=ErrorCodes.PRODUCT_NOT_FOUND
        )

class InvalidProductDataError(ProductServiceError):
    """Raised when product data fails validation."""
    def __init__(self, message: str = "Invalid product data", errors: Optional[List[str]] = None):
        super().__init__(
            message=message,
            errors=errors or [message],
            code=ErrorCodes.INVALID_DATA
        )

class ProductCreationError(ProductServiceError):
    """Raised when product creation fails."""
    def __init__(self, reason: str = "Unspecified reason", errors: Optional[List[str]] = None):
        super().__init__(
            message=f"Product creation failed: {reason}",
            errors=errors or [reason],
            code=ErrorCodes.CREATION_FAILED
        )