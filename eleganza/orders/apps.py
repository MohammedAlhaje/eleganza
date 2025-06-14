from django.apps import AppConfig
import contextlib
from django.utils.translation import gettext_lazy as _


class OrdersConfig(AppConfig):
    name = 'eleganza.orders'
    verbose_name = _("Orders")

    def ready(self):
        with contextlib.suppress(ImportError):
            import eleganza.orders.signals  # noqa: F401
