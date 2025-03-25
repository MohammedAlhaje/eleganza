from django.apps import AppConfig
import contextlib
from django.utils.translation import gettext_lazy as _

class ProductsConfig(AppConfig):

    name = 'eleganza.products'
    verbose_name = _("Products")

    def ready(self):
        with contextlib.suppress(ImportError):
            import eleganza.products.signals  # noqa: F401
