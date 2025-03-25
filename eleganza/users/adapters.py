from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.account.adapter import DefaultAccountAdapter
from allauth.exceptions import ImmediateHttpResponse
from allauth.account.models import EmailAddress  # Import Allauth's EmailAddress model
from django.core.files.base import ContentFile
from django.shortcuts import redirect
from urllib.request import urlopen
from .models import User
import uuid
import logging
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


class AccountAdapter(DefaultAccountAdapter):
    def populate_username(self, request, user):
        # Bypass default username generation since we're using email as the main identifier
        pass


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    """Custom social account adapter handling Google and future providers"""

    def pre_social_login(self, request, sociallogin):
        """
        Handle existing email associations and account merging.
        If a user with the same email already exists, connect the social account to it.
        """
        email = sociallogin.account.extra_data.get('email')
        if email:
            try:
                # Check if an email address already exists in Allauth's EmailAddress table
                email_address = EmailAddress.objects.get(email=email)
                # Connect the social account to the existing user
                sociallogin.connect(request, email_address.user)
                # Log the user in
                from allauth.account.utils import perform_login
                perform_login(request, email_address.user, email_verification='optional')
                # Redirect to the login redirect URL
                raise ImmediateHttpResponse(redirect(settings.LOGIN_REDIRECT_URL))
            except EmailAddress.DoesNotExist:
                # If no email exists, let allauth create a new user
                pass

    def populate_user(self, request, sociallogin, data):
        """
        Populate user model with data from social providers.
        Handles Google OAuth2 and can be extended for other providers.
        """
        user = super().populate_user(request, sociallogin, data)
        extra_data = sociallogin.account.extra_data
        provider = sociallogin.account.provider

        # Common fields across providers
        user.display_name = extra_data.get('name', '')

        # Provider-specific field mapping
        provider_handler = getattr(self, f'_handle_{provider}_data', None)
        if provider_handler:
            provider_handler(user, extra_data)
        else:
            logger.warning(f"No specific handler for provider: {provider}")

        # Generate a unique username if not provided
        if not user.username:
            user.username = self._generate_unique_username(extra_data.get('email', ''))

        return user

    def save_user(self, request, sociallogin, form=None):
        """
        Custom user save handler with additional fields and validation.
        """
        user = super().save_user(request, sociallogin, form)
        extra_data = sociallogin.account.extra_data
        provider = sociallogin.account.provider

        # Common social data processing
        user.data_consent = True
        user.data_consent_at = timezone.now()

        # Handle avatar from social providers
        avatar_url = self._get_avatar_url(provider, extra_data)
        if avatar_url:
            self._update_avatar(user, avatar_url)

        # Save the user first to ensure they have a primary key
        user.save()

        # Add the email to Allauth's EmailAddress table
        email = extra_data.get('email')
        if email:
            EmailAddress.objects.create(
                user=user,
                email=email,
                verified=True,  # Assume verified since it's from a social provider
                primary=True
            )

        return user

    def _handle_google_data(self, user, extra_data):
        """Google-specific data handling"""
        user.first_name = extra_data.get('given_name', '')
        user.last_name = extra_data.get('family_name', '')
        user.is_phone_verified = False  # Google doesn't provide phone verification

        # Store Google-specific data in JSON field if needed
        user.social_metadata = {
            'google': {
                'id': extra_data.get('id'),
                'locale': extra_data.get('locale'),
                'hd': extra_data.get('hd'),
            }
        }

    def _generate_unique_username(self, email):
        """
        Generate a unique username from the email or a random string.
        """
        if email:
            base_username = email.split('@')[0]
            username = base_username
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{base_username}_{counter}"
                counter += 1
            return username
        return str(uuid.uuid4().hex[:30])

    def _get_avatar_url(self, provider, extra_data):
        """Get avatar URL based on provider"""
        provider_handlers = {
            'google': lambda d: d.get('picture'),
            # Add other providers here
            # 'facebook': lambda d: d.get('picture', {}).get('data', {}).get('url'),
            # 'github': lambda d: d.get('avatar_url'),
        }
        return provider_handlers.get(provider, lambda d: None)(extra_data)

    def _update_avatar(self, user, url):
        """
        Download and update user avatar from URL.
        """
        try:
            response = urlopen(url)
            if response.status == 200:
                user.avatar.save(
                    f"social_{user.id}.jpg",
                    ContentFile(response.read()),
                    save=False
                )
        except Exception as e:
            logger.error(f"Failed to download avatar from {url}: {str(e)}")

    def is_open_for_signup(self, request, sociallogin):
        """
        Enable social signup even if regular signup is closed.
        """
        return True