from django.db import models
from django.core.validators import RegexValidator, FileExtensionValidator
from django.db.models import UniqueConstraint
from django.utils.translation import gettext_lazy as _
from eleganza.core.models import BaseModel
from eleganza.products.constants import (
    FieldLimits,
    ValidationPatterns,
    ImageConstants,
)

class ProductCategory(BaseModel):
    """Hierarchical product categorization system"""
    name = models.CharField(
        _("Name"),
        max_length=FieldLimits.CATEGORY_NAME,
        unique=True,
        validators=[
            RegexValidator(
                ValidationPatterns.PRODUCT_NAME,
                _("Category name contains invalid characters")
            )
        ]
    )
    parent = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='children',
        verbose_name=_("Parent Category")
    )
    slug = models.SlugField(
        _("Slug"),
        unique=True,
        max_length=FieldLimits.CATEGORY_NAME
    )
    description = models.TextField(_("Description"), blank=True)
    featured_image = models.ImageField(
        _("Featured Image"),
        upload_to=ImageConstants.UPLOAD_PATHS['CATEGORY'],
        blank=True,
        null=True,
        validators=[
            FileExtensionValidator(ImageConstants.ALLOWED_FORMATS),
        ]
    )
    is_active = models.BooleanField(_("Active"), default=True, db_index=True)

    class Meta:
        verbose_name = _("Product Category")
        verbose_name_plural = _("Product Categories")
        constraints = [
            UniqueConstraint(
                fields=['parent', 'name'],
                name='unique_category_name_per_parent'
            )
        ]

    def __str__(self):
        return self.name
