# forms.py
from django import forms
from django.contrib.auth.forms import (
    AuthenticationForm,
)
from django.utils.translation import gettext_lazy as _


class UserRegistrationForm(forms.ModelForm):
    """
    Custom user registration form with password matching validation.
    Handles both customer and team member registration based on user type.
    """


class CustomAuthenticationForm(AuthenticationForm):
    """
    Custom login form with remember me functionality and improved security.
    """


class UserProfileForm(forms.ModelForm):
    """
    Base profile form with common fields for all user types.
    Includes avatar upload handling and phone number validation.
    """




