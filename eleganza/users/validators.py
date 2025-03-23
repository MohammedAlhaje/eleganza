# validators.py
import os
import uuid
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.utils.translation import gettext_lazy as _
from PIL import Image  # Required for image content validation

class AvatarConfig:
    """
    Central configuration for avatar validation and processing rules.
    Maintain all security-related settings in this single location.
    """
    # Allowed file extensions for upload
    ALLOWED_UPLOAD_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp']
    
    # Format for stored files (after conversion)
    OUTPUT_EXTENSION = 'webp'
    
    # Size limits
    MAX_SIZE_MB = 2
    MAX_SIZE_BYTES = MAX_SIZE_MB * 1024 * 1024
    
    # Valid image formats as recognized by Pillow
    VALID_CONTENT_TYPES = ['JPEG', 'PNG', 'WEBP']

class WebPSecurityValidator(FileExtensionValidator):
    """
    Comprehensive avatar validation combining:
    1. File extension check
    2. Actual content verification
    3. Security best practices
    """
    def __init__(self):
        super().__init__(allowed_extensions=AvatarConfig.ALLOWED_UPLOAD_EXTENSIONS)

    def __call__(self, value):
        """
        Performs layered validation:
        1. Check file extension
        2. Verify actual image content
        3. Validate file structure
        """
        # First validate the file extension
        super().__call__(value)
        
        try:
            # Open image to validate actual content
            with Image.open(value) as img:
                self._validate_image_content(img)
                self._validate_image_integrity(img)
        except Exception as e:
            raise ValidationError(
                _("Invalid image file: %(reason)s"),
                code="invalid_image",
                params={'reason': str(e)}
            ) from e

    def _validate_image_content(self, image):
        """Verify the image format matches allowed types"""
        if image.format.upper() not in AvatarConfig.VALID_CONTENT_TYPES:
            raise ValidationError(
                _("Invalid image format: %(format)s. Allowed: %(allowed)s"),
                code="invalid_format",
                params={
                    'format': image.format,
                    'allowed': ', '.join(AvatarConfig.VALID_CONTENT_TYPES)
                }
            )

    def _validate_image_integrity(self, image):
        """Check for corrupted image files"""
        try:
            image.verify()
        except Exception as e:
            raise ValidationError(
                _("Corrupted image file: %(reason)s"),
                code="corrupted_image",
                params={'reason': str(e)}
            ) from e

def secure_avatar_name(instance, filename: str) -> str:
    """
    Generates secure avatar filenames to prevent:
    - Directory traversal
    - File enumeration
    - Collision attacks
    
    Args:
        instance: Related model instance
        filename: Original uploaded filename
        
    Returns:
        str: Secure path in format 'avatars/{uuid}.webp'
    """
    # Extract extension from config (ignore upload extension)
    ext = AvatarConfig.OUTPUT_EXTENSION
    
    # Generate cryptographic random UUID
    filename = f"{uuid.uuid4()}.{ext}"
    
    return os.path.join('avatars', filename)

# Pre-configured validator for model fields
avatar_validator = WebPSecurityValidator()