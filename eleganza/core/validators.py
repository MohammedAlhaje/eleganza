# core/validators.py
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
    class ProductImageConfig(ImageTypeConfig):
        UPLOAD_PATH = 'products/'
        ALLOWED_UPLOAD_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp']
    """
    UPLOAD_PATH = 'generic/'
    ALLOWED_UPLOWD_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp']
    OUTPUT_EXTENSION = 'webp'
    MAX_SIZE_MB = 5
    VALID_CONTENT_TYPES = ['JPEG', 'PNG', 'WEBP']
    MAX_DIMENSION = 4000

class BaseImageValidator(FileExtensionValidator):
    """
    Generic image validator that can be configured for different use cases
    """
    def __init__(self, config_class):
        self.config = config_class()
        super().__init__(allowed_extensions=self.config.ALLOWED_UPLOWD_EXTENSIONS)

    def __call__(self, value):
        # First validate the file extension
        super().__call__(value)
        
        try:
            with Image.open(value) as img:
                self._validate_image_content(img)
                self._validate_image_integrity(img)
                self._validate_image_dimensions(img)
        except Exception as e:
            raise ValidationError(
                _("Invalid image file: %(reason)s"),
                code="invalid_image",
                params={'reason': str(e)}
            ) from e

    def _validate_image_content(self, image):
        if image.format.upper() not in self.config.VALID_CONTENT_TYPES:
            raise ValidationError(
                _("Invalid image format: %(format)s. Allowed: %(allowed)s"),
                code="invalid_format",
                params={
                    'format': image.format,
                    'allowed': ', '.join(self.config.VALID_CONTENT_TYPES)
                }
            )

    def _validate_image_integrity(self, image):
        try:
            image.verify()
        except Exception as e:
            raise ValidationError(
                _("Corrupted image file: %(reason)s"),
                code="corrupted_image",
                params={'reason': str(e)}
            ) from e

    def _validate_image_dimensions(self, image):
        if max(image.size) > self.config.MAX_DIMENSION:
            raise ValidationError(
                _("Image dimensions too large. Max dimension: %(dim)dpx"),
                code="oversized_image",
                params={'dim': self.config.MAX_DIMENSION}
            )

def secure_image_name(instance, filename: str, config_class) -> str:
    """
    Generic secure filename generator
    """
    ext = config_class.OUTPUT_EXTENSION
    filename = f"{uuid.uuid4()}.{ext}"
    return os.path.join(config_class.UPLOAD_PATH, filename)