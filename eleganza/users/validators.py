"""
Avatar Image Validation
-----------------------
Specialized validation configuration for user avatar images.
Inherits from and extends the core image validation system.
"""
from django.core.exceptions import ValidationError
from eleganza.core.validators import (
    ImageTypeConfig,
    BaseImageValidator,
    secure_image_upload_path  # Note renamed function
)

class AvatarConfig(ImageTypeConfig):
    """
    Avatar-specific configuration with stricter limits and custom processing.
    Inherits default security settings from core ImageTypeConfig.
    """
    
    # Override core settings
    UPLOAD_PATH = 'avatars/'
    MAX_SIZE_MB = 2
    MAX_DIMENSION = 3000
    QUALITY = 80
    OUTPUT_EXTENSION = 'webp'
    
    # Custom avatar-specific settings
    STRIP_METADATA = True  # Remove EXIF data for avatars
    ALLOW_ANIMATED = False
    
    # Maintain format mapping from core
    FORMAT_MAPPING = {
        **ImageTypeConfig.FORMAT_MAPPING,
        # Add/override formats specific to avatars
        'webp': 'WEBP'
    }

class AvatarValidator(BaseImageValidator):
    """
    Custom validator implementing AvatarConfig with additional avatar-specific checks.
    Extends BaseImageValidator with profile-specific rules.
    """
    
    def __init__(self):
        super().__init__(config_class=AvatarConfig)
    
    def validate_avatar_aspect_ratio(self, image):
        """
        Optional: Add custom aspect ratio validation
        Example implementation for square images
        """
        width, height = image.size
        if width != height:
            raise ValidationError(
                _("Avatar must be square (1:1 aspect ratio)"),
                code="invalid_aspect_ratio"
            )

def avatar_upload_path(instance, filename: str) -> str:
    """
    Generates secure upload path for avatars using UUID filename.
    
    Args:
        instance: UserProfile model instance
        filename: Original filename (ignored)
    
    Returns:
        str: Secure upload path with avatar configuration
    
    Example:
        >>> avatar_upload_path(None, 'myphoto.jpg')
        'avatars/f3c983c4-4d86-4112-9e3a-3d3f4f343192.webp'
    """
    return secure_image_upload_path(instance, filename, AvatarConfig)