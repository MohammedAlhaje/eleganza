# products/services/variants.py
import logging
from typing import Dict, Optional, List
from uuid import UUID
from django.db import transaction
from django.core.exceptions import ValidationError
from ..models import ProductVariant, ProductOption, Product
from ..exceptions import (
    VariantNotFoundError,
    InvalidVariantDataError,
    VariantCreationError
)
from ..constants import (
    FieldLengths,
    RegexPatterns,
    Defaults
)

logger = logging.getLogger(__name__)

class VariantService:
    """
    Service handling product variant operations including creation, updates,
    option management, and inventory coordination.
    """

    @classmethod
    @transaction.atomic
    def create_variant(cls, product_id: UUID, variant_data: Dict) -> ProductVariant:
        """
        Creates a new product variant with validated data.
        
        Args:
            product_id: Parent product UUID
            variant_data: Validated variant attributes
            
        Returns:
            ProductVariant: Created variant instance
            
        Raises:
            InvalidVariantDataError: For validation failures
            VariantCreationError: For critical creation errors
        """
        try:
            product = Product.objects.get(id=product_id)
            cls._validate_variant_data(product, variant_data)
            
            variant = ProductVariant.objects.create(
                product=product,
                **cls._normalize_variant_data(variant_data)
            )
            
            if 'options' in variant_data:
                cls._process_variant_options(variant, variant_data['options'])
            
            logger.info("Variant created successfully",
                      extra={"sku": variant.sku, "product_id": product_id})
            return variant

        except Product.DoesNotExist as e:
            logger.error("Parent product not found", extra={"product_id": product_id})
            raise VariantNotFoundError(f"Parent product {product_id} not found") from e
            
        except ValidationError as e:
            error_list = cls._format_validation_errors(e)
            logger.error("Variant validation failed", exc_info=True)
            raise InvalidVariantDataError("Validation failed", errors=error_list) from e
            
        except Exception as e:
            logger.error("Variant creation failed", exc_info=True)
            raise VariantCreationError(f"System error: {str(e)}") from e

    @classmethod
    @transaction.atomic
    def update_variant(cls, variant_id: UUID, update_data: Dict) -> ProductVariant:
        """
        Updates existing variant with validated partial data.
        
        Args:
            variant_id: UUID of variant to update
            update_data: Dictionary of fields to update
            
        Returns:
            ProductVariant: Updated variant instance
            
        Raises:
            VariantNotFoundError: For invalid variant ID
            InvalidVariantDataError: For validation failures
        """
        try:
            variant = ProductVariant.objects.get(id=variant_id)
            changes = cls._prepare_update_data(variant, update_data)
            
            if changes:
                for field, value in changes.items():
                    setattr(variant, field, value)
                variant.full_clean()
                variant.save()
                logger.info("Variant updated", 
                          extra={"variant_id": variant_id, "fields": list(changes.keys())})
            
            return variant
            
        except ProductVariant.DoesNotExist as e:
            logger.error("Variant not found", extra={"variant_id": variant_id})
            raise VariantNotFoundError(variant_id) from e
            
        except ValidationError as e:
            error_list = cls._format_validation_errors(e)
            logger.error("Update validation failed", exc_info=True)
            raise InvalidVariantDataError("Validation failed", errors=error_list) from e

    @classmethod
    @transaction.atomic
    def deactivate_variant(cls, variant_id: UUID) -> bool:
        """
        Soft-deactivates a variant and related inventory.
        
        Args:
            variant_id: UUID of variant to deactivate
            
        Returns:
            bool: True if successful
            
        Raises:
            VariantNotFoundError: For invalid variant ID
        """
        try:
            variant = ProductVariant.objects.get(id=variant_id)
            variant.is_active = False
            variant.save(update_fields=['is_active'])
            
            logger.info("Variant deactivated", 
                      extra={"variant_id": variant_id, "sku": variant.sku})
            return True
            
        except ProductVariant.DoesNotExist as e:
            logger.error("Deactivation failed - variant not found", 
                       extra={"variant_id": variant_id})
            raise VariantNotFoundError(variant_id) from e

    # region Core Operations
    
    @classmethod
    @transaction.atomic
    def create_default_variant(cls, product: Product) -> ProductVariant:
        """Creates default variant for new products"""
        try:
            variant_data = {
                'sku': f"{product.sku}-DEFAULT",
                'is_default': True,
                'price_modifier': 0
            }
            return cls.create_variant(product.id, variant_data)
            
        except Exception as e:
            logger.error("Default variant creation failed", exc_info=True)
            raise VariantCreationError(f"Default variant failed: {str(e)}") from e

    @classmethod
    def deactivate_all_variants(cls, product: Product) -> int:
        """Soft-deletes all variants for a product"""
        return ProductVariant.objects.filter(product=product).update(is_active=False)

    # endregion

    # region Validation & Data Processing

    @classmethod
    def _validate_variant_data(cls, product: Product, data: Dict) -> None:
        """Validates variant data against business rules"""
        errors = {}
        
        # SKU validation
        if 'sku' in data:
            if not RegexPatterns.SKU.match(data['sku']):
                errors['sku'] = "Invalid SKU format"
            if ProductVariant.objects.filter(product=product, sku=data['sku']).exists():
                errors['sku'] = "SKU must be unique per product"

        # Price modifier validation
        if 'price_modifier' in data:
            pm = data['price_modifier']
            if abs(pm.amount) > Defaults.MAX_PRICE:
                errors['price_modifier'] = f"Modifier exceeds ±{Defaults.MAX_PRICE}"

        if errors:
            raise ValidationError(errors)

    @classmethod
    def _normalize_variant_data(cls, data: Dict) -> Dict:
        """Ensures consistent data format for variant creation"""
        return {
            **data,
            'is_default': data.get('is_default', False),
            'price_modifier': data.get('price_modifier', 0),
            'is_active': data.get('is_active', True)
        }

    @classmethod
    def _format_validation_errors(cls, exc: ValidationError) -> List[str]:
        """Converts Django validation errors to client-friendly format"""
        return [f"{field}: {', '.join(errs)}" for field, errs in exc.message_dict.items()]

    @classmethod
    def _prepare_update_data(cls, variant: ProductVariant, update_data: Dict) -> Dict:
        """Identifies and validates changed fields for updates"""
        cls._validate_variant_data(variant.product, update_data)
        return {k: v for k, v in update_data.items() if getattr(variant, k, None) != v}

    @classmethod
    @transaction.atomic
    def _process_variant_options(cls, variant: ProductVariant, option_ids: List[UUID]) -> None:
        """Validates and sets variant options"""
        valid_options = ProductOption.objects.filter(
            id__in=option_ids,
            attribute__in=variant.product.attributes.all()
        )
        
        if len(valid_options) != len(option_ids):
            logger.error("Invalid options provided", 
                       extra={"variant_id": variant.id, "option_ids": option_ids})
            raise InvalidVariantDataError("One or more invalid options provided")
        
        variant.options.set(valid_options)
        logger.info("Options updated for variant",
                  extra={"variant_id": variant.id, "option_count": len(valid_options)})

    # endregion