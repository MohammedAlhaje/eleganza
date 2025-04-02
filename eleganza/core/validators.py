"""
Secure Image Validation Module
-----------------------------
Provides robust image validation and processing with security-first approach.
Features:
- Content-type verification
- Animated image detection
- EXIF data handling
- Decompression bomb protection
- Metadata consistency checks
- Secure filename generation
"""

import os
import uuid
import logging
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.utils.translation import gettext_lazy as _
from PIL import Image, ImageFile, UnidentifiedImageError
from PIL.ExifTags import TAGS

# Configure logging
logger = logging.getLogger(__name__)

# Disable PIL decompression bomb protection (we handle this ourselves)
ImageFile.LOAD_TRUNCATED_IMAGES = False

class ImageTypeConfig:
    """
    Configuration for secure image handling with safety defaults.
    Inherit and override for specific use cases.
    """
    
    # File handling
    UPLOAD_PATH = 'secure_uploads/'
    OUTPUT_EXTENSION = 'webp'
    MAX_SIZE_MB = 5
    
    # Content restrictions
    ALLOWED_TYPES = ['JPEG', 'PNG', 'WEBP']  # PIL format names
    MAX_DIMENSION = 3000  # Maximum width/height in pixels
    QUALITY = 85  # Output quality for lossy formats
    ALLOW_ANIMATED = False
    STRIP_METADATA = True
    
    # Security parameters
    MAX_PIXELS = 25_000_000  # 25MP default limit
    
    # Extension mapping (extension: PIL format)
    FORMAT_MAPPING = {
        'jpg': 'JPEG',
        'jpeg': 'JPEG',
        'png': 'PNG',
        'webp': 'WEBP',
        'jfif': 'JPEG'
    }
    
    @property
    def allowed_extensions(self):
        """Derive allowed extensions from format mapping"""
        return list(self.FORMAT_MAPPING.keys())

