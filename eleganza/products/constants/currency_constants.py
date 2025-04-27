from django.utils.translation import gettext_lazy as _

class CurrencyConstants:
    """Currency configurations"""
    
    CHOICES = [('LYD', _('Libyan Dinar'))]  # Supported currencies
    DEFAULT = "LYD"                        # Default currency
