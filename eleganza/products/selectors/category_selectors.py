# eleganza/products/selectors/category_selectors.py
from django.db.models import Prefetch, Count, Q
from typing import List, Dict, Optional, Iterable
from collections import defaultdict
from django.views.decorators.cache import cache_page
from django.db.models import Value, F
from django.db.models.functions import Coalesce
from eleganza.products.models import ProductCategory, Product
from eleganza.products.constants import FieldLengths
from eleganza.products.validators import validate_id, validate_category_depth

# Reusable annotation for active product count
ACTIVE_PRODUCTS_COUNT = Count(
    'products', 
    filter=Q(products__is_active=True)
)

def get_category_tree_with_stats() -> Iterable[ProductCategory]:
    """
    Get full category tree with annotated product counts.
    Uses Coalesce to handle null values safely.
    """
    return ProductCategory.objects.annotate(
        product_count=Coalesce(ACTIVE_PRODUCTS_COUNT, Value(0))
    ).order_by('tree_id', 'lft')

def get_category_tree(
    *,
    depth: Optional[int] = None,
    include_products: bool = False,
    only_active_products: bool = True,
    limit: Optional[int] = None,
    offset: int = 0,  # Added pagination support
    fields: Optional[List[str]] = None
) -> List[ProductCategory]:
    """
    Get hierarchical category structure with optional product inclusion.
    
    Args:
        depth: Maximum depth to retrieve (None for all levels, max 10)
        include_products: Whether to prefetch products
        only_active_products: Filter inactive products
        limit: Maximum number of root categories to return
        offset: Pagination offset
        fields: Specific product fields to include (None for all)
    """
    validate_category_depth(depth)
    
    queryset = ProductCategory.objects.filter(parent__isnull=True)
    
    if depth is not None:
        queryset = queryset.filter(level__lt=depth)
    
    if include_products:
        product_qs = Product.objects.filter(is_active=True)
        if only_active_products:
            product_qs = product_qs.filter(is_active=True)
        if fields:
            product_qs = product_qs.only(*fields)
            
        queryset = queryset.prefetch_related(
            Prefetch('products', queryset=product_qs))
    
    children_qs = ProductCategory.objects.all().annotate(
        product_count=Coalesce(ACTIVE_PRODUCTS_COUNT, Value(0))  # Safe null handling
    )
    
    if fields:
        children_qs = children_qs.only('id', 'name', 'slug', 'level', 'parent')
    
    queryset = queryset.prefetch_related(
        Prefetch('children', queryset=children_qs)
    )
    
    # Pagination support
    if limit:
        queryset = queryset[offset:offset + limit]
    
    return list(queryset)

@cache_page(60 * 15, key_prefix="category_products_map")  # Unique cache key
def get_category_products_map() -> Dict[str, List[int]]:
    """
    Get mapping of category slugs to active product IDs.
    Uses Coalesce to ensure valid values.
    """
    products = Product.objects.filter(
        is_active=True
    ).annotate(
        category_slug=Coalesce(F('category__slug'), Value('uncategorized'))
    ).values_list('category_slug', 'id')
    
    result = defaultdict(list)
    for slug, prod_id in products:
        result[slug].append(prod_id)
    return dict(result)

def get_featured_categories(
    limit: int = 5,
    *,
    min_products: int = 1,
    only_active: bool = True,
    offset: int = 0  # Added pagination
) -> List[ProductCategory]:
    """
    Get categories with the most active products.
    Uses reusable ACTIVE_PRODUCTS_COUNT annotation.
    """
    queryset = ProductCategory.objects.annotate(
        active_products=ACTIVE_PRODUCTS_COUNT
    )
    
    if only_active:
        queryset = queryset.filter(is_active=True)
    
    return list(queryset.filter(
        active_products__gte=min_products
    ).order_by(
        '-active_products'
    ).only('id', 'name', 'slug', 'active_products')[offset:offset + limit])  # Pagination

def get_category_path(slug: str) -> List[ProductCategory]:
    """
    Get breadcrumb path for a category.
    Uses centralized slug validation.
    """
    if not slug:
        raise ValidationError("Slug cannot be empty")
    
    category = ProductCategory.objects.filter(slug=slug).first()
    if not category:
        return []
    
    return list(
        category.get_ancestors(include_self=True)
        .only('id', 'name', 'slug')
        .annotate(product_count=ACTIVE_PRODUCTS_COUNT)  # Reused annotation
    )

def get_category_products(
    category_id: int,
    *,
    only_featured: bool = False,
    only_active: bool = True,
    fields: Optional[List[str]] = None,
    limit: Optional[int] = None,
    offset: int = 0  # Added pagination
) -> List[Product]:
    """
    Get products for a category with optional filtering.
    Uses centralized ID validation.
    """
    validate_id(category_id, "Category ID")
    
    queryset = Product.objects.filter(category_id=category_id)
    
    if only_active:
        queryset = queryset.filter(is_active=True)
    if only_featured:
        queryset = queryset.filter(is_featured=True)
    if fields:
        queryset = queryset.only(*fields)
    
    # Pagination support
    if limit:
        queryset = queryset[offset:offset + limit]
    
    return list(queryset.order_by('-is_featured', 'name'))

def get_category_by_slug(
    slug: str,
    *,
    include_products: bool = False,
    product_fields: Optional[List[str]] = None
) -> Optional[ProductCategory]:
    """
    Get category by slug with product count.
    Uses Coalesce for safe null handling.
    """
    if not slug:
        raise ValidationError("Slug cannot be empty")
    
    queryset = ProductCategory.objects.filter(slug=slug)
    
    if include_products:
        product_qs = Product.objects.filter(is_active=True)
        if product_fields:
            product_qs = product_qs.only(*product_fields)
        queryset = queryset.prefetch_related(
            Prefetch('products', queryset=product_qs)
        )
    
    return queryset.annotate(
        product_count=Coalesce(ACTIVE_PRODUCTS_COUNT, Value(0))  # Safe default
    ).only('id', 'name', 'slug', 'product_count').first()