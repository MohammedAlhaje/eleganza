import os
import uuid
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.utils.translation import gettext_lazy as _
from PIL import Image

class ImageTypeConfig:
    """
    Base configuration for image handling. Inherit and override for specific types.
    Example usage:
    class AvatarConfig(ImageTypeConfig):
        UPLOAD_PATH = 'avatars/'
        ALLOWED_UPLOAD_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp']
        MAX_SIZE_MB = 2
        MAX_DIMENSION = 2000
    """
    UPLOAD_PATH = 'generic/'
    ALLOWED_UPLOAD_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp', 'jfif']
    OUTPUT_EXTENSION = 'webp'
    MAX_SIZE_MB = 5
    VALID_CONTENT_TYPES = ['JPEG', 'PNG', 'WEBP']  # Matches PIL format names
    MAX_DIMENSION = 4000

class BaseImageValidator(FileExtensionValidator):
    """
    Generic image validator that can be configured for different use cases.
    """
    def __init__(self, config_class):
        self.config = config_class()
        super().__init__(allowed_extensions=self.config.ALLOWED_UPLOAD_EXTENSIONS)

    def __call__(self, value):
        # Reset file pointer to the beginning
        value.seek(0)
        
        # Check file size
        if value.size > self.config.MAX_SIZE_MB * 1024 * 1024:
            raise ValidationError(
                _("File size too large. Max size: %(max_size)d MB"),
                code="file_too_large",
                params={'max_size': self.config.MAX_SIZE_MB}
            )
        
        # Validate file extension
        super().__call__(value)
        
        try:
            # First image opening: check format and verify integrity
            value.seek(0)  # Ensure pointer is at start
            with Image.open(value) as img:
                if img.format not in self.config.VALID_CONTENT_TYPES:
                    raise ValidationError(
                        _("Invalid image format: %(format)s. Allowed: %(allowed)s"),
                        code="invalid_format",
                        params={
                            'format': img.format,
                            'allowed': ', '.join(self.config.VALID_CONTENT_TYPES)
                        }
                    )
                try:
                    img.verify()
                except Exception:
                    pass  # Ignore verification errors for now
            
            # Second image opening: check dimensions
            value.seek(0)  # Reset pointer again
            with Image.open(value) as img:
                width, height = img.size
                if max(width, height) > self.config.MAX_DIMENSION:
                    raise ValidationError(
                        _("Image dimensions too large. Max dimension: %(dim)dpx"),
                        code="oversized_image",
                        params={'dim': self.config.MAX_DIMENSION}
                    )
        except Exception as e:
            raise ValidationError(
                _("Upload a valid image. The file you uploaded was either not an image or a corrupted image. Reason: %(reason)s"),
                code="invalid_image",
                params={'reason': str(e)}
            ) from e
        finally:
            value.seek(0)  # Reset pointer for subsequent processing

def secure_image_name(instance, filename: str, config_class) -> str:
    """
    Generic secure filename generator.
    """
    ext = config_class.OUTPUT_EXTENSION
    filename = f"{uuid.uuid4()}.{ext}"
    return os.path.join(config_class.UPLOAD_PATH, filename)