import uuid
from django.db import models
from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.utils.translation import gettext_lazy as _
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.contrib.auth.hashers import check_password
from django_countries.fields import CountryField
from phonenumber_field.modelfields import PhoneNumberField
from timezone_field import TimeZoneField
from imagekit.models import ProcessedImageField
from imagekit.processors import ResizeToFill, Transpose
from eleganza.core.models import SoftDeleteModel, TimeStampedModel
from .validators import AvatarValidator, avatar_upload_path,AvatarConfig
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.utils.text import slugify


class SpaceAllowedUsernameValidator(UnicodeUsernameValidator):
    regex = r'^[\w.@+ -]+\Z'
    message = _(
        "Enter a valid username. This value may contain letters, digits, "
        "@/./+/-/_ characters, and spaces."
    )


class ContactMethod(models.Model):
    name = models.CharField(_("Name"), max_length=50)
    code = models.SlugField(_("Code"), unique=True)
    is_active = models.BooleanField(_("Active"), default=True)
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated at"), auto_now=True)

    def save(self, *args, **kwargs):
        self.code = slugify(self.name)
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = _("Contact Method")
        verbose_name_plural = _("Contact Methods")
        ordering = ['name']

    def __str__(self):
        return self.name


class UserManager(BaseUserManager):
    """Enhanced user manager with complete validation chain"""
    
    def _validate_creation_fields(self, username, email):
        """Centralized validation for required fields"""
        if not email:
            raise ValueError(_('The Email must be set'))
        if not username:
            raise ValueError(_('The Username must be set'))

    def create_user(self, username, email, password=None, **extra_fields):
        """Create user with full validation pipeline"""
        self._validate_creation_fields(username, email)
        
        user = self.model(
            username=username,
            email=self.normalize_email(email),
            **extra_fields
        )
        user.set_password(password)
        user.full_clean()
        user.save(using=self._db)
        return user

    def create_superuser(self, username, email, password=None, **extra_fields):
        """Create superuser with explicit privilege escalation"""
        extra_fields.setdefault('type', User.Types.TEAM_MEMBER)
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(username, email, password, **extra_fields)

class User(AbstractUser, SoftDeleteModel, TimeStampedModel):
    """Core user model with password history validation"""
    
    class Types(models.TextChoices):
        CUSTOMER = "CUSTOMER", _("Customer")
        TEAM_MEMBER = "TEAM_MEMBER", _("Team Member")
    
    uuid = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        help_text=_("Public user identifier for API interactions")
    )

    username = models.CharField(
        _("username"),
        max_length=150,
        unique=True,
        null=True,
        blank=True,
        default=None,
        help_text=_("Optional. 150 characters or fewer. Letters, digits, spaces, and @/./+/-/_ only."),
        validators=[SpaceAllowedUsernameValidator()],
    )
    
    email = models.EmailField(
        _('email address'), 
        unique=True,
        blank=False,
        help_text=_("Verified contact email address")
    )
    
    display_name = models.CharField(
        _("display name"),
        max_length=150,
        blank=True,
        help_text=_("Public facing name (optional)")
    )

    type = models.CharField(
        _("User Type"),
        max_length=20,
        choices=Types.choices,
        default=Types.CUSTOMER,
        db_index=True
    )

    objects = UserManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['username'],
                name='unique_non_empty_username',
                condition=models.Q(username__isnull=False)),
        ]
        
    def set_password(self, raw_password):
        """Override password setting with history validation"""
        if self.pk:  # Only check history for existing users
            max_history = getattr(settings, 'PASSWORD_HISTORY_LIMIT', 5)
            
            # Prevent reusing current password
            if self.check_password(raw_password):
                raise ValidationError(_("New password must differ from current password."))
            
            # Check against password history
            last_passwords = self.password_history.order_by('-created_at')[:max_history]
            for entry in last_passwords:
                if check_password(raw_password, entry.password):
                    raise ValidationError(
                        _("Cannot reuse any of your last %(count)d passwords.") % {'count': max_history}
                    )
        
        super().set_password(raw_password)

    def save(self, *args, **kwargs):
        """Handle initial password history creation"""
        creating = self.pk is None
        super().save(*args, **kwargs)
        
        # For new users, create initial password history entry
        if creating:
            PasswordHistory.objects.create(
                user=self,
                password=self.password
            )

    def clean(self):
        super().clean()
        validate_email(self.email)

    def __str__(self):
        return f"{self.username} ({self.uuid})"