class BaseImageValidator(FileExtensionValidator):
    """
    Comprehensive image validator with multiple security layers.
    Inherits from Django's FileExtensionValidator for basic extension checks.
    """
    
    def __init__(self, config_class=ImageTypeConfig):
        self.config = config_class()
        super().__init__(allowed_extensions=self.config.allowed_extensions)
        self._configure_pillow()
    
    def _configure_pillow(self):
        """Set up Pillow security parameters"""
        Image.MAX_IMAGE_PIXELS = self.config.MAX_PIXELS
    
    def _validate_basic_file_properties(self, value):
        """Initial file property checks"""
        if not hasattr(value, 'read') or not hasattr(value, 'name'):
            logger.error("Invalid file object structure")
            raise ValidationError(
                _("Invalid file type"),
                code="invalid_file_type"
            )
            
        if value.size > self.config.MAX_SIZE_MB * 1024 * 1024:
            logger.error(f"File size exceeded: {value.size} bytes")
            raise ValidationError(
                _("Maximum file size exceeded. Limit: %(max_size)s MB"),
                code="file_too_large",
                params={'max_size': self.config.MAX_SIZE_MB}
            )
    
    def _validate_image_content(self, value):
        """Core image validation logic using Pillow"""
        try:
            with Image.open(value) as img:
                self._verify_image_format(value, img)
                self._check_animation(img)
                self._check_dimensions(img)
                self._verify_image_integrity(img)
                self._check_metadata_consistency(value, img)
        except UnidentifiedImageError as e:
            logger.error(f"Unidentifiable image format: {str(e)}")
            raise ValidationError(
                _("Invalid image format"),
                code="invalid_image_format"
            ) from e
    
    def _verify_image_format(self, value, img):
        """Verify image matches declared extension"""
        ext = value.name.split('.')[-1].lower()
        expected_format = self.config.FORMAT_MAPPING.get(ext)
        
        if img.format != expected_format:
            logger.error(f"Format mismatch: {img.format} vs {expected_format}")
            raise ValidationError(
                _("File extension does not match image content"),
                code="format_mismatch"
            )
    
    def _check_animation(self, img):
        """Detect animated content"""
        if self.config.ALLOW_ANIMATED:
            return
            
        animation_checks = {
            'GIF': lambda: img.is_animated,
            'WEBP': lambda: hasattr(img, 'is_animated') and img.is_animated
        }
        
        if animation_checks.get(img.format, lambda: False)():
            logger.error("Animated content detected")
            raise ValidationError(
                _("Animated images are not allowed"),
                code="animated_content"
            )
    
    def _check_dimensions(self, img):
        """Validate image dimensions"""
        width, height = img.size
        if max(width, height) > self.config.MAX_DIMENSION:
            logger.error(f"Oversized image: {width}x{height}")
            raise ValidationError(
                _("Image dimensions exceed maximum allowed size"),
                code="oversized_image"
            )
    
    def _verify_image_integrity(self, img):
        """Verify image file integrity"""
        try:
            img.verify()
            logger.debug("Image integrity verified")
        except Exception as e:
            logger.error(f"Image verification failed: {str(e)}")
            raise ValidationError(
                _("Invalid or corrupted image file"),
                code="corrupted_image"
            ) from e
    
    def _check_metadata_consistency(self, value, img):
        """Check for metadata/extension inconsistencies"""
        if img.format == 'JPEG' and not value.name.lower().endswith(('.jpg', '.jpeg', '.jfif')):
            logger.error("JPEG content with invalid extension")
            raise ValidationError(
                _("Invalid file extension for JPEG content"),
                code="extension_mismatch"
            )
    
    def __call__(self, value):
        """Main validation entry point"""
        logger.info(f"Validating image: {value.name}")
        original_position = None  # Explicit initialization
        
        # Skip validation for empty values or system files
        if not value:
            logger.debug("Empty value received")
            return
        if value.name == 'default.webp':
            logger.debug("Skipping default image")
            return

        try:
            # File pointer management
            if value.seekable():
                original_position = value.tell()
                value.seek(0)
            
            self._validate_basic_file_properties(value)
            super().__call__(value)  # FileExtensionValidator check
            self._validate_image_content(value)

        except ValidationError as ve:
            logger.error(f"Validation failed: {ve}")
            raise ve
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}", exc_info=True)
            raise ValidationError(
                _("Image validation error"),
                code="validation_error"
            ) from e
        finally:
            # Reset file pointer only if valid position exists
            if value.seekable() and original_position is not None:
                try:
                    value.seek(int(original_position))  # Ensure integer position
                    logger.debug("File pointer reset successfully")
                except (TypeError, OSError) as e:
                    logger.warning(f"Failed to reset file pointer: {str(e)}")

                    
def secure_image_upload_path(instance, filename: str, config_class=ImageTypeConfig) -> str:
    """
    Generate secure upload path with UUID filename and configured extension.
    
    Args:
        instance: Model instance (unused, but required for Django upload_to)
        filename: Original filename (unused)
        config_class: ImageTypeConfig subclass
    
    Returns:
        str: Secure upload path
    """
    config = config_class()
    ext = config.OUTPUT_EXTENSION.lstrip('.')
    filename = f"{uuid.uuid4()}.{ext}"
    return os.path.join(config.UPLOAD_PATH, filename)

def process_image_metadata(image, config_class=ImageTypeConfig):
    """
    Process image metadata according to configuration.
    
    Args:
        image: PIL Image object
        config_class: ImageTypeConfig subclass
    
    Returns:
        PIL Image: Processed image
    """
    config = config_class()
    
    if config.STRIP_METADATA:
        logger.info("Stripping image metadata")
        # Remove EXIF data
        data = list(image.getdata())
        clean_image = Image.new(image.mode, image.size)
        clean_image.putdata(data)
        return clean_image
    
    return image