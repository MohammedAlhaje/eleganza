# users/validators.py
from eleganza.core.validators import ImageTypeConfig, BaseImageValidator, secure_image_name

class AvatarConfig(ImageTypeConfig):
    UPLOAD_PATH = 'avatars/'
    MAX_SIZE_MB = 2
    MAX_DIMENSION = 2000

class AvatarValidator(BaseImageValidator):
    def __init__(self):
        super().__init__(AvatarConfig)

def avatar_path(instance, filename):
    return secure_image_name(instance, filename, AvatarConfig)