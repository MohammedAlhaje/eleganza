class ValidationPatterns:
    """Regex patterns for field validation"""
    
    SKU = r'^[A-Z0-9-]{8,20}$'        # SKU format validation
    PRODUCT_NAME = r'^[\w\s-]+$'       # Product name validation