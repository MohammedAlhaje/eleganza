import logging
from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.core.files.base import ContentFile
from PIL import Image
from io import BytesIO
import uuid
from .validators import AvatarConfig
from django.core.exceptions import ValidationError
from .models import User  # Explicit import from local module

logger = logging.getLogger(__name__)

@receiver(pre_save, sender=User)  # Critical: Only handle User model saves
def convert_avatar_to_webp(sender, instance, **kwargs):
    """
    Converts avatars to WebP format and validates images.
    Security enhancements:
    - Restricted to User model only
    - Defensive NULL handling for invalid files
    - Structured error logging
    """
    
    # Exit early if no avatar or already in target format
    if not instance.avatar:
        return

    current_ext = instance.avatar.name.split('.')[-1].lower()
    if current_ext == AvatarConfig.OUTPUT_EXTENSION:
        return

    try:
        with Image.open(instance.avatar) as img:
            # Convert image to WebP
            buffer = BytesIO()
            
            # Preserve transparency if needed
            if img.mode in ('RGBA', 'LA'):
                img = img.convert('RGB')

            # Optimized WebP conversion
            img.save(
                buffer,
                format='WEBP',
                quality=85,  # Optimal quality/size balance
                method=6,     # Slower encode for better compression
                lossless=False
            )
            buffer.seek(0)

            # Generate secure filename
            new_name = f"{uuid.uuid4()}.{AvatarConfig.OUTPUT_EXTENSION}"
            
            # Replace file content while preserving FieldFile reference
            instance.avatar.save(
                new_name,
                ContentFile(buffer.getvalue()),
                save=False
            )

    except Exception as e:
        # Critical security fix: Prevent invalid files from persisting
        logger.error(f"Avatar conversion failed for user {instance.pk}: {str(e)}")
        instance.avatar = None  # Clear invalid file reference
        
        # Preserve original error while avoiding raw exposure
        raise ValidationError(
            "Avatar processing failed. Please try another image."
        ) from e
    

from allauth.mfa.models import Authenticator