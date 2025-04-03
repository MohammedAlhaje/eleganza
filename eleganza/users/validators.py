"""
Avatar Image Validation
-----------------------
Specialized validation configuration for user avatar images.
Inherits from and extends the core image validation system.
"""
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from PIL import Image  # Add this import for Image
from core.validators import (
    ImageTypeConfig,
    ImageValidator,  # Updated to use ImageValidator instead of BaseImageValidator
    secure_image_upload_path
)

class AvatarConfig(ImageTypeConfig):
    """
    Avatar-specific configuration with stricter limits and custom processing.
    Inherits default security settings from core ImageTypeConfig.
    """
    
    # Override core settings
    UPLOAD_PATH = 'avatars/'
    MAX_SIZE_MB = 2  # 2MB maximum for avatars
    MAX_DIMENSION = 1000  # More restrictive than core (3000px)
    QUALITY = 80  # Slightly lower quality for smaller files
    OUTPUT_EXTENSION = 'webp'  # Force WebP format
    
    # Security settings
    STRIP_METADATA = True  # Always remove EXIF data for privacy
    ALLOW_ANIMATED = False  # No animated avatars
    
    # Format restrictions
    ALLOWED_TYPES = ['JPEG', 'PNG', 'WEBP']  # Explicit allowed formats
    FORMAT_MAPPING = {
        'jpg': 'JPEG',
        'jpeg': 'JPEG',
        'png': 'PNG',
        'webp': 'WEBP'
    }

class AvatarValidator(ImageValidator):
    """
    Custom validator implementing AvatarConfig with additional avatar-specific checks.
    """
    
    def __init__(self):
        super().__init__(config=AvatarConfig())  # Pass config instance
    
    def _validate_image_content(self, value):
        """Extend core validation with avatar-specific rules"""
        super()._validate_image_content(value)  # Core validation first
        
        # Additional avatar-specific validation
        with Image.open(value) as img:
            self._validate_avatar_aspect_ratio(img)
            self._validate_avatar_content(img)

    def _validate_avatar_content(self, image):
        """Additional content checks for avatars"""
        # Example: Could add face detection here
        pass

def avatar_upload_path(instance, filename: str) -> str:
    """
    Generates secure upload path for avatars using UUID filename.
    
    Args:
        instance: User model instance
        filename: Original filename (ignored)
    
    Returns:
        str: Secure path like 'avatars/uuid.webp'
    
    Example:
        'avatars/f3c983c4-4d86-4112-9e3a-3d3f4f343192.webp'
    """
    return secure_image_upload_path(instance, filename, AvatarConfig)