from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from phonenumber_field.modelfields import PhoneNumberField
from timezone_field import TimeZoneField
from encrypted_model_fields.fields import EncryptedCharField
from django_countries.fields import CountryField
from djmoney.models.fields import CurrencyField
from datetime import date
from .validators import rename_avatar, validate_avatar, get_file_extension_validator
from django.utils.translation import gettext_lazy as _
from django.urls import reverse
from django.conf import settings
from djmoney.settings import CURRENCY_CHOICES


class UserManager(BaseUserManager):
    """Custom user manager with soft deletion support"""
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)

    def create_user(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        return self._create_user(username, email, password, **extra_fields)

    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self._create_user(username, email, password, **extra_fields)

    def _create_user(self, username, email, password, **extra_fields):
        if not username:
            raise ValueError('The given username must be set')
        email = self.normalize_email(email)
        user = self.model(username=username, email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user


class User(AbstractUser):
    """Custom User model with enhanced fields and soft deletion"""
    # Core identification fields

    display_name = models.CharField(max_length=150, blank=True, null=True)

    phone = PhoneNumberField(
        unique=False, blank=True, null=True,
        help_text=_("User's phone number in international format.")
    )

    # Phone verification fields
    is_phone_verified = models.BooleanField(
        default=False,
        help_text=_("Flag indicating if the user's phone number has been verified.")
    )
    phone_verified_at = models.DateTimeField(
        blank=True, null=True,
        help_text=_("Timestamp when the user's phone number was verified.")
    )

    # Consent fields
    data_consent = models.BooleanField(
        default=False,
        help_text=_("Flag indicating if the user has consented to data processing.")
    )
    data_consent_at = models.DateTimeField(
        blank=True, null=True,
        help_text=_("Timestamp when the user gave data processing consent.")
    )
    marketing_consent = models.BooleanField(
        default=False,
        help_text=_("Flag indicating if the user has consented to receive marketing communications.")
    )
    marketing_consent_at = models.DateTimeField(
        blank=True, null=True,
        help_text=_("Timestamp when the user gave marketing consent.")
    )

    # User preferences
    timezone = TimeZoneField(
        default='UTC',
        help_text=_("User's preferred timezone for displaying dates and times.")
    )
    language = models.CharField(
        max_length=10, default='en',
        choices=settings.LANGUAGES, 
        help_text=_("User's preferred language (ISO 639-1 code).")
    )
    default_currency = CurrencyField(
        default='USD',
        choices=CURRENCY_CHOICES,
        help_text=_("User's preferred currency for transactions and pricing.")
    )

    # Security fields
    failed_login_attempts = models.IntegerField(
        default=0,
        help_text=_("Number of consecutive failed login attempts.")
    )
    locked_until = models.DateTimeField(
        blank=True, null=True,
        help_text=_("Timestamp until which the account is locked.")
    )
    password_updated_at = models.DateTimeField(
        blank=True, null=True,
        help_text=_("Timestamp of the last password change.")
    )

    # Profile fields
    avatar = models.ImageField(
        upload_to=rename_avatar,
        blank=True,
        null=True,
        default="avatars/default.webp",
        validators=[validate_avatar, get_file_extension_validator()],
        help_text=_("Profile picture. Formats: JPG/PNG/WEBP. Max 2MB.")
    )
    date_of_birth = models.DateField(
        blank=True, null=True,
        help_text=_("Date of birth for age verification.")
    )

    # Audit fields
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(
        blank=True, null=True,
        help_text=_("Timestamp for soft deletion.")
    )

    # Versioning
    version = models.IntegerField(
        default=0,
        editable=False,
        help_text=_("Version number for concurrency control.")
    )

    # Managers
    objects = UserManager()
    all_objects = models.Manager()  # Includes deleted users

    def clean(self):
        """Comprehensive validation for user data"""
        super().clean()

        # Date of birth validation
        if self.date_of_birth:
            today = timezone.now().date()
            if self.date_of_birth >= today:
                raise ValidationError(
                    {'date_of_birth': _('Date of birth must be in the past.')}
                )
            age = today.year - self.date_of_birth.year
            if (today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day):
                age -= 1
            if age < 13:
                raise ValidationError(
                    _("Users must be at least 13 years old."),
                    code='underage'
                )

        # Avatar validation
        if self.avatar:
            validate_avatar(self.avatar)

    def delete(self, *args, **kwargs):
        """Soft delete implementation"""
        self.deleted_at = timezone.now()
        self.is_active = False  # deactivate the user
        self.save()

    def set_password(self, raw_password):
        """Track password changes for existing users only"""
        super().set_password(raw_password)
        self.password_updated_at = timezone.now()

        # Only create history if user already exists in DB
        if self.pk:
            PasswordHistory.objects.create(
                user=self,
                password_hash=self.password
            )

    def save(self, *args, **kwargs):
        """Create initial password history for new users"""
        is_new = self.pk is None  # Check if creating new user
        super().save(*args, **kwargs)

        # Create initial password history after first save
        if is_new:
            PasswordHistory.objects.create(
                user=self,
                password_hash=self.password
            )

    def get_absolute_url(self):
        """Returns the URL to access a particular user instance."""
        return reverse('users:detail', kwargs={'username': self.username})

    class Meta:
        indexes = [
            models.Index(fields=['email']),
            models.Index(fields=['phone']),
            models.Index(fields=['is_active', 'deleted_at']),
            models.Index(fields=['created_at']),
        ]
        verbose_name = _('user')
        verbose_name_plural = _('users')


class PasswordHistory(models.Model):
    """Secure password history tracking"""
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='password_history',
        help_text=_("Associated user account.")
    )
    password_hash = models.CharField(
        max_length=255,
        help_text=_("Securely hashed password representation.")
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text=_("Timestamp when password was set.")
    )

    class Meta:
        unique_together = ('user', 'password_hash')
        ordering = ['-created_at']
        verbose_name = _('password history')
        verbose_name_plural = _('password histories')


class Address(models.Model):
    """Enhanced address model with proper validation"""
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='addresses',
        help_text=_("Associated user account.")
    )
    street = models.CharField(
        max_length=255,
        help_text=_("Street name and number.")
    )
    city = models.CharField(
        max_length=100,
        help_text=_("City or locality name.")
    )
    state = models.CharField(
        max_length=100,
        help_text=_("State, province, or region.")
    )
    postal_code = models.CharField(
        max_length=20,
        help_text=_("Postal or ZIP code.")
    )
    country = CountryField(
        help_text=_("Country location.")
    )
    is_default = models.BooleanField(
        default=False,
        help_text=_("Default address flag.")
    )
    version = models.IntegerField(
        default=0,
        help_text=_("Version number for changes.")
    )
    deleted_at = models.DateTimeField(
        null=True, blank=True,
        help_text=_("Soft deletion timestamp.")
    )

    def clean(self):
        """Enhanced postal code validation"""
        super().clean()
        if self.postal_code:
            cleaned_pc = self.postal_code.replace(' ', '').replace('-', '')
            if not cleaned_pc.isalnum():
                raise ValidationError(
                    _('Postal code contains invalid characters.'),
                    code='invalid_postal_code'
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['user'],
                condition=models.Q(is_default=True),
                name='unique_default_address'
            )
        ]
        verbose_name = _('address')
        verbose_name_plural = _('addresses')