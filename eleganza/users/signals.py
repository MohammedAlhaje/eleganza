from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.core.files.base import ContentFile
from PIL import Image
from io import BytesIO
import uuid
from .validators import AvatarConfig
from django.core.exceptions import ValidationError

@receiver(pre_save)
def convert_avatar_to_webp(sender, instance, **kwargs):
    """
    Converts avatars to WebP using AvatarConfig:
    - Uses OUTPUT_EXTENSION from config
    - Applies to any model with 'avatar' field
    """
    if not hasattr(instance, 'avatar') or not instance.avatar:
        return

    current_ext = instance.avatar.name.split('.')[-1].lower()
    if current_ext == AvatarConfig.OUTPUT_EXTENSION:
        return

    try:
        with Image.open(instance.avatar) as img:
            buffer = BytesIO()
            
            # Handle transparency
            if img.mode in ('RGBA', 'LA'):
                img = img.convert('RGB')
            
            # Save as WebP with quality setting
            img.save(buffer, 
                    format='WEBP', 
                    quality=85,  # Adjust between 1-100
                    method=6  # Slower encode, smaller file
                    )
            buffer.seek(0)
            
            # Generate new filename
            new_name = f"{uuid.uuid4()}.{AvatarConfig.OUTPUT_EXTENSION}"
            
            # Replace original file
            instance.avatar.save(
                new_name,
                ContentFile(buffer.getvalue()),
                save=False
            )
            
    except Exception as e:
        raise ValidationError(f"Image conversion failed: {str(e)}")