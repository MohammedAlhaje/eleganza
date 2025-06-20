import contextlib

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _

class PaymentsConfig(AppConfig):
    name = 'eleganza.payments'
    verbose_name = _("Payments")
    
    def ready(self):
        with contextlib.suppress(ImportError):
            import eleganza.payments.signals  # noqa: F401

