from django.db.models import Prefetch, QuerySet
from .models import ProductCategory, Product

def get_all_categories(active_only: bool = True) -> QuerySet:
    """UC-PC05: Retrieve all categories"""
    queryset = ProductCategory.objects.all()
    if active_only:
        queryset = queryset.filter(is_active=True)
    return queryset.order_by('name')

def get_category_tree() -> QuerySet:
    """Retrieve categories in a tree structure"""
    return ProductCategory.objects.filter(parent__isnull=True).prefetch_related(
        Prefetch('children', queryset=ProductCategory.objects.filter(is_active=True))
    )

def get_products_in_category(category_id: int) -> QuerySet:
    """UC-PC06: Retrieve products associated with a category"""
    return Product.objects.filter(
        category_id=category_id,
        is_active=True
    ).select_related('category')