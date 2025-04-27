from django.db.models import Q, QuerySet
from .models import ProductImage

def get_product_images(product_id: int) -> QuerySet:
    """UC-M05: Retrieve images for a product"""
    return ProductImage.objects.filter(
        product_id=product_id
    ).order_by('-is_primary', 'sort_order')

def get_variant_images(variant_id: int) -> QuerySet:
    """UC-M06: Retrieve images for a variant"""
    return ProductImage.objects.filter(
        variant_id=variant_id
    ).order_by('-is_primary', 'sort_order')

def get_primary_image(target_id: int, is_variant: bool = False) -> ProductImage:
    """UC-M07: Retrieve the primary image"""
    filter_kwargs = {'variant_id' if is_variant else 'product_id': target_id}
    return ProductImage.objects.filter(
        **filter_kwargs,
        is_primary=True
    ).first()