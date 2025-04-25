# products/services/products.py
import logging
from decimal import Decimal
from typing import Optional, Dict, List
from django.db import transaction
from django.core.exceptions import ValidationError
from ..models import Product, ProductCategory
from ..exceptions import (
    ProductNotFoundError,
    InvalidProductDataError,
    ProductCreationError
)
from .variants import VariantService
from .inventory import InventoryService
from .tags import TagService
from .pricing import PricingService
from ..constants import (
    FieldLengths,
    Defaults,
    RegexPatterns,
    DiscountTypes
)

logger = logging.getLogger(__name__)

class ProductService:
    """
    Service handling core product lifecycle operations including creation,
    updates, soft deletion, and business rule enforcement.
    """

    @classmethod
    @transaction.atomic
    def create_product(cls, product_data: Dict, tags: Optional[List[str]] = None) -> Product:
        """
        Creates a new product with validated data and associated resources.
        
        Args:
            product_data: Validated product attributes
            tags: Optional list of tags to associate
            
        Returns:
            Product: Created product instance
            
        Raises:
            InvalidProductDataError: For validation failures
            ProductCreationError: For critical creation errors
        """
        try:
            cls._validate_product_data(product_data)
            normalized_data = cls._normalize_product_data(product_data)
            
            # Core product creation
            product = Product.objects.create(**normalized_data)
            
            # Create associated resources
            variant = VariantService.create_default_variant(product)
            InventoryService.create_inventory(variant)
            
            if tags:
                TagService.assign_tags_to_product(product, tags)

            logger.info("Product created successfully", 
                      extra={"sku": product.sku, "category": product.category_id})
            return product

        except ValidationError as e:
            error_list = cls._format_validation_errors(e)
            logger.error("Product validation failed", exc_info=True)
            raise InvalidProductDataError("Validation failed", errors=error_list) from e
            
        except Exception as e:
            logger.error("Product creation failed", exc_info=True)
            raise ProductCreationError(f"System error: {str(e)}") from e

    @classmethod
    @transaction.atomic
    def update_product(cls, product_id: str, update_data: Dict) -> Product:
        """
        Updates product with validated partial data.
        
        Args:
            product_id: UUID of product to update
            update_data: Dictionary of fields to update
            
        Returns:
            Product: Updated product instance
            
        Raises:
            ProductNotFoundError: For invalid product ID
            InvalidProductDataError: For validation failures
        """
        try:
            product = Product.objects.get(id=product_id)
            changes = cls._prepare_update_data(product, update_data)
            
            if changes:
                for field, value in changes.items():
                    setattr(product, field, value)
                product.full_clean()
                product.save()
                logger.info("Product updated", 
                          extra={"product_id": product_id, "fields": list(changes.keys())})
            
            return product
            
        except Product.DoesNotExist as e:
            logger.error("Product not found", extra={"product_id": product_id})
            raise ProductNotFoundError(product_id) from e
            
        except ValidationError as e:
            error_list = cls._format_validation_errors(e)
            logger.error("Update validation failed", exc_info=True)
            raise InvalidProductDataError("Validation failed", errors=error_list) from e

    @classmethod
    @transaction.atomic
    def delete_product(cls, product_id: str, reason: str = "Manual deletion") -> bool:
        """
        Performs soft deletion with audit trail.
        
        Args:
            product_id: UUID of product to delete
            reason: Deletion reason for auditing
            
        Returns:
            bool: True if successful
            
        Raises:
            ProductNotFoundError: For invalid product ID
        """
        try:
            product = Product.objects.get(id=product_id)
            product.is_active = False
            product.deletion_reason = reason
            product.save(update_fields=['is_active', 'deletion_reason'])
            
            VariantService.deactivate_all_variants(product)
            
            logger.info("Product soft-deleted", 
                      extra={"product_id": product_id, "reason": reason})
            return True
            
        except Product.DoesNotExist as e:
            logger.error("Delete failed - product not found", 
                       extra={"product_id": product_id})
            raise ProductNotFoundError(product_id) from e

    @classmethod
    def calculate_final_price(cls, product: Product) -> Decimal:
        """Calculates final price after applying discounts"""
        return PricingService.calculate_final_price(product)

    # region Validation & Normalization

    @classmethod
    def _validate_product_data(cls, data: Dict, partial: bool = False) -> None:
        """Validates product data against business rules"""
        errors = {}
        
        # Required fields check
        if not partial:
            for field in ['name', 'sku', 'base_price', 'category_id']:
                if field not in data:
                    errors[field] = "This field is required"

        # Category existence check
        if 'category_id' in data:
            try:
                ProductCategory.objects.get(id=data['category_id'], is_active=True)
            except ProductCategory.DoesNotExist:
                errors['category_id'] = "Invalid or inactive category"

        # Field-level validation
        field_rules = {
            'name': {
                'max_length': FieldLengths.PRODUCT_NAME,
                'regex': RegexPatterns.PRODUCT_NAME
            },
            'sku': {
                'max_length': FieldLengths.SKU,
                'regex': RegexPatterns.SKU
            },
            'base_price': {
                'min': Defaults.DEFAULT_MIN_PRICE,
                'max': Defaults.MAX_PRICE
            }
        }

        for field, rules in field_rules.items():
            if field in data:
                value = data[field]
                if 'max_length' in rules and len(str(value)) > rules['max_length']:
                    errors[field] = f"Exceeds maximum length of {rules['max_length']}"
                if 'regex' in rules and not rules['regex'].match(str(value)):
                    errors[field] = "Contains invalid characters"
                if 'min' in rules and value < rules['min']:
                    errors[field] = f"Minimum value: {rules['min']}"
                if 'max' in rules and value > rules['max']:
                    errors[field] = f"Maximum value: {rules['max']}"

        if errors:
            raise ValidationError(errors)

    @classmethod
    def _normalize_product_data(cls, data: Dict) -> Dict:
        """Ensures consistent data format for product creation"""
        return {
            **data,
            'description': data.get('description', ''),
            'discount_type': data.get('discount_type', DiscountTypes.NONE),
            'discount_amount': data.get('discount_amount', Decimal(0)),
            'discount_percent': data.get('discount_percent', Decimal(0))
        }

    @classmethod
    def _format_validation_errors(cls, exc: ValidationError) -> List[str]:
        """Converts Django validation errors to standardized format"""
        return [f"{field}: {', '.join(errs)}" for field, errs in exc.message_dict.items()]

    @classmethod
    def _prepare_update_data(cls, product: Product, update_data: Dict) -> Dict:
        """Identifies and validates changed fields for updates"""
        cls._validate_product_data(update_data, partial=True)
        return {k: v for k, v in update_data.items() if getattr(product, k, None) != v}

    # endregion