class ImageConstants:
    """Image upload and processing settings"""
    
    MAX_SIZE = 5 * 1024 * 1024  # 5MB - Max file size
    ALLOWED_FORMATS = ['jpg', 'jpeg', 'png', 'gif']  # Supported formats
    UPLOAD_PATHS = {
        'CATEGORY': 'products/categories/',  # Category image path
        'PRODUCT': 'products/products/'      # Product image path
    }
    RESIZE_DIMENSIONS = (1920, 1920)  # Target image dimensions
    QUALITY = 85      