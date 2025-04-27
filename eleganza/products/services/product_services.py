from django.db import transaction
from django.core.exceptions import ValidationError
from django.db.models import Q
from .models import (
    Product,
    ProductVariant,
    ProductAttribute,
    ProductOption,
    ProductTag
)

# ──────────────────────────────────────────────────
# Attribute Management Services (ProductAttribute)
# ──────────────────────────────────────────────────

@transaction.atomic
def create_attribute(name: str, code: str, is_required: bool) -> ProductAttribute:
    """UC-A01: Create a new attribute with duplicate validation"""
    if ProductAttribute.objects.filter(Q(name=name) | Q(code=code)).exists():
        raise ValidationError("The name or code is already in use")
    
    return ProductAttribute.objects.create(
        name=name,
        code=code,
        is_required=is_required
    )

@transaction.atomic
def update_attribute(attribute_id: int, **kwargs) -> ProductAttribute:
    """UC-A02: Update attribute details"""
    attribute = ProductAttribute.objects.get(id=attribute_id)
    
    if 'code' in kwargs and ProductAttribute.objects.exclude(id=attribute_id).filter(code=kwargs['code']).exists():
        raise ValidationError("The code is already in use")
    
    for field, value in kwargs.items():
        setattr(attribute, field, value)
    attribute.save()
    return attribute

@transaction.atomic
def delete_attribute(attribute_id: int) -> None:
    """UC-A03: Delete an unused attribute"""
    attribute = ProductAttribute.objects.get(id=attribute_id)
    if attribute.options.exists() or attribute.products.exists():
        raise ValidationError("Cannot delete an attribute that is in use")
    attribute.delete()

# ──────────────────────────────────────────────────
# Option Management Services (ProductOption)
# ──────────────────────────────────────────────────

@transaction.atomic
def create_option(attribute_id: int, value: str, sort_order: int = 0) -> ProductOption:
    """UC-O01: Create a new option"""
    attribute = ProductAttribute.objects.get(id=attribute_id)
    if ProductOption.objects.filter(attribute=attribute, value=value).exists():
        raise ValidationError("The value is already in use for this attribute")
    
    return ProductOption.objects.create(
        attribute=attribute,
        value=value,
        sort_order=sort_order
    )

@transaction.atomic
def update_option(option_id: int, **kwargs) -> ProductOption:
    """UC-O02: Update option details"""
    option = ProductOption.objects.get(id=option_id)
    
    if 'value' in kwargs:
        if ProductOption.objects.filter(attribute=option.attribute, value=kwargs['value']).exclude(id=option_id).exists():
            raise ValidationError("The value is already in use for this attribute")
    
    for field, value in kwargs.items():
        setattr(option, field, value)
    option.save()
    return option

@transaction.atomic
def toggle_option_active(option_id: int) -> ProductOption:
    """UC-O03: Toggle the active status of an option"""
    option = ProductOption.objects.get(id=option_id)
    option.is_active = not option.is_active
    option.save()
    return option

# ──────────────────────────────────────────────────
# Product Management Services (Product)
# ──────────────────────────────────────────────────

@transaction.atomic
def create_product(
    name: str,
    slug: str,
    sku: str,
    category_id: int,
    attributes: list[int] = None,
    tags: list[int] = None
) -> Product:
    """UC-P01: Create a new product"""
    if Product.objects.filter(Q(slug=slug) | Q(sku=sku)).exists():
        raise ValidationError("The slug or SKU is already in use")
    
    product = Product.objects.create(
        name=name,
        slug=slug,
        sku=sku,
        category_id=category_id
    )
    
    if attributes:
        product.attributes.set(attributes)
    
    if tags:
        ProductTag.objects.bulk_create([
            ProductTag(product=product, tag_id=tag_id)
            for tag_id in tags
        ])
    
    return product

@transaction.atomic
def update_product(product_id: int, **kwargs) -> Product:
    """UC-P02: Update product details"""
    product = Product.objects.get(id=product_id)
    
    if 'slug' in kwargs and Product.objects.exclude(id=product_id).filter(slug=kwargs['slug']).exists():
        raise ValidationError("The slug is already in use")
    
    if 'sku' in kwargs and Product.objects.exclude(id=product_id).filter(sku=kwargs['sku']).exists():
        raise ValidationError("The SKU is already in use")
    
    for field, value in kwargs.items():
        if field not in ['attributes', 'tags']:
            setattr(product, field, value)
    
    if 'attributes' in kwargs:
        product.attributes.set(kwargs['attributes'])
    
    if 'tags' in kwargs:
        current_tags = product.tags.values_list('id', flat=True)
        new_tags = set(kwargs['tags']) - set(current_tags)
        ProductTag.objects.bulk_create([
            ProductTag(product=product, tag_id=tag_id)
            for tag_id in new_tags
        ])
    
    product.save()
    return product

@transaction.atomic
def archive_product(product_id: int) -> Product:
    """UC-P03: Archive a product"""
    product = Product.objects.get(id=product_id)
    product.status = 'archived'
    product.save()
    product.variants.update(is_active=False)
    return product

# ──────────────────────────────────────────────────
# Variant Management Services (ProductVariant)
# ──────────────────────────────────────────────────

@transaction.atomic
def create_variant(
    product_id: int,
    sku: str,
    options: list[int],
    is_default: bool = False
) -> ProductVariant:
    """UC-V01: Create a new variant"""
    product = Product.objects.get(id=product_id)
    
    if ProductVariant.objects.filter(product=product, sku=sku).exists():
        raise ValidationError("The SKU is already in use for this product")
    
    variant = ProductVariant.objects.create(
        product=product,
        sku=sku,
        is_default=is_default
    )
    variant.options.set(options)
    return variant

@transaction.atomic
def update_variant(variant_id: int, **kwargs) -> ProductVariant:
    """UC-V02: Update variant details"""
    variant = ProductVariant.objects.get(id=variant_id)
    
    if 'sku' in kwargs and ProductVariant.objects.exclude(id=variant_id).filter(sku=kwargs['sku']).exists():
        raise ValidationError("The SKU is already in use")
    
    for field, value in kwargs.items():
        setattr(variant, field, value)
    variant.save()
    return variant

@transaction.atomic
def set_default_variant(variant_id: int) -> None:
    """UC-V03: Set a variant as the default"""
    variant = ProductVariant.objects.get(id=variant_id)
    ProductVariant.objects.filter(product=variant.product).update(is_default=False)
    variant.is_default = True
    variant.save()

@transaction.atomic
def toggle_variant_active(variant_id: int) -> ProductVariant:
    """UC-V04: Toggle the active status of a variant"""
    variant = ProductVariant.objects.get(id=variant_id)
    variant.is_active = not variant.is_active
    variant.save()
    return variant

@transaction.atomic
def delete_variant(variant_id: int) -> None:
    """UC-V05: Delete a variant"""
    variant = ProductVariant.objects.get(id=variant_id)
    variant.delete()
