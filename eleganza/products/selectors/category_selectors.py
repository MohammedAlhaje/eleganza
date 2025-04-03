from django.db.models import Prefetch, Count, Q
from typing import List, Dict, Optional
from django.core.exceptions import ValidationError
from django.core.cache import cache
from ..models import ProductCategory, Product
from ..constants import FieldLengths

def validate_category_depth(depth: Optional[int]) -> None:
    """Validate depth parameter for category queries"""
    if depth is not None and (depth < 1 or depth > 10):
        raise ValidationError("Depth must be between 1 and 10")

def get_category_tree(
    *,
    depth: Optional[int] = None,
    include_products: bool = False,
    only_active_products: bool = True,
    limit: Optional[int] = None,
    fields: Optional[List[str]] = None
) -> List[ProductCategory]:
    """
    Get hierarchical category structure with optional product inclusion
    
    Args:
        depth: Maximum depth to retrieve (None for all levels, max 10)
        include_products: Whether to prefetch products
        only_active_products: Filter inactive products
        limit: Maximum number of root categories to return
        fields: Specific product fields to include (None for all)
        
    Returns:
        List of root categories with children relationships
        
    Raises:
        ValidationError: For invalid depth parameter
    """
    validate_category_depth(depth)
    
    # Base queryset for root categories
    queryset = ProductCategory.objects.filter(parent__isnull=True)
    
    # Apply depth filtering
    if depth is not None:
        queryset = queryset.filter(level__lt=depth)
    
    # Product prefetch configuration
    if include_products:
        product_qs = Product.objects.filter(is_active=True)
        if only_active_products:
            product_qs = product_qs.filter(is_active=True)
        if fields:
            product_qs = product_qs.only(*fields)
            
        queryset = queryset.prefetch_related(
            Prefetch('products', queryset=product_qs)
        )
    
    # Children prefetch with annotation
    children_qs = ProductCategory.objects.all().annotate(
        product_count=Count('products', filter=Q(products__is_active=True))
    )
    
    if fields:
        children_qs = children_qs.only('id', 'name', 'slug', 'level', 'parent')
    
    queryset = queryset.prefetch_related(
        Prefetch('children', queryset=children_qs)
    )
    
    # Apply limit if specified
    if limit:
        queryset = queryset[:limit]
    
    return list(queryset)

def get_category_with_children(
    category_id: int,
    *,
    include_products: bool = False,
    product_fields: Optional[List[str]] = None
) -> Optional[ProductCategory]:
    """
    Get single category with its immediate children
    
    Args:
        category_id: ID of the parent category
        include_products: Whether to include products
        product_fields: Specific product fields to include
        
    Returns:
        Category instance with prefetched children or None
    """
    if category_id <= 0:
        raise ValidationError("Category ID must be positive")
    
    queryset = ProductCategory.objects.filter(pk=category_id)
    
    if include_products:
        product_qs = Product.objects.filter(is_active=True)
        if product_fields:
            product_qs = product_qs.only(*product_fields)
        queryset = queryset.prefetch_related(
            Prefetch('products', queryset=product_qs)
        )
    
    return queryset.prefetch_related(
        Prefetch('children',
               queryset=ProductCategory.objects.annotate(
                   product_count=Count('products', filter=Q(products__is_active=True))
               ).only('id', 'name', 'slug', 'product_count'))
    ).first()

@cache(60 * 15)  # Cache for 15 minutes
def get_category_products_map() -> Dict[str, List[int]]:
    """
    Get mapping of category slugs to active product IDs
    
    Returns:
        Dictionary {category_slug: [product_id1, product_id2]}
    """
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT c.slug, array_agg(p.id)
            FROM products_productcategory c
            JOIN products_product p ON p.category_id = c.id
            WHERE p.is_active = TRUE
            GROUP BY c.slug
        """)
        return {slug: ids for slug, ids in cursor.fetchall()}

def get_featured_categories(
    limit: int = 5,
    *,
    min_products: int = 1,
    only_active: bool = True
) -> List[ProductCategory]:
    """
    Get categories with the most active products
    
    Args:
        limit: Number of categories to return
        min_products: Minimum active products to include
        only_active: Only include active categories
        
    Returns:
        List of categories ordered by product count
    """
    queryset = ProductCategory.objects.annotate(
        active_products=Count('products', filter=Q(products__is_active=True))
    )
    
    if only_active:
        queryset = queryset.filter(is_active=True)
    
    return list(queryset.filter(
        active_products__gte=min_products
    ).order_by(
        '-active_products'
    ).only('id', 'name', 'slug', 'active_products')[:limit])

def get_category_path(slug: str) -> List[ProductCategory]:
    """
    Get breadcrumb path for a category
    
    Args:
        slug: Category slug
        
    Returns:
        Ordered list from root to target category
        
    Raises:
        ValidationError: If slug is empty
    """
    if not slug:
        raise ValidationError("Slug cannot be empty")
    
    category = ProductCategory.objects.filter(slug=slug).first()
    if not category:
        return []
    
    return list(category.get_ancestors(include_self=True).only('id', 'name', 'slug'))

def get_category_products(
    category_id: int,
    *,
    only_featured: bool = False,
    only_active: bool = True,
    fields: Optional[List[str]] = None
) -> List[Product]:
    """
    Get products for a category with optional filtering
    
    Args:
        category_id: ID of the category
        only_featured: Only include featured products
        only_active: Only include active products
        fields: Specific fields to return (None for all)
        
    Returns:
        List of Product instances
        
    Raises:
        ValidationError: For invalid category ID
    """
    if category_id <= 0:
        raise ValidationError("Category ID must be positive")
    
    queryset = Product.objects.filter(category_id=category_id)
    
    if only_active:
        queryset = queryset.filter(is_active=True)
    if only_featured:
        queryset = queryset.filter(is_featured=True)
    if fields:
        queryset = queryset.only(*fields)
    
    return list(queryset.order_by('-is_featured', 'name'))

def get_category_by_slug(
    slug: str,
    *,
    include_products: bool = False,
    product_fields: Optional[List[str]] = None
) -> Optional[ProductCategory]:
    """
    Get category by slug with product count
    
    Args:
        slug: Category slug
        include_products: Whether to include products
        product_fields: Specific product fields to include
        
    Returns:
        Category instance or None
        
    Raises:
        ValidationError: If slug is empty
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
        product_count=Count('products', filter=Q(products__is_active=True))
    ).only('id', 'name', 'slug', 'product_count').first()