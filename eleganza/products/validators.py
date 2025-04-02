# products/validators.py (NEW file)
from core.validators import ImageTypeConfig, BaseImageValidator, secure_image_upload_path
import uuid
import os

class ProductImageConfig(ImageTypeConfig):
    UPLOAD_PATH = 'products/'
    MAX_SIZE_MB = 5
    QUALITY = 100
    MAX_DIMENSION = 3000

class ProductImageValidator(BaseImageValidator):
    def __init__(self):
        super().__init__(ProductImageConfig)

def product_image_path(instance, filename):
    """Secure path generator for product images"""
    return secure_image_upload_path(instance, filename, ProductImageConfig)



class CategoryImageConfig(ImageTypeConfig):
    UPLOAD_PATH = 'categories/'
    MAX_SIZE_MB = 5
    QUALITY = 100
    MAX_DIMENSION = 3000

class CategoryImageValidator(BaseImageValidator):
    def __init__(self):
        super().__init__(ProductImageConfig)

def category_image_path(instance, filename):
    """Secure path generator for product images"""
    return secure_image_upload_path(instance, filename, ProductImageConfig)