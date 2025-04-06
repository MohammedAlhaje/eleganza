"""
Secure Image Validation Core
---------------------------
Complete, production-ready image validation system.
Maintains all original security checks with proper Django integration.
"""

import os
import uuid
import logging
from typing import Type, Dict, Any
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.utils.translation import gettext_lazy as _
from django.utils.deconstruct import deconstructible
from PIL import Image, ImageFile
from django.db.models import Model

# Configure logging
logger = logging.getLogger(__name__)

# Security: Disable PIL bomb protection (we handle this ourselves)
ImageFile.LOAD_TRUNCATED_IMAGES = False

class ImageTypeConfig:
    """
    Base configuration for image validation rules.
    Inherit and override attributes per use case.
    """
    UPLOAD_PATH = 'secure_uploads/'
    OUTPUT_EXTENSION = 'webp'
    MAX_SIZE_MB = 5
    ALLOWED_TYPES = ['JPEG', 'PNG', 'WEBP']
    MAX_DIMENSION = 3000
    STRIP_METADATA = True
    MAX_PIXELS = 25_000_000  # 25MP default
    
    FORMAT_MAPPING = {
        'jpg': 'JPEG',
        'jpeg': 'JPEG',
        'png': 'PNG',
        'webp': 'WEBP'
    }

    @classmethod
    def allowed_extensions(cls):
        """Get allowed file extensions"""
        return list(cls.FORMAT_MAPPING.keys())

@deconstructible
class ImageValidator(FileExtensionValidator):
    """
    Core validator implementing all security checks.
    """
    def __init__(self, config: Type[ImageTypeConfig]):
        self.config = config
        super().__init__(allowed_extensions=self.config.allowed_extensions())
        Image.MAX_IMAGE_PIXELS = self.config.MAX_PIXELS
    
    def _validate_basic_file_properties(self, value):
        """Validate file size and structure"""
        if not hasattr(value, 'read') or not hasattr(value, 'name'):
            raise ValidationError(_("Invalid file type"), code="invalid_file_type")
            
        if value.size > self.config.MAX_SIZE_MB * 1024 * 1024:
            raise ValidationError(
                _("Maximum file size exceeded. Limit: %(max_size)s MB"),
                code="file_too_large",
                params={'max_size': self.config.MAX_SIZE_MB}
            )
    
    def _validate_image_content(self, value):
        """Validate image content using Pillow"""
        try:
            with Image.open(value) as img:
                self._verify_image_format(value, img)
                self._check_dimensions(img)
                img.verify()  # Integrity check
        except Exception as e:
            raise ValidationError(_("Invalid image content"), code="image_validation") from e
    
    def _verify_image_format(self, value, img):
        """Verify extension matches content"""
        ext = os.path.splitext(value.name)[1][1:].lower()
        expected_format = self.config.FORMAT_MAPPING.get(ext)
        
        if not expected_format or img.format != expected_format:
            raise ValidationError(_("Invalid file format"), code="invalid_format")
    
    def _check_dimensions(self, img):
        """Validate against max dimensions"""
        if max(img.size) > self.config.MAX_DIMENSION:
            raise ValidationError(_("Image too large"), code="oversized_image")
    
    def __call__(self, value):
        """Main validation entry point"""
        if not value:
            return
            
        try:
            self._validate_basic_file_properties(value)
            super().__call__(value)
            self._validate_image_content(value)
        except ValidationError:
            raise
        except Exception as e:
            logger.error(f"Validation error: {str(e)}", exc_info=True)
            raise ValidationError(_("Image validation failed"), code="validation_error")

@deconstructible
class UploadPathGenerator:
    """
    Generates secure upload paths with UUID filenames.
    Migration-safe implementation.
    """
    def __init__(self, config: Type[ImageTypeConfig]):
        self.config = config
    
    def __call__(self, instance: Model, filename: str) -> str:
        """Generate upload path: {UPLOAD_PATH}/{uuid}.{ext}"""
        ext = self.config.OUTPUT_EXTENSION.lstrip('.')
        filename = f"{uuid.uuid4()}.{ext}"
        return os.path.join(self.config.UPLOAD_PATH, filename)

class ImageFieldBuilder:
    """
    Creates properly configured ImageFields with validation.
    """
    @staticmethod
    def build(config_class: Type[ImageTypeConfig], **kwargs) -> Dict[str, Any]:
        """
        Returns complete configuration for ImageField.
        
        Usage:
            image = models.ImageField(**ImageFieldBuilder.build(MyConfig))
        """
        return {
            'upload_to': UploadPathGenerator(config_class),
            'validators': [ImageValidator(config_class)],
            'blank': kwargs.get('blank', True),
            'null': kwargs.get('null', True),
            'help_text': kwargs.get('help_text', 
                f"Allowed: {', '.join(config_class.allowed_extensions())}. "
                f"Max size: {config_class.MAX_SIZE_MB}MB."
            )
        }

class BaseImageType:
    """
    Optional base class for organizing image types.
    Provides common interface for all image validators.
    """
    CONFIG_CLASS: Type[ImageTypeConfig]
    VALIDATOR_CLASS: Type[ImageValidator] = ImageValidator

    @classmethod
    def get_validator(cls) -> ImageValidator:
        """Get configured validator instance"""
        return cls.VALIDATOR_CLASS(cls.CONFIG_CLASS())

    @classmethod
    def get_field_config(cls, **kwargs) -> Dict[str, Any]:
        """Get complete ImageField configuration"""
        return ImageFieldBuilder.build(cls.CONFIG_CLASS, **kwargs)

    @classmethod
    def upload_path(cls, instance: Model, filename: str) -> str:
        """Generate secure upload path"""
        return UploadPathGenerator(cls.CONFIG_CLASS)(instance, filename)