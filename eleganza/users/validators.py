import os
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
import uuid

# Avatar validation rules
class AvatarConfig:
    """Central configuration for avatar validation rules"""
    ALLOWED_UPLOAD_EXTENSIONS = ['jpg', 'jpeg', 'png','webp']  # What users can upload
    OUTPUT_EXTENSION = 'webp' # What we store // TODO: Implement conversion
    MAX_SIZE_MB = 2
    MAX_SIZE_BYTES = MAX_SIZE_MB * 1024 * 1024

def validate_avatar(image):

    # Extension validation
    ext = os.path.splitext(image.name)[1][1:].lower()
    if ext not in AvatarConfig.ALLOWED_UPLOAD_EXTENSIONS:
        raise ValidationError(
            f"Invalid format. Allowed: {', '.join(AvatarConfig.ALLOWED_UPLOAD_EXTENSIONS)}"
        )

def get_file_extension_validator():
    """Returns validator using centralized config"""
    return FileExtensionValidator(
        allowed_extensions=AvatarConfig.ALLOWED_UPLOAD_EXTENSIONS
    )

def rename_avatar(instance, filename: str) -> str:
    """
    Generates a unique filename for avatar uploads.
    
    Args:
        instance: The model instance associated with the file
        filename: Original filename provided by the user
    
    Returns:
        A path string in the format 'avatars/{uuid}.{extension}'
    """
    # Generate a unique filename using UUID
    unique_id = uuid.uuid4()
    
    # Use the configured output extension regardless of input format
    extension = AvatarConfig.OUTPUT_EXTENSION
    
    # Return the path with the new filename
    return f'avatars/{unique_id}.{extension}'