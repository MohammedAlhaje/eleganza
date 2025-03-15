from django.contrib.auth.models import AbstractUser
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

class User(AbstractUser):
    """
    User model extending Django's built-in AbstractUser.
    Inherits core fields like `username`, `password`, and `is_active`.
    Adds additional fields for enhanced user profile management, security, and preferences.
    """

    # Core identification fields
    email = models.EmailField(unique=True, help_text="Unique email address used for login and communication.")
    phone = PhoneNumberField(unique=True, blank=True, null=True, help_text="User's phone number in international format.")

    # Verification fields (for security and compliance)
    is_email_verified = models.BooleanField(
        default=False,
        help_text="Flag indicating if the user's email address has been verified."
    )
    email_verified_at = models.DateTimeField(
        blank=True, null=True,
        help_text="Timestamp when the user's email was verified."
    )
    is_phone_verified = models.BooleanField(
        default=False,
        help_text="Flag indicating if the user's phone number has been verified."
    )
    phone_verified_at = models.DateTimeField(
        blank=True, null=True,
        help_text="Timestamp when the user's phone number was verified."
    )

    # Consent fields (for GDPR and privacy compliance)
    data_consent = models.BooleanField(
        default=False,
        help_text="Flag indicating if the user has consented to data processing."
    )
    data_consent_at = models.DateTimeField(
        blank=True, null=True,
        help_text="Timestamp when the user gave data processing consent."
    )
    marketing_consent = models.BooleanField(
        default=False,
        help_text="Flag indicating if the user has consented to receive marketing communications."
    )
    marketing_consent_at = models.DateTimeField(
        blank=True, null=True,
        help_text="Timestamp when the user gave marketing consent."
    )

    # User preferences
    timezone = TimeZoneField(
        default='UTC',
        help_text="User's preferred timezone for displaying dates and times."
    )
    language = models.CharField(
        max_length=10, default='en',
        help_text="User's preferred language (ISO 639-1 code)."
    )
    default_currency = CurrencyField(
        default='USD',
        help_text="User's preferred currency for transactions and pricing."
    )

    # Security-related fields
    mfa_enabled = models.BooleanField(
        default=False,
        help_text="Flag indicating if multi-factor authentication (MFA) is enabled for the user."
    )
    mfa_secret = EncryptedCharField(
        max_length=64, blank=True, null=True,
        help_text="Encrypted secret key used for MFA (e.g., TOTP)."
    )
    failed_login_attempts = models.IntegerField(
        default=0,
        help_text="Number of consecutive failed login attempts."
    )
    locked_until = models.DateTimeField(
        blank=True, null=True,
        help_text="Timestamp until which the account is locked due to too many failed login attempts."
    )
    password_updated_at = models.DateTimeField(
        blank=True, null=True,
        help_text="Timestamp of the last password change."
    )

    # Profile fields
    avatar = models.ImageField(
        upload_to=rename_avatar,
        blank=True,
        null=True,
        default="avatars/default.webp",  # Use WebP for default image
        validators=[validate_avatar, get_file_extension_validator()],
        help_text="User's profile picture or avatar. Allowed formats: JPG, JPEG, PNG, WEBP. Max size: 2MB."
    )

    date_of_birth = models.DateField(
        blank=True, null=True,
        help_text="User's date of birth for age verification and personalization."
    )

        # Audit fields (for tracking user activity and changes)
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp when the user account was created."
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="Timestamp when the user account was last updated."
    )
    deleted_at = models.DateTimeField(
        blank=True, null=True,
        help_text="Timestamp for soft deletion of the user account."
    )

    # Versioning and concurrency control
    version = models.IntegerField(
        default=0,
        editable=False,
        help_text="Version number for tracking changes and handling concurrency."
    )


    def clean(self):
        """
        Custom validation logic for the model.
        Ensures that the date of birth is in the past.
        """
        super().clean()

        if self.date_of_birth:
            age = date.today().year - self.date_of_birth.year
            if age < 13:
                raise ValidationError("Users must be at least 13 years old.")
  
        if self.date_of_birth and self.date_of_birth >= timezone.now().date():
            raise ValidationError({'date_of_birth': 'Date of birth must be in the past.'})

    def save(self, *args, **kwargs):
        """
        Overrides the save method to ensure validation is run before saving.
        """
        self.full_clean()  # Runs model validation before saving
        super().save(*args, **kwargs)


    class Meta:
        indexes = [
            models.Index(fields=['email']),
            models.Index(fields=['phone']),
            models.Index(fields=['is_active', 'deleted_at']),
        ]


class PasswordHistory(models.Model):
    """
    Stores historical password hashes for a user.
    Used to enforce password reuse policies and enhance security.
    """

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='password_history',
        help_text="User associated with this password history entry."
    )
    password_hash = models.CharField(
        max_length=255,
        help_text="Hashed representation of the user's password."
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp when this password was set."
    )

    class Meta:
        unique_together = ('user', 'password_hash')  # Prevents duplicate password hashes for the same user.
        ordering = ['-created_at']  # Orders entries by creation date (newest first).


class Address(models.Model):
    """
    Represents a physical address associated with a user.
    Used for shipping, billing, and other location-based purposes.
    """

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='addresses',
        help_text="User associated with this address."
    )
    street = models.CharField(
        max_length=255,
        help_text="Street name and number."
    )
    city = models.CharField(
        max_length=100,
        help_text="City or locality name."
    )
    state = models.CharField(
        max_length=100,
        help_text="State, province, or region."
    )
    postal_code = models.CharField(
        max_length=20,
        help_text="Postal or ZIP code for the address."
    )
    country = CountryField(
        help_text="Country where the address is located."
    )
    is_default = models.BooleanField(
        default=False,
        help_text="Flag indicating if this is the user's default address."
    )
    version = models.IntegerField(
        default=0,
        help_text="Version number for tracking changes to the address."
    )
    deleted_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Timestamp for soft deletion of the address."
    )

    def clean(self):
        """
        Custom validation logic for the model.
        Ensures that the postal code is alphanumeric.
        """
        # In Address.clean()

        super().clean()
        if self.postal_code and not self.postal_code.replace(' ', '').isalnum():
            raise ValidationError('Postal code can only contain letters/numbers.')

    def save(self, *args, **kwargs):
        """
        Overrides the save method to ensure validation is run before saving.
        """
        self.full_clean()  # Runs model validation before saving
        super().save(*args, **kwargs)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['user'],
                condition=models.Q(is_default=True),
                name='unique_default_address'
            )
        ]