from django.db.models import Prefetch, Q, QuerySet
from .models import (
    Product,
    ProductVariant,
    ProductAttribute,
    ProductOption
)

def get_product_with_relations(slug: str) -> Product:
    """UC-P04: Retrieve a product with all its relations"""
    return Product.objects.filter(
        Q(status='active') | Q(status='archived'),
        slug=slug
    ).prefetch_related(
        Prefetch('variants', queryset=ProductVariant.objects.filter(is_active=True)),
        'attributes__options',
        'tags'
    ).first()

def search_products(keyword: str) -> QuerySet:
    """UC-P05: Search for products"""
    return Product.objects.filter(
        Q(name__icontains=keyword) |
        Q(description__icontains=keyword) |
        Q(sku__icontains=keyword),
        status='active'
    ).select_related('category')

def get_products_by_category(category_slug: str) -> QuerySet:
    """UC-P06: Retrieve products by category"""
    return Product.objects.filter(
        category__slug=category_slug,
        status='active'
    ).prefetch_related('media_files')

def get_active_attributes() -> QuerySet:
    """Retrieve active attributes with their options"""
    return ProductAttribute.objects.filter(
        is_active=True
    ).prefetch_related(
        Prefetch('options', queryset=ProductOption.objects.filter(is_active=True))
    )

def get_product_variants(product_id: int) -> QuerySet:
    """Retrieve active product variants"""
    return ProductVariant.objects.filter(
        product_id=product_id,
        is_active=True
    ).order_by('-is_default')