class UserProfile(models.Model):
    """Base profile with internationalization and biometrics"""
    
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='%(class)s_profile',
        verbose_name=_("System User")
    )
    
    phone = PhoneNumberField(
        _("Phone Number"),
        blank=True,
        null=True,
        help_text=_("International format (+CountryCode...)")
    )
    
    timezone = TimeZoneField(
        _("Timezone"),
        default='UTC',
        help_text=_("User's preferred timezone")
    )
    
    language = models.CharField(
        _("Language"),
        max_length=10,
        choices=settings.LANGUAGES,
        default=settings.LANGUAGE_CODE,
        help_text=_("Interface language preference")
    )
    
    avatar = ProcessedImageField(
        verbose_name=_("Avatar"),
        upload_to=avatar_upload_path,
        processors=[
            Transpose(),  # Auto-rotate based on EXIF
            ResizeToFill(AvatarConfig.MAX_DIMENSION, AvatarConfig.MAX_DIMENSION),  # Force exact dimensions
        ],
        format='WEBP',
        options={'quality': AvatarConfig.QUALITY},
        validators=[AvatarValidator()],
        blank=True,
        null=True,
        default="avatars/default.webp",
        help_text=_("User profile image. Will be converted to WEBP format."),
    )

    class Meta:
        abstract = True

    def __str__(self):
        return f"{self.user.username}'s Profile"

class CustomerProfile(UserProfile):
    """Consumer profile with commerce preferences"""

    loyalty_points = models.PositiveIntegerField(
        _("Loyalty Points"),
        default=0,
        db_index=True
    )
    
    newsletter_subscribed = models.BooleanField(
        _("Newsletter Subscribed"),
        default=False
    )
    
    preferred_contact_method = models.ForeignKey(
        ContactMethod,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_("Preferred Contact Method")
    )
    
    default_currency = models.CharField(
        _("Default Currency"),
        max_length=3,
        choices=settings.CURRENCY_CHOICES,
        default=settings.DEFAULT_CURRENCY
    )

class TeamMemberProfile(UserProfile):
    """Staff profile with operational permissions"""
    
    department = models.CharField(
        _("Department"),
        max_length=50,
        choices=[
            ('sales', _('Sales')),
            ('support', _('Support')),
            ('management', _('Management'))
        ],
        db_index=True
    )
    
    can_approve_orders = models.BooleanField(
        _("Can Approve Orders"),
        default=False
    )
    
    default_currency = models.CharField(
        _("Default Currency"),
        max_length=3,
        choices=settings.CURRENCY_CHOICES,
        default=settings.DEFAULT_CURRENCY
    )
    
    profit_percentage = models.DecimalField(
        _("Profit Percentage"),
        max_digits=5,
        decimal_places=2,
        default=0.0,
        blank=True,
        null=True,
        help_text=_("Percentage of profit to be shared with the team member")
    )

class Address(models.Model):
    """Geolocation data with validation"""
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='addresses',
        limit_choices_to={'type': User.Types.CUSTOMER}
    )
    
    street = models.CharField(
        _("Street Address"),
        max_length=255,
        help_text=_("Building number and street name")
    )
    
    city = models.CharField(
        _("City"),
        max_length=100,
        db_index=True
    )
    
    postal_code = models.CharField(
        _("Postal Code"),
        max_length=20,
        blank=True
    )
    
    country = CountryField(
        _("Country"),
        default='LY'
    )
    
    is_primary = models.BooleanField(
        _("Primary Address"),
        default=False,
        db_index=True
    )

    class Meta:
        verbose_name = _("Address")
        verbose_name_plural = _("Addresses")
        ordering = ['-is_primary', 'city']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'street', 'city', 'postal_code'],
                name='unique_user_address')
        ]

    def __str__(self):
        return f"{self.city}, {self.country.name}"

class PasswordHistory(models.Model):
    """Security audit trail for credential changes"""
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='password_history'
    )
    
    password = models.CharField(
        _("Password Hash"),
        max_length=255,
        help_text=_("Hashed password value")
    )
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True
    )

    class Meta:
        verbose_name = _("Password History")
        verbose_name_plural = _("Password Histories")
        ordering = ['-created_at']

    def __str__(self):
        return f"Auth Record #{self.pk}"
    
