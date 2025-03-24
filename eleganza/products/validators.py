# products/validators.py
from eleganza.core.validators import ImageTypeConfig, BaseImageValidator, secure_image_name

class ProductImageConfig(ImageTypeConfig):
    UPLOAD_PATH = 'products/'
    ALLOWED_UPLOWD_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp']
    OUTPUT_EXTENSION = 'webp'
    MAX_SIZE_MB = 10  # Larger size limit for products
    MAX_DIMENSION = 4000
    VALID_CONTENT_TYPES = ['JPEG', 'PNG', 'WEBP']

class ProductImageValidator(BaseImageValidator):
    def __init__(self):
        super().__init__(ProductImageConfig)

def product_image_path(instance, filename):
    return secure_image_name(instance, filename, ProductImageConfig)

# Similarly for category images
class CategoryImageConfig(ImageTypeConfig):
    UPLOAD_PATH = 'categories/'
    MAX_DIMENSION = 2000

class CategoryImageValidator(BaseImageValidator):
    def __init__(self):
        super().__init__(CategoryImageConfig)

def category_image_path(instance, filename):
    return secure_image_name(instance, filename, CategoryImageConfig)