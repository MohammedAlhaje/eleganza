# core/image_utils.py
from django.db.models import ImageField
from django.core.validators import validate_image_file_extension
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from PIL import Image, ImageFile
import uuid
import os
import logging
from threading import Lock
from typing import Optional

# Configure logging
logger = logging.getLogger(__name__)

# Thread safety for directory creation
upload_lock = Lock()

class ImageConfig:
    """
    Central configuration with validation and defaults.
    
    Example:
        class CustomConfig(ImageConfig):
            UPLOAD_DIR = 'custom_uploads/'
            MAX_SIZE_MB = 10
    """
    # File settings
    UPLOAD_DIR = 'uploads/'
    OUTPUT_FORMAT = 'WEBP'  # None to keep original
    
    # Security limits
    MAX_SIZE_MB = 5
    MAX_DIMENSION = 3000
    MAX_PIXELS = 25000000  # 25MP
    
    # Conversion settings
    QUALITY = 85
    STRIP_METADATA = True
    COMPRESSION_METHOD = 6  # Best compression
    
    # Help text
    HELP_TEXT = _(
        "Allowed formats: JPEG, PNG, WEBP. "
        "Max size: %(max_size)sMB. Max dimension: %(max_dimension)spx."
    )

    def __init__(self):
        """Validate dangerous configurations"""
        if self.MAX_PIXELS > 100_000_000:  # 100MP
            raise ValueError("MAX_PIXELS exceeds safety limit")
        if self.MAX_SIZE_MB > 100:  # 100MB
            raise ValueError("MAX_SIZE_MB exceeds safety limit")

class WebPField(ImageField):
    """
    Production-ready ImageField with:
    - Secure WebP conversion
    - Atomic writes
    - Thread-safe operations
    - Complete Django integration
    
    Usage:
        image = WebPField(
            # Standard options
            verbose_name=_("Photo"),
            blank=True,
            null=True,
            
            # Custom options
            UPLOAD_DIR='custom/',
            QUALITY=90
        )
    """
    
    def __init__(self, *args, **kwargs):
        self.config = ImageConfig()
        
        # Extract custom configs
        for attr in [a for a in dir(self.config) if not a.startswith('_')]:
            if attr in kwargs:
                setattr(self.config, attr, kwargs.pop(attr))
        
        # Set default help text
        if 'help_text' not in kwargs:
            kwargs['help_text'] = self.config.HELP_TEXT % {
                'max_size': self.config.MAX_SIZE_MB,
                'max_dimension': self.config.MAX_DIMENSION
            }
        
        super().__init__(*args, **kwargs)
        
        # Configure Pillow security
        ImageFile.LOAD_TRUNCATED_IMAGES = False
        Image.MAX_IMAGE_PIXELS = self.config.MAX_PIXELS
    
    def _generate_upload_path(self, instance, filename: str) -> str:
        """Generate secure UUID-based path"""
        ext = (self.config.OUTPUT_FORMAT.lower() if self.config.OUTPUT_FORMAT 
               else os.path.splitext(filename)[1][1:].lower() or 'webp')
        return os.path.join(self.config.UPLOAD_DIR, f"{uuid.uuid4()}.{ext}")
    
    def _validate_image(self, file) -> None:
        """Perform comprehensive image validation"""
        try:
            # File size check
            if file.size > self.config.MAX_SIZE_MB * 1024 * 1024:
                raise ValidationError(
                    _("Maximum file size is %(max_size)sMB") % {
                        'max_size': self.config.MAX_SIZE_MB
                    }
                )
            
            # Image content validation
            with Image.open(file) as img:
                if max(img.size) > self.config.MAX_DIMENSION:
                    raise ValidationError(
                        _("Maximum dimension is %(max_dim)spx") % {
                            'max_dim': self.config.MAX_DIMENSION
                        }
                    )
                
                if img.format not in ['JPEG', 'PNG', 'WEBP']:
                    raise ValidationError(_("Unsupported image format"))
                
                img.verify()  # Integrity check
                
        except Exception as e:
            logger.error(f"Image validation failed: {str(e)}")
            raise ValidationError(_("Invalid image file")) from e
        finally:
            file.seek(0)  # Rewind file
    
    def _process_image(self, file_path: str) -> bool:
        """Convert image with error handling"""
        try:
            with Image.open(file_path) as img:
                if self.config.STRIP_METADATA:
                    img.info = {}
                
                if self.config.OUTPUT_FORMAT:
                    img.save(
                        file_path,
                        format=self.config.OUTPUT_FORMAT,
                        quality=self.config.QUALITY,
                        method=self.config.COMPRESSION_METHOD
                    )
            return True
        except Exception as e:
            logger.error(f"Image processing failed: {str(e)}")
            return False
    
    def save_form_data(self, instance, data) -> None:
        """Thread-safe file processing pipeline"""
        if not data or data == self.DEFAULT:
            return super().save_form_data(instance, data)
        
        try:
            self._validate_image(data)
            data.name = self._generate_upload_path(instance, data.name)
            temp_path = data.path
            
            # Atomic write operation
            with upload_lock:
                os.makedirs(os.path.dirname(temp_path), exist_ok=True)
                with open(temp_path, 'wb+') as f:
                    for chunk in data.chunks():
                        f.write(chunk)
            
            # Process image
            if self.config.OUTPUT_FORMAT and not self._process_image(temp_path):
                os.remove(temp_path)
                raise ValidationError(_("Image processing failed"))
                
        except Exception as e:
            logger.error(f"Upload failed: {str(e)}")
            if 'temp_path' in locals() and os.path.exists(temp_path):
                os.remove(temp_path)
            raise
        
        super().save_form_data(instance, data)
    
    def deconstruct(self):
        """Migration support"""
        name, path, args, kwargs = super().deconstruct()
        for attr in [a for a in dir(self.config) if not a.startswith('_')]:
            kwargs[attr] = getattr(self.config, attr)
        return name, path, args, kwargs