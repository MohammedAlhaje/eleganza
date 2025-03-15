from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings
from django.utils import timezone
from .models import User  # Import your User model
from django.http import HttpRequest

class AccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request: HttpRequest) -> bool:
        return getattr(settings, "ACCOUNT_ALLOW_REGISTRATION", True)

    def save_user(self, request, user, form, commit=True):
        """
        Saves new user with additional fields from your User model
        """
        user = super().save_user(request, user, form, commit=False)
        
        # Add your custom fields
        user.phone = form.cleaned_data.get('phone')
        user.timezone = form.cleaned_data.get('timezone', 'UTC')
        user.language = form.cleaned_data.get('language', 'en')
        user.default_currency = form.cleaned_data.get('default_currency', 'USD')
        
        if commit:
            user.save()
        return user

    def confirm_email(self, request, email_address):
        """
        Updates email verification fields after confirmation
        """
        super().confirm_email(request, email_address)
        user = email_address.user
        user.is_email_verified = True
        user.email_verified_at = timezone.now()
        user.save()

class SocialAccountAdapter(DefaultSocialAccountAdapter):
    def populate_user(self, request, sociallogin, data):
        """
        Maps social provider data to your User fields
        """
        user = super().populate_user(request, sociallogin, data)
        
        # Map name fields if needed (adjust based on your social providers)
        extra_data = sociallogin.account.extra_data
        
        # Example for Google/Facebook
        user.date_of_birth = extra_data.get('birthdate')
        user.phone = extra_data.get('phone_number')
        
        # Set default values for required fields
        user.timezone = 'UTC'
        user.language = 'en'
        user.default_currency = 'USD'
        
        return user

    def is_open_for_signup(self, request, sociallogin):
        return getattr(settings, "ACCOUNT_ALLOW_REGISTRATION", True)