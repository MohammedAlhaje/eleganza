from django.db.models import Prefetch, Count, Q
from typing import List, Dict, Optional
from ..models import ProductCategory, Product
from ..constants import FieldLengths

def get_category_tree(*, depth: Optional[int] = None, include_products: bool = False) -> List[ProductCategory]:
    """
    Get hierarchical category structure with optional product inclusion
    
    Args:
        depth: Maximum depth to retrieve (None for all levels)
        include_products: Whether to prefetch active products
        
    Returns:
        List of root categories with children relationships
    """
    queryset = ProductCategory.objects.filter(parent__isnull=True)
    
    if depth is not None:
        queryset = queryset.filter(level__lt=depth)
    
    if include_products:
        queryset = queryset.prefetch_related(
            Prefetch('products',
                   queryset=Product.objects.filter(is_active=True)
                   .only('id', 'name', 'slug', 'final_price', 'primary_image'))
        )
    
    return list(queryset.prefetch_related(
        Prefetch('children',
               queryset=ProductCategory.objects.all()
               .annotate(product_count=Count('products', filter=Q(products__is_active=True))))
    ))

def get_category_with_children(category_id: int) -> Optional[ProductCategory]:
    """
    Get single category with its immediate children
    
    Args:
        category_id: ID of the parent category
        
    Returns:
        Category instance with prefetched children or None
    """
    return ProductCategory.objects.filter(
        pk=category_id
    ).prefetch_related(
        'children'
    ).annotate(
        product_count=Count('products', filter=Q(products__is_active=True))
    ).first()

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

def get_featured_categories(limit: int = 5) -> List[ProductCategory]:
    """
    Get categories with the most active products
    
    Args:
        limit: Number of categories to return
        
    Returns:
        List of categories ordered by product count
    """
    return list(ProductCategory.objects.annotate(
        active_products=Count('products', filter=Q(products__is_active=True))
    ).filter(
        active_products__gt=0
    ).order_by(
        '-active_products'
    )[:limit])

def get_category_path(slug: str) -> List[ProductCategory]:
    """
    Get breadcrumb path for a category
    
    Args:
        slug: Category slug
        
    Returns:
        Ordered list from root to target category
    """
    category = ProductCategory.objects.filter(slug=slug).first()
    if not category:
        return []
    
    return list(category.get_ancestors(include_self=True))

def get_category_products(category_id: int, *, only_featured: bool = False) -> List[Product]:
    """
    Get products for a category with optional filtering
    
    Args:
        category_id: ID of the category
        only_featured: Only include featured products
        
    Returns:
        List of Product instances
    """
    base_qs = Product.objects.filter(
        category_id=category_id,
        is_active=True
    ).select_related('category')
    
    if only_featured:
        base_qs = base_qs.filter(is_featured=True)
    
    return list(base_qs.order_by('-is_featured', 'name'))

def get_category_by_slug(slug: str) -> Optional[ProductCategory]:
    """
    Get category by slug with product count
    
    Args:
        slug: Category slug
        
    Returns:
        Category instance or None
    """
    return ProductCategory.objects.filter(
        slug=slug
    ).annotate(
        product_count=Count('products', filter=Q(products__is_active=True))
    ).first()