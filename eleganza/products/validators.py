from core.validators import ImageTypeConfig, ImageValidator, secure_image_upload_path
import os

class ProductImageConfig(ImageTypeConfig):
    """Configuration for product images"""
    UPLOAD_PATH = 'products/'
    OUTPUT_EXTENSION = 'webp'
    MAX_SIZE_MB = 5
    QUALITY = 100
    MAX_DIMENSION = 3000
    STRIP_METADATA = True  # Recommended for product images

class ProductImageValidator(ImageValidator):
    """Validator for product images with product-specific rules"""
    def __init__(self):
        super().__init__(ProductImageConfig())

def product_image_path(instance, filename):
    """
    Secure path generator for product images
    
    Args:
        instance: Model instance
        filename: Original filename
        
    Returns:
        str: Secure upload path
    """
    return secure_image_upload_path(instance, filename, ProductImageConfig)


class CategoryImageConfig(ImageTypeConfig):
    """Configuration for category images"""
    UPLOAD_PATH = 'categories/'
    OUTPUT_EXTENSION = 'webp'
    MAX_SIZE_MB = 5
    QUALITY = 100
    MAX_DIMENSION = 3000
    STRIP_METADATA = True  # Recommended for category images

class CategoryImageValidator(ImageValidator):
    """Validator for category images with category-specific rules"""
    def __init__(self):
        super().__init__(CategoryImageConfig())

def category_image_path(instance, filename):
    """
    Secure path generator for category images
    
    Args:
        instance: Model instance
        filename: Original filename
        
    Returns:
        str: Secure upload path
    """
    return secure_image_upload_path(instance, filename, CategoryImageConfig)